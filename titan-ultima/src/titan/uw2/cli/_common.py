"""Helpers and option types shared by the ``titan uw2`` command modules."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from titan.errors import InstallNotFoundError


def _uw2_game_directory(value: str | None) -> Path | None:
    """The ``--game-dir`` value; when omitted, the CLI fills it from the configured install (titan._input_fill)."""
    return Path(value).expanduser() if value else None


def _require_uw2_game_directory(explicit: str | None) -> Path:
    """:func:`_uw2_game_directory`, or :class:`InstallNotFoundError` if none is set."""
    game_directory = _uw2_game_directory(explicit)
    if game_directory is None:
        raise InstallNotFoundError("provide --game-dir or configure [uw2.game] base")
    return game_directory


def _uw2_data_file(value: str, game_directory: Path | None) -> Path:
    """Resolve absolute/path-like input or a file name below UU2 ``DATA``."""
    path = Path(value).expanduser()
    if path.is_file() or path.is_absolute() or game_directory is None:
        return path
    data_directory = (
        game_directory
        if game_directory.name.upper() == "DATA"
        else game_directory / "DATA"
    )
    return data_directory / path


def _require_file(path: Path, label: str) -> bool:
    if path.is_file():
        return True
    typer.echo(f"ERROR: UU2 {label} file not found: {path}", err=True)
    return False


GameDirOption = Annotated[
    Optional[str],
    typer.Option(
        "-g",
        "--game-dir",
        help="UU2 install root or DATA directory; falls back to [uw2.game] base",
    ),
]


PaletteOption = Annotated[
    Optional[str],
    typer.Option("-p", "--palette", help="PALS.DAT path/name (default: PALS.DAT)"),
]


AllPalsOption = Annotated[
    Optional[str],
    typer.Option(
        "-a",
        "--allpals",
        help="ALLPALS.DAT path/name (default: ALLPALS.DAT when found)",
    ),
]


SlotsOption = Annotated[
    Optional[list[int]],
    typer.Option("--slots", help="Zero-based LEV.ARK map slots (repeat values)"),
]


CeilingSourceOption = Annotated[
    str,
    typer.Option(
        "--ceiling-source",
        help="runtime port rule, or ua for UnderworldAdventures mapping[32]",
    ),
]


ZScaleOption = Annotated[
    float,
    typer.Option("--z-scale", help="Map height units per rendered unit"),
]
