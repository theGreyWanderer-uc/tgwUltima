"""Read-only monster definitions, saved actors, equipment and spawn browsing."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from titan.u7 import npc_browser
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.actor_flags import U7ActorFlags, load_u7_actor_flags
from titan.u7.eggs import EggQueryParams, query_eggs
from titan.u7.install import existing_path
from titan.u7.monster import (
    U7MonsterDefinition,
    U7MonsterDefinitions,
    U7MonsterEquipment,
    U7WeaponInfos,
    monster_equipment_rows_from_data,
)
from titan.u7.names import U7ShapeNames
from titan.u7.save import U7Identity, U7NPC, U7NPCData, U7Save
from titan.u7.gameplay_metadata import read_gameplay_table
from titan.u7.shape_archive import find_archive
from titan.u7.typeflag import U7TypeFlags
from titan.u7.world import WorldQueryParams, load_query_metadata

READ_ERRORS = npc_browser.READ_ERRORS
clean = npc_browser.clean
IREG_NAME = re.compile(r"(?:(map[0-9a-f]{2})/)?(u7ireg[0-9a-f]{2})", re.IGNORECASE)


@dataclass(frozen=True)
class MonsterEntry:
    number: int  # Shape number for definitions; source record index for actors.
    shape: int
    definition: U7MonsterDefinition | None = None
    actor: U7NPC | None = None


@dataclass
class Session(npc_browser.Session):
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
    actor_flags: U7ActorFlags = field(default_factory=U7ActorFlags)

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
    target: ArchiveTarget, source: npc_browser.Source, game: str
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
        parsed = U7MonsterDefinitions.from_bytes(data, str(path), game)
        if parsed.warnings:
            raise ValueError(f"{path}: {'; '.join(parsed.warnings)}")
        merged = U7MonsterDefinitions.merge(merged, parsed)
    return merged


def _counted_records(data: bytes, stride: int, name: str) -> None:
    """The existing readers tolerate partial tables; report those explicitly."""
    table = read_gameplay_table(data, stride, name)
    if table.warnings:
        raise ValueError("; ".join(table.warnings))


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

        path = npc_browser.owner_file(target, "SHAPES.VGA")
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
    npc_browser.load_inventory_metadata(session, session.typeflags)
    return containers, shape_count


def _equipment(session: Session) -> None:
    path = npc_browser.owner_file(session.target, "EQUIP.DAT")
    if path is None:
        session.warnings.append(
            "EQUIP.DAT unavailable; possible spawn equipment is unknown."
        )
        return
    try:
        blob = path.read_bytes()
        _counted_records(blob, 60, "EQUIP.DAT")
        session.equipment = U7MonsterEquipment.from_bytes(blob, str(path))
        session.warnings.extend(session.equipment.warnings)
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


def load_session(
    target: ArchiveTarget, source: npc_browser.Source, game: str
) -> Session:
    path = existing_path(source.path.expanduser()).absolute()
    if not path.exists():
        raise ValueError(f"Source not found: {path}")
    source = npc_browser.Source(path, source.kind)
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
            session.warnings.extend(session.archive.warnings)
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
        try:
            flag_patch = target.patch
            owned = {
                p.resolve()
                for p in (
                    find_archive(target.static, "MONSTERS.DAT")
                    if target.static
                    else None,
                    find_archive(target.patch, "MONSTERS.DAT"),
                )
                if p
            }
            if (
                source.kind == "definitions"
                and source.path.is_file()
                and source.path.resolve() not in owned
            ):
                flag_patch = source.path.parent
            session.actor_flags = load_u7_actor_flags(
                game=game, patch_dirs=[flag_patch]
            )
            session.warnings.extend(session.actor_flags.warnings)
        except READ_ERRORS as error:
            session.warnings.append(f"Actor flag metadata unavailable: {error}")
        _equipment(session)
        session.warnings.extend(
            session.definitions.validate_semantics(
                equipment_count=len(session.equipment.records)
                if session.equipment is not None
                else None,
                shape_count=shape_count,
            )
        )
    if source.kind == "definitions":
        session.records = [
            MonsterEntry(d.shape, d.shape, d) for d in session.definitions.records
        ]
    elif blob is None:
        session.warnings.append(
            "monsnpcs.dat is not present in this source; no monsters are inherited from other saves or GAMEDAT."
        )
    else:
        session.npcs = U7NPCData.from_monsnpcs_bytes(
            blob,
            containers,
            shape_count,
            game=game,
            ireg_context=session.ireg_context,
        )
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


def definition_detail(
    definition: U7MonsterDefinition, actor_flags: U7ActorFlags | None = None
) -> str:
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
            f"Alignment: {definition.alignment_name}; behavior category: {definition.behavior_category_name}",
            f"Movement: {definition.move_flags or 'none'}; stored legacy abilities/traits: {', '.join(abilities) or 'none'}",
            f"Immune damage: {definition.immune_names or 'none'}; vulnerable damage: {definition.vulnerable_names or 'none'}",
            f"Protected effects: {', '.join(safe) or 'none'}; SFX {definition.sfx}; equipment offset {definition.equip_offset}",
            *(
                [
                    f"Effective actor flags: {actor_flags.resolve(definition.shape, legacy_flags=definition.legacy_actor_flags).summary()}"
                    + (
                        f"; sources: {'; '.join(actor_flags.sources)}"
                        if actor_flags.sources
                        else ""
                    )
                ]
                if actor_flags is not None
                else []
            ),
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
        definition_detail(entry.definition, session.actor_flags)
        if entry.definition
        else "No matching monster definition available in this world."
    )
    if entry.definition is None and session.world_matches:
        lines.append(
            f"Effective actor flags: {session.actor_flags.resolve(entry.shape).summary()}"
        )
    return "\n".join(lines)


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
            f" | {row['charges_if_created']} charges on one item"
            if row["charges_if_created"] != ""
            else ""
        )
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


def _csv(rows: list[dict[str, object]], fields: list[str]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output, list(rows[0]) if rows else fields, lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
