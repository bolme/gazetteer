from __future__ import annotations

import fnmatch
import os
import statistics
from collections import defaultdict

import click

from gazetteer import report, walk
from gazetteer.walk import WalkEntry

_LIMIT_OPTIONS = [
    click.option("--max-seconds", default=30.0, show_default=True, help="Wall-clock budget."),
    click.option("--max-entries", default=1_000_000, show_default=True, help="Filesystem entries visited."),
    click.option("--max-rows", default=50, show_default=True, help="Rows printed."),
    click.option("--max-depth", default=None, type=int, help="Depth to scope the walk to."),
]

_SIZE_HELP = (
    "Only include files matching this size. Prefix with >, >=, <, <=, "
    "or nothing for exact (e.g. --size '>1M', --size '<=2k'). "
    "Repeatable; combine two for a range, e.g. --size '>1M' --size '<10M'."
)


def _validate_size_filters(ctx, param, value):
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
        callback=_validate_size_filters,
        help=_SIZE_HELP,
    ),
]


def limit_options(f):
    for option in reversed(_LIMIT_OPTIONS):
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


@click.group()
@click.version_option()
def main() -> None:
    """gaz — bounded structural queries for huge directory trees."""


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@limit_options
@filter_options
def ext(
    path: str,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    extensions: tuple[str, ...],
    patterns: tuple[str, ...],
    size_filters: tuple[str, ...],
) -> None:
    """File-extension breakdown: count, total size, median size."""
    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
    )

    sizes_by_ext: dict[str, list[int]] = defaultdict(list)
    for entry in result.entries:
        if entry.is_dir:
            continue
        if not matches_filters(entry, extensions, patterns, size_filters):
            continue
        _, dot_ext = os.path.splitext(entry.name)
        sizes_by_ext[dot_ext.lower() or "(none)"].append(entry.size)

    rows = []
    for extension, sizes in sizes_by_ext.items():
        total = sum(sizes)
        median = int(statistics.median(sizes))
        rows.append((extension, len(sizes), total, median))
    rows.sort(key=lambda r: r[2], reverse=True)

    truncated_rows = [
        (extension, count, report.human_size(total), report.human_size(median))
        for extension, count, total, median in rows[:max_rows]
    ]
    click.echo(report.render_table(truncated_rows, ("ext", "count", "total_size", "median_size")))
    click.echo()
    click.echo(report.status_line(result, max_seconds=max_seconds))


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@limit_options
@filter_options
def tree(
    path: str,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    extensions: tuple[str, ...],
    patterns: tuple[str, ...],
    size_filters: tuple[str, ...],
) -> None:
    """Depth-limited structure with per-directory file counts and sizes."""
    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
    )

    stats: dict[str, list[int]] = defaultdict(list)
    for entry in result.entries:
        if entry.is_dir:
            continue
        if not matches_filters(entry, extensions, patterns, size_filters):
            continue
        stats[entry.parent].append(entry.size)

    rows = [(dir_path, len(sizes), sum(sizes)) for dir_path, sizes in stats.items()]
    rows.sort(key=lambda r: r[2], reverse=True)

    truncated_rows = [
        (dir_path, n_files, report.human_size(total))
        for dir_path, n_files, total in rows[:max_rows]
    ]
    click.echo(report.render_table(truncated_rows, ("dir", "n_files", "total_size")))
    click.echo()

    matched_files = sum(len(sizes) for sizes in stats.values())
    matched_bytes = sum(sum(sizes) for sizes in stats.values())
    if extensions or patterns or size_filters:
        click.echo(
            f"Total (matching filter): {result.n_dirs:,} dirs walked, "
            f"{matched_files:,} files, {report.human_size(matched_bytes)}"
        )
    else:
        click.echo(
            f"Total: {result.n_dirs:,} dirs, {result.n_files:,} files, "
            f"{report.human_size(result.n_bytes)}"
        )
    click.echo(report.status_line(result, max_seconds=max_seconds))


@main.command()
@click.argument("pattern")
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@limit_options
@click.option(
    "--ext",
    "extensions",
    multiple=True,
    help="Only include files with this extension (e.g. --ext .jpg). Repeatable.",
)
@click.option(
    "--size",
    "size_filters",
    multiple=True,
    callback=_validate_size_filters,
    help=_SIZE_HELP,
)
def find(
    pattern: str,
    path: str,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    extensions: tuple[str, ...],
    size_filters: tuple[str, ...],
) -> None:
    """Bounded search, filtering during the walk rather than after it."""
    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
    )

    matches = [
        e for e in result.entries
        if fnmatch.fnmatch(e.name, pattern) and matches_filters(e, extensions, (), size_filters)
    ]
    truncated = matches[:max_rows]

    rows = [(m.path, "dir" if m.is_dir else "file", report.human_size(m.size)) for m in truncated]
    click.echo(report.render_table(rows, ("path", "type", "size")))
    click.echo()
    click.echo(report.status_line(result, max_seconds=max_seconds))


if __name__ == "__main__":
    main()
