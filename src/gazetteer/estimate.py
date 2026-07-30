"""Sampling-based size estimation — a research spike, NOT what `gaz
sample` ships with. The shipped command uses frontier.py's different
(frontier-based, memoized) algorithm instead — see that module's
docstring. This one remains as a validated, alternative approach; nothing
in src/gazetteer imports it outside its own test suite.

The problem this explores: for a tree too large to walk within any
reasonable time budget, can `gaz` give a statistically honest estimate of
total size/file count, with an error bar, from a bounded number of
directory reads?

## The estimator

This uses Knuth's algorithm for estimating the size of a search tree
(1975, "Estimating the efficiency of backtrack programs"), generalized
from counting nodes to summing an arbitrary leaf value (bytes).

A single **probe** does a random descent from the root:

1. Start at the root with a running weight `w = 1`.
2. At each directory, list its children (one `os.scandir`, i.e. one unit
   of I/O). Let `c` be the number of children.
   - If `c == 0`, the probe contributes 0 and stops.
   - Otherwise pick one child uniformly at random, set `w *= c`, and
     descend into it.
3. When the descent reaches a file (not a directory), the probe's
   estimate is `w * size_of(file)`. When it reaches an empty directory,
   the probe's estimate is 0.

Averaging many independent probes' estimates gives an unbiased estimator
of the tree's total size. The intuition: a probe that reaches a leaf at
depth `d` via children-counts `c_1, c_2, ..., c_d` reaches it with
probability `1 / (c_1 * c_2 * ... * c_d)` — exactly `1 / w`. Weighting its
contribution by `w` is inverse-probability (Horvitz-Thompson) weighting,
so `E[w * value] = value` for that one leaf, and by linearity of
expectation, `E[mean of many probes] = sum of all leaf values` = the
tree's total size. The same probes, weighting each leaf's contribution by
`w * 1` instead of `w * size`, give an unbiased estimator of *file count*.
Both are computed from the same probes at no extra I/O cost — see
`Estimator.run`.

This only requires listing directories along the sampled path, never a
full walk — the I/O cost of one probe is proportional to the *depth* it
reaches, not the tree's size. That's what makes it viable on a tree too
large to walk.

## Why not uniform leaf sampling

The naive alternative — "sample N random files uniformly and multiply
their average size by the total file count" — needs the total file count
up front, which is exactly what's unknown on a tree too large to walk.
Random-descent estimation gets both totals from the same probes without
that prerequisite, at the cost of higher variance per probe (see
docs/sample-estimation.md for how this compares to what `gaz sample`
actually ships; the sample-size-vs-tree-shape scaling this module was
originally validated against lives in `tests/test_estimate.py`, not in
a separate written report).

## Variance and honesty

Random-descent estimates can have high variance, particularly on skewed
trees where a small fraction of files hold most of the bytes (see
`mocktree.skewed_tree`) or wide-then-narrow trees where an early
high-branching directory inflates `w` for every probe that passes through
it. This module reports a standard error and confidence interval computed
from the probes actually drawn (sample standard deviation of the N probe
estimates, not an assumed distribution) rather than a bare point estimate,
so a caller can see when the interval is too wide to be useful and either
draw more probes or fall back to a bounded walk.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

T = TypeVar("T")


class TreeAdapter(Protocol[T]):
    """The three operations a probe needs. Implemented once for the real
    filesystem (os.scandir) and once for tests/mocktree.Node, so the
    estimator itself never depends on which one it's talking to."""

    def children(self, node: T) -> list[T]: ...
    def is_leaf(self, node: T) -> bool: ...
    def value(self, node: T) -> float: ...


@dataclass
class Probe:
    """One random root-to-leaf descent."""

    weight: float  # product of children-counts along the path (1 / reach-probability)
    value: float  # leaf's value (0 for an empty directory reached as a "leaf")
    depth: int  # number of descent steps taken


@dataclass
class Estimate:
    point: float
    stderr: float
    ci_low: float
    ci_high: float
    n_probes: int
    # Half-width of the 95% CI, as a fraction of the point estimate.
    relative_error: float

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"Estimate(point={self.point:.3g}, 95% CI=[{self.ci_low:.3g}, "
            f"{self.ci_high:.3g}], relative_error={self.relative_error:.1%}, "
            f"n={self.n_probes})"
        )


def run_probe(
    adapter: TreeAdapter[T],
    root: T,
    rng: random.Random,
    *,
    max_depth: int | None = None,
) -> Probe:
    """One random descent from root, stopping at a file, an empty
    directory, or max_depth (whichever comes first). Both the byte-total
    and file-count estimators (Estimator.run) are computed from the same
    probes — see the module docstring for why one descent serves both."""
    node = root
    weight = 1.0
    depth = 0
    while not adapter.is_leaf(node):
        children = adapter.children(node)
        if not children:
            return Probe(weight=weight, value=0.0, depth=depth)
        if max_depth is not None and depth >= max_depth:
            return Probe(weight=weight, value=0.0, depth=depth)
        node = rng.choice(children)
        weight *= len(children)
        depth += 1
    return Probe(weight=weight, value=adapter.value(node), depth=depth)


def _summarize(weighted_values: list[float]) -> Estimate:
    n = len(weighted_values)
    point = sum(weighted_values) / n
    if n < 2:
        return Estimate(
            point=point,
            stderr=float("nan"),
            ci_low=float("nan"),
            ci_high=float("nan"),
            n_probes=n,
            relative_error=float("nan"),
        )
    mean = point
    var = sum((x - mean) ** 2 for x in weighted_values) / (n - 1)
    stderr = math.sqrt(var / n)
    # 95% CI via normal approximation (CLT over probe means) — valid once n
    # is large enough for the mean's sampling distribution to be
    # approximately normal despite individual probes being heavy-tailed.
    # tests/test_estimate.py checks this empirically (measured CI coverage
    # against a target of 95%) rather than asserting a specific n here.
    margin = 1.959963984540054 * stderr
    ci_low = point - margin
    ci_high = point + margin
    relative_error = (margin / point) if point > 0 else float("inf")
    return Estimate(
        point=point,
        stderr=stderr,
        ci_low=ci_low,
        ci_high=ci_high,
        n_probes=n,
        relative_error=relative_error,
    )


@dataclass
class DualEstimate:
    """Size and count estimates from one shared batch of probes."""

    size: Estimate
    count: Estimate
    probes: list[Probe] = field(default_factory=list)


class Estimator(Generic[T]):
    """Draws probes and summarizes them into byte-total and file-count
    estimates. Both estimates reuse the same probes (each descent already
    pays the I/O cost; reading off two weighted sums from it is free)."""

    def __init__(self, adapter: TreeAdapter[T], *, seed: int | None = None):
        self.adapter = adapter
        self.rng = random.Random(seed)

    def run(
        self, root: T, n_probes: int, *, max_depth: int | None = None
    ) -> DualEstimate:
        probes = [
            run_probe(self.adapter, root, self.rng, max_depth=max_depth)
            for _ in range(n_probes)
        ]
        # A probe that stops at an empty directory hit no file, so it
        # contributes 0 to both sums. Every other probe reached exactly one
        # file: `1 * weight` for the count (Horvitz-Thompson with value=1
        # instead of value=size), `value * weight` for bytes.
        size_weighted = [p.weight * p.value for p in probes]
        count_weighted = [p.weight if p.value > 0 else 0.0 for p in probes]
        return DualEstimate(
            size=_summarize(size_weighted),
            count=_summarize(count_weighted),
            probes=probes,
        )


def probes_needed_for_relative_error(
    adapter: TreeAdapter[T],
    root: T,
    target_relative_error: float,
    *,
    seed: int | None = None,
    pilot_probes: int = 200,
    max_probes: int = 500_000,
    max_depth: int | None = None,
) -> tuple[int, Estimate]:
    """Estimate how many probes are needed to reach a target relative
    error on the 95% CI.

    Uses iterative doubling rather than a single pilot-then-jump: draw
    `pilot_probes`, check the achieved relative_error, and if it's not at
    target yet, double the batch size and draw that many *more* probes,
    folding them into the same running sample, repeating until the target
    is met or max_probes is reached.

    A single small pilot's own variance estimate is itself unreliable on a
    heavy-tailed weight distribution (the common case here — a handful of
    high-branching-factor or high-size paths dominate the variance, and a
    small pilot may not have sampled any of them yet), so extrapolating
    from it in one jump can badly undershoot -- confirmed empirically on
    a skewed test tree, where a single 200-probe pilot's extrapolation
    missed the true requirement by 3-7x (see
    test_probes_needed_does_not_undershoot_on_skewed_tree in
    tests/test_estimate.py, a regression test for this exact failure
    mode). Doubling re-measures variance from an ever-larger cumulative
    sample at each step, so each extrapolation is only ever asked to
    predict one doubling ahead rather than the whole remaining distance.
    """
    rng = random.Random(seed)
    weighted: list[float] = []
    n = 0
    batch = pilot_probes
    while True:
        batch = min(batch, max_probes - n)
        probes = [
            run_probe(adapter, root, rng, max_depth=max_depth) for _ in range(batch)
        ]
        weighted.extend(p.weight * p.value for p in probes)
        n += batch
        est = _summarize(weighted)
        target_met = est.relative_error == est.relative_error and (
            est.relative_error <= target_relative_error
        )
        if target_met or n >= max_probes:
            return n, est
        batch *= 2
