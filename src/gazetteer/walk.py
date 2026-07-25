"""Bounded directory walker — the one core primitive every command uses.

Every gaz command that touches the filesystem does so through this module.
It enforces the three independent budgets (time, entries, rows are enforced
by callers) and handles symlinks and permission errors uniformly.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field


@dataclass
class WalkEntry:
    path: str
    parent: str
    name: str
    is_dir: bool
    size: int
    mtime: float


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


def walk(
    root: str,
    *,
    max_seconds: float = 30,
    max_entries: int = 1_000_000,
    max_depth: int | None = None,
    follow_symlinks: bool = False,
    cross_fs: bool = False,
) -> WalkResult:
    """Walk `root` under explicit time/count/depth budgets.

    Uses os.scandir (not os.walk) so stat data comes free with the directory
    read. Stops as soon as any budget is exhausted and reports why.
    """
    result = WalkResult()
    start = time.monotonic()
    root = os.path.abspath(root)

    try:
        root_dev = os.stat(root).st_dev
    except OSError:
        result.n_errors += 1
        result.stop_reason = f"cannot stat root: {root}"
        result.complete = False
        result.elapsed = time.monotonic() - start
        return result

    # (root_path, depth)
    stack: list[tuple[str, int]] = [(root, 0)]
    visited_dirs: set[tuple[int, int]] = set()  # (st_dev, st_ino) for symlink-loop guard

    while stack:
        if time.monotonic() - start >= max_seconds:
            result.complete = False
            result.stop_reason = f"{max_seconds}s limit"
            break
        if result.n_dirs + result.n_files >= max_entries:
            result.complete = False
            result.stop_reason = f"{max_entries} entries limit"
            break

        dir_path, depth = stack.pop()

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
                for entry in it:
                    if time.monotonic() - start >= max_seconds:
                        result.complete = False
                        result.stop_reason = f"{max_seconds}s limit"
                        break
                    if result.n_dirs + result.n_files >= max_entries:
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
                                size=stat_result.st_size,
                                mtime=stat_result.st_mtime,
                            )
                        )
                        result.n_files += 1
                        continue

                    if is_dir:
                        result.entries.append(
                            WalkEntry(
                                path=entry.path,
                                parent=dir_path,
                                name=entry.name,
                                is_dir=True,
                                size=0,
                                mtime=stat_result.st_mtime,
                            )
                        )
                        if not cross_fs and stat_result.st_dev != root_dev:
                            continue
                        if max_depth is None or depth < max_depth:
                            stack.append((entry.path, depth + 1))
                    else:
                        result.entries.append(
                            WalkEntry(
                                path=entry.path,
                                parent=dir_path,
                                name=entry.name,
                                is_dir=False,
                                size=stat_result.st_size,
                                mtime=stat_result.st_mtime,
                            )
                        )
                        result.n_files += 1
                        result.n_bytes += stat_result.st_size
        except OSError:
            result.n_errors += 1
            continue

    result.elapsed = time.monotonic() - start
    return result
