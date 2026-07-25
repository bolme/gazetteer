from __future__ import annotations

import os
import statistics
from collections import defaultdict

import click

from gazetteer import report, walk

_LIMIT_OPTIONS = [
    click.option("--max-seconds", default=30.0, show_default=True, help="Wall-clock budget."),
    click.option("--max-entries", default=1_000_000, show_default=True, help="Filesystem entries visited."),
    click.option("--max-rows", default=50, show_default=True, help="Rows printed."),
    click.option("--max-depth", default=None, type=int, help="Depth to scope the walk to."),
]


def limit_options(f):
    for option in reversed(_LIMIT_OPTIONS):
        f = option(f)
    return f


@click.group()
@click.version_option()
def main() -> None:
    """gaz — bounded structural queries for huge directory trees."""


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@limit_options
def ext(path: str, max_seconds: float, max_entries: int, max_rows: int, max_depth: int | None) -> None:
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
def tree(path: str, max_seconds: float, max_entries: int, max_rows: int, max_depth: int | None) -> None:
    """Depth-limited structure with per-directory file counts and sizes."""
    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
    )

    stats: dict[str, list[int]] = defaultdict(list)
    for entry in result.entries:
        if not entry.is_dir:
            stats[entry.parent].append(entry.size)

    rows = [(dir_path, len(sizes), sum(sizes)) for dir_path, sizes in stats.items()]
    rows.sort(key=lambda r: r[2], reverse=True)

    truncated_rows = [
        (dir_path, n_files, report.human_size(total))
        for dir_path, n_files, total in rows[:max_rows]
    ]
    click.echo(report.render_table(truncated_rows, ("dir", "n_files", "total_size")))
    click.echo()
    click.echo(report.status_line(result, max_seconds=max_seconds))


@main.command()
@click.argument("pattern")
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@limit_options
def find(pattern: str, path: str, max_seconds: float, max_entries: int, max_rows: int, max_depth: int | None) -> None:
    """Bounded search, filtering during the walk rather than after it."""
    import fnmatch

    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
    )

    matches = [e for e in result.entries if fnmatch.fnmatch(e.name, pattern)]
    truncated = matches[:max_rows]

    rows = [(m.path, "dir" if m.is_dir else "file", report.human_size(m.size)) for m in truncated]
    click.echo(report.render_table(rows, ("path", "type", "size")))
    click.echo()
    click.echo(report.status_line(result, max_seconds=max_seconds))


if __name__ == "__main__":
    main()
