"""Frontier-based adaptive sampling — scan each directory at most once.

Powers `gaz sample`. See docs/sample-estimation.md for the user-facing
explanation, the bias mechanism this module works around, the
identity-vs-equality bug fixed below, and known gaps — this docstring
only covers the mechanics; that document covers the *why* in more depth,
with the empirical evidence behind it. estimate.py implements a
different, unshipped algorithm (weighted random descent) considered as
an alternative — see that module and the same doc for the comparison.

## The algorithm

Maintain a **frontier** of directories that have been discovered (seen as
a child in some scanned directory's listing) but not yet scanned
themselves, and a **memo** of every directory already scanned. Repeatedly
pop a directory from the frontier and descend from it — scanning every
directory visited along the way exactly once, ever — until reaching a
directory with no subdirectories of its own. A directory's own files are
counted exactly the moment it's scanned (their sizes are read directly,
not estimated). A directory's *subtree* total, while its descendants are
still only partially scanned, is estimated recursively:

    subtree_estimate(D) = own_file_bytes(D)
        + n_subdirs(D) * weighted_mean(subtree_estimate(child) for child in scanned children of D)

where the mean is weighted by each child's own `completeness` (fraction
of its own subtree scanned so far) rather than an unweighted average: a
child that's barely been explored contributes less to its parent's
estimate than one that's mostly or fully resolved, instead of both
counting equally. This reduces, but does not eliminate, a real bias this
formula has at partial coverage — see docs/sample-estimation.md's
mechanism section. `_estimate` additionally clamps its result to never
fall below `_lower_bound` at every level of the recursion, fixing a case
where the weighted mean alone could dip below what was already counted
for certain.

Frontier/memo membership is keyed by identity — `(st_dev, st_ino)`,
mirroring the same key walk.py uses for its symlink-loop guard — never
by path string or value equality; see docs/sample-estimation.md for the
bug this avoids (two unrelated but field-identical directories getting
confused).

`run()` is bounded by `max_seconds` (matching every other gaz command's
budget convention) with an optional `max_scans` secondary cap, and is
**resumable**: calling it again on the same `FrontierSampler` (same
root) continues from wherever the frontier was left rather than
restarting, which is what lets `gaz sample` give every subdirectory a
small first-pass budget and then round-robin additional budget only to
the ones still incomplete — see cli.py's `sample` command.

## Why three numbers, not one

A single point estimate is not an honest thing to report on its own,
given the bias above. Every `SampleResult` carries three instead:

- `exact`: True if this directory's entire subtree was scanned (the
  frontier under it fully drained within budget). When True,
  `lower_bound` and `estimate` both equal the true total exactly.
- `lower_bound`: the sum of every file byte actually counted so far.
  Always a true floor — never an extrapolation — the same "honest
  partial coverage" contract every other bounded gaz command already
  makes (see walk.py's module docstring).
- `estimate`: the completeness-weighted recursive extrapolation above.
  This is the number that can be biased; it is always reported
  *alongside* `lower_bound` and `exact`, never as a bare number, so a
  caller always has the true floor next to the rough guess.

Beyond bytes/files/dirs, this module also tracks a per-directory
extension breakdown, per-owner (uid) breakdown, newest-mtime, and a
permission-denied count, all recursing through `_lower_bound` the same
way byte/file/dir totals do — see each field's docstring on
`SampleResult` for why these are always exact tallies, never estimated.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field

from gazetteer.report import extension_of
from gazetteer.walk import entry_size


def _add_counts(totals: dict, counts: dict) -> None:
    """totals[k] += v for every k, v in counts, in place."""
    for key, value in counts.items():
        totals[key] = totals.get(key, 0) + value


@dataclass
class DirRecord:
    """Per-directory bookkeeping the estimator accumulates as it scans."""

    own_bytes: int = 0
    own_files: int = 0
    own_dirs: int = 0
    own_ext_bytes: dict[str, int] = field(default_factory=dict)
    own_ext_files: dict[str, int] = field(default_factory=dict)
    own_owner_bytes: dict[int, int] = field(default_factory=dict)
    own_owner_files: dict[int, int] = field(default_factory=dict)
    newest_mtime: float | None = None
    subdirs: list[str] = field(default_factory=list)
    scanned: bool = False
    # True if scanning THIS directory itself failed with any OSError
    # (permission denied, vanished mid-scan) -- only read once, right
    # after adapter.scan() returns, to bump the sampler's n_errors.
    own_errored: bool = False
    # 1 if scanning THIS directory itself failed with PermissionError, 0
    # otherwise -- one scan attempt, so never more than 1 per DirRecord.
    # Recurses through _lower_bound the same way own_dirs does, so a
    # parent's total reflects every permission-denied directory anywhere
    # in its subtree, not just its own immediate children.
    own_denied: int = 0


class FilesystemAdapter:
    """Scans real directories via os.scandir. One scandir call per
    directory, ever, is the whole point of this algorithm — see the
    module docstring."""

    def scan(self, path: str) -> DirRecord:
        record = DirRecord(scanned=True)
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        is_symlink = entry.is_symlink()
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir and not is_symlink:
                        record.subdirs.append(entry.path)
                        record.own_dirs += 1
                        continue
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    record.own_files += 1
                    size = entry_size(stat_result)
                    record.own_bytes += size
                    ext = extension_of(entry.name)
                    record.own_ext_bytes[ext] = record.own_ext_bytes.get(ext, 0) + size
                    record.own_ext_files[ext] = record.own_ext_files.get(ext, 0) + 1
                    uid = stat_result.st_uid
                    record.own_owner_bytes[uid] = record.own_owner_bytes.get(uid, 0) + size
                    record.own_owner_files[uid] = record.own_owner_files.get(uid, 0) + 1
                    if (
                        record.newest_mtime is None
                        or stat_result.st_mtime > record.newest_mtime
                    ):
                        record.newest_mtime = stat_result.st_mtime
        except OSError as e:
            # Permission denied or the directory vanished mid-scan: treat
            # it as scanned-but-empty, same as walk.py's n_errors handling
            # — a directory gaz can't read contributes nothing rather than
            # crashing the whole sample. Flagged so the caller can still
            # count how many directories this happened to, and whether it
            # was specifically a permission problem (see `denied` on
            # SampleResult) as opposed to some other OSError.
            return DirRecord(
                scanned=True,
                own_errored=True,
                own_denied=1 if isinstance(e, PermissionError) else 0,
            )
        return record

    def identity(self, path: str) -> object:
        """A stable key for "is this the same directory," robust to two
        different paths naming the same directory (bind mount, symlink)
        and to two different directories merely sharing a name — the
        exact confusion a value-equality key falls into (see
        docs/sample-estimation.md's correctness-trap section). Falls
        back to the path itself if the directory can't be stat'd (about
        to fail loudly elsewhere anyway)."""
        try:
            st = os.stat(path)
            return (st.st_dev, st.st_ino)
        except OSError:
            return path


@dataclass
class SampleResult:
    exact: bool
    lower_bound_bytes: int
    lower_bound_files: int
    lower_bound_dirs: int
    estimate_bytes: float
    estimate_files: float
    estimate_dirs: float
    # ext -> bytes/files, keyed the same way `gaz ext` normalizes
    # extensions (lowercased, "(none)" for no extension). Always an exact
    # tally of files actually scanned so far — never extrapolated, unlike
    # estimate_bytes/estimate_files, since a completeness-weighted guess
    # at an *unscanned* subdirectory's extension mix would be presenting
    # a much shakier statistical claim than "this subtree is probably
    # about this many bytes." A caller sees fewer files reflected here
    # than lower_bound_files claims exist only when coverage is partial —
    # same honesty contract as lower_bound_bytes/lower_bound_files.
    lower_bound_ext_bytes: dict[str, int]
    lower_bound_ext_files: dict[str, int]
    # uid -> bytes/files, same "exact tally of scanned files only, never
    # extrapolated" contract as the extension breakdown above, and for
    # the same reason.
    lower_bound_owner_bytes: dict[int, int]
    lower_bound_owner_files: dict[int, int]
    # Most recent mtime among every file actually scanned so far, or None
    # if none were scanned yet. Like the ext/owner breakdowns, this is
    # never estimated/extrapolated for unscanned subdirectories -- a
    # guess at "how recently touched is the part I haven't looked at
    # yet" has no principled basis the way a size/count extrapolation
    # does (nothing about a directory's known metadata predicts its
    # unscanned children's mtimes the way subdirectory COUNT predicts
    # their aggregate size).
    newest_mtime: float | None
    # Count of directories anywhere in this subtree that couldn't be
    # scanned because of PermissionError specifically (not any OSError —
    # a directory vanishing mid-scan doesn't count here). Recurses the
    # same way lower_bound_dirs does: a denied directory deep in the
    # tree is reflected in every ancestor's total, not just its own
    # parent's. Always exact, same as the ext/owner breakdowns.
    lower_bound_denied: int
    completeness: float  # fraction of discovered directories actually scanned
    n_scans: int
    n_errors: int
    elapsed: float
    stop_reason: str | None


@dataclass
class _LowerBoundTotals:
    """Internal accumulator for _lower_bound's recursive walk -- a
    dataclass rather than a growing tuple since this has picked up enough
    fields (bytes/files/dirs/ext/owner/mtime) that positional unpacking
    would be error-prone to read and to extend further."""

    bytes: int = 0
    files: int = 0
    dirs: int = 0
    ext_bytes: dict[str, int] = field(default_factory=dict)
    ext_files: dict[str, int] = field(default_factory=dict)
    owner_bytes: dict[int, int] = field(default_factory=dict)
    owner_files: dict[int, int] = field(default_factory=dict)
    newest_mtime: float | None = None
    denied: int = 0


class FrontierSampler:
    """Scans a single root's subtree via frontier-based adaptive sampling,
    reporting an exact total, a lower bound, and a completeness-weighted
    estimate — see the module docstring for what each of those means and
    why all three are reported rather than one number."""

    def __init__(self, adapter: FilesystemAdapter | None = None, *, seed: int | None = None):
        self.adapter = adapter or FilesystemAdapter()
        self.rng = random.Random(seed)
        self.records: dict[object, DirRecord] = {}
        self.n_errors = 0
        # Frontier state persists across run() calls so a sampler can be
        # resumed with more budget instead of restarting from the root —
        # see run()'s docstring. None until the first run() call sets it.
        self._root: str | None = None
        self._root_key: object | None = None
        self._frontier: list[str] = []
        self._frontier_keys: set[object] = set()

    def _scan_once(self, path: str, key: object) -> DirRecord:
        record = self.records.get(key)
        if record is not None and record.scanned:
            return record
        record = self.adapter.scan(path)
        if record.own_errored:
            self.n_errors += 1
        self.records[key] = record
        return record

    def _completeness(self, key: object) -> float:
        """Fraction of this directory's known subtree that's been scanned
        — 1.0 for a leaf or fully-drained subtree, lower for a directory
        with unscanned descendants still outstanding. Used to weight this
        directory's contribution to its *parent's* estimate (improvement
        6.1): a barely-explored child should count for less than a
        thoroughly-explored one, rather than both counting equally in a
        plain average — see the module docstring's mechanism note."""
        record = self.records.get(key)
        if record is None or not record.scanned:
            return 0.0
        if not record.subdirs:
            return 1.0
        child_completenesses = []
        for child_path in record.subdirs:
            child_key = self._key(child_path)
            child_completenesses.append(self._completeness(child_key))
        return sum(child_completenesses) / len(child_completenesses)

    def _key(self, path: str) -> object:
        return self.adapter.identity(path)

    def _estimate(self, path: str) -> tuple[float, float, float]:
        """(estimated_bytes, estimated_files, estimated_dirs) for path's
        subtree, using currently scanned descendants and completeness
        weighting. Extension breakdowns are NOT estimated this way — see
        SampleResult's docstring for why an exact-scanned-only tally is
        the more honest number for a distribution, versus a single
        scalar total."""
        key = self._key(path)
        record = self.records.get(key)
        if record is None or not record.scanned:
            return 0.0, 0.0, 0.0
        if not record.subdirs:
            return float(record.own_bytes), float(record.own_files), float(record.own_dirs)

        weighted_bytes = []
        weighted_files = []
        weighted_dirs = []
        weights = []
        for child_path in record.subdirs:
            child_key = self._key(child_path)
            child_record = self.records.get(child_key)
            if child_record is None or not child_record.scanned:
                continue
            completeness = self._completeness(child_key)
            child_bytes, child_files, child_dirs = self._estimate(child_path)
            # A weight of exactly 0 (child scanned but 0% of ITS
            # descendants resolved, i.e. we only know it exists) would
            # drop the child from the average entirely, which silently
            # throws away the one thing we do know for sure -- that
            # child's OWN files are exact regardless of its descendants'
            # completeness. Floor the weight so a freshly-scanned child
            # still counts, just less than a well-explored one.
            weight = max(completeness, 0.05)
            weighted_bytes.append(child_bytes * weight)
            weighted_files.append(child_files * weight)
            weighted_dirs.append(child_dirs * weight)
            weights.append(weight)

        if not weights:
            # No child has been scanned at all yet -- own totals are all
            # we know; report them as-is rather than guessing at
            # unresolved subdirectories with zero information. own_dirs
            # is exact regardless (scanning path already revealed every
            # immediate subdirectory), so it's never itself an estimate.
            return float(record.own_bytes), float(record.own_files), float(record.own_dirs)

        mean_bytes = sum(weighted_bytes) / sum(weights)
        mean_files = sum(weighted_files) / sum(weights)
        mean_dirs = sum(weighted_dirs) / sum(weights)
        n_subdirs = len(record.subdirs)
        est_bytes = record.own_bytes + n_subdirs * mean_bytes
        est_files = record.own_files + n_subdirs * mean_files
        est_dirs = record.own_dirs + n_subdirs * mean_dirs

        # The completeness-weighted mean can come out BELOW what's
        # already known for certain: a low-completeness child's own
        # estimate gets diluted toward the average of its siblings, but
        # that child's LOWER BOUND (bytes/files/dirs actually counted
        # inside it already) doesn't shrink just because the weighting
        # formula is unsure about it. Concretely: a directory with two
        # children -- one fully scanned and small, one 13%-scanned but
        # already containing more than the mean suggests -- can produce
        # a weighted mean pulled below the second child's own already-
        # counted total. Clamping against the lower bound here, at every
        # level of the recursion (not just the root), fixes it exactly
        # once: each level's own clamped estimate is what its parent
        # consumes as a child estimate, so a fix at the root alone
        # wouldn't help an ancestor two levels up unless every level
        # between them also flowed the clamp through.
        #
        # Cost note: this re-walks path's whole subtree at every level of
        # _estimate's own recursion, so total work is superlinear in the
        # number of scanned directories (measured: ~57ms at ~950 scanned
        # dirs). Deliberately left this way rather than threading a
        # precomputed totals map through the recursion -- current_result()
        # is called a small, fixed number of times per subdirectory (not
        # in a per-scan hot loop), so this has never been the bottleneck
        # in practice. Revisit only if profiling shows otherwise.
        totals = self._lower_bound(path)
        return (
            max(est_bytes, float(totals.bytes)),
            max(est_files, float(totals.files)),
            max(est_dirs, float(totals.dirs)),
        )

    def _lower_bound(self, path: str) -> _LowerBoundTotals:
        """Sum of every file/directory actually counted in path's subtree
        so far -- a true floor, never an extrapolation. Unlike _estimate,
        this only ever adds up real, scanned numbers."""
        key = self._key(path)
        record = self.records.get(key)
        if record is None or not record.scanned:
            return _LowerBoundTotals()
        totals = _LowerBoundTotals(
            bytes=record.own_bytes,
            files=record.own_files,
            dirs=record.own_dirs,
            ext_bytes=dict(record.own_ext_bytes),
            ext_files=dict(record.own_ext_files),
            owner_bytes=dict(record.own_owner_bytes),
            owner_files=dict(record.own_owner_files),
            newest_mtime=record.newest_mtime,
            denied=record.own_denied,
        )
        for child_path in record.subdirs:
            child = self._lower_bound(child_path)
            totals.bytes += child.bytes
            totals.files += child.files
            totals.dirs += child.dirs
            totals.denied += child.denied
            _add_counts(totals.ext_bytes, child.ext_bytes)
            _add_counts(totals.ext_files, child.ext_files)
            _add_counts(totals.owner_bytes, child.owner_bytes)
            _add_counts(totals.owner_files, child.owner_files)
            if child.newest_mtime is not None and (
                totals.newest_mtime is None or child.newest_mtime > totals.newest_mtime
            ):
                totals.newest_mtime = child.newest_mtime
        return totals

    def _is_fully_scanned(self, path: str) -> bool:
        key = self._key(path)
        record = self.records.get(key)
        if record is None or not record.scanned:
            return False
        return all(self._is_fully_scanned(c) for c in record.subdirs)

    def run(
        self,
        root: str,
        *,
        max_seconds: float = 10.0,
        max_scans: int = 0,
    ) -> SampleResult:
        """Scan root's subtree under an *additional* time and/or scan-count
        budget (0 means unlimited for either), returning an exact total if
        the frontier drains, else a lower bound and a completeness-weighted
        estimate. See the module docstring for what each field of
        SampleResult means.

        Calling run() again on the same sampler (same root) resumes from
        wherever the frontier was left, rather than restarting the scan —
        this is what lets a caller give a directory a small budget, move
        on to other directories, and come back later to extend it with
        more budget without losing or repeating any work already done.
        Pass a different root to start a fresh, independent scan (the
        memo and frontier from a prior root are dropped).
        """
        if root != self._root:
            self._root = root
            self._root_key = self._key(root)
            self._frontier = [root]
            self._frontier_keys = {self._root_key}
            self.records = {}
            self.n_errors = 0

        start = time.monotonic()
        n_scans = 0
        stop_reason = None

        def time_exceeded() -> bool:
            return max_seconds > 0 and time.monotonic() - start >= max_seconds

        def scans_exceeded() -> bool:
            return max_scans > 0 and n_scans >= max_scans

        # Descend repeatedly, choosing a fresh frontier start whenever the
        # previous descent bottoms out at a leaf. `current` is deliberately
        # left IN the frontier until the instant just before it's actually
        # scanned: an earlier version removed a chosen node a step ahead
        # of scanning it, so a budget check landing between "removed" and
        # "scanned" could strand it in neither the frontier nor the memo,
        # silently orphaning that whole branch forever -- even across a
        # later run() call with unlimited remaining budget. Checking the
        # budget, THEN removing, THEN scanning, with nothing budget-gated
        # in between, closes that gap at both the outer (new descent) and
        # inner (continuing a descent) points where it can occur.
        current: str | None = None
        while current is not None or self._frontier:
            if current is None:
                idx = self.rng.randrange(len(self._frontier))
                current = self._frontier[idx]

            if time_exceeded():
                stop_reason = f"{max_seconds}s limit"
                break
            if scans_exceeded():
                stop_reason = f"{max_scans} scans limit"
                break

            current_key = self._key(current)
            self._frontier = [p for p in self._frontier if self._key(p) != current_key]
            self._frontier_keys.discard(current_key)

            record = self._scan_once(current, current_key)
            n_scans += 1
            for child_path in record.subdirs:
                child_key = self._key(child_path)
                if child_key not in self.records and child_key not in self._frontier_keys:
                    self._frontier.append(child_path)
                    self._frontier_keys.add(child_key)
            current = None if not record.subdirs else self.rng.choice(record.subdirs)

        return self._build_result(
            n_scans=n_scans,
            elapsed=time.monotonic() - start,
            stop_reason=stop_reason,
        )

    def _build_result(
        self, *, n_scans: int, elapsed: float, stop_reason: str | None
    ) -> SampleResult:
        root = self._root
        exact = self._is_fully_scanned(root)
        totals = self._lower_bound(root)
        if exact:
            estimate_bytes = float(totals.bytes)
            estimate_files = float(totals.files)
            estimate_dirs = float(totals.dirs)
        else:
            estimate_bytes, estimate_files, estimate_dirs = self._estimate(root)
        completeness = 1.0 if exact else self._completeness(self._root_key)

        return SampleResult(
            exact=exact,
            lower_bound_bytes=totals.bytes,
            lower_bound_files=totals.files,
            lower_bound_dirs=totals.dirs,
            estimate_bytes=estimate_bytes,
            estimate_files=estimate_files,
            estimate_dirs=estimate_dirs,
            lower_bound_ext_bytes=totals.ext_bytes,
            lower_bound_ext_files=totals.ext_files,
            lower_bound_owner_bytes=totals.owner_bytes,
            lower_bound_owner_files=totals.owner_files,
            newest_mtime=totals.newest_mtime,
            lower_bound_denied=totals.denied,
            completeness=completeness,
            n_scans=n_scans,
            n_errors=self.n_errors,
            elapsed=elapsed,
            stop_reason=stop_reason,
        )

    def current_result(self) -> SampleResult:
        """The SampleResult for whatever has been scanned so far, without
        doing any further scanning — used by a caller (like `gaz sample`'s
        round-robin scheduler) that wants each subdirectory's up-to-date
        result after every sampler has had a turn, not just after its own
        most recent run() call. Must be called after at least one run()."""
        if self._root is None:
            raise RuntimeError("current_result() called before any run()")
        return self._build_result(n_scans=0, elapsed=0.0, stop_reason=None)

    @property
    def is_exhausted(self) -> bool:
        """True once the frontier under the current root has fully
        drained — i.e. the most recent run() result was exact. Lets a
        caller doing round-robin scanning across many samplers skip ones
        that have nothing left to do without re-running an empty scan."""
        return self._root is not None and not self._frontier
