---
name: gaz-usage
description: Guidance for using the gaz CLI to explore large directory trees effectively — when to use which command, how to read completeness/truncation output, and how to avoid wasting budget on noise. Use this when investigating an unfamiliar or very large directory (a dataset, a home directory, a build output tree) with gaz installed.
---

# Using gaz effectively

`gaz` answers structural questions about huge directory trees (counts,
sizes, duplicates, staleness, empty dirs) under explicit time/count/output
budgets, and always says clearly when a result is partial. This skill
covers practices that aren't obvious from `--help` text alone.

## Start broad and cheap, then narrow

Run `gaz tree` or `gaz ext` with default budgets first to get the shape of
a tree before writing a narrow query. Don't guess `--pattern`/`--ext`/`--size`
filters up front — they're for narrowing *after* you know roughly what's
there. `gaz find` is the exception: it's for a specific known pattern, and
takes `PATTERN` positionally (`gaz find "*.jpg" /data`), not as `--pattern`
— that's intentional, `tree`/`ext`/`stale` use `--pattern` but `find`'s
whole job *is* the pattern.

## Treat the status line as load-bearing

Every command ends with a one-line completeness status. Never treat a
truncated result's numbers as exhaustive — a "Total (at least, ...)" or
"Stopped at the N limit" line means the count below it is a floor, not the
real total. When gaz suggests a re-run flag, it's naming whichever budget
actually stopped the walk; use that suggestion rather than guessing which
flag to raise.

```
Stopped at the 30.0s limit after 1,204 dirs / 412,003 files.
Numbers below are a lower bound. Re-run with --max-seconds 300 for a fuller picture.
```

## Know which budgets are active by default

- `--max-seconds` (default `30`) — **on by default.** The only thing that
  guarantees a command returns.
- `--max-entries` (default `0` = unlimited) — **opt-in.** Turn it on only
  when storage is slow enough that a single pathological directory could
  burn the whole time budget before you'd want it to stop.
- `--max-rows` (default `50`) — **on by default**, protecting your own
  context window regardless of walk speed. Pass `0` to see every row once
  you actually want the full list (e.g. right before acting on it).
- `0` means "unlimited" for all three. `--max-depth` is a separate scoping
  flag (not a budget) and has no "off" value — it's already off by default.

On slow storage (network mounts, spinning disks — anywhere a bare `find .`
is known to hang), prefer a smaller `--max-seconds` and iterate rather
than requesting a big budget up front.

## Prune noise before it eats your budget

If the tree has vendored dependencies (`node_modules`, `site-packages`,
`.venv`, build caches, `.git`), use `--exclude PATTERN` (repeatable, glob
against a directory's basename) rather than filtering them out of the
output afterward — an excluded directory is pruned *before* descent, so it
never counts against `--max-entries` either. `gaz dup --skip-vendored` is
a built-in shortcut for the common package-manager directories.

```
gaz ext /home/user --exclude node_modules --exclude .venv --exclude '.git'
gaz dup /home/user --skip-vendored
```

## Sampling a truncated walk

`gaz` walks breadth-first by default, so even a truncated run sees every
top-level directory before going deep into any one of them — a partial
result still shows the tree's overall shape. Use `--shuffle` (with
`--seed` for reproducibility) when a truncated sample needs to be
representative rather than always the same alphabetically-first slice.
Use `--depth-first` only when deliberately confirming one known subtree,
not when surveying broadly.

## Reading `gaz stale`'s age column

An age flagged `(?)` (within a week of the Unix epoch) is almost always a
timestamp reset by some other tool (a cache, archive, or sync tool), not a
genuinely decades-old file — don't report it to the user as "this file
hasn't been touched since 1970" without that caveat.

## Feeding results into another step

When you're going to parse the output programmatically (pipe into `jq`,
build a follow-up call, hand rows to another agent step) use `--json`
instead of scraping the aligned text table — same `--max-rows` cap, same
completeness signal as fields (`complete`, `stop_reason`) rather than a
sentence you'd have to pattern-match. Still check `complete` before
treating `rows` as the full answer; `--json` doesn't relax the
"truncated is not exhaustive" rule, it just makes the truncation
programmatically checkable.

## `gaz tree --recursive` for subtree totals

Default `gaz tree` rows are each directory's *direct* children only — a
parent directory with a huge subtree can look small if its files all live
several levels down. Add `--recursive` when you want each row to reflect
its whole subtree (like `du -d1`), e.g. to find which top-level directory
is actually consuming the most space.

## Command cheat sheet

| Command | Question it answers |
|---|---|
| `gaz ext` | What kinds of files are here, and how much space does each kind use? |
| `gaz tree` | What's the per-directory breakdown (counts, sizes)? |
| `gaz find PATTERN` | Where are files matching this specific glob? |
| `gaz stale` | What hasn't been touched in a while? |
| `gaz empty` | What directories are dead weight (no files anywhere under them)? |
| `gaz dup` | Where is space being wasted on duplicate file content? |
| `gaz preview FILE` | What's actually inside this one file? |
| `gaz convert FILE -o OUT` | Save a converted (DOCX/PPTX/XLSX/PDF → text) file to disk. |
