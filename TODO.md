Issues and feature ideas from real usage, kept lower priority than
active work. Living document — update as items are discovered or fixed.
Items are unordered within their priority group; add new ones wherever
they fit rather than renumbering anything.

Two reviews of the same real ~175GB/947K-file home directory motivated
most of this: `GAZ_REVIEW.md` (v0.1.0, 5/10) and `GAZ_REVIEW_v0.1.2.md`
(v0.1.2, 7/10 — confirmed the v0.1.0 fixes landed, found a new round of
gaps at the same scale).

**gaz is read-only — knowledge, not modification.** Both reviews asked
for some form of deletion (`gaz rm`, `--dry-run`+`--confirm`, an
`ncdu`-style interactive delete). Out of scope by design: gaz's job is
to report state; acting on it is another tool's job (a script, `xargs`,
an agent's next step). The answer to "gaz should help me delete things"
is "make gaz's output good enough to hand to something that deletes
things" (e.g. `--json`), not gaz growing a write path.

**Also keep in view:** gaz's job is partly to *prevent* information
overload (a truncated, honest "at least N" beats a flood of raw rows),
and its bounded walk is a reliability guarantee, not just a nicety — on
slow/networked storage, a plain `find`/`du` can hang for hours. Every
item below should preserve both.

## Priority / difficulty key

- **Priority:** P0 (fix soon, actively misleading) → P3 (nice to have)
- **Difficulty:** S (hours) / M (a design choice + a few files) / L
  (large, touches every command or needs its own design pass)
- **Type:** Bug / Improvement / Feature

## Open items

### P1

- **[Bug, M] `gaz dup` is too slow to be useful on real huge trees.** On
  a real 175GB/947K-file tree, only 48K of 904K same-size candidates got
  hashed before the default `--max-hash-seconds` (30s) ran out — 94.7%
  unhashed, with no visibility into how large the shortfall is or any
  progress indication during the run. Reconsider the default (same
  problem `--max-entries` had before it became opt-in), and/or surface
  hashing progress and the hashed/total fraction more loudly than "lower
  bound."
- **[Feature, M] `--exclude` only matches directory basenames, not
  paths.** No way to exclude `*/archive/` or a specific nested path
  without also excluding every same-named directory elsewhere in the
  tree. Add `--exclude-path` (glob against the relative/absolute path)
  composing with `--exclude` the way `--skip-vendored` does. Needs the
  accumulated relative path threaded through `walk.py`'s loop, which
  `is_excluded` doesn't currently see.

### P2

- **[Improvement, S] Audit converter priority order for
  preview/convert.** The `pandoc` → optional-lib → error ordering in
  DESIGN.md was chosen before real files had been run through it. Worth
  a real pass now: does the documented first choice actually produce the
  best output per format? Research/docs task; code only if it finds an
  actual defect.
- **[Improvement, M] `cli.py` has grown past its own 300-line
  convention.** ~1,100 lines (DESIGN.md/AGENTS.md say ~300) after several
  rounds of adding a shared flag to all seven commands, each repeating
  the same walk/filter/render-or-json shape. A shared per-command dispatch
  (rows + a total dict in, JSON-or-table out) would cut the duplication.
  Needs a design pass on where the split falls before moving code.

### P3 — large/speculative, own design pass needed before code

- **[Feature, L] Sampling-based fast size estimation.** Randomly sample
  root-to-leaf paths (tracking branching, depth, sizes/ages), repeat N
  times, statistically estimate the tree's totals — for trees too large
  for even a bounded walk to usefully cover. Different guarantee than
  everything else gaz does (an estimate with error bars, not an observed
  lower bound) — needs its own honest-presentation design before code.
  **Spike done, superseded for the CLI surface by `gaz sample`** (see
  "Recently resolved" below): `src/gazetteer/estimate.py` implements and
  `tests/test_estimate.py` validates a weighted-random-descent estimator
  (Knuth's tree-size algorithm generalized to sum bytes) against
  synthetic trees in `tests/mocktree.py` — confirmed unbiased, confirmed
  95% CI coverage is honest, and found that probe cost is driven far more
  by tree *shape* (depth, branching-factor variance across siblings) than
  by tree size. See `docs/sample-estimation.md` for the comparison.
  `gaz sample` ships a different algorithm instead (`frontier.py`'s
  frontier-based sampler). `estimate.py`/`mocktree.py` remain unwired to
  any command, as a validated alternative — see that document's "known
  gaps" section for a proposed hybrid of the two that hasn't been built.
- **[Feature, L] LLM-based captioning for images/visual formats.**
  Configure a multimodal LLM to caption images, convert PDF/PPTX pages
  to images first. Pulls in a network dependency and API-key config
  nothing else in gaz needs, and raises a real question about how "an
  LLM's opinion" fits gaz's bounded/factual contract.
- **[Feature, L] Integrate with OS search indexes** (Spotlight, Windows
  Search) for a fast candidate list instead of a full walk.
  Platform-specific; trades "walks the real filesystem" for "trusts a
  possibly-stale external index," which needs its own staleness story.
- **[Feature, L] Integrate with OS quick-preview tools** (Quick Look,
  Windows Preview) instead of gaz's own `pandoc`/`pdftotext` stack. Most
  render to an image/GUI window, not text — needs a design layer
  (screenshot + OCR?) shared with the LLM-captioning idea above.
- **[Feature, L] MCP server interface.** DESIGN.md's Phase 4. gaz's
  bounded-output-plus-completeness-signal contract is exactly what an
  agent needs, but this is a large standalone effort (tool schema,
  server lifecycle, packaging) — deliberately last, so the schema can
  mirror a settled CLI surface instead of being designed twice.

## Recently resolved

- **`gaz sample`**: estimates each immediate subdirectory of PATH via a
  frontier-based adaptive sampler (`src/gazetteer/frontier.py`) that
  scans each directory at most once, for subtrees too large for `gaz
  list` to fully walk. Every row reports three tiers rather than one
  number — `exact` when a subdirectory's frontier fully drains in time,
  else a true `lower_bound` (sum of everything actually counted, never
  inflated) alongside a completeness-weighted `estimate` that is clearly
  marked as possibly biased. See `docs/sample-estimation.md` for the
  algorithm, the bias finding that motivates the three-tier reporting,
  and a real identity-vs-equality bug found and fixed during development.
  `--max-seconds` is a total budget shared across every subdirectory
  (33% divided equally up front so small ones reliably finish, the rest
  round-robined across whatever's incomplete), not a per-subdirectory
  one — this keeps total runtime predictable regardless of how many
  subdirectories PATH has. Also reports `dirs` (same lower-bound/
  estimate split), an `activity` column (age of the most recently
  modified file), `ext types` (count of distinct extensions), and `ext`
  (as many "ext(NN%)" entries as fit in 30 chars, ranked biggest-first —
  no "+N other" filler) — an opt-in `--fields owners` shows a single top
  file owner the same way. `--rank-by size|count` (default `size`)
  controls whether `ext`/`owners` rank by bytes or file count. The
  extension/activity/owner data are always an exact tally of scanned
  files only, never extrapolated, since guessing at an unscanned
  directory's likely extension mix, recency, or ownership is a much
  shakier claim than guessing at its total size.
  `--sort name|size|files|dirs|activity` (default `name`, `--reverse`
  flips it) ranks by the estimate rather than the lower bound, so a huge
  but barely-scanned subdirectory still sorts as huge. A `denied` column
  (count of directories that hit `PermissionError`, recursing through
  ancestors the same way `dirs` does) appears only when at least one
  subdirectory has a nonzero count — invisible on a tree gaz can fully
  read; a row with any denials gets a leading `-` marker, which takes
  priority over the incomplete-scan `*` marker even on a row that's
  both. Plain files directly inside PATH are listed alongside
  subdirectories (like `gaz list`), always exact since a file's own stat
  is already the complete answer — the "N of M subdirectories" status
  line and JSON's `subdirs`/`exact_subdirs` count only directory rows,
  so files don't inflate either side of that ratio. Also fixed a real
  bug found by inspection: the completeness-weighted estimate could come
  out below its own lower bound when a low-completeness child's diluted
  mean undercut its own already-counted total; now clamped at every
  level of the recursion, not just the root. Ends with a two-line
  summary: total directories/files visited and wall-clock time, then a
  grand total across every row (a single number if every subdirectory
  finished exactly, or a confirmed/estimated split if any didn't).

- **Consistent paths**: relative (`./sub/f.txt`) in text everywhere,
  shared `-P` for absolute, `--json` always absolute. Every command now
  reports row truncation, and `gaz dup` lists every copy in a set.

- **`gaz largest`**: biggest individual files across a subtree, with
  `--min-size` and `--apparent`. `--max-rows` doubles as the N.

- **`preview`/`convert` error paths audited**: every converter-library
  call is wrapped, so a corrupt or mislabeled file gives an actionable
  error instead of a raw traceback; a failing `pandoc`'s stderr survives
  into the message. Added **`gaz preview --check-deps`**.
- **`gaz preview` metadata header**: filename, size, and
  modified/created dates above the content.

- Closed **dry-run/preview-before-acting for `gaz dup`** as out of
  scope — see the read-only note above; `--json` is the integration
  point for external deletion tools, not a feature gaz builds itself.
- **Bounded `--json` output** on all six commands: one shared envelope
  (`report.json_output` — `rows`, `complete`, `stop_reason`, counts,
  `total`), still respects `--max-rows`. Schema in DESIGN.md.
- **`gaz tree` became `gaz list`**: one level, each subdirectory row
  carrying its whole subtree's totals; `--recursive` removed, plus
  `--sort`/`--fields`/`-P`, a default `modified` column, and `*` marking
  incompletely-scanned subtrees.
- **Sizes now measure allocated blocks, not `st_size`**, so totals match
  `du` — a sparse VM image no longer reports 100 GB while using 7 MB.
- Added **`skills/gaz-usage/SKILL.md`** covering non-obvious usage
  (default budgets, `--exclude`, sampling, reading the status line).
- **`gaz stale`** flags timestamps within a week of the Unix epoch with
  `(?)` instead of reporting them indistinguishably from real old files.
- **`gaz find --pattern`** now errors with a pointer to the correct
  positional form instead of a generic "no such option."
- **`--exclude PATTERN`** (all six commands) prunes directories before
  descent, so excluding noise also frees up `--max-entries` budget;
  `gaz dup --skip-vendored` builds a curated exclude list on top.
- **Limits model rework**: only `--max-seconds` is on by default now;
  `--max-entries` is opt-in (was a silent 1,000,000 ceiling);
  `--max-rows` stays on but `0` means every row. `0` is the unlimited
  sentinel across all three.
- **Status line re-run suggestions** now name whichever budget actually
  stopped the walk, instead of always suggesting `--max-seconds`.
- **`gaz empty`** no longer false-positives unvisited directories
  (walk stopped early, or out of `--max-depth` scope) as empty.
