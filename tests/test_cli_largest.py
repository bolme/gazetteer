import json

from click.testing import CliRunner

from gazetteer.cli import main


def _tree_with_sizes(tmp_path):
    """A tree whose biggest files are nested, not at the top level."""
    (tmp_path / "sub" / "deep").mkdir(parents=True)
    (tmp_path / "small.txt").write_text("x" * 10)
    (tmp_path / "sub" / "medium.bin").write_bytes(b"x" * 200_000)
    (tmp_path / "sub" / "deep" / "biggest.bin").write_bytes(b"x" * 900_000)
    return tmp_path


def _paths(output):
    return [
        line.split()[-1]
        for line in output.splitlines()
        if line.startswith(("1", "2", "3", "4", "5", "6", "7", "8", "9"))
        and "/" in line
    ]


def test_largest_ranks_files_across_the_whole_subtree(tmp_path):
    _tree_with_sizes(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path)])

    assert result.exit_code == 0
    paths = _paths(result.output)
    # The biggest file is three levels down — the point of the command.
    assert paths[0].endswith("biggest.bin")
    assert paths[1].endswith("medium.bin")


def test_largest_lists_files_not_directories(tmp_path):
    _tree_with_sizes(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path)])

    assert result.exit_code == 0
    # Directories have sizes too, but "largest file" is the question.
    assert "sub  " not in result.output
    for path in _paths(result.output):
        assert path.endswith((".txt", ".bin"))


def test_largest_max_rows_is_the_n(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.bin").write_bytes(b"x" * (1000 * (i + 1)))

    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path), "--max-rows", "3"])

    assert result.exit_code == 0
    assert len(_paths(result.output)) == 3
    assert "Showing 3 of 10 files" in result.output


def test_largest_totals_cover_every_candidate_not_just_shown_rows(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.bin").write_bytes(b"x" * 1000)

    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path), "--max-rows", "2"])

    assert result.exit_code == 0
    assert "Total: 10 files" in result.output


def test_largest_min_size_filters(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * 500_000)
    (tmp_path / "small.txt").write_text("tiny")

    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path), "--min-size", "100k"])

    assert result.exit_code == 0
    assert "big.bin" in result.output
    assert "small.txt" not in result.output


def test_largest_min_size_rejects_garbage(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path), "--min-size", "bogus"])

    assert result.exit_code != 0
    assert "--min-size" in result.output


def test_largest_apparent_flag_changes_the_ranking(tmp_path):
    # A sparse file: huge apparent length, almost no allocated blocks.
    sparse = tmp_path / "sparse.img"
    with open(sparse, "wb") as f:
        f.seek(50_000_000)
        f.write(b"x")
    (tmp_path / "real.bin").write_bytes(b"x" * 300_000)

    runner = CliRunner()
    by_disk = runner.invoke(main, ["largest", str(tmp_path)])
    by_apparent = runner.invoke(main, ["largest", str(tmp_path), "--apparent"])

    assert by_disk.exit_code == 0 and by_apparent.exit_code == 0
    # By disk usage the dense file wins; by apparent length the sparse one does.
    assert _paths(by_disk.output)[0].endswith("real.bin")
    assert _paths(by_apparent.output)[0].endswith("sparse.img")


def test_largest_json_output(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 5000)

    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["complete"] is True
    assert data["total"]["files"] == 1
    assert data["total"]["ranked_by"] == "size"
    row = data["rows"][0]
    assert row["path"].endswith("a.bin")
    assert row["apparent_size"] == 5000
    assert row["size"] >= 5000  # allocated blocks
    assert "mtime" in row


def test_largest_json_records_apparent_ranking(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 5000)

    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path), "--json", "--apparent"])

    data = json.loads(result.output)
    assert data["total"]["ranked_by"] == "apparent_size"


def test_largest_respects_ext_filter(tmp_path):
    (tmp_path / "keep.py").write_bytes(b"x" * 5000)
    (tmp_path / "skip.jpg").write_bytes(b"x" * 90_000)

    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path), "--ext", ".py"])

    assert result.exit_code == 0
    assert "keep.py" in result.output
    assert "skip.jpg" not in result.output


def test_largest_respects_exclude(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "big.js").write_bytes(b"x" * 90_000)
    (tmp_path / "src.py").write_bytes(b"x" * 5000)

    runner = CliRunner()
    result = runner.invoke(
        main, ["largest", str(tmp_path), "--exclude", "node_modules"]
    )

    assert result.exit_code == 0
    assert "big.js" not in result.output
    assert "src.py" in result.output


def test_largest_empty_tree(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path)])

    assert result.exit_code == 0
    assert "Total: 0 files" in result.output


def test_largest_status_line_present(tmp_path):
    (tmp_path / "f.bin").write_bytes(b"x" * 100)

    runner = CliRunner()
    result = runner.invoke(main, ["largest", str(tmp_path)])

    assert result.exit_code == 0
    assert "Complete." in result.output


def test_largest_total_is_qualified_when_walk_truncated(tmp_path):
    for i in range(20):
        (tmp_path / f"f{i}.bin").write_bytes(b"x" * 1000)

    runner = CliRunner()
    result = runner.invoke(
        main, ["largest", str(tmp_path), "--max-entries", "5"]
    )

    assert result.exit_code == 0
    assert "Total (at least, walk stopped early):" in result.output
