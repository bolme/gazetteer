"""Table and status-line rendering.

Plain aligned text by default; every command's output ends with a one-line
natural-language status describing whether the result is complete.
"""

from __future__ import annotations

from gazetteer.walk import WalkResult


def human_size(n_bytes: int) -> str:
    """Render a byte count as e.g. '16.5 MB', matching -h conventions."""
    size = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def render_table(rows: list[tuple], headers: tuple[str, ...]) -> str:
    """Render rows as plain aligned text (no rich markup)."""
    widths = [len(h) for h in headers]
    str_rows = [[str(c) for c in row] for row in rows]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    lines = [fmt_row(list(headers))]
    lines.append("  ".join("-" * w for w in widths))
    lines.extend(fmt_row(row) for row in str_rows)
    return "\n".join(lines)


def status_line(result: WalkResult, *, max_seconds: float) -> str:
    """Build the one-line completeness status required by every command."""
    dirs = f"{result.n_dirs:,}"
    files = f"{result.n_files:,}"

    if result.complete:
        line = f"Scanned {dirs} dirs / {files} files in {result.elapsed:.1f}s. Complete."
    else:
        line = (
            f"Stopped at the {result.stop_reason} after {dirs} dirs / {files} files. "
            f"Numbers below are a lower bound. "
            f"Re-run with --max-seconds {int(max_seconds * 10)} for a fuller picture."
        )

    if result.n_errors:
        line += f" ({result.n_errors:,} unreadable paths skipped.)"

    return line
