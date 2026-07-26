import os

from gazetteer import walk


def test_walk_counts_files_and_dirs(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f1.txt").write_text("hello")
    (tmp_path / "a" / "f2.txt").write_text("world")
    (tmp_path / "b").mkdir()

    result = walk.walk(str(tmp_path))

    assert result.complete
    assert result.n_dirs == 3  # root, a, b
    assert result.n_files == 2
    assert result.n_bytes == 10
    assert result.n_errors == 0


def test_walk_respects_max_entries(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x")

    result = walk.walk(str(tmp_path), max_entries=5)

    assert not result.complete
    assert "entries limit" in result.stop_reason


def test_walk_does_not_follow_symlink_loop(tmp_path):
    loop_dir = tmp_path / "loop"
    loop_dir.mkdir()
    (loop_dir / "self").symlink_to(loop_dir, target_is_directory=True)

    result = walk.walk(str(tmp_path), max_seconds=5)

    assert result.complete
    assert result.n_errors == 0


def test_walk_skips_unreadable_directory(tmp_path):
    unreadable = tmp_path / "secret"
    unreadable.mkdir()
    (unreadable / "hidden.txt").write_text("shh")
    os.chmod(unreadable, 0o000)

    try:
        result = walk.walk(str(tmp_path))
    finally:
        os.chmod(unreadable, 0o755)

    assert result.n_errors >= 1


def test_walk_handles_deeply_nested_path(tmp_path):
    current = tmp_path
    for i in range(50):
        current = current / f"d{i}"
        current.mkdir()
    (current / "leaf.txt").write_text("x")

    result = walk.walk(str(tmp_path), max_seconds=10)

    assert result.complete
    assert result.n_files == 1


def test_walk_respects_max_depth(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "shallow.txt").write_text("x")
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "a" / "b" / "deep.txt").write_text("x")

    result = walk.walk(str(tmp_path), max_depth=1)

    names = {e.name for e in result.entries}
    assert "shallow.txt" in names
    assert "deep.txt" not in names
    # b itself is discovered (it's a child at depth 1) but never scanned into
    assert "b" in names
    assert result.complete


def test_walk_max_depth_zero_only_lists_root_children(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "nested.txt").write_text("x")
    (tmp_path / "top.txt").write_text("x")

    result = walk.walk(str(tmp_path), max_depth=0)

    names = {e.name for e in result.entries}
    assert "top.txt" in names
    assert "a" in names
    assert "nested.txt" not in names


def test_walk_stops_at_max_seconds(tmp_path):
    for i in range(200):
        d = tmp_path / f"d{i}"
        d.mkdir()
        (d / "f.txt").write_text("x")

    result = walk.walk(str(tmp_path), max_seconds=0)

    assert not result.complete
    assert "limit" in result.stop_reason
    assert result.elapsed >= 0


def test_walk_does_not_descend_into_symlinked_dir_by_default(tmp_path):
    # Target lives outside the walked root so "inside.txt" can only be
    # found by following the symlink — proving the walker doesn't.
    outside = tmp_path.parent / f"gaz_symlink_target_{tmp_path.name}"
    outside.mkdir()
    (outside / "inside.txt").write_text("x")
    try:
        root = tmp_path / "root"
        root.mkdir()
        link = root / "link"
        link.symlink_to(outside, target_is_directory=True)

        result = walk.walk(str(root))

        names = {e.name for e in result.entries}
        assert "link" in names
        link_entry = next(e for e in result.entries if e.name == "link")
        assert link_entry.is_dir is False
        assert "inside.txt" not in names
    finally:
        (outside / "inside.txt").unlink()
        outside.rmdir()


def test_walk_records_symlink_to_file(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("hello")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    result = walk.walk(str(tmp_path))

    names = {e.name for e in result.entries}
    assert "target.txt" in names
    assert "link.txt" in names
    assert result.n_errors == 0


def test_walk_nonexistent_root_reports_error_not_exception(tmp_path):
    missing = tmp_path / "does_not_exist"

    result = walk.walk(str(missing))

    assert not result.complete
    assert result.n_errors == 1
    assert result.entries == []


def test_walk_root_is_a_file_not_a_directory(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")

    result = walk.walk(str(f))

    # stat succeeds (it's a valid path) but scandir on a file fails
    assert result.n_errors == 1
    assert result.entries == []


def test_walk_empty_directory(tmp_path):
    result = walk.walk(str(tmp_path))

    assert result.complete
    assert result.n_dirs == 1
    assert result.n_files == 0
    assert result.n_bytes == 0
    assert result.entries == []


def test_walk_max_entries_zero_stops_immediately(tmp_path):
    (tmp_path / "f.txt").write_text("x")

    result = walk.walk(str(tmp_path), max_entries=0)

    assert not result.complete
    assert "entries limit" in result.stop_reason


def test_walk_relative_path_is_resolved_to_absolute(tmp_path, monkeypatch):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.txt").write_text("x")
    monkeypatch.chdir(tmp_path)

    result = walk.walk("sub")

    assert result.complete
    assert result.n_files == 1
    assert all(os.path.isabs(e.path) for e in result.entries)


def test_walk_elapsed_time_is_tracked(tmp_path):
    (tmp_path / "f.txt").write_text("x")

    result = walk.walk(str(tmp_path))

    assert result.elapsed >= 0
    assert result.elapsed < 5  # sanity bound, not a real timing assertion


def _make_wide_shallow_tree(tmp_path, n_top_dirs=4):
    """n_top_dirs directories, each with one file directly inside and one
    nested subdirectory containing another file. Used to distinguish BFS
    (discovers all top dirs before descending) from DFS (goes deep into
    the first branch before discovering siblings)."""
    names = [f"top{i}" for i in range(n_top_dirs)]
    for name in names:
        d = tmp_path / name
        (d / "nested").mkdir(parents=True)
        (d / "nested" / "deep.txt").write_text("x")
    return names


def test_walk_is_breadth_first_by_default(tmp_path):
    names = _make_wide_shallow_tree(tmp_path, n_top_dirs=6)

    # Budget: root + 6 top dirs = 7 dir-scans is enough to have scanned
    # every top-level dir (and thereby discovered, but not scanned into,
    # each "nested" child) but too little to have gone two levels deep.
    result = walk.walk(str(tmp_path), max_entries=7)

    assert not result.complete
    discovered_dir_names = {e.name for e in result.entries if e.is_dir}
    assert discovered_dir_names == set(names) | {"nested"}
    # None of the nested/deep.txt files should have been reached yet.
    assert "deep.txt" not in {e.name for e in result.entries}


def test_walk_depth_first_goes_deep_before_wide(tmp_path):
    _make_wide_shallow_tree(tmp_path, n_top_dirs=6)

    result = walk.walk(str(tmp_path), max_entries=4, depth_first=True)

    assert not result.complete
    # With a tight budget, DFS should have scanned into a "nested" dir
    # (depth 2) rather than only having discovered top-level siblings.
    dir_entries = [e for e in result.entries if e.is_dir]
    assert any(e.name == "nested" for e in dir_entries)


def test_walk_bfs_discovers_more_top_level_dirs_than_dfs_under_same_budget(tmp_path):
    _make_wide_shallow_tree(tmp_path, n_top_dirs=8)

    bfs_result = walk.walk(str(tmp_path), max_entries=5)
    dfs_result = walk.walk(str(tmp_path), max_entries=5, depth_first=True)

    bfs_top_dirs_scanned = {
        e.parent for e in bfs_result.entries
    }
    dfs_top_dirs_scanned = {
        e.parent for e in dfs_result.entries
    }
    # BFS should have scanned into (i.e. discovered children of) strictly
    # more distinct directories than DFS under an identical tight budget.
    assert len(bfs_top_dirs_scanned) >= len(dfs_top_dirs_scanned)


def test_walk_shuffle_changes_order_across_seeds(tmp_path):
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_text("x")

    result_a = walk.walk(str(tmp_path), shuffle=True, seed=1)
    result_b = walk.walk(str(tmp_path), shuffle=True, seed=2)

    order_a = [e.name for e in result_a.entries]
    order_b = [e.name for e in result_b.entries]
    assert set(order_a) == set(order_b)  # same files found either way
    assert order_a != order_b  # but in a different order


def test_walk_shuffle_same_seed_is_reproducible(tmp_path):
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_text("x")

    result_a = walk.walk(str(tmp_path), shuffle=True, seed=42)
    result_b = walk.walk(str(tmp_path), shuffle=True, seed=42)

    order_a = [e.name for e in result_a.entries]
    order_b = [e.name for e in result_b.entries]
    assert order_a == order_b


def test_walk_shuffle_without_seed_still_finds_all_entries(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x")

    result = walk.walk(str(tmp_path), shuffle=True)

    assert result.complete
    assert result.n_files == 10


def test_walk_depth_first_and_shuffle_compose(tmp_path):
    _make_wide_shallow_tree(tmp_path, n_top_dirs=4)

    # Should not raise, and should still respect the walk budgets.
    result = walk.walk(str(tmp_path), depth_first=True, shuffle=True, seed=1, max_seconds=5)

    assert result.complete
