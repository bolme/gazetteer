from click.testing import CliRunner

from gazetteer.cli import main
from gazetteer.report import human_size

ALL_COMMANDS = [
    ["ext"],
    ["tree"],
    ["find", "*"],
    ["stale"],
    ["empty"],
    ["dup"],
]


def test_nonexistent_path_is_a_clean_usage_error(tmp_path):
    missing = tmp_path / "does_not_exist"
    runner = CliRunner()
    result = runner.invoke(main, ["ext", str(missing)])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_path_that_is_a_file_not_a_directory_is_a_clean_usage_error(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    runner = CliRunner()
    result = runner.invoke(main, ["ext", str(f)])

    assert result.exit_code != 0


def test_all_commands_handle_completely_empty_tree(tmp_path):
    runner = CliRunner()
    for cmd in ALL_COMMANDS:
        result = runner.invoke(main, [*cmd, str(tmp_path)])
        assert result.exit_code == 0, f"{cmd[0]} failed: {result.output}"
        assert "Complete." in result.output or "Scanned" in result.output


def test_ext_max_rows_zero_hides_rows_but_keeps_status_accurate(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["ext", str(tmp_path), "--max-rows", "0"])

    assert result.exit_code == 0
    assert ".txt" not in result.output.split("\n\n")[0]  # no data row printed
    assert "5 files" in result.output


def test_tree_total_line_reflects_all_files_not_just_shown_rows(tmp_path):
    for name in ("a", "b", "c"):
        d = tmp_path / name
        d.mkdir()
        (d / "f.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["tree", str(tmp_path), "--max-rows", "1"])

    assert result.exit_code == 0
    assert "Total: 4 dirs, 3 files" in result.output


def test_find_max_rows_truncates_but_status_reports_full_walk(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(
        main, ["find", "*.txt", str(tmp_path), "--max-rows", "2"]
    )

    assert result.exit_code == 0
    table_section = result.output.split("\n\n")[0]
    assert table_section.count(".txt") == 2
    assert "10 files" in result.output


def test_dup_ignores_zero_byte_files(tmp_path):
    (tmp_path / "empty1.txt").touch()
    (tmp_path / "empty2.txt").touch()

    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: 0 duplicate sets" in result.output


def test_dup_handles_three_way_duplicate_set(tmp_path):
    content = "identical content"
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(content)

    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: 1 duplicate sets" in result.output
    # 3 copies of an N-byte file -> 2 * N bytes reclaimable
    reclaimable = human_size(len(content) * 2)
    assert reclaimable in result.output
    table_line = next(
        line for line in result.output.splitlines() if str(tmp_path) in line
    )
    columns = table_line.split()
    assert "3" in columns


def test_dup_files_with_same_size_but_different_content_are_not_duplicates(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"aaaaa")
    (tmp_path / "b.txt").write_bytes(b"bbbbb")

    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: 0 duplicate sets" in result.output


def test_stale_older_than_zero_matches_everything(tmp_path):
    (tmp_path / "f.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["stale", str(tmp_path), "--older-than", "0s"])

    assert result.exit_code == 0
    assert "f.txt" in result.output


def test_stale_default_older_than_is_90d(tmp_path):
    (tmp_path / "f.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["stale", str(tmp_path)])

    assert result.exit_code == 0
    assert "90d" in result.output
    # a file just created is not older than 90 days
    assert "Total: 0 files older than 90d" in result.output


def test_empty_root_itself_is_reported_when_it_has_no_files(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["empty", str(tmp_path)])

    assert result.exit_code == 0
    assert str(tmp_path) in result.output
    assert "Total: 1 empty directories" in result.output


def test_empty_no_warning_when_walk_completes(tmp_path):
    (tmp_path / "sub").mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["empty", str(tmp_path)])

    assert result.exit_code == 0
    assert "may simply be unvisited" not in result.output


def test_find_pattern_matches_directories_too(tmp_path):
    (tmp_path / "match_dir").mkdir()
    (tmp_path / "other_dir").mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["find", "match_*", str(tmp_path)])

    assert result.exit_code == 0
    assert "match_dir" in result.output
    assert "other_dir" not in result.output


def test_max_entries_zero_still_produces_valid_output(tmp_path):
    (tmp_path / "f.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["ext", str(tmp_path), "--max-entries", "0"])

    assert result.exit_code == 0
    assert "lower bound" in result.output


# --- Total-line truncation qualification -----------------------------
# DESIGN.md: "Never present a partial number as if it were total." Each
# command's Total line must say so itself, not just rely on the separate
# status_line mentioning the walk was cut short.


def _many_files(tmp_path, n=20):
    for i in range(n):
        (tmp_path / f"f{i}.txt").write_text("x")


def test_ext_total_is_qualified_when_walk_truncated(tmp_path):
    _many_files(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["ext", str(tmp_path), "--max-entries", "5"])

    assert result.exit_code == 0
    assert "Total (at least, walk stopped early):" in result.output


def test_ext_total_is_unqualified_when_walk_completes(tmp_path):
    _many_files(tmp_path, n=3)
    runner = CliRunner()
    result = runner.invoke(main, ["ext", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: " in result.output
    assert "at least" not in result.output


def test_tree_total_is_qualified_when_walk_truncated(tmp_path):
    _many_files(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["tree", str(tmp_path), "--max-entries", "5"])

    assert result.exit_code == 0
    assert "Total (at least, walk stopped early):" in result.output


def test_tree_total_mentions_both_filter_and_truncation(tmp_path):
    _many_files(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main, ["tree", str(tmp_path), "--max-entries", "5", "--ext", ".txt"]
    )

    assert result.exit_code == 0
    assert "matching filter" in result.output
    assert "at least" in result.output


def test_stale_total_is_qualified_when_walk_truncated(tmp_path):
    _many_files(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main, ["stale", str(tmp_path), "--older-than", "0s", "--max-entries", "5"]
    )

    assert result.exit_code == 0
    assert "Total (at least, walk stopped early):" in result.output


def test_dup_total_blames_walk_when_walk_is_the_truncated_part(tmp_path):
    _many_files(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path), "--max-entries", "5"])

    assert result.exit_code == 0
    assert "Total (at least, walk stopped early):" in result.output


def test_dup_total_blames_hashing_when_only_hashing_is_truncated(tmp_path):
    (tmp_path / "a.txt").write_text("identical")
    (tmp_path / "b.txt").write_text("identical")

    runner = CliRunner()
    result = runner.invoke(
        main, ["dup", str(tmp_path), "--max-hash-seconds", "0"]
    )

    assert result.exit_code == 0
    assert "Total (at least, hashing stopped early):" in result.output
    assert "walk stopped early" not in result.output


def test_dup_total_unqualified_when_both_passes_complete(tmp_path):
    (tmp_path / "a.txt").write_text("identical")
    (tmp_path / "b.txt").write_text("identical")

    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: 1 duplicate sets" in result.output
    assert "at least" not in result.output
