"""Read-only MD actor, save-state, dialogue and text export commands."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Iterator, Optional

import typer

from titan._config import get_config
from titan.md.actor import parse_martian_actors
from titan.md.game_profile import resolve_martian_directory
from titan.md.gamestate import MartianGameState
from titan.md.references import (
    martian_dialogue_report,
    read_martian_books,
    read_martian_dialogue,
    read_martian_names,
)
from titan.md.world_state import load_martian_objlist
from titan.u6.actor import U6ActorError
from titan.u6.converse import U6ConverseError, format_instructions
from titan.u6.lib import U6LibraryError
from titan.u6.look import U6LookError
from titan.u6.lzw import U6LzwError
from titan.u6.object import U6ObjectError

__all__ = ["register_martian_inspection_commands"]


def _directory(explicit: str | None) -> Path:
    path = explicit or get_config().get("md", {}).get("game", {}).get("base")
    if not path:
        raise typer.BadParameter("Pass --gamedir or set [md.game] base in titan.toml")
    return resolve_martian_directory(path)


def _write_text(text: str, output: str | None) -> None:
    if output is None:
        typer.echo(text)
    else:
        destination = Path(output).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf-8")
        typer.echo(f"Saved: {destination}")


@contextmanager
def _inspection_errors() -> Iterator[None]:
    try:
        yield
    except (
        OSError,
        ValueError,
        U6ActorError,
        U6ConverseError,
        U6LibraryError,
        U6LookError,
        U6LzwError,
        U6ObjectError,
    ) as exc:
        typer.echo(f"ERROR: Martian Dreams inspection: {exc}", err=True)
        raise typer.Exit(1) from exc


def register_martian_inspection_commands(app: typer.Typer) -> None:
    """Register MD read-only inspections beside the map renderer, with explicit output paths."""

    @app.command("actor-list")
    def actor_list_cmd(
        gamedir: Annotated[
            Optional[str],
            typer.Option(
                "-g", "--gamedir", help="MARTIAN directory or installation parent"
            ),
        ] = None,
        savegame: Annotated[
            Optional[str],
            typer.Option(
                "--savegame", help="Read actor state from DOS SAVEGAME/OBJLIST"
            ),
        ] = None,
        actor: Annotated[
            Optional[int],
            typer.Option(
                "--actor",
                min=0,
                max=255,
                help="One actor slot; default: all active slots",
            ),
        ] = None,
        output: Annotated[
            Optional[str],
            typer.Option("-o", "--output", help="JSON output file; omit for stdout"),
        ] = None,
    ) -> None:
        """Read MD actor positions, appearances, stats and raw flag bytes."""
        with _inspection_errors():
            directory = _directory(gamedir)
            objlist = load_martian_objlist(directory, savegame)
            actors = parse_martian_actors(objlist)
            names = (
                {s.item: s.display_name for s in read_martian_dialogue(directory)}
                if (directory / "TALK.LZC").is_file()
                else {}
            )
            names.update(
                {m.actor_id: m.name for m in MartianGameState.parse(objlist).party}
            )
            for slot in actors:
                slot.name = names.get(slot.actor_id, "")
            selected = (
                [actors[actor]]
                if actor is not None
                else [a for a in actors if a.is_active]
            )
            _write_text(
                json.dumps([asdict(a) for a in selected], indent=2, ensure_ascii=False),
                output,
            )

    @app.command("gamestate-dump")
    def gamestate_dump_cmd(
        gamedir: Annotated[
            Optional[str],
            typer.Option(
                "-g", "--gamedir", help="MARTIAN directory or installation parent"
            ),
        ] = None,
        savegame: Annotated[
            Optional[str],
            typer.Option(
                "--savegame", help="Read DOS SAVEGAME/OBJLIST instead of initial state"
            ),
        ] = None,
        output: Annotated[
            Optional[str],
            typer.Option("-o", "--output", help="JSON output file; omit for stdout"),
        ] = None,
    ) -> None:
        """Read MD party, clock, gender, dream state, berry timers and world flags."""
        with _inspection_errors():
            state = MartianGameState.parse(
                load_martian_objlist(_directory(gamedir), savegame)
            )
            data = asdict(state)
            data["canals_filled"] = state.canals_filled
            data["brown_berry_vision"] = state.brown_berry_vision
            data["game_datetime"] = state.clock.iso_string()
            _write_text(json.dumps(data, indent=2, ensure_ascii=False), output)

    @app.command("converse-dump")
    def converse_dump_cmd(
        gamedir: Annotated[
            Optional[str],
            typer.Option(
                "-g", "--gamedir", help="MARTIAN directory or installation parent"
            ),
        ] = None,
        item: Annotated[
            Optional[int],
            typer.Option(
                "--item", min=0, help="TALK.LZC slot; default: all NPC scripts"
            ),
        ] = None,
        output: Annotated[
            Optional[str],
            typer.Option(
                "-o", "--output", help="UTF-8 disassembly file; omit for stdout"
            ),
        ] = None,
    ) -> None:
        """Disassemble TALK.LZC NPC scripts, retaining unknown opcodes by number."""
        with _inspection_errors():
            scripts = read_martian_dialogue(_directory(gamedir), item)
            _write_text(
                "\n\n".join(
                    f"TALK.LZC item {s.item}: {s.raw_name}\n{format_instructions(s.instructions)}"
                    for s in scripts
                ),
                output,
            )

    @app.command("converse-report")
    def converse_report_cmd(
        gamedir: Annotated[
            Optional[str],
            typer.Option(
                "-g", "--gamedir", help="MARTIAN directory or installation parent"
            ),
        ] = None,
        output: Annotated[
            Optional[str],
            typer.Option(
                "-o", "--output", help="JSON coverage report; omit for stdout"
            ),
        ] = None,
    ) -> None:
        """Report dialogue coverage and unresolved opcode offsets."""
        with _inspection_errors():
            _write_text(
                json.dumps(martian_dialogue_report(_directory(gamedir)), indent=2),
                output,
            )

    @app.command("look-dump")
    def look_dump_cmd(
        gamedir: Annotated[
            Optional[str],
            typer.Option(
                "-g", "--gamedir", help="MARTIAN directory or installation parent"
            ),
        ] = None,
        tile: Annotated[
            Optional[int],
            typer.Option(
                "--tile",
                min=0,
                max=2047,
                help="Resolve one tile through LOOK's name ranges",
            ),
        ] = None,
        output: Annotated[
            Optional[str],
            typer.Option("-o", "--output", help="JSON name records; omit for stdout"),
        ] = None,
    ) -> None:
        """Read LOOK.LZC with correct archive framing and name-range lookup."""
        with _inspection_errors():
            names = read_martian_names(_directory(gamedir))
            entries = [names.get_entry(tile)] if tile is not None else names.entries
            _write_text(
                json.dumps(
                    [
                        {
                            "range_end_tile": e.tile_num,
                            "raw_name": e.name,
                            "singular": e.singular(),
                            "plural": e.plural(),
                        }
                        for e in entries
                        if e is not None
                    ],
                    indent=2,
                    ensure_ascii=False,
                ),
                output,
            )

    @app.command("book-dump")
    def book_dump_cmd(
        gamedir: Annotated[
            Optional[str],
            typer.Option(
                "-g", "--gamedir", help="MARTIAN directory or installation parent"
            ),
        ] = None,
        book: Annotated[
            Optional[int],
            typer.Option(
                "--book", min=0, help="MDTEXT.LZC text number; default: all texts"
            ),
        ] = None,
        output: Annotated[
            Optional[str],
            typer.Option("-o", "--output", help="UTF-8 text file; omit for stdout"),
        ] = None,
    ) -> None:
        """Read MD books and signs from MDTEXT.LZC, preserving page markers."""
        with _inspection_errors():
            books = read_martian_books(_directory(gamedir))
            if book is not None and book >= len(books):
                raise ValueError(f"Martian Dreams book must be 0-{len(books) - 1}")
            indices = [book] if book is not None else range(len(books))
            _write_text(
                "\n\n".join(f"MDTEXT.LZC item {i}\n{books[i]}" for i in indices), output
            )
