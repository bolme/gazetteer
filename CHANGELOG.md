# Changelog

## 0.1.3 (unreleased)

### Fixed

- **Sizes now measure disk space actually used, not apparent length.**
  gaz summed `st_size`, which for a sparse file or an un-downloaded
  cloud-sync placeholder can be orders of magnitude larger than the space
  it occupies — a Colima VM image reported 100 GB while using 7 MB of
  blocks, making `gaz` claim a 1 GB directory held 120 GB. Space totals
  now use allocated blocks (`st_blocks * 512`) and agree with `du`.
  Per-file size columns and `--size` filters still use apparent length,
  since "how big is this file" is a question about content; `gaz list
  --json` emits both as `size` and `apparent_size`. **Behavior change:**
  reported sizes will drop on trees containing sparse or cloud-placeholder
  files, and small files now show as one block (e.g. `4.0 KB`) since that
  is the space they cost.

### Changed

- **`gaz tree` is now `gaz list`, and lists exactly one level.** The old
  command produced a nested, multi-level listing; each subdirectory row
  now carries the file count and byte total for its *entire* subtree, so
  one level answers "what's here and what's big" without the nesting. To
  go deeper, run `gaz list` on the row you care about.
- **`--recursive` removed** — subtree totals are now the only behavior,
  leaving the flag nothing to mean.
- **`gaz list` shows names, not full paths, by default.** Use
  `-P`/`--full-paths` for resolved absolute paths (a symlink renders as
  `link -> target` so it stays distinct from the directory it points at).

### Added

- **`gaz list --sort name|size|files|modified|created`** (default `name`)
  with `--reverse`. Directories always sort before files.
- **`gaz list --fields created|dirs|path`** to add optional columns; a
  `modified` date column is now shown by default.
- **`*` marks a directory whose subtree wasn't fully scanned** in `gaz
  list`, so partial counts are never presented as totals.

## 0.1.2

### Changed

- **`--max-entries` is now opt-in, defaulting to unlimited (`0`).**
  Previously all three budgets (`--max-seconds`, `--max-entries`,
  `--max-rows`) applied simultaneously, so a scan on fast local storage
  could stop early on entry count alone even with plenty of time left.
  Now only `--max-seconds` (default `30`) is on by default;
  `--max-entries` defaults to `0` (unlimited) and must be passed
  explicitly to activate. `--max-rows` (default `50`) still applies by
  default, since it protects the terminal/context window rather than
  bounding the walk itself. `0` now means "unlimited" for all three
  flags — **this is a behavior change**: anyone relying on the old
  1,000,000-entry default should pass `--max-entries 1000000` (or any
  value) explicitly to restore the old ceiling.

### Added

- **`--exclude PATTERN`** (repeatable, on all six commands): prunes
  directories matching a glob against their basename *before* descent —
  an excluded directory is never scanned, never appears in results, and
  never counts against `--max-entries`, freeing budget for directories
  that matter instead of just filtering noise out of the output.
- **`gaz dup --skip-vendored`**: excludes common package-manager/dependency
  directories (`node_modules`, `site-packages`, `.venv`, `vendor`, etc.)
  by default-off flag, since duplicates inside them are a byproduct of
  how packages ship, not something reclaimable without breaking the
  installed environment. Composes with `--exclude`.
- **`--json`** (all six commands): a bounded structured-output
  alternative to the text table — same `--max-rows` cap, same
  completeness fields (`complete`, `stop_reason`, counts) as the text
  status line, for piping into `jq`/`xargs`/another agent without
  parsing aligned text or a natural-language sentence.
- **`gaz tree --recursive`**: rolls up each row's totals to its full
  subtree (like `du -d1`) instead of direct children only. Pure
  aggregation over data the walk already collected — no extra
  filesystem cost.
- **`gaz stale`** now flags ages within a week of the Unix epoch with
  `(?)`, since those are almost always a timestamp reset by some other
  tool (a cache, archive, or sync tool), not a genuinely decades-old
  file.
- **`gaz find --pattern`** now errors with a clear pointer to the
  correct positional form (`gaz find PATTERN [PATH]`) instead of a
  generic "no such option" — `find` intentionally takes `PATTERN`
  positionally, unlike `--pattern` on every other command.
- **`skills/gaz-usage/SKILL.md`**: usage guidance covering practices
  that aren't obvious from `--help` alone (default budgets, `--exclude`,
  sampling with `--shuffle`, reading the status line).

### Fixed

- `report.status_line` no longer suggests raising an already-unlimited
  budget (e.g. a nonsensical `--max-entries 0` re-run suggestion), and
  no longer misattributes an entries-limit stop as a time-limit stop due
  to a substring collision (`"entries limit"` contains `"s limit"`).

## 0.1.1

- Fixed `gaz --version` resolving the wrong package name after the PyPI
  distribution rename (`gazetteer` → `gaz`).
- Fixed the two P0 bugs from a real-world review: `report.status_line`
  suggesting the wrong re-run flag, and `gaz empty` false-positiving
  unvisited directories as empty.
- Made the walker breadth-first by default (`--depth-first` opts back
  into the old order); added `--shuffle`/`--seed` for representative
  sampling of a truncated walk.
- Added `gaz preview` and `gaz convert` for single-file inspection
  (JSON/YAML/TOML/XML/CSV pretty-printing; DOCX/PPTX/XLSX/PDF via
  `pandoc`/`pdftotext`/optional Python libraries).
- Renamed the PyPI distribution to `gaz` (`gazetteer` is blocked by
  PyPI's name policy); the `gazetteer` Python package and `gaz` command
  are unaffected.

## 0.1.0

- Initial release: bounded walker (`walk.py`) plus `gaz ext`, `gaz tree`,
  `gaz find`, `gaz dup`, `gaz stale`, `gaz empty`.
- `--ext`/`--pattern`/`--size` filters, human-readable size formatting,
  a "Total (at least, ...)" qualifier for truncated results.
