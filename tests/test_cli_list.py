from click.testing import CliRunner

from gazetteer.cli import main


def _make_nested_tree(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "c").mkdir()
    (tmp_path / "a" / "f1.txt").write_text("x")
    (tmp_path / "a" / "b" / "f2.txt").write_text("x")
    (tmp_path / "c" / "f3.txt").write_text("x")


def _row(output, name):
    """The output line whose first column is `name`."""
    for line in output.splitlines():
        if line.split() and line.split()[0] == name:
            return line
    raise AssertionError(f"no row named {name!r} in:\n{output}")


def test_list_lists_only_direct_children(tmp_path):
    _make_nested_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path)])

    assert result.exit_code == 0
    # a/ and c/ are direct children; b/ is nested and must not be a row.
    _row(result.output, "a/")
    _row(result.output, "c/")
    assert "b/" not in result.output


def test_list_dir_totals_include_whole_subtree(tmp_path):
    _make_nested_tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path)])

    assert result.exit_code == 0
    # a/ holds f1.txt directly plus b/f2.txt nested beneath it.
    assert _row(result.output, "a/").split()[1] == "2"
    assert _row(result.output, "c/").split()[1] == "1"


def test_list_lists_files_alongside_directories(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("x")
    (tmp_path / "top.txt").write_text("hello")

    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path)])

    assert result.exit_code == 0
    # Files get a "-" count (a per-file count is meaningless) but a real
    # size. The size column is allocated blocks, so a 5-byte file shows as
    # one block rather than "5 B".
    top = _row(result.output, "top.txt")
    assert top.split()[1] == "-"
    assert "B" in top


def test_list_sorts_by_name_with_dirs_first(tmp_path):
    (tmp_path / "zdir").mkdir()
    (tmp_path / "zdir" / "f.txt").write_text("x")
    (tmp_path / "afile.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path)])

    assert result.exit_code == 0
    names = [
        line.split()[0]
        for line in result.output.splitlines()
        if line.split() and line.split()[0] in {"zdir/", "afile.txt"}
    ]
    assert names == ["zdir/", "afile.txt"]  # dir first despite z > a


def test_list_sort_by_size_is_largest_first(tmp_path):
    (tmp_path / "small").mkdir()
    (tmp_path / "small" / "s.txt").write_text("x")
    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "b.txt").write_text("x" * 5000)

    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path), "--sort", "size"])

    assert result.exit_code == 0
    names = [
        line.split()[0]
        for line in result.output.splitlines()
        if line.split() and line.split()[0] in {"big/", "small/"}
    ]
    assert names == ["big/", "small/"]


def test_list_reverse_flips_sort_order(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path), "--reverse"])

    assert result.exit_code == 0
    names = [
        line.split()[0]
        for line in result.output.splitlines()
        if line.split() and line.split()[0] in {"a.txt", "b.txt"}
    ]
    assert names == ["b.txt", "a.txt"]


def test_list_full_paths_flag(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.txt").write_text("x")

    runner = CliRunner()
    default = runner.invoke(main, ["list", str(tmp_path)])
    full = runner.invoke(main, ["list", str(tmp_path), "-P"])

    assert default.exit_code == 0 and full.exit_code == 0
    # Default shows a bare name; -P shows a resolved absolute path.
    assert _row(default.output, "sub/")
    import os

    assert os.path.realpath(str(tmp_path / "sub")) in full.output


def test_list_full_paths_distinguishes_a_symlink_from_its_target(tmp_path):
    # -P resolves symlinks, so a link and the directory it points at would
    # otherwise print as two identical rows — the link must stay visible.
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "f.txt").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "real")

    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path), "-P"])

    assert result.exit_code == 0
    assert "link -> " in result.output
    path_cells = [
        line.split()[0] for line in result.output.splitlines() if "/" in line
    ]
    assert len(path_cells) == len(set(path_cells))  # no duplicate rows


def test_list_fields_adds_optional_columns(tmp_path):
    (tmp_path / "sub" / "deep").mkdir(parents=True)
    (tmp_path / "sub" / "f.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["list", str(tmp_path), "--fields", "dirs", "--fields", "created"],
    )

    assert result.exit_code == 0
    assert "n_dirs" in result.output
    assert "created" in result.output
    assert _row(result.output, "sub/").split()[2] == "1"  # one nested dir


def test_list_default_omits_optional_columns(tmp_path):
    (tmp_path / "f.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path)])

    assert result.exit_code == 0
    assert "n_dirs" not in result.output
    assert "created" not in result.output
    assert "modified" in result.output  # modified is on by default


def test_list_respects_filters(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "keep.txt").write_text("x")
    (tmp_path / "a" / "skip.jpg").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path), "--ext", ".txt"])

    assert result.exit_code == 0
    assert _row(result.output, "a/").split()[1] == "1"


def test_list_marks_incomplete_subtree_totals(tmp_path):
    (tmp_path / "a").mkdir()
    for i in range(20):
        (tmp_path / "a" / f"f{i}.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(
        main, ["list", str(tmp_path), "--max-entries", "5"]
    )

    assert result.exit_code == 0
    # The name itself carries the marker: "a/*", not "a/".
    assert _row(result.output, "a/*")
    assert "lower bounds" in result.output


def test_list_empty_directory(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total:" in result.output


def test_list_status_line_present(tmp_path):
    (tmp_path / "f.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path)])

    assert result.exit_code == 0
    assert "Complete." in result.output


def test_list_reports_row_truncation(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["list", str(tmp_path), "--max-rows", "3"])

    assert result.exit_code == 0
    assert "Showing 3 of 10 entries." in result.output
