"""U7 place commands: named buildings, dungeons, areas and towns."""

from __future__ import annotations

import sys
from typing import Annotated, Literal, Optional

import typer


def places_export_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(help="STATIC directory; defaults to the configured game"),
    ] = None,
    output: Annotated[
        str,
        typer.Option("-o", "--output", help="JSON file to write"),
    ] = ...,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Ultima VII game; only bg has place data so far"),
    ] = "bg",
    pretty: Annotated[
        bool,
        typer.Option("--pretty/--compact", help="Indented or compact JSON"),
    ] = False,
) -> None:
    """Export every named building, dungeon, area and town as one JSON file.

    Buildings and dungeons are found in your game files (roofs, floors, doors,
    signs, and who is where when a new game starts); names and town outlines
    come from place data bundled with titan.
    """
    from titan.u7.places import (
        PlaceDataError,
        available_games,
        build_places_document,
        write_places_document,
    )

    if game not in available_games():
        print(
            f"ERROR: No place data for --game {game} yet; Serpent Isle is still "
            f"being reviewed. Available: {', '.join(available_games())}.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        document = build_places_document(static, game)
    except (FileNotFoundError, PlaceDataError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    path = write_places_document(document, output, pretty=pretty)
    counts = document["counts"]
    print(
        f"{counts['towns']} towns, {counts['buildings']} buildings "
        f"({counts['buildings_named']} named), {counts['dungeons']} dungeons "
        f"({counts['dungeons_named']} named), {counts['areas']} areas -> {path}"
    )
