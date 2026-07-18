"""Ultima 7 static shape/combat metadata parsers."""

from __future__ import annotations

__all__ = [
    "U7Ammos",
    "U7Armors",
    "U7Blends",
    "U7Containers",
    "U7UsecodeIndex",
    "U7Weapons",
    "U7Xforms",
]

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from titan.u7.flex import U7FlexArchive
from titan.u7.names import U7ShapeNames


def _read_count(data: bytes, pos: int = 0) -> tuple[int, int]:
    if pos >= len(data):
        return 0, pos
    count = data[pos]
    pos += 1
    if count == 255 and pos + 2 <= len(data):
        count = int.from_bytes(data[pos : pos + 2], "little")
        pos += 2
    return count, pos


def _find_file(data_dir: str, names: tuple[str, ...]) -> Path | None:
    root = Path(data_dir)
    for name in names:
        path = root / name
        if path.is_file():
            return path
    return None


def _name(shape_names: U7ShapeNames | None, shape: int) -> str:
    return shape_names.get(shape) if shape_names else ""


def _rows_to_csv(rows: list[dict[str, object]]) -> str:
    buf = io.StringIO()
    if not rows:
        return ""
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _power_names(value: int) -> str:
    names = [
        (0x01, "sleep"),
        (0x02, "charm"),
        (0x04, "curse"),
        (0x08, "poison"),
        (0x10, "paralyze"),
        (0x20, "magebane"),
        (0x40, "unknown_6"),
        (0x80, "harmless"),
    ]
    return "|".join(name for bit, name in names if value & bit)


_DAMAGE_TYPE_NAMES = {
    0: "normal",
    1: "fire",
    2: "magic",
    3: "lightning",
    4: "ethereal",
    5: "sonic_poison",
}

_WEAPON_USE_NAMES = {
    0: "melee",
    1: "poor_thrown",
    2: "good_thrown",
    3: "ranged",
}

_AMMO_DROP_NAMES = {
    0: "drop_normally",
    1: "never_drop",
    2: "always_drop",
    3: "homing_if_explodes",
}

_EXULT_BG_BLENDS_RECORD = 10
_EXULT_BG_CONTAINER_RECORD = 11
_EXULT_SI_BLENDS_RECORD = 7
_EXULT_SI_CONTAINER_RECORD = 8
_EXULT_HARDCODED_BLENDS = [
    (208, 216, 224, 192),
    (136, 44, 148, 198),
    (248, 252, 80, 211),
    (144, 148, 252, 247),
    (64, 216, 64, 201),
    (204, 60, 84, 140),
    (144, 40, 192, 128),
    (96, 40, 16, 128),
    (100, 108, 116, 192),
    (68, 132, 28, 128),
    (255, 208, 48, 64),
    (28, 52, 255, 128),
    (8, 68, 0, 128),
    (255, 8, 8, 118),
    (255, 244, 248, 128),
    (56, 40, 32, 128),
    (228, 224, 214, 82),
]


def _exult_record(exult_flx_path: str | None, record_index: int) -> bytes:
    if not exult_flx_path:
        return b""
    path = Path(exult_flx_path)
    if not path.is_file():
        return b""
    flex = U7FlexArchive.from_file(str(path))
    if record_index >= len(flex.records):
        return b""
    return flex.get_record(record_index)


def _exult_blends_record_index(game: str) -> int:
    return _EXULT_BG_BLENDS_RECORD if game.lower() == "bg" else _EXULT_SI_BLENDS_RECORD


def _exult_container_record_index(game: str) -> int:
    return (
        _EXULT_BG_CONTAINER_RECORD
        if game.lower() == "bg"
        else _EXULT_SI_CONTAINER_RECORD
    )


@dataclass
class U7WeaponRecord:
    shape: int
    ammo: int
    projectile: int
    damage: int
    damage_type: int
    lucky: bool
    explodes: bool
    no_blocking: bool
    delete_depleted: bool
    autohit: bool
    uses: int
    range: int
    returns: bool
    need_target: bool
    missile_speed: int
    rotation_speed: int
    actor_frames: int
    powers: int
    usecode: int
    sfx: int
    hitsfx: int
    raw: bytes


class U7Weapons:
    def __init__(self, records: list[U7WeaponRecord]) -> None:
        self.records = records

    @classmethod
    def from_dir(cls, static_dir: str, game: str = "bg") -> "U7Weapons":
        path = _find_file(static_dir, ("weapons.dat", "WEAPONS.DAT"))
        return cls.from_file(str(path), game=game) if path else cls([])

    @classmethod
    def from_file(cls, filepath: str, game: str = "bg") -> "U7Weapons":
        return cls.from_bytes(Path(filepath).read_bytes(), game=game)

    @classmethod
    def from_bytes(cls, data: bytes, game: str = "bg") -> "U7Weapons":
        count, pos = _read_count(data)
        records: list[U7WeaponRecord] = []
        for _ in range(count):
            if pos + 21 > len(data):
                break
            raw = data[pos : pos + 21]
            pos += 21
            if raw[-1] == 0xFF:
                continue
            shape = int.from_bytes(raw[0:2], "little")
            ammo = int.from_bytes(raw[2:4], "little", signed=True)
            projectile = int.from_bytes(raw[4:6], "little", signed=True)
            damage = raw[6]
            flags0 = raw[7]
            range_byte = raw[8]
            flags1 = raw[9]
            flags2 = raw[10]
            speed = (flags2 >> 5) & 7
            missile_speed = (
                4
                if ((flags1 >> 2) & 3)
                else (3 if speed == 0 else 2 if speed < 3 else 1)
            )
            sfx_delta = -1 if game.lower() == "bg" else 0
            records.append(
                U7WeaponRecord(
                    shape=shape,
                    ammo=ammo,
                    projectile=projectile,
                    damage=damage,
                    damage_type=(flags0 >> 4) & 15,
                    lucky=bool(flags0 & 0x01),
                    explodes=bool(flags0 & 0x02),
                    no_blocking=bool(flags0 & 0x04),
                    delete_depleted=bool(flags0 & 0x08),
                    autohit=bool(range_byte & 0x01),
                    uses=(range_byte >> 1) & 3,
                    range=range_byte >> 3,
                    returns=bool(flags1 & 0x01),
                    need_target=bool(flags1 & 0x02),
                    missile_speed=missile_speed,
                    rotation_speed=(flags1 >> 4) & 15,
                    actor_frames=flags2 & 15,
                    powers=raw[11],
                    usecode=int.from_bytes(raw[13:15], "little"),
                    sfx=int.from_bytes(raw[15:17], "little", signed=True) + sfx_delta,
                    hitsfx=int.from_bytes(raw[17:19], "little", signed=True)
                    + sfx_delta,
                    raw=raw,
                )
            )
        return cls(records)

    def dump_csv(self, names: U7ShapeNames | None = None) -> str:
        rows = [
            {
                "shape": rec.shape,
                "shape_hex": f"0x{rec.shape:04X}",
                "shape_name": _name(names, rec.shape),
                "ammo": rec.ammo,
                "projectile": rec.projectile,
                "damage": rec.damage,
                "damage_type": rec.damage_type,
                "damage_type_name": _DAMAGE_TYPE_NAMES.get(rec.damage_type, ""),
                "lucky": int(rec.lucky),
                "explodes": int(rec.explodes),
                "no_blocking": int(rec.no_blocking),
                "delete_depleted": int(rec.delete_depleted),
                "autohit": int(rec.autohit),
                "uses": rec.uses,
                "uses_name": _WEAPON_USE_NAMES.get(rec.uses, ""),
                "range": rec.range,
                "returns": int(rec.returns),
                "need_target": int(rec.need_target),
                "missile_speed": rec.missile_speed,
                "rotation_speed": rec.rotation_speed,
                "actor_frames": rec.actor_frames,
                "powers": rec.powers,
                "power_names": _power_names(rec.powers),
                "usecode": rec.usecode,
                "usecode_hex": f"0x{rec.usecode:04X}",
                "sfx": rec.sfx,
                "hitsfx": rec.hitsfx,
                "raw_hex": rec.raw.hex(),
            }
            for rec in self.records
        ]
        return _rows_to_csv(rows)


@dataclass
class U7AmmoRecord:
    shape: int
    family_shape: int
    sprite_shape: int
    damage: int
    lucky: bool
    autohit: bool
    returns: bool
    no_blocking: bool
    homing: bool
    drop_type: int
    explodes: bool
    damage_type: int
    powers: int
    raw: bytes


class U7Ammos:
    def __init__(self, records: list[U7AmmoRecord]) -> None:
        self.records = records

    @classmethod
    def from_dir(cls, static_dir: str) -> "U7Ammos":
        path = _find_file(static_dir, ("ammo.dat", "AMMO.DAT"))
        return cls.from_file(str(path)) if path else cls([])

    @classmethod
    def from_file(cls, filepath: str) -> "U7Ammos":
        return cls.from_bytes(Path(filepath).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7Ammos":
        count, pos = _read_count(data)
        records: list[U7AmmoRecord] = []
        for _ in range(count):
            if pos + 13 > len(data):
                break
            raw = data[pos : pos + 13]
            pos += 13
            if raw[-1] == 0xFF:
                continue
            flags0 = raw[7]
            homing = ((flags0 >> 4) & 3) == 3
            records.append(
                U7AmmoRecord(
                    shape=int.from_bytes(raw[0:2], "little"),
                    family_shape=int.from_bytes(raw[2:4], "little", signed=True),
                    sprite_shape=int.from_bytes(raw[4:6], "little", signed=True),
                    damage=raw[6],
                    lucky=bool(flags0 & 0x01),
                    autohit=bool(flags0 & 0x02),
                    returns=bool(flags0 & 0x04),
                    no_blocking=bool(flags0 & 0x08),
                    homing=homing,
                    drop_type=0 if homing else (flags0 >> 4) & 3,
                    explodes=bool(flags0 & 0x40),
                    damage_type=(raw[9] >> 4) & 15,
                    powers=raw[10],
                    raw=raw,
                )
            )
        return cls(records)

    def dump_csv(self, names: U7ShapeNames | None = None) -> str:
        rows = []
        for rec in self.records:
            rows.append(
                {
                    "shape": rec.shape,
                    "shape_hex": f"0x{rec.shape:04X}",
                    "shape_name": _name(names, rec.shape),
                    "family_shape": rec.family_shape,
                    "family_name": _name(names, rec.family_shape),
                    "sprite_shape": rec.sprite_shape,
                    "sprite_name": _name(names, rec.sprite_shape),
                    "damage": rec.damage,
                    "damage_type": rec.damage_type,
                    "damage_type_name": _DAMAGE_TYPE_NAMES.get(rec.damage_type, ""),
                    "lucky": int(rec.lucky),
                    "autohit": int(rec.autohit),
                    "returns": int(rec.returns),
                    "no_blocking": int(rec.no_blocking),
                    "homing": int(rec.homing),
                    "drop_type": rec.drop_type,
                    "drop_type_name": _AMMO_DROP_NAMES.get(rec.drop_type, ""),
                    "explodes": int(rec.explodes),
                    "powers": rec.powers,
                    "power_names": _power_names(rec.powers),
                    "raw_hex": rec.raw.hex(),
                }
            )
        return _rows_to_csv(rows)


@dataclass
class U7ArmorRecord:
    shape: int
    protection: int
    immunity: int
    raw: bytes


class U7Armors:
    def __init__(self, records: list[U7ArmorRecord]) -> None:
        self.records = records

    @classmethod
    def from_dir(cls, static_dir: str) -> "U7Armors":
        path = _find_file(static_dir, ("armor.dat", "ARMOR.DAT"))
        return cls.from_file(str(path)) if path else cls([])

    @classmethod
    def from_file(cls, filepath: str) -> "U7Armors":
        return cls.from_bytes(Path(filepath).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7Armors":
        count, pos = _read_count(data)
        records: list[U7ArmorRecord] = []
        for _ in range(count):
            if pos + 10 > len(data):
                break
            raw = data[pos : pos + 10]
            pos += 10
            if raw[-1] == 0xFF:
                continue
            records.append(
                U7ArmorRecord(
                    shape=int.from_bytes(raw[0:2], "little"),
                    protection=raw[2],
                    immunity=raw[4],
                    raw=raw,
                )
            )
        return cls(records)

    def dump_csv(self, names: U7ShapeNames | None = None) -> str:
        return _rows_to_csv(
            [
                {
                    "shape": rec.shape,
                    "shape_hex": f"0x{rec.shape:04X}",
                    "shape_name": _name(names, rec.shape),
                    "protection": rec.protection,
                    "immunity": rec.immunity,
                    "immunity_hex": f"0x{rec.immunity:02X}",
                    "raw_hex": rec.raw.hex(),
                }
                for rec in self.records
            ]
        )


@dataclass
class U7ContainerRecord:
    shape: int
    gump_shape: int
    gump_font: int


class U7Containers:
    def __init__(self, version: int, records: list[U7ContainerRecord]) -> None:
        self.version = version
        self.records = records

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        game: str = "bg",
        exult_flx_path: str | None = None,
    ) -> "U7Containers":
        path = _find_file(static_dir, ("container.dat", "CONTAINER.DAT"))
        if path:
            return cls.from_file(str(path))
        data = _exult_record(exult_flx_path, _exult_container_record_index(game))
        return cls.from_bytes(data) if data else cls(0, [])

    @classmethod
    def from_file(cls, filepath: str) -> "U7Containers":
        return cls.from_bytes(Path(filepath).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7Containers":
        if not data:
            return cls(0, [])
        version = data[0]
        count, pos = _read_count(data, 1)
        records: list[U7ContainerRecord] = []
        for _ in range(count):
            need = 6 if version >= 2 else 4
            if pos + need > len(data):
                break
            shape = int.from_bytes(data[pos : pos + 2], "little")
            gump_shape = int.from_bytes(data[pos + 2 : pos + 4], "little")
            gump_font = (
                int.from_bytes(data[pos + 4 : pos + 6], "little", signed=True)
                if version >= 2
                else -1
            )
            pos += need
            records.append(U7ContainerRecord(shape, gump_shape, gump_font))
        return cls(version, records)

    def dump_csv(self, names: U7ShapeNames | None = None) -> str:
        return _rows_to_csv(
            [
                {
                    "shape": rec.shape,
                    "shape_hex": f"0x{rec.shape:04X}",
                    "shape_name": _name(names, rec.shape),
                    "gump_shape": rec.gump_shape,
                    "gump_shape_hex": f"0x{rec.gump_shape:04X}",
                    "gump_font": rec.gump_font,
                    "version": self.version,
                }
                for rec in self.records
            ]
        )


class U7Xforms:
    def __init__(self, tables: list[bytes]) -> None:
        self.tables = tables

    @classmethod
    def from_dir(cls, static_dir: str) -> "U7Xforms":
        path = _find_file(static_dir, ("xform.tbl", "XFORM.TBL"))
        return cls.from_file(str(path)) if path else cls([])

    @classmethod
    def from_file(cls, filepath: str) -> "U7Xforms":
        flex = U7FlexArchive.from_file(filepath)
        return cls([rec[:256] for rec in flex.records if rec])

    def dump_csv(self) -> str:
        rows: list[dict[str, object]] = []
        for table_index, table in enumerate(self.tables):
            for source_color, target_color in enumerate(table):
                rows.append(
                    {
                        "table": table_index,
                        "source_color": source_color,
                        "target_color": target_color,
                    }
                )
        return _rows_to_csv(rows)


@dataclass
class U7BlendRecord:
    index: int
    r: int
    g: int
    b: int
    alpha: int
    translucent_palette_index: int


class U7Blends:
    def __init__(self, records: list[U7BlendRecord]) -> None:
        self.records = records

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        game: str = "bg",
        exult_flx_path: str | None = None,
    ) -> "U7Blends":
        path = _find_file(static_dir, ("blends.dat", "BLENDS.DAT"))
        if path:
            return cls.from_file(str(path))
        data = _exult_record(exult_flx_path, _exult_blends_record_index(game))
        return cls.from_bytes(data) if data else cls.from_exult_hardcoded()

    @classmethod
    def from_file(cls, filepath: str) -> "U7Blends":
        return cls.from_bytes(Path(filepath).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7Blends":
        if not data:
            return cls([])
        count = data[0]
        records = []
        xfstart = 0xFF - count
        pos = 1
        for index in range(count):
            if pos + 4 > len(data):
                break
            records.append(
                U7BlendRecord(
                    index=index,
                    r=data[pos],
                    g=data[pos + 1],
                    b=data[pos + 2],
                    alpha=data[pos + 3],
                    translucent_palette_index=xfstart + index,
                )
            )
            pos += 4
        return cls(records)

    @classmethod
    def from_exult_hardcoded(cls) -> "U7Blends":
        count = len(_EXULT_HARDCODED_BLENDS)
        xfstart = 0xFF - count
        return cls(
            [
                U7BlendRecord(
                    index=index,
                    r=r,
                    g=g,
                    b=b,
                    alpha=alpha,
                    translucent_palette_index=xfstart + index,
                )
                for index, (r, g, b, alpha) in enumerate(_EXULT_HARDCODED_BLENDS)
            ]
        )

    def dump_csv(self) -> str:
        return _rows_to_csv(
            [
                {
                    "index": rec.index,
                    "r": rec.r,
                    "g": rec.g,
                    "b": rec.b,
                    "alpha": rec.alpha,
                    "translucent_palette_index": rec.translucent_palette_index,
                }
                for rec in self.records
            ]
        )


@dataclass
class U7UsecodeFunction:
    offset: int
    func_id: int
    func_id_hex: str
    func_size: int
    data_size: int
    num_args: int
    num_locals: int
    num_externs: int
    externs: list[int]
    ext32: bool


class U7UsecodeIndex:
    def __init__(self, functions: list[U7UsecodeFunction]) -> None:
        self.functions = functions

    @classmethod
    def from_file(cls, filepath: str) -> "U7UsecodeIndex":
        return cls.from_bytes(Path(filepath).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "U7UsecodeIndex":
        pos = 0
        functions: list[U7UsecodeFunction] = []
        while pos + 6 <= len(data):
            start = pos
            func_id = int.from_bytes(data[pos : pos + 2], "little")
            pos += 2
            ext32 = func_id == 0xFFFF
            if ext32:
                if pos + 10 > len(data):
                    break
                func_id = int.from_bytes(data[pos : pos + 2], "little")
                func_size = int.from_bytes(data[pos + 2 : pos + 6], "little")
                data_size = int.from_bytes(data[pos + 6 : pos + 10], "little")
                pos += 10
                header_size = 12
            else:
                if pos + 4 > len(data):
                    break
                func_size = int.from_bytes(data[pos : pos + 2], "little")
                data_size = int.from_bytes(data[pos + 2 : pos + 4], "little")
                pos += 4
                header_size = 6
            if func_size <= 0 or start + func_size + 4 > len(data):
                break
            code_header = pos + data_size
            if code_header + 6 > len(data):
                break
            num_args = int.from_bytes(data[code_header : code_header + 2], "little")
            num_locals = int.from_bytes(
                data[code_header + 2 : code_header + 4], "little"
            )
            num_externs = int.from_bytes(
                data[code_header + 4 : code_header + 6], "little"
            )
            externs_pos = code_header + 6
            externs = []
            for _ in range(num_externs):
                if externs_pos + 2 > len(data):
                    break
                externs.append(
                    int.from_bytes(data[externs_pos : externs_pos + 2], "little")
                )
                externs_pos += 2
            functions.append(
                U7UsecodeFunction(
                    offset=start,
                    func_id=func_id,
                    func_id_hex=f"0x{func_id:04X}",
                    func_size=func_size,
                    data_size=data_size,
                    num_args=num_args,
                    num_locals=num_locals,
                    num_externs=num_externs,
                    externs=externs,
                    ext32=ext32,
                )
            )
            pos = (
                start + func_size + 4
                if not ext32
                else start + func_size + header_size - 2
            )
        return cls(functions)

    def dump_csv(self) -> str:
        return _rows_to_csv(
            [
                {
                    "offset": fn.offset,
                    "offset_hex": f"0x{fn.offset:08X}",
                    "func_id": fn.func_id,
                    "func_id_hex": fn.func_id_hex,
                    "func_size": fn.func_size,
                    "data_size": fn.data_size,
                    "num_args": fn.num_args,
                    "num_locals": fn.num_locals,
                    "num_externs": fn.num_externs,
                    "externs": "|".join(f"0x{value:04X}" for value in fn.externs),
                    "ext32": int(fn.ext32),
                }
                for fn in self.functions
            ]
        )
