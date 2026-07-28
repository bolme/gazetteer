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
path                                type  size
----------------------------------  ----  -----
/data/dataset/train/ann/0042.xml    file  1.2 MB

Scanned 1,204 dirs / 964,012 files in 6.1s. Complete.
```

### `gaz largest` — the biggest individual files

`gaz list` ranks a directory's immediate children; `gaz largest` ranks
single files across the whole subtree — the `du -a | sort -rn | head`
answer. `--max-rows` is the N (default 50).

```
$ gaz largest ~ --max-rows 4
size     modified    path
-------  ----------  ------------------------------------------------
27.7 GB  2026-07-25  ./exports/train_v3.tar
16.8 GB  2026-06-11  ./exports/train_v2.tar
14.1 GB  2026-03-30  ./checkpoints/epoch_120.pt
7.1 GB   2026-06-27  ./raw/session_04.mp4

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
path                                age   size
----------------------------------  ----  ------
/data/dataset/exports/old_run.tar   210d  1.2 GB

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
------------------------------------
/data/dataset/train/images/.tmp_abc

Total: 1 empty directories
Scanned 1,204 dirs / 964,012 files in 8.2s. Complete.
```

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
