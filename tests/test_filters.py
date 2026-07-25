import pytest

from gazetteer.filters import matches_filters
from gazetteer.walk import WalkEntry


def _entry(name, size=100, is_dir=False):
    return WalkEntry(path=f"/{name}", parent="/", name=name, is_dir=is_dir, size=size, mtime=0)


def test_matches_filters_no_filters_matches_everything():
    assert matches_filters(_entry("anything.xyz"), (), ())


def test_matches_filters_ext_is_case_insensitive():
    assert matches_filters(_entry("a.JPG"), ("jpg",), ())
    assert matches_filters(_entry("a.jpg"), ("JPG",), ())


def test_matches_filters_ext_accepts_with_or_without_dot():
    assert matches_filters(_entry("a.jpg"), ("jpg",), ())
    assert matches_filters(_entry("a.jpg"), (".jpg",), ())


def test_matches_filters_multiple_ext_values_are_ored():
    assert matches_filters(_entry("a.jpg"), ("jpg", "png"), ())
    assert matches_filters(_entry("a.png"), ("jpg", "png"), ())
    assert not matches_filters(_entry("a.gif"), ("jpg", "png"), ())


def test_matches_filters_file_with_no_extension():
    assert matches_filters(_entry("README"), (), ())
    assert not matches_filters(_entry("README"), ("txt",), ())


def test_matches_filters_pattern_is_glob_not_regex():
    assert matches_filters(_entry("image_001.jpg"), (), ("image_*.jpg",))
    assert not matches_filters(_entry("other.jpg"), (), ("image_*.jpg",))


def test_matches_filters_multiple_patterns_are_ored():
    assert matches_filters(_entry("a.jpg"), (), ("*.jpg", "*.png"))
    assert matches_filters(_entry("a.png"), (), ("*.jpg", "*.png"))
    assert not matches_filters(_entry("a.gif"), (), ("*.jpg", "*.png"))


def test_matches_filters_ext_and_pattern_are_anded():
    # matches pattern but not ext -> excluded
    assert not matches_filters(_entry("photo.jpg"), ("png",), ("photo*",))
    # matches both -> included
    assert matches_filters(_entry("photo.jpg"), ("jpg",), ("photo*",))


@pytest.mark.parametrize(
    "size,size_filters,expected",
    [
        (500, (">100",), True),
        (500, (">1000",), False),
        (500, ("<1000",), True),
        (500, ("<100",), False),
        (500, (">=500",), True),
        (500, ("<=500",), True),
        (500, ("500",), True),  # bare = exact
        (500, ("501",), False),
        (500, (">100", "<1000"), True),  # range, both satisfied
        (500, (">100", "<200"), False),  # range, second clause fails
    ],
)
def test_matches_filters_size(size, size_filters, expected):
    assert matches_filters(_entry("f", size=size), (), (), size_filters) == expected


def test_matches_filters_size_zero_boundary():
    zero_file = _entry("empty", size=0)
    assert matches_filters(zero_file, (), (), ("=0",))
    assert not matches_filters(zero_file, (), (), (">0",))
    assert matches_filters(zero_file, (), (), ("<=0",))


def test_matches_filters_does_not_special_case_directories():
    # matches_filters applies the same size/ext logic to dirs; callers
    # (CLI commands) are responsible for excluding dirs where relevant.
    empty_dir = _entry("d", size=0, is_dir=True)
    assert matches_filters(empty_dir, (), (), ("=0",))
    assert not matches_filters(empty_dir, (), (), (">0",))


def test_matches_filters_invalid_size_filter_raises():
    with pytest.raises(ValueError):
        matches_filters(_entry("f"), (), (), ("bogus",))
