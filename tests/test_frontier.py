"""Tests for gazetteer.frontier — the frontier-based adaptive sampler.

See docs/sample-estimation.md for the algorithm's design and the
bias/efficiency findings that motivate the exact/lower_bound/estimate
three-way split this module reports (rather than a single point
estimate). These tests build real directory trees under tmp_path (the
project's convention for walk.py tests too — see test_walk.py) rather
than mocks, since frontier.py's whole job is real os.scandir behavior,
identity handling, and error recovery.
"""

from __future__ import annotations

import os

from gazetteer import frontier


def _make_tree(tmp_path):
    """
    root/
      a/
        f1.txt (100 bytes)
        f2.txt (200 bytes)
        b/
          f3.txt (300 bytes)
      c/  (empty)
      top.txt (50 bytes)
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f1.txt").write_bytes(b"x" * 100)
    (tmp_path / "a" / "f2.txt").write_bytes(b"x" * 200)
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "a" / "b" / "f3.txt").write_bytes(b"x" * 300)
    (tmp_path / "c").mkdir()
    (tmp_path / "top.txt").write_bytes(b"x" * 50)
    return tmp_path


def test_full_scan_is_exact_and_matches_ground_truth(tmp_path):
    _make_tree(tmp_path)
    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.exact
    assert result.completeness == 1.0
    assert result.lower_bound_files == 4
    # Sizes are allocated blocks (see walk.py's _entry_size rationale),
    # so exact byte count depends on the filesystem's block size --
    # assert it's at least the apparent length, same invariant test_walk
    # uses.
    assert result.lower_bound_bytes >= 100 + 200 + 300 + 50
    # Exact means estimate and lower_bound must agree exactly -- no
    # daylight between "what we know" and "what we're guessing" once
    # coverage is complete.
    assert result.estimate_bytes == result.lower_bound_bytes
    assert result.estimate_files == result.lower_bound_files
    # 3 subdirectories anywhere beneath the tree: a, a/b, c.
    assert result.lower_bound_dirs == 3
    assert result.estimate_dirs == 3


def test_newest_mtime_reflects_most_recently_touched_file(tmp_path):
    _make_tree(tmp_path)
    older = (tmp_path / "a" / "f1.txt").stat().st_mtime
    newest = older + 1000
    os.utime(tmp_path / "a" / "b" / "f3.txt", (newest, newest))

    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.newest_mtime == newest


def test_newest_mtime_is_none_for_empty_tree(tmp_path):
    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.newest_mtime is None


def test_owner_breakdown_matches_ground_truth(tmp_path):
    _make_tree(tmp_path)
    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    my_uid = os.getuid()
    assert result.lower_bound_owner_files == {my_uid: 4}
    assert result.lower_bound_owner_bytes[my_uid] == result.lower_bound_bytes


def test_extension_breakdown_is_exact_and_matches_ground_truth(tmp_path):
    _make_tree(tmp_path)
    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    # 4 .txt files total (f1, f2, f3, top), no other extensions.
    assert result.lower_bound_ext_files == {".txt": 4}
    assert result.lower_bound_ext_bytes[".txt"] == result.lower_bound_bytes


def test_extension_breakdown_separates_multiple_extensions(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x" * 10)
    (tmp_path / "b.txt").write_bytes(b"x" * 20)
    (tmp_path / "c.json").write_bytes(b"x" * 30)
    (tmp_path / "noext").write_bytes(b"x" * 5)

    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.lower_bound_ext_files == {".txt": 2, ".json": 1, "(none)": 1}
    # .json's own bytes must be a distinct, correctly separated tally,
    # not merged with .txt's just because they share a parent directory.
    assert result.lower_bound_ext_bytes[".json"] < result.lower_bound_ext_bytes[".txt"]


def test_extension_breakdown_only_counts_scanned_files_not_estimated(tmp_path):
    """Per the design decision: extension breakdowns are an exact tally
    of scanned files only, never extrapolated the way estimate_bytes is
    -- a partial scan's ext dicts should sum to no more than
    lower_bound_files, never claim more than what was actually counted."""
    current = tmp_path / "big"
    current.mkdir()
    for i in range(5):
        current = current / f"d{i}"
        current.mkdir()
        (current / "f.txt").write_bytes(b"x" * 1000)

    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path / "big"), max_seconds=10, max_scans=2)

    assert not result.exact
    total_ext_files = sum(result.lower_bound_ext_files.values())
    assert total_ext_files == result.lower_bound_files
    assert total_ext_files < 5  # tree has 5 files total, scan was cut short


def test_full_scan_uses_no_redundant_scans(tmp_path):
    """Core promise of the algorithm: exactly one scandir per directory,
    ever. This tree has 4 directories (root, a, a/b, c)."""
    _make_tree(tmp_path)
    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.exact
    assert result.n_scans == 4


def test_partial_scan_reports_lower_bound_not_exact(tmp_path):
    _make_tree(tmp_path)
    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10, max_scans=1)

    assert not result.exact
    assert result.stop_reason == "1 scans limit"
    assert result.completeness < 1.0
    # A lower bound must never count more files than actually exist.
    assert result.lower_bound_files <= 4


def test_lower_bound_never_exceeds_estimate_when_incomplete(tmp_path):
    """The lower bound is always-true information; the estimate
    extrapolates beyond it. On an incomplete scan the estimate should be
    at least the lower bound (it can only ever add projected, unscanned
    mass on top, never subtract known bytes)."""
    _make_tree(tmp_path)
    sampler = frontier.FrontierSampler(seed=2)
    result = sampler.run(str(tmp_path), max_seconds=10, max_scans=1)

    assert result.estimate_bytes >= result.lower_bound_bytes
    assert result.estimate_files >= result.lower_bound_files


def test_estimate_never_falls_below_lower_bound_with_lopsided_children(tmp_path):
    """Regression test for a real bug: a directory with one fully-scanned
    small child and one large-but-mostly-unscanned child could produce a
    completeness-weighted mean pulled below the unscanned child's own
    already-counted total, because the low-completeness child's ESTIMATE
    (diluted toward the small sibling's value) was averaged in, rather
    than respecting that child's own LOWER BOUND as a floor. The
    invariant estimate >= lower_bound must hold at every level of the
    recursion, not just at the root, since a parent's mean consumes its
    children's estimates -- a violation two levels down silently
    corrupts every ancestor above it. This tree reproduces that shape:
    root has a tiny fully-scanned sibling and a wide, deep sibling that a
    tight scan cap only partially covers.
    """
    (tmp_path / "tiny").mkdir()
    (tmp_path / "tiny" / "f.txt").write_bytes(b"x")

    wide = tmp_path / "wide"
    wide.mkdir()
    for i in range(20):
        sub = wide / f"d{i}"
        sub.mkdir()
        for j in range(5):
            nested = sub / f"n{j}"
            nested.mkdir()
            (nested / "f.txt").write_bytes(b"x" * 100)

    sampler = frontier.FrontierSampler(seed=1)
    # Enough scans to fully resolve "tiny" and partially resolve "wide"
    # (which has 1 + 20 + 100 = 121 directories), landing in the exact
    # lopsided-completeness regime that triggered the bug.
    for _ in range(40):
        result = sampler.run(str(tmp_path), max_seconds=10, max_scans=3)
        if result.exact:
            break
        assert result.estimate_bytes >= result.lower_bound_bytes
        assert result.estimate_files >= result.lower_bound_files
        assert result.estimate_dirs >= result.lower_bound_dirs


def test_empty_directory_is_exact_and_zero(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(empty_dir), max_seconds=10)

    assert result.exact
    assert result.lower_bound_bytes == 0
    assert result.lower_bound_files == 0
    assert result.n_scans == 1


def test_single_file_directory_is_exact(tmp_path):
    (tmp_path / "only.txt").write_bytes(b"x" * 42)
    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.exact
    assert result.lower_bound_files == 1
    assert result.lower_bound_bytes >= 42


def test_unreadable_directory_counts_as_error_not_crash(tmp_path):
    (tmp_path / "visible.txt").write_bytes(b"x" * 10)
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "hidden.txt").write_bytes(b"x" * 999)
    os.chmod(secret, 0o000)

    try:
        sampler = frontier.FrontierSampler(seed=1)
        result = sampler.run(str(tmp_path), max_seconds=10)
    finally:
        os.chmod(secret, 0o755)

    assert result.n_errors >= 1
    # The visible file must still be counted despite the sibling error.
    assert result.lower_bound_files >= 1
    assert result.lower_bound_denied == 1


def test_denied_count_recurses_through_ancestors(tmp_path):
    """A permission-denied directory several levels deep must be
    reflected in every ancestor's lower_bound_denied, not just its
    immediate parent's -- same recursion contract as lower_bound_dirs."""
    nested = tmp_path / "a" / "b" / "secret"
    nested.mkdir(parents=True)
    (nested / "hidden.txt").write_bytes(b"x")
    os.chmod(nested, 0o000)

    try:
        sampler = frontier.FrontierSampler(seed=1)
        result = sampler.run(str(tmp_path), max_seconds=10)
    finally:
        os.chmod(nested, 0o755)

    assert result.lower_bound_denied == 1


def test_denied_count_is_zero_when_nothing_blocked(tmp_path):
    _make_tree(tmp_path)
    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.lower_bound_denied == 0


def test_denied_count_sums_multiple_blocked_directories(tmp_path):
    secret1 = tmp_path / "secret1"
    secret1.mkdir()
    secret2 = tmp_path / "sub" / "secret2"
    secret2.mkdir(parents=True)
    os.chmod(secret1, 0o000)
    os.chmod(secret2, 0o000)

    try:
        sampler = frontier.FrontierSampler(seed=1)
        result = sampler.run(str(tmp_path), max_seconds=10)
    finally:
        os.chmod(secret1, 0o755)
        os.chmod(secret2, 0o755)

    assert result.lower_bound_denied == 2


def test_deeply_nested_path_completes(tmp_path):
    current = tmp_path
    for i in range(30):
        current = current / f"d{i}"
        current.mkdir()
    (current / "leaf.txt").write_bytes(b"x" * 77)

    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.exact
    assert result.lower_bound_files == 1
    assert result.n_scans == 31  # 30 nested dirs + tmp_path itself


def test_identical_sibling_directories_are_not_confused(tmp_path):
    """Regression test for the bug documented in
    docs/sample-estimation.md's correctness-trap section: two structurally
    identical directories (same name, both empty) must both be scanned
    and counted independently, never treated as the same directory just
    because they'd compare equal under a naive value-based check."""
    for parent_name in ("p1", "p2"):
        parent = tmp_path / parent_name
        parent.mkdir()
        (parent / "d0").mkdir()  # identically-named empty dir in both

    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.exact
    # root, p1, p1/d0, p2, p2/d0 = 5 directories, each scanned once.
    assert result.n_scans == 5


def test_many_identically_shaped_leaf_dirs_all_counted(tmp_path):
    """Broader version of the sibling-confusion regression: many
    same-named, same-shaped empty directories scattered across different
    parents must each be independently accounted for."""
    for i in range(20):
        parent = tmp_path / f"parent{i}"
        parent.mkdir()
        (parent / "shared_name").mkdir()  # empty, same name every time
        (parent / "f.txt").write_bytes(b"x" * 10)

    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.exact
    assert result.lower_bound_files == 20
    # root + 20 parents + 20 "shared_name" dirs = 41
    assert result.n_scans == 41


def test_result_is_deterministic_given_a_seed(tmp_path):
    _make_tree(tmp_path)
    r1 = frontier.FrontierSampler(seed=42).run(str(tmp_path), max_seconds=10, max_scans=2)
    r2 = frontier.FrontierSampler(seed=42).run(str(tmp_path), max_seconds=10, max_scans=2)

    assert r1.lower_bound_bytes == r2.lower_bound_bytes
    assert r1.n_scans == r2.n_scans


def test_wide_directory_is_exact_and_counts_all_children(tmp_path):
    n = 200
    for i in range(n):
        (tmp_path / f"f{i}.txt").write_bytes(b"x")

    sampler = frontier.FrontierSampler(seed=1)
    result = sampler.run(str(tmp_path), max_seconds=10)

    assert result.exact
    assert result.lower_bound_files == n
    assert result.n_scans == 1


def test_run_resumes_instead_of_restarting(tmp_path):
    """Calling run() again on the same sampler (same root) with a fresh
    budget must continue from where the frontier was left, not restart
    the scan from the root -- this is what lets gaz sample give a
    directory a small first pass and top it up later without redoing or
    losing any work already done."""
    current = tmp_path / "big"
    current.mkdir()
    for i in range(8):
        current = current / f"d{i}"
        current.mkdir()
        (current / "f.txt").write_bytes(b"x" * 1000)

    sampler = frontier.FrontierSampler(seed=1)
    first = sampler.run(str(tmp_path / "big"), max_seconds=10, max_scans=2)
    assert not first.exact
    assert first.n_scans == 2

    second = sampler.run(str(tmp_path / "big"), max_seconds=10, max_scans=2)
    # Progress made in the second call should be strictly additional --
    # the memo from the first call must still be there, so the second
    # call's own n_scans is a fresh 2 (not re-counting the first call's),
    # while the sampler's cumulative lower_bound only grows or holds
    # steady, never resets or shrinks.
    assert second.n_scans == 2
    assert second.lower_bound_files >= first.lower_bound_files

    # Enough further calls should eventually drain the frontier and match
    # a fresh, one-shot full scan of the same tree exactly.
    result = second
    while not result.exact:
        result = sampler.run(str(tmp_path / "big"), max_seconds=10, max_scans=2)

    reference = frontier.FrontierSampler(seed=2).run(str(tmp_path / "big"), max_seconds=10)
    assert result.exact
    assert result.lower_bound_bytes == reference.lower_bound_bytes
    assert result.lower_bound_files == reference.lower_bound_files == 8


def test_resuming_a_single_branch_chain_never_stalls(tmp_path):
    """Regression test for a real bug found during development: a node
    chosen as the next descent step was removed from the frontier one
    iteration before it was actually scanned, so a budget check landing
    in between could strand it in neither the frontier nor the memo --
    permanently orphaning the rest of that branch even with unlimited
    future budget. A single-branch chain (each directory has exactly one
    subdirectory) is the case that exposes it: the frontier only ever
    holds at most one entry, so losing that one entry means the NEXT
    run() call has nothing to resume from and makes zero progress,
    forever, despite the tree being far from fully scanned."""
    current = tmp_path / "chain"
    current.mkdir()
    for i in range(10):
        current = current / f"d{i}"
        current.mkdir()
        (current / "f.txt").write_bytes(b"x" * 100)

    sampler = frontier.FrontierSampler(seed=3)
    total_scans = 0
    for _ in range(20):
        result = sampler.run(str(tmp_path / "chain"), max_seconds=10, max_scans=1)
        total_scans += result.n_scans
        if result.exact:
            break
        # Every call must make forward progress -- one scan, every time,
        # for as long as the tree isn't fully scanned yet. A stalled
        # sampler would report n_scans == 0 here forever.
        assert result.n_scans == 1

    assert result.exact
    assert result.lower_bound_files == 10


def test_is_exhausted_reflects_frontier_state(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.txt").write_bytes(b"x")

    sampler = frontier.FrontierSampler(seed=1)
    assert not sampler.is_exhausted  # no run() yet

    sampler.run(str(tmp_path / "a"), max_seconds=10, max_scans=1)
    assert sampler.is_exhausted  # one dir, one scan -- frontier drained

    fresh = frontier.FrontierSampler(seed=1)
    fresh.run(str(tmp_path), max_seconds=10, max_scans=0)
    assert fresh.is_exhausted
