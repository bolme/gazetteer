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
