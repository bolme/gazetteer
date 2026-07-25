from click.testing import CliRunner

from gazetteer.cli import main


def test_preview_json_shows_pretty_printed_content(tmp_path):
    path = tmp_path / "sample.json"
    path.write_text('{"a": 1, "b": 2}')

    runner = CliRunner()
    result = runner.invoke(main, ["preview", str(path)])

    assert result.exit_code == 0
    assert '"a": 1' in result.output
    assert "Complete." in result.output


def test_preview_truncates_to_max_lines_by_default(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("\n".join(f"line {i}" for i in range(1, 61)))

    runner = CliRunner()
    result = runner.invoke(main, ["preview", str(path)])

    assert result.exit_code == 0
    assert "line 50" in result.output
    assert "line 51" not in result.output
    assert "Showing 50 of 60 lines" in result.output
    assert "--full" in result.output


def test_preview_full_shows_everything(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("\n".join(f"line {i}" for i in range(1, 61)))

    runner = CliRunner()
    result = runner.invoke(main, ["preview", str(path), "--full"])

    assert result.exit_code == 0
    assert "line 60" in result.output
    assert "Showing all 60 lines" in result.output
    assert "Complete." in result.output


def test_preview_max_lines_override(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("\n".join(f"line {i}" for i in range(1, 61)))

    runner = CliRunner()
    result = runner.invoke(main, ["preview", str(path), "--max-lines", "5"])

    assert result.exit_code == 0
    assert "line 5" in result.output
    assert "line 6" not in result.output
    assert "Showing 5 of 60 lines" in result.output


def test_preview_nonexistent_file_is_clean_usage_error(tmp_path):
    missing = tmp_path / "nope.json"
    runner = CliRunner()
    result = runner.invoke(main, ["preview", str(missing)])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_preview_markdown_reads_as_is(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nBody.")

    runner = CliRunner()
    result = runner.invoke(main, ["preview", str(path)])

    assert result.exit_code == 0
    assert "# Title" in result.output


def test_preview_csv_renders_aligned_table(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("name,age\nAlice,30\n")

    runner = CliRunner()
    result = runner.invoke(main, ["preview", str(path)])

    assert result.exit_code == 0
    assert "Alice" in result.output


def test_preview_binary_with_unknown_extension_is_a_clean_error(tmp_path):
    path = tmp_path / "mystery.bin"
    path.write_bytes(b"\x00\x01\x02binary junk")

    runner = CliRunner()
    result = runner.invoke(main, ["preview", str(path)])

    assert result.exit_code != 0
    assert "Error" in result.output


def test_preview_missing_converter_gives_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("gazetteer.convert._has_module", lambda name: False)
    path = tmp_path / "report.docx"
    path.write_bytes(b"fake docx bytes")

    runner = CliRunner()
    result = runner.invoke(main, ["preview", str(path)])

    assert result.exit_code != 0
    assert "pandoc" in result.output
    assert "gaz[preview]" in result.output
