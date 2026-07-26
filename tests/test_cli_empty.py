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


def test_empty_does_not_falsely_report_unscanned_dirs_as_empty(tmp_path):
    # Regression test: a truncated walk used to label the root (and any
    # other discovered-but-unscanned directory) as "empty" just because no
    # files had been *discovered* under it yet, even though its
    # subdirectories were never actually explored and could contain files.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["empty", str(tmp_path), "--max-entries", "1"])

    assert result.exit_code == 0
    assert "Total (at least, walk stopped early): 0 empty directories" in result.output
    assert "could not be confirmed empty or non-empty" in result.output
    assert "1 directories" in result.output


def test_empty_does_not_report_a_dir_whose_child_is_unscanned(tmp_path):
    # Subtler regression case: "parent" itself IS fully scanned (its own
    # os.scandir completed), but its child "maybe_empty" is only
    # discovered, not yet scanned, when the budget runs out. maybe_empty
    # could contain files, so parent must not be reported as empty either
    # — being scanned yourself isn't enough; your whole subtree must be
    # known.
    (tmp_path / "parent" / "maybe_empty").mkdir(parents=True)
    (tmp_path / "parent" / "maybe_empty" / "hidden.txt").write_text("x")

    runner = CliRunner()
    # root + parent scanned (2 dirs), maybe_empty only discovered.
    result = runner.invoke(main, ["empty", str(tmp_path), "--max-entries", "3"])

    assert result.exit_code == 0
    assert "Total (at least, walk stopped early): 0 empty directories" in result.output
    assert "parent" not in result.output.split("Total")[0]


def test_empty_no_unvisited_caveat_when_walk_completes_and_nothing_out_of_scope(tmp_path):
    (tmp_path / "has_files").mkdir()
    (tmp_path / "has_files" / "f.txt").write_text("x")
    (tmp_path / "empty_dir").mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["empty", str(tmp_path)])

    assert result.exit_code == 0
    assert "could not be confirmed" not in result.output


def test_empty_max_depth_scope_is_not_reported_as_a_truncation(tmp_path):
    # --max-depth is a deliberate scoping choice (see DESIGN.md), not a
    # truncation, so directories it excludes must not be labeled "empty"
    # (their subtree genuinely wasn't looked at) but also must not trigger
    # the "walk stopped early" truncation wording, since the walk itself
    # completed on its own terms.
    (tmp_path / "a" / "b").mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(main, ["empty", str(tmp_path), "--max-depth", "0"])

    assert result.exit_code == 0
    assert "Total: 0 empty directories" in result.output
    assert "--max-depth=0 kept their subtree out of scope" in result.output
    assert "walk stopped before" not in result.output
    assert "Complete." in result.output
