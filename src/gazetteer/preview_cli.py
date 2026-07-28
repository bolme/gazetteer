"""The `gaz preview` and `gaz convert` commands.

Separate from cli.py's tree-walking commands: these operate on a single
file, not a directory tree, so they route through convert.py instead of
walk.py and don't take the shared limit_options/filter_options.
"""

from __future__ import annotations

import os

import click

from gazetteer import convert, report, walk


def _metadata_header(path: str, method: str) -> str:
    """Banner shown above previewed content.

    Size/timestamps are often as useful as the content for orientation
    ("is this the file I meant, and is it current?"), and they're the one
    thing the converted text can never tell you. Uses apparent size, not
    allocated blocks: this describes the file, not its disk footprint.

    Ruled off above and below because the content underneath is arbitrary
    text — frequently Markdown with its own `#` headings — and a bare line
    of metadata would read as part of the document rather than as gaz's
    framing of it. Rules do that with plain ASCII, no markup, consistent
    with every other table gaz prints.
    """
    st = os.stat(path)
    name = os.path.basename(path)
    detail = (
        f"{report.human_size(st.st_size)}  ·  "
        f"modified {report.human_date(st.st_mtime)}  ·  "
        f"created {report.human_date(walk.entry_ctime(st))}  ·  "
        f"{method}"
    )
    width = max(len(name), len(detail))
    rule = "=" * width
    return f"{rule}\n{name}\n{detail}\n{rule}"


def _print_check_deps() -> None:
    rows = convert.check_dependencies()
    table = [
        (fmt, "yes" if usable else "NO", detail)
        for fmt, usable, detail in rows
    ]
    click.echo(report.render_table(table, ("format", "usable", "converter")))
    click.echo()
    missing = [fmt for fmt, usable, _ in rows if not usable]
    if missing:
        click.echo(
            f"{len(missing)} format(s) have no converter: {', '.join(missing)}. "
            f"Install pandoc and/or poppler, or run `pip install gaz[preview]`."
        )
    else:
        click.echo("All supported formats have a converter available.")


@click.command()
@click.argument("path", required=False, type=click.Path(exists=True, dir_okay=False))
@click.option("--max-lines", default=50, show_default=True, help="Lines of converted output to show.")
@click.option("--full", is_flag=True, help="Show the whole file, ignoring --max-lines.")
@click.option(
    "--check-deps",
    is_flag=True,
    help="Report which converter each format would use, then exit. Takes no PATH.",
)
@click.option(
    "--max-seconds",
    default=30.0,
    show_default=True,
    help="Wall-clock budget for the conversion step (e.g. a pandoc/pdftotext subprocess).",
)
def preview(
    path: str | None, max_lines: int, full: bool, check_deps: bool, max_seconds: float
) -> None:
    """Show a bounded, format-aware preview of a single file.

    Converts the file to readable text (pandoc/pdftotext for office and PDF
    formats, pretty-printing for JSON/YAML/TOML/XML/CSV, as-is for
    Markdown/plain text) and prints up to --max-lines of it, under a
    one-line header naming the file's size and timestamps.
    """
    if check_deps:
        _print_check_deps()
        return
    if path is None:
        raise click.UsageError("missing PATH (or pass --check-deps).")

    try:
        result = convert.convert_to_text(path, max_seconds=max_seconds)
    except convert.UnsupportedFormat as e:
        raise click.ClickException(str(e))

    click.echo(_metadata_header(path, result.method))
    click.echo()

    lines = result.text.splitlines()
    shown = lines if full else lines[:max_lines]
    click.echo("\n".join(shown))
    click.echo()

    if result.warning:
        click.echo(f"Warning: {result.warning}")

    # The conversion method is named in the header, so the status line
    # only has to answer "did I see all of it?"
    if not result.complete:
        click.echo(
            "Conversion did not finish. Output above may be empty or "
            "partial. Re-run with a larger --max-seconds, or use "
            "`gaz convert` to write the full result to a file."
        )
    elif full or len(shown) == len(lines):
        click.echo(f"Showing all {len(lines):,} lines. Complete.")
    else:
        click.echo(
            f"Showing {len(shown):,} of {len(lines):,} lines. "
            f"Re-run with --full to see everything, or `gaz convert` to save it to a file."
        )


@click.command("convert")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "-o", "--output", "output_path",
    required=True,
    type=click.Path(dir_okay=False),
    help="Where to write the converted file.",
)
@click.option(
    "--to", "to_format",
    default=None,
    help="Output format (e.g. md, txt, csv). Inferred from --output's extension if omitted.",
)
@click.option(
    "--max-seconds",
    default=120.0,
    show_default=True,
    help="Wall-clock budget for the conversion step.",
)
def convert_cmd(path: str, output_path: str, to_format: str | None, max_seconds: float) -> None:
    """Convert a file to text/Markdown/CSV and write the full result to OUTPUT.

    Binary formats only (docx, pptx, xlsx, pdf) — JSON/YAML/TOML/XML are
    already text, so `gaz preview` is the right tool for those; `convert`
    refuses them rather than inventing a format-translation feature.
    """
    source_format = convert.detect_format(path)
    if source_format in convert.PREVIEW_ONLY_FORMATS:
        raise click.ClickException(
            f"cannot convert .{source_format} — it's already text. "
            f"Use `gaz preview {path}` to pretty-print it instead; "
            f"`gaz convert` only handles binary formats (docx/pptx/xlsx/pdf)."
        )

    resolved_to = to_format or os.path.splitext(output_path)[1].lstrip(".")
    try:
        result = convert.convert_to_text(path, max_seconds=max_seconds, to_format=resolved_to)
    except convert.UnsupportedFormat as e:
        raise click.ClickException(str(e))

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result.text)
    except OSError as e:
        raise click.ClickException(f"cannot write {output_path!r}: {e}")

    if result.warning:
        click.echo(f"Warning: {result.warning}")

    n_bytes = len(result.text.encode("utf-8"))
    if result.complete:
        click.echo(
            f"Wrote {report.human_size(n_bytes)} to {output_path} "
            f"(method: {result.method}). Complete."
        )
    else:
        click.echo(
            f"Wrote {report.human_size(n_bytes)} to {output_path} "
            f"(method: {result.method}), but the conversion did not finish "
            f"— output is likely incomplete. Re-run with a larger --max-seconds."
        )
