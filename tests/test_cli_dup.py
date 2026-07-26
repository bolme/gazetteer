from click.testing import CliRunner

from gazetteer.cli import main


def test_dup_finds_duplicate_content(tmp_path):
    (tmp_path / "a.txt").write_text("same content")
    (tmp_path / "b.txt").write_text("same content")
    (tmp_path / "c.txt").write_text("different content entirely")

    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: 1 duplicate sets" in result.output
    assert "copies" in result.output


def test_dup_ignores_files_with_no_duplicates(tmp_path):
    (tmp_path / "a.txt").write_text("unique a")
    (tmp_path / "b.txt").write_text("unique b")

    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: 0 duplicate sets" in result.output


def test_dup_respects_size_filter(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path), "--size", ">100"])

    assert result.exit_code == 0
    assert "Total: 0 duplicate sets" in result.output


def test_dup_reports_hash_truncation(tmp_path):
    (tmp_path / "a.txt").write_text("same content")
    (tmp_path / "b.txt").write_text("same content")

    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path), "--max-hash-seconds", "0"])

    assert result.exit_code == 0
    assert "lower bound" in result.output


def _make_vendored_dup_tree(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("same content")
    (tmp_path / "node_modules" / "y.js").write_text("same content")
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.txt").write_text("same content")
    (tmp_path / "real" / "b.txt").write_text("same content")


def test_dup_without_skip_vendored_counts_everything(tmp_path):
    _make_vendored_dup_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: 1 duplicate sets" in result.output
    assert "Hashed 4 candidate files" in result.output


def test_dup_skip_vendored_excludes_node_modules(tmp_path):
    _make_vendored_dup_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path), "--skip-vendored"])

    assert result.exit_code == 0
    assert "node_modules" not in result.output
    assert "Total: 1 duplicate sets" in result.output
    assert "Hashed 2 candidate files" in result.output


def test_dup_skip_vendored_combines_with_explicit_exclude(tmp_path):
    _make_vendored_dup_tree(tmp_path)
    (tmp_path / "real" / "c.txt").write_text("same content")
    runner = CliRunner()
    result = runner.invoke(
        main, ["dup", str(tmp_path), "--skip-vendored", "--exclude", "real"]
    )

    assert result.exit_code == 0
    assert "Total: 0 duplicate sets" in result.output
