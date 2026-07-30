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
`--max-entries`, `--max-rows`, and `--exclude`. Every command's final line
of output must say whether the result is complete or a lower bound, and if
partial, what stopped it and how to get further (see `report.status_line`).
`--json` output must carry the same signal as a real field (`complete`,
`stop_reason`), not just the text status line — see `report.json_output`.

`walk.py` traverses breadth-first by default specifically because of this
rule: on a truncated walk, BFS still shows the tree's overall shape (every
top-level dir before descending into any one of them) instead of complete
depth-first coverage of the first branch and nothing else. `--depth-first`
opts back into the old order; `--shuffle`/`--seed` randomize sibling order
so repeated truncated runs sample different parts of a wide directory. See
DESIGN.md's "Traversal order" section.

## Where things live

```
src/gazetteer/
├── cli.py          # click group + the eight tree-walking commands (incl. sample)
├── preview_cli.py  # the preview/convert commands (single-file, no walker)
├── walk.py         # the one bounded walker — every tree command routes through this
├── frontier.py     # gaz sample's frontier-based adaptive sampler (its own os.scandir; see below)
├── estimate.py     # unshipped random-descent sampling estimator (research spike, not wired to any command)
├── filters.py      # shared --max-*/--ext/--pattern/--size options + matches_filters
├── report.py       # human_size/human_duration/extension_of, parsing, table + status-line rendering
├── convert.py      # format detection + single-file conversion, used by preview_cli.py
└── cache.py        # SQLite store + resolution ladder (phase 2, not yet built)
tests/              # one test file per source module, plus CLI-level test files, plus mocktree.py (estimate.py's synthetic-tree generator)
```

- Commands never call `os.scandir` or hash files directly outside of
  `walk.py`'s traversal, with one deliberate exception: `frontier.py`
  (`gaz sample`) calls `os.scandir` itself, because its whole premise is
  scanning each directory at most once under a resumable, per-
  subdirectory budget rather than one bounded walk over the whole tree —
  see DESIGN.md's Layout section. Everywhere else, a command needing its
  own filesystem walk is a signal `walk.py`'s interface is wrong; fix the
  walker, don't route around it.
- Shared CLI option definitions (`--max-seconds`, `--exclude`, `--json`,
  `--ext`, `--size`, ...) live in `filters.py`, not copy-pasted into each
  command in `cli.py`.
- Size/duration/extension parsing and formatting (`parse_size`,
  `parse_duration`, `human_size`, `human_duration`, `extension_of`) live
  in `report.py`, not scattered inline or duplicated per-module.
- Resist splitting a module further until it exceeds ~300 lines. `cli.py`
  is already an exception (~1,650 lines) — see TODO.md before adding
  another cross-cutting flag to the seven `filters.py`-based commands
  without addressing it (`gaz sample` doesn't use `filters.py` — it has
  its own budget/option model — so it's outside that count).

## Conventions

- **Dependencies:** `click` only (plus `pytest` for dev) in the core install.
  Format-specific libraries for `preview`/`convert` (PyYAML, tomli,
  python-docx, python-pptx, openpyxl, pypdf) live in the optional
  `gaz[preview]` extra — core `gaz` must keep working with none of them
  installed. Adding a new *required* runtime dependency requires a note in
  DESIGN.md explaining why; adding to `gaz[preview]` is lower-stakes but
  still needs a fallback path (see `convert.py`'s "stdlib/pandoc first,
  optional Python lib second, clear error naming what's missing third").
- **Exit codes:** always `0` on a successful run, including truncated ones,
  for every tree-walking command. Partial is a normal outcome, not an
  error — status goes in the output text, never the exit code. The one
  exception is `preview`/`convert`: a file they genuinely cannot handle at
  all (no converter installed, unparseable input) is a real failure and
  exits non-zero with an actionable message — a truncated *conversion*
  (timed out mid-pandoc-call) still follows the exit-0 rule.
- **Symlinks:** not followed by default (loops are common in dataset
  trees). Filesystems are not crossed by default. Don't change either
  default without updating DESIGN.md's rationale table.
- **Sizes:** `WalkEntry.size` is *allocated* bytes (`st_blocks * 512`,
  what `du` reports); `WalkEntry.apparent_size` is `st_size`. Space
  totals and anything answering "what's using my disk" use `size`;
  per-file size columns and `--size` filters use `apparent_size`. They
  differ by orders of magnitude on sparse files and cloud placeholders,
  so never substitute one for the other casually — see DESIGN.md's
  "Apparent vs. allocated size."
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
  descent, `max_seconds`/`max_entries` actually stopping the walk, `exclude`
  actually pruning before descent (and not counting against `max_entries`),
  a nonexistent root, and a root that's a file rather than a directory. See
  `tests/test_walk.py`.
- A new shared flag that threads through all seven commands (like `--exclude`
  or `--json`) needs at least one CLI-level test combining it with another
  recently-added shared flag, not just tested in isolation per-flag — see
  `tests/test_cli_json.py`'s `--json` + `--exclude`/`--skip-vendored` tests
  for the pattern.
- Traversal-order behavior needs tests that actually distinguish BFS from
  DFS under a tight budget (not just "doesn't crash") — e.g. a wide-shallow
  fixture tree where BFS discovers every top-level dir before descending
  and DFS goes deep into the first branch instead. `shuffle=True` needs a
  same-seed-is-reproducible test and a different-seeds-differ test.
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
2. Reuse `filters.limit_options`, `filters.traversal_options`, and
   `filters.filter_options` for the standard flags unless the command has
   a genuine reason to diverge (see how `find` keeps its positional
   `PATTERN` argument instead of adding a redundant `--pattern`). Thread
   `depth_first`/`shuffle`/`seed`/`exclude` straight through to
   `walk.walk()`. `limit_options` also carries `json_output` (the `--json`
   flag) — accept it as a parameter even if you branch on it immediately.
3. Branch early on `json_output`: build the command's row dicts and a
   `total` dict, call `report.json_output(result, rows, total=...)`,
   `click.echo` it, and `return`. Otherwise print a table
   (`report.render_table`), then a blank line, then any command-specific
   totals line, then `report.status_line(...)` last. Keep both branches'
   row content in sync — the JSON row shape should carry the same
   information as the table columns, just as raw values instead of
   `human_size`/`human_duration`-formatted strings. Document the new
   row/`total` shape in DESIGN.md's "Structured output (--json)" table.
4. Add tests before considering it done: happy path, empty tree, at least
   one truncation/edge case specific to that command's logic (see `gaz
   empty`'s walk-truncated warning for an example that isn't just "fewer
   rows"), and a `--json` happy-path test asserting the row/total shape.
