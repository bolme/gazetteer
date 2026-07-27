import json

from click.testing import CliRunner

from gazetteer.cli import main


def _parse(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_ext_json_output(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.jpg").write_text("xx")

    runner = CliRunner()
    result = runner.invoke(main, ["ext", str(tmp_path), "--json"])
    data = _parse(result)

    assert data["complete"] is True
    assert data["total"]["files"] == 2
    exts = {row["ext"] for row in data["rows"]}
    assert exts == {".txt", ".jpg"}


def test_tree_json_output_recursive(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["tree", str(tmp_path), "--json", "--recursive"])
    data = _parse(result)

    assert data["total"]["recursive"] is True
    dirs = {row["dir"]: row["n_files"] for row in data["rows"]}
    assert dirs[str(tmp_path)] == 1
    assert dirs[str(tmp_path / "a")] == 1


def test_find_json_output(tmp_path):
    (tmp_path / "a.jpg").write_text("x")
    (tmp_path / "b.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["find", "*.jpg", str(tmp_path), "--json"])
    data = _parse(result)

    assert data["total"]["matches"] == 1
    assert data["rows"][0]["path"].endswith("a.jpg")
    assert data["rows"][0]["type"] == "file"


def test_stale_json_output(tmp_path):
    (tmp_path / "old.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(
        main, ["stale", str(tmp_path), "--older-than", "0s", "--json"]
    )
    data = _parse(result)

    assert data["total"]["files"] == 1
    row = data["rows"][0]
    assert row["path"].endswith("old.txt")
    assert "age_seconds" in row
    assert row["suspicious_mtime"] is False


def test_stale_json_flags_suspicious_mtime(tmp_path):
    import os

    epoch_file = tmp_path / "epoch.txt"
    epoch_file.write_text("x")
    os.utime(epoch_file, (0, 0))

    runner = CliRunner()
    result = runner.invoke(
        main, ["stale", str(tmp_path), "--older-than", "0s", "--json"]
    )
    data = _parse(result)

    assert data["total"]["n_suspicious_mtime"] == 1
    assert data["rows"][0]["suspicious_mtime"] is True


def test_empty_json_output(tmp_path):
    (tmp_path / "emptydir").mkdir()
    (tmp_path / "nonempty").mkdir()
    (tmp_path / "nonempty" / "f.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["empty", str(tmp_path), "--json"])
    data = _parse(result)

    assert data["total"]["empty_dirs"] == 1
    assert data["rows"][0]["dir"].endswith("emptydir")


def test_dup_json_output(tmp_path):
    (tmp_path / "a.txt").write_text("same")
    (tmp_path / "b.txt").write_text("same")

    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path), "--json"])
    data = _parse(result)

    assert data["total"]["duplicate_sets"] == 1
    assert data["total"]["hash_complete"] is True
    row = data["rows"][0]
    assert row["copies"] == 2
    assert row["reclaimable"] > 0


def test_json_output_respects_max_rows(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(main, ["find", "*.txt", str(tmp_path), "--json", "--max-rows", "3"])
    data = _parse(result)

    assert len(data["rows"]) == 3
    assert data["total"]["matches"] == 10


def test_json_output_reflects_truncated_walk(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x")

    runner = CliRunner()
    result = runner.invoke(
        main, ["find", "*.txt", str(tmp_path), "--json", "--max-entries", "2"]
    )
    data = _parse(result)

    assert data["complete"] is False
    assert data["stop_reason"] is not None


def test_json_output_combined_with_exclude(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x")
    (tmp_path / "src.py").write_text("x")

    runner = CliRunner()
    result = runner.invoke(
        main, ["ext", str(tmp_path), "--json", "--exclude", "node_modules"]
    )
    data = _parse(result)

    exts = {row["ext"] for row in data["rows"]}
    assert exts == {".py"}
    assert data["total"]["files"] == 1


def test_dup_json_output_with_skip_vendored(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("same content")
    (tmp_path / "node_modules" / "y.js").write_text("same content")
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.txt").write_text("same content")
    (tmp_path / "real" / "b.txt").write_text("same content")

    runner = CliRunner()
    result = runner.invoke(main, ["dup", str(tmp_path), "--json", "--skip-vendored"])
    data = _parse(result)

    assert data["total"]["duplicate_sets"] == 1
    assert data["rows"][0]["copies"] == 2
    assert "node_modules" not in data["rows"][0]["path"]
