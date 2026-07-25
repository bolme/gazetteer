import importlib.util

import pytest
from click.testing import CliRunner

from gazetteer.cli import main

HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None


def test_convert_rejects_json_as_already_text(tmp_path):
    path = tmp_path / "sample.json"
    path.write_text('{"a": 1}')
    output = tmp_path / "out.txt"

    runner = CliRunner()
    result = runner.invoke(main, ["convert", str(path), "-o", str(output)])

    assert result.exit_code != 0
    assert "already text" in result.output
    assert "gaz preview" in result.output
    assert not output.exists()


@pytest.mark.parametrize("fmt", ["yaml", "toml", "xml"])
def test_convert_rejects_all_preview_only_formats(tmp_path, fmt):
    path = tmp_path / f"sample.{fmt}"
    path.write_text("placeholder")
    output = tmp_path / "out.txt"

    runner = CliRunner()
    result = runner.invoke(main, ["convert", str(path), "-o", str(output)])

    assert result.exit_code != 0
    assert "already text" in result.output


def test_convert_txt_to_md_writes_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello world")
    output = tmp_path / "out.md"

    runner = CliRunner()
    result = runner.invoke(main, ["convert", str(path), "-o", str(output)])

    assert result.exit_code == 0
    assert output.read_text() == "hello world"
    assert "Complete." in result.output
    assert str(output) in result.output


def test_convert_nonexistent_input_is_clean_usage_error(tmp_path):
    missing = tmp_path / "nope.docx"
    output = tmp_path / "out.md"

    runner = CliRunner()
    result = runner.invoke(main, ["convert", str(missing), "-o", str(output)])

    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_convert_requires_output_flag(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")

    runner = CliRunner()
    result = runner.invoke(main, ["convert", str(path)])

    assert result.exit_code != 0
    assert "output" in result.output.lower()


def test_convert_missing_converter_is_actionable_and_leaves_no_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("gazetteer.convert._has_module", lambda name: False)
    path = tmp_path / "report.docx"
    path.write_bytes(b"fake docx bytes")
    output = tmp_path / "out.md"

    runner = CliRunner()
    result = runner.invoke(main, ["convert", str(path), "-o", str(output)])

    assert result.exit_code != 0
    assert "pandoc" in result.output
    assert not output.exists()


@pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl not installed")
def test_convert_xlsx_infers_csv_from_output_extension(tmp_path):
    import openpyxl

    xlsx_path = tmp_path / "data.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Age"])
    sheet.append(["Alice", 30])
    workbook.save(xlsx_path)

    output = tmp_path / "out.csv"
    runner = CliRunner()
    result = runner.invoke(main, ["convert", str(xlsx_path), "-o", str(output)])

    assert result.exit_code == 0
    content = output.read_text()
    assert "Name,Age" in content
    assert "Alice,30" in content


@pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl not installed")
def test_convert_xlsx_to_explicit_md_gives_natural_representation(tmp_path):
    import openpyxl

    xlsx_path = tmp_path / "data.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Age"])
    workbook.save(xlsx_path)

    output = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(main, ["convert", str(xlsx_path), "-o", str(output)])

    assert result.exit_code == 0
    assert output.exists()
