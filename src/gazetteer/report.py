"""Table and status-line rendering.

Plain aligned text by default; every command's output ends with a one-line
natural-language status describing whether the result is complete.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

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


def human_date(timestamp: float) -> str:
    """Render a timestamp as a compact YYYY-MM-DD date.

    Date-only (no clock time): `tree`'s date columns exist to answer "how
    fresh is this directory," a question a date answers and a timestamp
    only makes wider. `stale` still uses human_duration for relative ages.
    """
    if timestamp <= 0:
        return "-"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


# Below this length, an encoded-looking run is shown verbatim: it's
# cheap, and at short lengths the "is this data or a real word?" call is
# unreliable enough that showing it is the safer error. A git SHA (40) or
# a UUID-ish token stays visible; a data: URI payload does not.
ENCODED_RUN_MIN_LENGTH = 64

# How much of a suppressed run to keep as a recognizable fragment. Enough
# to identify what it is (a PNG data URI and an SVG one differ in their
# first few characters) without spending a line on it.
_ENCODED_FRAGMENT = 16

# Runs of base64/hex-ish characters. Deliberately not anchored to `data:`
# URIs — the same flood arrives as inline SVG payloads, embedded font
# blobs, JWTs, checksums in a manifest, and base64 in a JSON field. The
# character class is standard base64's alphabet, which is a superset of
# hex, so one pattern covers both.
#
# `-` and `_` are deliberately excluded even though base64url uses them:
# including them made a long URL slug
# ("after-revisiting-fbi-international-season-4-ratings-...") match as a
# single 132-char run and get suppressed as data. Hyphens and underscores
# are how human-readable identifiers separate words, so treating them as
# run *boundaries* costs a little base64url coverage (those runs still
# get caught in their inter-separator chunks, and the vowel test flags
# them) and buys back every slug, kebab-case name, and snake_case
# identifier in previewed text.
_ENCODED_RUN_RE = re.compile(r"[A-Za-z0-9+/]{%d,}={0,2}" % ENCODED_RUN_MIN_LENGTH)

# Natural text rarely produces a long unbroken alphanumeric run, but when
# it does it's usually a real word or identifier rather than encoded data.
# Requiring a mix of cases *or* digits, plus a low vowel rate, separates
# "supercalifragilisticexpialidocious" and a long snake_case identifier
# from "PHN2ZyBjbGFzcz0iaWNvbi1zdmciIGhlaWdodD0i".
_VOWELS = set("aeiouAEIOU")
_HEX_CHARS = set("0123456789abcdefABCDEF")


# Past this length, an unbroken run is treated as data regardless of how
# its characters happen to score. No natural-language word or identifier
# runs this long without a space, hyphen, or underscore, and base64 of
# repetitive input can otherwise mimic prose statistics — b64 of 300 'x'
# bytes is "eHh4eHh4..." at a 33% vowel rate, indistinguishable from
# English by that measure alone.
_ENCODED_CERTAIN_LENGTH = 120


def _looks_encoded(run: str) -> bool:
    """True if `run` looks like encoded data rather than a long word."""
    if len(run) >= _ENCODED_CERTAIN_LENGTH:
        return True

    # Pure hex is checked on its own: 'a'/'e' are hex digits, so a long
    # hash scores misleadingly vowel-rich under the test below. At this
    # length an all-hex run is a hash or a blob, never a word.
    if all(c in _HEX_CHARS for c in run):
        return True

    has_digit = any(c.isdigit() for c in run)
    has_upper = any(c.isupper() for c in run)
    has_lower = any(c.islower() for c in run)
    if not (has_digit or (has_upper and has_lower)):
        return False
    letters = [c for c in run if c.isalpha()]
    if not letters:
        return True  # all digits/symbols — a hash or an ID, not prose
    vowel_rate = sum(1 for c in letters if c in _VOWELS) / len(letters)
    # English runs ~38% vowels; base64 lands far below that.
    return vowel_rate < 0.26


def suppress_encoded_runs(text: str) -> tuple[str, int]:
    """Replace long base64/hex-looking runs with a short placeholder.

    Returns (text, n_suppressed). A single inline image can carry tens of
    kilobytes of base64 in one line, which in a *bounded* preview is
    strictly destructive: it costs the whole line budget (and, for an
    agent, the context window) while conveying nothing a human or model
    can read. The placeholder keeps what's actually informative — that
    encoded data was here, how much, and enough of a fragment to tell a
    PNG from an SVG.

    Runs shorter than ENCODED_RUN_MIN_LENGTH are left alone; below that
    the distinction between data and a legitimate token is too unreliable
    to act on, and the cost of being wrong is higher than the noise.
    """
    n_suppressed = 0

    def replace(match: re.Match) -> str:
        nonlocal n_suppressed
        run = match.group(0)
        if not _looks_encoded(run):
            return run
        n_suppressed += 1
        return f"{run[:_ENCODED_FRAGMENT]}… [{len(run):,} chars of encoded data suppressed]"

    return _ENCODED_RUN_RE.sub(replace, text), n_suppressed


# Threshold for is_suspicious_mtime: within a week of the Unix epoch. Wide
# enough to catch "reset to exactly 0" and the handful of nearby values
# some tools use (e.g. 1 for FAT's "no timestamp"), narrow enough that a
# genuinely ancient real file (uncommon, but not impossible on old media)
# isn't misflagged.
_EPOCH_SUSPECT_WINDOW = 7 * 86400


def is_suspicious_mtime(mtime: float) -> bool:
    """True if `mtime` looks like a reset artifact rather than a real file age.

    `gaz stale` reports whatever st_mtime the OS gives it — that's correct
    by definition, not a bug — but a timestamp reset to (or near) the Unix
    epoch by some other tool (common with certain caches, archives, or sync
    tools) is indistinguishable from a genuinely decades-old file unless
    it's called out, and gaz presenting it silently reads as "gaz is
    wrong" rather than "this file's timestamp is wrong."
    """
    return abs(mtime) <= _EPOCH_SUSPECT_WINDOW


def limit_rows(rows: list, max_rows: int) -> list:
    """Truncate `rows` to `max_rows`, or return every row when max_rows == 0.

    Unlike --max-seconds/--max-entries, --max-rows stays on by default
    (it's the guard against flooding a terminal or an LLM's context
    window, which matters regardless of how fast the walk itself was) —
    but it's still explicitly turn-off-able for someone who wants every
    row printed, via --max-rows 0.
    """
    return rows if max_rows == 0 else rows[:max_rows]


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


def total_label(
    result: WalkResult,
    *,
    filtered: bool = False,
    complete: bool | None = None,
    incomplete_reason: str = "walk stopped early",
) -> str:
    """Label for a command's 'Total: ...' line, qualified when the underlying data is incomplete.

    A total computed from a truncated walk (or, for commands with a second
    budgeted pass like `dup`'s hashing, a truncated second pass) is a lower
    bound, not the real total, so the label itself must say so — the status
    line's "lower bound" note talks about the walk's raw dirs/files count,
    not this total. Pass `complete=` to fold in a second pass's own
    completeness (defaults to the walk's), and `incomplete_reason=` so the
    label names whichever pass actually stopped early.
    """
    is_complete = result.complete if complete is None else complete
    parts = ["Total"]
    if filtered:
        parts.append("matching filter")
    if not is_complete:
        parts.append(f"at least, {incomplete_reason}")
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} ({', '.join(parts[1:])})"


def status_line(result: WalkResult, *, max_seconds: float, max_entries: int = 0) -> str:
    """Build the one-line completeness status required by every command.

    The re-run suggestion names whichever budget actually stopped the walk
    (read from result.stop_reason) rather than always pointing at
    --max-seconds — suggesting a bigger time budget does nothing if
    --max-entries was the real constraint. Since max_seconds=0 and
    max_entries=0 both now mean "unlimited," the only way either limit
    appears in stop_reason is if it was already a positive, active value
    — so "suggest a bigger number" always makes sense here, never a
    suggestion to raise an already-unlimited budget.
    """
    dirs = f"{result.n_dirs:,}"
    files = f"{result.n_files:,}"

    if result.complete:
        line = f"Scanned {dirs} dirs / {files} files in {result.elapsed:.1f}s. Complete."
    else:
        reason = result.stop_reason or ""
        # "entries" is checked as its own category first since "entries
        # limit" also contains the substring "s limit" ("entrie-s limit").
        is_entries_stop = "entries" in reason
        is_time_stop = not is_entries_stop and "s limit" in reason

        if is_entries_stop and max_entries > 0:
            suggestion = f"--max-entries {max_entries * 10}"
        elif is_time_stop and max_seconds > 0:
            suggestion = f"--max-seconds {int(max_seconds * 10)}"
        else:
            # Either not a budget at all (e.g. "cannot stat root: ..."),
            # or the caller's max_entries/max_seconds doesn't match what
            # the walk actually used (e.g. 0/unlimited) -- no bigger
            # number to suggest, so say nothing rather than something
            # wrong like "--max-entries 0" (which means *unlimited*, the
            # opposite of "bigger").
            suggestion = None
        line = f"Stopped at the {result.stop_reason} after {dirs} dirs / {files} files. "
        line += "Numbers below are a lower bound."
        if suggestion:
            line += f" Re-run with {suggestion} for a fuller picture."

    if result.n_errors:
        line += f" ({result.n_errors:,} unreadable paths skipped.)"

    return line


def json_output(
    result: WalkResult,
    rows: list[dict],
    *,
    total: dict,
    complete: bool | None = None,
) -> str:
    """Bounded structured-output envelope, shared by every command's --json.

    Same completeness contract as the plain-text output — `rows` is
    already truncated by the caller via `limit_rows` (--max-rows applies
    identically either way, so piping into `jq`/`xargs` can't silently
    see more than the terminal would), and `complete`/`stop_reason` carry
    the same "don't treat a partial result as exhaustive" signal that the
    text status line gives a human. `total` is command-specific (e.g.
    ext's {"files": N, "bytes": N}) since each command aggregates
    differently; `complete` defaults to the walk's own completeness but
    can be overridden for a command with a second budgeted pass (like
    dup's hashing), matching `total_label`'s `complete=` parameter.
    """
    is_complete = result.complete if complete is None else complete
    return json.dumps(
        {
            "rows": rows,
            "complete": is_complete,
            "stop_reason": result.stop_reason,
            "n_dirs": result.n_dirs,
            "n_files": result.n_files,
            "n_errors": result.n_errors,
            "elapsed": result.elapsed,
            "total": total,
        },
        indent=2,
    )
