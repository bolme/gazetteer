"""Bounded directory walker — the one core primitive every command uses.

Every gaz command that touches the filesystem does so through this module.
It enforces two independent budgets — time and entry count — and handles
symlinks and permission errors uniformly. (--max-rows is a third budget,
but it bounds *output*, not the walk itself, so it's enforced by callers
slicing their result rows, not by walk().)

`exclude` patterns (matched against a directory's basename) are pruned
*before* descent: an excluded directory is never scanned, never counted
against n_dirs, never queued, and its contents never appear in
result.entries or count against max_entries/max_seconds. This is what
makes --exclude actually useful on a real tree — skipping a noisy
subtree (vendored dependencies, .git, a build cache) frees up budget for
directories that matter, rather than just filtering excluded entries out
of the output afterward.

Only max_seconds is on by default. max_entries defaults to 0 (unlimited):
on fast local storage there's no reason to cut a scan short on entry count
alone when there was plenty of time left, and the risk max_entries exists
to guard against — a single pathological directory eating the whole time
budget — is really a slow-storage problem, so it's opt-in rather than a
hidden ceiling everyone pays for. Pass 0 for max_seconds too to remove the
time budget entirely for a deliberate full-processing run; nothing about
gaz requires a prior scan or makes an unbounded run unsafe, it's just not
the default because most calls want a fast partial answer.

Traversal is breadth-first by default: on a truncated walk, BFS discovers
every top-level (and next-level, etc.) directory before going deep into
any one of them, so a partial result still shows the tree's overall shape
instead of exhaustively covering just the first subdirectory and missing
its siblings entirely. Pass depth_first=True for the old stack-based
behavior (complete coverage of the first branches, at the cost of breadth).
"""

from __future__ import annotations

import fnmatch
import os
import random
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class WalkEntry:
    path: str
    parent: str
    name: str
    is_dir: bool
    # Bytes actually allocated on disk (st_blocks * 512), which is what
    # `du` reports and what "where did my space go" means. For a sparse
    # file or a cloud placeholder this is far below `apparent_size`; see
    # _entry_size for why that's the default rather than st_size.
    size: int
    mtime: float
    # st_size: the length a program reading the file sees. Equal to `size`
    # for an ordinary file, wildly larger for a sparse/dataless one.
    apparent_size: int = 0
    # Creation time where the platform tracks it (st_birthtime on macOS/BSD),
    # falling back to st_ctime elsewhere — which is metadata-change time, not
    # creation. Named `ctime` rather than `created` so the fallback isn't
    # misrepresented as something stronger than it is; see entry_ctime.
    ctime: float = 0.0


def entry_ctime(stat_result: os.stat_result) -> float:
    """Best available creation time for a stat result.

    macOS/BSD expose a real creation time as st_birthtime; Linux does not,
    so st_ctime (inode-change time) is the closest stand-in. Callers that
    surface this to a user should say "created/changed," not "created."
    """
    return getattr(stat_result, "st_birthtime", stat_result.st_ctime)


def _entry_size(stat_result: os.stat_result) -> int:
    """Bytes this file actually occupies on disk.

    st_size is the file's *apparent* length, which for a sparse file (VM
    disk images, database preallocation) or a cloud-sync placeholder
    (iCloud/Dropbox dataless files) can be orders of magnitude larger than
    the space it consumes — a 100 GB VM image using 7 MB of real blocks is
    a real case, not a hypothetical. Since gaz exists to answer "what is
    using my disk," it reports allocated blocks like `du` does, and keeps
    st_size alongside as `apparent_size` for the questions where the
    logical length is the right answer.

    st_blocks is POSIX-only and counts 512-byte units by definition
    (independent of the filesystem's block size). Where it's unavailable
    (Windows), fall back to st_size — apparent and allocated size coincide
    there for ordinary files anyway.
    """
    blocks = getattr(stat_result, "st_blocks", None)
    if blocks is None:
        return stat_result.st_size
    return blocks * 512


@dataclass
class WalkResult:
    entries: list[WalkEntry] = field(default_factory=list)
    n_dirs: int = 0
    n_files: int = 0
    n_bytes: int = 0
    n_errors: int = 0
    elapsed: float = 0.0
    complete: bool = True
    stop_reason: str | None = None
    # Paths that were actually os.scandir'd — as opposed to paths merely
    # *discovered* as an entry of a scanned parent but never explored
    # themselves. On a truncated walk, a directory can only be confidently
    # called "empty" if it's in here; otherwise it's unvisited, not empty.
    scanned_dirs: set[str] = field(default_factory=set)


def walk(
    root: str,
    *,
    max_seconds: float = 30,
    max_entries: int = 0,
    max_depth: int | None = None,
    follow_symlinks: bool = False,
    cross_fs: bool = False,
    depth_first: bool = False,
    shuffle: bool = False,
    seed: int | None = None,
    exclude: tuple[str, ...] = (),
) -> WalkResult:
    """Walk `root` under explicit time/count/depth budgets.

    Uses os.scandir (not os.walk) so stat data comes free with the directory
    read. Stops as soon as any active budget is exhausted and reports why.

    max_seconds=0 and max_entries=0 both mean "no limit" (see module
    docstring for why max_entries defaults to unlimited while max_seconds
    doesn't). max_depth=None means no depth limit; unlike the other two,
    it's a scoping choice rather than a budget, so it has no "off" value
    to speak of — it's already off by default.

    Breadth-first by default (see module docstring for why); pass
    depth_first=True for the old stack-based order. shuffle=True randomizes
    each directory's entries before they're queued, so a truncated walk
    samples a different slice of a wide directory on each run — pass seed
    for a reproducible shuffle.

    exclude is a tuple of glob patterns matched against a directory's
    basename (e.g. "node_modules", ".git", ".*"). A matching directory is
    pruned before descent: it's never scanned, never appears in
    result.entries, and never counts against max_entries. The root itself
    is never excluded, even if its basename matches.
    """
    result = WalkResult()
    start = time.monotonic()
    root = os.path.abspath(root)
    rng = random.Random(seed) if shuffle else None

    def is_excluded(name: str) -> bool:
        return any(fnmatch.fnmatch(name, pattern) for pattern in exclude)

    def time_exceeded() -> bool:
        return max_seconds > 0 and time.monotonic() - start >= max_seconds

    def entries_exceeded() -> bool:
        return max_entries > 0 and result.n_dirs + result.n_files >= max_entries

    try:
        root_dev = os.stat(root).st_dev
    except OSError:
        result.n_errors += 1
        result.stop_reason = f"cannot stat root: {root}"
        result.complete = False
        result.elapsed = time.monotonic() - start
        return result

    # (dir_path, depth). depth_first pops from the right (LIFO stack);
    # breadth-first (default) pops from the left (FIFO queue).
    frontier: deque[tuple[str, int]] = deque([(root, 0)])
    visited_dirs: set[tuple[int, int]] = set()  # (st_dev, st_ino) for symlink-loop guard

    while frontier:
        if time_exceeded():
            result.complete = False
            result.stop_reason = f"{max_seconds}s limit"
            break
        if entries_exceeded():
            result.complete = False
            result.stop_reason = f"{max_entries} entries limit"
            break

        dir_path, depth = frontier.pop() if depth_first else frontier.popleft()

        try:
            dir_stat = os.stat(dir_path)
        except OSError:
            result.n_errors += 1
            continue

        dir_key = (dir_stat.st_dev, dir_stat.st_ino)
        if dir_key in visited_dirs:
            continue
        visited_dirs.add(dir_key)

        result.n_dirs += 1

        try:
            with os.scandir(dir_path) as it:
                scanned = list(it)
        except OSError:
            result.n_errors += 1
            continue

        if shuffle:
            rng.shuffle(scanned)

        for entry in scanned:
            if time_exceeded():
                result.complete = False
                result.stop_reason = f"{max_seconds}s limit"
                break
            if entries_exceeded():
                result.complete = False
                result.stop_reason = f"{max_entries} entries limit"
                break

            try:
                is_symlink = entry.is_symlink()
                is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
                stat_result = entry.stat(follow_symlinks=follow_symlinks)
            except OSError:
                result.n_errors += 1
                continue

            if is_symlink and not follow_symlinks:
                # Record as a leaf entry, but never descend into it.
                result.entries.append(
                    WalkEntry(
                        path=entry.path,
                        parent=dir_path,
                        name=entry.name,
                        is_dir=False,
                        size=_entry_size(stat_result),
                        apparent_size=stat_result.st_size,
                        mtime=stat_result.st_mtime,
                        ctime=entry_ctime(stat_result),
                    )
                )
                result.n_files += 1
                continue

            if is_dir:
                if is_excluded(entry.name):
                    continue
                result.entries.append(
                    WalkEntry(
                        path=entry.path,
                        parent=dir_path,
                        name=entry.name,
                        is_dir=True,
                        size=0,
                        mtime=stat_result.st_mtime,
                        ctime=entry_ctime(stat_result),
                    )
                )
                if not cross_fs and stat_result.st_dev != root_dev:
                    continue
                if max_depth is None or depth < max_depth:
                    frontier.append((entry.path, depth + 1))
            else:
                result.entries.append(
                    WalkEntry(
                        path=entry.path,
                        parent=dir_path,
                        name=entry.name,
                        is_dir=False,
                        size=_entry_size(stat_result),
                        apparent_size=stat_result.st_size,
                        mtime=stat_result.st_mtime,
                        ctime=entry_ctime(stat_result),
                    )
                )
                result.n_files += 1
                result.n_bytes += _entry_size(stat_result)
        else:
            # Only reached if the for-loop above ran to completion without
            # `break`ing on a budget check — i.e. every entry in this
            # directory was actually processed, not just some of them.
            result.scanned_dirs.add(dir_path)

    result.elapsed = time.monotonic() - start
    return result
