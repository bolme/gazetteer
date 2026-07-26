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

1. Re-run suggestion names the wrong flag — Bug, P0, S
2. gaz empty's truncation caveat isn't load-bearing — Improvement, P0, S
3. Revisit how the three limits work (time-only default, others optional) — Improvement, P1, M
4. gaz find's positional PATTERN vs --pattern discoverability trap — Improvement, P1, S
5. Flag suspicious/epoch-like mtimes in gaz stale — Improvement, P1, S
6. Default --max-entries is too low for an ordinary large tree — Improvement, P1, S/M (superseded by #3 if that lands first)
7. No --exclude / path-ignore flag — Feature, P1, M
8. gaz dup: separate real duplicates from vendored/package-manager noise — Feature, P2, M (built on #7)
9. gaz tree: recursive/rollup size mode — Feature, P2, M
10. Bounded machine-readable output format — Feature, P2, L
11. No dry-run / preview-before-acting workflow for gaz dup — Feature, P3, S (built on #10)
12. Add a SKILL / agent-guidance doc — Feature, P1, S (docs-only, no code risk)
13. Add an MCP server interface — Feature, P3, L (deliberately last — wants a stable CLI surface first)

Rationale for the order: the two P0 items are outright bugs that make
gaz's own output misleading, and both are small, isolated fixes — no
reason to defer them. #3 (revisiting the limits model) comes right after
because it's a foundational change to what "bounded" means for every
other command and item on this list — in particular it makes #6 (is 1M
the right --max-entries default?) largely moot, since the plan is for
that limit to become optional rather than tune its default. Doing #3
before #6 avoids re-litigating a default that might not exist afterward.
The rest of the P1 usability/default items follow because they're each
small and independently shippable, and the SKILL doc is pulled forward
to P1 despite being a "feature idea" because it's pure documentation (no
code risk) and immediately raises the value of everything already
shipped. `--exclude` (#7) is ranked ahead of the two items that most
benefit from it (#8, #9 lean on being able to skip noisy subtrees) even
though it's a bigger change, because doing it first avoids building
`dup`'s vendored-directory heuristic and then reconciling it with a
general exclude mechanism later. The output-format and MCP items are
pushed to the end because they're the largest, most design-heavy
changes, and the MCP surface specifically should mirror whatever flags
exist by then rather than be designed twice.

## Items, in suggested order

### 1. Re-run suggestion names the wrong flag when --max-entries was the limit
**Bug · Priority P0 · Difficulty S**

`status_line`'s truncation message always suggests re-running with a
larger `--max-seconds`, even when `--max-entries` was the actual limit
hit. Confirmed on a real run: stopped at "the 1,000,000 entries limit"
but still said "Re-run with --max-seconds 300 for a fuller picture" —
advice that does nothing, since time was never the constraint. Fix:
`report.status_line` should read `result.stop_reason` and suggest
whichever flag actually applies (`--max-entries` vs `--max-seconds`).
Small, isolated fix in one function; no design decision needed.

### 2. gaz empty's "unvisited, not empty" caveat needs to be load-bearing, not just present
**Improvement · Priority P0 · Difficulty S**

On a truncated walk (the common case for a big tree under default
limits), most of the directories `gaz empty` reports are typically ones
that were never fully explored, not actually empty — in one real run,
the large majority of ~574 reported "empty" directories fell in this
category. The command already prints a warning when the walk was
incomplete, but it's one line at the very bottom of a long list, easy to
miss, and the false-positive rate can be high enough that the "empty"
label becomes misleading in a truncated run. Consider: sorting/flagging
per-row instead of one global footer warning, or refusing to label an
individual directory "empty" (vs. "unvisited") unless the walk actually
completed within that subtree. Contained to `cli.py`'s `empty` command
and `walk.py`'s existing per-directory completeness bookkeeping — no new
walker concept needed, just surfacing what's already tracked.

### 3. Revisit how the three limits work: time-only by default, others optional
**Improvement · Priority P1 · Difficulty M**

Today all three budgets (`--max-seconds`, `--max-entries`, `--max-rows`)
apply by default, and the walk stops when **any** is hit — which means
on fast local storage, a scan can stop early on entry count alone even
though there was plenty of time left to keep going. The better default:
**only the time budget (`--max-seconds`) is on by default.** Let a scan
collect as much as it can within the time limit rather than cutting
itself off on an arbitrary entry count that has nothing to do with
whether the storage can keep up. `--max-entries` becomes opt-in — most
useful on slow storage (spinning disks, network mounts) where an
attacker isn't the concern but a single pathological directory (a cache
with millions of tiny files) chewing through the whole time budget is.
**`--max-rows`, unlike the other two, should stay on by default** and
not be folded into this change — it isn't a walk budget, it's the
output-size guard that protects the terminal/LLM context window, which
matters regardless of how fast or slow the underlying storage is; a
fast local disk can still enumerate more files than anyone wants printed
or fed into a context window.

Every limit needs an explicit "unbounded" escape hatch for full
processing when that's genuinely what's wanted (e.g. `--max-seconds 0`
or `--no-max-seconds` meaning "run until done," similarly for
`--max-entries`) — someone who wants the complete picture and is willing
to wait should be able to ask for it plainly, without gaz still
second-guessing them with a hidden ceiling. `--max-rows` should get the
same treatable-as-optional mechanism, but its default should stay *on*
rather than flip to unbounded, since an accidentally-unbounded row count
is exactly the flooding problem gaz exists to prevent — this is the one
limit where "make it optional" should not quietly imply "make it
unbounded by default" the way it does for the walk-time budgets.

Medium effort: this is a real semantics change to `walk.py`'s stopping
conditions (which limits are active at all, not just their values) and
to `report.status_line`/`total_label`'s truncation messaging (needs to
correctly describe "ran out of time" vs. "hit an entry cap you
explicitly opted into" vs. "output was capped, though the walk itself
finished") — three genuinely different situations that read differently
today because they're conflated under one "stopped early" model. Should
land before or alongside #6 (the `--max-entries` default-value question)
since it changes the question from "what should the default number be"
to "should this default to being on at all."

### 4. gaz find's positional PATTERN vs --pattern is a discoverability trap
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

### 5. Investigate flagging suspicious/epoch-like mtimes in gaz stale
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

### 6. Default --max-entries (1,000,000) is too low for an ordinary large tree
**Improvement · Priority P1 · Difficulty S/M**

A single real home directory hit the 1M-entry default almost
immediately (~947K files across ~53K dirs is most of the budget before
any filtering). Every command reports its numbers as "at least" in this
case, which is *correct*, but if the default is this easy to exhaust on
an unremarkable modern filesystem, it stops being "a generous default"
and becomes "the thing you always have to override." Worth reconsidering
the default upward, or documenting more prominently that large trees
should expect to pass `--max-entries` explicitly. Changing the constant
is trivial (S); the real work is M — gathering timing data across a few
real trees so the new default is chosen deliberately, not guessed.

### 7. No --exclude / path-ignore flag on any command
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

### 8. gaz dup needs a way to separate "your duplicates" from "vendored/package-manager duplicates"
**Feature · Priority P2 · Difficulty M**

The largest duplicate sets found in a real run were near-entirely inside
a Python package manager's installed-package tree (repeated JS bundles,
fonts, source maps as a byproduct of how the packages ship) — reclaiming
that space would mean breaking the installed environment, not cleaning
up anything. `gaz dup` has no way today to deprioritize or exclude
duplicates that live inside dependency-manager directories
(`site-packages`, `node_modules`, `.venv`, conda envs, etc.). Once #7
(`--exclude`) exists, a user can already work around this manually;
this item is the built-in heuristic on top (recognize common
package-manager directory names by default, or a `--skip-vendored`
flag) since "noise from vendored dependencies" is dup's single biggest
source of low-value results and shouldn't require every user to
rediscover the same exclude list. Depends on #7 landing first.

### 9. gaz tree has no recursive/rollup size mode
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

### 10. No machine-readable output format
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

### 11. No dry-run / preview-before-acting workflow for gaz dup
**Feature · Priority P3 · Difficulty S**

`gaz dup` (and any future command that suggests deletions) has no way to
preview *what specifically* would be affected before a user acts on it
outside the tool — today that means manually copying paths out of the
table. This is lower priority than the items above since gaz doesn't
delete anything itself (it only reports), but worth considering a
`--script` or `--emit-paths` style output tailored to feeding into a
review step or a deletion command. Small once #10 (structured output)
exists to build it on — mostly a thin rendering of data gaz already
computes — but blocked until then, since duplicating a one-off output
format now would just be replaced later.

### 12. Add a SKILL (or equivalent agent-guidance doc) for using gaz effectively
**Feature · Priority P1 · Difficulty S**

Right now an agent discovering gaz has to infer good practice from
`--help` text alone. A skill/guidance doc should cover things that
aren't obvious from flags in isolation:
- Start broad and cheap (`gaz tree`/`gaz ext` with default budgets)
  before narrowing with `--ext`/`--pattern`/`--size`, rather than
  guessing a narrow query first.
- Treat "Total (at least, ...)" / "Stopped at the N limit" lines as
  load-bearing — never treat a truncated result's numbers as exhaustive,
  and re-run with a larger budget (the *correct* budget flag — see
  item 1 above) rather than assuming completeness.
- On slow storage (network mounts, spinning disks, anything where a bare
  `find .` has been known to hang), prefer smaller `--max-seconds` and
  iterate rather than requesting a huge budget up front — and once item
  3 lands, know which limits are even active by default (time only)
  versus opt-in (`--max-entries`).
- Use `--shuffle`/`--seed` when a truncated sample needs to be
  representative rather than always the same alphabetically-first
  slice, and `--depth-first` only when deliberately confirming one known
  subtree rather than surveying broadly.
- When results should feed into another step (a script, a second agent
  call), prefer the bounded structured-output mode (once it exists, see
  item 10) over scraping the text table.

Ranked P1 despite being a "feature idea" because it's pure documentation
with no code risk, and it immediately raises the value of every command
gaz already ships — the highest value-to-effort item on this whole list.
This should live as a real skill file once the project's skill-authoring
convention is decided — for now, tracked here so the need isn't lost.

### 13. Add an MCP server interface
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
wait until the CLI surface (especially #3 the limits-model change, #7
--exclude, and #10 structured output) is more settled, since the MCP
tool schema will want to mirror stable flags rather than be redesigned
twice.
