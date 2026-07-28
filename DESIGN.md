# gazetteer (`gaz`) — Design

## Problem

Computer-vision datasets in the multi-terabyte range (images, video, XML, CSV, JSON)
are hard to understand structurally. The standard tools fail in three specific ways:

1. **They hang.** `find . | grep ...` or `du -d1 .` runs for minutes or hours with no
   output and no indication of progress.
2. **They flood.** When they do return, they emit hundreds of thousands of lines,
   burying the terminal and blowing out an LLM's context window.
3. **They're all-or-nothing.** Ctrl-C gives you nothing. There's no "here's what I
   learned in 30 seconds."

`gaz` is a Click-based CLI that answers structural questions about huge trees under
explicit time, count, and output budgets — and always says clearly when it stopped early.

- **Package (PyPI):** `gaz`
- **Command:** `gaz`
- `gazetteer` was the original intended package name but is blocked by PyPI's
  admin-side name policy (confirmed via a rejected upload and a genuine 404 on
  the project page, 2026-07-25) — likely flagged as a generic dictionary word.
  Renamed the distribution to `gaz`; the internal Python package
  (`import gazetteer`, `src/gazetteer/`) and the `gaz` command are unaffected.

## Core principle

> Every operation is bounded, and every truncated result says so.

A partial answer delivered in 30 seconds is more useful than a complete answer that
never arrives. This is the whole product. Do not add a feature that can run unbounded.

## Design decisions

| Decision | Choice | Why |
|---|---|---|
| Walker | One shared bounded walker in `walk.py`, used by every command | Single place where limits, symlinks, and permission errors are handled correctly |
| Directory iteration | `os.scandir`, not `os.walk` | `scandir` returns `stat` data from the directory read, avoiding a syscall per file |
| Traversal order | Breadth-first by default | A truncated walk should show the tree's overall shape, not exhaustively cover the first branch and miss every sibling. See "Traversal order" below. |
| Symlinks | Not followed by default | Loops are common in dataset trees and will hang the walk |
| Filesystems | Do not cross by default | Keeps network mounts from silently joining a local scan |
| Permission errors | Skip, count, report total at the end | One unreadable directory should not kill a 4-hour scan |
| Output | Plain aligned text by default, `--json` for machines | Plain text is compact in LLM context; `rich` markup is not |
| Exit code | Always `0` on a successful run, including partial ones | Partial is a normal outcome, not an error. Status goes in the output. |
| `find`'s PATTERN | Positional argument, not `--pattern` (unlike `list`/`ext`/`stale`) | It's `find`'s one required argument, not an optional filter layered on top of a walk — a positional signals that. A user coming from `--pattern` on another command who types `gaz find --pattern ...` anyway gets a `find`-specific error pointing at the correct form (`FindCommand` in `cli.py`), rather than growing a second, redundant way to spell the same thing. |
| `list`'s depth | Always exactly one level; no `--recursive`, no `--depth` | Each subdirectory row already reports totals for its *whole* subtree, so a nested listing would re-answer at every level what one level answers once. Going deeper is `gaz list <that row>` — a second command invocation, not a second output mode. |
| `list`'s incomplete rows | `*` after the directory name, once per row | A directory whose subtree wasn't fully scanned has counts that are floors, not totals. Marking the row once (`train/*`) rather than flagging each numeric cell keeps the table readable while still never presenting a partial number as if it were complete. |
| Size measurement | Allocated blocks (`st_blocks * 512`) for space totals; `st_size` for per-file sizes and `--size` filters | See "Apparent vs. allocated size" below. |
| Path rendering | Relative to the walk root (`./sub/file.txt`) in text output; `-P`/`--full-paths` for absolute; `--json` always absolute | Absolute paths routinely run past 100 characters on a real tree and push the numeric columns off the right edge, burying the numbers the command exists to report. Relative is also what a user can act on directly from the same cwd. `--json` is the exception because a script consuming gaz's output may run from a different cwd than gaz did, so a relative path there would be ambiguous — and unlike a human reading a table, a consumer isn't paying a readability cost for the length. |
| `-P` on every path command | A shared `full_path_option` decorator, applied to all six commands with a path column (not `ext`) | A flag present on five of six commands is a worse inconsistency than one absent everywhere. `ext` is excluded rather than given a no-op flag: its rows are extensions, so `-P` there would parse and do nothing, which is its own kind of lie. |
| `largest` as its own command | Separate from `gaz list --sort size`, not a flag on it | They answer different questions: `list` ranks a directory's *immediate children* (a subdirectory row aggregating its whole subtree), `largest` ranks *individual files* anywhere beneath. Folding the second into the first would mean one command whose rows are sometimes directories-with-subtree-totals and sometimes single files — a mode switch, not a sort order. `--max-rows` doubles as the N, so no separate `-n` was needed. |

## Traversal order

`walk()` is breadth-first by default: it discovers every directory at depth
N before descending to depth N+1. On a truncated walk this means the
partial result still shows the tree's overall shape — every top-level
directory (and the next level, and so on) rather than complete, deep
coverage of whichever directory scandir happened to return first and zero
visibility into its siblings. For a command whose entire purpose is "tell
me what this tree looks like," a lopsided sample is actively misleading.

- **`--depth-first`** switches to the old stack-based order: complete
  coverage of the first branches, at the cost of breadth. Occasionally
  useful — e.g. confirming one specific subtree's full structure fast.
- **`--shuffle`** (optionally with **`--seed`** for reproducibility)
  randomizes sibling order at each directory before it's queued, so a
  truncated walk samples a different slice of a wide directory on each
  run instead of always the same alphabetically-first N entries. Cheap:
  each directory's own entries are shuffled in place, not the whole walk.
  Composes with `--depth-first`.

Implemented with a `collections.deque`: breadth-first pops from the left
(FIFO), depth-first pops from the right (LIFO) — same walker, same
budgets, just which end of the queue is read.

## Limits

Three independent budgets, each with a flag. `0` means unlimited for all three.

- `--max-seconds` (default `30`) — wall-clock budget. On by default: this
  is the one thing that guarantees a command returns.
- `--max-entries` (default `0`, i.e. unlimited) — filesystem entries
  visited. Opt-in, not on by default: on fast local storage there's no
  reason to cut a scan short on entry count when there's still time left;
  the risk this guards against (one pathological directory eating the
  whole time budget) is really a slow-storage problem. Pass a positive
  value to add it back.
- `--max-rows` (default `50`) — rows printed; aggregation (the Total line)
  continues past this regardless. Stays on by default — it's the guard
  against flooding a terminal or an LLM's context window, a concern that
  has nothing to do with how fast the walk itself was. Pass `0` for every
  row.

`--max-depth` is a scoping flag, not a budget — it changes what "complete" means.

The status line names whichever budget actually stopped the walk (never a
budget the caller left unlimited), so the re-run suggestion is always
something that would actually help.

## Apparent vs. allocated size

A file has two sizes, and conflating them produces answers that are wrong
by orders of magnitude:

- **Apparent size** (`st_size`) — the length a program reading the file
  sees.
- **Allocated size** (`st_blocks * 512`) — the disk space it actually
  occupies. This is what `du` reports.

They coincide for ordinary files and diverge wildly for two common cases:
**sparse files** (VM disk images, preallocated databases) and
**cloud-sync placeholders** (iCloud/Dropbox dataless files). A real
example that motivated this: a Colima VM image reported 100 GB apparent
while occupying 7 MB of blocks, which made `gaz` claim a 1 GB directory
held 120 GB. Across one real home directory the gap was 136 GB — over
half the reported total.

gaz's central question is "what is using my disk," so **space totals use
allocated size** (`WalkEntry.size`, `WalkResult.n_bytes`, every
directory total, `dup`'s reclaimable figure — deleting a file frees
blocks, not apparent bytes).

**Per-file sizes and `--size` filters use apparent size**
(`WalkEntry.apparent_size`). "How big is this file" and "`--size +1M`"
are questions about content length: a 5-byte file occupying one 4 KB
block is still a 5-byte file, and a `--size` filter that matched it
against 4096 would be surprising. `gaz list --json` emits both per row.

The one visible oddity is that small files show as one block (`4.0 KB`)
in `gaz list`'s size column. That's correct — it's the space they cost —
and it keeps a directory's total equal to the sum of its rows.

## Excluding directories

`--exclude PATTERN` (repeatable, glob against a directory's basename —
e.g. `--exclude node_modules`, `--exclude '.*'`) prunes a directory
*before* descent: it's never scanned, never appears in output, and never
counts against `--max-entries`. This is deliberately a walker-level
change rather than an output filter — the point isn't just cleaner
results, it's freeing up the time/entry budget so it's spent on
directories that actually matter instead of being burned inside a noisy
subtree. The walk root itself is never excluded even if its basename
matches. Available on all seven commands via the shared `limit_options`.

`gaz dup --skip-vendored` builds on this: it adds a curated list of
common package-manager/dependency directory names (`node_modules`,
`site-packages`, `.venv`, `vendor`, etc. — see `cli.VENDORED_DIR_NAMES`)
to the exclude set. It's opt-in, not on by default — gaz doesn't guess
what counts as noise without being asked, consistent with never silently
hiding data — and it composes with `--exclude` rather than replacing it.
The motivating case: the largest duplicate sets on a real large tree
were near-entirely inside an installed-package tree, where "reclaiming"
the space would mean breaking the installed environment, not cleaning
anything up.

## Output contract

Every command prints a table, then a one-line natural-language status. Both humans
and LLMs read the status line to know how much to trust the numbers.

Complete:

```
Scanned 1,204 dirs / 412,003 files in 8.2s. Complete.
```

Truncated:

```
Stopped at the 30s limit after 1,204 dirs / 412,003 files (~14% of an
estimated 2.9M). Numbers below are a lower bound. Re-run with
--max-seconds 300 for a fuller picture.
```

Rules for the status line:
- Say what stopped it, and what the user should change to get further.
- Never present a partial number as if it were total. Say "at least" or "lower bound."
- Report skipped/unreadable paths as a count, not a list.
- Say where the data came from — a live walk or a cached scan, and how old it is.

### Structured output (--json)

Every command accepts `--json` (in `filters.limit_options`, so it's uniform
across all six) as an alternative to the plain-text table + status line —
not an addition to it, and not a firehose: `--json` still respects
`--max-rows`, so a truncated table and a truncated JSON `rows` array show
the same number of rows for the same flags. The point is letting a result
feed into `jq`/`xargs`/another agent without re-parsing aligned text, while
keeping the exact same "don't treat a partial result as exhaustive"
guarantee the text status line gives a human.

One shared envelope (`report.json_output`), one command-specific `rows`
shape and `total` dict per command:

```json
{
  "rows": [ {"...": "command-specific keys, see below"} ],
  "complete": true,
  "stop_reason": null,
  "n_dirs": 1204,
  "n_files": 412003,
  "n_errors": 0,
  "elapsed": 8.2,
  "total": { "...": "command-specific summary" }
}
```

`complete`/`stop_reason`/`n_dirs`/`n_files`/`n_errors`/`elapsed` mirror
`WalkResult` directly — the same fields the text status line is built
from — so a consumer never has to parse a natural-language sentence to
know whether a result is partial. `dup` overrides `complete` to also
fold in its second (hashing) pass, matching `total_label`'s `complete=`
parameter.

Row shapes (raw numeric values, not human-formatted strings — that
formatting is what `--json` exists to skip):

| Command | Row keys | `total` keys |
|---|---|---|
| `ext` | `ext, count, total_size, median_size` | `files, bytes, filtered` |
| `list` | `name, path, type, n_files, n_dirs, size, apparent_size, mtime, complete` (`ctime` with `--fields created`) | `dirs, files, bytes, filtered, sort` |
| `find` | `path, type, size` | `matches` |
| `largest` | `path, size, apparent_size, mtime` | `files, bytes, shown_bytes, filtered, ranked_by` |
| `stale` | `path, age_seconds, size, suspicious_mtime` | `files, bytes, older_than, filtered, n_suspicious_mtime` |
| `empty` | `dir` | `empty_dirs, unvisited_dirs, scanned_dirs` |
| `dup` | `path, paths, copies, size_each, reclaimable` | `duplicate_sets, reclaimable_bytes, hash_complete, hash_stop_reason, n_hashed` |

## Cache

Repeat structural questions about the same tree are the common case, and re-walking
terabytes to answer them is the main cost. `gaz scan` walks once and stores the result
so later commands answer from the database in milliseconds.

**Location:** `~/.gazetteer/cache.db`, overridable with `GAZETTEER_HOME`.
Created on first use. One SQLite file, WAL mode.

SQLite is stdlib, single-file, and indexes cleanly into the tens of millions of rows —
so this adds no dependency. (This supersedes the earlier NDJSON manifest plan: NDJSON
requires a full re-read for every query, which defeats the purpose.)

### Schema

```sql
scans(id, root, started_at, finished_at, status, max_depth,
      cross_fs, follow_symlinks, n_dirs, n_files, n_bytes, n_errors)
      -- status: running | complete | truncated | aborted

entries(scan_id, path, parent, name, ext, size, mtime, is_dir)
      -- indexes: (scan_id, ext), (scan_id, parent), (scan_id, path)
```

Store full paths as text initially. If the DB gets uncomfortably large (roughly
150 bytes/file, so ~1.5 GB at 10M files), intern directory paths into a separate
table and store `parent_id` — but only once that's an actual problem.

Write in batched transactions of ~10k rows so an interrupted scan leaves usable data
rather than nothing.

### Cache resolution

This logic lives in one place (`cache.py`) and every command calls it. The ladder:

1. **Fresh, complete, covering scan** → serve from cache.
   A scan covers a query if its root is the query path or an ancestor, it finished
   `complete`, and its `max_depth` doesn't cut off the requested subtree.
2. **Stale, truncated, or aborted scan** → walk live by default, but mention the cache
   in the status line so the user can opt in. A truncated or aborted scan may only
   serve queries where the query root equals the scan root, and its results are always
   labeled a lower bound.
3. **No usable cache** → live bounded walk. This is v0 behavior and always works.
4. **Any cache error at all** — missing file, lock contention, corrupt DB, schema
   mismatch — → warn on stderr, fall back to a live walk, continue.

> The cache is an optimization, never a dependency. No command may fail because the
> cache is unavailable, and no command requires a prior scan.

### Flags

Shared by every read command:

- `--cache / --no-cache` (default: use cache when one qualifies)
- `--max-age DURATION` (default `24h`) — older scans are stale
- `--refresh` — ignore the cache, walk live, and write the result back

`gaz scan [PATH]` takes the standard limit flags. A scan stopped by a limit is stored
with `status=truncated` and remains useful under the rules above.

### Staleness

Age-based only. Do not attempt to detect filesystem changes — at this scale any check
cheap enough to run is unreliable, and any check reliable enough is as expensive as
rescanning. The honest approach is to report the scan's age and let the user decide.

### Management

- `gaz cache list` — scans on record: root, age, status, entry count, size on disk
- `gaz cache rm ROOT` / `gaz cache prune --older-than 30d`
- `gaz cache path` — print the DB location

### Status lines

```
412,003 files from cache (scanned 3h ago, complete).
```

```
Walked live in 8.2s. A cached scan of /data exists but is 4 days old;
pass --max-age 7d to use it, or --refresh to rebuild.
```

```
1,204 dirs from cache (scanned 2h ago, truncated at the 60s limit).
Numbers are a lower bound. Re-run: gaz scan /data --max-seconds 600
```

## Preview and convert

`gaz preview FILE` and `gaz convert FILE -o OUT` look *inside* a single
file rather than answering structural questions about a tree — the
natural next step after `gaz find`/`gaz list` locates something worth
reading. Both share one dispatch function, `convert.convert_to_text()`.

- **preview**: bounded to a terminal. Converts the file to readable text,
  then shows up to `--max-lines` (default `50`) of it, or the whole file
  with `--full`. Same "bounded, and says so when truncated" contract as
  every other command. A ruled banner above the content gives the file's
  name, apparent size, modified/created dates, and the conversion method —
  orientation the converted text itself can never supply ("is this the
  file I meant, and is it current?"). It uses apparent size, not allocated
  blocks, because it describes the file rather than its disk footprint.
  The rules matter: previewed content is arbitrary text, often Markdown
  with its own `#` headings, and an unruled metadata line reads as part of
  the document rather than as gaz's framing of it. Naming the method in
  the banner also keeps it out of the status line, which is then free to
  answer only "did I see all of it?"
- **convert**: unbounded, writes the full result to `-o OUTPUT`. Binary
  formats only (DOCX/PPTX/XLSX/PDF → MD/TXT/CSV) — JSON/YAML/TOML/XML are
  already text, so `convert` refuses them (`gaz preview` is the right tool)
  rather than growing into a general-purpose format translator.

Converter priority per format, each step attempted only if the previous
one is unavailable: `pandoc`/`pdftotext` (if on `$PATH`) → the matching
optional Python library from the `gaz[preview]` extra → a clear error
naming exactly what's missing. JSON/XML/CSV pretty-printing needs nothing
beyond stdlib; YAML and TOML-on-3.9/3.10 need `PyYAML`/`tomli` (no stdlib
option exists for either), so those two are the only "always needed for
this format to work at all" entries in the extra.

**Text markup formats are rendered to Markdown, not shown raw.**
HTML/RST/Org/LaTeX/EPUB/ipynb are all readable as plain text in a strict
sense, so "just print them" would work — but in a *bounded* preview the
boilerplate wins, and the first 50 lines of an HTML file are frequently
doctype, `<meta>`, and inline CSS before a word of prose. Markdown
carries the same semantics (headings, lists, tables, emphasis) in far
fewer lines, which is exactly the tradeoff a line-budgeted preview wants.

Rendered with pandoc's `gfm-raw_html` writer plus `--strip-comments`,
and each part of that is load-bearing: plain `markdown` appends attribute
noise to headings (`# Title {#title .class}`); `markdown_strict` falls
back to raw HTML for tables; and plain `gfm` passes through any HTML it
can't express, which on an app-shell page of layout `<div>`s made the
output *longer* than the source (a real 337-line page became 1,742
lines — dropping raw HTML brought it to 602 lines of actual content).

Unlike the binary formats, a missing pandoc here degrades rather than
fails: the raw source is shown with a note, because unconverted HTML is
still legible where an unconverted `.docx` is not. `.epub` is the
exception — it's a zip archive, so it fails outright like the office
formats.

**Encoded blobs are suppressed in `preview`, never in `convert`.**
`report.suppress_encoded_runs()` replaces long base64/hex runs with
`iVBORw0KGgoAAAAN… [12,847 chars of encoded data suppressed]`. A single
inline `data:` image can carry tens of kilobytes on one line, which in a
*bounded* preview is strictly destructive: it spends the entire line
budget (and, for an agent, the context window) on something no human or
model can read. Suppression runs *before* the `--max-lines` slice, so the
blob can't consume the budget it was flooding. `--raw` opts out.
`gaz convert` deliberately never suppresses — it writes a real file to
disk, where the actual bytes are the point.

Detection is heuristic, and tuned so that a false positive (hiding real
text) is much worse than a false negative (leaking some noise):

- Runs shorter than 64 chars are always shown. Below that the
  data-vs-identifier call is unreliable, and a git SHA or a short token
  is worth seeing.
- Runs of 120+ chars are always suppressed. No word or identifier runs
  that long without a separator, and this is the only test that catches
  base64 of *repetitive* input — `base64(b"x" * 300)` is `"eHh4eHh4…"`,
  a 33% vowel rate that reads as prose to any character-frequency test.
- Between those bounds: pure hex is suppressed (checked separately, since
  `a`/`e` are hex digits and make hashes score deceptively vowel-rich),
  and otherwise a run needs mixed case or digits plus a sub-26% vowel
  rate — English runs ~38%.

`gaz preview --check-deps` reports the converter ladder for every format —
which converter would actually be chosen, or what's missing — without
needing a file to try it on. It distinguishes formats that degrade
gracefully (reported usable, with the caveat in the detail column) from
those that fail outright. It's generated from `_CONVERTER_REQUIREMENTS`, kept
adjacent to the dispatch it describes so the two can't drift.

**Every failure path returns an `UnsupportedFormat` with an actionable
message; none leak a library exception.** Each optional library raises its
own type for a corrupt, empty, or mislabeled file
(`PackageNotFoundError`, `EmptyFileError`, `BadZipFile`, ...), and letting
those propagate produced a raw traceback from a library the user may not
know they have — reading as "gaz crashed" rather than "this file isn't
what its extension says." `convert._library_errors()` wraps every library
call site and re-raises with the path, the format, and the underlying
error. Relatedly, when `pandoc` runs but fails *and* no Python fallback is
installed, pandoc's stderr is carried into the error rather than being
replaced by a generic "no converter available" — it's the only real
explanation of what went wrong.

Neither command takes the tree-walking budget flags (`--max-entries`,
`--ext`, `--size`, ...) — they operate on one file, not a directory. The
one bounded-operation nod is `--max-seconds`, which caps a
`pandoc`/`pdftotext` subprocess call: a timeout is reported through the
result (`preview` says so and suggests a larger budget or `gaz convert`;
`convert` still writes whatever was produced) rather than raised — the one
genuine exit-non-zero case for these two commands is a file they cannot
convert *at all* (no converter available, or the input doesn't parse),
which is a real failure, not a truncation.

## Layout

```
gazetteer/
├── pyproject.toml          # [project.scripts] gaz = "gazetteer.cli:main"
├── src/gazetteer/
│   ├── cli.py              # click group + the seven tree-walking commands
│   ├── preview_cli.py      # the preview/convert commands (single-file, no walker)
│   ├── walk.py             # bounded walker — the one core primitive
│   ├── filters.py          # shared --max-*/--ext/--pattern/--size options
│   ├── cache.py            # SQLite store + cache resolution (phase 2)
│   ├── report.py           # table + status-line rendering
│   └── convert.py          # format detection + single-file conversion (used by preview_cli.py)
└── tests/
```

Seven modules. Resist splitting further until one exceeds ~300 lines —
`cli.py` has already blown past this (714 lines as of 0.1.2, six
commands each repeating the same walk/filter/render-or-json shape); see
TODO.md's item on splitting it before adding another cross-cutting flag.

Commands never touch SQL or `os.scandir` directly. They ask `cache.py` for a result
set; it either answers from the DB or delegates to `walk.py`. That single seam is what
keeps the cached and uncached paths from drifting apart.

## v0 scope

Build the walker first, then these three commands against it:

- `gaz tree [PATH]` — depth-limited structure with per-directory file counts and sizes
- `gaz ext [PATH]` — file-extension breakdown (count, total size, median size).
  This is the highest-value command for CV datasets and should land first.
- `gaz find PATTERN [PATH]` — bounded search, filtering during the walk rather than
  after it

Deferred until the above are solid: `gaz du`, `gaz scan` (manifest).

What actually shipped in v0 beyond this original three-command scope:
`gaz dup`, `gaz stale`, `gaz empty` (cleanup-focused commands built on the
same walker), and `gaz preview`/`gaz convert` (single-file inspection —
see "Preview and convert" above). `gaz du` and `gaz scan` remain deferred.

`gaz tree` above shipped and was later renamed **`gaz list`**, after real
use showed the multi-level listing it implied was the wrong shape: a
nested dump re-answers at every level what one level plus subtree totals
answers once. `gaz list` shows a single level (like `ls`) where each
subdirectory carries the totals for everything beneath it, which also
made `--recursive` unnecessary — it was removed rather than kept as a
second way to ask the same question.

## Later phases

**Phase 2 — cache.** `gaz scan` plus the SQLite store and resolution ladder described
above. Land the store and `gaz cache list` first, then wire commands to the resolver
one at a time — each should keep working unchanged if the cache is deleted mid-way.

**Phase 3 — CV-aware.** Commands that understand dataset conventions: train/val/test
split balance, annotation-to-image pairing, orphaned labels, class distribution from
COCO/VOC/YOLO files.

**Phase 4 — MCP server.** Expose the same commands as MCP tools. The output contract
above is already designed for this: bounded output and an explicit
completeness signal are exactly what an agent needs to avoid acting on partial data.

## Non-goals

- No progress bars, TUI, or interactive browsing. `ncdu` exists.
- No config file. Flags and sensible defaults only.
- No plugin system, no abstract base classes, no dependency injection.
- No async or multiprocessing in v0. Add it only after profiling proves the walk is
  I/O-bound in a way threading actually fixes.
- No database beyond stdlib SQLite. No server, no ORM, no migration framework — on a
  schema change, drop the cache and rescan.
- No cache write-back from read commands. Only `gaz scan` and `--refresh` write.
  Otherwise a `gaz find` with tight limits would poison the cache with partial data.

## Conventions for contributors and agents

- Dependencies: `click` only in the core (required) install. Adding a required
  dependency needs a note in this file. Format-specific libraries for
  `preview`/`convert` (PyYAML, tomli, python-docx, python-pptx, openpyxl,
  pypdf) are the one exception — they live in the optional `gaz[preview]`
  extra, never core `dependencies`, and every format they cover must degrade
  gracefully (external tool if present, else the optional lib if installed,
  else a clear error naming what to install) rather than making `gaz`
  uninstallable without them.
- Every command routes through `walk.py`. If a command needs its own traversal,
  that's a signal the walker's interface is wrong — fix the walker.
  (`preview`/`convert` are the exception: they operate on one file, not a
  tree, so they route through `convert.py` instead.)
- Test the walker against a fixture tree containing a symlink loop, an unreadable
  directory, and a deeply nested path. These are the cases that break naive walkers.
- Every command needs a test asserting it produces correct output with the cache
  deleted, and a second asserting cached and live results agree on the same tree.
- Test the cache against a corrupt DB file and a read-only `~/.gazetteer/`. Both must
  warn and fall back, not raise.
- Test every `convert.py` converter's missing-dependency path (fake
  `shutil.which`/module availability) so the "no converter" error message
  stays accurate as new formats are added, and gate any test needing a real
  `pandoc`/`pdftotext`/optional library behind a skip so the suite stays
  green without them installed.
- Test each converter's *corrupt-input* path too, not just its
  missing-dependency path: feed a file whose extension lies about its
  contents and assert an `UnsupportedFormat` comes back rather than the
  library's own exception. These are separate failures with separate
  fixes, and only the wrapped one is safe to show a user.
- Prefer deleting code to adding a flag.
