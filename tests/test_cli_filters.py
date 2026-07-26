from click.testing import CliRunner

from gazetteer.cli import main


def _make_tree(tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("xx")
    (tmp_path / "c.txt").write_text("xxx")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.py").write_text("xxxx")


def test_ext_filters_by_extension(tmp_path):
    _make_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["ext", str(tmp_path), "--ext", ".py"])

    assert result.exit_code == 0
    assert ".py" in result.output
    assert ".txt" not in result.output


def test_ext_accepts_extension_without_dot(tmp_path):
    _make_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["ext", str(tmp_path), "--ext", "txt"])

    assert result.exit_code == 0
    assert ".txt" in result.output
    assert ".py" not in result.output


def test_tree_filters_by_pattern(tmp_path):
    _make_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["tree", str(tmp_path), "--pattern", "*.py"])

    assert result.exit_code == 0
    assert "Total (matching filter): " in result.output
    assert "3 files" in result.output


def test_find_narrows_with_ext(tmp_path):
    _make_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["find", "*", str(tmp_path), "--ext", ".py"])

    assert result.exit_code == 0
    assert "a.py" in result.output
    assert "c.txt" not in result.output


def _make_size_tree(tmp_path):
    (tmp_path / "small.bin").write_bytes(b"x" * 100)
    (tmp_path / "medium.bin").write_bytes(b"x" * 5_000)
    (tmp_path / "large.bin").write_bytes(b"x" * 2_000_000)


def test_find_filters_by_min_size(tmp_path):
    _make_size_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["find", "*", str(tmp_path), "--size", ">1k"])

    assert result.exit_code == 0
    assert "small.bin" not in result.output
    assert "medium.bin" in result.output
    assert "large.bin" in result.output


def test_find_filters_by_size_range(tmp_path):
    _make_size_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main, ["find", "*", str(tmp_path), "--size", ">1k", "--size", "<1M"]
    )

    assert result.exit_code == 0
    assert "small.bin" not in result.output
    assert "medium.bin" in result.output
    assert "large.bin" not in result.output


def test_find_rejects_invalid_size(tmp_path):
    _make_size_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["find", "*", str(tmp_path), "--size", "bogus"])

    assert result.exit_code != 0
    assert "invalid size" in result.output


def _make_vendored_tree(tmp_path):
    (tmp_path / "src.py").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("xx")
    (tmp_path / "node_modules" / "sub").mkdir()
    (tmp_path / "node_modules" / "sub" / "nested.js").write_text("xxx")


def test_ext_exclude_prunes_matching_directory(tmp_path):
    _make_vendored_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["ext", str(tmp_path), "--exclude", "node_modules"])

    assert result.exit_code == 0
    assert ".js" not in result.output
    assert "Total: 1 files" in result.output


def test_find_exclude_is_repeatable(tmp_path):
    _make_vendored_tree(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["find", "*", str(tmp_path), "--exclude", "node_modules", "--exclude", ".git"],
    )

    assert result.exit_code == 0
    assert "node_modules" not in result.output
    assert ".git" not in result.output
    assert "src.py" in result.output


def test_exclude_does_not_count_excluded_entries_against_max_entries(tmp_path):
    _make_vendored_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["ext", str(tmp_path), "--exclude", "node_modules", "--max-entries", "2"],
    )

    assert result.exit_code == 0
    assert "Complete." in result.output
