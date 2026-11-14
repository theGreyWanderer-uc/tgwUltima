"""``titan u9 npc-*`` — NPC table commands."""

from __future__ import annotations

__all__ = [
    "npc_list_cmd",
    "npc_show_cmd",
    "npc_classes_cmd",
    "npc_diff_cmd",
    "npc_csv_cmd",
]

import csv
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.npc import NO_COMBAT_BEHAVIOR, U9NpcError, U9Npcs


def _npc_level_csv_columns(prefix: str) -> list[str]:
    return [
        f"{prefix}_code",
        f"{prefix}_status",
        f"{prefix}_raw_hex",
    ]


def _npc_level_status(value: int) -> str:
    return "" if -1 <= value <= 3 else "out_of_range"


def _npc_level_csv_values(value: int, raw: bytes) -> list[object]:
    return [
        value,
        _npc_level_status(value),
        f"0x{raw.hex()}",
    ]


def _format_npc_level(value: int, raw: bytes) -> str:
    status = _npc_level_status(value)
    suffix = f", {status}" if status else ""
    return f"{value} [signed i32, raw {raw.hex(' ')}{suffix}]"


def _load_npcs(filepath: str, from_save: bool) -> Optional[U9Npcs]:
    """Open runtime/NPC.FLX, or the live array inside a savegame file."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        if from_save:
            return U9Npcs.from_process_data(filepath)
        return U9Npcs.from_file(filepath)
    except U9NpcError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_npc_list(args: SimpleNamespace) -> int:
    """List NPC records; the record index is also the activity set index."""
    npcs = _load_npcs(args.file, args.save)
    if npcs is None:
        return 1

    rows = list(npcs)
    if args.region is not None:
        rows = [n for n in rows if n.region == args.region]
    if args.npc_class is not None:
        rows = [n for n in rows if n.combat_behavior_id == args.npc_class]
    if not args.all:
        rows = [n for n in rows if n.name]
    shown = rows[: args.limit] if args.limit else rows

    print(f"{args.file} -- {len(rows)} NPC(s) of {len(npcs)} record(s)")
    print(
        f"{'Idx':>5}  {'Name':<24} {'G':>1}  {'Behavior':>8}  {'Region':>6}  "
        f"{'HP':>5}  {'Mana':>5}  Position"
    )
    print("-" * 90)
    for n in shown:
        behavior = "-" if not n.has_combat_behavior else str(n.combat_behavior_id)
        print(
            f"{n.index:>5}  {n.name:<24} {'F' if n.is_female else 'M'}  "
            f"{behavior:>8}  {n.region:>6}  {n.health_bonus_maximum:>5}  "
            f"{n.mana_bonus_maximum:>5}  "
            f"{n.x},{n.y},{n.z}"
        )
    if args.limit and len(rows) > args.limit:
        print(f"... ({len(rows) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_npc_show(args: SimpleNamespace) -> int:
    """Print one NPC record's decoded fields."""
    npcs = _load_npcs(args.file, args.save)
    if npcs is None:
        return 1
    try:
        n = npcs.npc(args.index)
    except U9NpcError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"{args.file} -- NPC {n.index}")
    print(f"  Name        : {n.name!r}")
    print(f"  Gender      : {'female' if n.is_female else 'male'}")
    print(f"  Magic tier  : {n.magic_tier}")
    print(f"  Armor       : {n.armor_rating} (+{n.armor_modifier})")
    levels = {name: (value, raw) for name, value, raw in n.level_code_items}
    print(
        "  Core levels : "
        f"might {_format_npc_level(*levels['might'])}; "
        f"agility {_format_npc_level(*levels['agility'])}; "
        f"intellect {_format_npc_level(*levels['intellect'])}"
    )
    health_status = f" [{n.health_status}]" if n.health_status else ""
    print(
        f"  Health      : {n.health_current} / {n.health_bonus_maximum} "
        f"(base {n.health_base_maximum}){health_status}"
    )
    print(
        f"  Mana        : {n.mana_current} / {n.mana_bonus_maximum} "
        f"(base {n.mana_base_maximum})"
    )
    behavior = (
        f"{n.combat_behavior_id} ({n.combat_behavior_name})"
        if n.has_combat_behavior
        else "none (-1)"
    )
    movement = (
        f"{n.movement_behavior_id} ({n.movement_behavior_name})"
        if n.movement_behavior_name
        else f"none ({n.movement_behavior_id})"
    )
    print(f"  Behavior    : combat {behavior}, movement {movement}")
    weapon = n.active_weapon_category_name or "none"
    print(f"  Combat      : weapon {weapon}, hit sound {n.impact_material_name}")
    if n.known_spells:
        print(f"  Spells      : {', '.join(n.known_spell_names)}")
    print(f"  State flags : {int(n.state_flags):#010x}")
    print(f"  Trait flags : {int(n.trait_flags):#010x}")
    print(
        f"  Awareness   : radius {n.awareness_radius}, arc "
        f"{n.awareness_arc_degrees} deg, guaranteed "
        f"{n.guaranteed_awareness_percent}%"
    )
    print(f"  Region      : {n.region}")
    print(f"  Position    : {n.x}, {n.y}, {n.z}")
    print(f"  Scale       : {n.scale[0]}%, {n.scale[1]}%, {n.scale[2]}%")
    print(
        f"  Activities  : active {n.active_routine_id} arg "
        f"{n.active_routine_argument}; fallback {n.fallback_routine_id} arg "
        f"{n.fallback_routine_argument}; queued {n.queued_routine_id} arg "
        f"{n.queued_routine_argument}"
    )
    if n.routine_start_time or n.routine_end_time:
        print(
            f"  Routine time: {n.clock_time(n.routine_start_time)} to "
            f"{n.clock_time(n.routine_end_time)}"
        )
    print(f"  Equipment   : {n.equipped_object_offsets}")
    print(f"  Attachments : {n.model_attachment_ids}")
    print(
        "  Skill levels: "
        f"unarmed {_format_npc_level(*levels['unarmed_skill'])}; "
        f"one-handed {_format_npc_level(*levels['one_handed_skill'])}; "
        f"two-handed {_format_npc_level(*levels['two_handed_skill'])}; "
        f"blunt {_format_npc_level(*levels['blunt_skill'])}; "
        f"ranged {_format_npc_level(*levels['ranged_skill'])}"
    )
    if n.has_pool_object:
        print(
            f"  Pool handle : {n.pool_handle} (element {n.pool_index} of the region object pool)"
        )
    elif n.is_slot_used:
        print("  Pool handle : 1 -- slot allocated, no pool object yet")
    else:
        print("  Pool handle : 0 -- slot free / no world placement")
    print(f"  Record index {n.index} is also this NPC's activity set index.")
    print("  Reserved cells: exposed by offset-named fields and preserved in raw.")
    return 0


def cmd_npc_classes(args: SimpleNamespace) -> int:
    """Group NPCs by combat behavior profile (legacy command name)."""
    npcs = _load_npcs(args.file, args.save)
    if npcs is None:
        return 1

    histogram = npcs.combat_behavior_histogram()
    print(f"{args.file} -- {len(histogram)} distinct combat behavior value(s)")
    for behavior_id, count in histogram.most_common():
        group = npcs.by_combat_behavior(behavior_id)
        if behavior_id == NO_COMBAT_BEHAVIOR:
            label = "none (-1)"
        else:
            label = f"{behavior_id} {group[0].combat_behavior_name or '?'}"
        members = [n.name for n in group if n.name]
        preview = ", ".join(members[: args.members])
        if len(members) > args.members:
            preview += ", ..."
        print(f"  {label:>20}  x{count:<4} {preview}")
    return 0


def cmd_npc_csv(args: SimpleNamespace) -> int:
    """Export every NPC record to CSV: decoded fields, then the whole record as hex."""
    npcs = _load_npcs(args.file, args.save)
    if npcs is None:
        return 1

    rows = list(npcs)
    if not args.all:
        rows = [n for n in rows if n.name]

    out_path = args.output or f"{Path(args.file).stem}_npcs.csv"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    header = [
        "index",
        "name",
        "gender",
        "sex",
        "magic_tier",
        "armor_rating",
        "armor_modifier",
        *_npc_level_csv_columns("might"),
        *_npc_level_csv_columns("agility"),
        *_npc_level_csv_columns("intellect"),
        "health_current",
        "health_bonus_maximum",
        "health_base_maximum",
        "health_status",
        "health_raw_hex",
        "mana_current",
        "mana_bonus_maximum",
        "mana_base_maximum",
        "mana_raw_hex",
        "reserved_0x40",
        "residual_0x41_0x43_hex",
        "combat_behavior_id",
        "combat_behavior_name",
        "state_flags",
        "active_routine_id",
        "fallback_routine_id",
        "fallback_routine_argument",
        "magic_resistance_modifier",
        "route_search_workers",
        "awareness_radius",
        "awareness_arc_degrees",
        "guaranteed_awareness_percent",
        "region",
        "x",
        "y",
        "z",
        "position_tail_hex",
        "routine_stack_depth",
        "routine_step_index",
        "active_routine_argument",
        "scale_x",
        "scale_y",
        "scale_z",
        "reserved_0x6f",
        *[f"equipped_object_offset_{index}" for index in range(7)],
        *[f"model_attachment_id_{index}" for index in range(7)],
        "active_weapon_category_id",
        "active_weapon_category_name",
        "invulnerability_duration",
        "movement_behavior_id",
        "movement_behavior_name",
        "breath_current",
        "breath_bonus_maximum",
        "breath_base_maximum",
        "breath_raw_hex",
        "reserved_0xba_0xc3_hex",
        "trait_flags",
        "impact_material_id",
        "impact_material_name",
        "reserved_0xcc_0xdf_hex",
        "reserved_0xe0",
        "proximity_enter_radius",
        "proximity_exit_radius",
        "queued_routine_argument",
        "route_search_counter",
        "routine_end_time",
        "routine_end_clock",
        "routine_start_time",
        "routine_start_clock",
        "primary_routine_duration",
        "queued_routine_id",
        "secondary_routine_duration",
        "reserved_0xfc_0x10f_hex",
        "routine_stack_hex",
        "spellbook_flags_hex",
        "known_spells",
        *_npc_level_csv_columns("unarmed_skill"),
        *_npc_level_csv_columns("one_handed_skill"),
        *_npc_level_csv_columns("two_handed_skill"),
        *_npc_level_csv_columns("blunt_skill"),
        *_npc_level_csv_columns("ranged_skill"),
        "reserved_0x138_0x13b_hex",
        "pool_handle",
        "pool_index",
        "raw_hex",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for n in rows:
            levels = {name: (value, raw) for name, value, raw in n.level_code_items}
            writer.writerow(
                [
                    n.index,
                    n.name,
                    n.gender,
                    "female" if n.is_female else "male",
                    n.magic_tier,
                    n.armor_rating,
                    n.armor_modifier,
                    *_npc_level_csv_values(*levels["might"]),
                    *_npc_level_csv_values(*levels["agility"]),
                    *_npc_level_csv_values(*levels["intellect"]),
                    n.health_current,
                    n.health_bonus_maximum,
                    n.health_base_maximum,
                    n.health_status or "",
                    f"0x{n.health_raw.hex()}",
                    n.mana_current,
                    n.mana_bonus_maximum,
                    n.mana_base_maximum,
                    f"0x{n.mana_raw.hex()}",
                    n.reserved_0x40,
                    n.residual_0x41_0x43.hex(),
                    n.combat_behavior_id,
                    n.combat_behavior_name or "",
                    f"{int(n.state_flags):#010x}",
                    n.active_routine_id,
                    n.fallback_routine_id,
                    n.fallback_routine_argument,
                    n.magic_resistance_modifier,
                    n.route_search_workers,
                    n.awareness_radius,
                    n.awareness_arc_degrees,
                    n.guaranteed_awareness_percent,
                    n.region,
                    n.x,
                    n.y,
                    n.z,
                    n.position_tail.hex(),
                    n.routine_stack_depth,
                    n.routine_step_index,
                    n.active_routine_argument,
                    n.scale[0],
                    n.scale[1],
                    n.scale[2],
                    n.reserved_0x6f,
                    *n.equipped_object_offsets,
                    *n.model_attachment_ids,
                    n.active_weapon_category_id,
                    n.active_weapon_category_name or "",
                    n.invulnerability_duration,
                    n.movement_behavior_id,
                    n.movement_behavior_name or "",
                    n.breath_current,
                    n.breath_bonus_maximum,
                    n.breath_base_maximum,
                    f"0x{n.breath_raw.hex()}",
                    n.reserved_0xba_0xc3.hex(),
                    f"{int(n.trait_flags):#010x}",
                    n.impact_material_id,
                    n.impact_material_name or "",
                    n.reserved_0xcc_0xdf.hex(),
                    n.reserved_0xe0,
                    n.proximity_enter_radius,
                    n.proximity_exit_radius,
                    n.queued_routine_argument,
                    n.route_search_counter,
                    n.routine_end_time,
                    n.clock_time(n.routine_end_time),
                    n.routine_start_time,
                    n.clock_time(n.routine_start_time),
                    n.primary_routine_duration,
                    n.queued_routine_id,
                    n.secondary_routine_duration,
                    n.reserved_0xfc_0x10f.hex(),
                    n.routine_stack.hex(),
                    n.spellbook_flags.hex(),
                    " ".join(n.known_spell_names),
                    *_npc_level_csv_values(*levels["unarmed_skill"]),
                    *_npc_level_csv_values(*levels["one_handed_skill"]),
                    *_npc_level_csv_values(*levels["two_handed_skill"]),
                    *_npc_level_csv_values(*levels["blunt_skill"]),
                    *_npc_level_csv_values(*levels["ranged_skill"]),
                    n.reserved_0x138_0x13b.hex(),
                    n.pool_handle,
                    n.pool_index,
                    n.raw.hex(),
                ]
            )

    print(f"{args.file} -- wrote {len(rows)} NPC row(s) -> {out_path}")
    print(
        f"  {len(header)} columns; raw_hex carries the full {len(rows[0].raw) if rows else 0}-byte record"
    )
    out_of_range = [
        (npc.index, name, value)
        for npc in rows
        for name, value, _raw in npc.level_code_items
        if _npc_level_status(value)
    ]
    print(f"  Level codes outside -1..3: {len(out_of_range)}")
    if out_of_range:
        print(
            f"  WARNING: {len(out_of_range)} level code(s) marked out_of_range; "
            "see *_status columns"
        )
    health_flags = [npc for npc in rows if npc.health_status]
    if health_flags:
        print(
            f"  WARNING: {len(health_flags)} health record(s) flagged; "
            "see health_status"
        )
    if not args.all:
        blank = len(npcs) - len(rows)
        if blank:
            print(
                f"  {blank} unnamed/blank slot(s) omitted; pass --all to include them"
            )
    return 0


def cmd_npc_diff(args: SimpleNamespace) -> int:
    """Compare a shipped NPC table against a savegame's copy, field by field."""
    left = _load_npcs(args.file, False)
    right = _load_npcs(args.save_file, True)
    if left is None or right is None:
        return 1

    print(f"{args.file}\n{args.save_file}")
    print(f"  {len(left)} authored record(s) vs {len(right)} live record(s)")
    if len(right) > len(left):
        spawned = [n.name for n in list(right)[len(left) :] if n.name]
        print(
            f"  {len(right) - len(left)} extra live slot(s), {len(spawned)} named "
            f"(runtime-spawned): {', '.join(spawned[:8])}"
            + (", ..." if len(spawned) > 8 else "")
        )

    changed = left.changed_fields(right)
    print(f"  {len(changed)} byte offset(s) differ across the shared records:")
    for offset, count in changed.items():
        print(f"      {offset:#06x}  {count} NPC(s)")

    moved = [
        (a, b)
        for a, b in zip(left, right)
        if (a.region, a.x, a.y, a.z) != (b.region, b.x, b.y, b.z)
    ]
    print(f"  {len(moved)} NPC(s) moved:")
    for a, b in moved[: args.limit or len(moved)]:
        print(
            f"      {a.name:<16} region {a.region} {a.x},{a.y},{a.z}"
            f"  ->  region {b.region} {b.x},{b.y},{b.z}"
        )
    return 0


def npc_list_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save"),
    ],
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Read the live array from a savegame processes.dat / .sav",
        ),
    ] = False,
    region: Annotated[
        Optional[int],
        typer.Option("-r", "--region", help="Only NPCs in this region"),
    ] = None,
    npc_class: Annotated[
        Optional[int],
        typer.Option(
            "-b",
            "--behavior-profile",
            "--class",
            help="Only NPCs with this combat behavior profile",
        ),
    ] = None,
    all: Annotated[
        bool, typer.Option("-a", "--all", help="Include unnamed/empty slots")
    ] = False,
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum rows to print")
    ] = None,
) -> None:
    """List U9 NPC records; the record index is also the activity set index."""
    raise SystemExit(
        cmd_npc_list(
            SimpleNamespace(
                file=file,
                save=save,
                region=region,
                npc_class=npc_class,
                all=all,
                limit=limit,
            )
        )
    )


def npc_show_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save"),
    ],
    index: Annotated[int, typer.Argument(help="NPC record index")],
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Read the live array from a savegame processes.dat / .sav",
        ),
    ] = False,
) -> None:
    """Print one U9 NPC record's decoded fields."""
    raise SystemExit(cmd_npc_show(SimpleNamespace(file=file, index=index, save=save)))


def npc_classes_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save"),
    ],
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Read the live array from a savegame processes.dat / .sav",
        ),
    ] = False,
    members: Annotated[
        int,
        typer.Option("-m", "--members", help="Member names to preview per profile"),
    ] = 8,
) -> None:
    """Group U9 NPCs by combat behavior profile (legacy command name)."""
    raise SystemExit(
        cmd_npc_classes(SimpleNamespace(file=file, save=save, members=members))
    )


def npc_diff_cmd(
    file: Annotated[str, typer.Argument(help="Path to the shipped runtime/NPC.FLX")],
    save_file: Annotated[
        str, typer.Argument(help="Path to a savegame processes.dat or u9game*.sav")
    ],
    limit: Annotated[
        Optional[int], typer.Option("-n", "--limit", help="Maximum moved NPCs to print")
    ] = None,
) -> None:
    """Compare the shipped U9 NPC table against a savegame's live copy."""
    raise SystemExit(
        cmd_npc_diff(SimpleNamespace(file=file, save_file=save_file, limit=limit))
    )


def npc_csv_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to runtime/NPC.FLX, or a savegame file with --save"),
    ],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output CSV path (default: <file>_npcs.csv)"
        ),
    ] = None,
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Read the live array from a savegame processes.dat / .sav",
        ),
    ] = False,
    all: Annotated[
        bool, typer.Option("-a", "--all", help="Include unnamed/blank slots")
    ] = False,
) -> None:
    """Export every U9 NPC record to CSV, decoded fields plus the raw record."""
    raise SystemExit(
        cmd_npc_csv(SimpleNamespace(file=file, output=output, save=save, all=all))
    )
