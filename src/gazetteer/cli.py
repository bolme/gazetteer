from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass

import click

from gazetteer import frontier, preview_cli, report, walk
from gazetteer.filters import (
    SIZE_HELP,
    filter_options,
    full_path_option,
    limit_options,
    matches_filters,
    traversal_options,
    validate_size_filters,
)
from gazetteer.walk import WalkEntry

# Directory basenames that gaz dup --skip-vendored excludes: common
# package-manager/dependency install directories where duplicate files
# are a byproduct of how packages ship, not something a user can safely
# reclaim by deleting one copy.
VENDORED_DIR_NAMES = (
    "node_modules",
    "site-packages",
    ".venv",
    "venv",
    "vendor",
    "bower_components",
    ".tox",
    "target",  # Rust/Java/Maven/Cargo build output
)


class FindCommand(click.Command):
    """gaz find takes PATTERN positionally, unlike --pattern on every other
    command — a user who's just used --pattern elsewhere and tries it here
    hits a generic "no such option" error that reads as a missing feature
    rather than a deliberate, differently-shaped argument. Point at the
    actual fix instead of the default message.
    """

    def parse_args(self, ctx, args):
        if "--pattern" in args:
            raise click.UsageError(
                "find takes PATTERN as a positional argument, not --pattern: "
                "gaz find PATTERN [PATH]  (e.g. gaz find '*.jpg' /data)",
                ctx=ctx,
            )
        return super().parse_args(ctx, args)


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
    exclude: tuple[str, ...],
    json_output: bool,
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
        exclude=exclude,
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
        sizes_by_ext[report.extension_of(entry.name)].append(entry.size)

    rows = []
    for extension, sizes in sizes_by_ext.items():
        total = sum(sizes)
        median = int(statistics.median(sizes))
        rows.append((extension, len(sizes), total, median))
    rows.sort(key=lambda r: r[2], reverse=True)

    matched_files = sum(len(sizes) for sizes in sizes_by_ext.values())
    matched_bytes = sum(sum(sizes) for sizes in sizes_by_ext.values())
    is_filtered = bool(extensions or patterns or size_filters)

    if json_output:
        json_rows = [
            {"ext": extension, "count": count, "total_size": total, "median_size": median}
            for extension, count, total, median in report.limit_rows(rows, max_rows)
        ]
        click.echo(
            report.json_output(
                result,
                json_rows,
                total={"files": matched_files, "bytes": matched_bytes, "filtered": is_filtered},
            )
        )
        return

    shown = report.limit_rows(rows, max_rows)
    truncated_rows = [
        (extension, count, report.human_size(total), report.human_size(median))
        for extension, count, total, median in shown
    ]
    click.echo(report.render_table(truncated_rows, ("ext", "count", "total_size", "median_size")))
    click.echo()

    if len(shown) < len(rows):
        click.echo(f"Showing {len(shown):,} of {len(rows):,} extensions.")
    click.echo(
        f"{report.total_label(result, filtered=is_filtered)}: "
        f"{matched_files:,} files, {report.human_size(matched_bytes)}"
    )
    click.echo(report.status_line(result, max_seconds=max_seconds, max_entries=max_entries))


# gaz list's sortable/displayable columns. Each maps to a key function
# over a ListRow; "name" sorts ascending (alphabetical), every other key
# sorts descending by default since "biggest/newest first" is the useful
# reading for sizes and dates.
LIST_SORT_KEYS = {
    "name": lambda r: r.name.lower(),
    "size": lambda r: r.size,
    "files": lambda r: r.n_files,
    "modified": lambda r: r.mtime,
    "created": lambda r: r.ctime,
}

# Columns beyond the always-on ones, addable via --fields.
LIST_OPTIONAL_FIELDS = ("created", "dirs", "path")


@dataclass
class ListRow:
    """One line of `gaz list` output — a direct child of the listed dir."""

    name: str          # display name, "src/" for dirs
    path: str          # absolute path
    is_dir: bool
    n_files: int       # files anywhere beneath (subtree), or 1 for a file
    n_dirs: int        # subdirectories anywhere beneath
    size: int          # allocated bytes beneath (or own), what `du` reports
    apparent_size: int  # summed st_size — differs on sparse/cloud files
    mtime: float
    ctime: float
    complete: bool     # False if this dir's subtree wasn't fully scanned


# Registered as "list" but named list_dir in Python — `list` is a builtin,
# and shadowing it in module scope is exactly the kind of thing that bites
# someone later.
@main.command("list")
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--sort",
    "sort_key",
    type=click.Choice(sorted(LIST_SORT_KEYS)),
    default="name",
    show_default=True,
    help="Column to sort by. Directories are always listed before files.",
)
@click.option(
    "--reverse",
    is_flag=True,
    help="Reverse the sort order.",
)
@click.option(
    "--fields",
    "extra_fields",
    multiple=True,
    type=click.Choice(LIST_OPTIONAL_FIELDS),
    help=(
        "Add an optional column: created (creation/change date), dirs "
        "(subdirectory count), path (full path alongside the name). "
        "Repeatable."
    ),
)
@full_path_option
@limit_options
@traversal_options
@filter_options
def list_dir(
    path: str,
    sort_key: str,
    reverse: bool,
    extra_fields: tuple[str, ...],
    full_paths: bool,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    exclude: tuple[str, ...],
    json_output: bool,
    depth_first: bool,
    shuffle: bool,
    seed: int | None,
    extensions: tuple[str, ...],
    patterns: tuple[str, ...],
    size_filters: tuple[str, ...],
) -> None:
    """List a directory's contents, with subtree totals for each subdirectory.

    Like `ls`, but every subdirectory reports how many files and how many
    bytes live anywhere beneath it — the question `ls` can't answer and
    `du` only answers for directories. One level only: rows are the direct
    children of PATH, never a nested listing.
    """
    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
        exclude=exclude,
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
    )

    root = os.path.abspath(path)
    is_filtered = bool(extensions or patterns or size_filters)

    # Every directory's parent, so a file's size can be walked up to
    # whichever top-level child of root contains it.
    parent_of = {e.path: e.parent for e in result.entries if e.is_dir}

    def top_level_ancestor(dir_path: str) -> str | None:
        """The direct child of root that contains dir_path (or itself)."""
        current = dir_path
        while current != root:
            parent = parent_of.get(current)
            if parent is None:
                return None
            if parent == root:
                return current
            current = parent
        return None

    # Aggregate every matching file into the top-level child containing it.
    subtree_files: dict[str, int] = defaultdict(int)
    subtree_bytes: dict[str, int] = defaultdict(int)
    subtree_apparent: dict[str, int] = defaultdict(int)
    subtree_dirs: dict[str, int] = defaultdict(int)
    direct_children: list[WalkEntry] = []
    matched_files = 0
    matched_bytes = 0

    for entry in result.entries:
        if entry.parent == root:
            direct_children.append(entry)
        if entry.is_dir:
            ancestor = top_level_ancestor(entry.path)
            if ancestor is not None and entry.path != ancestor:
                subtree_dirs[ancestor] += 1
            continue
        if not matches_filters(entry, extensions, patterns, size_filters):
            continue
        matched_files += 1
        matched_bytes += entry.size
        if entry.parent == root:
            continue
        ancestor = top_level_ancestor(entry.parent)
        if ancestor is not None:
            subtree_files[ancestor] += 1
            subtree_bytes[ancestor] += entry.size
            subtree_apparent[ancestor] += entry.apparent_size

    # A subdirectory's totals are only trustworthy if its whole subtree was
    # scanned — same rule gaz empty uses. Anything unscanned beneath it
    # makes its numbers a lower bound, flagged with a trailing "+".
    unknown_dirs = {d for d in parent_of if d not in result.scanned_dirs}
    for d in list(unknown_dirs):
        current = parent_of.get(d)
        while current and current not in unknown_dirs:
            unknown_dirs.add(current)
            if current == root:
                break
            current = parent_of.get(current)

    rows: list[ListRow] = []
    for entry in direct_children:
        if entry.is_dir:
            rows.append(
                ListRow(
                    name=entry.name + "/",
                    path=entry.path,
                    is_dir=True,
                    n_files=subtree_files.get(entry.path, 0),
                    n_dirs=subtree_dirs.get(entry.path, 0),
                    size=subtree_bytes.get(entry.path, 0),
                    apparent_size=subtree_apparent.get(entry.path, 0),
                    mtime=entry.mtime,
                    ctime=entry.ctime,
                    complete=entry.path not in unknown_dirs,
                )
            )
        elif matches_filters(entry, extensions, patterns, size_filters):
            rows.append(
                ListRow(
                    name=entry.name,
                    path=entry.path,
                    is_dir=False,
                    n_files=1,
                    n_dirs=0,
                    size=entry.size,
                    apparent_size=entry.apparent_size,
                    mtime=entry.mtime,
                    ctime=entry.ctime,
                    complete=True,
                )
            )

    # Directories first, then the chosen key. "name" reads best ascending;
    # sizes/counts/dates read best largest-or-newest first, so they default
    # to descending and --reverse flips whichever default applies.
    descending = sort_key != "name"
    if reverse:
        descending = not descending
    key_fn = LIST_SORT_KEYS[sort_key]
    rows.sort(key=key_fn, reverse=descending)
    rows.sort(key=lambda r: not r.is_dir)

    shown = report.limit_rows(rows, max_rows)

    if json_output:
        json_rows = []
        for row in shown:
            json_row = {
                "name": row.name,
                # Always absolute: a consumer's cwd is not gaz's cwd.
                "path": row.path,
                "type": "dir" if row.is_dir else "file",
                "n_files": row.n_files,
                "n_dirs": row.n_dirs,
                "size": row.size,
                "apparent_size": row.apparent_size,
                "mtime": row.mtime,
                "complete": row.complete,
            }
            if "created" in extra_fields:
                json_row["ctime"] = row.ctime
            json_rows.append(json_row)
        click.echo(
            report.json_output(
                result,
                json_rows,
                total={
                    "dirs": result.n_dirs,
                    "files": matched_files,
                    "bytes": matched_bytes,
                    "filtered": is_filtered,
                    "sort": sort_key,
                },
            )
        )
        return

    headers = ["name", "n_files"]
    if "dirs" in extra_fields:
        headers.append("n_dirs")
    headers += ["size", "modified"]
    if "created" in extra_fields:
        headers.append("created")
    if "path" in extra_fields and not full_paths:
        headers.append("path")

    table_rows = []
    for row in shown:
        # A trailing "*" on the name marks a directory whose subtree wasn't
        # fully scanned — every number on that row is a floor, not a total.
        # Marking the row once beats repeating a flag on each numeric cell.
        name = (
            report.display_path(row.path, root, full_paths=True, is_dir=row.is_dir)
            if full_paths
            else row.name
        )
        if not row.complete:
            name += "*"
        # Counts are a directory question; a plain file's "1 file, 0 dirs"
        # is noise, so those cells stay blank and the eye goes to the dirs.
        cells = [
            name,
            f"{row.n_files:,}" if row.is_dir else "-",
        ]
        if "dirs" in extra_fields:
            cells.append(f"{row.n_dirs:,}" if row.is_dir else "-")
        cells += [
            report.human_size(row.size),
            report.human_date(row.mtime),
        ]
        if "created" in extra_fields:
            cells.append(report.human_date(row.ctime))
        if "path" in extra_fields and not full_paths:
            cells.append(os.path.realpath(row.path))
        table_rows.append(tuple(cells))

    click.echo(report.render_table(table_rows, tuple(headers)))
    click.echo()

    if len(shown) < len(rows):
        click.echo(f"Showing {len(shown):,} of {len(rows):,} entries.")
    dirs_label = "dirs walked" if is_filtered else "dirs"
    click.echo(
        f"{report.total_label(result, filtered=is_filtered)}: "
        f"{result.n_dirs:,} {dirs_label}, {matched_files:,} files, "
        f"{report.human_size(matched_bytes)}"
    )
    if any(not r.complete for r in shown):
        click.echo(
            "* marks a directory whose subtree wasn't fully scanned — its "
            "counts and sizes are lower bounds, not totals."
        )
    click.echo(report.status_line(result, max_seconds=max_seconds, max_entries=max_entries))


@main.command(cls=FindCommand)
@click.argument("pattern")
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@full_path_option
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
    full_paths: bool,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    exclude: tuple[str, ...],
    json_output: bool,
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
        exclude=exclude,
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
    )
    root = os.path.abspath(path)

    matches = [
        e for e in result.entries
        if fnmatch.fnmatch(e.name, pattern) and matches_filters(e, extensions, (), size_filters)
    ]
    truncated = report.limit_rows(matches, max_rows)

    if json_output:
        json_rows = [
            {"path": m.path, "type": "dir" if m.is_dir else "file", "size": m.apparent_size}
            for m in truncated
        ]
        click.echo(report.json_output(result, json_rows, total={"matches": len(matches)}))
        return

    rows = [
        (
            report.display_path(m.path, root, full_paths=full_paths, is_dir=m.is_dir),
            "dir" if m.is_dir else "file",
            report.human_size(m.apparent_size),
        )
        for m in truncated
    ]
    click.echo(report.render_table(rows, ("path", "type", "size")))
    click.echo()
    if len(truncated) < len(matches):
        click.echo(f"Showing {len(truncated):,} of {len(matches):,} matches.")
    click.echo(report.status_line(result, max_seconds=max_seconds, max_entries=max_entries))


_EXT_COLUMN_WIDTH = 30


def _top_extensions_cell(counts: dict[str, int], total: int, width: int = _EXT_COLUMN_WIDTH) -> str:
    """The top extension with its percentage, followed by as many bare
    extension names as fit within `width` characters — e.g. ".jpg(52%)
    .png .xml". Only the top entry carries a percentage: repeating "(NN%)"
    on every entry ate space that could instead list one more real
    extension, and the top share is the one number that's usually worth
    knowing at a glance. No "+N other" suffix either, for the same
    reason — the adjacent ext-types column already states that count."""
    if not counts or total <= 0:
        return ""
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top_ext, top_count = ranked[0]
    if top_count == total:
        return top_ext[:width]
    parts = [f"{top_ext}({top_count / total:.0%})"]
    used = len(parts[0])
    for ext, _count in ranked[1:]:
        added = len(ext) + 1  # +1 for the joining space
        if used + added > width:
            break
        parts.append(ext)
        used += added
    return " ".join(parts)


def _top_owner_cell(counts: dict, total: int) -> str:
    """The single top owner, with a "(NN%)" suffix only when they don't
    own everything — e.g. "alice" at 100%, otherwise "alice(80%)". Only
    one name is ever shown: who else touched a directory is rarely as
    actionable as who owns most of it, and one name keeps the column
    narrow without needing its own width cap."""
    if not counts or total <= 0:
        return ""
    top_name, top_count = max(counts.items(), key=lambda kv: kv[1])
    if top_count == total:
        return top_name
    return f"{top_name}({top_count / total:.0%})"


_username_cache: dict[int, str] = {}


def _username(uid: int) -> str:
    """Resolve a uid to a username, once per uid per process. Falls back
    to the bare uid (e.g. "1000") if the platform has no pwd database
    (Windows) or the uid isn't in it (a deleted user, a container image
    built for a different host) — better than crashing a whole `gaz
    sample` run over a single unresolvable owner."""
    if uid in _username_cache:
        return _username_cache[uid]
    name = str(uid)
    try:
        import pwd

        name = pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError):
        pass
    _username_cache[uid] = name
    return name


# gaz sample's sortable columns. Each maps to a key function over
# (entry, SampleResult). Ranking uses estimate_* rather than
# lower_bound_* for size/files/dirs: a huge subtree that's only 10%
# scanned still has a lower_bound far below a tiny fully-scanned one, so
# sorting by the raw floor would rank "probably huge" below "definitely
# tiny" -- estimate_* is the best-available number for ranking regardless
# of completeness, exactly the number the row displays as "~M" (or the
# exact total when the row is exact, since estimate == lower_bound then).
SAMPLE_SORT_KEYS = {
    "name": lambda pair: pair[0].name.lower(),
    "size": lambda pair: pair[1].estimate_bytes,
    "files": lambda pair: pair[1].estimate_files,
    "dirs": lambda pair: pair[1].estimate_dirs,
    "activity": lambda pair: pair[1].newest_mtime or 0.0,
}


def _is_real_dir(entry: os.DirEntry) -> bool:
    """True for an entry gaz sample scans as a directory -- a symlink is
    always a file row instead, regardless of what it points at (never
    descended into), matching the convention walk.py/gaz list use."""
    return entry.is_dir(follow_symlinks=False) and not entry.is_symlink()


def _file_sample_result(entry: os.DirEntry) -> frontier.SampleResult | None:
    """A synthetic, already-exact SampleResult for a plain file directly
    inside PATH -- gaz sample's rows come from FrontierSampler.run(),
    which only ever samples directories, so a loose file at the top
    level needs its own trivial "result" built directly from one stat()
    call instead of a sampler. Its own size/mtime/owner are already the
    complete answer -- there's nothing left to scan. Returns None if the
    file can't be stat'd (permission error, vanished mid-listing), same
    as a directory that fails to scan contributing nothing rather than
    crashing the whole command.
    """
    try:
        stat_result = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    size = walk.entry_size(stat_result)
    ext = report.extension_of(entry.name)
    uid = stat_result.st_uid
    return frontier.SampleResult(
        exact=True,
        lower_bound_bytes=size,
        lower_bound_files=1,
        lower_bound_dirs=0,
        estimate_bytes=float(size),
        estimate_files=1.0,
        estimate_dirs=0.0,
        lower_bound_ext_bytes={ext: size},
        lower_bound_ext_files={ext: 1},
        lower_bound_owner_bytes={uid: size},
        lower_bound_owner_files={uid: 1},
        newest_mtime=stat_result.st_mtime,
        lower_bound_denied=0,
        completeness=1.0,
        n_scans=0,
        n_errors=0,
        elapsed=0.0,
        stop_reason=None,
    )


_SAMPLE_FIRST_PASS_FRACTION = 0.33
# One round-robin slice per incomplete subdirectory, small enough that a
# fast-finishing directory near the end of the queue doesn't have to wait
# for a slow one's whole share before getting its next turn, but not so
# small that per-call overhead (scandir setup, Python call overhead)
# starts to dominate actual scanning time.
_SAMPLE_ROUND_ROBIN_SLICE_SECONDS = 0.25


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--max-seconds",
    default=30.0,
    show_default=True,
    help=(
        "Total wall-clock budget for the whole command, shared across "
        "every immediate subdirectory of PATH — not a per-subdirectory "
        "budget. 33% is divided equally across all subdirectories first "
        "(so small subtrees reliably finish), then the remainder is "
        "round-robined across whichever subdirectories are still "
        "incomplete until this budget runs out."
    ),
)
@full_path_option
@click.option(
    "--sort",
    "sort_key",
    type=click.Choice(sorted(SAMPLE_SORT_KEYS)),
    default="name",
    show_default=True,
    help="Column to sort by.",
)
@click.option(
    "--reverse",
    is_flag=True,
    help="Reverse the sort order.",
)
@click.option(
    "--max-rows",
    default=50,
    show_default=True,
    help="Rows printed. 0 means show every row.",
)
@click.option(
    "--seed",
    default=None,
    type=int,
    help="Seed for the frontier's random directory selection, for a reproducible scan order.",
)
@click.option(
    "--rank-by",
    "rank_by",
    type=click.Choice(("size", "count")),
    default="size",
    show_default=True,
    help=(
        "Rank the ext and owner columns by total bytes or by file count. "
        "Size is usually the more useful question (\"what's actually "
        "using the space\"), so it's the default; --rank-by count "
        "switches both columns to file counts instead."
    ),
)
@click.option(
    "--fields",
    "extra_fields",
    multiple=True,
    type=click.Choice(("owners",)),
    help=(
        "Add an optional column: owners (top file owner, ranked by "
        "--rank-by, e.g. \"alice(80%)\", with no percentage shown if "
        "they own everything — off by default since resolving usernames "
        "is extra width most runs don't need). Repeatable, though "
        "there's currently only one."
    ),
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Print a bounded JSON object instead of a text table.",
)
def sample(
    path: str,
    max_seconds: float,
    full_paths: bool,
    sort_key: str,
    reverse: bool,
    max_rows: int,
    seed: int | None,
    rank_by: str,
    extra_fields: tuple[str, ...],
    json_output: bool,
) -> None:
    """Estimate each immediate subdirectory's size via frontier sampling.

    For trees too large for `gaz list` to finish walking. Scans each
    subdirectory of PATH with a frontier-based sampler that never re-reads
    the same directory twice (see docs/sample-estimation.md for the
    algorithm and why it behaves the way it does), sharing one total
    --max-seconds budget across all of them: 33% divided equally up front
    so small subtrees reliably finish, then the rest round-robined across
    whatever's left incomplete until time runs out — this keeps total
    runtime predictable regardless of how many subdirectories PATH has,
    unlike giving each one its own fixed budget. Plain files directly
    inside PATH are listed too (like `gaz list`), with no scanning
    needed — a file's own size/owner/mtime is already the complete
    answer, so those rows are always exact. Every directory row reports
    three numbers rather than one:

    \b
    - exact, if the subdirectory's entire subtree was scanned in time —
      the reported size and file count are then the true totals, not an
      estimate.
    - a lower bound: the sum of every file byte actually counted so far.
      Always a true floor, never inflated by extrapolation.
    - an estimate: a completeness-weighted recursive projection beyond the
      lower bound. This number can be biased, sometimes substantially, at
      partial coverage — see docs/sample-estimation.md — so it is always
      shown next to the lower bound, never alone, and the gap between
      them is itself a signal of how much to trust it.

    The dirs column follows the same lower-bound/estimate split as files
    and size. "ext types" is how many distinct file extensions were
    found; "ext" packs in as many "ext(NN%)" entries as fit in 30
    characters, ranked by --rank-by (bytes by default, or file count with
    --rank-by count), with a bare extension name when it's the only one
    present. "activity" shows how long ago the most recently modified
    file in the subtree was touched (e.g. "2d ago"). All three are always
    an exact tally/observation of files actually scanned so far, never
    extrapolated the way the size/files/dirs estimate is, since guessing
    at an *unscanned* directory's likely extension mix, file ownership,
    or recency would be a much shakier claim than guessing at its total
    size. `--fields owners` adds one more column in the same spirit — the
    single top file owner, ranked the same way, with a percentage only
    shown below 100% (e.g. "alice(80%)") — off by default since it's
    extra width most runs don't need.

    --sort ranks by the estimate (or the exact total, when a row is
    exact) rather than the lower bound, so a huge-but-partially-scanned
    subdirectory is still ranked as huge rather than as small just
    because little of it has been counted yet.

    A "denied" column appears automatically, only when at least one
    subdirectory hit a permission error — it never shows for a tree gaz
    can read all of. It counts directories anywhere in that row's
    subtree that couldn't be opened (PermissionError specifically, not
    any failure), so a row can be exact (every directory it *could* open
    was fully scanned) while still reporting a nonzero denied count.

    After the table, a summary reports how much work the whole command
    actually did: total directories and files visited and how long it
    took, then a grand total across every row. If every subdirectory
    finished exactly, the total is one number; if any didn't, it's
    split into what's confirmed (the sum of every row's lower bound —
    still a true floor) and what's estimated (the sum of every row's
    estimate — the same number shown per-row, just added up).

    This is not a replacement for `gaz list` on a tree that finishes
    walking comfortably inside a normal budget — it exists for the trees
    that don't.
    """
    root = os.path.abspath(path)
    try:
        with os.scandir(root) as it:
            entries = list(it)
    except OSError as e:
        raise click.ClickException(f"cannot read {path}: {e}")

    subdirs = sorted((e for e in entries if _is_real_dir(e)), key=lambda e: e.name)
    files = sorted(
        (e for e in entries if not _is_real_dir(e)),
        key=lambda e: e.name,
    )

    samplers = [frontier.FrontierSampler(seed=seed) for _ in subdirs]
    command_start = time.monotonic()

    if subdirs:
        # First pass: divide a third of the total budget equally across
        # every subdirectory, so a small subtree reliably finishes here
        # regardless of how large or slow its siblings are — a shared
        # round-robin budget alone could starve a fast, small directory
        # of even the little time it needs if it happened to be scanned
        # last.
        first_pass_each = (max_seconds * _SAMPLE_FIRST_PASS_FRACTION) / len(subdirs)
        for entry, sampler in zip(subdirs, samplers):
            sampler.run(entry.path, max_seconds=first_pass_each)

        # Second pass: round-robin whatever's left of the total budget
        # across subdirectories that aren't exact yet, in small slices —
        # this is what keeps overall runtime bounded by --max-seconds
        # regardless of subdirectory count (unlike a fixed per-directory
        # budget, which scales total runtime with the number of
        # subdirectories) while still letting a slow subtree make
        # incremental progress across many rounds instead of getting one
        # single uninterruptible turn.
        while time.monotonic() - command_start < max_seconds:
            incomplete = [
                (entry, sampler)
                for entry, sampler in zip(subdirs, samplers)
                if not sampler.is_exhausted
            ]
            if not incomplete:
                break
            for entry, sampler in incomplete:
                remaining = max_seconds - (time.monotonic() - command_start)
                if remaining <= 0:
                    break
                slice_seconds = min(_SAMPLE_ROUND_ROBIN_SLICE_SECONDS, remaining)
                sampler.run(entry.path, max_seconds=slice_seconds)

    rows = [(entry, sampler.current_result()) for entry, sampler in zip(subdirs, samplers)]
    for entry in files:
        result = _file_sample_result(entry)
        if result is not None:
            rows.append((entry, result))
    # "name" reads best ascending; every other key reads best
    # biggest/most-recent first, matching gaz list's --sort convention.
    descending = sort_key != "name"
    if reverse:
        descending = not descending
    rows.sort(key=SAMPLE_SORT_KEYS[sort_key], reverse=descending)

    if json_output:
        json_rows = [
            {
                "name": entry.name,
                # Always absolute: a consumer's cwd is not gaz's cwd.
                "path": entry.path,
                "type": "dir" if _is_real_dir(entry) else "file",
                "exact": result.exact,
                "lower_bound_bytes": result.lower_bound_bytes,
                "lower_bound_files": result.lower_bound_files,
                "lower_bound_dirs": result.lower_bound_dirs,
                "estimate_bytes": result.estimate_bytes,
                "estimate_files": result.estimate_files,
                "estimate_dirs": result.estimate_dirs,
                # Exact tallies of scanned files only -- never
                # extrapolated, unlike estimate_bytes/estimate_files. See
                # frontier.SampleResult's docstring.
                "ext_bytes": result.lower_bound_ext_bytes,
                "ext_files": result.lower_bound_ext_files,
                "newest_mtime": result.newest_mtime,
                # uid -> bytes/files; JSON always includes this (unlike
                # the text table, where it's --fields owners-gated) since
                # a JSON consumer can just ignore keys it doesn't want,
                # and resolving uids to usernames is a text-table-only
                # display concern, not a data-shape one.
                "owner_bytes": result.lower_bound_owner_bytes,
                "owner_files": result.lower_bound_owner_files,
                "denied": result.lower_bound_denied,
                "completeness": result.completeness,
                "n_scans": result.n_scans,
                "n_errors": result.n_errors,
                "stop_reason": result.stop_reason,
            }
            for entry, result in rows
        ]
        shown = report.limit_rows(json_rows, max_rows)
        # Not report.json_output: that envelope's shape (n_dirs/n_files/
        # elapsed at the top level) describes one shared WalkResult, but
        # sample has no single walk -- every row is its own independent
        # frontier scan with its own completeness. Rather than populate
        # those fields with meaningless zeros, this command's envelope
        # only claims what's actually true here: each row's own data,
        # plus a top-level rollup of how many DIRECTORY rows came back
        # exact -- files are always exact (nothing to scan), so counting
        # them here would inflate the ratio with entries never at risk
        # of being partial.
        dir_json_rows = [r for r in json_rows if r["type"] == "dir"]
        click.echo(
            json.dumps(
                {
                    "rows": shown,
                    "complete": all(r["exact"] for r in dir_json_rows),
                    "subdirs": len(dir_json_rows),
                    "exact_subdirs": sum(1 for r in dir_json_rows if r["exact"]),
                },
                indent=2,
            )
        )
        return

    show_owners = "owners" in extra_fields
    # The denied column only appears when at least one subdirectory (not
    # just the ones actually shown after --max-rows) hit a permission
    # error -- most trees never do, and a column that's almost always
    # "0" or blank is pure noise most of the time.
    show_denied = any(result.lower_bound_denied > 0 for _, result in rows)
    now = time.time()
    shown = report.limit_rows(rows, max_rows)
    table_rows = []
    for entry, result in shown:
        is_dir_row = _is_real_dir(entry)
        name = (
            report.display_path(entry.path, root, full_paths=True, is_dir=is_dir_row)
            if full_paths
            else entry.name + ("/" if is_dir_row else "")
        )
        # A leading marker (not a trailing suffix) so it stands out at the
        # left edge, where the eye actually scans first — buried at the
        # end of a long path it's easy to miss. Every row gets a
        # two-character prefix so names still start in the same column
        # regardless of which marker (if any) applies:
        #   "- " a directory this row's subtree hit a permission error
        #        in -- takes priority over "*" since "gaz couldn't even
        #        read part of this" is a more specific, more actionable
        #        fact than "the scan ran out of time."
        #   "* " row wasn't fully scanned within budget, no denials
        #   "  " row is both exact and has nothing denied
        if result.exact:
            size_cell = report.human_size(result.lower_bound_bytes)
            files_cell = f"{result.lower_bound_files:,}"
            dirs_cell = f"{result.lower_bound_dirs:,}"
        else:
            size_cell = (
                f"{report.human_size(result.lower_bound_bytes)}+ "
                f"(~{report.human_size(int(result.estimate_bytes))})"
            )
            files_cell = f"{result.lower_bound_files:,}+ (~{result.estimate_files:,.0f})"
            dirs_cell = f"{result.lower_bound_dirs:,}+ (~{result.estimate_dirs:,.0f})"
        if result.lower_bound_denied > 0:
            name = "- " + name
        elif result.exact:
            name = "  " + name
        else:
            name = "* " + name
        # Extension/activity/owner data are always the exact scanned-so-
        # far tally or observation (see SampleResult's docstring) even on
        # an incomplete row -- no "+"/"~" markers here, since these are
        # already honestly scoped to "of what's been counted," not
        # claiming to describe the whole subtree.
        activity_cell = (
            report.human_duration(now - result.newest_mtime) + " ago"
            if result.newest_mtime is not None
            else "-"
        )
        # --rank-by picks bytes or file counts as the ranking basis for
        # BOTH the ext and owner columns, so the two stay consistent with
        # each other within a run instead of one always being by size
        # and the other always by count.
        if rank_by == "count":
            ext_counts, ext_total = result.lower_bound_ext_files, result.lower_bound_files
            owner_counts_raw, owner_total = (
                result.lower_bound_owner_files,
                result.lower_bound_files,
            )
        else:
            ext_counts, ext_total = result.lower_bound_ext_bytes, result.lower_bound_bytes
            owner_counts_raw, owner_total = (
                result.lower_bound_owner_bytes,
                result.lower_bound_bytes,
            )
        ext_types_cell = f"{len(result.lower_bound_ext_files):,}" if result.lower_bound_files else "-"
        ext_cell = _top_extensions_cell(ext_counts, ext_total)
        row_cells = [name, files_cell, dirs_cell, size_cell, activity_cell, ext_types_cell, ext_cell]
        if show_denied:
            # Blank rather than "0" for a row with no denials of its own,
            # so the handful of rows that actually hit permission errors
            # stand out at a glance against an otherwise-empty column.
            denied_cell = f"{result.lower_bound_denied:,}" if result.lower_bound_denied else ""
            row_cells.insert(3, denied_cell)
        if show_owners:
            owner_counts = {_username(uid): count for uid, count in owner_counts_raw.items()}
            row_cells.append(_top_owner_cell(owner_counts, owner_total))
        table_rows.append(tuple(row_cells))

    headers = ["name", "files", "dirs", "size", "activity", "ext types", "ext"]
    if show_denied:
        headers.insert(3, "denied")
    if show_owners:
        headers.append("owner")
    click.echo(report.render_table(table_rows, tuple(headers)))
    click.echo()

    if len(shown) < len(rows):
        click.echo(f"Showing {len(shown):,} of {len(rows):,} entries.")
    # Files are always exact (a stat() has nothing left to estimate), so
    # counting them here would inflate both sides of the ratio with
    # entries that were never at risk of being partial -- this line is
    # specifically about how the (potentially slow) directory sampling
    # went, not a status line for the whole table.
    dir_rows = [r for e, r in rows if _is_real_dir(e)]
    n_exact = sum(1 for r in dir_rows if r.exact)
    click.echo(f"{n_exact:,} of {len(dir_rows):,} subdirectories fully scanned (exact).")
    if n_exact < len(dir_rows):
        click.echo(
            "* marks a subdirectory that wasn't fully scanned within the "
            f"{max_seconds:g}s total --max-seconds budget: \"N+ (~M)\" "
            "means N is a true lower bound and M is a rough, "
            "possibly-biased estimate of the real total — see "
            "docs/sample-estimation.md. Re-run with a larger "
            "--max-seconds for a tighter lower bound."
        )

    # Directories "visited" is lower_bound_dirs (everything BENEATH each
    # row) plus one per row for the row's own directory, which was
    # necessarily scanned to produce a result at all. Files visited is
    # exactly lower_bound_files, with no "+1" needed -- unlike a
    # directory, a file IS the leaf, so nothing is scanned "beneath" it.
    total_dirs_visited = sum(r.lower_bound_dirs + 1 for r in dir_rows)
    total_lower_bytes = sum(r.lower_bound_bytes for _, r in rows)
    total_lower_files = sum(r.lower_bound_files for _, r in rows)
    elapsed = time.monotonic() - command_start
    click.echo(
        f"Scanned {total_dirs_visited:,} dirs / {total_lower_files:,} "
        f"files in {elapsed:.1f}s."
    )

    if n_exact == len(dir_rows):
        # Every directory finished, so the estimate is identical to the
        # lower bound everywhere -- stating both would just repeat the
        # same number twice for no reason.
        click.echo(
            f"Total: {total_lower_files:,} files, "
            f"{report.human_size(total_lower_bytes)}."
        )
    else:
        total_estimate_bytes = sum(r.estimate_bytes for _, r in rows)
        total_estimate_files = sum(r.estimate_files for _, r in rows)
        click.echo(
            f"Total: {total_lower_files:,} files, "
            f"{report.human_size(total_lower_bytes)} confirmed "
            f"(~{total_estimate_files:,.0f} files, "
            f"~{report.human_size(int(total_estimate_bytes))} estimated)."
        )


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--min-size",
    "min_size",
    default=None,
    help=(
        "Ignore files smaller than this (e.g. 10M). Cheap pre-filter for "
        "huge trees — a file below the bound can't be in the top N anyway."
    ),
)
@click.option(
    "--apparent",
    is_flag=True,
    help=(
        "Rank by apparent size (st_size) instead of disk space used. "
        "Surfaces sparse files and cloud placeholders, which occupy far "
        "fewer blocks than their length suggests."
    ),
)
@full_path_option
@limit_options
@traversal_options
@filter_options
def largest(
    path: str,
    min_size: str | None,
    apparent: bool,
    full_paths: bool,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    exclude: tuple[str, ...],
    json_output: bool,
    depth_first: bool,
    shuffle: bool,
    seed: int | None,
    extensions: tuple[str, ...],
    patterns: tuple[str, ...],
    size_filters: tuple[str, ...],
) -> None:
    """The biggest individual files anywhere beneath PATH.

    `gaz list` ranks a directory's immediate children; this ranks single
    files across the whole subtree — the `du -a | sort -rn | head` answer.
    `--max-rows` is the N (default 50).

    Sizes are disk space used, so the total is what deleting the listed
    files would actually reclaim. Pass --apparent to rank by file length
    instead, which is what surfaces sparse and cloud-placeholder files.
    """
    if min_size is not None:
        try:
            min_bytes = report.parse_size(min_size)
        except ValueError as e:
            raise click.BadParameter(str(e), param_hint="--min-size")
    else:
        min_bytes = 0

    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
        exclude=exclude,
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
    )
    root = os.path.abspath(path)

    def rank_size(entry: WalkEntry) -> int:
        return entry.apparent_size if apparent else entry.size

    candidates = [
        e for e in result.entries
        if not e.is_dir
        and rank_size(e) >= min_bytes
        and matches_filters(e, extensions, patterns, size_filters)
    ]
    candidates.sort(key=rank_size, reverse=True)

    shown = report.limit_rows(candidates, max_rows)
    # Totals describe every candidate, not just the rows printed — the
    # same "aggregation continues past --max-rows" rule the other
    # commands follow.
    matched_bytes = sum(rank_size(e) for e in candidates)
    shown_bytes = sum(rank_size(e) for e in shown)
    is_filtered = bool(extensions or patterns or size_filters or min_bytes)

    if json_output:
        json_rows = [
            {
                "path": e.path,
                "size": e.size,
                "apparent_size": e.apparent_size,
                "mtime": e.mtime,
            }
            for e in shown
        ]
        click.echo(
            report.json_output(
                result,
                json_rows,
                total={
                    "files": len(candidates),
                    "bytes": matched_bytes,
                    "shown_bytes": shown_bytes,
                    "filtered": is_filtered,
                    "ranked_by": "apparent_size" if apparent else "size",
                },
            )
        )
        return

    rows = [
        (
            report.human_size(rank_size(e)),
            report.human_date(e.mtime),
            report.display_path(e.path, root, full_paths=full_paths),
        )
        for e in shown
    ]
    # Size first: the whole question is "what's big," and a leading size
    # column stays scannable however long the paths get.
    click.echo(report.render_table(rows, ("size", "modified", "path")))
    click.echo()

    if len(shown) < len(candidates):
        click.echo(
            f"Showing {len(shown):,} of {len(candidates):,} files "
            f"({report.human_size(shown_bytes)} of "
            f"{report.human_size(matched_bytes)})."
        )
    click.echo(
        f"{report.total_label(result, filtered=is_filtered)}: "
        f"{len(candidates):,} files, {report.human_size(matched_bytes)}"
    )
    click.echo(report.status_line(result, max_seconds=max_seconds, max_entries=max_entries))


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--older-than",
    "older_than",
    default="90d",
    show_default=True,
    help="Only include files last modified more than this long ago (e.g. 90d, 6h, 2w, 1y).",
)
@full_path_option
@limit_options
@traversal_options
@filter_options
def stale(
    path: str,
    older_than: str,
    full_paths: bool,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    exclude: tuple[str, ...],
    json_output: bool,
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
        exclude=exclude,
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
    )
    root = os.path.abspath(path)

    now = time.time()
    stale_entries = [
        e
        for e in result.entries
        if not e.is_dir
        and (now - e.mtime) >= min_age
        and matches_filters(e, extensions, patterns, size_filters)
    ]
    stale_entries.sort(key=lambda e: e.mtime)

    truncated = report.limit_rows(stale_entries, max_rows)
    total_bytes = sum(e.size for e in stale_entries)
    is_filtered = bool(extensions or patterns or size_filters)
    n_suspicious = sum(1 for e in stale_entries if report.is_suspicious_mtime(e.mtime))

    if json_output:
        json_rows = [
            {
                "path": e.path,
                "age_seconds": now - e.mtime,
                "size": e.apparent_size,
                "suspicious_mtime": report.is_suspicious_mtime(e.mtime),
            }
            for e in truncated
        ]
        click.echo(
            report.json_output(
                result,
                json_rows,
                total={
                    "files": len(stale_entries),
                    "bytes": total_bytes,
                    "older_than": older_than,
                    "filtered": is_filtered,
                    "n_suspicious_mtime": n_suspicious,
                },
            )
        )
        return

    rows = [
        (
            report.display_path(e.path, root, full_paths=full_paths),
            report.human_duration(now - e.mtime)
            + (" (?)" if report.is_suspicious_mtime(e.mtime) else ""),
            report.human_size(e.apparent_size),
        )
        for e in truncated
    ]
    click.echo(report.render_table(rows, ("path", "age", "size")))
    click.echo()

    if len(truncated) < len(stale_entries):
        click.echo(f"Showing {len(truncated):,} of {len(stale_entries):,} files.")
    click.echo(
        f"{report.total_label(result, filtered=is_filtered)}: "
        f"{len(stale_entries):,} files older than {older_than}, "
        f"{report.human_size(total_bytes)}"
    )

    if n_suspicious:
        click.echo(
            f"(?) {n_suspicious:,} file(s) have a timestamp within a week of "
            f"the Unix epoch — likely a reset by another tool (a cache, "
            f"archive, or sync tool), not a genuinely old file."
        )

    click.echo(report.status_line(result, max_seconds=max_seconds, max_entries=max_entries))


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@full_path_option
@limit_options
@traversal_options
def empty(
    path: str,
    full_paths: bool,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    exclude: tuple[str, ...],
    json_output: bool,
    depth_first: bool,
    shuffle: bool,
    seed: int | None,
) -> None:
    """Directories containing no files anywhere in their subtree.

    A directory is only reported as empty if its entire subtree was
    actually scanned — one merely *discovered* (an entry of a scanned
    parent) but not itself explored before the walk stopped is reported
    separately as "unvisited," never mislabeled empty.
    """
    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
        exclude=exclude,
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

    # A dir's subtree is only fully known if the dir itself was scanned AND
    # every subdirectory it contains is also fully known (recursively) —
    # an unscanned child could be hiding a file that would make this
    # directory non-empty (whether it's unscanned because the walk's
    # budget ran out, or because --max-depth deliberately excluded it).
    # Propagate "unknown" up from any discovered-but-unscanned directory,
    # the same way non-emptiness propagates from files.
    unknown_dirs = {d for d in all_dirs if d not in result.scanned_dirs}
    for d in list(unknown_dirs):
        current = parent_of.get(d)
        while current and current not in unknown_dirs:
            unknown_dirs.add(current)
            if current == root:
                break
            current = parent_of.get(current)

    empty_dirs = sorted(all_dirs - non_empty_dirs - unknown_dirs)
    unvisited_dirs = sorted((all_dirs - non_empty_dirs) & unknown_dirs)
    confirmed_dirs = all_dirs - unknown_dirs
    truncated = report.limit_rows(empty_dirs, max_rows)

    if json_output:
        json_rows = [{"dir": d} for d in truncated]
        click.echo(
            report.json_output(
                result,
                json_rows,
                total={
                    "empty_dirs": len(empty_dirs),
                    "unvisited_dirs": len(unvisited_dirs),
                    "scanned_dirs": len(confirmed_dirs),
                },
            )
        )
        return

    rows = [
        (report.display_path(d, root, full_paths=full_paths, is_dir=True),)
        for d in truncated
    ]
    click.echo(report.render_table(rows, ("dir",)))
    click.echo()
    if len(truncated) < len(empty_dirs):
        click.echo(f"Showing {len(truncated):,} of {len(empty_dirs):,} directories.")
    click.echo(
        f"{len(empty_dirs):,} directories confirmed empty of "
        f"{len(confirmed_dirs):,} that were fully scanned."
    )
    if unvisited_dirs:
        if result.complete:
            # The walk itself finished; any unvisited dirs here are purely
            # a consequence of --max-depth deliberately not looking deeper.
            click.echo(
                f"Additionally, {len(unvisited_dirs):,} directories could not be "
                f"confirmed empty or non-empty because --max-depth={max_depth} "
                f"kept their subtree out of scope."
            )
        else:
            click.echo(
                f"Additionally, {len(unvisited_dirs):,} directories could not be "
                f"confirmed empty or non-empty because the walk stopped before "
                f"their full subtree was scanned — not counted above, and not "
                f"shown as a false positive."
            )
    click.echo(report.status_line(result, max_seconds=max_seconds, max_entries=max_entries))


@main.command()
@click.argument("path", default=".", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--max-hash-seconds",
    default=30.0,
    show_default=True,
    help="Separate wall-clock budget for the hashing pass (after the walk completes).",
)
@click.option(
    "--skip-vendored",
    is_flag=True,
    help=(
        "Skip common package-manager/dependency directories (e.g. "
        f"{', '.join(VENDORED_DIR_NAMES[:4])}, ...) — duplicates inside "
        "them usually can't be reclaimed without breaking the installed "
        "environment, so they're just noise in the results. Combines with "
        "--exclude rather than replacing it."
    ),
)
@full_path_option
@limit_options
@traversal_options
@filter_options
def dup(
    path: str,
    max_hash_seconds: float,
    skip_vendored: bool,
    full_paths: bool,
    max_seconds: float,
    max_entries: int,
    max_rows: int,
    max_depth: int | None,
    exclude: tuple[str, ...],
    json_output: bool,
    depth_first: bool,
    shuffle: bool,
    seed: int | None,
    extensions: tuple[str, ...],
    patterns: tuple[str, ...],
    size_filters: tuple[str, ...],
) -> None:
    """Duplicate files by content hash — grouped by size first, then hashed."""
    if skip_vendored:
        exclude = tuple(exclude) + VENDORED_DIR_NAMES
    result = walk.walk(
        path,
        max_seconds=max_seconds,
        max_entries=max_entries,
        max_depth=max_depth,
        exclude=exclude,
        depth_first=depth_first,
        shuffle=shuffle,
        seed=seed,
    )
    root = os.path.abspath(path)

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
    total_reclaimable = sum(group[0].size * (len(group) - 1) for group in dup_groups)

    if json_output:
        json_rows = [
            {
                # `path` is the first copy, kept for compatibility; `paths`
                # is every copy in the set, which is what a caller deciding
                # what to delete actually needs.
                "path": group[0].path,
                "paths": [e.path for e in group],
                "copies": len(group),
                "size_each": group[0].size,
                "reclaimable": group[0].size * (len(group) - 1),
            }
            for group in report.limit_rows(dup_groups, max_rows)
        ]
        click.echo(
            report.json_output(
                result,
                json_rows,
                complete=result.complete and hash_complete,
                total={
                    "duplicate_sets": len(dup_groups),
                    "reclaimable_bytes": total_reclaimable,
                    "hash_complete": hash_complete,
                    "hash_stop_reason": hash_stop_reason,
                    "n_hashed": n_hashed,
                },
            )
        )
        return

    # Every copy is listed, not just a representative: the question `dup`
    # answers is "what can I delete," and that needs the other copies'
    # paths. Sets are separated by a blank line and each set's numbers
    # appear once, above its paths — a flat table would repeat copies/
    # size_each on every row and lose which paths belong together.
    shown_groups = report.limit_rows(dup_groups, max_rows)
    lines = []
    for group in shown_groups:
        reclaimable = group[0].size * (len(group) - 1)
        lines.append(
            f"{len(group)} copies × {report.human_size(group[0].size)} "
            f"= {report.human_size(reclaimable)} reclaimable"
        )
        for e in group:
            lines.append(
                f"    {report.display_path(e.path, root, full_paths=full_paths)}"
            )
        lines.append("")
    if lines:
        click.echo("\n".join(lines))

    if len(shown_groups) < len(dup_groups):
        click.echo(
            f"Showing {len(shown_groups):,} of {len(dup_groups):,} duplicate sets."
        )

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
    click.echo(report.status_line(result, max_seconds=max_seconds, max_entries=max_entries))


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
