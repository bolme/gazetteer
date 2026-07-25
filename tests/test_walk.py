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
