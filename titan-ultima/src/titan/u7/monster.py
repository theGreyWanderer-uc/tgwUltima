"""Ultima 7 monster definition and live-monster helpers."""

from __future__ import annotations

__all__ = [
    "U7MonsterDefinition",
    "U7MonsterDefinitions",
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
from titan.u7.save import U7NPC, U7NPCData, U7Save
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


def monster_report(
    static_dir: str,
    gamedat_dir: str | None,
    live_source: str | None,
    game: str = "bg",
    mod_monsters: str | None = None,
    output_dir: str | None = None,
) -> dict[str, str]:
    """Build a joined monster report and optionally write CSV files."""
    base_csv, mod_csv, merged_csv = monster_definitions_csv(
        static_dir,
        game=game,
        mod_file=mod_monsters,
    )
    outputs: dict[str, str] = {
        "monster_definitions_base.csv": base_csv,
        "monster_definitions_mod.csv": mod_csv,
        "monster_definitions_merged.csv": merged_csv,
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
        outputs["monster_world_objects.csv"] = _rows_to_csv([])

    outputs["manifest.txt"] = "\n".join(
        [
            "U7 monster report",
            f"game={game}",
            f"static_dir={static_dir}",
            f"gamedat_dir={gamedat_dir or ''}",
            f"live_source={live_source or ''}",
            f"mod_monsters={mod_monsters or ''}",
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
