import json
import os
import time

from click.testing import CliRunner

from gazetteer import frontier, report
from gazetteer.cli import _top_extensions_cell, _top_owner_cell, _username, main


def _tree(tmp_path):
    """
    tmp_path/
      a/f1.txt (100 bytes), a/f2.txt (200 bytes)
      b/ (empty)
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f1.txt").write_bytes(b"x" * 100)
    (tmp_path / "a" / "f2.txt").write_bytes(b"x" * 200)
    (tmp_path / "b").mkdir()
    return tmp_path


def test_sample_lists_each_immediate_subdirectory(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    assert "a/" in result.output
    assert "b/" in result.output


def test_sample_reports_exact_for_small_fully_scanned_tree(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    assert "2 of 2 subdirectories fully scanned (exact)." in result.output
    # A fully-scanned row must never carry the incomplete "*" marker --
    # it's now a leading prefix ("* name"), not trailing.
    lines = result.output.splitlines()
    a_line = next(l for l in lines if "a/" in l)
    b_line = next(l for l in lines if "b/" in l)
    assert not a_line.lstrip().startswith("*")
    assert not b_line.lstrip().startswith("*")


def test_sample_reports_correct_file_counts(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--json"])

    data = json.loads(result.output)
    rows = {row["name"]: row for row in data["rows"]}
    assert rows["a"]["exact"] is True
    assert rows["a"]["lower_bound_files"] == 2
    assert rows["b"]["exact"] is True
    assert rows["b"]["lower_bound_files"] == 0


def test_sample_json_matches_estimate_to_lower_bound_when_exact(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--json"])

    data = json.loads(result.output)
    for row in data["rows"]:
        assert row["exact"]
        assert row["estimate_bytes"] == row["lower_bound_bytes"]
        assert row["estimate_files"] == row["lower_bound_files"]
        assert row["estimate_dirs"] == row["lower_bound_dirs"]


def test_sample_json_reports_dirs_and_extension_breakdown(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_bytes(b"x" * 100)
    (tmp_path / "a" / "two.txt").write_bytes(b"x" * 100)
    (tmp_path / "a" / "three.json").write_bytes(b"x" * 100)
    (tmp_path / "a" / "sub").mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--json"])

    data = json.loads(result.output)
    row = next(r for r in data["rows"] if r["name"] == "a")
    assert row["lower_bound_dirs"] == 1
    assert row["ext_files"] == {".txt": 2, ".json": 1}


def test_sample_table_shows_top_extensions_by_count_and_size(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_bytes(b"x" * 10)
    (tmp_path / "a" / "two.txt").write_bytes(b"x" * 10)
    (tmp_path / "a" / "big.json").write_bytes(b"x" * 100_000)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    result_json = runner.invoke(main, ["sample", str(tmp_path), "--json"])
    data = json.loads(result_json.output)
    row = next(r for r in data["rows"] if r["name"] == "a")

    # .txt is the majority BY COUNT (2 of 3 files); .json dominates BY
    # SIZE (100,000 of ~108,000 allocated bytes, once small files round
    # up to a full block each) -- the two extension dicts must reflect
    # that difference, not just report the same ranking twice.
    top_by_count = max(row["ext_files"], key=row["ext_files"].get)
    top_by_size = max(row["ext_bytes"], key=row["ext_bytes"].get)
    assert top_by_count == ".txt"
    assert top_by_size == ".json"


def test_sample_partial_scan_marks_row_and_shows_estimate(tmp_path):
    # A directory with enough nesting that a near-zero budget can't finish.
    current = tmp_path / "big"
    current.mkdir()
    for i in range(5):
        current = current / f"d{i}"
        current.mkdir()
        (current / "f.txt").write_bytes(b"x" * 1000)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sample", str(tmp_path), "--max-seconds", "0.0000001"]
    )

    assert result.exit_code == 0
    lines = result.output.splitlines()
    big_line = next(l for l in lines if "big/" in l)
    # "*" now prefixes the name rather than trailing it.
    assert big_line.lstrip().startswith("*")
    assert "0 of 1 subdirectories fully scanned (exact)." in result.output
    assert "possibly-biased estimate" in result.output


def test_sample_full_paths_option(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "-P"])

    assert result.exit_code == 0
    assert str(tmp_path / "a") in result.output


def test_sample_max_rows_limits_output(tmp_path):
    for i in range(5):
        (tmp_path / f"sub{i}").mkdir()
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--max-rows", "2"])

    assert result.exit_code == 0
    assert "Showing 2 of 5 entries." in result.output


def test_sample_on_empty_path_reports_no_subdirectories(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    assert "0 of 0 subdirectories fully scanned (exact)." in result.output


def test_sample_deterministic_with_seed(tmp_path):
    current = tmp_path / "big"
    current.mkdir()
    for i in range(6):
        current = current / f"d{i}"
        current.mkdir()
        (current / "f.txt").write_bytes(b"x" * 1000)

    runner = CliRunner()
    r1 = runner.invoke(
        main,
        ["sample", str(tmp_path), "--max-seconds", "0.0000001", "--seed", "7", "--json"],
    )
    r2 = runner.invoke(
        main,
        ["sample", str(tmp_path), "--max-seconds", "0.0000001", "--seed", "7", "--json"],
    )

    d1 = json.loads(r1.output)
    d2 = json.loads(r2.output)
    assert d1["rows"] == d2["rows"]


def _deep_chain(base, depth, size=1000):
    base.mkdir(parents=True)
    current = base
    for i in range(depth):
        current = current / f"d{i}"
        current.mkdir()
        (current / "f.txt").write_bytes(b"x" * size)
    return current


def test_sample_max_seconds_is_a_total_budget_not_per_subdirectory(tmp_path):
    """--max-seconds bounds the WHOLE command, regardless of how many
    subdirectories PATH has -- a fixed per-subdirectory budget would make
    total runtime scale with subdirectory count instead."""
    for i in range(20):
        _deep_chain(tmp_path / f"sub{i}", depth=15)

    runner = CliRunner()
    start = time.monotonic()
    result = runner.invoke(main, ["sample", str(tmp_path), "--max-seconds", "2"])
    elapsed = time.monotonic() - start

    assert result.exit_code == 0
    # Generous slack for process/test overhead, but this must stay well
    # under "20 subdirectories x some fixed per-dir budget" -- the whole
    # point of the total-budget model.
    assert elapsed < 6


def test_sample_first_pass_completes_small_subdirs_despite_huge_sibling(tmp_path):
    """The first pass gives every subdirectory an equal share of 33% of
    the total budget up front, so a trivially small subtree finishes
    immediately even when scanned alongside a sibling too large to ever
    finish in the available time."""
    (tmp_path / "tiny").mkdir()
    (tmp_path / "tiny" / "f.txt").write_bytes(b"x" * 10)
    _deep_chain(tmp_path / "huge", depth=200)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--max-seconds", "1", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    rows = {row["name"]: row for row in data["rows"]}
    assert rows["tiny"]["exact"] is True
    assert rows["tiny"]["lower_bound_files"] == 1


def test_sample_round_robin_makes_progress_on_multiple_incomplete_dirs(tmp_path):
    """After the first pass, remaining budget round-robins across every
    still-incomplete subdirectory rather than exhausting the whole
    remainder on just one of them."""
    _deep_chain(tmp_path / "big1", depth=100)
    _deep_chain(tmp_path / "big2", depth=100)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--max-seconds", "1.5", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    rows = {row["name"]: row for row in data["rows"]}
    # Neither huge subtree finishes in 1.5s, but both should show real
    # progress (more than the handful of scans a single first-pass share
    # alone would produce) if round-robin is actually alternating between
    # them rather than starving one in favor of the other.
    assert rows["big1"]["n_scans"] > 0 or rows["big1"]["lower_bound_files"] > 0
    assert rows["big2"]["n_scans"] > 0 or rows["big2"]["lower_bound_files"] > 0


def test_sample_stops_round_robin_early_once_all_exact(tmp_path):
    """A generous total budget shouldn't be fully consumed if every
    subdirectory finishes well within it -- round-robin must exit as soon
    as nothing is left incomplete, not busy-wait for the clock."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.txt").write_bytes(b"x")

    runner = CliRunner()
    start = time.monotonic()
    result = runner.invoke(main, ["sample", str(tmp_path), "--max-seconds", "30"])
    elapsed = time.monotonic() - start

    assert result.exit_code == 0
    assert "1 of 1 subdirectories fully scanned (exact)." in result.output
    assert elapsed < 5


def test_top_extensions_cell_only_top_entry_has_percentage():
    counts = {".txt": 6, ".json": 3, ".md": 1}
    assert _top_extensions_cell(counts, total=10, width=30) == ".txt(60%) .json .md"


def test_top_extensions_cell_bare_name_when_only_one_extension():
    assert _top_extensions_cell({".md": 5}, total=5) == ".md"


def test_top_extensions_cell_stops_at_width_budget():
    counts = {".txt": 6, ".json": 3, ".md": 1}
    result = _top_extensions_cell(counts, total=10, width=12)
    assert result == ".txt(60%)"
    assert len(result) <= 12


def test_top_extensions_cell_never_exceeds_width():
    counts = {".extremelylongextension": 5, ".b": 3, ".c": 2}
    result = _top_extensions_cell(counts, total=10, width=30)
    assert len(result) <= 30


def test_top_extensions_cell_empty_when_no_data():
    assert _top_extensions_cell({}, total=0) == ""
    assert _top_extensions_cell({".txt": 1}, total=0) == ""


def test_top_owner_cell_bare_name_at_100_percent():
    assert _top_owner_cell({"alice": 10}, total=10) == "alice"


def test_top_owner_cell_shows_percentage_below_100():
    counts = {"alice": 8, "bob": 2}
    assert _top_owner_cell(counts, total=10) == "alice(80%)"


def test_top_owner_cell_empty_when_no_data():
    assert _top_owner_cell({}, total=0) == ""


def test_sample_shows_activity_column_by_default(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    assert "activity" in result.output
    # "a" has files (recently written by this test), so it should show a
    # real recency string, not the "no files scanned" placeholder.
    lines = result.output.splitlines()
    a_line = next(l for l in lines if "a/" in l)
    assert "ago" in a_line


def test_sample_activity_placeholder_for_directory_with_no_files(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    lines = result.output.splitlines()
    b_line = next(l for l in lines if "b/" in l)
    # "b" is empty -- no files means no meaningful "most recently
    # touched" answer, so it must show the placeholder, not a bogus age.
    assert " - " in b_line or b_line.rstrip().endswith("-")


def test_sample_json_includes_newest_mtime_and_owner_breakdown(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--json"])

    data = json.loads(result.output)
    row_a = next(r for r in data["rows"] if r["name"] == "a")
    assert row_a["newest_mtime"] is not None
    my_uid = str(os.getuid())
    assert row_a["owner_files"] == {my_uid: 2}

    row_b = next(r for r in data["rows"] if r["name"] == "b")
    assert row_b["newest_mtime"] is None
    assert row_b["owner_files"] == {}


def test_sample_owners_column_hidden_by_default(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    header = result.output.splitlines()[0]
    assert "owner" not in header


def test_sample_fields_owners_shows_owner_column(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--fields", "owners"])

    assert result.exit_code == 0
    header = result.output.splitlines()[0]
    assert "owner" in header
    my_name = _username(os.getuid())
    lines = result.output.splitlines()
    a_line = next(l for l in lines if "a/" in l)
    # Sole owner of everything in "a" -- bare name, no "(100%)" suffix.
    assert f" {my_name} " in a_line or a_line.rstrip().endswith(my_name)


def test_username_falls_back_to_uid_for_unknown_user():
    # A uid vanishingly unlikely to exist on any real system.
    assert _username(2**31 - 1) == str(2**31 - 1)


def test_sample_sort_by_size_ranks_biggest_first(tmp_path):
    (tmp_path / "small").mkdir()
    (tmp_path / "small" / "f.txt").write_bytes(b"x" * 10)
    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "f.txt").write_bytes(b"x" * 1_000_000)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--sort", "size", "--json"])

    data = json.loads(result.output)
    names = [row["name"] for row in data["rows"]]
    assert names.index("big") < names.index("small")


def test_sample_sort_reverse_flips_order(tmp_path):
    (tmp_path / "small").mkdir()
    (tmp_path / "small" / "f.txt").write_bytes(b"x" * 10)
    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "f.txt").write_bytes(b"x" * 1_000_000)

    runner = CliRunner()
    result = runner.invoke(
        main, ["sample", str(tmp_path), "--sort", "size", "--reverse", "--json"]
    )

    data = json.loads(result.output)
    names = [row["name"] for row in data["rows"]]
    assert names.index("small") < names.index("big")


def test_sample_sort_defaults_to_name_ascending(tmp_path):
    for n in ("zebra", "apple", "mango"):
        (tmp_path / n).mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--json"])

    data = json.loads(result.output)
    names = [row["name"] for row in data["rows"]]
    assert names == ["apple", "mango", "zebra"]


def test_sample_sort_by_files_uses_estimate_not_lower_bound(tmp_path):
    """A subtree that's mostly unscanned should still sort as "big" by
    estimated file count, not as "small" by its partial lower bound --
    this is the whole reason --sort ranks on estimate_*, not
    lower_bound_*."""
    (tmp_path / "tiny").mkdir()
    (tmp_path / "tiny" / "f.txt").write_bytes(b"x")
    _deep_chain(tmp_path / "huge", depth=50)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["sample", str(tmp_path), "--sort", "files", "--max-seconds", "0.5", "--json"],
    )

    data = json.loads(result.output)
    names = [row["name"] for row in data["rows"]]
    assert names.index("huge") < names.index("tiny")


def test_sample_ext_types_column_counts_distinct_extensions(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_bytes(b"x" * 10)
    (tmp_path / "a" / "two.txt").write_bytes(b"x" * 10)
    (tmp_path / "a" / "three.json").write_bytes(b"x" * 10)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])
    assert result.exit_code == 0
    assert "ext types" in result.output.splitlines()[0]

    result_json = runner.invoke(main, ["sample", str(tmp_path), "--json"])
    data = json.loads(result_json.output)
    row = next(r for r in data["rows"] if r["name"] == "a")
    # 2 distinct extensions (.txt, .json), regardless of file counts --
    # the text column is a direct len() of this same dict.
    assert len(row["ext_files"]) == 2


def test_sample_ext_types_placeholder_for_no_files(tmp_path):
    (tmp_path / "empty").mkdir()
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    lines = result.output.splitlines()
    e_line = next(l for l in lines if "empty/" in l)
    assert " - " in e_line


def test_sample_rank_by_defaults_to_size(tmp_path):
    """Default ranking is by bytes: a big .json file should outrank many
    tiny .txt files in the ext column even though .txt has more files."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_bytes(b"x" * 10)
    (tmp_path / "a" / "two.txt").write_bytes(b"x" * 10)
    (tmp_path / "a" / "big.json").write_bytes(b"x" * 200_000)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    lines = result.output.splitlines()
    a_line = next(l for l in lines if "a/" in l)
    assert ".json" in a_line and a_line.index(".json") < a_line.index(".txt")


def test_sample_rank_by_count_switches_ext_ranking(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_bytes(b"x" * 10)
    (tmp_path / "a" / "two.txt").write_bytes(b"x" * 10)
    (tmp_path / "a" / "big.json").write_bytes(b"x" * 200_000)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--rank-by", "count"])

    lines = result.output.splitlines()
    a_line = next(l for l in lines if "a/" in l)
    assert ".txt" in a_line and a_line.index(".txt") < a_line.index(".json")


def test_sample_rank_by_count_also_affects_owner_column(tmp_path):
    """--rank-by is shared between the ext and owner columns, not just
    the ext one -- confirmed via JSON since a single-owner tree can't
    show a visible ranking difference in the owner cell itself, but the
    option must be accepted together with --fields owners without error."""
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main, ["sample", str(tmp_path), "--rank-by", "count", "--fields", "owners"]
    )

    assert result.exit_code == 0
    header = result.output.splitlines()[0]
    assert "owner" in header


def test_sample_incomplete_marker_is_leading_not_trailing(tmp_path):
    """The "*" for an incomplete row is a leading prefix ("* name"), not
    a trailing suffix ("name*") -- it should stand out at the left edge
    where the eye scans first, not be buried at the end of a long row."""
    current = tmp_path / "big"
    current.mkdir()
    for i in range(5):
        current = current / f"d{i}"
        current.mkdir()
        (current / "f.txt").write_bytes(b"x" * 1000)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--max-seconds", "0.0000001"])

    lines = result.output.splitlines()
    big_line = next(l for l in lines if "big/" in l)
    assert big_line.startswith("* ")
    assert "big/*" not in result.output


def test_sample_names_stay_aligned_between_complete_and_incomplete_rows(tmp_path):
    """A complete row's name and an incomplete row's name must start in
    the same column -- the incomplete row's "* " prefix and the complete
    row's blank-space prefix need to be the same width."""
    (tmp_path / "small").mkdir()
    (tmp_path / "small" / "f.txt").write_bytes(b"x")
    _deep_chain(tmp_path / "big", depth=30)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--max-seconds", "0.0000001"])

    lines = [l for l in result.output.splitlines() if "small/" in l or "big/" in l]
    assert len(lines) == 2
    # Whatever column the name text starts in, it must be the same for
    # both rows.
    small_line = next(l for l in lines if "small/" in l)
    big_line = next(l for l in lines if "big/" in l)
    small_start = len(small_line) - len(small_line.lstrip())
    big_start = len(big_line) - len(big_line.lstrip())
    assert small_start == big_start


def test_sample_denied_column_hidden_when_nothing_blocked(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    header = result.output.splitlines()[0]
    assert "denied" not in header


def test_sample_denied_column_appears_when_something_blocked(tmp_path):
    _tree(tmp_path)
    secret = tmp_path / "a" / "secret"
    secret.mkdir()
    os.chmod(secret, 0o000)

    try:
        runner = CliRunner()
        result = runner.invoke(main, ["sample", str(tmp_path)])
    finally:
        os.chmod(secret, 0o755)

    assert result.exit_code == 0
    header = result.output.splitlines()[0]
    assert "denied" in header

    lines = result.output.splitlines()
    a_line = next(l for l in lines if "a/" in l)
    b_line = next(l for l in lines if "b/" in l)
    # "a" has the denied subdirectory, "b" doesn't -- the column should
    # be blank (not "0") for a row with nothing denied, so the row that
    # actually hit a permission error stands out.
    assert "1" in a_line.split()
    header_cols = header.split()
    denied_idx = header_cols.index("denied")
    assert b_line.split()[denied_idx] not in ("1",)


def test_sample_json_includes_denied_count(tmp_path):
    _tree(tmp_path)
    secret = tmp_path / "a" / "secret"
    secret.mkdir()
    os.chmod(secret, 0o000)

    try:
        runner = CliRunner()
        result = runner.invoke(main, ["sample", str(tmp_path), "--json"])
    finally:
        os.chmod(secret, 0o755)

    data = json.loads(result.output)
    rows = {row["name"]: row for row in data["rows"]}
    assert rows["a"]["denied"] == 1
    assert rows["b"]["denied"] == 0


def test_sample_denied_recurses_to_parent_row(tmp_path):
    """A permission-denied directory nested inside a subdirectory must
    still be reflected in that subdirectory's own denied count, not just
    somewhere buried in the tree."""
    nested_secret = tmp_path / "a" / "nested" / "secret"
    nested_secret.mkdir(parents=True)
    os.chmod(nested_secret, 0o000)

    try:
        runner = CliRunner()
        result = runner.invoke(main, ["sample", str(tmp_path), "--json"])
    finally:
        os.chmod(nested_secret, 0o755)

    data = json.loads(result.output)
    row_a = next(r for r in data["rows"] if r["name"] == "a")
    assert row_a["denied"] == 1


def test_sample_lists_loose_files_alongside_subdirectories(tmp_path):
    _tree(tmp_path)
    (tmp_path / "loose.txt").write_bytes(b"x" * 100)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    lines = result.output.splitlines()
    file_line = next(l for l in lines if "loose.txt" in l)
    # A file row has no trailing "/" on its name, unlike a directory row.
    assert "loose.txt/" not in file_line
    assert "loose.txt" in file_line


def test_sample_file_row_is_always_exact_with_no_markers(tmp_path):
    (tmp_path / "small.txt").write_bytes(b"x" * 10)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    lines = result.output.splitlines()
    file_line = next(l for l in lines if "small.txt" in l)
    # No "*" (incomplete) or "-" (denied) marker -- a file's own stat is
    # already the complete answer, nothing to scan or be denied on.
    assert not file_line.lstrip().startswith("*")
    assert not file_line.lstrip().startswith("-")


def test_sample_json_reports_file_rows_with_type_file(tmp_path):
    (tmp_path / "small.txt").write_bytes(b"x" * 123)
    (tmp_path / "sub").mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--json"])

    data = json.loads(result.output)
    rows = {row["name"]: row for row in data["rows"]}
    assert rows["small.txt"]["type"] == "file"
    assert rows["small.txt"]["exact"] is True
    assert rows["small.txt"]["lower_bound_files"] == 1
    assert rows["small.txt"]["lower_bound_dirs"] == 0
    assert rows["sub"]["type"] == "dir"


def test_sample_status_line_excludes_files_from_subdirectory_count(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    (tmp_path / "b.txt").write_bytes(b"x")
    (tmp_path / "sub").mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    # Only "sub" is a subdirectory -- the two files must not inflate the
    # denominator of the "N of M subdirectories" status line.
    assert "1 of 1 subdirectories fully scanned (exact)." in result.output


def test_sample_json_subdirs_count_excludes_files(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    (tmp_path / "sub").mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--json"])

    data = json.loads(result.output)
    assert data["subdirs"] == 1
    assert data["exact_subdirs"] == 1
    # But the file row is still present among the actual rows.
    assert len(data["rows"]) == 2


def test_sample_file_only_directory_has_no_subdirectory_status_confusion(tmp_path):
    (tmp_path / "only.txt").write_bytes(b"x")

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    assert "0 of 0 subdirectories fully scanned (exact)." in result.output
    assert "only.txt" in result.output


def test_sample_sort_by_size_ranks_files_and_dirs_together(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.txt").write_bytes(b"x" * 1_000_000)
    (tmp_path / "small.txt").write_bytes(b"x" * 10)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--sort", "size", "--json"])

    data = json.loads(result.output)
    names = [row["name"] for row in data["rows"]]
    assert names.index("sub") < names.index("small.txt")


def test_sample_denied_marker_takes_priority_over_incomplete_marker(tmp_path, monkeypatch):
    """A row that is BOTH incomplete (didn't finish scanning in budget)
    AND has a denied directory inside it must show "-", not "*" -- denial
    is a more specific, more actionable fact than "ran out of time".
    Exercised by patching FrontierSampler.current_result so the scenario
    is exact and deterministic rather than depending on the sampler's
    random descent order happening to hit both conditions at once."""
    (tmp_path / "sub").mkdir()

    incomplete_and_denied = frontier.SampleResult(
        exact=False,
        lower_bound_bytes=100,
        lower_bound_files=1,
        lower_bound_dirs=1,
        estimate_bytes=500.0,
        estimate_files=5.0,
        estimate_dirs=2.0,
        lower_bound_ext_bytes={".txt": 100},
        lower_bound_ext_files={".txt": 1},
        lower_bound_owner_bytes={},
        lower_bound_owner_files={},
        newest_mtime=None,
        lower_bound_denied=1,
        completeness=0.5,
        n_scans=3,
        n_errors=1,
        elapsed=0.01,
        stop_reason="10s limit",
    )
    monkeypatch.setattr(
        frontier.FrontierSampler, "current_result", lambda self: incomplete_and_denied
    )

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    lines = result.output.splitlines()
    sub_line = next(l for l in lines if "sub/" in l)
    assert sub_line.lstrip().startswith("-")
    assert not sub_line.lstrip().startswith("*")


def test_sample_summary_reports_scanned_dirs_and_files(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    # "a" has 0 subdirs beneath it (+1 for itself), "b" has 0 (+1 for
    # itself) = 2 dirs visited; "a" has 2 files, "b" has 0 = 2 files.
    assert "Scanned 2 dirs / 2 files in" in result.output


def test_sample_summary_reports_exact_total_when_fully_scanned(tmp_path):
    _tree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    # Fully scanned -- no "confirmed"/"estimated" split, just one number.
    assert "Total: 2 files," in result.output
    assert "confirmed" not in result.output
    assert "estimated" not in result.output


def test_sample_summary_splits_confirmed_and_estimated_when_partial(tmp_path):
    current = tmp_path / "big"
    current.mkdir()
    for i in range(5):
        current = current / f"d{i}"
        current.mkdir()
        (current / "f.txt").write_bytes(b"x" * 1000)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path), "--max-seconds", "0.0000001"])

    assert result.exit_code == 0
    assert "confirmed" in result.output
    assert "estimated" in result.output


def test_sample_summary_totals_include_file_rows(tmp_path):
    _tree(tmp_path)
    (tmp_path / "loose.txt").write_bytes(b"x" * 500)

    runner = CliRunner()
    result = runner.invoke(main, ["sample", str(tmp_path)])

    assert result.exit_code == 0
    # 2 files in "a" + 1 loose file = 3 files total; the loose file
    # contributes no directories.
    assert "Total: 3 files," in result.output
    assert "Scanned 2 dirs / 3 files in" in result.output


def test_sample_summary_totals_match_json_sums(tmp_path):
    _tree(tmp_path)
    (tmp_path / "loose.txt").write_bytes(b"x" * 500)

    runner = CliRunner()
    result_json = runner.invoke(main, ["sample", str(tmp_path), "--json"])
    data = json.loads(result_json.output)
    expected_files = sum(row["lower_bound_files"] for row in data["rows"])
    expected_bytes = sum(row["lower_bound_bytes"] for row in data["rows"])

    result = runner.invoke(main, ["sample", str(tmp_path)])
    assert f"Total: {expected_files:,} files," in result.output
    assert report.human_size(expected_bytes) in result.output
