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

## Excluding directories

`--exclude PATTERN` (repeatable, glob against a directory's basename —
e.g. `--exclude node_modules`, `--exclude '.*'`) prunes a directory
*before* descent: it's never scanned, never appears in output, and never
counts against `--max-entries`. This is deliberately a walker-level
change rather than an output filter — the point isn't just cleaner
results, it's freeing up the time/entry budget so it's spent on
directories that actually matter instead of being burned inside a noisy
subtree. The walk root itself is never excluded even if its basename
matches. Available on all six commands via the shared `limit_options`.

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
natural next step after `gaz find`/`gaz tree` locates something worth
reading. Both share one dispatch function, `convert.convert_to_text()`.

- **preview**: bounded to a terminal. Converts the file to readable text,
  then shows up to `--max-lines` (default `50`) of it, or the whole file
  with `--full`. Same "bounded, and says so when truncated" contract as
  every other command.
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
│   ├── cli.py              # click group + the six tree-walking commands
│   ├── preview_cli.py      # the preview/convert commands (single-file, no walker)
│   ├── walk.py             # bounded walker — the one core primitive
│   ├── filters.py          # shared --max-*/--ext/--pattern/--size options
│   ├── cache.py            # SQLite store + cache resolution (phase 2)
│   ├── report.py           # table + status-line rendering
│   └── convert.py          # format detection + single-file conversion (used by preview_cli.py)
└── tests/
```

Seven modules. Resist splitting further until one exceeds ~300 lines.

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
- Prefer deleting code to adding a flag.
