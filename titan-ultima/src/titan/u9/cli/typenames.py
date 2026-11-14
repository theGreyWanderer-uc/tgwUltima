"""``titan u9 typename-*`` / ``types-csv`` — type name and type table commands."""

from __future__ import annotations

__all__ = [
    "typename_dump_cmd",
    "typename_csv_cmd",
    "typename_import_cmd",
    "types_csv_cmd",
]

import csv
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.typename import U9TypeNameError, U9TypeNames
from titan.u9.types_dat import U9TypesDat, U9TypesDatError
from titan.u9.cli import _common


def cmd_typename_dump(args: SimpleNamespace) -> int:
    """List named object types and their readable-text and icon references."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        names = U9TypeNames.from_file(filepath)
    except (U9FlxArchiveError, U9TypeNameError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    named = [entry for entry in names if entry.display_name]
    print(f"{filepath} — {len(names)} entries, {len(named)} named")
    print(f"{'TypeID':>7}  {'Text':>6}  {'Icon':>6}  Name")
    print("-" * 52)
    for entry in named:
        print(
            f"{entry.type_id:>7}  {entry.readable_text_id:>6}  "
            f"{entry.object_icon_id:>6}  {entry.display_name}"
        )
    return 0


def cmd_typename_csv(args: SimpleNamespace) -> int:
    """Export every ``TYPENAME.FLX`` object-metadata entry to CSV."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    try:
        names = U9TypeNames.from_file(filepath)
    except (U9FlxArchiveError, U9TypeNameError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    output = args.output or f"{Path(filepath).stem}_metadata.csv"
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "type_id",
                "record_representation",
                "warnings",
                "readable_text_id",
                "has_readable_text",
                "object_icon_id",
                "uses_default_icon",
                "display_name",
                "trailing_hex",
                "raw_hex",
            ]
        )
        for entry in names:
            writer.writerow(
                [
                    entry.type_id,
                    entry.record_representation,
                    ";".join(entry.warnings),
                    entry.readable_text_id,
                    entry.has_readable_text,
                    entry.object_icon_id,
                    entry.uses_default_icon,
                    entry.display_name or "",
                    f"0x{entry.trailing_bytes.hex()}" if entry.trailing_bytes else "",
                    f"0x{entry.raw.hex()}",
                ]
            )
    print(f"{filepath} — wrote {len(names)} object metadata row(s) -> {output}")
    return 0


def cmd_typename_import(args: SimpleNamespace) -> int:
    """Rebuild a type-name archive from an edited ``typename-csv`` CSV."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1
    try:
        names = U9TypeNames.from_file(filepath)
    except (U9FlxArchiveError, U9TypeNameError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    rows = _common._read_import_csv(args.csv, "type_id", "display_name")
    if rows is None:
        return 1
    changes = {
        type_id: value
        for type_id, value in rows.items()
        if (value or None) != names.name_for(type_id)
        or names.entry_for(type_id) is None
    }
    try:
        data = names.rebuilt(changes)
    except U9TypeNameError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    rebuilt = U9TypeNames(U9FlxArchive(data))
    for type_id, value in changes.items():
        if rebuilt.name_for(type_id) != (value or None):
            print(
                f"ERROR: type {type_id} did not read back as written", file=sys.stderr
            )
            return 1
    removed = sum(1 for value in changes.values() if not value)

    source = Path(filepath)
    output = args.output or str(
        source.with_name(f"{source.stem}_imported{source.suffix}")
    )
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "wb") as file:
        file.write(data)
    print(f"{filepath} — {len(rows)} row(s) read, {len(changes)} label(s) changed")
    if removed:
        print(f"  Removed : {removed} label(s) (empty display_name cells)")
    print(f"  Written : {output} ({len(data)} bytes, slot count {rebuilt.num_entries})")
    return 0


def cmd_types_csv(args: SimpleNamespace) -> int:
    """Export active ``TYPES.DAT`` records, or every physical slot, to CSV."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    typenames_path = getattr(args, "typenames", None)
    try:
        types = U9TypesDat.from_file(filepath)
        names = U9TypeNames.from_file(typenames_path) if typenames_path else None
    except (OSError, U9TypesDatError, U9FlxArchiveError, U9TypeNameError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    rows = types.slots if getattr(args, "all_slots", False) else types.records
    output = args.output or f"{Path(filepath).stem}_records.csv"
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "type_id",
                "slot_state",
                "display_name",
                "record_representation",
                "warnings",
                "active_type_count",
                "npc_type_count",
                "runtime_handler_pointer_cell",
                "runtime_handler_pointer_hex",
                "runtime_pointer_state",
                "base_type_id",
                "default_model_id",
                "object_flags",
                "object_flags_hex",
                "object_flag_names",
                "unmapped_object_flag_bits_hex",
                "mass_code",
                "can_drag",
                "can_inventory",
                "volume_code",
                "legacy_document_code",
                "durability_points",
                "runtime_handler_mask_cell",
                "runtime_handler_mask_hex",
                "raw_hex",
            ]
        )
        for record in rows:
            writer.writerow(
                [
                    record.type_id,
                    "active" if record.is_active else "inactive_capacity",
                    names.name_for(record.type_id) if names else "",
                    record.record_representation,
                    ";".join(record.warnings),
                    types.header.active_type_count,
                    types.header.npc_type_count,
                    record.runtime_handler_pointer_cell,
                    f"0x{record.runtime_handler_pointer_cell:08x}",
                    record.runtime_pointer_state,
                    record.base_type_id,
                    record.default_model_id,
                    record.object_flags,
                    f"0x{record.object_flags:04x}",
                    ";".join(record.object_flag_names),
                    f"0x{record.unmapped_object_flag_bits:04x}",
                    record.mass_code,
                    record.can_drag,
                    record.can_inventory,
                    record.volume_code,
                    record.legacy_document_code,
                    record.durability_points,
                    record.runtime_handler_mask_cell,
                    f"0x{record.runtime_handler_mask_cell:04x}",
                    f"0x{record.raw.hex()}",
                ]
            )
    print(f"{filepath} — wrote {len(rows)} type record row(s) -> {output}")
    return 0


def typename_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/TYPENAME.FLX")],
) -> None:
    """List named U9 object types with readable-text and icon references."""
    raise SystemExit(cmd_typename_dump(SimpleNamespace(file=file)))


def typename_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/TYPENAME.FLX")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="CSV output path"),
    ] = None,
) -> None:
    """Export complete U9 object-type display metadata to CSV."""
    raise SystemExit(cmd_typename_csv(SimpleNamespace(file=file, output=output)))


def typename_import_cmd(
    file: Annotated[
        str, typer.Argument(help="Original type-name archive (TYPENAME.FLX, Tnbrk.*)")
    ],
    csv_path: Annotated[
        str,
        typer.Argument(
            metavar="CSV", help="Edited typename-csv CSV (type_id, display_name)"
        ),
    ],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output archive (default: <stem>_imported<ext>)"
        ),
    ] = None,
) -> None:
    """Rebuild a U9 type-name archive with the labels from an edited CSV."""
    raise SystemExit(
        cmd_typename_import(SimpleNamespace(file=file, csv=csv_path, output=output))
    )


def types_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/TYPES.DAT")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="CSV output path"),
    ] = None,
    typenames: Annotated[
        Optional[str],
        typer.Option("--typenames", help="Optional static/TYPENAME.FLX labels"),
    ] = None,
    all_slots: Annotated[
        bool,
        typer.Option("--all-slots", help="Include inactive physical capacity slots"),
    ] = False,
) -> None:
    """Export the lossless U9 object-type table to CSV."""
    raise SystemExit(
        cmd_types_csv(
            SimpleNamespace(
                file=file,
                output=output,
                typenames=typenames,
                all_slots=all_slots,
            )
        )
    )
