"""Ultima 7 monster definition and live-monster helpers."""

from __future__ import annotations

__all__ = [
    "U7MonsterDefinition",
    "U7MonsterDefinitions",
    "U7MonsterEquipment",
    "monster_equipment_csv",
    "monster_equipment_summary",
    "monster_definitions_csv",
    "live_monsters_csv",
    "monster_report",
]

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from titan.u7.eggs import EggQueryParams, format_csv as eggs_csv, query_eggs
from titan.u7.names import U7ShapeNames
from titan.u7.save import U7NPC, U7NPCData, U7Save
from titan.u7.typeflag import U7TypeFlags
from titan.u7.world import WorldQueryParams, _format_csv as world_csv, run_query


ALIGNMENT_NAMES = {
    0: "neutral",
    1: "good",
    2: "evil",
    3: "chaotic",
}

ATTACK_MODE_NAMES = {
    0: "nearest",
    1: "weakest",
    2: "strongest",
    3: "berserk",
    4: "protect",
    5: "defend",
    6: "flank",
    7: "random",
}

MOVE_FLAG_BITS = (
    (0, "fly"),
    (1, "swim"),
    (2, "walk"),
    (3, "ethereal"),
    (4, "no_body"),
    (5, "unknown_5"),
    (6, "start_invisible"),
    (7, "see_invisible"),
)

DAMAGE_BITS = (
    (0, "normal"),
    (1, "fire"),
    (2, "magic"),
    (3, "poison"),
    (4, "ethereal"),
    (5, "sonic"),
    (6, "lightning"),
    (7, "death"),
)

_MONSTERS_ENTRY_SIZE = 25
_EQUIP_ELEMENT_SIZE = 6
_EQUIP_ELEMENTS_PER_RECORD = 10
_WEAPON_ENTRY_PAYLOAD_SIZE = 19


def _bit_names(value: int, table: Iterable[tuple[int, str]]) -> str:
    return "|".join(name for bit, name in table if value & (1 << bit))


@dataclass
class U7MonsterDefinition:
    """Decoded one-record entry from ``MONSTERS.DAT``."""

    source_file: str
    file_version: int | None
    offset: int
    shape: int
    deleted: bool
    strength: int = 0
    dexterity: int = 0
    intelligence: int = 0
    alignment: int = 0
    combat: int = 0
    armor: int = 0
    weapon: int = 0
    reach: int = 0
    flags: int = 0
    vulnerable: int = 0
    immune: int = 0
    sleep_safe: bool = False
    charm_safe: bool = False
    curse_safe: bool = False
    paralysis_safe: bool = False
    poison_safe: bool = False
    xp_unknown_bit: bool = False
    splits: bool = False
    cant_die: bool = False
    power_safe: bool = False
    death_safe: bool = False
    cant_yell: bool = False
    cant_bleed: bool = False
    attack_mode: int = 0
    byte13_extra: int = 0
    equip_offset: int = 0
    can_teleport: bool = False
    can_summon: bool = False
    can_be_invisible: bool = False
    sfx: int = 0
    raw_hex: str = ""

    @property
    def shape_hex(self) -> str:
        return f"0x{self.shape:03X}"

    @property
    def alignment_name(self) -> str:
        return ALIGNMENT_NAMES.get(self.alignment, f"alignment_{self.alignment}")

    @property
    def attack_mode_name(self) -> str:
        return ATTACK_MODE_NAMES.get(
            self.attack_mode,
            f"attack_{self.attack_mode}",
        )

    @property
    def move_flags(self) -> str:
        return _bit_names(self.flags, MOVE_FLAG_BITS)

    @property
    def vulnerable_names(self) -> str:
        return _bit_names(self.vulnerable, DAMAGE_BITS)

    @property
    def immune_names(self) -> str:
        return _bit_names(self.immune, DAMAGE_BITS)

    def as_row(self) -> dict[str, object]:
        return {
            "source_file": self.source_file,
            "file_version": "" if self.file_version is None else self.file_version,
            "offset": self.offset,
            "shape": self.shape,
            "shape_hex": self.shape_hex,
            "deleted": int(self.deleted),
            "strength": self.strength,
            "dexterity": self.dexterity,
            "intelligence": self.intelligence,
            "alignment": self.alignment,
            "alignment_name": self.alignment_name,
            "combat": self.combat,
            "armor": self.armor,
            "weapon": self.weapon,
            "reach": self.reach,
            "flags": self.flags,
            "flags_hex": f"0x{self.flags:02X}",
            "move_flags": self.move_flags,
            "vulnerable": self.vulnerable,
            "vulnerable_hex": f"0x{self.vulnerable:02X}",
            "vulnerable_names": self.vulnerable_names,
            "immune": self.immune,
            "immune_hex": f"0x{self.immune:02X}",
            "immune_names": self.immune_names,
            "sleep_safe": int(self.sleep_safe),
            "charm_safe": int(self.charm_safe),
            "curse_safe": int(self.curse_safe),
            "paralysis_safe": int(self.paralysis_safe),
            "poison_safe": int(self.poison_safe),
            "xp_unknown_bit": int(self.xp_unknown_bit),
            "splits": int(self.splits),
            "cant_die": int(self.cant_die),
            "power_safe": int(self.power_safe),
            "death_safe": int(self.death_safe),
            "cant_yell": int(self.cant_yell),
            "cant_bleed": int(self.cant_bleed),
            "attack_mode": self.attack_mode,
            "attack_mode_name": self.attack_mode_name,
            "byte13_extra": self.byte13_extra,
            "equip_offset": self.equip_offset,
            "can_teleport": int(self.can_teleport),
            "can_summon": int(self.can_summon),
            "can_be_invisible": int(self.can_be_invisible),
            "sfx": self.sfx,
            "raw_hex": self.raw_hex,
        }


class U7MonsterDefinitions:
    """All decoded ``MONSTERS.DAT`` records."""

    def __init__(self, records: list[U7MonsterDefinition]) -> None:
        self.records = records

    @classmethod
    def from_file(
        cls,
        filepath: str,
        game: str = "bg",
    ) -> "U7MonsterDefinitions":
        return cls.from_bytes(
            Path(filepath).read_bytes(),
            source_file=filepath,
            game=game,
        )

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        game: str = "bg",
    ) -> "U7MonsterDefinitions":
        for name in ("MONSTERS.DAT", "monsters.dat"):
            path = Path(static_dir) / name
            if path.is_file():
                return cls.from_file(str(path), game=game)
        raise FileNotFoundError(f"MONSTERS.DAT not found in {static_dir}")

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        source_file: str = "",
        game: str = "bg",
    ) -> "U7MonsterDefinitions":
        header_size = 1 if len(data) % _MONSTERS_ENTRY_SIZE == 1 else 0
        file_version = data[0] if header_size else None
        payload_len = len(data) - header_size
        records: list[U7MonsterDefinition] = []

        for rel_offset in range(
            0,
            payload_len - (payload_len % _MONSTERS_ENTRY_SIZE),
            _MONSTERS_ENTRY_SIZE,
        ):
            offset = header_size + rel_offset
            entry = data[offset : offset + _MONSTERS_ENTRY_SIZE]
            records.append(
                cls._read_record(
                    entry,
                    source_file=source_file,
                    file_version=file_version,
                    offset=offset,
                    game=game,
                )
            )
        return cls(records)

    @staticmethod
    def _read_record(
        entry: bytes,
        source_file: str,
        file_version: int | None,
        offset: int,
        game: str,
    ) -> U7MonsterDefinition:
        shape = int.from_bytes(entry[0:2], "little")
        raw = entry[2:]
        deleted = raw[-1] == 0xFF
        if deleted:
            return U7MonsterDefinition(
                source_file=source_file,
                file_version=file_version,
                offset=offset,
                shape=shape,
                deleted=True,
                raw_hex=entry.hex(),
            )

        b2, b3, b4, b5, b6 = raw[0], raw[1], raw[2], raw[3], raw[4]
        b8, flags, vulnerable, immune = raw[6], raw[7], raw[8], raw[9]
        b12, b13, equip_offset, b15 = raw[10], raw[11], raw[12], raw[13]
        sfx_delta = -1 if game.lower() == "bg" else 0
        sfx = int.from_bytes(raw[15:16], "little", signed=True) + sfx_delta
        attack_mode = b13 & 7
        attack_mode = 2 if attack_mode == 0 else attack_mode - 1

        return U7MonsterDefinition(
            source_file=source_file,
            file_version=file_version,
            offset=offset,
            shape=shape,
            deleted=False,
            strength=(b2 >> 2) & 63,
            dexterity=(b3 >> 2) & 63,
            intelligence=(b4 >> 2) & 63,
            alignment=b5 & 3,
            combat=(b5 >> 2) & 63,
            armor=(b6 >> 4) & 15,
            weapon=(b8 >> 4) & 15,
            reach=b8 & 15,
            flags=flags,
            vulnerable=vulnerable,
            immune=immune,
            sleep_safe=bool(b2 & 1),
            charm_safe=bool(b2 & 2),
            curse_safe=bool(b3 & 1),
            paralysis_safe=bool(b3 & 2),
            poison_safe=bool(b4 & 1),
            xp_unknown_bit=bool(b4 & 2),
            splits=bool(b6 & 1),
            cant_die=bool(b6 & 2),
            power_safe=bool(b6 & 4),
            death_safe=bool(b6 & 8),
            cant_yell=bool(b12 & (1 << 5)),
            cant_bleed=bool(b12 & (1 << 6)),
            attack_mode=attack_mode,
            byte13_extra=b13 & ~7,
            equip_offset=equip_offset,
            can_teleport=bool(b15 & 1),
            can_summon=bool(b15 & 2),
            can_be_invisible=bool(b15 & 4),
            sfx=sfx,
            raw_hex=entry.hex(),
        )

    def active_records(self) -> list[U7MonsterDefinition]:
        return [record for record in self.records if not record.deleted]

    def by_shape(self) -> dict[int, U7MonsterDefinition]:
        return {record.shape: record for record in self.active_records()}

    def dump_summary(self) -> str:
        active = len(self.active_records())
        deleted = len(self.records) - active
        lines = [
            (
                "Monster definitions: "
                f"{active} active, {deleted} deleted, {len(self.records)} total"
            )
        ]
        for record in self.active_records()[:20]:
            lines.append(
                f"  {record.shape:4d} {record.shape_hex:>6} "
                f"STR={record.strength:2d} DEX={record.dexterity:2d} "
                f"INT={record.intelligence:2d} CMB={record.combat:2d} "
                f"armor={record.armor:2d} flags={record.move_flags or '-'}"
            )
        if active > 20:
            lines.append(f"  ... {active - 20} more")
        return "\n".join(lines)

    def dump_csv(self) -> str:
        return _rows_to_csv([record.as_row() for record in self.records])

    @staticmethod
    def merge(
        base: "U7MonsterDefinitions",
        mod: Optional["U7MonsterDefinitions"] = None,
    ) -> "U7MonsterDefinitions":
        merged = base.by_shape()
        if mod is not None:
            for record in mod.records:
                if record.deleted:
                    merged.pop(record.shape, None)
                else:
                    merged[record.shape] = record
        return U7MonsterDefinitions([merged[key] for key in sorted(merged)])


@dataclass
class U7MonsterEquipElement:
    """One possible item entry in a monster equipment record."""

    record_index: int
    element_index: int
    shape: int
    probability: int
    quantity: int

    @property
    def equip_offset(self) -> int:
        return self.record_index + 1

    def as_row(self) -> dict[str, object]:
        return {
            "equip_offset": self.equip_offset,
            "record_index": self.record_index,
            "element_index": self.element_index,
            "shape": self.shape,
            "shape_hex": f"0x{self.shape:04X}",
            "probability": self.probability,
            "quantity": self.quantity,
        }


class U7MonsterEquipment:
    """Decoded monster ``equip.dat`` records."""

    def __init__(
        self,
        records: list[list[U7MonsterEquipElement]],
        source_file: str = "",
    ) -> None:
        self.records = records
        self.source_file = source_file

    @classmethod
    def from_file(cls, filepath: str) -> "U7MonsterEquipment":
        data = Path(filepath).read_bytes()
        records = cls.from_bytes(data, source_file=filepath)
        return records

    @classmethod
    def from_dir(cls, data_dir: str) -> "U7MonsterEquipment":
        for name in ("equip.dat", "EQUIP.DAT"):
            path = Path(data_dir) / name
            if path.is_file():
                return cls.from_file(str(path))
        return cls([], source_file="")

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        source_file: str = "",
    ) -> "U7MonsterEquipment":
        if not data:
            return cls([], source_file=source_file)
        pos = 0
        count = data[pos]
        pos += 1
        if count == 255:
            if pos + 2 > len(data):
                return cls([], source_file=source_file)
            count = int.from_bytes(data[pos : pos + 2], "little")
            pos += 2

        records: list[list[U7MonsterEquipElement]] = []
        record_size = _EQUIP_ELEMENT_SIZE * _EQUIP_ELEMENTS_PER_RECORD
        for record_index in range(count):
            if pos + record_size > len(data):
                break
            elements: list[U7MonsterEquipElement] = []
            for element_index in range(_EQUIP_ELEMENTS_PER_RECORD):
                shape = int.from_bytes(data[pos : pos + 2], "little")
                probability = data[pos + 2]
                quantity = data[pos + 3]
                pos += _EQUIP_ELEMENT_SIZE
                elements.append(
                    U7MonsterEquipElement(
                        record_index=record_index,
                        element_index=element_index,
                        shape=shape,
                        probability=probability,
                        quantity=quantity,
                    )
                )
            records.append(elements)
        return cls(records, source_file=source_file)

    def by_offset(self, equip_offset: int) -> list[U7MonsterEquipElement]:
        if equip_offset <= 0 or equip_offset > len(self.records):
            return []
        return self.records[equip_offset - 1]

    def dump_csv(self) -> str:
        return _rows_to_csv(
            [
                {
                    "source_file": self.source_file,
                    **element.as_row(),
                }
                for record in self.records
                for element in record
            ]
        )

    def summary_for_offset(self, equip_offset: int) -> str:
        parts = []
        for element in self.by_offset(equip_offset):
            if element.shape <= 0 or element.probability <= 0 or element.quantity <= 0:
                continue
            parts.append(f"{element.shape}x{element.quantity}@{element.probability}%")
        return "|".join(parts)


@dataclass
class U7WeaponInfo:
    """Small subset of `weapons.dat` needed for monster ammo expansion."""

    shape: int
    ammo: int


class U7WeaponInfos:
    """Decoded `weapons.dat` ammo references by weapon shape."""

    def __init__(self, records: dict[int, U7WeaponInfo]) -> None:
        self.records = records

    @classmethod
    def from_dir(cls, data_dir: str, game: str = "bg") -> "U7WeaponInfos":
        del game
        for name in ("weapons.dat", "WEAPONS.DAT"):
            path = Path(data_dir) / name
            if path.is_file():
                return cls.from_file(str(path))
        return cls({})

    @classmethod
    def from_file(cls, filepath: str) -> "U7WeaponInfos":
        return cls.from_bytes(Path(filepath).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7WeaponInfos":
        if not data:
            return cls({})
        pos = 0
        count = data[pos]
        pos += 1
        if count == 255:
            if pos + 2 > len(data):
                return cls({})
            count = int.from_bytes(data[pos : pos + 2], "little")
            pos += 2
        records: dict[int, U7WeaponInfo] = {}
        for _ in range(count):
            if pos + 2 + _WEAPON_ENTRY_PAYLOAD_SIZE > len(data):
                break
            shape = int.from_bytes(data[pos : pos + 2], "little")
            pos += 2
            payload = data[pos : pos + _WEAPON_ENTRY_PAYLOAD_SIZE]
            pos += _WEAPON_ENTRY_PAYLOAD_SIZE
            if payload[-1] == 0xFF:
                records.pop(shape, None)
                continue
            ammo = int.from_bytes(payload[0:2], "little", signed=True)
            records[shape] = U7WeaponInfo(shape=shape, ammo=ammo)
        return cls(records)

    def ammo_for_weapon(self, shape: int) -> int | None:
        info = self.records.get(shape)
        return info.ammo if info else None


def _rows_to_csv(rows: list[dict[str, object]]) -> str:
    buf = io.StringIO()
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    writer = csv.DictWriter(buf, fieldnames=keys, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _live_monster_row(
    monster: U7NPC, index: int, source_file: str
) -> dict[str, object]:
    return {
        "source_file": source_file,
        "live_index": index,
        "shape": monster.shape,
        "shape_hex": f"0x{monster.shape:03X}",
        "frame": monster.frame,
        "tile_x": monster.tile_x,
        "tile_y": monster.tile_y,
        "lift": monster.lift,
        "map_num": monster.map_num,
        "health": monster.health,
        "strength": monster.strength,
        "dexterity": monster.dexterity,
        "intelligence": monster.intelligence,
        "combat": monster.combat,
        "schedule_type": monster.schedule_type,
        "schedule_name": monster.schedule_name,
        "attack_mode": monster.attack_mode,
        "attack_mode_name": monster.attack_mode_name,
        "alignment": monster.alignment,
        "alignment_name": monster.alignment_name,
        "type_flags": monster.type_flags,
        "type_flags_hex": f"0x{monster.type_flags:04X}",
        "rflags": monster.rflags,
        "rflags_hex": f"0x{monster.rflags:04X}",
        "dead": int(monster.is_dead),
        "has_inventory": int(monster.has_inventory),
    }


def live_monsters_from_source(
    source: str,
    container_shapes: set | None = None,
) -> tuple[U7NPCData, str]:
    """Read live monster actors from a save, GAMEDAT dir, or monsnpcs.dat."""
    path = Path(source)
    source_file = str(path)
    data: bytes | None = None
    if path.is_dir():
        mon_path = path / "monsnpcs.dat"
        source_file = str(mon_path)
        data = mon_path.read_bytes() if mon_path.is_file() else b"\x00\x00"
    elif path.name.lower() == "monsnpcs.dat":
        data = path.read_bytes()
    else:
        save = U7Save.from_file(str(path))
        data = save.get_data("monsnpcs.dat") or b"\x00\x00"
    return U7NPCData.from_monsnpcs_bytes(data, container_shapes), source_file


def live_monsters_csv(monsters: U7NPCData, source_file: str) -> str:
    return _rows_to_csv(
        [
            _live_monster_row(monster, index, source_file)
            for index, monster in enumerate(monsters.npcs)
        ]
    )


def monster_definitions_csv(
    static_dir: str,
    game: str = "bg",
    mod_file: str | None = None,
) -> tuple[str, str, str]:
    """Return base, mod, and merged monster definition CSV text."""
    base = U7MonsterDefinitions.from_dir(static_dir, game=game)
    mod = (
        U7MonsterDefinitions.from_file(mod_file, game=game)
        if mod_file and Path(mod_file).is_file()
        else None
    )
    merged = U7MonsterDefinitions.merge(base, mod)
    return (
        base.dump_csv(),
        mod.dump_csv() if mod else _rows_to_csv([]),
        merged.dump_csv(),
    )


def _monster_spawn_report_csv(
    eggs: list,
    definitions: U7MonsterDefinitions,
    equipment: U7MonsterEquipment,
) -> str:
    defs_by_shape = definitions.by_shape()
    rows: list[dict[str, object]] = []
    for egg in eggs:
        meta = egg.meta
        monster_shape = meta.monster_shape
        definition = (
            defs_by_shape.get(monster_shape) if monster_shape is not None else None
        )
        equip_offset = definition.equip_offset if definition else 0
        row: dict[str, object] = {
            "sc": f"0x{egg.superchunk:02X}",
            "tx": egg.obj.tx,
            "ty": egg.obj.ty,
            "tz": egg.obj.tz,
            "monster_shape": "" if monster_shape is None else monster_shape,
            "monster_frame": "" if meta.monster_frame is None else meta.monster_frame,
            "monster_count": "" if meta.monster_count is None else meta.monster_count,
            "monster_schedule": (
                "" if meta.monster_schedule is None else meta.monster_schedule
            ),
            "monster_alignment": (
                "" if meta.monster_alignment is None else meta.monster_alignment
            ),
            "probability": meta.probability,
            "distance": meta.distance,
            "criteria": meta.criteria,
            "criteria_name": meta.criteria_name,
            "once": int(meta.once),
            "nocturnal": int(meta.nocturnal),
            "auto_reset": int(meta.auto_reset),
            "hatched": int(meta.hatched),
            "definition_found": int(definition is not None),
            "equip_offset": equip_offset,
            "equipment_summary": equipment.summary_for_offset(equip_offset),
        }
        if definition is not None:
            for key, value in definition.as_row().items():
                if key in {"shape", "shape_hex", "source_file", "offset", "raw_hex"}:
                    continue
                row[f"def_{key}"] = value
        rows.append(row)
    return _rows_to_csv(rows)


def _pick_mod_equip(mod_monsters: str | None) -> str | None:
    if not mod_monsters:
        return None
    path = Path(mod_monsters).parent
    for name in ("equip.dat", "EQUIP.DAT"):
        candidate = path / name
        if candidate.is_file():
            return str(candidate)
    return None


def _load_monster_equipment_inputs(
    static_dir: str,
    game: str,
    mod_monsters: str | None,
    equip_file: str | None,
) -> tuple[
    U7MonsterDefinitions,
    U7MonsterEquipment,
    U7WeaponInfos,
    U7ShapeNames,
    U7TypeFlags,
]:
    base_defs = U7MonsterDefinitions.from_dir(static_dir, game=game)
    mod_defs = (
        U7MonsterDefinitions.from_file(mod_monsters, game=game)
        if mod_monsters and Path(mod_monsters).is_file()
        else None
    )
    definitions = U7MonsterDefinitions.merge(base_defs, mod_defs)
    resolved_equip = equip_file or _pick_mod_equip(mod_monsters)
    equipment = (
        U7MonsterEquipment.from_file(resolved_equip)
        if resolved_equip and Path(resolved_equip).is_file()
        else U7MonsterEquipment.from_dir(static_dir)
    )
    weapon_dir = (
        Path(resolved_equip).parent
        if resolved_equip
        else Path(mod_monsters).parent
        if mod_monsters
        else Path(static_dir)
    )
    weapons = U7WeaponInfos.from_dir(str(weapon_dir), game=game)
    if not weapons.records and weapon_dir != Path(static_dir):
        weapons = U7WeaponInfos.from_dir(static_dir, game=game)
    names = U7ShapeNames.from_static_dir(static_dir) or U7ShapeNames([])
    tfa = U7TypeFlags.from_dir(static_dir)
    return definitions, equipment, weapons, names, tfa


def monster_equipment_rows(
    static_dir: str,
    game: str = "bg",
    mod_monsters: str | None = None,
    equip_file: str | None = None,
    monster_shapes: set[int] | None = None,
) -> list[dict[str, object]]:
    """Calculate possible monster equipment rows from definitions + equip.dat."""
    definitions, equipment, weapons, names, tfa = _load_monster_equipment_inputs(
        static_dir,
        game,
        mod_monsters,
        equip_file,
    )
    rows: list[dict[str, object]] = []
    for definition in definitions.active_records():
        if monster_shapes and definition.shape not in monster_shapes:
            continue
        if definition.equip_offset <= 0:
            continue
        elements = equipment.by_offset(definition.equip_offset)
        for element in elements:
            if element.shape <= 0 or element.probability <= 0 or element.quantity <= 0:
                continue
            shape_entry = tfa.get(element.shape)
            is_quantity = (
                shape_entry is not None
                and shape_entry.shape_class == U7TypeFlags.SHAPE_CLASS_QUANTITY
            )
            min_quantity = 1 if is_quantity else element.quantity
            max_quantity = element.quantity
            avg_on_create = (
                (1 + element.quantity) / 2 if is_quantity else float(element.quantity)
            )
            expected_quantity = avg_on_create * (element.probability / 100)
            base_row = {
                "monster_shape": definition.shape,
                "monster_shape_hex": definition.shape_hex,
                "monster_name": names.get(definition.shape),
                "equip_offset": definition.equip_offset,
                "element_index": element.element_index,
                "generated": 0,
                "generated_from_item_shape": "",
                "item_shape": element.shape,
                "item_shape_hex": f"0x{element.shape:04X}",
                "item_name": names.get(element.shape),
                "probability": element.probability,
                "quantity": element.quantity,
                "quantity_mode": "random_1_to_quantity"
                if is_quantity
                else "exact_quantity",
                "min_quantity_if_created": min_quantity,
                "max_quantity_if_created": max_quantity,
                "average_quantity_if_created": f"{avg_on_create:.2f}",
                "expected_quantity_per_spawn": f"{expected_quantity:.2f}",
                "note": "",
            }
            rows.append(base_row)
            ammo_shape = weapons.ammo_for_weapon(element.shape)
            if ammo_shape is not None and ammo_shape >= 0:
                avg_ammo = 11.0
                rows.append(
                    {
                        **base_row,
                        "generated": 1,
                        "generated_from_item_shape": element.shape,
                        "item_shape": ammo_shape,
                        "item_shape_hex": f"0x{ammo_shape:04X}",
                        "item_name": names.get(ammo_shape),
                        "quantity": "2d10",
                        "quantity_mode": "exult_random_2d10_ammo",
                        "min_quantity_if_created": 2,
                        "max_quantity_if_created": 20,
                        "average_quantity_if_created": f"{avg_ammo:.2f}",
                        "expected_quantity_per_spawn": f"{avg_ammo * (element.probability / 100):.2f}",
                        "note": "Generated by Exult when monster equipment creates an ammo-using weapon.",
                    }
                )
    return rows


def monster_equipment_csv(
    static_dir: str,
    game: str = "bg",
    mod_monsters: str | None = None,
    equip_file: str | None = None,
    monster_shapes: set[int] | None = None,
) -> str:
    return _rows_to_csv(
        monster_equipment_rows(
            static_dir,
            game,
            mod_monsters,
            equip_file,
            monster_shapes,
        )
    )


def monster_equipment_summary(
    static_dir: str,
    game: str = "bg",
    mod_monsters: str | None = None,
    equip_file: str | None = None,
    monster_shapes: set[int] | None = None,
) -> str:
    rows = monster_equipment_rows(
        static_dir,
        game,
        mod_monsters,
        equip_file,
        monster_shapes,
    )
    lines = [f"Monster equipment: {len(rows)} possible item row(s)."]
    by_monster: dict[tuple[int, str], list[dict[str, object]]] = {}
    for row in rows:
        monster_shape = row["monster_shape"]
        if not isinstance(monster_shape, int):
            continue
        key = (monster_shape, str(row["monster_name"]))
        by_monster.setdefault(key, []).append(row)
    for (shape, name), monster_rows in sorted(by_monster.items())[:40]:
        label = f"{shape} ({name})" if name else str(shape)
        parts = [
            f"{row['item_shape']}:{row['item_name']} x{row['quantity']}"
            f" @{row['probability']}%"
            for row in monster_rows
        ]
        lines.append(f"  {label}: " + "; ".join(parts))
    if len(by_monster) > 40:
        lines.append(f"  ... {len(by_monster) - 40} more monster(s)")
    return "\n".join(lines)


def monster_report(
    static_dir: str,
    gamedat_dir: str | None,
    live_source: str | None,
    game: str = "bg",
    mod_monsters: str | None = None,
    mod_equip: str | None = None,
    output_dir: str | None = None,
) -> dict[str, str]:
    """Build a joined monster report and optionally write CSV files."""
    base_defs = U7MonsterDefinitions.from_dir(static_dir, game=game)
    mod_defs = (
        U7MonsterDefinitions.from_file(mod_monsters, game=game)
        if mod_monsters and Path(mod_monsters).is_file()
        else None
    )
    merged_defs = U7MonsterDefinitions.merge(base_defs, mod_defs)
    equipment_path = mod_equip or _pick_mod_equip(mod_monsters)
    equipment = (
        U7MonsterEquipment.from_file(equipment_path)
        if equipment_path and Path(equipment_path).is_file()
        else U7MonsterEquipment.from_dir(static_dir)
    )
    outputs: dict[str, str] = {
        "monster_definitions_base.csv": base_defs.dump_csv(),
        "monster_definitions_mod.csv": mod_defs.dump_csv()
        if mod_defs
        else _rows_to_csv([]),
        "monster_definitions_merged.csv": merged_defs.dump_csv(),
        "monster_equipment.csv": equipment.dump_csv(),
    }

    if live_source:
        monsters, source_file = live_monsters_from_source(live_source)
        outputs["live_monsters.csv"] = live_monsters_csv(monsters, source_file)
    else:
        outputs["live_monsters.csv"] = _rows_to_csv([])

    if gamedat_dir:
        eggs = query_eggs(
            EggQueryParams(
                static_dir=static_dir,
                gamedat_dir=gamedat_dir,
                egg_types=["monster"],
                output_format="csv",
            )
        )
        outputs["monster_eggs.csv"] = eggs_csv(eggs)
        outputs["monster_spawn_report.csv"] = _monster_spawn_report_csv(
            eggs,
            merged_defs,
            equipment,
        )
        world = run_query(
            WorldQueryParams(
                static_dir=static_dir,
                gamedat_dir=gamedat_dir,
                shape_classes=[12],
                include_ifix=False,
                include_ireg=True,
                output_format="csv",
            )
        )
        outputs["monster_world_objects.csv"] = world_csv(world)
    else:
        outputs["monster_eggs.csv"] = _rows_to_csv([])
        outputs["monster_spawn_report.csv"] = _rows_to_csv([])
        outputs["monster_world_objects.csv"] = _rows_to_csv([])

    outputs["manifest.txt"] = "\n".join(
        [
            "U7 monster report",
            f"game={game}",
            f"static_dir={static_dir}",
            f"gamedat_dir={gamedat_dir or ''}",
            f"live_source={live_source or ''}",
            f"mod_monsters={mod_monsters or ''}",
            f"mod_equip={equipment_path or ''}",
            "",
            "Files:",
            *sorted(name for name in outputs if name != "manifest.txt"),
            "",
            "Note: usecode-created monsters are not exhaustively discoverable.",
        ]
    )

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, text in outputs.items():
            (out / name).write_text(text, encoding="utf-8")
    return outputs
