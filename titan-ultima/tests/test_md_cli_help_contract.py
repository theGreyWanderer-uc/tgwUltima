"""Public CLI help contracts for the Martian Dreams entry point."""

from typer.testing import CliRunner

from titan.cli import app
from titan.md.cli import md_app


def test_root_registers_martian_dreams() -> None:
    result = CliRunner().invoke(app, ["md", "--help"])
    assert result.exit_code == 0, result.output
    assert "Martian Dreams" in result.output
    assert "map-render" in result.output


def test_md_map_render_help_lists_public_options() -> None:
    result = CliRunner().invoke(md_app, ["map-render", "--help"])
    assert result.exit_code == 0, result.output
    for option in (
        "--gamedir",
        "--palette",
        "--region",
        "--dungeon",
        "--full",
        "--objects",
        "--actors",
        "--savegame",
        "--show-markers",
        "--show-invisible",
        "--tick",
        "--palette-tick",
        "--lighting",
        "--output",
    ):
        assert option in result.output


def test_every_md_command_has_working_help() -> None:
    for command in md_app.registered_commands:
        assert command.name is not None
        result = CliRunner().invoke(md_app, [command.name, "--help"])
        assert result.exit_code == 0, result.output
