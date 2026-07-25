from click.testing import CliRunner

from gazetteer.cli import main


def test_empty_finds_empty_directories(tmp_path):
    (tmp_path / "has_files").mkdir()
    (tmp_path / "has_files" / "f.txt").write_text("x")
    (tmp_path / "empty_dir").mkdir()
    (tmp_path / "nested" / "also_empty").mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(main, ["empty", str(tmp_path)])

    assert result.exit_code == 0
    assert "empty_dir" in result.output
    assert "also_empty" in result.output
    assert "has_files" not in result.output
    assert "Total: 3 empty directories" in result.output


def test_empty_dir_with_only_empty_subdirs_is_empty(tmp_path):
    (tmp_path / "parent" / "child").mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(main, ["empty", str(tmp_path)])

    assert result.exit_code == 0
    assert "parent" in result.output
    assert "child" in result.output


def test_empty_warns_when_walk_truncated(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["empty", str(tmp_path), "--max-entries", "1"])

    assert result.exit_code == 0
    assert "may simply be unvisited" in result.output
