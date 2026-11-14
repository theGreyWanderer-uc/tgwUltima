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

from dataclasses import dataclass, replace
from pathlib import Path

from titan.u7.flex import U7FlexArchive
from titan.u7.gameplay_metadata import (
    U7GameplayMetadata,
    U7GameplayTable,
    U7GameplayFormat,
    read_gameplay_table,
)
from titan.u7.names import U7ShapeNames
from titan.u7.usecode import U7UsecodeFile
from titan.u7.combat_metadata import U7CombatMetadata
from titan._files import rows_to_csv


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


def _retail_power_names(value: int) -> str:
    """Recovered retail weapon/ammo power bit names; effect details still differ between BG/SI."""
    names = (
        "sleep",
        "charm",
        "curse",
        "poison",
        "paralyze",
        "drain_mana",
        "drain_health",
        "no_damage",
    )
    return "|".join(name for bit, name in enumerate(names) if value & (1 << bit))


_DAMAGE_TYPE_NAMES = {
    0: "normal",
    1: "fire",
    2: "magic",
    3: "lightning",
    4: "ethereal",
    5: "sonic",
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
    need_target: bool | None
    missile_speed: int | None
    rotation_speed: int
    actor_frames: int
    powers: int
    usecode: int
    sfx: int | None
    hitsfx: int | None
    raw: bytes
    data_format: U7GameplayFormat = "exult"
    game: str = "bg"

    @property
    def retail_damage(self) -> int:
        """Original BG/SI WeaponRecord.damage is signed char, independently of the selected view."""
        return int.from_bytes(self.raw[6:7], "little", signed=True)

    @property
    def retail_sound_byte(self) -> int:
        """Retail stores one sound byte; offsets 16..20 are padding, not Exult's sound words."""
        return self.raw[15]

    @property
    def retail_sfx_script_byte(self) -> int | None:
        """Zero disables the ranged sound; BG emits byte(sound-1), SI emits byte(sound)."""
        if not self.retail_sound_byte:
            return None
        return (self.retail_sound_byte - (self.game.lower() == "bg")) & 255

    @property
    def retail_homing(self) -> bool:
        """Retail missile tracking uses bit 1 at offset 9; Exult calls it need_target."""
        return bool(self.raw[9] & 2)

    @property
    def retail_missile_speed_code(self) -> int:
        """Retain the retail two-bit code without applying Exult's derived-speed conversion."""
        return (self.raw[9] >> 2) & 3

    @property
    def retail_frame_step(self) -> int:
        """Raw four-bit retail sprite-frame increment."""
        return self.raw[9] >> 4

    @property
    def retail_speed(self) -> int:
        """Raw three-bit retail speed selector; this is not a duration."""
        return self.raw[10] >> 5

    @property
    def retail_power_names(self) -> str:
        """The recovered retail power bit names differ from Exult for mana/health drain."""
        return _retail_power_names(self.powers)


class U7Weapons(U7GameplayMetadata):
    world_metadata: U7CombatMetadata | None = None

    def __init__(
        self,
        records: list[U7WeaponRecord],
        table: U7GameplayTable | None = None,
        *,
        data_format: U7GameplayFormat = "exult",
    ) -> None:
        super().__init__(table, data_format=data_format)
        self.records = records

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        game: str = "bg",
        *,
        patch_dir: str | Path | None = None,
        data_format: U7GameplayFormat = "exult",
    ) -> "U7Weapons":
        world = U7CombatMetadata.from_dir(
            "weapon",
            static_dir,
            patch_dir=patch_dir,
            strict=patch_dir is not None,
            data_format=data_format,
        )
        result = (
            cls.from_bytes(world.resolved_bytes(), game=game, data_format=data_format)
            if world.layers
            else cls([], data_format=data_format)
        )
        result.world_metadata = world
        result._source_warnings.extend(world.warnings)
        return result

    @classmethod
    def from_file(
        cls, filepath: str, game: str = "bg", *, data_format: U7GameplayFormat = "exult"
    ) -> "U7Weapons":
        return cls.from_bytes(
            Path(filepath).read_bytes(), game=game, data_format=data_format
        )

    @classmethod
    def from_bytes(
        cls, data: bytes, game: str = "bg", *, data_format: U7GameplayFormat = "exult"
    ) -> "U7Weapons":
        table = read_gameplay_table(data, 21, "WEAPONS.DAT", data_format=data_format)
        records: list[U7WeaponRecord] = []
        for raw in table.records:
            if data_format == "exult" and raw[-1] == 0xFF:
                continue
            shape = int.from_bytes(raw[0:2], "little")
            ammo = int.from_bytes(raw[2:4], "little", signed=True)
            projectile = int.from_bytes(raw[4:6], "little", signed=True)
            damage = (
                int.from_bytes(raw[6:7], "little", signed=True)
                if data_format == "retail"
                else raw[6]
            )
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
                    need_target=bool(flags1 & 0x02) if data_format == "exult" else None,
                    missile_speed=missile_speed if data_format == "exult" else None,
                    rotation_speed=(flags1 >> 4) & 15,
                    actor_frames=flags2 & 15,
                    powers=raw[11],
                    usecode=int.from_bytes(
                        raw[13:15], "little", signed=data_format == "retail"
                    ),
                    sfx=(int.from_bytes(raw[15:17], "little", signed=True) + sfx_delta)
                    if data_format == "exult"
                    else ((raw[15] + sfx_delta) & 255)
                    if raw[15]
                    else None,
                    hitsfx=int.from_bytes(raw[17:19], "little", signed=True) + sfx_delta
                    if data_format == "exult"
                    else None,
                    raw=raw,
                    data_format=data_format,
                    game=game,
                )
            )
        return cls(records, table)

    def dump_csv(self, names: U7ShapeNames | None = None) -> str:
        rows: list[dict[str, object]] = [
            {
                "shape": rec.shape,
                "data_format": self.data_format,
                "shape_hex": f"0x{rec.shape:04X}",
                "shape_name": _name(names, rec.shape),
                "ammo": rec.ammo,
                "projectile": rec.projectile,
                "damage": rec.damage,
                "retail_damage": rec.retail_damage,
                "exult_damage": rec.raw[6],
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
                "need_target": int(rec.need_target)
                if rec.need_target is not None
                else None,
                "missile_speed": rec.missile_speed,
                "rotation_speed": rec.rotation_speed,
                "actor_frames": rec.actor_frames,
                "powers": rec.powers,
                "power_names": rec.retail_power_names
                if self.data_format == "retail"
                else _power_names(rec.powers),
                "retail_power_names": rec.retail_power_names,
                "usecode": rec.usecode,
                "usecode_hex": f"0x{rec.usecode & 65535:04X}",
                "sfx": rec.sfx,
                "hitsfx": rec.hitsfx,
                "retail_sound_byte": rec.retail_sound_byte,
                "retail_sfx_script_byte": rec.retail_sfx_script_byte,
                "retail_homing": int(rec.retail_homing),
                "retail_missile_speed_code": rec.retail_missile_speed_code,
                "retail_frame_step": rec.retail_frame_step,
                "retail_speed": rec.retail_speed,
                "retail_melee_ready_frame": int(bool(rec.raw[10] & 1)),
                "retail_melee_strike_frame": int(bool(rec.raw[10] & 2)),
                "retail_ranged_ready_frame": int(bool(rec.raw[10] & 4)),
                "retail_ranged_strike_frame": int(bool(rec.raw[10] & 8)),
                "retail_padding_hex": rec.raw[16:21].hex(),
                "raw_hex": rec.raw.hex(),
            }
            for rec in self.records
        ]
        return rows_to_csv(rows)


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
    homing: bool | None
    drop_type: int | None
    explodes: bool
    damage_type: int
    powers: int
    raw: bytes
    data_format: U7GameplayFormat = "exult"

    @property
    def family_word(self) -> int:
        """Unsigned on-disk value, also the value loaded by the examined Exult reader."""
        return self.family_shape & 0xFFFF

    @property
    def sprite_word(self) -> int:
        """Keep the word distinct from the retail signed selector interpretation."""
        return self.sprite_shape & 0xFFFF

    @property
    def reference_interpretation(self) -> str:
        return (
            "signed_unsigned_disagree"
            if (self.family_word | self.sprite_word) & 0x8000
            else "signed_unsigned_agree"
        )

    @property
    def signed_sprite_meaning(self) -> str:
        """Compatibility labels for the signed selector, verified in retail BG/SI attack code."""
        if self.sprite_shape == -3:
            return "ammo_item_shape"
        if self.sprite_shape == -1 or self.sprite_shape == self.family_shape:
            return "keep_weapon_projectile"
        if self.sprite_shape < 0:
            return "unknown_negative_selector"
        return "explicit_shape"

    @property
    def retail_sprite_meaning(self) -> str:
        """Retail recognizes -1/-3 and family equality; other words pass to shape creation."""
        if self.signed_sprite_meaning == "unknown_negative_selector":
            return "literal_projectile_word"
        return self.signed_sprite_meaning

    @property
    def retail_damage(self) -> int:
        """Retail AmmoRecord.damage is signed char; Exult and the legacy damage field are unsigned."""
        return int.from_bytes(self.raw[6:7], "little", signed=True)

    @property
    def retail_remove_on_stop(self) -> bool:
        """Stored retail removal request, before weapon and collision-state rules."""
        return bool(self.raw[7] & 16)

    @property
    def retail_keep_on_stop(self) -> bool:
        """Stored retail retention request, independent of the removal bit."""
        return bool(self.raw[7] & 32)

    @property
    def retail_continuous(self) -> bool:
        """Both stop bits request continuous tracking; this is not Exult's homing label."""
        return self.retail_remove_on_stop and self.retail_keep_on_stop

    @property
    def retail_power_names(self) -> str:
        return _retail_power_names(self.powers)

    def resolve_retail_attack_projectile(self, weapon_projectile: int) -> int:
        """Apply only the AMMO override to an already selected weapon projectile.

        The caller resolves WEAPONS -3 first. The retail attack routine later
        normalizes a remaining -1 to zero. Egg firing has different precedence
        and uses the egg's packed type/frame for -3; this method is not that path.
        """
        if self.sprite_shape == -3:
            return self.shape
        if self.sprite_shape == -1 or self.sprite_shape == self.family_shape:
            return weapon_projectile
        return self.sprite_shape


class U7Ammos(U7GameplayMetadata):
    world_metadata: U7CombatMetadata | None = None

    def __init__(
        self,
        records: list[U7AmmoRecord],
        table: U7GameplayTable | None = None,
        *,
        data_format: U7GameplayFormat = "exult",
    ) -> None:
        super().__init__(table, data_format=data_format)
        self.records = records

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        *,
        patch_dir: str | Path | None = None,
        data_format: U7GameplayFormat = "exult",
    ) -> "U7Ammos":
        world = U7CombatMetadata.from_dir(
            "ammo",
            static_dir,
            patch_dir=patch_dir,
            strict=patch_dir is not None,
            data_format=data_format,
        )
        result = (
            cls.from_bytes(world.resolved_bytes(), data_format=data_format)
            if world.layers
            else cls([], data_format=data_format)
        )
        result.world_metadata = world
        result._source_warnings.extend(world.warnings)
        return result

    @classmethod
    def from_file(
        cls, filepath: str, *, data_format: U7GameplayFormat = "exult"
    ) -> "U7Ammos":
        return cls.from_bytes(Path(filepath).read_bytes(), data_format=data_format)

    @classmethod
    def from_bytes(
        cls, data: bytes, *, data_format: U7GameplayFormat = "exult"
    ) -> "U7Ammos":
        table = read_gameplay_table(data, 13, "AMMO.DAT", data_format=data_format)
        records: list[U7AmmoRecord] = []
        for raw in table.records:
            if data_format == "exult" and raw[-1] == 0xFF:
                continue
            flags0 = raw[7]
            homing = ((flags0 >> 4) & 3) == 3
            records.append(
                U7AmmoRecord(
                    shape=int.from_bytes(raw[0:2], "little"),
                    family_shape=int.from_bytes(raw[2:4], "little", signed=True),
                    sprite_shape=int.from_bytes(raw[4:6], "little", signed=True),
                    damage=int.from_bytes(raw[6:7], "little", signed=True)
                    if data_format == "retail"
                    else raw[6],
                    lucky=bool(flags0 & 0x01),
                    autohit=bool(flags0 & 0x02),
                    returns=bool(flags0 & 0x04),
                    no_blocking=bool(flags0 & 0x08),
                    homing=homing if data_format == "exult" else None,
                    drop_type=(0 if homing else (flags0 >> 4) & 3)
                    if data_format == "exult"
                    else None,
                    explodes=bool(flags0 & 0x40),
                    damage_type=(raw[9] >> 4) & 15,
                    powers=raw[10],
                    raw=raw,
                    data_format=data_format,
                )
            )
        result = cls(records, table)
        for record in records:
            if record.reference_interpretation == "signed_unsigned_disagree":
                result._source_warnings.append(
                    f"AMMO.DAT shape {record.shape}: high-bit reference words "
                    f"family=0x{record.family_word:04X}, sprite=0x{record.sprite_word:04X}; "
                    "Titan's signed interpretation differs from Exult's unsigned binary loader. "
                    "Retail BG/SI signed i16 decoding is verified; both interpretations are exported."
                )
            if record.retail_damage != record.raw[6]:
                result._source_warnings.append(
                    f"AMMO.DAT shape {record.shape}: damage byte 0x{record.raw[6]:02X} "
                    f"is {record.retail_damage} in retail BG/SI and {record.raw[6]} in Exult."
                )
        return result

    def dump_csv(self, names: U7ShapeNames | None = None) -> str:
        rows = []
        for rec in self.records:
            rows.append(
                {
                    "shape": rec.shape,
                    "shape_hex": f"0x{rec.shape:04X}",
                    "shape_name": _name(names, rec.shape),
                    "family_shape": rec.family_shape,
                    "data_format": self.data_format,
                    "family_word": rec.family_word,
                    "exult_loaded_family_shape": rec.family_word,
                    "family_name": _name(names, rec.family_shape),
                    "sprite_shape": rec.sprite_shape,
                    "sprite_word": rec.sprite_word,
                    "exult_loaded_sprite_shape": rec.sprite_word,
                    "reference_interpretation": rec.reference_interpretation,
                    "signed_sprite_meaning": rec.signed_sprite_meaning,
                    "retail_sprite_meaning": rec.retail_sprite_meaning,
                    "sprite_name": _name(names, rec.sprite_shape),
                    "damage": rec.damage,
                    "retail_damage": rec.retail_damage,
                    "exult_damage": rec.raw[6],
                    "damage_type": rec.damage_type,
                    "damage_type_name": _DAMAGE_TYPE_NAMES.get(rec.damage_type, ""),
                    "lucky": int(rec.lucky),
                    "autohit": int(rec.autohit),
                    "returns": int(rec.returns),
                    "no_blocking": int(rec.no_blocking),
                    "homing": int(rec.homing) if rec.homing is not None else None,
                    "drop_type": rec.drop_type,
                    "drop_type_name": _AMMO_DROP_NAMES.get(rec.drop_type, "")
                    if rec.drop_type is not None
                    else "",
                    "retail_remove_on_stop": int(rec.retail_remove_on_stop),
                    "retail_keep_on_stop": int(rec.retail_keep_on_stop),
                    "retail_continuous": int(rec.retail_continuous),
                    "explodes": int(rec.explodes),
                    "powers": rec.powers,
                    "power_names": rec.retail_power_names
                    if self.data_format == "retail"
                    else _power_names(rec.powers),
                    "retail_power_names": rec.retail_power_names,
                    "raw_hex": rec.raw.hex(),
                }
            )
        return rows_to_csv(rows)


@dataclass
class U7ArmorRecord:
    shape: int
    protection: int
    immunity: int
    raw: bytes


class U7Armors(U7GameplayMetadata):
    world_metadata: U7CombatMetadata | None = None

    def __init__(
        self,
        records: list[U7ArmorRecord],
        table: U7GameplayTable | None = None,
        *,
        data_format: U7GameplayFormat = "exult",
    ) -> None:
        super().__init__(table, data_format=data_format)
        self.records = records

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        *,
        patch_dir: str | Path | None = None,
        data_format: U7GameplayFormat = "exult",
    ) -> "U7Armors":
        world = U7CombatMetadata.from_dir(
            "armor",
            static_dir,
            patch_dir=patch_dir,
            strict=patch_dir is not None,
            data_format=data_format,
        )
        result = (
            cls.from_bytes(world.resolved_bytes(), data_format=data_format)
            if world.layers
            else cls([], data_format=data_format)
        )
        result.world_metadata = world
        result._source_warnings.extend(world.warnings)
        return result

    @classmethod
    def from_file(
        cls, filepath: str, *, data_format: U7GameplayFormat = "exult"
    ) -> "U7Armors":
        return cls.from_bytes(Path(filepath).read_bytes(), data_format=data_format)

    @classmethod
    def from_bytes(
        cls, data: bytes, *, data_format: U7GameplayFormat = "exult"
    ) -> "U7Armors":
        table = read_gameplay_table(data, 10, "ARMOR.DAT", data_format=data_format)
        records: list[U7ArmorRecord] = []
        for raw in table.records:
            if data_format == "exult" and raw[-1] == 0xFF:
                continue
            records.append(
                U7ArmorRecord(
                    shape=int.from_bytes(raw[0:2], "little"),
                    protection=raw[2],
                    immunity=raw[4],
                    raw=raw,
                )
            )
        return cls(records, table)

    def dump_csv(self, names: U7ShapeNames | None = None) -> str:
        return rows_to_csv(
            [
                {
                    "shape": rec.shape,
                    "shape_hex": f"0x{rec.shape:04X}",
                    "shape_name": _name(names, rec.shape),
                    "protection": rec.protection,
                    "data_format": self.data_format,
                    "immunity": rec.immunity,
                    "immunity_hex": f"0x{rec.immunity:02X}",
                    "raw_hex": rec.raw.hex(),
                }
                for rec in self.records
            ]
        )


@dataclass
class U7ContainerRecord:
    """Signed container gump binding with the complete original record retained."""

    shape: int
    gump_shape: int
    gump_font: int
    raw: bytes = b""
    source: str = ""
    offset: int = 0
    version: int = 0

    @property
    def gump_shape_raw(self) -> int:
        """Return the unsigned disk word separately from the semantic signed gump ID."""
        return self.gump_shape & 65535


class U7Containers(U7GameplayMetadata):
    """Versioned container bindings with raw bytes and count/extent diagnostics."""

    def __init__(
        self,
        version: int,
        records: list[U7ContainerRecord],
        table: U7GameplayTable | None = None,
    ) -> None:
        super().__init__(table)
        self.version = version
        self.records = records
        self.source_tables = [table] if table is not None else []

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        game: str = "bg",
        exult_flx_path: str | None = None,
        *,
        patch_dir: str | Path | None = None,
        custom_game: bool = False,
    ) -> "U7Containers":
        """Resolve engine defaults then patch; use from_file for explicit loose-file inspection."""
        from titan.u7.gump_metadata import load_u7_gump_sources

        sources = load_u7_gump_sources(
            static_dir,
            patch_dir=patch_dir,
            game=game,
            exult_flx=exult_flx_path,
            custom_game=custom_game,
        )
        layers = [
            cls.from_bytes(layer.data, source=layer.source, strict=True)
            for layer in sources.layers
            if layer.name == "CONTAINER.DAT"
        ]
        result = cls.merge(*layers)
        result._source_warnings.extend(sources.warnings)
        return result

    @classmethod
    def from_file(cls, filepath: str, *, strict: bool = False) -> "U7Containers":
        """Inspect the explicitly selected file independently of engine resource precedence."""
        return cls.from_bytes(
            Path(filepath).read_bytes(), source=filepath, strict=strict
        )

    @classmethod
    def from_bytes(
        cls, data: bytes, *, source: str = "", strict: bool = False
    ) -> "U7Containers":
        """Decode versioned records; strict mode rejects incomplete headers/records, retaining tails."""
        version = data[0] if data else 0
        width = 6 if version >= 2 else 4
        table = read_gameplay_table(data[1:], width, "CONTAINER.DAT")
        table = replace(table, raw=data, header_size=table.header_size + bool(data))
        if strict and (
            table.declared_count is None or table.parsed_count != table.declared_count
        ):
            raise ValueError(
                f"Incomplete container table in {source or 'input'}: {'; '.join(table.warnings)}"
            )
        records = [
            U7ContainerRecord(
                int.from_bytes(raw[:2], "little"),
                int.from_bytes(raw[2:4], "little", signed=True),
                int.from_bytes(raw[4:6], "little", signed=True) if version >= 2 else -1,
                raw,
                source,
                table.header_size + index * width,
                version,
            )
            for index, raw in enumerate(table.records)
        ]
        return cls(version, records, table)

    @classmethod
    def merge(cls, *layers: "U7Containers") -> "U7Containers":
        """Resolve ordered full-row assignments, including negatives, while retaining all source tables."""
        rows: dict[int, U7ContainerRecord] = {}
        for layer in layers:
            rows.update((row.shape, row) for row in layer.records)
        result = cls(layers[-1].version if layers else 0, list(rows.values()))
        result.source_tables = [
            table for layer in layers for table in layer.source_tables
        ]
        result._source_warnings = [
            warning for layer in layers for warning in layer.warnings
        ]
        return result

    def dump_csv(self, names: U7ShapeNames | None = None) -> str:
        return rows_to_csv(
            [
                {
                    "shape": rec.shape,
                    "shape_hex": f"0x{rec.shape:04X}",
                    "shape_name": _name(names, rec.shape),
                    "gump_shape": rec.gump_shape,
                    "gump_shape_hex": f"0x{rec.gump_shape_raw:04X}",
                    "gump_shape_raw": rec.gump_shape_raw,
                    "gump_font": rec.gump_font,
                    "version": rec.version if rec.raw else self.version,
                    "raw_hex": rec.raw.hex(),
                    "source": rec.source,
                    "offset": rec.offset,
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
        return rows_to_csv(rows)


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
        return rows_to_csv(
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
    """Compatibility metadata view backed by the shared executable Usecode reader."""

    def __init__(
        self,
        functions: list[U7UsecodeFunction],
        *,
        warnings: list[str] | None = None,
        parsed_bytes: int = 0,
        complete: bool = True,
    ) -> None:
        self.functions = functions
        self.warnings = list(warnings or ())
        self.parsed_bytes = parsed_bytes
        self.complete = complete

    @classmethod
    def from_file(cls, filepath: str, *, strict: bool = False) -> "U7UsecodeIndex":
        return cls.from_bytes(Path(filepath).read_bytes(), strict=strict)

    @classmethod
    def from_bytes(cls, data: bytes, *, strict: bool = False) -> "U7UsecodeIndex":
        usecode = U7UsecodeFile.from_bytes(data, strict=strict)
        functions = [
            U7UsecodeFunction(
                offset=fn.offset,
                func_id=fn.func_id,
                func_id_hex=f"0x{fn.func_id:04X}",
                func_size=fn.func_size,
                data_size=fn.data_size,
                num_args=fn.num_args,
                num_locals=fn.num_locals,
                num_externs=fn.num_externs,
                externs=list(fn.externs),
                ext32=fn.ext32,
            )
            for fn in usecode.functions
        ]
        return cls(
            functions,
            warnings=usecode.warnings,
            parsed_bytes=usecode.parsed_bytes,
            complete=usecode.complete,
        )

    def dump_csv(self) -> str:
        return rows_to_csv(
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
