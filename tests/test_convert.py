import importlib.util
import shutil

import pytest

from gazetteer.convert import (
    PREVIEW_ONLY_FORMATS,
    UnsupportedFormat,
    convert_to_text,
    detect_format,
)

HAS_PANDOC = shutil.which("pandoc") is not None
HAS_PDFTOTEXT = shutil.which("pdftotext") is not None
HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None
HAS_PYYAML = importlib.util.find_spec("yaml") is not None


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("report.docx", "docx"),
        ("slides.pptx", "pptx"),
        ("data.xlsx", "xlsx"),
        ("legacy.xls", "xls"),
        ("doc.pdf", "pdf"),
        ("config.json", "json"),
        ("config.yaml", "yaml"),
        ("config.yml", "yaml"),
        ("config.toml", "toml"),
        ("data.xml", "xml"),
        ("data.csv", "csv"),
        ("notes.md", "md"),
        ("notes.markdown", "md"),
        ("plain.txt", "txt"),
    ],
)
def test_detect_format_by_extension(tmp_path, filename, expected):
    path = tmp_path / filename
    path.write_text("x")
    assert detect_format(str(path)) == expected


def test_detect_format_sniffs_binary_without_known_extension(tmp_path):
    path = tmp_path / "mystery.bin"
    path.write_bytes(b"\x00\x01\x02binary junk")
    assert detect_format(str(path)) == "binary"


def test_detect_format_sniffs_text_without_known_extension(tmp_path):
    path = tmp_path / "mystery"
    path.write_text("just some plain text, no nulls")
    assert detect_format(str(path)) == "txt"


def test_convert_json_pretty_prints(tmp_path):
    path = tmp_path / "sample.json"
    path.write_text('{"b": 2, "a": [1, 2, 3]}')

    result = convert_to_text(str(path))

    assert result.method == "stdlib-json"
    assert result.complete
    assert '"a": [' in result.text
    assert "  " in result.text  # indented


def test_convert_json_invalid_raises(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")

    with pytest.raises(UnsupportedFormat):
        convert_to_text(str(path))


def test_convert_csv_renders_aligned_table(tmp_path):
    path = tmp_path / "sample.csv"
    path.write_text("name,age\nAlice,30\nBob,25\n")

    result = convert_to_text(str(path))

    assert result.method == "stdlib-csv"
    lines = result.text.splitlines()
    assert lines[0].startswith("name")
    assert "Alice" in result.text
    assert "Bob" in result.text


def test_convert_csv_empty_file(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("")

    result = convert_to_text(str(path))

    assert result.method == "stdlib-csv"
    assert result.text == ""


def test_convert_xml_pretty_prints(tmp_path):
    path = tmp_path / "sample.xml"
    path.write_text("<root><item>hello</item></root>")

    result = convert_to_text(str(path))

    assert result.method == "stdlib-xml"
    assert "<root>" in result.text
    assert "<item>hello</item>" in result.text


def test_convert_xml_invalid_raises(tmp_path):
    path = tmp_path / "bad.xml"
    path.write_text("<root><unclosed>")

    with pytest.raises(UnsupportedFormat):
        convert_to_text(str(path))


def test_convert_markdown_reads_as_is(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nBody text.")

    result = convert_to_text(str(path))

    assert result.method == "text"
    assert result.text == "# Title\n\nBody text."


def test_convert_txt_reads_as_is(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("plain content")

    result = convert_to_text(str(path))

    assert result.text == "plain content"


def test_convert_binary_with_no_extension_raises(tmp_path):
    path = tmp_path / "mystery.bin"
    path.write_bytes(b"\x00\x01\x02binary")

    with pytest.raises(UnsupportedFormat):
        convert_to_text(str(path))


def test_missing_converter_error_names_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("gazetteer.convert._has_module", lambda name: False)
    path = tmp_path / "report.docx"
    path.write_bytes(b"not a real docx")

    with pytest.raises(UnsupportedFormat) as exc_info:
        convert_to_text(str(path))

    message = str(exc_info.value)
    assert "pandoc" in message
    assert "gaz[preview]" in message


def test_timeout_reports_incomplete_not_an_exception(tmp_path, monkeypatch):
    if not HAS_PANDOC:
        pytest.skip("pandoc not on PATH")
    path = tmp_path / "report.docx"
    path.write_bytes(b"PK\x03\x04fake docx bytes")  # invalid but has the right extension

    result = convert_to_text(str(path), max_seconds=0.0000001)

    assert not result.complete
    assert result.warning is not None
    assert "did not finish" in result.warning


@pytest.mark.skipif(not HAS_PYYAML, reason="PyYAML not installed")
def test_convert_yaml_with_pyyaml(tmp_path):
    path = tmp_path / "sample.yaml"
    path.write_text("name: test\nitems:\n  - a\n  - b\n")

    result = convert_to_text(str(path))

    assert result.method == "pyyaml"
    assert "name: test" in result.text


def test_convert_yaml_without_pyyaml_falls_back_to_raw_text(tmp_path, monkeypatch):
    monkeypatch.setattr("gazetteer.convert._has_module", lambda name: False)
    path = tmp_path / "sample.yaml"
    path.write_text("name: test\n")

    result = convert_to_text(str(path))

    assert "PyYAML not installed" in result.warning
    assert result.text == "name: test\n"


def test_convert_toml_without_tomli_below_311_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.version_info", (3, 10, 0))
    monkeypatch.setattr("gazetteer.convert._has_module", lambda name: False)
    path = tmp_path / "sample.toml"
    path.write_text('name = "test"\n')

    result = convert_to_text(str(path))

    assert "tomli not installed" in result.warning
    assert result.text == 'name = "test"\n'


@pytest.mark.skipif(not HAS_PANDOC, reason="pandoc not on PATH")
def test_convert_docx_via_pandoc(tmp_path):
    import subprocess

    md_path = tmp_path / "source.md"
    md_path.write_text("# Heading\n\nBody paragraph.\n")
    docx_path = tmp_path / "sample.docx"
    subprocess.run(
        ["pandoc", str(md_path), "-o", str(docx_path)],
        check=True,
        capture_output=True,
    )

    result = convert_to_text(str(docx_path))

    assert result.method == "pandoc"
    assert result.complete
    assert "Heading" in result.text
    assert "Body paragraph" in result.text


@pytest.mark.skipif(not HAS_PDFTOTEXT, reason="pdftotext not on PATH")
def test_convert_pdf_via_pdftotext(tmp_path):
    # Minimal hand-built single-page PDF containing one line of text.
    pdf_bytes = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>/MediaBox[0 0 612 792]/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 55>>
stream
BT /F1 24 Tf 100 700 Td (Hello test PDF) Tj ET
endstream
endobj
xref
0 6
0000000000 65535 f
trailer<</Size 6/Root 1 0 R>>
startxref
0
%%EOF
"""
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(pdf_bytes)

    result = convert_to_text(str(pdf_path))

    assert result.method == "pdftotext"
    assert result.complete
    assert "Hello test PDF" in result.text


@pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl not installed")
def test_convert_xlsx_to_csv_uses_first_sheet_only(tmp_path):
    import openpyxl

    xlsx_path = tmp_path / "sample.xlsx"
    workbook = openpyxl.Workbook()
    sheet1 = workbook.active
    sheet1.title = "First"
    sheet1.append(["Name", "Age"])
    sheet1.append(["Alice", 30])
    sheet2 = workbook.create_sheet("Second")
    sheet2.append(["Other", "Data"])
    workbook.save(xlsx_path)

    result = convert_to_text(str(xlsx_path), to_format="csv")

    assert result.method == "openpyxl"
    assert "Name,Age" in result.text
    assert "Alice,30" in result.text
    assert "Other" not in result.text
    assert result.warning is not None
    assert "2 sheets" in result.warning


def test_convert_xlsx_to_csv_without_openpyxl_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("gazetteer.convert._has_module", lambda name: False)
    path = tmp_path / "sample.xlsx"
    path.write_bytes(b"PK\x03\x04fake")

    with pytest.raises(UnsupportedFormat) as exc_info:
        convert_to_text(str(path), to_format="csv")

    assert "openpyxl" in str(exc_info.value)


def test_preview_only_formats_are_json_yaml_toml_xml():
    assert PREVIEW_ONLY_FORMATS == {"json", "yaml", "toml", "xml"}


# --- Corrupt/mislabeled files must not leak library tracebacks ---------
# Each optional library raises its own exception type for a file that
# isn't what its extension claims. Those used to propagate as raw
# tracebacks (see TODO.md's preview/convert error-path item); they must
# come back as UnsupportedFormat naming the file and the library.


@pytest.mark.skipif(
    not importlib.util.find_spec("docx"), reason="python-docx not installed"
)
def test_corrupt_docx_raises_unsupported_not_library_error(tmp_path, monkeypatch):
    # No pandoc, so dispatch reaches the python-docx fallback.
    monkeypatch.setattr("shutil.which", lambda name: None)
    path = tmp_path / "fake.docx"
    path.write_text("this is plainly not a docx")

    with pytest.raises(UnsupportedFormat) as exc_info:
        convert_to_text(str(path))

    message = str(exc_info.value)
    assert "python-docx" in message
    assert "fake.docx" in message
    assert "corrupt, truncated, or not actually a .docx" in message


@pytest.mark.skipif(
    not importlib.util.find_spec("pypdf"), reason="pypdf not installed"
)
def test_empty_pdf_raises_unsupported_not_library_error(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")

    with pytest.raises(UnsupportedFormat) as exc_info:
        convert_to_text(str(path))

    message = str(exc_info.value)
    assert "pypdf" in message
    assert "empty.pdf" in message


def test_pandoc_failure_without_fallback_surfaces_pandoc_stderr(tmp_path, monkeypatch):
    """pandoc exists but fails, and no Python fallback is installed.

    The old message said only "no converter available," hiding the actual
    reason. pandoc's stderr is the only real explanation, so it must survive.
    """
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pandoc")
    monkeypatch.setattr("gazetteer.convert._has_module", lambda name: False)

    class FakeProc:
        returncode = 1
        stdout = b""
        stderr = b"pandoc: cannot decode byte -- invalid UTF-8 stream"

    monkeypatch.setattr(
        "gazetteer.convert._run_subprocess", lambda cmd, max_seconds: FakeProc()
    )
    path = tmp_path / "report.docx"
    path.write_bytes(b"garbage")

    with pytest.raises(UnsupportedFormat) as exc_info:
        convert_to_text(str(path))

    message = str(exc_info.value)
    assert "invalid UTF-8 stream" in message
    assert "gaz[preview]" in message


# --- check_dependencies -----------------------------------------------


def test_check_dependencies_reports_every_format():
    from gazetteer.convert import check_dependencies

    rows = check_dependencies()
    formats = {fmt for fmt, _, _ in rows}
    assert {"docx", "pptx", "xlsx", "pdf", "json", "csv", "xml"} <= formats
    # stdlib-only formats are always usable, whatever is installed.
    stdlib = {fmt: usable for fmt, usable, _ in rows}
    assert stdlib["json"] and stdlib["xml"] and stdlib["csv"]


def test_check_dependencies_marks_missing_converters(monkeypatch):
    from gazetteer.convert import check_dependencies

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("gazetteer.convert._has_module", lambda name: False)

    rows = {fmt: (usable, detail) for fmt, usable, detail in check_dependencies()}

    usable, detail = rows["docx"]
    assert usable is False
    assert "pandoc" in detail and "docx" in detail

    # yaml degrades to raw text rather than failing, so it stays usable.
    usable, _ = rows["yaml"]
    assert usable is True

    # stdlib formats are unaffected by anything being missing.
    assert rows["json"][0] is True
