"""Path rendering is consistent across every command with a path column.

Absolute paths on a real tree routinely run past 100 characters and push
the numeric columns off the right edge. Text output is therefore relative
to the walk root everywhere; -P opts into absolute; --json always emits
absolute regardless, since a consumer's cwd is not gaz's cwd.
"""

import json

import pytest
from click.testing import CliRunner

from gazetteer.cli import main

# (command args producing at least one path row). `ext` is excluded: its
# rows are extensions, not paths.
PATH_COMMANDS = [
    ["list"],
    ["find", "*"],
    ["largest"],
    ["stale", "--older-than", "0s"],
    ["empty"],
    ["dup"],
]


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "sub" / "deep").mkdir(parents=True)
    (tmp_path / "emptydir").mkdir()
    (tmp_path / "a.txt").write_text("duplicate body")
    (tmp_path / "sub" / "b.txt").write_text("duplicate body")
    (tmp_path / "sub" / "deep" / "c.txt").write_text("unique")
    return tmp_path


@pytest.mark.parametrize("cmd", PATH_COMMANDS, ids=lambda c: c[0])
def test_text_output_is_relative_by_default(tree, cmd):
    runner = CliRunner()
    result = runner.invoke(main, [*cmd, str(tree)])

    assert result.exit_code == 0, result.output
    # The absolute tmp_path prefix must not appear anywhere in the table.
    # (`list` goes further and shows bare names like "sub/", since its rows
    # are always exactly one level down and "./" would just be noise.)
    table = result.output.split("\n\n")[0]
    assert str(tree) not in table, f"{cmd[0]} leaked an absolute path"


@pytest.mark.parametrize("cmd", PATH_COMMANDS, ids=lambda c: c[0])
def test_full_paths_flag_switches_to_absolute(tree, cmd):
    runner = CliRunner()
    result = runner.invoke(main, [*cmd, str(tree), "-P"])

    assert result.exit_code == 0, result.output
    assert str(tree) in result.output


@pytest.mark.parametrize("cmd", PATH_COMMANDS, ids=lambda c: c[0])
def test_json_paths_are_always_absolute(tree, cmd):
    runner = CliRunner()
    result = runner.invoke(main, [*cmd, str(tree), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    if not data["rows"]:
        pytest.skip(f"{cmd[0]} produced no rows on this fixture")
    for row in data["rows"]:
        path = row.get("path") or row.get("dir")
        assert path.startswith("/"), f"{cmd[0]} emitted a relative JSON path"


@pytest.mark.parametrize("cmd", PATH_COMMANDS, ids=lambda c: c[0])
def test_full_paths_does_not_change_json(tree, cmd):
    # -P is a text-output concern, so it must not alter JSON at all. Only
    # the path fields are compared: rows also carry live values (ages,
    # elapsed) that differ between two runs for reasons unrelated to -P.
    runner = CliRunner()
    plain = json.loads(runner.invoke(main, [*cmd, str(tree), "--json"]).output)
    with_p = json.loads(
        runner.invoke(main, [*cmd, str(tree), "--json", "-P"]).output
    )

    def paths(data):
        return [r.get("path") or r.get("dir") for r in data["rows"]]

    assert paths(plain) == paths(with_p)


def test_every_path_command_accepts_dash_p():
    # A flag that exists on five of six commands is worse than one that
    # exists on all of them; this catches a new command forgetting it.
    runner = CliRunner()
    for cmd in PATH_COMMANDS:
        result = runner.invoke(main, [*cmd, "--help"])
        assert "-P, --full-paths" in result.output, f"{cmd[0]} is missing -P"


def test_ext_does_not_offer_full_paths():
    # ext's rows are extensions — a path flag there would do nothing.
    runner = CliRunner()
    result = runner.invoke(main, ["ext", "--help"])
    assert "--full-paths" not in result.output


def test_root_itself_renders_as_dot_slash(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["empty", str(tmp_path)])

    assert result.exit_code == 0
    assert "./" in result.output
    assert str(tmp_path) not in result.output.split("\n\n")[0]


def test_nested_paths_keep_their_structure(tree):
    runner = CliRunner()
    result = runner.invoke(main, ["find", "c.txt", str(tree)])

    assert result.exit_code == 0
    assert "./sub/deep/c.txt" in result.output


ALL_COMMANDS_WITH_ROWS = [
    ["ext"],
    ["list"],
    ["find", "*"],
    ["largest"],
    ["stale", "--older-than", "0s"],
]


@pytest.mark.parametrize("cmd", ALL_COMMANDS_WITH_ROWS, ids=lambda c: c[0])
def test_every_command_reports_row_truncation(tmp_path, cmd):
    # "Never present a partial number as if it were total" applies to row
    # truncation too, not just a truncated walk.
    for i in range(10):
        (tmp_path / f"f{i}.e{i}").write_text("x" * (i + 1))

    runner = CliRunner()
    result = runner.invoke(main, [*cmd, str(tmp_path), "--max-rows", "3"])

    assert result.exit_code == 0, result.output
    assert "Showing 3 of 10" in result.output, f"{cmd[0]} hid rows silently"
