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
