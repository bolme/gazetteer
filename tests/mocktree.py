"""In-memory synthetic directory trees for sampling-estimator experiments.

Building a 500K-file tree on real disk per test is slow and I/O-bound for
no benefit here — the estimator under test only ever looks at branching
factors and leaf sizes, never file contents or real stat() calls. This
module generates a tree of `Node` objects with the same shape (directories
with children, files with a size) and exposes the two primitives the
estimator needs: listing a node's children, and reading a leaf's size.
Every generator returns the ground-truth totals alongside the tree so
simulations can score estimates against a known-correct answer.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class Node:
    name: str
    is_dir: bool
    size: int = 0  # meaningful only for files
    children: list["Node"] = field(default_factory=list)


@dataclass
class TreeStats:
    root: Node
    n_files: int
    n_dirs: int
    total_size: int


def children_of(node: Node) -> list[Node]:
    return node.children


def is_leaf(node: Node) -> bool:
    return not node.is_dir


class NodeAdapter:
    """estimate.TreeAdapter for mocktree.Node — lets the estimator walk a
    synthetic in-memory tree exactly as it would walk a real filesystem."""

    def children(self, node: Node) -> list[Node]:
        return node.children

    def is_leaf(self, node: Node) -> bool:
        return not node.is_dir

    def value(self, node: Node) -> float:
        return float(node.size)


def _totals(node: Node) -> tuple[int, int, int]:
    """(n_files, n_dirs, total_size) for the subtree rooted at node."""
    if not node.is_dir:
        return (1, 0, node.size)
    n_files = n_dirs = total_size = 0
    for child in node.children:
        f, d, s = _totals(child)
        n_files += f
        n_dirs += d
        total_size += s
    return (n_files, n_dirs + 1, total_size)


def finalize(root: Node) -> TreeStats:
    n_files, n_dirs, total_size = _totals(root)
    return TreeStats(root=root, n_files=n_files, n_dirs=n_dirs, total_size=total_size)


def uniform_tree(
    *,
    depth: int,
    branching: int,
    files_per_dir: int,
    file_size: int = 1024,
    rng: random.Random | None = None,
) -> TreeStats:
    """A perfectly regular tree: every directory has the same fan-out and
    the same number of same-size files. The simplest possible case — an
    estimator that's biased even here has no hope on a real tree."""
    rng = rng or random.Random(0)

    def build(level: int, name: str) -> Node:
        node = Node(name=name, is_dir=True)
        for i in range(files_per_dir):
            node.children.append(Node(name=f"f{i}", is_dir=False, size=file_size))
        if level < depth:
            for i in range(branching):
                node.children.append(build(level + 1, f"d{i}"))
        return node

    return finalize(build(0, "root"))


def random_branching_tree(
    *,
    depth: int,
    branching_range: tuple[int, int],
    files_range: tuple[int, int],
    size_range: tuple[int, int],
    rng: random.Random,
    depth_decay: float = 1.0,
) -> TreeStats:
    """An irregular tree: branching factor, file count, and file size are
    each drawn independently per directory. `depth_decay` < 1 shrinks the
    expected branching factor at deeper levels (e.g. 0.7 means each level
    has ~70% of the branching of its parent), modeling the common real
    shape where a tree fans out near the root and narrows toward leaves.
    """

    def build(level: int, name: str) -> Node:
        node = Node(name=name, is_dir=True)
        n_files = rng.randint(*files_range)
        for i in range(n_files):
            size = rng.randint(*size_range)
            node.children.append(Node(name=f"f{i}", is_dir=False, size=size))
        if level < depth:
            lo, hi = branching_range
            decay = depth_decay**level
            lo = max(0, round(lo * decay))
            hi = max(lo, round(hi * decay))
            n_children = rng.randint(lo, hi)
            for i in range(n_children):
                node.children.append(build(level + 1, f"d{i}"))
        return node

    return finalize(build(0, "root"))


def skewed_tree(
    *,
    depth: int,
    branching_range: tuple[int, int],
    files_range: tuple[int, int],
    rng: random.Random,
    hot_branch_probability: float = 0.05,
    hot_branch_size: int = 10_000_000,
    cold_size_range: tuple[int, int] = (100, 100_000),
) -> TreeStats:
    """Like random_branching_tree, but a small fraction of files are huge
    ("hot" files — a checkpoint, a video, a database dump) sitting among
    many small ones. This is the case that breaks naive uniform-leaf
    sampling: most of the tree's *bytes* live in a small fraction of its
    *files*, so a size estimator needs to handle high-variance leaf values,
    not just high-variance leaf counts.
    """

    def build(level: int, name: str) -> Node:
        node = Node(name=name, is_dir=True)
        n_files = rng.randint(*files_range)
        for i in range(n_files):
            if rng.random() < hot_branch_probability:
                size = rng.randint(hot_branch_size // 2, hot_branch_size)
            else:
                size = rng.randint(*cold_size_range)
            node.children.append(Node(name=f"f{i}", is_dir=False, size=size))
        if level < depth:
            n_children = rng.randint(*branching_range)
            for i in range(n_children):
                node.children.append(build(level + 1, f"d{i}"))
        return node

    return finalize(build(0, "root"))
