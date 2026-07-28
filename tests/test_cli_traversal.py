from click.testing import CliRunner

from gazetteer.cli import main


def _make_wide_shallow_tree(tmp_path, n_top_dirs=6):
    for i in range(n_top_dirs):
        d = tmp_path / f"top{i}"
        (d / "nested").mkdir(parents=True)
        (d / "nested" / "deep.txt").write_text("x")


ALL_WALK_COMMANDS = [
    ["ext"],
    ["list"],
    ["find", "*"],
    ["stale"],
    ["empty"],
    ["dup"],
    ["largest"],
]


def test_all_walk_commands_accept_depth_first_flag(tmp_path):
    (tmp_path / "f.txt").write_text("x")
    runner = CliRunner()
    for cmd in ALL_WALK_COMMANDS:
        result = runner.invoke(main, [*cmd, str(tmp_path), "--depth-first"])
        assert result.exit_code == 0, f"{cmd[0]} --depth-first failed: {result.output}"


def test_all_walk_commands_accept_shuffle_and_seed(tmp_path):
    (tmp_path / "f.txt").write_text("x")
    runner = CliRunner()
    for cmd in ALL_WALK_COMMANDS:
        result = runner.invoke(main, [*cmd, str(tmp_path), "--shuffle", "--seed", "1"])
        assert result.exit_code == 0, f"{cmd[0]} --shuffle --seed failed: {result.output}"


# Traversal order is asserted through `find` rather than `list`: find lists
# every match at any depth, so what the walk reached is directly visible in
# its rows. `list` lists one level only (its rows are always the root's
# direct children regardless of how deep the walk got), which makes it
# unable to distinguish BFS from DFS.
def test_default_is_breadth_first(tmp_path):
    _make_wide_shallow_tree(tmp_path, n_top_dirs=6)
    runner = CliRunner()
    result = runner.invoke(
        main, ["find", "*", str(tmp_path), "--max-entries", "7", "--max-rows", "20"]
    )

    assert result.exit_code == 0
    # BFS sees all six top-level dirs before descending to any deep.txt.
    assert "deep.txt" not in result.output
    assert "Stopped at the 7 entries limit" in result.output


def test_depth_first_flag_reaches_deeper(tmp_path):
    _make_wide_shallow_tree(tmp_path, n_top_dirs=6)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "find", "*", str(tmp_path),
            "--max-entries", "4", "--depth-first", "--max-rows", "20",
        ],
    )

    assert result.exit_code == 0
    # DFS dives into the first branch instead of covering the top level.
    assert "nested" in result.output


def test_shuffle_produces_different_order_across_seeds(tmp_path):
    for i in range(15):
        (tmp_path / f"f{i}.txt").write_text("x")

    runner = CliRunner()
    result_a = runner.invoke(
        main, ["find", "*.txt", str(tmp_path), "--shuffle", "--seed", "1"]
    )
    result_b = runner.invoke(
        main, ["find", "*.txt", str(tmp_path), "--shuffle", "--seed", "2"]
    )

    assert result_a.exit_code == 0
    assert result_b.exit_code == 0
    assert result_a.output != result_b.output


def test_shuffle_same_seed_is_reproducible(tmp_path):
    for i in range(15):
        (tmp_path / f"f{i}.txt").write_text("x")

    runner = CliRunner()
    result_a = runner.invoke(
        main, ["find", "*.txt", str(tmp_path), "--shuffle", "--seed", "42"]
    )
    result_b = runner.invoke(
        main, ["find", "*.txt", str(tmp_path), "--shuffle", "--seed", "42"]
    )

    assert result_a.output == result_b.output


def test_depth_first_and_shuffle_compose_without_error(tmp_path):
    _make_wide_shallow_tree(tmp_path, n_top_dirs=4)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["list", str(tmp_path), "--depth-first", "--shuffle", "--seed", "1"],
    )

    assert result.exit_code == 0
