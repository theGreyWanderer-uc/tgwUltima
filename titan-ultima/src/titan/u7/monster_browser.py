"""Read-only monster definitions, saved actors, equipment and spawn browsing."""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from titan import _wizard_ui as ui
from titan._terminal_image import play_terminal, terminal_image
from titan.u7 import npc_browser as npc_ui
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.eggs import EggQueryParams, query_eggs
from titan.u7.install import existing_path
from titan.u7.monster import (
    U7MonsterDefinition,
    U7MonsterDefinitions,
    U7MonsterEquipment,
    U7WeaponInfos,
    live_monsters_csv,
    monster_equipment_rows_from_data,
)
from titan.u7.names import U7ShapeNames
from titan.u7.save import U7Identity, U7NPC, U7NPCData, U7ReadyTypes, U7Save
from titan.u7.shape_archive import find_archive
from titan.u7.shape_browser import ShapeLibrary, load_library, playback_provider
from titan.u7.target_picker import game_targets, select_target
from titan.u7.typeflag import U7TypeFlags
from titan.u7.world import WorldQueryParams, load_query_metadata

PAGE_SIZE = npc_ui.PAGE_SIZE
READ_ERRORS = npc_ui.READ_ERRORS
clean = npc_ui.clean
menu = npc_ui._menu
IREG_NAME = re.compile(r"(?:(map[0-9a-f]{2})/)?(u7ireg[0-9a-f]{2})", re.IGNORECASE)


@dataclass(frozen=True)
class MonsterEntry:
    number: int  # Shape number for definitions; source record index for actors.
    shape: int
    definition: U7MonsterDefinition | None = None
    actor: U7NPC | None = None


@dataclass
class Session(npc_ui.Session):
    definitions: U7MonsterDefinitions = field(
        default_factory=lambda: U7MonsterDefinitions([])
    )
    equipment: U7MonsterEquipment | None = None
    equipment_rows: list[dict[str, object]] = field(default_factory=list)
    typeflags: U7TypeFlags = field(default_factory=lambda: U7TypeFlags.parse(b""))
    records: list[MonsterEntry] = field(default_factory=list)
    archive: U7Save | None = field(default=None, repr=False)
    spawn_cache: dict[int, list[dict[str, object]]] = field(default_factory=dict)
    world_matches: bool = True

    def name(self, entry: MonsterEntry) -> str:
        return clean(
            (entry.actor.name if entry.actor else "")
            or (self.names.get(entry.shape) if self.names else "")
            or "(unnamed)"
        )

    def overview(self) -> str:
        lines = [
            f"World: {clean(self.target.name)} ({self.game})",
            f"Source: {self.source.path} ({self.source.kind}; {self.format})",
            f"View: {'definitions' if self.source.kind == 'definitions' else 'saved/live monster instances'}",
            f"Monsters: {len(self.records)}; resolved definitions: {len(self.definitions.records)}",
        ]
        if self.title:
            lines.append(f"Save title: {clean(self.title)}")
        if self.identity:
            lines.append(f"Identity: {clean(self.identity)}")
        lines.append(
            f"Spawn equipment: {self.equipment.source_file if self.equipment else 'unavailable'}"
        )
        lines.extend(f"WARNING: {clean(warning)}" for warning in self.warnings)
        return "\n".join(lines)


def _definitions(
    target: ArchiveTarget, source: npc_ui.Source, game: str
) -> U7MonsterDefinitions:
    base = find_archive(target.static, "MONSTERS.DAT") if target.static else None
    patch = find_archive(target.patch, "MONSTERS.DAT")
    paths = list(dict.fromkeys(p for p in (base, patch) if p))
    if (
        source.kind == "definitions"
        and source.path.is_file()
        and source.path not in paths
    ):
        # An explicitly selected foreign file must not silently inherit retail data.
        paths = [source.path]
    merged = U7MonsterDefinitions([])
    for path in paths:
        data = path.read_bytes()
        if len(data) % 25 not in {0, 1}:
            raise ValueError(f"Incomplete MONSTERS.DAT record: {path}")
        parsed = U7MonsterDefinitions.from_bytes(data, str(path), game)
        merged = U7MonsterDefinitions.merge(merged, parsed)
    return merged


def _counted_records(data: bytes, stride: int, name: str) -> None:
    """The existing readers tolerate partial tables; report those explicitly."""
    if not data:
        raise ValueError(f"{name} header is incomplete")
    header, count = 1, data[0]
    if count == 255:
        if len(data) < 3:
            raise ValueError(f"{name} extended count is incomplete")
        header, count = 3, int.from_bytes(data[1:3], "little")
    if len(data) < header + count * stride:
        raise ValueError(f"{name} entries are incomplete")


def _metadata(session: Session) -> tuple[set[int] | None, int | None]:
    target = session.target
    containers, shape_count = None, None
    if target.static is not None:
        try:
            session.typeflags, session.names, _, count = load_query_metadata(
                WorldQueryParams(
                    static_dir=str(target.static),
                    base_static=str(target.static),
                    patch_dir=str(target.patch) if target.patch.is_dir() else None,
                    game=session.game,
                )
            )
            if count:
                containers = {
                    entry.shape_num
                    for entry in session.typeflags.entries[:count]
                    if entry.shape_class == U7TypeFlags.SHAPE_CLASS_CONTAINER
                }
        except READ_ERRORS as error:
            session.warnings.append(f"World item metadata unavailable: {error}")
    if session.names is None:
        session.warnings.append("Item names unavailable; numeric shape IDs are shown.")
    if containers is None:
        session.warnings.append(
            "Container classes unavailable; inventory nesting uses reader heuristics."
        )
    try:
        from titan.u7.shape_archive import U7ShapeArchive

        path = npc_ui.owner_file(target, "SHAPES.VGA")
        base = find_archive(target.static, "SHAPES.VGA") if target.static else None
        if path:
            shapes = U7ShapeArchive.from_file(
                str(path),
                base_archive=str(base) if base and base != path else None,
                infer_base=False,
                strict=True,
            )
            shape_count = len(shapes.effective.records)
    except READ_ERRORS as error:
        session.warnings.append(f"Shape bounds unavailable: {error}")
    ready = npc_ui.owner_file(target, "READY.DAT")
    if ready:
        try:
            session.ready = U7ReadyTypes.from_file(str(ready), game=session.game)
        except READ_ERRORS as error:
            session.warnings.append(f"Ready-slot preferences unavailable: {error}")
    return containers, shape_count


def _equipment(session: Session) -> None:
    path = npc_ui.owner_file(session.target, "EQUIP.DAT")
    if path is None:
        session.warnings.append(
            "EQUIP.DAT unavailable; possible spawn equipment is unknown."
        )
        return
    try:
        blob = path.read_bytes()
        _counted_records(blob, 60, "EQUIP.DAT")
        session.equipment = U7MonsterEquipment.from_bytes(blob, str(path))
    except READ_ERRORS as error:
        session.warnings.append(f"Possible equipment unavailable: {error}")
        return
    weapons = U7WeaponInfos({})
    paths = list(
        dict.fromkeys(
            p
            for p in (
                find_archive(session.target.static, "WEAPONS.DAT")
                if session.target.static
                else None,
                find_archive(session.target.patch, "WEAPONS.DAT"),
            )
            if p
        )
    )
    for weapon_path in paths:
        try:
            blob = weapon_path.read_bytes()
            _counted_records(blob, 21, "WEAPONS.DAT")
            weapons = U7WeaponInfos.merge(weapons, U7WeaponInfos.from_bytes(blob))
        except READ_ERRORS as error:
            session.warnings.append(
                f"Generated ammunition metadata unavailable: {error}"
            )
            weapons = U7WeaponInfos({})
            break
    if not paths:
        session.warnings.append(
            "WEAPONS.DAT unavailable; generated ammunition is unknown."
        )
    session.equipment_rows = monster_equipment_rows_from_data(
        session.definitions,
        session.equipment,
        weapons,
        session.names or U7ShapeNames([]),
        session.typeflags,
    )


def load_session(target: ArchiveTarget, source: npc_ui.Source, game: str) -> Session:
    path = existing_path(source.path.expanduser()).absolute()
    if not path.exists():
        raise ValueError(f"Source not found: {path}")
    source = npc_ui.Source(path, source.kind)
    session = Session(target, source, game=game)
    blob = None
    if source.kind != "definitions":
        if path.is_dir() or path.name.casefold() == "monsnpcs.dat":
            mon_path = find_archive(path, "MONSNPCS.DAT") if path.is_dir() else path
            if not path.exists():
                raise ValueError(f"Source not found: {path}")
            session.format = "directory" if path.is_dir() else "loose monster file"
            blob = mon_path.read_bytes() if mon_path else None
            identity = find_archive(path if path.is_dir() else path.parent, "identity")
            if identity:
                session.identity = U7Identity.from_bytes(identity.read_bytes()).game
        else:
            session.archive = U7Save.from_file(str(path))
            session.title, session.format = (
                session.archive.title,
                session.archive.container_format,
            )
            blob = session.archive.get_data("monsnpcs.dat")
            identity_blob = session.archive.get_data("identity")
            if identity_blob:
                session.identity = U7Identity.from_bytes(identity_blob).game
    else:
        session.format = "world metadata" if path.is_dir() else "definition file"
    known = {
        "BLACKGATE": "bg",
        "FORGEOFVIRTUE": "bg",
        "SERPENTISLE": "si",
        "SILVERSEED": "si",
    }
    identity_key = session.identity.upper().replace(" ", "")
    mismatch = identity_key in known and known[identity_key] != game
    containers, shape_count = None, None
    if mismatch:
        session.world_matches = False
        session.warnings.append(
            "Stored identity differs from the selected BG/SI flavour; world definitions, item metadata and artwork are disabled. Choose the matching world."
        )
        session.preview_error = "Choose the world matching this save's game identity."
    else:
        containers, shape_count = _metadata(session)
        try:
            session.definitions = _definitions(target, source, game)
        except READ_ERRORS as error:
            session.warnings.append(f"Monster definitions unavailable: {error}")
        if not session.definitions.records:
            session.warnings.append(
                "No active monster definitions found for this source."
            )
        _equipment(session)
    if source.kind == "definitions":
        session.records = [
            MonsterEntry(d.shape, d.shape, d) for d in session.definitions.records
        ]
    elif blob is None:
        session.warnings.append(
            "monsnpcs.dat is not present in this source; no monsters are inherited from other saves or GAMEDAT."
        )
    else:
        session.npcs = U7NPCData.from_monsnpcs_bytes(blob, containers, shape_count)
        expected = session.npcs.num_npcs1
        if (
            len(session.npcs.npcs) != expected
            or session.npcs._parsed_bytes > len(blob) + 2
        ):
            session.warnings.append(
                f"monsnpcs.dat is partial: parsed {len(session.npcs.npcs)} of {expected} declared monsters; the final record may be incomplete."
            )
        definitions = session.definitions.by_shape()
        session.records = [
            MonsterEntry(i, actor.shape, definitions.get(actor.shape), actor)
            for i, actor in enumerate(session.npcs.npcs)
        ]
    return session


def filter_entries(
    session: Session, query: str = "", mode: str = "all"
) -> list[MonsterEntry]:
    query = query.strip().casefold()
    number = None
    by_instance = query.startswith("#")
    try:
        number = int(
            query[1:] if by_instance else query, 16 if query.startswith("0x") else 10
        )
    except ValueError:
        pass
    matches = []
    for entry in session.records:
        alignment = (
            entry.actor.alignment_name
            if entry.actor
            else entry.definition.alignment_name
            if entry.definition
            else ""
        )
        if mode in {"good", "evil", "neutral", "chaotic"} and alignment != mode:
            continue
        if mode == "alive" and (entry.actor is None or entry.actor.is_dead):
            continue
        if mode == "dead" and (entry.actor is None or not entry.actor.is_dead):
            continue
        if query:
            if number is not None:
                if (entry.number if by_instance else entry.shape) != number:
                    continue
            elif query not in session.name(entry).casefold():
                continue
        matches.append(entry)
    return matches


def definition_detail(definition: U7MonsterDefinition) -> str:
    abilities = [
        label
        for flag, label in (
            (definition.can_teleport, "teleport"),
            (definition.can_summon, "summon"),
            (definition.can_be_invisible, "invisibility"),
            (definition.splits, "splits"),
            (definition.cant_die, "cannot die"),
            (definition.cant_yell, "cannot yell"),
            (definition.cant_bleed, "cannot bleed"),
        )
        if flag
    ]
    safe = [
        name
        for name in ("sleep", "charm", "curse", "paralysis", "poison", "power", "death")
        if getattr(definition, name + "_safe")
    ]
    return "\n".join(
        [
            f"Definition source: {definition.source_file} (offset {definition.offset})",
            f"Base stats: STR {definition.strength}; DEX {definition.dexterity}; INT {definition.intelligence}; combat {definition.combat}",
            f"Armour {definition.armor}; innate weapon damage {definition.weapon}; reach {definition.reach}",
            f"Alignment: {definition.alignment_name}; attack: {definition.attack_mode_name}",
            f"Movement: {definition.move_flags or 'none'}; abilities: {', '.join(abilities) or 'none'}",
            f"Immune damage: {definition.immune_names or 'none'}; vulnerable damage: {definition.vulnerable_names or 'none'}",
            f"Protected effects: {', '.join(safe) or 'none'}; SFX {definition.sfx}; equipment offset {definition.equip_offset}",
        ]
    )


def detail(session: Session, entry: MonsterEntry) -> str:
    lines = [
        f"Monster {'instance #' + str(entry.number) if entry.actor else 'definition'}: {session.name(entry)} — shape {entry.shape}"
    ]
    if entry.actor:
        actor = entry.actor
        lines.extend(
            [
                f"Actor source: {session.source.path}; stored frame {actor.frame}",
                f"Map {actor.map_num}; tile ({actor.tile_x}, {actor.tile_y}, {actor.lift}); superchunk {actor.superchunk}",
                f"Current health {actor.health}; STR {actor.strength}; DEX {actor.dexterity}; INT {actor.intelligence}; combat {actor.combat}",
                f"Activity: {actor.schedule_name}; alignment: {actor.alignment_name}; attack: {actor.attack_mode_name}; dead: {actor.is_dead}",
                f"Actual inventory: {len(actor.inventory)} parsed items (including nested contents)",
            ]
        )
    lines.append(
        definition_detail(entry.definition)
        if entry.definition
        else "No matching monster definition available in this world."
    )
    return "\n".join(lines)


def _library(session: Session) -> ShapeLibrary | None:
    if session.preview_library is None and session.preview_error is None:
        try:
            path = npc_ui.owner_file(session.target, "SHAPES.VGA")
            if path is None:
                raise ValueError("SHAPES.VGA not found for the selected world")
            session.preview_library = load_library(session.target, session.game, path)
        except READ_ERRORS as error:
            session.preview_error = str(error)
    if session.preview_library is None:
        print(
            f"  Monster preview unavailable: {clean(session.preview_error or 'missing artwork')}"
        )
    return session.preview_library


def preview(
    session: Session, entry: MonsterEntry, frame: int | None = None
) -> int | None:
    if not sys.stdout.isatty():
        return None
    library = _library(session)
    if library is None:
        return None
    try:
        shape = library.shape(entry.shape)
        if not shape.frames:
            raise ValueError(f"Shape {entry.shape} has no frames")
        # Consistent with NPC browsing, with an explicit frame-0 fallback for
        # creatures whose archive has no standing frame 16.
        selected = (
            (16 if len(shape.frames) > 16 else 0)
            if frame is None
            else frame % len(shape.frames)
        )
        print(f"  Monster shape preview: shape {entry.shape}, frame {selected}")
        terminal_image(library.images(shape, entry.shape)[selected], reserved_rows=20)
        return selected
    except READ_ERRORS as error:
        print(f"  Monster preview unavailable: {clean(str(error))}")
        return None


def possible_equipment(
    session: Session, entry: MonsterEntry
) -> list[dict[str, object]]:
    return [
        row for row in session.equipment_rows if row["monster_shape"] == entry.shape
    ]


def equipment_lines(session: Session, entry: MonsterEntry) -> list[str]:
    if entry.definition is None:
        return ["No matching definition; possible spawn equipment is unknown."]
    offset = entry.definition.equip_offset
    if offset == 0:
        return ["Definition has no random equipment table (offset 0)."]
    if session.equipment is None:
        return ["EQUIP.DAT unavailable; possible spawn equipment is unknown."]
    if offset > len(session.equipment.records):
        return [
            f"Equipment offset {offset} is outside EQUIP.DAT; possible equipment is unknown."
        ]
    return [
        f"Shape {row['item_shape']} {clean(str(row['item_name'])) or '(unnamed)'}: {row['probability']}% chance; quantity {row['min_quantity_if_created']}-{row['max_quantity_if_created']}"
        + (
            f" | generated ammunition for weapon {row['generated_from_item_shape']}"
            if row["generated"]
            else ""
        )
        for row in possible_equipment(session, entry)
    ] or ["No non-zero equipment chances in this table."]


def spawn_rows(
    session: Session, shape: int, map_num: int = 0
) -> list[dict[str, object]]:
    if not session.world_matches:
        raise ValueError(
            "Choose the world matching this save's game identity before interpreting eggs."
        )
    if map_num not in session.spawn_cache:
        static = session.target.static or session.target.patch
        root: Path | None
        if session.archive is not None:
            with TemporaryDirectory(prefix="titan-monster-eggs-") as temporary:
                root = Path(temporary)
                for name in session.archive.entry_names():
                    match = IREG_NAME.fullmatch(name.replace("\\", "/"))
                    if match is None:
                        continue
                    stored_map = int(match[1][3:], 16) if match[1] else 0
                    if stored_map != map_num:
                        continue
                    destination = (
                        root
                        / ((match[1].lower() + "/") if match[1] else "")
                        / match[2].lower()
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(session.archive.get_data(name) or b"")
                eggs = query_eggs(
                    EggQueryParams(
                        str(static),
                        str(root),
                        egg_types=["monster"],
                        patch_dir=str(session.target.patch),
                        map_num=map_num,
                    )
                )
            provenance = str(session.source.path)
        else:
            root = (
                session.target.gamedat
                if session.source.kind == "definitions"
                else session.source.path
                if session.source.path.is_dir()
                else session.source.path.parent
            )
            if root is None or not root.is_dir():
                raise ValueError(
                    "No live GAMEDAT available for spawn eggs; select a saved game or GAMEDAT source."
                )
            eggs = query_eggs(
                EggQueryParams(
                    str(static),
                    str(root),
                    egg_types=["monster"],
                    patch_dir=str(session.target.patch),
                    map_num=map_num,
                )
            )
            provenance = str(root)
        session.spawn_cache[map_num] = [
            {
                "source": provenance,
                "map_num": map_num,
                "superchunk": egg.superchunk,
                "tile_x": egg.obj.tx,
                "tile_y": egg.obj.ty,
                "lift": egg.obj.tz,
                "monster_shape": egg.meta.monster_shape,
                "monster_frame": egg.meta.monster_frame,
                "count": egg.meta.monster_count,
                "probability": egg.meta.probability,
                "criteria": egg.meta.criteria_name,
                "distance": egg.meta.distance,
                "once": egg.meta.once,
                "hatched": egg.meta.hatched,
                "schedule": egg.meta.monster_schedule,
                "alignment": egg.meta.monster_alignment,
            }
            for egg in eggs
        ]
    return [
        row for row in session.spawn_cache[map_num] if row["monster_shape"] == shape
    ]


def _spawn_map(session: Session, entry: MonsterEntry) -> int:
    maps = {0, entry.actor.map_num if entry.actor else 0}
    if session.archive:
        for name in session.archive.entry_names():
            match = IREG_NAME.fullmatch(name.replace("\\", "/"))
            if match and match[1]:
                maps.add(int(match[1][3:], 16))
    else:
        root = (
            session.target.gamedat
            if session.source.kind == "definitions"
            else session.source.path
            if session.source.path.is_dir()
            else session.source.path.parent
        )
        if root and root.is_dir():
            for path in root.iterdir():
                if path.is_dir() and re.fullmatch(
                    r"map[0-9a-f]{2}", path.name, re.IGNORECASE
                ):
                    maps.add(int(path.name[3:], 16))
    default = entry.actor.map_num if entry.actor else 0
    return int(
        menu("Spawn egg map:", {str(i): f"Map {i}" for i in sorted(maps)}, str(default))
    )


def _csv(rows: list[dict[str, object]], fields: list[str]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output, list(rows[0]) if rows else fields, lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def write_report(session: Session, path: Path, content: str) -> None:
    path = path.expanduser().absolute()
    resolved = path.resolve()
    protected = [session.target.static, session.target.patch, session.target.gamedat]
    if session.source.path.is_dir():
        protected.append(session.source.path)
    elif session.source.path.name.casefold() == "monsnpcs.dat":
        protected.append(session.source.path.parent)
    if resolved == session.source.path.resolve() or any(
        p and resolved.is_relative_to(p.resolve()) for p in protected
    ):
        raise ValueError(
            "Choose a report destination outside the game archives and GAMEDAT folders"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(content)
    print(f"  Saved {path}")


def _export(
    session: Session, matches: list[MonsterEntry], current: MonsterEntry | None = None
) -> None:
    labels = {
        "C": f"Matching monsters (.csv; {len(matches)} records)",
        "T": "Source overview (.txt)",
        "Q": "Back",
    }
    if current:
        labels.update(
            {
                "J": "This monster and equipment (.json)",
                "P": "Possible spawn equipment (.csv)",
                "G": "Related spawn eggs (.csv)",
            }
        )
        if current.actor:
            labels["I"] = "Actual inventory (.csv)"
    action = menu("Export monster report:", labels, "J" if current else "C")
    if action == "Q":
        return
    suffix = ".csv"
    if action == "T":
        content, suffix = session.overview() + "\n", ".txt"
    elif action == "C":
        if session.source.kind == "definitions":
            rows = [
                {"name": session.name(e), **e.definition.as_row()}
                for e in matches
                if e.definition
            ]
            content = _csv(rows, ["name", "shape", "source_file"])
        else:
            # Keep source record numbers stable when the list is filtered.
            rows = []
            for entry in matches:
                if entry.actor:
                    row = next(
                        csv.DictReader(
                            io.StringIO(
                                live_monsters_csv(
                                    U7NPCData([entry.actor]), str(session.source.path)
                                )
                            )
                        )
                    )
                    row["live_index"] = str(entry.number)
                    row["name"] = session.name(entry)
                    rows.append(dict(row))
            content = _csv(rows, ["source_file", "live_index", "shape", "name"])
    elif current is None:
        return
    elif action == "J":
        report = {
            "world": session.target.name,
            "source": str(session.source.path),
            "record_number": current.number,
            "shape": current.shape,
            "name": session.name(current),
            "definition": current.definition.as_row() if current.definition else None,
            "actual_actor": asdict(current.actor) if current.actor else None,
            "actual_inventory": npc_ui.inventory_rows(session, current.actor)
            if current.actor
            else None,
            "possible_spawn_equipment": possible_equipment(session, current),
            "equipment_notes": equipment_lines(session, current),
            "warnings": session.warnings,
        }
        content, suffix = json.dumps(report, indent=2) + "\n", ".json"
    elif action == "P":
        content = _csv(
            possible_equipment(session, current),
            ["monster_shape", "item_shape", "probability", "quantity"],
        )
    elif action == "I" and current.actor:
        content = _csv(
            npc_ui.inventory_rows(session, current.actor),
            ["shape", "frame", "depth", "path"],
        )
    elif action == "G":
        content = _csv(
            spawn_rows(session, current.shape, _spawn_map(session, current)),
            ["source", "map_num", "monster_shape", "tile_x", "tile_y"],
        )
    else:
        return
    default = f"monster_{current.number}" if current else "monster_report"
    raw = (
        ui.path(f"  Report output [{default}{suffix}]: ", default + suffix)
        .strip()
        .strip('"')
        or default + suffix
    )
    write_report(session, Path(raw), content)


def _source(target: ArchiveTarget, default: str = "D") -> npc_ui.Source | None:
    while True:
        action = menu(
            "Monster source:",
            {
                "D": "Monster definitions (selected world's base + patch)",
                "G": f"Current GAMEDAT — {target.gamedat or 'not found'}",
                "S": "Saved game from this world's save folder",
                "C": "Other save, GAMEDAT, monsnpcs.dat, or MONSTERS.DAT",
                "W": "Change game/world",
                "Q": "Quit",
            },
            default,
        )
        if action == "Q":
            raise ui.PromptCancelled
        if action == "W":
            return None
        if action == "D":
            return npc_ui.Source(
                npc_ui.owner_file(target, "MONSTERS.DAT")
                or target.static
                or target.patch,
                "definitions",
            )
        if action == "G" and target.gamedat and target.gamedat.is_dir():
            return npc_ui.Source(target.gamedat, "live")
        if action == "S":
            path = npc_ui._choose_save(target)
            if path:
                return npc_ui.Source(path, "save")
        elif action == "C":
            raw = (
                ui.path("  Monster source file or GAMEDAT folder: ").strip().strip('"')
            )
            if raw:
                path = Path(raw).expanduser()
                return npc_ui.Source(
                    path,
                    "definitions"
                    if path.name.casefold() == "monsters.dat"
                    else "custom",
                )
        elif action != "D":
            print("  That source is unavailable; select another or enter its path.")


def _monster_action(
    session: Session,
    current: MonsterEntry,
    action: str,
    frame: int | None,
    matches: list[MonsterEntry],
) -> int | None:
    if action == "F":
        return frame + 1 if frame is not None else None
    if action == "P":
        if sys.stdout.isatty():
            library = _library(session)
            if library:
                play_terminal(
                    playback_provider(
                        library,
                        library.shape(current.shape),
                        current.shape,
                        frame or 0,
                        "F",
                    ),
                    title=f"Monster {session.name(current)}",
                )
        else:
            print("  Frame playback requires an interactive terminal.")
    elif action == "T":
        print(
            "  Possible spawn equipment; chances do not describe this actor's actual inventory."
        )
        npc_ui._paged("Possible spawn equipment", equipment_lines(session, current))
    elif action == "I" and current.actor:
        npc_ui._inventory(session, current.actor, actor_label="monster")
    elif action == "G":
        map_num = _spawn_map(session, current)
        print(
            f"  Scanning source spawn eggs for shape {current.shape}, map {map_num}..."
        )
        rows = spawn_rows(session, current.shape, map_num)
        npc_ui._paged(
            "Related spawn eggs",
            [
                f"{r['source']} | map {r['map_num']}, tile ({r['tile_x']}, {r['tile_y']}, {r['lift']}), frame {r['monster_frame']}, count {r['count']}, chance {r['probability']}%, {r['criteria']}"
                for r in rows
            ],
        )
    elif action == "E":
        _export(session, matches, current)
    return frame


def browse(session: Session, first: int | None = None) -> str:
    if not session.records:
        print(
            "  No monster records available in this source; choose another source or view."
        )
    query, mode, page = "", "all", 0
    current = next((e for e in session.records if e.shape == first), None)
    frame = None
    if first is not None and current is None:
        print(f"  Monster shape {first} is not present; choose an available monster.")
    while True:
        matches = filter_entries(session, query, mode)
        page = min(page, max(0, (len(matches) - 1) // PAGE_SIZE))
        if current is None:
            labels = {
                str(
                    e.number
                ): f"{'Instance #' + str(e.number) + ' — ' if e.actor else ''}shape {e.shape}: {session.name(e)}"
                + (f" | map {e.actor.map_num}, HP {e.actor.health}" if e.actor else "")
                for e in matches[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
            }
            labels.update(
                {
                    "S": "Search by shape/name (#number for a live instance)",
                    "F": f"Filter ({mode})",
                    "E": "Export matching monsters",
                    "O": "Source overview",
                    "D": "Different source",
                    "W": "Change world",
                    "Q": "Quit",
                }
            )
            if (page + 1) * PAGE_SIZE < len(matches):
                labels["N"] = "Next page"
            if page:
                labels["B"] = "Previous page"
            print(
                f"\nMonsters: {len(matches)} matches; page {page + 1}/{max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)}; search: {clean(query) or '(all)'}"
            )
            action = menu("Choose monster:", labels, next(iter(labels)))
            if action == "S":
                query = ui.text("  Shape, name or #instance [blank = all]: ").strip()
                page = 0
            elif action == "F":
                filters = {
                    "A": "All",
                    "G": "Good",
                    "E": "Evil",
                    "U": "Neutral",
                    "C": "Chaotic",
                }
                modes = {
                    "A": "all",
                    "G": "good",
                    "E": "evil",
                    "U": "neutral",
                    "C": "chaotic",
                }
                if session.source.kind != "definitions":
                    filters.update({"L": "Alive", "D": "Dead"})
                    modes.update({"L": "alive", "D": "dead"})
                mode = modes[menu("Show monsters:", filters, "A")]
                page = 0
            elif action in {"N", "B"}:
                page += 1 if action == "N" else -1
            elif action == "E":
                try:
                    _export(session, matches)
                except READ_ERRORS as error:
                    print(f"  ERROR: {error}")
            elif action in {"Q", "D", "W", "O"}:
                return action
            else:
                current = next(e for e in matches if str(e.number) == action)
                frame = None
            continue
        print("\n" + detail(session, current))
        frame = preview(session, current, frame)
        navigation = filter_entries(session, mode=mode)
        index = navigation.index(current)
        following, previous = (
            navigation[(index + 1) % len(navigation)],
            navigation[(index - 1) % len(navigation)],
        )
        print(
            f"  Browsing {index + 1}/{len(navigation)} monsters; filter: {mode}. Search applies to the selection list."
        )
        labels = {
            "N": f"Next monster ({following.number}: {session.name(following)})",
            "B": f"Previous monster ({previous.number}: {session.name(previous)})",
            "S": "Choose/search monster",
            "F": "Next preview frame",
            "P": "Play shape frames",
            "T": "Possible spawn equipment",
            "G": "Related spawn eggs",
            "E": "Export report",
            "O": "Source overview",
            "D": "Different source",
            "W": "Change world",
            "Q": "Quit",
        }
        if current.actor:
            labels["I"] = "Actual inventory and nested contents"
        action = menu("Monster actions:", labels, "S")
        if action in {"Q", "D", "W", "O"}:
            return action
        if action in {"N", "B"}:
            if len(navigation) == 1:
                print(
                    "  Only one monster matches this filter; choose All to browse more."
                )
            current, frame = (following if action == "N" else previous), None
        elif action == "S":
            current, frame = None, None
        else:
            try:
                frame = _monster_action(session, current, action, frame, matches)
            except READ_ERRORS as error:
                print(f"  ERROR: {error}")


def run_browser(
    *, game: str = "bg", source: str | None = None, shape: int | None = None
) -> int:
    print("\nTitan U7 Monster Browser")
    try:
        while True:
            flavour = menu(
                "Game flavour:",
                {"1": "Black Gate", "2": "Serpent Isle"},
                "2" if game == "si" else "1",
            )
            game = "si" if flavour == "2" else "bg"
            base, targets = game_targets(game)
            target = select_target(base, targets)
            print(f"  Selected target: {clean(target.name)}")
            print(f"  Base: {target.static or 'not found'}; patch: {target.patch}")
            while True:
                try:
                    selected: npc_ui.Source | None
                    if source:
                        path = Path(source)
                        selected = npc_ui.Source(
                            path,
                            "definitions"
                            if path.name.casefold() == "monsters.dat"
                            else "custom",
                        )
                        source = None
                    else:
                        selected = _source(target)
                    if selected is None:
                        break
                    session = load_session(target, selected, game)
                except READ_ERRORS as error:
                    print(f"  ERROR: {error}")
                    continue
                print("\n" + session.overview())
                while True:
                    try:
                        action = browse(session, shape)
                        shape = None
                        if action == "O":
                            print("\n" + session.overview())
                            action = menu(
                                "Source actions:",
                                {
                                    "M": "Browse monsters",
                                    "E": "Export report",
                                    "D": "Different source",
                                    "W": "Change world",
                                    "Q": "Quit",
                                },
                                "M",
                            )
                            if action == "E":
                                _export(session, session.records)
                        if action == "Q":
                            return 0
                        if action in {"D", "W"}:
                            break
                    except READ_ERRORS as error:
                        print(f"  ERROR: {error}")
                if action == "W":
                    break
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
