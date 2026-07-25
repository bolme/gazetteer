import pytest

from gazetteer.report import (
    human_duration,
    human_size,
    parse_duration,
    parse_size,
    parse_size_filter,
    render_table,
    status_line,
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
