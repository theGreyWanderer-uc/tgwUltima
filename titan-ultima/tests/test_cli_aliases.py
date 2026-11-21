"""Renamed options: new names in help, old spellings still accepted."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from titan._cli_aliases import alias_group, renamed_options, rewrite_args
from titan.cli import app


def _command(*opts: str) -> SimpleNamespace:
    params = [SimpleNamespace(opts=[opt], secondary_opts=[]) for opt in opts]
    return SimpleNamespace(params=params, callback=None)


ALIASES = {"--gamedir": ("--game-dir",), "--json": ("--format", "json")}


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--gamedir", "D:/U6"], ["--game-dir", "D:/U6"]),
        (["--gamedir=D:/U6"], ["--game-dir=D:/U6"]),
        (["--json"], ["--format", "json"]),
        (["-g", "x", "--", "--gamedir"], ["-g", "x", "--", "--gamedir"]),
    ],
)
def test_rewrite_args(args, expected) -> None:
    assert rewrite_args(args, _command("--game-dir", "--format"), ALIASES) == expected


def test_alias_never_overrides_a_command_that_keeps_the_old_name() -> None:
    both = _command("--gamedir", "--game-dir")
    assert rewrite_args(["--gamedir", "x"], both, ALIASES) == ["--gamedir", "x"]
    neither = _command("--output")
    assert rewrite_args(["--gamedir", "x"], neither, ALIASES) == ["--gamedir", "x"]


def test_group_rewrites_before_parsing_in_process() -> None:
    demo = typer.Typer(cls=alias_group({"--gamedir": "--game-dir"}))

    @demo.command("show")
    def show(game_dir: str = typer.Option("", "--game-dir")) -> None:
        typer.echo(f"dir={game_dir}")

    @demo.command("other")
    @renamed_options({"--old": "--new"})
    def other(new: str = typer.Option("", "--new")) -> None:
        typer.echo(f"new={new}")

    runner = CliRunner()
    assert runner.invoke(demo, ["show", "--gamedir", "A"]).output.strip() == "dir=A"
    assert runner.invoke(demo, ["other", "--old", "B"]).output.strip() == "new=B"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (["u6", "map-render", "--gamedir", "X", "--help"], "--game-dir"),
        (["md", "map-render", "--savegame", "X", "--help"], "--save"),
        (["u8", "map-render", "--nonfixed", "3", "--help"], "--save"),
        (["u7", "map-render", "--gamedat", "X", "--help"], "--save"),
        (["uw1", "texture-info", "--json", "--help"], "--format"),
        (["u9", "save-check", "T", "--json", "r.json", "--help"], "--output"),
        (["uo", "art-export", "--output", "X", "--help"], "--output-dir"),
    ],
)
def test_titan_accepts_old_spellings(old, new) -> None:
    result = CliRunner().invoke(app, old)
    assert result.exit_code == 0, result.output
    assert new in result.output


@pytest.mark.parametrize(
    ("command", "gone"),
    [
        (["u6", "map-render"], "--gamedir"),
        (["md", "map-render"], "--savegame"),
        (["u8", "map-render"], "--nonfixed"),
        (["u7", "map-render"], "--gamedat"),
        (["uw2", "shape-info"], "--json"),
        (["u8", "palette-export"], "--output "),
    ],
)
def test_help_shows_only_the_new_names(command, gone) -> None:
    result = CliRunner().invoke(app, [*command, "--help"], terminal_width=200)
    assert result.exit_code == 0, result.output
    assert gone not in result.output
