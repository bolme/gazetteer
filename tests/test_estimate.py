"""Simulation-based validation of gazetteer.estimate's random-descent
sampling estimator (Knuth's tree-size algorithm, generalized to sum leaf
bytes as well as count leaves — see estimate.py's module docstring for the
math). Every mock tree here is generated in memory (tests/mocktree.py) with
a known ground truth, so these tests check the estimator against an exact
answer rather than another estimate.

Three questions this suite answers, in order:
1. Is the point estimate unbiased (test_*_unbiased)?
2. Is the reported confidence interval honest — does a 95% CI actually
   contain the true value ~95% of the time (test_*_ci_coverage)?
3. Does error shrink with more probes the way the 1/sqrt(n) theory
   predicts, and how many probes does a real tree size need for +/-10%,
   +/-5% (test_error_shrinks_with_probes, test_probes_needed_for_*)?
"""

from __future__ import annotations

import random
import statistics

from gazetteer import estimate
from tests import mocktree


def _adapter():
    return mocktree.NodeAdapter()


# ---------------------------------------------------------------------
# 1. Unbiasedness: the mean of many independent point estimates should
#    converge to the true total, for both size and file count, and on
#    both a regular and an irregular tree.
# ---------------------------------------------------------------------


def test_size_estimate_unbiased_on_uniform_tree():
    tree = mocktree.uniform_tree(depth=3, branching=4, files_per_dir=5, file_size=1000)
    adapter = _adapter()

    points = []
    for trial in range(300):
        est = estimate.Estimator(adapter, seed=trial)
        points.append(est.run(tree.root, 500).size.point)

    mean_estimate = statistics.mean(points)
    # Mean of 300 independent 500-probe estimates should land within 5% of
    # truth — a much tighter bound than any single estimate's own CI,
    # since averaging trials shrinks error by sqrt(300) again.
    assert abs(mean_estimate - tree.total_size) / tree.total_size < 0.05


def test_count_estimate_unbiased_on_uniform_tree():
    tree = mocktree.uniform_tree(depth=3, branching=4, files_per_dir=5, file_size=1000)
    adapter = _adapter()

    points = []
    for trial in range(300):
        est = estimate.Estimator(adapter, seed=trial)
        points.append(est.run(tree.root, 500).count.point)

    mean_estimate = statistics.mean(points)
    assert abs(mean_estimate - tree.n_files) / tree.n_files < 0.05


def test_size_estimate_unbiased_on_irregular_tree():
    rng = random.Random(123)
    tree = mocktree.random_branching_tree(
        depth=4,
        branching_range=(1, 5),
        files_range=(0, 8),
        size_range=(100, 5000),
        rng=rng,
        depth_decay=0.8,
    )
    adapter = _adapter()

    points = []
    for trial in range(300):
        est = estimate.Estimator(adapter, seed=trial)
        points.append(est.run(tree.root, 800).size.point)

    mean_estimate = statistics.mean(points)
    assert abs(mean_estimate - tree.total_size) / tree.total_size < 0.10


def test_size_estimate_unbiased_on_skewed_tree():
    """The hard case: most bytes live in a small fraction of files. High
    per-trial variance is expected and fine (see test_error_shrinks_with_
    probes) — what matters here is that averaging many trials still
    converges to truth, i.e. the estimator isn't systematically biased by
    the skew, just noisier."""
    rng = random.Random(99)
    tree = mocktree.skewed_tree(
        depth=4,
        branching_range=(2, 5),
        files_range=(3, 8),
        rng=rng,
        hot_branch_probability=0.05,
    )
    adapter = _adapter()

    points = []
    for trial in range(600):
        est = estimate.Estimator(adapter, seed=trial)
        points.append(est.run(tree.root, 1500).size.point)

    mean_estimate = statistics.mean(points)
    assert abs(mean_estimate - tree.total_size) / tree.total_size < 0.20


# ---------------------------------------------------------------------
# 2. CI coverage: a 95% confidence interval should contain the true value
#    in ~95% of independent trials -- not 100% (too conservative to be
#    useful) and not e.g. 60% (dishonestly narrow).
# ---------------------------------------------------------------------


def test_ci_coverage_close_to_95_percent_uniform_tree():
    tree = mocktree.uniform_tree(depth=3, branching=4, files_per_dir=5, file_size=1000)
    adapter = _adapter()

    covered = 0
    trials = 400
    for trial in range(trials):
        est = estimate.Estimator(adapter, seed=10_000 + trial)
        result = est.run(tree.root, 500)
        if result.size.ci_low <= tree.total_size <= result.size.ci_high:
            covered += 1

    coverage = covered / trials
    # Binomial noise on 400 trials at true p=0.95 has stderr ~1.1%; allow
    # a generous +/-6% band so this isn't a flaky test while still
    # catching a genuinely broken interval (e.g. off by a factor of z).
    assert 0.89 <= coverage <= 1.0


def test_ci_coverage_close_to_95_percent_irregular_tree():
    rng = random.Random(55)
    tree = mocktree.random_branching_tree(
        depth=4,
        branching_range=(1, 5),
        files_range=(0, 8),
        size_range=(100, 5000),
        rng=rng,
    )
    adapter = _adapter()

    covered = 0
    trials = 400
    for trial in range(trials):
        est = estimate.Estimator(adapter, seed=20_000 + trial)
        result = est.run(tree.root, 800)
        if result.size.ci_low <= tree.total_size <= result.size.ci_high:
            covered += 1

    coverage = covered / trials
    assert 0.85 <= coverage <= 1.0


# ---------------------------------------------------------------------
# 3. Error shrinks with more probes, following the 1/sqrt(n) law, and
#    probes_needed_for_relative_error hits its target in practice.
# ---------------------------------------------------------------------


def test_error_shrinks_with_probes():
    tree = mocktree.uniform_tree(depth=3, branching=4, files_per_dir=5, file_size=1000)
    adapter = _adapter()

    errors = {}
    for n in (100, 400, 1600, 6400):
        est = estimate.Estimator(adapter, seed=1)
        errors[n] = est.run(tree.root, n).size.relative_error

    # Quadrupling n should roughly halve relative_error (1/sqrt(4) = 0.5).
    # Allow a wide band since this is a single run, not an average.
    for lo, hi in ((100, 400), (400, 1600), (1600, 6400)):
        ratio = errors[hi] / errors[lo]
        assert 0.25 <= ratio <= 0.85, (lo, hi, errors[lo], errors[hi])


def test_probes_needed_hits_target_relative_error():
    tree = mocktree.uniform_tree(depth=3, branching=4, files_per_dir=5, file_size=1000)
    adapter = _adapter()

    for target in (0.20, 0.10):
        n, result = estimate.probes_needed_for_relative_error(
            adapter, tree.root, target, seed=7
        )
        # Iterative doubling stops the step *after* the target is first
        # met, so achieved error should be at or just under target, never
        # far over it.
        assert result.relative_error <= target * 1.1
        # And the point estimate should be in the right ballpark.
        assert abs(result.point - tree.total_size) / tree.total_size < target * 3


def test_probes_needed_scales_with_tighter_target():
    tree = mocktree.uniform_tree(depth=3, branching=4, files_per_dir=5, file_size=1000)
    adapter = _adapter()

    n_loose, _ = estimate.probes_needed_for_relative_error(
        adapter, tree.root, 0.20, seed=3
    )
    n_tight, _ = estimate.probes_needed_for_relative_error(
        adapter, tree.root, 0.05, seed=3
    )
    # ~16x more probes needed for a 4x tighter target ((20/5)**2 == 16).
    assert n_tight > n_loose * 5


def test_probes_needed_does_not_undershoot_on_skewed_tree():
    """Regression case for the bug a single fixed-size pilot has: on a
    heavy-tailed weight distribution, a small pilot's own variance
    estimate is itself unreliable, so extrapolating from it in one jump
    can badly undershoot the true requirement (this test is the empirical
    confirmation — see docs/sample-estimation.md for the broader picture).
    Iterative doubling re-measures
    from an ever-larger cumulative sample, so it should either hit the
    target or, if capped by max_probes, get meaningfully closer than the
    pilot's naive one-shot extrapolation would have."""
    rng = random.Random(2)
    tree = mocktree.skewed_tree(
        depth=5,
        branching_range=(2, 5),
        files_range=(3, 10),
        rng=rng,
        hot_branch_probability=0.05,
    )
    adapter = _adapter()

    n, result = estimate.probes_needed_for_relative_error(
        adapter, tree.root, 0.20, seed=2, max_probes=500_000
    )
    # A naive single 200-probe pilot extrapolated to ~2,500 probes here and
    # landed at ~97% relative error, not 20%. Doubling should either meet
    # the 20% target outright or come reasonably close within the budget.
    assert result.relative_error <= 0.35


def test_probes_needed_reports_honestly_when_capped():
    """If max_probes is reached before the target, the function must not
    claim success — it returns max_probes with whatever relative_error was
    actually achieved, so a caller can see the target wasn't met."""
    rng = random.Random(2)
    tree = mocktree.skewed_tree(
        depth=5,
        branching_range=(2, 5),
        files_range=(3, 10),
        rng=rng,
        hot_branch_probability=0.05,
    )
    adapter = _adapter()

    n, result = estimate.probes_needed_for_relative_error(
        adapter, tree.root, 0.01, seed=2, max_probes=2000
    )
    assert n == 2000
    assert result.relative_error > 0.01


# ---------------------------------------------------------------------
# Basic sanity / edge cases
# ---------------------------------------------------------------------


def test_empty_tree_estimates_zero():
    root = mocktree.Node(name="root", is_dir=True, children=[])
    adapter = _adapter()
    est = estimate.Estimator(adapter, seed=1)
    result = est.run(root, 50)
    assert result.size.point == 0.0
    assert result.count.point == 0.0


def test_single_file_root_is_exact():
    """A root that's a single file (edge case: no directories at all) —
    every probe should reach it with weight 1, and the estimate should be
    exact with zero variance."""
    root = mocktree.Node(name="f", is_dir=False, size=4096)
    adapter = _adapter()
    est = estimate.Estimator(adapter, seed=1)
    result = est.run(root, 20)
    assert result.size.point == 4096.0
    assert result.size.stderr == 0.0


def test_max_depth_truncates_descent_without_crashing():
    tree = mocktree.uniform_tree(depth=6, branching=3, files_per_dir=2, file_size=500)
    adapter = _adapter()
    est = estimate.Estimator(adapter, seed=1)
    result = est.run(tree.root, 500, max_depth=2)
    # Capped descent can't reach files below depth 2, so the estimate is a
    # (biased-low, by design) partial view -- this test only checks it
    # runs and produces a finite, non-negative number, not accuracy.
    assert result.size.point >= 0
    assert result.size.point < tree.total_size


def test_more_probes_never_hurts_relative_error_on_average():
    """Not a strict monotonicity check (a single run can get lucky/unlucky)
    -- averaged over many trials, more probes should give a tighter typical
    interval."""
    tree = mocktree.uniform_tree(depth=3, branching=4, files_per_dir=5, file_size=1000)
    adapter = _adapter()

    def avg_relative_error(n_probes, trials=40):
        errs = []
        for trial in range(trials):
            est = estimate.Estimator(adapter, seed=trial)
            errs.append(est.run(tree.root, n_probes).size.relative_error)
        return statistics.mean(errs)

    assert avg_relative_error(2000) < avg_relative_error(200)
