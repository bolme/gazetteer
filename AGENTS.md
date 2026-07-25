# AGENTS.md

Instructions for AI coding agents working in this repository. Humans should
read [DESIGN.md](DESIGN.md) for the full rationale; this file is the
condensed, actionable version.

## Setup

```
uv venv --python 3.12
uv pip install -e ".[dev]"
```

If that leaves `gaz` raising `ModuleNotFoundError: No module named
'gazetteer'`, the environment is mangling `.pth`-based editable installs.
Use the workaround instead:

```
./scripts/reinstall-dev.sh
```

Run the test suite before and after any change:

```
pytest -q
```

## The one rule

> Every operation is bounded, and every truncated result says so.

Do not add a feature that can run unbounded. Every command that walks the
filesystem must go through `walk.py` and respect `--max-seconds`,
`--max-entries`, and `--max-rows`. Every command's final line of output must
say whether the result is complete or a lower bound, and if partial, what
stopped it and how to get further (see `report.status_line`).

## Where things live

```
src/gazetteer/
├── cli.py       # click group + command definitions only
├── walk.py      # the one bounded walker — every command routes through this
├── filters.py   # shared --max-*/--ext/--pattern/--size options + matches_filters
├── report.py    # human_size/human_duration, parsing, table + status-line rendering
└── cache.py     # SQLite store + resolution ladder (phase 2, not yet built)
tests/           # one test file per source module, plus CLI-level test files
```

- Commands never call `os.scandir` or hash files directly outside of
  `walk.py`'s traversal — if a command needs its own filesystem walk, that's
  a signal `walk.py`'s interface is wrong. Fix the walker, don't route
  around it.
- Shared CLI option definitions (`--max-seconds`, `--ext`, `--size`, ...)
  live in `filters.py`, not copy-pasted into each command in `cli.py`.
- Size/duration parsing and formatting (`parse_size`, `parse_duration`,
  `human_size`, `human_duration`) live in `report.py`, not scattered inline.
- Resist splitting a module further until it exceeds ~300 lines.

## Conventions

- **Dependencies:** `click` only (plus `pytest` for dev). Adding a runtime
  dependency requires a note in DESIGN.md explaining why.
- **Exit codes:** always `0` on a successful run, including truncated ones.
  Partial is a normal outcome, not an error — status goes in the output
  text, never the exit code.
- **Symlinks:** not followed by default (loops are common in dataset
  trees). Filesystems are not crossed by default. Don't change either
  default without updating DESIGN.md's rationale table.
- **Permission errors:** skip and count, never let one unreadable directory
  abort a multi-hour scan.
- **Output:** plain aligned text, no `rich` markup — it's compact in an
  LLM's context window. Numbers over 999 get comma grouping.
- Prefer deleting code to adding a flag.
- No progress bars, TUI, config files, plugin systems, or abstract base
  classes. See DESIGN.md's Non-goals section before proposing one.

## Testing expectations

- The walker (`walk.py`) must be tested against: a symlink loop, an
  unreadable directory, a deeply nested path, `max_depth` actually limiting
  descent, `max_seconds`/`max_entries` actually stopping the walk, a
  nonexistent root, and a root that's a file rather than a directory. See
  `tests/test_walk.py`.
- Every new command needs: a happy-path test, a test on a completely empty
  tree, and a test that its output includes the completeness/status line.
- Parsing functions (`parse_size`, `parse_size_filter`, `parse_duration`)
  need tests for malformed input, case-insensitivity, and boundary values
  (zero, exact unit thresholds) — these are exactly the inputs that produce
  silent wrong answers instead of crashes if they're broken.
- Run `pytest -q` and confirm the full suite is green before considering a
  change done. Don't skip this because "it's just a docs change" — verify
  the assumption, don't state it.

## Adding a new command

1. Does it need anything `walk.py` doesn't already give you (a `WalkResult`
   of `WalkEntry` objects)? If yes, that's usually a walker change, not a
   command-local workaround.
2. Reuse `filters.limit_options` and `filters.filter_options` for the
   standard flags unless the command has a genuine reason to diverge (see
   how `find` keeps its positional `PATTERN` argument instead of adding a
   redundant `--pattern`).
3. Print a table (`report.render_table`), then a blank line, then any
   command-specific totals line, then `report.status_line(...)` last.
4. Add tests before considering it done: happy path, empty tree, and at
   least one truncation/edge case specific to that command's logic (see
   `gaz empty`'s walk-truncated warning for an example of a truncation edge
   case that isn't just "fewer rows").
