"""Shared --max-* budget options and --ext/--pattern/--size filter options.

Every command that walks a tree uses limit_options for its budgets, and
every command that reports on files uses filter_options plus
matches_filters to decide which walked entries to include.
"""

from __future__ import annotations

import fnmatch
import os

import click

from gazetteer import report
from gazetteer.walk import WalkEntry

_LIMIT_OPTIONS = [
    click.option(
        "--max-seconds",
        default=30.0,
        show_default=True,
        help="Wall-clock budget. 0 means unlimited (run until done).",
    ),
    click.option(
        "--max-entries",
        default=0,
        show_default=True,
        help=(
            "Filesystem entries visited. 0 (default) means unlimited — this "
            "budget is opt-in, since --max-seconds alone already protects "
            "against a run that never returns. Most useful on slow storage, "
            "where a single huge directory could burn the whole time budget."
        ),
    ),
    click.option(
        "--max-rows",
        default=50,
        show_default=True,
        help="Rows printed; aggregation continues past this. 0 means show every row.",
    ),
    click.option("--max-depth", default=None, type=int, help="Depth to scope the walk to."),
]

_TRAVERSAL_OPTIONS = [
    click.option(
        "--depth-first",
        is_flag=True,
        help=(
            "Walk depth-first instead of the default breadth-first. "
            "Breadth-first means a truncated walk still discovers every "
            "top-level directory before going deep into any one of them; "
            "depth-first exhausts the budget on the first branches instead."
        ),
    ),
    click.option(
        "--shuffle",
        is_flag=True,
        help="Randomize sibling order at each directory, so a truncated walk samples a different slice of a wide directory on each run.",
    ),
    click.option(
        "--seed",
        default=None,
        type=int,
        help="Seed for --shuffle, for a reproducible random order. Ignored without --shuffle.",
    ),
]

SIZE_HELP = (
    "Only include files matching this size. Prefix with >, >=, <, <=, "
    "or nothing for exact (e.g. --size '>1M', --size '<=2k'). "
    "Repeatable; combine two for a range, e.g. --size '>1M' --size '<10M'."
)


def validate_size_filters(ctx, param, value):
    for size_filter in value:
        try:
            report.parse_size_filter(size_filter)
        except ValueError as e:
            raise click.BadParameter(str(e), ctx=ctx, param=param)
    return value


_FILTER_OPTIONS = [
    click.option(
        "--ext",
        "extensions",
        multiple=True,
        help="Only include files with this extension (e.g. --ext .jpg). Repeatable.",
    ),
    click.option(
        "--pattern",
        "patterns",
        multiple=True,
        help="Only include files/dirs whose name matches this glob (e.g. --pattern '*.jpg'). Repeatable.",
    ),
    click.option(
        "--size",
        "size_filters",
        multiple=True,
        callback=validate_size_filters,
        help=SIZE_HELP,
    ),
]


def limit_options(f):
    for option in reversed(_LIMIT_OPTIONS):
        f = option(f)
    return f


def traversal_options(f):
    for option in reversed(_TRAVERSAL_OPTIONS):
        f = option(f)
    return f


def filter_options(f):
    for option in reversed(_FILTER_OPTIONS):
        f = option(f)
    return f


_SIZE_OPS = {
    ">": lambda size, bound: size > bound,
    ">=": lambda size, bound: size >= bound,
    "<": lambda size, bound: size < bound,
    "<=": lambda size, bound: size <= bound,
    "=": lambda size, bound: size == bound,
}


def matches_filters(
    entry: WalkEntry,
    extensions: tuple[str, ...],
    patterns: tuple[str, ...],
    size_filters: tuple[str, ...] = (),
) -> bool:
    """True if entry passes the --ext / --pattern / --size filters (AND'd together)."""
    if extensions:
        _, dot_ext = os.path.splitext(entry.name)
        normalized = {e if e.startswith(".") else f".{e}" for e in extensions}
        if dot_ext.lower() not in {e.lower() for e in normalized}:
            return False
    if patterns:
        if not any(fnmatch.fnmatch(entry.name, p) for p in patterns):
            return False
    for size_filter in size_filters:
        op, bound = report.parse_size_filter(size_filter)
        if not _SIZE_OPS[op](entry.size, bound):
            return False
    return True
