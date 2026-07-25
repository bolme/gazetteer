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
flags (`--max-seconds`, `--max-entries`, `--max-rows`, `--max-depth`), and
most accept `--ext`, `--pattern`, and `--size` to scope what's counted.

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

### `gaz tree` — per-directory file counts and sizes

Depth-limited structure with a running total, sorted by size.

```
$ gaz tree /data/dataset --max-depth 2
dir                     n_files  total_size
----------------------  -------  ----------
/data/dataset/train     820,451  98.1 GB
/data/dataset/val       102,340  14.2 GB
/data/dataset/test      60,221   6.1 GB

Total: 3 dirs, 983,012 files, 118.4 GB
Scanned 1,204 dirs / 964,012 files in 8.2s. Complete.
```

### `gaz find` — bounded pattern search

Filters during the walk rather than after it, so a narrow search over a
huge tree doesn't pay the cost of collecting everything first.

```
$ gaz find "*.xml" /data/dataset --size ">1M"
path                                type  size
----------------------------------  ----  -----
/data/dataset/train/ann/0042.xml    file  1.2 MB

Scanned 1,204 dirs / 964,012 files in 6.1s. Complete.
```

### `gaz dup` — duplicate files by content hash

Groups candidates by size first (cheap), then hashes only same-size groups
under a separate `--max-hash-seconds` budget, and reports reclaimable space.

```
$ gaz dup /data/dataset
path (first copy)                    copies  size_each  reclaimable
------------------------------------  ------  ---------  -----------
/data/dataset/train/images/0001.jpg  3       241.2 KB   482.4 KB

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
(default 50) of the result.

```
$ gaz preview annotations.json
{
  "image": "0001.jpg",
  "boxes": [
    [10, 20, 100, 200]
  ],
  "label": "car"
}

Showing all 8 lines (method: stdlib-json). Complete.
```

```
$ gaz preview report.docx
[converted markdown, up to 50 lines]

Showing 50 of 812 lines (method: pandoc). Re-run with --full to see
everything, or `gaz convert` to save it to a file.
```

`--full` shows the whole file regardless of `--max-lines`. If no converter
is available for a format, `preview` fails with a message naming exactly
what to install — it never guesses or emits garbage.

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

See [DESIGN.md](DESIGN.md) for the full design rationale, and
[AGENTS.md](AGENTS.md) if you're an AI agent working in this repo.

## Why "gazetteer"

A gazetteer is a geographic index — compiled once from survey work, then
consulted instead of re-surveying. That's the idea behind the name: a
possible future caching command could walk a tree once and store the
result, so later commands answer from an index in milliseconds instead of
re-walking terabytes. Not built yet — see [DESIGN.md](DESIGN.md)'s "Later
phases" for the sketch. Installed as `gaz` on PyPI (`gazetteer` was
blocked by PyPI's name policy), typed as `gaz`.

## Status

v0: the bounded walker plus `ext`, `tree`, `find`, `dup`, `stale`, `empty`,
and the single-file `preview`/`convert` pair. No caching yet — every
command does a live bounded walk or a live conversion. See
[DESIGN.md](DESIGN.md)'s "Later phases" for what's planned (a
SQLite-backed cache, CV-dataset-aware commands, an MCP server).

## License

MIT — see [LICENSE](LICENSE).
