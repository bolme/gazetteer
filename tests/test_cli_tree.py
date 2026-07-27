from click.testing import CliRunner

from gazetteer.cli import main


def _make_nested_tree(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "c").mkdir()
    (tmp_path / "a" / "f1.txt").write_text("x")
    (tmp_path / "a" / "b" / "f2.txt").write_text("x")
    (tmp_path / "c" / "f3.txt").write_text("x")


def test_tree_default_shows_direct_children_only(tmp_path):
    _make_nested_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["tree", str(tmp_path)])

    assert result.exit_code == 0
    lines = {line.split()[0]: line for line in result.output.splitlines() if str(tmp_path) in line}
    a_line = next(v for k, v in lines.items() if k.endswith("/a"))
    assert " 1 " in a_line  # only f1.txt, not b/f2.txt
    root_dir = str(tmp_path)
    assert not any(k == root_dir for k in lines)  # root has no direct files


def test_tree_recursive_rolls_up_subtree_totals(tmp_path):
    _make_nested_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["tree", str(tmp_path), "--recursive"])

    assert result.exit_code == 0
    lines = {line.split()[0]: line for line in result.output.splitlines() if str(tmp_path) in line}

    root_line = lines[str(tmp_path)]
    assert " 3 " in root_line  # all three files roll up to root

    a_line = next(v for k, v in lines.items() if k.endswith(f"{tmp_path.name}/a"))
    assert " 2 " in a_line  # f1.txt + b/f2.txt

    b_line = next(v for k, v in lines.items() if k.endswith("/a/b"))
    assert " 1 " in b_line  # just f2.txt, it's a leaf

    c_line = next(v for k, v in lines.items() if k.endswith(f"{tmp_path.name}/c"))
    assert " 1 " in c_line


def test_tree_recursive_respects_filters(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "a" / "keep.txt").write_text("x")
    (tmp_path / "a" / "b" / "skip.jpg").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["tree", str(tmp_path), "--recursive", "--ext", ".txt"])

    assert result.exit_code == 0
    lines = {line.split()[0]: line for line in result.output.splitlines() if str(tmp_path) in line}
    a_line = next(v for k, v in lines.items() if k.endswith(f"{tmp_path.name}/a"))
    assert " 1 " in a_line  # only keep.txt counted, skip.jpg filtered out


def test_tree_recursive_total_line_unaffected(tmp_path):
    _make_nested_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["tree", str(tmp_path), "--recursive"])

    assert result.exit_code == 0
    assert "Total: 4 dirs, 3 files" in result.output
