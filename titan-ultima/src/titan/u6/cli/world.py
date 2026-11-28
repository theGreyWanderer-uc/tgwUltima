"""``titan u6`` object, egg, actor, game-state, flag and schedule commands."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._meta import meta
from titan.u6.actor import U6Actors
from titan.u6.cli._common import (
    _require_gamedir,
)
from titan.u6.flags import (
    compare_flags,
    read_talk_flags,
    set_gargish_flag,
    set_quest_flag,
    set_talk_flag,
)
from titan.u6.gamestate import U6GameState
from titan.u6.look import U6ObjectNames
from titan.u6.object import U6WorldObjects, read_basetile
from titan.u6.schedule import U6Schedules


def _load_objlist_from_source(source: str) -> bytes:
    """Load objlist bytes from either a real save's SAVEGAME/ folder or a fresh gamedir, auto-detected."""
    if os.path.isfile(os.path.join(source, "OBJLIST")):
        return U6WorldObjects.from_savegame(source).objlist_tail
    if os.path.isfile(os.path.join(source, "LZDNGBLK")):
        return U6WorldObjects.from_directory(source).objlist_tail
    print(
        f"ERROR: {source} is neither a save's SAVEGAME folder (needs OBJLIST) "
        "nor a fresh gamedir (needs LZDNGBLK)",
        file=sys.stderr,
    )
    raise SystemExit(1)


def cmd_object_list(args: SimpleNamespace) -> int:
    """List world objects in a surface block or dungeon level."""
    gamedir = _require_gamedir(args.gamedir)
    for name in ("LZOBJBLK", "LZDNGBLK"):
        if not os.path.isfile(os.path.join(gamedir, name)):
            raise FileNotFoundError(
                f"Required file not found: {os.path.join(gamedir, name)}"
            )

    world = U6WorldObjects.from_directory(gamedir)

    if args.dungeon is not None:
        if args.dungeon < 0 or args.dungeon > 4:
            print("ERROR: --dungeon must be 0-4", file=sys.stderr)
            return 1
        objs = world.dungeon_objects[args.dungeon]
        label = f"dungeon {args.dungeon}"
    elif args.block is not None:
        if args.block < 0 or args.block >= len(world.surface_objects):
            print(
                f"ERROR: --block must be 0-{len(world.surface_objects) - 1}",
                file=sys.stderr,
            )
            return 1
        objs = world.surface_objects[args.block]
        label = f"surface block {args.block}"
    else:
        objs = list(world.iter_surface())
        label = "all surface blocks"

    print(f"{label}: {len(objs)} top-level object(s)")
    print(
        f"{'X':>5} {'Y':>5} {'Z':>2}  {'ObjN':>5} {'Frm':>3}  {'Qty':>4} {'Qual':>4}  {'Flags':<16} Contains"
    )
    print("-" * 78)
    for o in objs[: args.limit]:
        flags = []
        if o.is_ok_to_take:
            flags.append("take")
        if o.is_invisible:
            flags.append("invis")
        if o.is_temporary:
            flags.append("temp")
        if o.is_lit:
            flags.append("lit")
        print(
            f"{o.x:>5} {o.y:>5} {o.z:>2}  {o.obj_n:>5} {o.frame_n:>3}  {o.qty:>4} {o.quality:>4}  "
            f"{','.join(flags) or '-':<16} {len(o.contains)}"
        )
    if len(objs) > args.limit:
        print(
            f"... ({len(objs) - args.limit} more not shown; increase --limit to see more)"
        )
    return 0


def cmd_egg_list(args: SimpleNamespace) -> int:
    """List every egg (object spawner) in a surface block or dungeon level, with what it spawns."""
    gamedir = _require_gamedir(args.gamedir)
    for name in ("LZOBJBLK", "LZDNGBLK", "BASETILE", "LOOK.LZD"):
        if not os.path.isfile(os.path.join(gamedir, name)):
            raise FileNotFoundError(
                f"Required file not found: {os.path.join(gamedir, name)}"
            )

    world = U6WorldObjects.from_directory(gamedir)
    basetile = read_basetile(os.path.join(gamedir, "BASETILE"))
    names = U6ObjectNames.from_file(os.path.join(gamedir, "LOOK.LZD"))

    if args.dungeon is not None:
        if args.dungeon < 0 or args.dungeon > 4:
            print("ERROR: --dungeon must be 0-4", file=sys.stderr)
            return 1
        objs = world.dungeon_objects[args.dungeon]
        label = f"dungeon {args.dungeon}"
    elif args.block is not None:
        if args.block < 0 or args.block >= len(world.surface_objects):
            print(
                f"ERROR: --block must be 0-{len(world.surface_objects) - 1}",
                file=sys.stderr,
            )
            return 1
        objs = world.surface_objects[args.block]
        label = f"surface block {args.block}"
    else:
        objs = list(world.iter_surface())
        label = "all surface blocks"

    eggs = [o for o in objs if o.is_egg]
    print(f"{label}: {len(eggs)} egg(s)")
    print(
        f"{'X':>5} {'Y':>5} {'Z':>2}  {'Chance':>6}  {'Spawns':<20} {'Max':>3}  {'Qual':>4}"
    )
    print("-" * 60)
    for egg in eggs[: args.limit]:
        target = egg.spawn_target
        if target is None:
            print(
                f"{egg.x:>5} {egg.y:>5} {egg.z:>2}  {egg.spawn_probability:>5}%  (no spawn target)"
            )
            continue
        tnum = target.tile_num(basetile)
        name = names.get_name(tnum) or "?"
        print(
            f"{egg.x:>5} {egg.y:>5} {egg.z:>2}  {egg.spawn_probability:>5}%  {name:<20} {target.qty:>3}  {target.quality:>4}"
        )
    if len(eggs) > args.limit:
        print(
            f"... ({len(eggs) - args.limit} more not shown; increase --limit to see more)"
        )
    return 0


def cmd_actor_list(args: SimpleNamespace) -> int:
    """List the NPC/actor identity table (position, appearance, stats)."""
    gamedir = _require_gamedir(args.gamedir)
    if not os.path.isfile(os.path.join(gamedir, "LZDNGBLK")):
        raise FileNotFoundError(
            f"Required file not found: {os.path.join(gamedir, 'LZDNGBLK')}"
        )

    world = U6WorldObjects.from_directory(gamedir)
    actors = U6Actors.parse(world.objlist_tail)

    if not args.all:
        actors = [a for a in actors if a.is_active]

    print(
        f"{len(actors)} actor(s) {'(all 256 slots)' if args.all else '(active only; use --all for every slot)'}"
    )
    print(
        f"{'ID':>4}  {'X':>5} {'Y':>5} {'Z':>2}  {'ObjN':>5} {'Frm':>3}  "
        f"{'STR':>3} {'DEX':>3} {'INT':>3} {'HP':>4} {'Lvl':>3}  {'Algn':>4}"
    )
    print("-" * 68)
    for a in actors:
        print(
            f"{a.actor_id:>4}  {a.x:>5} {a.y:>5} {a.z:>2}  {a.obj_n:>5} {a.frame_n:>3}  "
            f"{a.strength:>3} {a.dexterity:>3} {a.intelligence:>3} {a.hp:>4} {a.level:>3}  {a.alignment:>4}"
        )
    return 0


def cmd_gamestate_dump(args: SimpleNamespace) -> int:
    """Show party roster, player state, and game clock/weather from objlist."""
    gamedir = _require_gamedir(args.gamedir)
    if not os.path.isfile(os.path.join(gamedir, "LZDNGBLK")):
        raise FileNotFoundError(
            f"Required file not found: {os.path.join(gamedir, 'LZDNGBLK')}"
        )

    world = U6WorldObjects.from_directory(gamedir)
    state = U6GameState.parse(world.objlist_tail)

    print(
        f"Date: {state.clock.date_string()}   Time: {state.clock.time_string()}   "
        f"Rest counter: {state.clock.rest_counter}"
    )
    print(f"Wind: {state.wind_direction or 'calm'}")
    print(
        f"Karma: {state.player.karma}   Alcohol: {state.player.alcohol}   "
        f"Gender: {state.player.gender_word}   Knows Gargish: {state.player.knows_gargish}   "
        f"Quest flag: {state.player.quest_flag}"
    )
    if state.player.solo_mode:
        print(f"Solo mode: party-roster index {state.player.solo_member_index}")
    else:
        print("Solo mode: off (full party active)")

    print(
        f"\nParty ({state.party.num_members} member(s), "
        f"combat mode {'on' if state.party.in_combat_mode else 'off'}):"
    )
    print(f"{'#':>3}  {'Name':<14} {'Actor ID':>8}")
    print("-" * 30)
    for i, member in enumerate(state.party.members):
        print(f"{i:>3}  {member.name:<14} {member.actor_id:>8}")
    return 0


def cmd_flags_dump(args: SimpleNamespace) -> int:
    """Dump every actor's talk_flags plus quest_flag/knows_gargish from a gamedir or SAVEGAME folder."""
    objlist = _load_objlist_from_source(args.source)
    flags = read_talk_flags(objlist)
    state = U6GameState.parse(objlist)

    print(
        f"Quest flag: {state.player.quest_flag}   Knows Gargish: {state.player.knows_gargish}"
    )
    print()
    print(f"{'Actor':>5}  {'Flags':<8} Bits set")
    print("-" * 40)
    for actor_id in range(len(flags)):
        value = flags[actor_id]
        if not args.all and value == 0:
            continue
        bits = [str(i) for i in range(8) if value & (1 << i)]
        print(f"{actor_id:>5}  0b{value:08b}  {','.join(bits) or '-'}")
    return 0


def cmd_flags_compare(args: SimpleNamespace) -> int:
    """Diff story-flag state (talk_flags, quest_flag, knows_gargish) between two gamedirs/SAVEGAME folders."""
    objlist_a = _load_objlist_from_source(args.source_a)
    objlist_b = _load_objlist_from_source(args.source_b)
    diffs = compare_flags(objlist_a, objlist_b)

    if not diffs:
        print("No differences.")
        return 0
    print(f"{len(diffs)} difference(s):")
    for d in diffs:
        print(f"  {d}")
    return 0


def cmd_flags_set(args: SimpleNamespace) -> int:
    """Set/clear one actor's talk flag, or the quest/gargish global flag, in a save's OBJLIST."""
    objlist_path = os.path.join(args.savegame, "OBJLIST")
    if not os.path.isfile(objlist_path):
        raise FileNotFoundError(f"Required file not found: {objlist_path}")

    with open(objlist_path, "rb") as f:
        data = bytearray(f.read())

    if args.actor is not None:
        if args.flag is None or args.value is None:
            print("ERROR: --actor requires --flag and --value", file=sys.stderr)
            return 1
        set_talk_flag(data, args.actor, args.flag, bool(args.value))
        desc = f"actor {args.actor} talk_flag bit {args.flag} -> {bool(args.value)}"
    elif args.quest_flag is not None:
        set_quest_flag(data, args.quest_flag)
        desc = f"quest_flag -> {args.quest_flag}"
    elif args.gargish is not None:
        set_gargish_flag(data, bool(args.gargish))
        desc = f"knows_gargish -> {bool(args.gargish)}"
    else:
        print(
            "ERROR: specify --actor/--flag/--value, --quest-flag, or --gargish",
            file=sys.stderr,
        )
        return 1

    if args.in_place and not args.output:
        backup_path = objlist_path + ".bak"
        if not os.path.isfile(backup_path):
            with open(objlist_path, "rb") as f:
                original = f.read()
            with open(backup_path, "wb") as f:
                f.write(original)
            print(f"Backed up original -> {backup_path}")
        out_path = objlist_path
    else:
        out_path = args.output or objlist_path + ".new"

    with open(out_path, "wb") as f:
        f.write(data)
    print(f"Set {desc}")
    print(f"Wrote: {out_path}")
    return 0


def cmd_schedule_dump(args: SimpleNamespace) -> int:
    """Dump one or all actors' schedules from SCHEDULE."""
    filepath = args.file
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    schedules = U6Schedules.from_file(filepath)
    actor_ids = (
        [args.actor] if args.actor is not None else range(len(schedules.per_actor))
    )

    outdir = args.output
    lines: list[str] = []
    for actor_id in actor_ids:
        if actor_id < 0 or actor_id >= len(schedules.per_actor):
            print(
                f"ERROR: Actor {actor_id} out of range (0..{len(schedules.per_actor) - 1})",
                file=sys.stderr,
            )
            return 1
        entries = schedules.for_actor(actor_id)
        if not entries:
            continue
        lines.append(f"--- actor {actor_id}: {len(entries)} entries ---")
        lines.append(
            f"{'Hour':>4} {'Day':>3}  {'Worktype':>8}  {'X':>5} {'Y':>5} {'Z':>2}"
        )
        for e in entries:
            lines.append(
                f"{e.hour:>4} {e.day_of_week:>3}  {e.worktype:>8}  {e.x:>5} {e.y:>5} {e.z:>2}"
            )

    text = "\n".join(lines)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
        out_path = os.path.join(outdir, "schedule_dump.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"Dumped schedules for {len(actor_ids)} actor(s) -> {out_path}")
    else:
        print(text)
    return 0


@meta(category="world", results=("text",))
def object_list_cmd(
    gamedir: Annotated[
        Optional[str], typer.Option("-g", "--game-dir", help="U6 game directory")
    ] = None,
    block: Annotated[
        Optional[int],
        typer.Option("--block", help="Surface superchunk block number (0-63)"),
    ] = None,
    dungeon: Annotated[
        Optional[int],
        typer.Option(
            "--dungeon", help="Dungeon level (0-4) instead of a surface block"
        ),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows to print")] = 200,
) -> None:
    """List world objects in a surface block or dungeon level."""
    raise SystemExit(
        cmd_object_list(
            SimpleNamespace(gamedir=gamedir, block=block, dungeon=dungeon, limit=limit)
        )
    )


@meta(category="world", results=("text",))
def egg_list_cmd(
    gamedir: Annotated[
        Optional[str], typer.Option("-g", "--game-dir", help="U6 game directory")
    ] = None,
    block: Annotated[
        Optional[int],
        typer.Option("--block", help="Surface superchunk block number (0-63)"),
    ] = None,
    dungeon: Annotated[
        Optional[int],
        typer.Option(
            "--dungeon", help="Dungeon level (0-4) instead of a surface block"
        ),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max rows to print")] = 200,
) -> None:
    """List every egg (object spawner) in a surface block or dungeon level, with what it spawns."""
    raise SystemExit(
        cmd_egg_list(
            SimpleNamespace(gamedir=gamedir, block=block, dungeon=dungeon, limit=limit)
        )
    )


@meta(category="characters", results=("text",))
def actor_list_cmd(
    gamedir: Annotated[
        Optional[str], typer.Option("-g", "--game-dir", help="U6 game directory")
    ] = None,
    all: Annotated[
        bool,
        typer.Option(
            "--all", help="Show all 256 actor slots, including inactive/unused ones"
        ),
    ] = False,
) -> None:
    """List the NPC/actor identity table (position, appearance, stats)."""
    raise SystemExit(cmd_actor_list(SimpleNamespace(gamedir=gamedir, all=all)))


@meta(category="saves", results=("text",))
def gamestate_dump_cmd(
    gamedir: Annotated[
        Optional[str], typer.Option("-g", "--game-dir", help="U6 game directory")
    ] = None,
) -> None:
    """Show party roster, player state, and game clock/weather from objlist."""
    raise SystemExit(cmd_gamestate_dump(SimpleNamespace(gamedir=gamedir)))


@meta(category="saves", results=("text",), params={"source": "input-dir"})
def flags_dump_cmd(
    source: Annotated[
        str,
        typer.Argument(
            help="A gamedir (LZDNGBLK) or a save's SAVEGAME folder (OBJLIST)"
        ),
    ],
    all: Annotated[
        bool,
        typer.Option("--all", help="Show every actor, including all-zero talk_flags"),
    ] = False,
) -> None:
    """Dump every actor's talk_flags plus quest_flag/knows_gargish."""
    raise SystemExit(cmd_flags_dump(SimpleNamespace(source=source, all=all)))


@meta(
    category="saves",
    results=("text",),
    params={"source_a": "input-dir", "source_b": "input-dir"},
)
def flags_compare_cmd(
    source_a: Annotated[str, typer.Argument(help="First gamedir or SAVEGAME folder")],
    source_b: Annotated[str, typer.Argument(help="Second gamedir or SAVEGAME folder")],
) -> None:
    """Diff story-flag state (talk_flags, quest_flag, knows_gargish) between two sources."""
    raise SystemExit(
        cmd_flags_compare(SimpleNamespace(source_a=source_a, source_b=source_b))
    )


@meta(
    category="saves",
    results=("file",),
    params={"output": "output-file", "savegame": "save"},
)
def flags_set_cmd(
    savegame: Annotated[
        str, typer.Argument(help="A save's SAVEGAME folder (containing OBJLIST)")
    ],
    actor: Annotated[
        Optional[int],
        typer.Option("--actor", help="Actor ID (0-255) whose talk flag to set"),
    ] = None,
    flag: Annotated[
        Optional[int],
        typer.Option("--flag", help="Talk-flag bit index (0-7); requires --actor"),
    ] = None,
    value: Annotated[
        Optional[int],
        typer.Option("--value", help="0 to clear, 1 to set; requires --actor/--flag"),
    ] = None,
    quest_flag: Annotated[
        Optional[int],
        typer.Option("--quest-flag", help="Set the global quest_flag byte"),
    ] = None,
    gargish: Annotated[
        Optional[int],
        typer.Option("--gargish", help="0/1: set whether the player knows Gargish"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Write the modified OBJLIST here instead of alongside the original",
        ),
    ] = None,
    in_place: Annotated[
        bool,
        typer.Option(
            "--in-place",
            help="Overwrite the save's own OBJLIST (backed up to OBJLIST.bak first)",
        ),
    ] = False,
) -> None:
    """Set/clear one actor's talk flag, or the quest/gargish global flag, in a save's OBJLIST."""
    raise SystemExit(
        cmd_flags_set(
            SimpleNamespace(
                savegame=savegame,
                actor=actor,
                flag=flag,
                value=value,
                quest_flag=quest_flag,
                gargish=gargish,
                output=output,
                in_place=in_place,
            )
        )
    )


@meta(
    category="characters",
    results=("files",),
    params={"output": "output-dir", "file": "install-file"},
    resources={"file": "schedule"},
)
def schedule_dump_cmd(
    file: Annotated[str, typer.Argument(help="Path to SCHEDULE")],
    actor: Annotated[
        Optional[int],
        typer.Option(
            "--actor",
            help="Single actor ID (0-255); default: every actor with a schedule",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output-dir", help="Output directory; omit to print to stdout"
        ),
    ] = None,
) -> None:
    """Dump one or all actors' schedules from SCHEDULE."""
    raise SystemExit(
        cmd_schedule_dump(SimpleNamespace(file=file, actor=actor, output=output))
    )
