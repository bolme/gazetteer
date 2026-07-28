import pytest

import json

from gazetteer.report import (
    ENCODED_RUN_MIN_LENGTH,
    human_duration,
    human_size,
    is_suspicious_mtime,
    json_output,
    parse_duration,
    parse_size,
    parse_size_filter,
    render_table,
    status_line,
    suppress_encoded_runs,
    total_label,
)
from gazetteer.walk import WalkResult


@pytest.mark.parametrize(
    "text,expected",
    [
        ("500", 500),
        ("1k", 1024),
        ("1K", 1024),
        ("1.5M", int(1.5 * 1024**2)),
        ("2GB", 2 * 1024**3),
        ("1T", 1024**4),
    ],
)
def test_parse_size(text, expected):
    assert parse_size(text) == expected


def test_parse_size_rejects_garbage():
    with pytest.raises(ValueError):
        parse_size("bogus")


@pytest.mark.parametrize(
    "text",
    ["", " ", ".", "5.", "-5", "MB", "1.5.5M", "5X"],
)
def test_parse_size_rejects_malformed_input(text):
    with pytest.raises(ValueError):
        parse_size(text)


def test_parse_size_is_case_insensitive():
    assert parse_size("5m") == parse_size("5M") == 5 * 1024**2


def test_parse_size_zero_is_valid():
    assert parse_size("0") == 0
    assert parse_size("0M") == 0


def test_parse_size_bare_number_defaults_to_bytes():
    assert parse_size("500") == 500


@pytest.mark.parametrize(
    "text,expected_op,expected_bytes",
    [
        (">1M", ">", 1024**2),
        (">=2k", ">=", 2048),
        ("<500", "<", 500),
        ("<=1G", "<=", 1024**3),
        ("100", "=", 100),
    ],
)
def test_parse_size_filter(text, expected_op, expected_bytes):
    op, size = parse_size_filter(text)
    assert op == expected_op
    assert size == expected_bytes


def test_parse_size_filter_tolerates_surrounding_whitespace():
    op, size = parse_size_filter(" > 5M ")
    assert op == ">"
    assert size == 5 * 1024**2


def test_parse_size_filter_rejects_double_operator():
    with pytest.raises(ValueError):
        parse_size_filter(">>5")


def test_parse_size_filter_rejects_unknown_operator():
    with pytest.raises(ValueError):
        parse_size_filter("!=5")


def test_parse_size_filter_rejects_empty_string():
    with pytest.raises(ValueError):
        parse_size_filter("")


def test_parse_size_filter_zero_bound_is_valid():
    op, size = parse_size_filter("<0")
    assert op == "<"
    assert size == 0


def test_human_size_roundtrip_style():
    assert human_size(0) == "0 B"
    assert human_size(1024) == "1.0 KB"
    assert "MB" in human_size(16_500_000)


@pytest.mark.parametrize(
    "n_bytes,expected",
    [
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1048575, "1.0 MB"),  # just under 1 MiB must round up, not show "1024.0 KB"
        (1048576, "1.0 MB"),
        (1073741823, "1.0 GB"),
        (1099511627775, "1.0 TB"),
        (1024**5, "1.0 PB"),
    ],
)
def test_human_size_unit_boundaries(n_bytes, expected):
    assert human_size(n_bytes) == expected


def test_human_size_zero():
    assert human_size(0) == "0 B"


@pytest.mark.parametrize(
    "text,expected_seconds",
    [
        ("30s", 30),
        ("1m", 60),
        ("6h", 6 * 3600),
        ("90d", 90 * 86400),
        ("2w", 2 * 7 * 86400),
        ("1y", 365 * 86400),
        ("90", 90),
    ],
)
def test_parse_duration(text, expected_seconds):
    assert parse_duration(text) == expected_seconds


def test_parse_duration_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("bogus")


@pytest.mark.parametrize("text", ["", " ", "-5d", "5x"])
def test_parse_duration_rejects_malformed_input(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_parse_duration_zero_is_valid():
    assert parse_duration("0") == 0
    assert parse_duration("0s") == 0


def test_parse_duration_fractional_units():
    assert parse_duration("5.5d") == 5.5 * 86400


def test_parse_duration_is_case_insensitive():
    assert parse_duration("6H") == parse_duration("6h") == 6 * 3600


def test_human_duration_picks_sensible_unit():
    assert human_duration(30) == "30s"
    assert human_duration(3600) == "1h"
    assert human_duration(90 * 86400) == "13w"
    assert human_duration(400 * 86400) == "1.1y"


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0s"),
        (59, "59s"),
        (60, "1m"),
        (3599, "60m"),
        (3600, "1h"),
        (86399, "24h"),
        (86400, "1d"),
        (604799, "7d"),
        (604800, "1w"),
        (31535999, "52w"),
        (31536000, "1.0y"),
    ],
)
def test_human_duration_boundaries(seconds, expected):
    assert human_duration(seconds) == expected


def test_human_duration_negative_is_treated_as_magnitude():
    assert human_duration(-30) == "30s"


@pytest.mark.parametrize(
    "mtime,expected",
    [
        (0, True),
        (1, True),
        (86400, True),  # 1 day after epoch
        (7 * 86400, True),  # exactly at the window boundary
        (-7 * 86400, True),  # negative mtimes are possible (pre-1970)
        (7 * 86400 + 1, False),
        (365 * 86400, False),  # ~1971, clearly not a reset artifact
        (1_700_000_000, False),  # a normal, recent real timestamp
    ],
)
def test_is_suspicious_mtime(mtime, expected):
    assert is_suspicious_mtime(mtime) == expected


def test_render_table_empty_rows_still_shows_header():
    output = render_table([], ("name", "size"))
    lines = output.splitlines()

    assert lines[0] == "name  size"
    assert len(lines) == 2  # header + separator, no data rows


def test_render_table_columns_align_to_widest_cell():
    output = render_table([("a", "1"), ("bbbbb", "22")], ("x", "y"))
    lines = output.splitlines()

    # every line's "y" column should start at the same character offset
    header_y_offset = lines[0].index("y")
    row_offsets = [line.index(cell) for line, cell in zip(lines[2:], ["1", "22"])]
    assert all(offset == header_y_offset for offset in row_offsets)


def test_render_table_handles_non_string_cells():
    output = render_table([(1, 2.5, True)], ("a", "b", "c"))
    assert "1" in output
    assert "2.5" in output
    assert "True" in output


def test_render_table_single_column():
    output = render_table([("only",)], ("header",))
    assert "only" in output
    assert "header" in output


def _walk_result(**overrides):
    defaults = dict(n_dirs=0, n_files=0, n_bytes=0, n_errors=0, elapsed=0.0, complete=True, stop_reason=None)
    defaults.update(overrides)
    return WalkResult(**defaults)


def test_status_line_complete_run():
    result = _walk_result(n_dirs=5, n_files=10, elapsed=1.23, complete=True)
    line = status_line(result, max_seconds=30)

    assert "Complete." in line
    assert "5" in line
    assert "10" in line
    assert "lower bound" not in line


def test_status_line_truncated_run_mentions_lower_bound_and_reason():
    result = _walk_result(n_dirs=1, n_files=2, complete=False, stop_reason="30.0s limit")
    line = status_line(result, max_seconds=30)

    assert "lower bound" in line
    assert "30.0s limit" in line
    assert "--max-seconds" in line


def test_status_line_entries_limit_suggests_max_entries_not_max_seconds():
    result = _walk_result(n_dirs=1, n_files=2, complete=False, stop_reason="1000000 entries limit")
    line = status_line(result, max_seconds=30, max_entries=1_000_000)

    assert "lower bound" in line
    assert "1000000 entries limit" in line
    assert "--max-entries 10000000" in line
    assert "--max-seconds" not in line


def test_status_line_entries_limit_without_max_entries_arg_omits_broken_suggestion():
    # max_entries defaults to 0 (unlimited). If the caller's stop_reason
    # says "entries limit" but they didn't pass a matching max_entries,
    # "--max-entries 0" would be actively wrong (0 means unlimited, the
    # opposite of "bigger") -- so no suggestion is better than a wrong one,
    # and --max-seconds (which wasn't the actual limit) isn't suggested
    # either.
    result = _walk_result(n_dirs=1, n_files=2, complete=False, stop_reason="1000000 entries limit")
    line = status_line(result, max_seconds=30)

    assert "--max-entries 0" not in line
    assert "--max-seconds" not in line
    assert "lower bound" in line


def test_status_line_max_seconds_zero_omits_broken_suggestion():
    # Mirror case: stop_reason says a time limit was hit, but the caller
    # passed max_seconds=0 (unlimited) -- can't have actually been what
    # stopped the walk, so don't suggest raising it.
    result = _walk_result(n_dirs=1, n_files=2, complete=False, stop_reason="30.0s limit")
    line = status_line(result, max_seconds=0)

    assert "--max-seconds 0" not in line
    assert "lower bound" in line


def test_status_line_reports_error_count_when_present():
    result = _walk_result(n_dirs=1, n_files=1, complete=True, n_errors=3)
    line = status_line(result, max_seconds=30)

    assert "3" in line
    assert "unreadable paths skipped" in line


def test_status_line_omits_error_mention_when_zero():
    result = _walk_result(n_dirs=1, n_files=1, complete=True, n_errors=0)
    line = status_line(result, max_seconds=30)

    assert "unreadable" not in line


def test_status_line_formats_large_counts_with_commas():
    result = _walk_result(n_dirs=1204, n_files=412003, complete=True)
    line = status_line(result, max_seconds=30)

    assert "1,204" in line
    assert "412,003" in line


def test_total_label_complete_walk_is_unqualified():
    result = _walk_result(complete=True)
    assert total_label(result) == "Total"


def test_total_label_truncated_walk_says_at_least():
    result = _walk_result(complete=False)
    label = total_label(result)

    assert "Total" in label
    assert "at least" in label
    assert "walk stopped early" in label


def test_total_label_filtered_and_complete():
    result = _walk_result(complete=True)
    assert total_label(result, filtered=True) == "Total (matching filter)"


def test_total_label_filtered_and_truncated_mentions_both():
    result = _walk_result(complete=False)
    label = total_label(result, filtered=True)

    assert "matching filter" in label
    assert "at least" in label


def test_total_label_complete_override_takes_precedence_over_walk_result():
    # A command with a second budgeted pass (e.g. dup's hashing) can be
    # complete at the walk level but incomplete overall, or vice versa.
    complete_walk = _walk_result(complete=True)
    assert "at least" in total_label(complete_walk, complete=False)

    truncated_walk = _walk_result(complete=False)
    assert total_label(truncated_walk, complete=True) == "Total"


def test_total_label_custom_incomplete_reason():
    result = _walk_result(complete=True)
    label = total_label(result, complete=False, incomplete_reason="hashing stopped early")

    assert "hashing stopped early" in label
    assert "walk stopped early" not in label


def test_json_output_is_valid_json_with_expected_keys():
    result = _walk_result(n_dirs=2, n_files=3, elapsed=1.5, complete=True)
    rows = [{"ext": ".txt", "count": 3}]
    output = json_output(result, rows, total={"files": 3})

    parsed = json.loads(output)
    assert parsed["rows"] == rows
    assert parsed["complete"] is True
    assert parsed["stop_reason"] is None
    assert parsed["n_dirs"] == 2
    assert parsed["n_files"] == 3
    assert parsed["elapsed"] == 1.5
    assert parsed["total"] == {"files": 3}


def test_json_output_reflects_truncation():
    result = _walk_result(complete=False, stop_reason="30.0s limit", n_dirs=1, n_files=2)
    parsed = json.loads(json_output(result, [], total={}))

    assert parsed["complete"] is False
    assert parsed["stop_reason"] == "30.0s limit"


def test_json_output_complete_override_takes_precedence():
    # Mirrors total_label's complete= override for a command with a second
    # budgeted pass (e.g. dup's hashing) that can be incomplete even when
    # the walk itself finished.
    result = _walk_result(complete=True)
    parsed = json.loads(json_output(result, [], total={}, complete=False))

    assert parsed["complete"] is False


def test_json_output_reports_errors():
    result = _walk_result(n_errors=5)
    parsed = json.loads(json_output(result, [], total={}))

    assert parsed["n_errors"] == 5


# --- suppress_encoded_runs --------------------------------------------
# A single inline data: URI can carry tens of KB of base64 on one line,
# which in a bounded preview costs the whole line budget (and an agent's
# context) while conveying nothing readable.


def test_suppress_replaces_long_base64_run():
    import base64

    blob = base64.b64encode(bytes(range(256))).decode()
    text = f'<img src="data:image/png;base64,{blob}">'

    out, n = suppress_encoded_runs(text)

    assert n == 1
    assert blob not in out
    assert f"[{len(blob):,} chars of encoded data suppressed]" in out
    # A leading fragment survives, so a PNG blob stays tellable from an SVG.
    assert blob[:8] in out
    assert len(out) < len(text)


def test_suppress_leaves_short_runs_alone():
    # Below the threshold the data-vs-token call is unreliable, and the
    # cost of being wrong outweighs the noise.
    short = "a" * (ENCODED_RUN_MIN_LENGTH - 1)
    out, n = suppress_encoded_runs(short)

    assert n == 0
    assert out == short


def test_suppress_catches_long_hex_hash():
    # 'a'/'e' are hex digits, so a hash scores deceptively vowel-rich —
    # pure hex needs its own check.
    sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    out, n = suppress_encoded_runs(f"checksum: {sha256}")

    assert n == 1
    assert sha256 not in out


def test_suppress_catches_base64_of_repetitive_data():
    # Regression: b64 of repeated bytes is "eHh4eHh4..." at a ~33% vowel
    # rate, which passes the prose heuristic. Length alone must settle it.
    import base64

    blob = base64.b64encode(b"x" * 300).decode()
    out, n = suppress_encoded_runs(blob)

    assert n == 1
    assert "suppressed" in out


@pytest.mark.parametrize(
    "text",
    [
        "The quick brown fox jumps over the lazy dog and keeps on running along",
        "supercalifragilisticexpialidociousandthensomemorewordshere",
        "some_very_long_descriptive_function_name_for_testing_purposes_here",
        "https://cdn.example.com/assets/EEPbqgguP7Rn9CUG33Na3a-1200-80.jpg",
        "an-article-slug-with-quite-a-few-hyphenated-words-strung-together",
        "a94064512ab34cd9f0e1b2c3d4e5f60718293a4b",  # sha1: under the threshold
        # Regression: a long URL slug matched as one run when `-` was in
        # the character class, and got suppressed as data.
        "https://example.com/interviews/after-revisiting-the-fourth-season-"
        "ratings-with-cast-comments-on-watching-episodes-together-and-the-"
        "cancellation-more",
        "a_very_long_snake_case_identifier_name_that_goes_on_and_on_here_yes",
    ],
)
def test_suppress_does_not_touch_ordinary_text(text):
    out, n = suppress_encoded_runs(text)

    assert n == 0
    assert out == text


def test_suppress_counts_multiple_runs():
    import base64

    a = base64.b64encode(bytes(range(200))).decode()
    b = base64.b64encode(bytes(range(100, 250))).decode()
    out, n = suppress_encoded_runs(f"one {a} two {b} three")

    assert n == 2
    assert "one" in out and "two" in out and "three" in out
