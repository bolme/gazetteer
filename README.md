# gazetteer (`gaz`)

**Bounded structural queries for huge directory trees.**

`find`, `du`, and `grep` were not built for multi-terabyte datasets. On a
tree with millions of files, they hang for minutes with no output, or they
return and flood your terminal (and an LLM's context window) with hundreds
of thousands of lines. Ctrl-C gives you nothing back either way.

`gaz` answers structural questions — extension breakdowns, size by
directory, duplicates, stale files, empty directories — under explicit
time, count, and output budgets, and always tells you clearly when it
stopped early instead of silently giving you a partial answer disguised as
a complete one.

> Every operation is bounded, and every truncated result says so.

A partial answer delivered in 30 seconds is more useful than a complete
answer that never arrives. That's the whole product.

## Install

```
pip install gaz
```

(The PyPI distribution is named `gaz`, not `gazetteer` — PyPI's admin
name policy blocks the latter as a generic word. The command, the
`import gazetteer` package internals, and everything else are unaffected.)

`gaz preview`/`gaz convert` work out of the box for JSON/CSV/XML/Markdown
(stdlib) and for anything `pandoc`/`pdftotext` handle if installed
separately. For YAML/TOML pretty-printing and Python fallbacks when
`pandoc`/`pdftotext` aren't available (DOCX/PPTX/XLSX/PDF), install the
extra:

```
pip install "gaz[preview]"
```

### Developing locally

```
uv pip install -e ".[dev]"
```

If that leaves `gaz` raising `ModuleNotFoundError: No module named
'gazetteer'`, your environment is likely mangling `.pth`-based editable
installs. Use the workaround script instead, which symlinks the package
into `site-packages` directly:

```
./scripts/reinstall-dev.sh
```

## Commands

Every command takes an optional `PATH` (defaults to `.`), the shared budget
flags (`--max-seconds`, `--max-entries`, `--max-rows`, `--max-depth`), the
traversal-order flags (`--depth-first`, `--shuffle`, `--seed`), a repeatable
`--exclude PATTERN` to prune noisy subtrees (glob against a directory's
basename, e.g. `--exclude node_modules`, `--exclude '.*'` — pruned before
descent, so it also frees up budget rather than just hiding output), `--json`
for a bounded structured-output alternative to the text table (see below),
and most accept `--ext`, `--pattern`, and `--size` to scope what's counted.

Paths print relative to the directory you asked about (`./sub/file.txt`) —
absolute paths on a real tree push the numbers off the right edge. Pass
`-P`/`--full-paths` for absolute paths with symlinks resolved. `--json`
always emits absolute paths regardless, since whatever consumes it may be
running from a different directory.

### `gaz ext` — file-extension breakdown

The highest-value command for understanding a CV dataset at a glance:
count, total size, and median size per extension.

```
$ gaz ext /data/dataset
ext   count    total_size  median_size
----  -------  ----------  -----------
.jpg  482,123  118.4 GB    241.2 KB
.xml  482,123  3.1 GB      6.6 KB
.txt  12       4.0 KB      340 B

Scanned 1,204 dirs / 964,012 files in 8.2s. Complete.
```

### `gaz list` — list a directory, with subtree totals

Like `ls`, but every subdirectory reports how many files and how many
bytes live anywhere beneath it — the question `ls` can't answer. Rows are
the direct children of the listed directory only; the counts they carry
are what makes one level enough.

```
$ gaz list /data/dataset
name       n_files  size      modified
---------  -------  --------  ----------
train/     820,451  98.1 GB   2026-03-14
val/       102,340  14.2 GB   2026-03-14
test/      60,221   6.1 GB    2026-03-14
README.md  -        4.2 KB    2026-01-08

Total: 1,204 dirs, 983,012 files, 118.4 GB
Scanned 1,204 dirs / 964,012 files in 8.2s. Complete.
```

Sort with `--sort name|size|files|modified|created` (`--reverse` flips it;
directories always sort before files) and add columns with `--fields
created|dirs|path`. Rows show bare names here, since they're always exactly
one level down; the shared `-P` swaps them for resolved absolute paths (a
symlink shows as `link -> target`, so it stays distinguishable from the
directory it points at).

A `*` after a directory name (`train/*`) means the walk stopped before
that subtree was fully scanned, so its counts and sizes are lower bounds
rather than totals.

Sizes are the disk space actually used (allocated blocks, like `du`), not
the files' apparent length. The difference matters: a sparse VM image or
an un-downloaded cloud file can claim 100 GB while occupying a few MB.
`--size` filters still match apparent length, since `--size +1M` is a
question about content, not blocks — see [DESIGN.md](DESIGN.md).

### `gaz find` — bounded pattern search

Filters during the walk rather than after it, so a narrow search over a
huge tree doesn't pay the cost of collecting everything first. Unlike
`list`/`ext`/`stale`, `PATTERN` here is positional, not `--pattern` — this
is intentional (see DESIGN.md), and `gaz find --pattern ...` errors with a
pointer to the correct form rather than a generic "no such option."

```
$ gaz find "*.xml" /data/dataset --size ">1M"
path                    type  size
----------------------  ----  ------
./train/ann/0042.xml    file  1.2 MB

Scanned 1,204 dirs / 964,012 files in 6.1s. Complete.
```

### `gaz largest` — the biggest individual files

`gaz list` ranks a directory's immediate children; `gaz largest` ranks
single files across the whole subtree — the `du -a | sort -rn | head`
answer. `--max-rows` is the N (default 50).

```
$ gaz largest /data/dataset --max-rows 4
size     modified    path
-------  ----------  --------------------------------------
4.2 GB   2026-03-14  ./exports/train_v3.tar
1.8 GB   2026-02-02  ./exports/train_v2.tar
612.0 MB 2026-03-14  ./checkpoints/epoch_120.pt
418.0 MB 2026-01-19  ./raw/session_04.mp4

Showing 4 of 964,012 files (7.0 GB of 118.4 GB).
Total: 964,012 files, 118.4 GB
Scanned 1,204 dirs / 964,012 files in 8.2s. Complete.
```

`--min-size 10M` skips small files before the sort — a cheap pre-filter on
a huge tree, since anything under the bound can't place in the top N.

Sizes are disk space used, so the total is what deleting those files would
actually reclaim. `--apparent` ranks by file length instead, which is what
surfaces sparse files and cloud placeholders — a VM disk image can be #1
by apparent size and unremarkable by allocated blocks.

### `gaz sample` — estimate huge subdirectories `gaz list` can't finish walking

For a tree so large that even `gaz list` can't fully walk one of its
subdirectories in a reasonable time. Scans each immediate subdirectory of
PATH with a frontier-based adaptive sampler that reads each directory at
most once — the whole point is to make real progress on trees a bounded
walk can't cover. Plain files directly inside PATH are listed too (like
`gaz list`), with no scanning needed since a file's own size/owner/mtime
is already the complete answer — those rows are always exact and never
carry a `*` or `-` marker. `--max-seconds` is a **total** budget for the
whole command, split in two passes so runtime stays predictable
regardless of how many subdirectories PATH has: 33% divided equally
across every subdirectory first (so small ones reliably finish), then
the rest round-robined in small slices across whatever's still
incomplete until the clock runs out. Every row is one of two kinds:

```
$ gaz sample /data/dataset --max-seconds 15
name       files                dirs             size                activity  ext types  ext
---------  -------------------  ---------------  ------------------  --------  ---------  ------------------------------
  val/     102,340              1,204            14.2 GB              2d ago    2          .jpg(96%) .xml(4%)
  test/    60,221               712              6.1 GB               5d ago    2          .jpg(97%) .xml(3%)
* train/   119,697+ (~501,819)  1,822+ (~7,603)  1.5 GB+ (~2.5 GB)   3h ago    5          .jpg(98%) .png(1%) .xml(1%)

2 of 3 subdirectories fully scanned (exact).
* marks a subdirectory that wasn't fully scanned within the 15s total
--max-seconds budget: "N+ (~M)" means N is a true lower bound and M is a
rough, possibly-biased estimate of the real total — see
docs/sample-estimation.md. Re-run with a larger --max-seconds
for a tighter lower bound.
Scanned 3,738 dirs / 182,258 files in 15.0s.
Total: 182,258 files, 21.8 GB confirmed (~1,001,922 files, ~30.4 GB estimated).
```

The last two lines summarize the whole run: how much work `--max-seconds`
actually bought (directories and files visited, wall-clock time), then a
grand total across every row. `Total` follows the same confirmed/
estimated split as any individual row — a plain number when every
subdirectory finished exactly, or `confirmed (~estimated)` when at least
one didn't, summing each row's lower bound and estimate respectively.

`val/` and `test/` finished within budget, so their numbers are exact
totals, identical to what `gaz list` would eventually report. `train/`
didn't — `119,697+` is a true floor (every file actually counted so far,
never inflated), and `(~501,819)` is a statistical estimate of the rest,
which **can be meaningfully wrong**, sometimes by a large margin, at
partial coverage — see docs/sample-estimation.md for why. Treat the
estimate as a rough size-of-the-problem signal and the lower bound as
the only number that's actually guaranteed true; re-running with a
larger `--max-seconds` tightens the lower bound and, given enough time,
converges to exact.
The `dirs` column follows the same lower-bound/estimate split. Sort with
`--sort name|size|files|dirs|activity` (default `name`, `--reverse`
flips it) — ranking uses the estimate, not the lower bound, so a huge
but barely-scanned subdirectory still sorts as huge instead of as
whatever sliver of it happened to get counted.

The `activity`, `ext types`, and `ext` columns are always an **exact
observation/tally of files actually scanned so far**, never extrapolated
the way size/files/dirs are — even on `train/`'s partial row, they
describe only the 119,697 files actually counted, not a guess about the
whole subtree. `activity` shows how long ago the most recently modified
file anywhere in the subtree was touched — the simplest useful "is this
still being used" signal, since guessing at an unscanned directory's
likely recency (or extension mix, or file ownership) would be a much
shakier statistical claim than guessing at its total size, so this
module doesn't attempt any of them (see
docs/sample-estimation.md). `ext types` is how many distinct
extensions exist — a variety signal `ext` alone doesn't give — and `ext`
packs in as many `ext(NN%)` entries as fit in 30 characters (ranked
biggest-first, no `+N other` filler), so a directory with only a couple
of extensions shows all of them while one with many shows however many
actually fit.

By default, `ext` (and `--fields owners`, below) rank by **total bytes**,
since "what's using the space" is usually the more useful question —
`--rank-by count` switches both to file counts instead:

```
$ gaz sample /data/dataset --rank-by count
name    files    ...  ext types  ext
------  -------  ...  ---------  ------------------
val/    102,340  ...  2          .xml(50%) .jpg(50%)
```

`--fields owners` adds one more column in the same spirit — the single
top file owner, ranked the same way as `ext`, with a percentage only
shown when they don't own everything (e.g. `alice(80%)`, or bare `alice`
at 100%) — off by default since it's extra width most runs don't need:

```
$ gaz sample /data/dataset --fields owners
name    files    ...  ext                  owner
------  -------  ...  -------------------  ----------
val/    102,340  ...  .jpg(96%) .xml(4%)   alice(92%)
```

A `denied` column appears automatically, only when at least one
subdirectory hit a permission error — a tree gaz can read all of never
shows it. It counts directories anywhere in that row's subtree that
couldn't be opened (blank rather than `0` for a row with nothing denied,
so the handful of rows that hit a real problem stand out), and a row
with any denials gets a leading `-` instead of `*`/blank — `-` takes
priority over `*` even on a row that's also incomplete, since "gaz
couldn't read part of this" is a more specific, more actionable fact
than "the scan ran out of time":

```
$ gaz sample /home/shared
name         files    dirs    denied  size    ...
-----------  -------  ------  ------  ------  ...
  alice/     102,340  1,204           14.2 GB ...
- bob/       8,204    340     3       1.1 GB  ...
```

`bob/`'s 3 denied directories don't stop the row from being `exact` —
every directory gaz *could* open was fully scanned; it's an honest count
of what was inaccessible, not a sign the scan itself was incomplete.

Total wall-clock time is bounded by `--max-seconds` (default 30)
regardless of subdirectory count — a directory with 2 subdirectories and
one with 200 both finish in roughly the same time, unlike a fixed
per-subdirectory budget, which would make total runtime scale with how
many subdirectories PATH happens to have.

### `gaz dup` — duplicate files by content hash

Groups candidates by size first (cheap), then hashes only same-size groups
under a separate `--max-hash-seconds` budget, and reports reclaimable space.
Add `--skip-vendored` to exclude common package-manager/dependency
directories (`node_modules`, `site-packages`, `.venv`, `vendor`, etc.) —
duplicates inside them are a byproduct of how packages ship, not something
you can reclaim without breaking the installed environment, so they're
usually just noise. Opt-in, and composes with `--exclude` rather than
replacing it.

Every copy in a set is listed, not just a representative — the point of
the command is deciding what to delete, and that needs the other paths.
`--max-rows` limits duplicate *sets*, not individual lines.

```
$ gaz dup /data/dataset
3 copies × 241.2 KB = 482.4 KB reclaimable
    ./train/images/0001.jpg
    ./train/images/0417.jpg
    ./val/images/0033.jpg

Total: 1 duplicate sets, 482.4 KB reclaimable
Hashed 6 candidate files. Complete.
Scanned 1,204 dirs / 964,012 files in 8.2s. Complete.
```

### `gaz stale` — old files worth archiving or deleting

```
$ gaz stale /data/dataset --older-than 180d --size ">100M"
path                     age   size
-----------------------  ----  ------
./exports/old_run.tar    210d  1.2 GB

Total: 1 files older than 180d, 1.2 GB
Scanned 1,204 dirs / 964,012 files in 8.2s. Complete.
```

Ages within a week of the Unix epoch are flagged with `(?)` — that's
almost always a timestamp reset by some other tool (a cache, archive, or
sync tool), not a genuinely decades-old file, and gaz calls it out rather
than reporting it indistinguishably from a real old file.

### `gaz empty` — dead directories

Finds directories with no files anywhere in their subtree — debris from
partial deletions or failed extraction jobs.

```
$ gaz empty /data/dataset
dir
------------------------------
./train/images/.tmp_abc/

1 directories confirmed empty of 1,204 that were fully scanned.
Scanned 1,204 dirs / 964,012 files in 8.2s. Complete.
```

The count is only ever directories whose *entire* subtree was scanned. One
merely discovered before the walk stopped is reported separately as
unvisited, never mislabeled empty.

### `gaz preview` — a bounded, format-aware look inside one file

Pretty-prints JSON/YAML/TOML/XML/CSV and converts DOCX/PPTX/XLSX/PDF to
readable Markdown/text (via `pandoc`/`pdftotext` if installed, or the
`gaz[preview]` extra's Python fallbacks), then shows up to `--max-lines`
(default 50) of the result under a one-line header giving the file's size
and timestamps.

```
$ gaz preview annotations.json
================================================================
annotations.json
118 B  ·  modified 2026-02-14  ·  created 2026-01-30  ·  stdlib-json
================================================================

{
  "image": "0001.jpg",
  "boxes": [
    [10, 20, 100, 200]
  ],
  "label": "car"
}

Showing all 8 lines. Complete.
```

HTML, RST, Org, LaTeX, EPUB, and Jupyter notebooks are rendered to
Markdown rather than shown raw. They're technically readable as text, but
in a bounded preview the boilerplate wins: an HTML file's first 50 lines
are often doctype, `<meta>` tags, and inline CSS before any prose.
Markdown keeps the headings, lists, and tables in far fewer lines.

```
$ gaz preview report.html
=================================================================================
report.html
551 B  ·  modified 2026-07-28  ·  created 2026-07-28  ·  pandoc (html -> markdown)
=================================================================================

# Quarterly Report

Revenue grew **12%** over the prior quarter.

## Regions

| Region | Revenue |
|--------|---------|
| North  | \$1.2M  |
| South  | \$0.9M  |

Showing all 13 lines. Complete.
```

Without `pandoc` these fall back to the raw source with a note — unlike a
`.docx`, raw HTML is still legible. (`.epub` is the exception: it's a zip
archive, so it fails outright.)

Long runs of base64/hex — inline `data:` images, embedded fonts, hashes —
are replaced with a short placeholder, since a single embedded image can
carry tens of kilobytes on one line and eat the whole preview budget
while conveying nothing readable:

```
"image": "data:image/png;base64,iVBORw0KGgoAAAAN… [12,847 chars of encoded data suppressed]",
```

Runs under 64 characters are left alone, and `--raw` disables suppression
entirely. `gaz convert` never suppresses — it writes the real file.

`--full` shows the whole file regardless of `--max-lines`. If no converter
is available for a format, `preview` fails with a message naming exactly
what to install — it never guesses or emits garbage. A file that's corrupt
or mislabeled (a `.docx` that isn't really one) gets an error naming the
file and the converter that rejected it, not a library traceback.

`gaz preview --check-deps` takes no file and reports which converter each
format would actually use, so you can see what's missing before hitting it:

```
$ gaz preview --check-deps
format  usable  converter
------  ------  ----------------------------------------
docx    yes     using pandoc
pdf     NO      missing: pdftotext or pypdf (pdftotext ships with poppler)
json    yes     stdlib
...

1 format(s) have no converter: pdf. Install pandoc and/or poppler, or run
`pip install gaz[preview]`.
```

### `gaz convert` — save a converted file to disk

Same conversion machinery as `preview`, unbounded, written to `-o OUTPUT`
instead of a terminal. Binary formats only (DOCX/PPTX/XLSX/PDF → MD/TXT/CSV)
— JSON/YAML/TOML/XML are already text, so `gaz preview` is the right tool
for those instead.

```
$ gaz convert report.docx -o report.md
Wrote 41.2 KB to report.md (method: pandoc). Complete.

$ gaz convert data.xlsx -o data.csv
Wrote 3.1 KB to data.csv (method: openpyxl). Complete.
```

Output format is inferred from `-o`'s extension; `--to FORMAT` overrides.
A conversion timeout (`--max-seconds`, default 120) still writes whatever
was produced and says so, rather than losing the work.

## The output contract

Every command prints a table, then a one-line natural-language status.
Complete:

```
Scanned 1,204 dirs / 412,003 files in 8.2s. Complete.
```

Truncated — never presented as if it were the full answer:

```
Stopped at the 30.0s limit after 1,204 dirs / 412,003 files. Numbers
below are a lower bound. Re-run with --max-seconds 300 for a fuller
picture.
```

For the tree-walking commands, exit code is always `0` on a successful
run, including truncated ones — partial is a normal outcome, not an
error. The status line is what tells you, and any agent reading your
output, how much to trust the numbers. `preview`/`convert` are the one
exception: a truncated conversion still exits `0` and says so (same
philosophy), but a file `preview`/`convert` genuinely cannot handle at
all — no converter installed, unparseable input — is a real failure and
exits non-zero with a message naming exactly what's missing.

Add `--json` for the same information as structured output instead of a
text table — still bounded by `--max-rows`, still carries `complete`/
`stop_reason` rather than a sentence you'd have to parse:

```
$ gaz ext /data/dataset --json --max-rows 2
{
  "rows": [
    {"ext": ".jpg", "count": 482123, "total_size": 127165956096, "median_size": 246989},
    {"ext": ".xml", "count": 482123, "total_size": 3328599654, "median_size": 6758}
  ],
  "complete": true,
  "stop_reason": null,
  "n_dirs": 1204,
  "n_files": 964012,
  "n_errors": 0,
  "elapsed": 8.2,
  "total": {"files": 964012, "bytes": 130508377170, "filtered": false}
}
```

See [DESIGN.md](DESIGN.md) for the full design rationale (including the
per-command `--json` row/total schema), and [AGENTS.md](AGENTS.md) if
you're an AI agent working in this repo.

## Traversal order

Walks are **breadth-first by default**: every directory at depth N is
discovered before descending to depth N+1. On a truncated walk this means
the partial result still shows the tree's overall shape — every top-level
directory, not just complete coverage of whichever one happened to be
scanned first while its siblings go undiscovered.

```
$ gaz list /data/dataset --max-entries 50
name     n_files  size     modified
-------  -------  -------  ----------
train/*  12       1.2 GB   2026-03-14
val/*    8        340 MB   2026-03-14
test/*   6        290 MB   2026-03-14
docs/    3        14 KB    2026-02-02

Total (at least, walk stopped early): 5 dirs, 29 files, 1.8 GB
* marks a directory whose subtree wasn't fully scanned — its counts and sizes are lower bounds, not totals.
Stopped at the 50 entries limit ...
```

- **`--depth-first`** — the opposite: complete, deep coverage of the first
  branches at the cost of breadth. Useful when you specifically want to
  confirm one subtree's structure fast rather than survey the whole tree.
- **`--shuffle`** — randomizes sibling order at each directory before it's
  explored, so a truncated walk samples a different slice of a wide
  directory on each run instead of always the same alphabetically-first
  entries. Add **`--seed N`** for a reproducible shuffle.

```
$ gaz find "*.jpg" /data/dataset --shuffle --max-entries 1000
# a different sample of matches each run

$ gaz find "*.jpg" /data/dataset --shuffle --seed 42 --max-entries 1000
# the same sample every time
```

## Why "gazetteer"

A gazetteer is a geographic index — compiled once from survey work, then
consulted instead of re-surveying. That's the idea behind the name: a
possible future caching command could walk a tree once and store the
result, so later commands answer from an index in milliseconds instead of
re-walking terabytes. Not built yet — see [DESIGN.md](DESIGN.md)'s "Later
phases" for the sketch. Installed as `gaz` on PyPI (`gazetteer` was
blocked by PyPI's name policy), typed as `gaz`.

## Status

v0: the bounded walker plus `ext`, `list`, `find`, `largest`, `dup`,
`stale`, `empty`, and the single-file `preview`/`convert` pair. No caching
yet — every command does a live bounded walk or a live conversion. See
[DESIGN.md](DESIGN.md)'s "Later phases" for what's planned (a
SQLite-backed cache, CV-dataset-aware commands, an MCP server).

## License

MIT — see [LICENSE](LICENSE).
