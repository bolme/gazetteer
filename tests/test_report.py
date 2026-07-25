import pytest

from gazetteer.report import human_size, parse_size, parse_size_filter


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


def test_human_size_roundtrip_style():
    assert human_size(0) == "0 B"
    assert human_size(1024) == "1.0 KB"
    assert "MB" in human_size(16_500_000)
