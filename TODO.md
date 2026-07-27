These are issues and feature ideas discovered through real usage, kept
lower priority than active work but worth tracking. This is a living
document — update it as new issues are discovered or remove items as
they're fixed. Several of these come from a hands-on cleanup review
(`GAZ_REVIEW.md`) of a large, real home directory (~175 GB, ~947K files,
~53K directories) that hit gaz's default limits almost immediately —
exactly the scale gaz is meant for, so its rough edges showed up fast.

Two things worth keeping in view while triaging this list, since they're
easy to under-value against feature requests like "add --json":

- **gaz's job is partly to prevent information overload.** A tool that
  dumps 947K rows is not more correct than one that reports "at least
  53,402 dirs, lower bound" — it's just less honest about what got
  read. Flooding a terminal or an LLM context window with raw output is
  a failure mode gaz exists to avoid, even when a fix "would be more
  complete."
- **gaz's bounded walk is a speed/reliability guarantee, not just a
  correctness nicety.** On HDD-backed or network-mounted storage, a
  plain `find .` or `du -sh` can run for hours and never return —
  something encountered repeatedly in agentic workflows, where a hung
  `find` eventually has to be killed with nothing to show for it. Every
  item below should keep that guarantee intact rather than trade it away
  for completeness.

## Priority / difficulty key

- **Priority:** P0 (fix soon, actively misleading) → P3 (nice to have,
  no rush)
- **Difficulty:** S (small, contained, hours) / M (medium, a design
  choice plus a few files) / L (large, touches every command or needs
  its own design pass)
- **Type:** Bug (behaves incorrectly), Improvement (behaves correctly
  but poorly), Feature (new capability)

## Suggested order of work

1. gaz tree: recursive/rollup size mode — Feature, P2, M
2. Bounded machine-readable output format — Feature, P2, L
3. No dry-run / preview-before-acting workflow for gaz dup — Feature, P3, S (built on #2)
4. Add an MCP server interface — Feature, P3, L (deliberately last — wants a stable CLI surface first)

Rationale for the order: the output-format and MCP items are pushed to
the end because they're the largest, most design-heavy changes, and the
MCP surface specifically should mirror whatever flags exist by then
rather than be designed twice. The dry-run item depends on structured
output landing first.

Eight items that were previously on this list have been fixed and
verified — see the "Recently resolved" section at the bottom for what
changed and how it was tested.

## Items, in suggested order

### 1. gaz tree has no recursive/rollup size mode
**Feature · Priority P2 · Difficulty M**

`gaz tree` reports each directory's *direct* children only — it doesn't
aggregate subtree totals the way `du -d1` (or deeper) does. Since the
walker already visits every file under the budget, this is aggregation
work gaz already has the data for; today a user has to shell out to
`du` separately for any directory that looks interesting. Candidate:
a `--recursive`/`--depth` interaction (or a new rollup mode) that sums
each directory's full subtree, not just its immediate contents — still
bounded by the same walk budgets, so this doesn't compromise the
speed/hang-prevention guarantee that's the point of gaz over plain `du`.
Medium effort: the raw per-file data is already collected, but rolling
it up per-ancestor-directory needs a real aggregation pass and a
decision about how deep results should nest in the table output.

### 2. No machine-readable output format
**Feature · Priority P2 · Difficulty L**

All output today is the plain aligned text table + status line. That's
intentionally compact for a human terminal or an LLM's context window
(see DESIGN.md's Output decision) — the point isn't to add a firehose
`--json` that dumps every row, since that reintroduces the exact
information-overload problem gaz exists to avoid. But a **bounded**
structured-output option (respecting the same `--max-rows` cap, one
JSON object per row plus the same completeness metadata gaz already
tracks) would let results feed into other tooling — `xargs`, a script
deciding what to delete, another agent — without giving up the budget
guarantees. Large because it needs a real design pass on schema (one
consistent shape across six different commands' row types plus the
completeness metadata) before any code — this is the kind of change
that should get its own design doc section, not just a flag.

### 3. No dry-run / preview-before-acting workflow for gaz dup
**Feature · Priority P3 · Difficulty S**

`gaz dup` (and any future command that suggests deletions) has no way to
preview *what specifically* would be affected before a user acts on it
outside the tool — today that means manually copying paths out of the
table. This is lower priority than the items above since gaz doesn't
delete anything itself (it only reports), but worth considering a
`--script` or `--emit-paths` style output tailored to feeding into a
review step or a deletion command. Small once #2 (structured output)
exists to build it on — mostly a thin rendering of data gaz already
computes — but blocked until then, since duplicating a one-off output
format now would just be replaced later.

### 4. Add an MCP server interface
**Feature · Priority P3 · Difficulty L**

DESIGN.md's Phase 4 already calls this out: expose the same commands as
MCP tools. The bounded-output-plus-explicit-completeness-signal contract
gaz already has is exactly what an agent needs to avoid acting on
partial data without knowing it's partial — this is arguably gaz's best
fit for agentic use, more so than the CLI itself, since an agent calling
gaz as a tool gets the same "safe, bounded" guarantee that makes it
useful over a raw `find`/`du` shellout that might hang for the ten
minutes an agent doesn't have. Deliberately last: it's a large effort in
its own right (tool schema, server lifecycle, packaging), and it should
wait until the CLI surface (especially #2 structured output) is more
settled, since the MCP tool schema will want to mirror stable flags
rather than be redesigned twice.

## Recently resolved

- **Added a SKILL doc for using gaz effectively.**
  `skills/gaz-usage/SKILL.md` covers what isn't obvious from `--help`
  alone: start broad with `tree`/`ext` before narrowing, treat the
  status line's completeness/re-run guidance as load-bearing, know which
  budgets are on by default (`--max-seconds` only) versus opt-in
  (`--max-entries`), use `--exclude`/`--skip-vendored` to keep noise out
  of results and free up budget, use `--shuffle`/`--seed` for
  representative sampling, and read `gaz stale`'s `(?)` epoch-mtime
  flag correctly. Docs-only, no code risk; no automated test, but
  reviewed against the original TODO checklist item-by-item for
  coverage.
- **`gaz stale` reported timestamp-reset artifacts indistinguishably
  from genuinely old files.** Files with `st_mtime` reset to (or near)
  the Unix epoch by some other tool — a cache, archive, or sync tool —
  read as "gaz is wrong" rather than "this file's timestamp is
  suspicious." `report.is_suspicious_mtime()` flags any mtime within a
  week of epoch; `gaz stale` appends `(?)` to that row's age and prints
  a one-line summary count when any are found. Tested in
  `tests/test_report.py` (boundary values around the epoch window) and
  `tests/test_cli_stale.py` (a flagged epoch-reset file next to a
  genuinely old file, and the no-false-positive case with nothing
  suspicious present).
- **`gaz find --pattern` failed with a generic "no such option" instead
  of pointing at the correct positional form.** `find` intentionally
  takes `PATTERN` positionally (it's the command's one required
  argument, not an optional filter layered on a walk — documented in
  DESIGN.md's decision table), unlike `tree`/`ext`/`stale`'s
  `--pattern` option, which made `gaz find --pattern ...` a natural but
  wrong guess. Making `PATTERN` accept both an alias option and a
  positional turned out to be genuinely ambiguous with click (a
  positional `PATH` argument after `--pattern VALUE` gets bound to the
  wrong slot), so the fix is a `FindCommand(click.Command)` subclass
  that intercepts the literal `--pattern` token and raises a `find`-
  specific `UsageError` naming the correct form, while every other
  unknown option still gets click's normal error. Tested in
  `tests/test_cli_filters.py` (the `--pattern` error message, and that
  positional `PATTERN` still works).
- **No --exclude / path-ignore flag; gaz dup couldn't separate real
  duplicates from vendored noise.** `walk()` now accepts `exclude: tuple[
  str, ...]` — glob patterns matched against a directory's basename — and
  prunes matching directories *before* descent: they're never scanned,
  never appear in `result.entries`, and never count against
  `--max-entries`, so excluding a noisy subtree actually frees up budget
  rather than just filtering it from output afterward. Exposed as a
  repeatable `--exclude PATTERN` option threaded through all six commands
  via `filters.limit_options`. `gaz dup --skip-vendored` builds on it: an
  opt-in flag that adds a curated list of common package-manager
  directory names (`cli.VENDORED_DIR_NAMES` — `node_modules`,
  `site-packages`, `.venv`, `vendor`, etc.) to the exclude set, composing
  with any explicit `--exclude` rather than replacing it. Tested in
  `tests/test_walk.py` (pruning, budget exemption, glob patterns, root
  never excluded), `tests/test_cli_filters.py` (`--exclude` on multiple
  commands, repeatability, budget interaction), and `tests/test_cli_dup.py`
  (`--skip-vendored` alone and combined with `--exclude`); manually
  verified against a real `node_modules`/vendored tree that excluded
  duplicates disappear from `gaz dup`'s results.
- **Limits model: only --max-seconds on by default, --max-entries opt-in,
  --max-rows still on but escapable.** All three budgets used to apply
  simultaneously (stop on whichever was hit first), so a scan on fast
  local storage could stop early on entry count alone even with plenty of
  time left. Now `--max-entries` defaults to `0` (unlimited) and is
  purely opt-in; `--max-seconds` stays on by default (default `30`);
  `--max-rows` stays on by default (default `50`, protecting the
  terminal/context window regardless of walk speed) but now honors `0`
  meaning "every row." `0` is the unlimited sentinel for all three.
  `walk.py` gained `time_exceeded()`/`entries_exceeded()` helper closures
  so the four inline budget checks read the same way; `report.status_line`
  now computes mutually-exclusive `is_entries_stop`/`is_time_stop` flags
  (avoiding a substring collision — `"entries limit"` contains `"s
  limit"`) and only suggests raising a budget the caller actually had
  active, never a nonsensical "--max-entries 0" or "--max-seconds 0."
  `report.limit_rows()` centralizes the `0`-means-unlimited row
  truncation used by all six commands. Tested in `tests/test_walk.py`,
  `tests/test_report.py`, and `tests/test_cli_edge_cases.py` (default
  behavior, explicit opt-in, and both `0`-means-unlimited cases); manually
  verified against a real tree that a default run no longer stops on
  entry count and `--max-rows 0` prints every row.
- **Re-run suggestion named the wrong flag.** `report.status_line` now
  reads `result.stop_reason` and suggests `--max-entries` when that was
  the actual limit hit, `--max-seconds` otherwise, instead of always
  suggesting a bigger time budget. Tested in `tests/test_report.py`
  (both the entries-limit and time-limit cases) and manually verified
  against a real truncated run.
- **`gaz empty` could false-positive unvisited directories as empty.**
  The walker now tracks which directories were actually fully scanned
  (`WalkResult.scanned_dirs`) rather than merely discovered as an entry
  of a scanned parent. `gaz empty` uses this to distinguish three cases:
  confirmed empty (scanned, and its whole subtree is known and
  file-free), unvisited due to the walk stopping early (reported
  separately, not counted as empty), and out of scope due to
  `--max-depth` (also not counted as empty, but not described as a
  truncation either, since `--max-depth` is a deliberate scoping choice
  that can still leave `result.complete == True`). Covers both the
  simple case (an unscanned root) and the subtler one (a directory that
  was itself fully scanned but has an unscanned child that could be
  hiding a file). Tested in `tests/test_walk.py` (the new `scanned_dirs`
  field directly) and `tests/test_cli_empty.py` (all three cases above,
  plus that a genuinely complete walk shows no caveat at all).
