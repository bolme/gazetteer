# How `gaz sample` estimates size

**Authors:** David Bolme, Claude 5, Chat GPT 5.6

`gaz sample` exists for one situation: a directory has so many files that
even `gaz list`'s bounded walk can't finish in a reasonable time. Instead
of walking, it *samples* — reading a bounded number of directories and
extrapolating a total. This is a genuinely different kind of answer than
every other `gaz` command gives, so it's worth understanding what you're
looking at.

## For users: what the numbers mean

Every row is one of two things:

- **Exact.** The whole subtree finished scanning within the time budget.
  The size/file/dir counts are real totals — identical to what `gaz list`
  would eventually report. No caveats.
- **Partial**, marked with `*` (or `-` if a permission error was also
  hit — see below). You get two numbers instead of one:
  - a **lower bound**: every byte and file actually counted so far. This
    is always true — never inflated, never a guess.
  - an **estimate** (shown as `~N`): a projection of the rest, based on
    what similar-looking parts of the tree contained. This can be
    **meaningfully wrong**, sometimes by a large margin, especially at
    small scan budgets on an irregular directory. Treat it as "how big
    this problem roughly is," not as a number to build a report on.

**The practical rule of thumb: trust the lower bound, treat the estimate
as a rough size-of-the-problem signal.** If you need a real number,
re-run with a larger `--max-seconds` — the lower bound only ever grows
tighter, and given enough time every row converges to exact.

The `ext`, `ext types`, `activity`, and `owner` columns are always exact
tallies of files actually scanned — never extrapolated, even on a
partial row. Guessing at an unscanned directory's likely file types,
recency, or ownership has no principled basis the way guessing at its
total size does (subdirectory *count* predicts aggregate size in a way
nothing predicts an unscanned directory's contents).

A `denied` column appears only if `gaz` hit a permission error somewhere
in the tree; a row with any denials is marked `-` instead of `*`, since
"couldn't read part of this" is a more useful thing to know than "ran
out of time."

## Why estimates can be wrong: the short version

The estimator's rule for a partially-scanned directory `D` is:

```
estimate(D) = (D's own files, exact)
            + (D's subdirectory count, exact)
              × (average size of whichever of D's subdirectories
                 have been scanned so far)
```

The subdirectory *count* is always known exactly (one directory listing
reveals it completely). The problem is the *average*: directories that
happen to scan quickly (small, few files) get counted before directories
that take longer to explore — and on a real filesystem, "scans quickly"
and "is small" are the same thing. So the average is systematically
skewed toward whichever subdirectories finished first, which is a biased
sample of what's actually down there. This bias is not one-directional
and not simply "improves with more scanning" — in testing, a two-child
tree (one tiny, one huge) swung to +45% too high at a middling scan
budget before decaying back toward correct.

Two things keep this from being worse in practice:

1. Each directory's contribution to its parent's average is **weighted
   by how much of it has actually been explored** — a barely-scanned
   subdirectory counts for less than a mostly-resolved one, rather than
   both counting equally.
2. **The estimate is never allowed to fall below the lower bound.** If
   the weighted average alone would suggest a total smaller than what's
   already been counted for certain, the higher (known-true) number wins.

Both of these are implemented, not just designed — see `frontier.py`'s
`_estimate` if you want the code. Once every directory finishes, the
estimate and the lower bound are the same number by construction.

## Why this method over "just sample files at random"?

A tempting alternative is Knuth's tree-size estimator: take random
root-to-leaf walks, weight each by how unlikely that exact path was, and
average — mathematically unbiased at *any* sample size, with a real
confidence interval. `src/gazetteer/estimate.py` implements and validates
this; it's real, tested, and not what `gaz sample` uses.

The reason: that method never remembers anything between samples, so two
random walks that both pass through the root — which is every walk —
each pay to re-list it. Measured redundancy in simulation ranged from
6.6x to over 100x depending on tree shape, meaning most of the I/O
budget goes to re-reading directories already seen. `gaz sample`'s
frontier method scans each directory **at most once, ever**, which wins
back that redundancy at the cost of the bias described above. At a
matched I/O budget, the frontier method measured roughly **19x lower
error** than random sampling in one tested case — the tradeoff favors
memoization heavily enough that the bias is worth living with, provided
it's reported honestly (which is why the lower bound always ships
alongside the estimate, never a bare number).

## For maintainers and future contributors

### The algorithm

Maintain a **frontier**: directories that have been discovered (seen as
a child in some scanned directory's listing) but not yet read themselves.
Repeatedly pop one, `scandir` it, then keep descending into a freshly
discovered child, then its child, and so on until hitting a directory
with no subdirectories — then return to the frontier for a new starting
point. Every directory visited this way, whether as a starting pick or a
step deeper in the same descent, gets scanned exactly once for the life
of the run. `own_bytes`/`own_files` for a directory are exact the moment
it's scanned; everything else follows the recursive formula above.

This is resumable: `FrontierSampler.run()` can be called again on the
same instance to extend a scan with more budget, picking up the frontier
where it was left rather than restarting. That's what lets `gaz sample`
give every subdirectory a small first-pass budget, then round-robin
whatever's left across the ones still incomplete.

### A correctness trap worth knowing about

The natural way to implement the frontier ("is this directory already
queued or scanned?") is to check `node in some_list`. If directories are
represented as plain value objects, two *different*, unrelated empty
directories that happen to have identical fields (extremely common —
think two unrelated folders both named `d0` with nothing in them) will
compare equal under `==`, and a naive `list.remove(node)` can silently
remove the *wrong* one. This dropped real directories from a test tree
and produced a small but genuine bias even at "full" coverage, where the
answer should have been exact by construction. **Fix:** key all
frontier/memo bookkeeping by identity — `(st_dev, st_ino)` on a real
filesystem (the same key `walk.py` already uses for its symlink-loop
guard), never by value equality.

### Known gaps, if extending this

- **No confidence interval.** The estimate has no rigorous error bar the
  way the unshipped random-descent estimator does — partial estimates
  are correlated with each other (they share memoized state) and biased,
  so the same statistical machinery doesn't directly apply. Reporting a
  bare lower-bound/estimate pair, as today, is the honest fallback until
  this is solved.
- **No directory-listing cache beyond the per-run memo.** Each
  `FrontierSampler` already never re-scans a directory *within one run*,
  but nothing is cached *across* separate sampler instances (e.g., two
  sibling subdirectories that happen to share content via a symlink).
  Untested whether this would matter in practice.
- **Frontier growth is unbounded.** A directory with an extreme fan-out
  can add far more entries to the frontier than get drained per scan.
  Fine at realistic scales; a pathological case (a single directory with
  millions of children) could grow memory faster than expected.
- **Cost is unpredictable per subdirectory.** Whether a subtree is cheap
  or expensive to estimate depends on its *shape* (how uneven its
  branching factor is), not its size — there's no cheap way to know this
  in advance, only by scanning. A future improvement worth considering:
  prioritizing the frontier by estimated impact on the final answer
  (deep under a high-branching ancestor matters more than shallow-and-
  narrow) rather than picking uniformly at random, which the current
  implementation does.
- **The unshipped random-descent estimator (`estimate.py`) remains a
  candidate for a hybrid**: use it as a fallback to unbiasedly estimate
  whatever the frontier method hasn't resolved yet, instead of
  extrapolating from an average. Not implemented or tested.

### Where the evidence lives

Everything stated above as measured (the 19x efficiency comparison, the
+45% bias figure, the redundancy factors, the identity-bug reproduction)
came from ad hoc simulation scripts during development, not committed
separately — the durable, re-runnable evidence is the test suite:
`tests/test_frontier.py` for the shipped algorithm (correctness against
real filesystem trees, the lower-bound-never-decreases invariant, the
identity-vs-equality regression) and `tests/test_estimate.py` +
`tests/mocktree.py` for the unshipped random-descent alternative
(unbiasedness, confidence-interval coverage, sample-size scaling). Rerun
either suite directly rather than trusting this document's numbers to
stay current.
