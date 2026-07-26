from __future__ import annotations

import fnmatch
import hashlib
import os
import statistics
import time
from collections import defaultdict

import click

from gazetteer import preview_cli, report, walk
from gazetteer.filters import (
    SIZE_HELP,
    filter_options,
    limit_options,
    matches_filters,
    traversal_options,
    validate_size_filters,
)
from gazetteer.walk import WalkEntry


@click.group()
@click.version_option(package_name="gaz")
def main() -> None:
    """gaz — bounded structural queries for huge directory trees."""


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@limit_options
@traversal_options
@filter_options
def ext(
    path: str,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    depth_first: bool,
    shuffle: bool,
    seed: int | None,
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
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
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

    matched_files = sum(len(sizes) for sizes in sizes_by_ext.values())
    matched_bytes = sum(sum(sizes) for sizes in sizes_by_ext.values())
    is_filtered = bool(extensions or patterns or size_filters)
    click.echo(
        f"{report.total_label(result, filtered=is_filtered)}: "
        f"{matched_files:,} files, {report.human_size(matched_bytes)}"
    )
    click.echo(report.status_line(result, max_seconds=max_seconds))


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@limit_options
@traversal_options
@filter_options
def tree(
    path: str,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    depth_first: bool,
    shuffle: bool,
    seed: int | None,
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
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
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
    is_filtered = bool(extensions or patterns or size_filters)
    dirs_label = "dirs walked" if is_filtered else "dirs"
    click.echo(
        f"{report.total_label(result, filtered=is_filtered)}: "
        f"{result.n_dirs:,} {dirs_label}, {matched_files:,} files, "
        f"{report.human_size(matched_bytes)}"
    )
    click.echo(report.status_line(result, max_seconds=max_seconds))


@main.command()
@click.argument("pattern")
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@limit_options
@traversal_options
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
    callback=validate_size_filters,
    help=SIZE_HELP,
)
def find(
    pattern: str,
    path: str,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    depth_first: bool,
    shuffle: bool,
    seed: int | None,
    extensions: tuple[str, ...],
    size_filters: tuple[str, ...],
) -> None:
    """Bounded search, filtering during the walk rather than after it."""
    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
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


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--older-than",
    "older_than",
    default="90d",
    show_default=True,
    help="Only include files last modified more than this long ago (e.g. 90d, 6h, 2w, 1y).",
)
@limit_options
@traversal_options
@filter_options
def stale(
    path: str,
    older_than: str,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    depth_first: bool,
    shuffle: bool,
    seed: int | None,
    extensions: tuple[str, ...],
    patterns: tuple[str, ...],
    size_filters: tuple[str, ...],
) -> None:
    """Files not modified in a while — candidates for cleanup or archival."""
    try:
        min_age = report.parse_duration(older_than)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="'--older-than'")

    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
    )

    now = time.time()
    stale_entries = [
        e
        for e in result.entries
        if not e.is_dir
        and (now - e.mtime) >= min_age
        and matches_filters(e, extensions, patterns, size_filters)
    ]
    stale_entries.sort(key=lambda e: e.mtime)

    truncated = stale_entries[:max_rows]
    rows = [
        (e.path, report.human_duration(now - e.mtime), report.human_size(e.size))
        for e in truncated
    ]
    click.echo(report.render_table(rows, ("path", "age", "size")))
    click.echo()

    total_bytes = sum(e.size for e in stale_entries)
    is_filtered = bool(extensions or patterns or size_filters)
    click.echo(
        f"{report.total_label(result, filtered=is_filtered)}: "
        f"{len(stale_entries):,} files older than {older_than}, "
        f"{report.human_size(total_bytes)}"
    )
    click.echo(report.status_line(result, max_seconds=max_seconds))


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@limit_options
@traversal_options
def empty(
    path: str,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    depth_first: bool,
    shuffle: bool,
    seed: int | None,
) -> None:
    """Directories containing no files anywhere in their subtree."""
    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
    )

    root = os.path.abspath(path)
    parent_of = {e.path: e.parent for e in result.entries if e.is_dir}
    all_dirs = set(parent_of) | {root}

    # A dir is empty (of files) if no file exists anywhere under it. Walk up
    # from each dir that directly contains a file and mark every ancestor
    # up to the root as non-empty.
    non_empty_dirs = set()
    for e in result.entries:
        if e.is_dir:
            continue
        current = e.parent
        while current and current not in non_empty_dirs:
            non_empty_dirs.add(current)
            if current == root:
                break
            current = parent_of.get(current)

    empty_dirs = sorted(all_dirs - non_empty_dirs)
    truncated = empty_dirs[:max_rows]

    rows = [(d,) for d in truncated]
    click.echo(report.render_table(rows, ("dir",)))
    click.echo()
    click.echo(f"{report.total_label(result)}: {len(empty_dirs):,} empty directories")
    if not result.complete:
        click.echo(
            "Warning: the walk stopped early, so some directories listed as empty "
            "may simply be unvisited rather than truly empty, and there may be "
            "more empty directories beyond what was walked."
        )
    click.echo(report.status_line(result, max_seconds=max_seconds))


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--max-hash-seconds",
    default=30.0,
    show_default=True,
    help="Separate wall-clock budget for the hashing pass (after the walk completes).",
)
@limit_options
@traversal_options
@filter_options
def dup(
    path: str,
    max_hash_seconds: float,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    depth_first: bool,
    shuffle: bool,
    seed: int | None,
    extensions: tuple[str, ...],
    patterns: tuple[str, ...],
    size_filters: tuple[str, ...],
) -> None:
    """Duplicate files by content hash — grouped by size first, then hashed."""
    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
    )

    candidates = [
        e
        for e in result.entries
        if not e.is_dir and e.size > 0 and matches_filters(e, extensions, patterns, size_filters)
    ]

    by_size: dict[int, list[WalkEntry]] = defaultdict(list)
    for e in candidates:
        by_size[e.size].append(e)
    size_groups = [group for group in by_size.values() if len(group) > 1]

    hash_start = time.monotonic()
    hash_complete = True
    hash_stop_reason = None
    by_hash: dict[tuple[int, str], list[WalkEntry]] = defaultdict(list)
    n_hashed = 0

    for group in size_groups:
        for e in group:
            if time.monotonic() - hash_start >= max_hash_seconds:
                hash_complete = False
                hash_stop_reason = f"{max_hash_seconds}s hashing limit"
                break
            digest = _hash_file(e.path)
            if digest is not None:
                by_hash[(e.size, digest)].append(e)
                n_hashed += 1
        else:
            continue
        break

    dup_groups = [group for group in by_hash.values() if len(group) > 1]
    dup_groups.sort(key=lambda group: group[0].size * len(group), reverse=True)

    rows = []
    for group in dup_groups[:max_rows]:
        reclaimable = group[0].size * (len(group) - 1)
        rows.append((
            group[0].path,
            len(group),
            report.human_size(group[0].size),
            report.human_size(reclaimable),
        ))

    click.echo(report.render_table(rows, ("path (first copy)", "copies", "size_each", "reclaimable")))
    click.echo()

    total_reclaimable = sum(group[0].size * (len(group) - 1) for group in dup_groups)
    if not result.complete:
        incomplete_reason = "walk stopped early"
    else:
        incomplete_reason = "hashing stopped early"
    label = report.total_label(
        result,
        complete=result.complete and hash_complete,
        incomplete_reason=incomplete_reason,
    )
    click.echo(
        f"{label}: {len(dup_groups):,} duplicate sets, "
        f"{report.human_size(total_reclaimable)} reclaimable"
    )

    if hash_complete:
        click.echo(f"Hashed {n_hashed:,} candidate files. Complete.")
    else:
        suggested = max(int(max_hash_seconds * 10), int(max_hash_seconds) + 30, 60)
        click.echo(
            f"Hashing stopped at the {hash_stop_reason} after {n_hashed:,} of "
            f"{sum(len(g) for g in size_groups):,} same-size candidates. "
            f"Duplicate sets below are a lower bound. Re-run with --max-hash-seconds "
            f"{suggested} for a fuller picture."
        )
    click.echo(report.status_line(result, max_seconds=max_seconds))


def _hash_file(path: str, chunk_size: int = 1024 * 1024) -> str | None:
    """SHA-256 of a file's contents, or None if it can't be read."""
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


main.add_command(preview_cli.preview)
main.add_command(preview_cli.convert_cmd)


if __name__ == "__main__":
    main()
