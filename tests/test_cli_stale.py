import os
import time

from click.testing import CliRunner

from gazetteer.cli import main


def _touch_with_age(path, age_seconds):
    path.write_text("x")
    old_time = time.time() - age_seconds
    os.utime(path, (old_time, old_time))


def test_stale_finds_old_files(tmp_path):
    _touch_with_age(tmp_path / "old.txt", age_seconds=200 * 86400)
    _touch_with_age(tmp_path / "new.txt", age_seconds=10)

    runner = CliRunner()
    result = runner.invoke(main, ["stale", str(tmp_path), "--older-than", "90d"])

    assert result.exit_code == 0
    assert "old.txt" in result.output
    assert "new.txt" not in result.output
    assert "Total: 1 files older than 90d" in result.output


def test_stale_accepts_various_duration_units(tmp_path):
    _touch_with_age(tmp_path / "old.txt", age_seconds=10 * 3600)

    runner = CliRunner()
    result = runner.invoke(main, ["stale", str(tmp_path), "--older-than", "1h"])

    assert result.exit_code == 0
    assert "old.txt" in result.output


def test_stale_rejects_invalid_duration(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["stale", str(tmp_path), "--older-than", "bogus"])

    assert result.exit_code != 0
    assert "invalid duration" in result.output


def test_stale_combines_with_ext_filter(tmp_path):
    _touch_with_age(tmp_path / "old.txt", age_seconds=200 * 86400)
    _touch_with_age(tmp_path / "old.jpg", age_seconds=200 * 86400)

    runner = CliRunner()
    result = runner.invoke(
        main, ["stale", str(tmp_path), "--older-than", "90d", "--ext", ".jpg"]
    )

    assert result.exit_code == 0
    assert "old.jpg" in result.output
    assert "old.txt" not in result.output
