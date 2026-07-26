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

1. gaz find's positional PATTERN vs --pattern discoverability trap — Improvement, P1, S
2. Flag suspicious/epoch-like mtimes in gaz stale — Improvement, P1, S
3. No --exclude / path-ignore flag — Feature, P1, M
4. gaz dup: separate real duplicates from vendored/package-manager noise — Feature, P2, M (built on #3)
5. gaz tree: recursive/rollup size mode — Feature, P2, M
6. Bounded machine-readable output format — Feature, P2, L
7. No dry-run / preview-before-acting workflow for gaz dup — Feature, P3, S (built on #6)
8. Add a SKILL / agent-guidance doc — Feature, P1, S (docs-only, no code risk)
9. Add an MCP server interface — Feature, P3, L (deliberately last — wants a stable CLI surface first)

Rationale for the order: the remaining P1 usability/default items come
first because they're each small and independently shippable, and the
SKILL doc is pulled forward to P1 despite being a "feature idea" because
it's pure documentation (no code risk) and immediately raises the value
of everything already shipped. `--exclude` (#3) is ranked ahead of the
two items that most benefit from it (#4, #5 lean on being able to skip
noisy subtrees) even though it's a bigger change, because doing it first
avoids building `dup`'s vendored-directory heuristic and then
reconciling it with a general exclude mechanism later. The output-format
and MCP items are pushed to the end because they're the largest, most
design-heavy changes, and the MCP surface specifically should mirror
whatever flags exist by then rather than be designed twice.

Three items that were previously on this list have been fixed and
verified — see the "Recently resolved" section at the bottom for what
changed and how it was tested.

## Items, in suggested order

### 1. gaz find's positional PATTERN vs --pattern is a discoverability trap
**Improvement · Priority P1 · Difficulty S**

`find` intentionally takes `PATTERN` as a positional argument (by
design — see DESIGN.md's "find keeps its positional PATTERN argument
instead of adding a redundant --pattern"), while `tree`/`ext`/`stale`
all accept `--pattern` as an option. A user who has just used
`--pattern` on another command reasonably tries `gaz find --pattern
'*.bak'` next, gets `No such option '--pattern'`, and reads it as a
missing feature rather than a different (intentional) argument shape.
Not a bug in behavior, but a real usability gap. Fix options: make the
error message for unknown `--pattern` on `find` explicitly point at the
positional form, or reconsider whether `find` should accept `--pattern`
as an alias for the positional argument for consistency. Either fix is
a small, localized change to one command.

### 2. Investigate flagging suspicious/epoch-like mtimes in gaz stale
**Improvement · Priority P1 · Difficulty S**

`gaz stale` correctly reports whatever `st_mtime` the OS gives it — that
part isn't a gaz bug. But real runs surfaced files reported as several
decades old (in cache/build-tool directories and inside a game-engine
project), which is almost certainly a timestamp reset to the Unix epoch
by some other tool (common with certain caches, archives, or sync
tools), not filesystem corruption. Because gaz presents this
indistinguishably from a genuinely old file, it can read as "gaz has a
bug" rather than "gaz found something worth double-checking." Consider
flagging ages that land suspiciously close to the epoch (or another
common reset value) with a note like "(unusually old — may be a reset
timestamp, not a real file age)" rather than reporting them at face
value. A small, additive check in the `stale` command's row-rendering;
no walker or schema change.

### 3. No --exclude / path-ignore flag on any command
**Feature · Priority P1 · Difficulty M**

Every walk-based command scans everything under `--max-depth`, with no
way to skip a known-irrelevant subtree (a package manager's install
directory, a build cache, `.git`, etc.) before it eats into the
`--max-entries`/`--max-seconds` budget. On a real large-tree run, a
meaningful fraction of the entries and duplicate results were pure
noise from exactly this kind of directory. An `--exclude PATTERN`
(repeatable, glob against path or dirname) would both improve result
quality and — more importantly given gaz's time/count budgets — let a
scan spend its limited budget on directories that actually matter
instead of burning through `--max-entries` inside a vendored dependency
tree. Medium effort: needs a walker-level change (skip descending into
excluded dirs, ideally *before* counting them against the budget, not
just filtering them from output afterward) plus a new shared CLI option
threaded through all six commands, similar in shape to the existing
`filters.py` options.

### 4. gaz dup needs a way to separate "your duplicates" from "vendored/package-manager duplicates"
**Feature · Priority P2 · Difficulty M**

The largest duplicate sets found in a real run were near-entirely inside
a Python package manager's installed-package tree (repeated JS bundles,
fonts, source maps as a byproduct of how the packages ship) — reclaiming
that space would mean breaking the installed environment, not cleaning
up anything. `gaz dup` has no way today to deprioritize or exclude
duplicates that live inside dependency-manager directories
(`site-packages`, `node_modules`, `.venv`, conda envs, etc.). Once #3
(`--exclude`) exists, a user can already work around this manually;
this item is the built-in heuristic on top (recognize common
package-manager directory names by default, or a `--skip-vendored`
flag) since "noise from vendored dependencies" is dup's single biggest
source of low-value results and shouldn't require every user to
rediscover the same exclude list. Depends on #3 landing first.

### 5. gaz tree has no recursive/rollup size mode
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

### 6. No machine-readable output format
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

### 7. No dry-run / preview-before-acting workflow for gaz dup
**Feature · Priority P3 · Difficulty S**

`gaz dup` (and any future command that suggests deletions) has no way to
preview *what specifically* would be affected before a user acts on it
outside the tool — today that means manually copying paths out of the
table. This is lower priority than the items above since gaz doesn't
delete anything itself (it only reports), but worth considering a
`--script` or `--emit-paths` style output tailored to feeding into a
review step or a deletion command. Small once #6 (structured output)
exists to build it on — mostly a thin rendering of data gaz already
computes — but blocked until then, since duplicating a one-off output
format now would just be replaced later.

### 8. Add a SKILL (or equivalent agent-guidance doc) for using gaz effectively
**Feature · Priority P1 · Difficulty S**

Right now an agent discovering gaz has to infer good practice from
`--help` text alone. A skill/guidance doc should cover things that
aren't obvious from flags in isolation:
- Start broad and cheap (`gaz tree`/`gaz ext` with default budgets)
  before narrowing with `--ext`/`--pattern`/`--size`, rather than
  guessing a narrow query first.
- Treat "Total (at least, ...)" / "Stopped at the N limit" lines as
  load-bearing — never treat a truncated result's numbers as exhaustive,
  and follow the re-run suggestion gaz itself prints (it now names
  whichever budget flag actually applies).
- On slow storage (network mounts, spinning disks, anything where a bare
  `find .` has been known to hang), prefer smaller `--max-seconds` and
  iterate rather than requesting a huge budget up front — and know which
  limits are even active by default (only `--max-seconds`; `--max-entries`
  is opt-in, `--max-rows` stays on but supports `0` for every row).
- Use `--shuffle`/`--seed` when a truncated sample needs to be
  representative rather than always the same alphabetically-first
  slice, and `--depth-first` only when deliberately confirming one known
  subtree rather than surveying broadly.
- When results should feed into another step (a script, a second agent
  call), prefer the bounded structured-output mode (once it exists, see
  item 6) over scraping the text table.

Ranked P1 despite being a "feature idea" because it's pure documentation
with no code risk, and it immediately raises the value of every command
gaz already ships — the highest value-to-effort item on this whole list.
This should live as a real skill file once the project's skill-authoring
convention is decided — for now, tracked here so the need isn't lost.

### 9. Add an MCP server interface
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
wait until the CLI surface (especially #3 --exclude and #6 structured
output) is more settled, since the MCP tool schema will want to mirror
stable flags rather than be redesigned twice.

## Recently resolved

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
