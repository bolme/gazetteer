"""Table and status-line rendering.

Plain aligned text by default; every command's output ends with a one-line
natural-language status describing whether the result is complete.
"""

from __future__ import annotations

import re

from gazetteer.walk import WalkResult

_SIZE_UNITS = {
    "B": 1,
    "K": 1024,
    "KB": 1024,
    "M": 1024**2,
    "MB": 1024**2,
    "G": 1024**3,
    "GB": 1024**3,
    "T": 1024**4,
    "TB": 1024**4,
}

_DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 7 * 86400,
    "y": 365 * 86400,
}


def human_size(n_bytes: int) -> str:
    """Render a byte count as e.g. '16.5 MB', matching -h conventions."""
    size = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        # Round before comparing so e.g. 1023.96 KB displays as 1.0 MB
        # instead of the misleading "1024.0 KB".
        rounded = round(size, 0 if unit == "B" else 1)
        if rounded < 1024 or unit == "PB":
            return f"{rounded:.0f} {unit}" if unit == "B" else f"{rounded:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def parse_size(text: str) -> int:
    """Parse a size like '1.5M', '2k', '500', '10GB' into a byte count."""
    match = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([A-Za-z]*)\s*", text)
    if not match:
        raise ValueError(f"invalid size: {text!r}")
    number, unit = match.groups()
    unit = unit.upper() or "B"
    if unit not in _SIZE_UNITS:
        raise ValueError(f"unknown size unit {unit!r} in {text!r}")
    return int(float(number) * _SIZE_UNITS[unit])


def parse_size_filter(text: str) -> tuple[str, int]:
    """Parse a size filter expression like '>1M', '<=2k', '500' (bare = exact).

    Returns (op, bytes) where op is one of '>', '>=', '<', '<=', '='.
    """
    match = re.fullmatch(r"\s*(>=|<=|>|<|=)?\s*(.+)", text)
    if not match:
        raise ValueError(f"invalid size filter: {text!r}")
    op, size_text = match.groups()
    return (op or "="), parse_size(size_text)


def parse_duration(text: str) -> float:
    """Parse a duration like '30d', '6h', '2w', '1y' into seconds."""
    match = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([A-Za-z]*)\s*", text)
    if not match:
        raise ValueError(f"invalid duration: {text!r}")
    number, unit = match.groups()
    unit = unit.lower() or "s"
    if unit not in _DURATION_UNITS:
        raise ValueError(f"unknown duration unit {unit!r} in {text!r}")
    return float(number) * _DURATION_UNITS[unit]


def human_duration(seconds: float) -> str:
    """Render an age in seconds as e.g. '3d', '5h', '42s'."""
    seconds = abs(seconds)
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.0f}h"
    if seconds < 7 * 86400:
        return f"{seconds / 86400:.0f}d"
    if seconds < 365 * 86400:
        return f"{seconds / (7 * 86400):.0f}w"
    return f"{seconds / (365 * 86400):.1f}y"


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
