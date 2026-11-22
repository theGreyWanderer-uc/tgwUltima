"""``titan uw2`` object table commands."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._meta import meta
from titan.uw2.cli._common import (
    GameDirOption,
    _require_file,
    _uw2_data_file,
    _uw2_game_directory,
)
from titan.uw2.object_data import (
    ANIMATION_ITEM_FIRST,
    ANIMATION_ITEM_LAST,
    UW2AnimationTable,
    UW2CommonObjectTable,
    UW2ObjectDataError,
)


def _resolve_object_tables(
    args: SimpleNamespace,
) -> tuple[UW2CommonObjectTable, UW2AnimationTable | None] | None:
    game_directory = _uw2_game_directory(args.gamedir)
    common_path = _uw2_data_file(args.comobj or "COMOBJ.DAT", game_directory)
    objects_path = _uw2_data_file(args.objects or "OBJECTS.DAT", game_directory)
    if not _require_file(common_path, "common object metadata"):
        return None
    try:
        common = UW2CommonObjectTable.from_file(common_path)
        animations = (
            UW2AnimationTable.from_file(objects_path)
            if objects_path.is_file()
            else None
        )
    except (OSError, UW2ObjectDataError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        return None
    if args.objects and animations is None:
        _require_file(objects_path, "animation metadata")
        return None
    return common, animations


def _object_record_dict(
    item_id: int,
    common: UW2CommonObjectTable,
    animations: UW2AnimationTable | None,
) -> dict[str, object]:
    result = common.get(item_id).to_dict()
    if (
        animations is not None
        and ANIMATION_ITEM_FIRST <= item_id <= ANIMATION_ITEM_LAST
    ):
        result["animation"] = animations.get(item_id).to_dict()
    return result


def cmd_object_info(args: SimpleNamespace) -> int:
    """Print rendering metadata for one UU2 item ID."""
    tables = _resolve_object_tables(args)
    if tables is None:
        return 1
    common, animations = tables
    result = _object_record_dict(args.item_id, common, animations)
    typer.echo(json.dumps(result, indent=2))
    return 0


def cmd_object_dump(args: SimpleNamespace) -> int:
    """Export all UU2 COMOBJ.DAT rendering metadata to JSON or CSV."""
    tables = _resolve_object_tables(args)
    if tables is None:
        return 1
    common, animations = tables
    records = [
        _object_record_dict(record.item_id, common, animations)
        for record in common.records
    ]
    output = Path(args.output or f"uw2_objects.{args.format}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    else:
        flat_records = []
        for record in records:
            flat = {key: value for key, value in record.items() if key != "animation"}
            animation = record.get("animation")
            if isinstance(animation, dict):
                flat.update(
                    {f"animation_{key}": value for key, value in animation.items()}
                )
            flat_records.append(flat)
        fieldnames = list(flat_records[0])
        for record in flat_records[1:]:
            fieldnames.extend(key for key in record if key not in fieldnames)
        with output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flat_records)
    typer.echo(f"Exported {len(records)} UU2 object metadata records: {output}")
    return 0


@meta(
    category="data",
    results=("text",),
    params={"comobj": "install-file", "objects": "install-file"},
)
def object_info_cmd(
    item_id: Annotated[int, typer.Argument(help="UU2 item ID (0..511)")],
    comobj: Annotated[
        Optional[str], typer.Option("--comobj", help="COMOBJ.DAT path/name")
    ] = None,
    objects: Annotated[
        Optional[str], typer.Option("--objects", help="OBJECTS.DAT path/name")
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Print one UU2 item's render type and optional animation frames."""
    raise SystemExit(cmd_object_info(SimpleNamespace(**locals())))


@meta(
    category="data",
    results=("json", "table"),
    params={
        "output": "output-file",
        "comobj": "install-file",
        "objects": "install-file",
        "format_name": "format",
    },
)
def object_dump_cmd(
    comobj: Annotated[
        Optional[str], typer.Option("--comobj", help="COMOBJ.DAT path/name")
    ] = None,
    objects: Annotated[
        Optional[str], typer.Option("--objects", help="OBJECTS.DAT path/name")
    ] = None,
    format_name: Annotated[
        str, typer.Option("-f", "--format", help="json or csv")
    ] = "json",
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output file")
    ] = None,
    gamedir: GameDirOption = None,
) -> None:
    """Export all UU2 COMOBJ.DAT render metadata as JSON or CSV."""
    if format_name not in {"json", "csv"}:
        raise typer.BadParameter("must be json or csv", param_hint="--format")
    raise SystemExit(
        cmd_object_dump(
            SimpleNamespace(
                comobj=comobj,
                objects=objects,
                format=format_name,
                output=output,
                gamedir=gamedir,
            )
        )
    )
