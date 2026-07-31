"""Ultima Online tiledata.mul metadata support."""

from __future__ import annotations

__all__ = ["UOLandTile", "UOStaticTile", "UOTileData"]

from dataclasses import dataclass
from pathlib import Path
import struct

_LAND_COUNT = 0x4000
_GROUP_SIZE = 32
_LAND_GROUPS = _LAND_COUNT // _GROUP_SIZE
_OLD_LAND_RECORD_SIZE = 26
_NEW_LAND_RECORD_SIZE = 30
_OLD_STATIC_RECORD_SIZE = 37
_NEW_STATIC_RECORD_SIZE = 41
_FLAG_NAMES = (
    (0x00000001, "background"),
    (0x00000002, "weapon"),
    (0x00000004, "transparent"),
    (0x00000008, "translucent"),
    (0x00000010, "wall"),
    (0x00000020, "damaging"),
    (0x00000040, "impassable"),
    (0x00000080, "wet"),
    (0x00000100, "unknown1"),
    (0x00000200, "surface"),
    (0x00000400, "bridge"),
    (0x00000800, "generic"),
    (0x00001000, "window"),
    (0x00002000, "no_shoot"),
    (0x00004000, "article_a"),
    (0x00008000, "article_an"),
    (0x00010000, "internal"),
    (0x00020000, "foliage"),
    (0x00040000, "partial_hue"),
    (0x00080000, "no_house"),
    (0x00100000, "map"),
    (0x00200000, "container"),
    (0x00400000, "wearable"),
    (0x00800000, "light_source"),
    (0x01000000, "animation"),
    (0x02000000, "no_diagonal"),
    (0x04000000, "unknown2"),
    (0x08000000, "armor"),
    (0x10000000, "roof"),
    (0x20000000, "door"),
    (0x40000000, "stair_back"),
    (0x80000000, "stair_right"),
    (0x0100000000, "alpha_blend"),
    (0x0200000000, "use_new_art"),
    (0x0400000000, "art_used"),
    (0x1000000000, "no_shadow"),
    (0x2000000000, "pixel_bleed"),
    (0x4000000000, "play_anim_once"),
    (0x10000000000, "multi_movable"),
)


@dataclass(frozen=True)
class UOLandTile:
    """One land record from tiledata.mul."""

    tile_id: int
    flags: int
    texture_id: int
    name: str

    @property
    def flag_names(self) -> tuple[str, ...]:
        return flag_names(self.flags)


@dataclass(frozen=True)
class UOStaticTile:
    """One static/item record from tiledata.mul."""

    tile_id: int
    flags: int
    weight: int
    quality: int
    misc_data: int
    unknown2: int
    quantity: int
    anim_id: int
    unknown3: int
    hue: int
    stacking_offset: int
    value: int
    height: int
    name: str

    @property
    def flag_names(self) -> tuple[str, ...]:
        return flag_names(self.flags)


class UOTileData:
    """Parsed tiledata.mul land and static/item metadata."""

    def __init__(
        self,
        *,
        is_new_format: bool,
        land: list[UOLandTile],
        statics: list[UOStaticTile],
    ) -> None:
        self.is_new_format = is_new_format
        self.land = land
        self.statics = statics
        self.land_by_texture = self._build_land_by_texture()

    @classmethod
    def from_file(cls, path: str | Path) -> UOTileData:
        data = Path(path).read_bytes()
        is_new = _detect_new_format(len(data))
        land_record_size = _NEW_LAND_RECORD_SIZE if is_new else _OLD_LAND_RECORD_SIZE
        static_record_size = (
            _NEW_STATIC_RECORD_SIZE if is_new else _OLD_STATIC_RECORD_SIZE
        )
        land_flag_size = 8 if is_new else 4
        static_flag_size = 8 if is_new else 4

        land: list[UOLandTile] = []
        pos = 0
        for group in range(_LAND_GROUPS):
            pos += 4
            for index_in_group in range(_GROUP_SIZE):
                tile_id = group * _GROUP_SIZE + index_in_group
                flags = _read_flags(data, pos, land_flag_size)
                texture_offset = pos + land_flag_size
                texture_id = struct.unpack_from("<H", data, texture_offset)[0]
                name = _read_name(data, texture_offset + 2)
                land.append(UOLandTile(tile_id, flags, texture_id, name))
                pos += land_record_size

        if is_new and land:
            land[0] = UOLandTile(
                0,
                _read_flags(data, 0, land_flag_size),
                struct.unpack_from("<H", data, land_flag_size)[0],
                _read_name(data, land_flag_size + 2),
            )

        statics: list[UOStaticTile] = []
        static_group_size = 4 + (_GROUP_SIZE * static_record_size)
        if (len(data) - pos) % static_group_size:
            raise ValueError("tiledata static section has unexpected length")

        static_groups = (len(data) - pos) // static_group_size
        for group in range(static_groups):
            pos += 4
            for index_in_group in range(_GROUP_SIZE):
                tile_id = group * _GROUP_SIZE + index_in_group
                flags = _read_flags(data, pos, static_flag_size)
                fields_offset = pos + static_flag_size
                weight = data[fields_offset]
                quality = data[fields_offset + 1]
                misc_data = struct.unpack_from("<h", data, fields_offset + 2)[0]
                unknown2 = data[fields_offset + 4]
                quantity = data[fields_offset + 5]
                anim_id = struct.unpack_from("<H", data, fields_offset + 6)[0]
                unknown3 = data[fields_offset + 8]
                hue = data[fields_offset + 9]
                stacking_offset = data[fields_offset + 10]
                value = data[fields_offset + 11]
                height = data[fields_offset + 12]
                name = _read_name(data, fields_offset + 13)
                statics.append(
                    UOStaticTile(
                        tile_id,
                        flags,
                        weight,
                        quality,
                        misc_data,
                        unknown2,
                        quantity,
                        anim_id,
                        unknown3,
                        hue,
                        stacking_offset,
                        value,
                        height,
                        name,
                    )
                )
                pos += static_record_size

        return cls(is_new_format=is_new, land=land, statics=statics)

    def _build_land_by_texture(self) -> dict[int, list[UOLandTile]]:
        by_texture: dict[int, list[UOLandTile]] = {}
        for tile in self.land:
            by_texture.setdefault(tile.texture_id, []).append(tile)
        return by_texture


def flag_names(flags: int) -> tuple[str, ...]:
    """Return known flag names set in a tiledata flag bitfield."""
    return tuple(name for bit, name in _FLAG_NAMES if flags & bit)


def _detect_new_format(length: int) -> bool:
    old_land_bytes = _LAND_GROUPS * (4 + _GROUP_SIZE * _OLD_LAND_RECORD_SIZE)
    new_land_bytes = _LAND_GROUPS * (4 + _GROUP_SIZE * _NEW_LAND_RECORD_SIZE)
    old_static_group = 4 + _GROUP_SIZE * _OLD_STATIC_RECORD_SIZE
    new_static_group = 4 + _GROUP_SIZE * _NEW_STATIC_RECORD_SIZE

    if length >= new_land_bytes and (length - new_land_bytes) % new_static_group == 0:
        return True
    if length >= old_land_bytes and (length - old_land_bytes) % old_static_group == 0:
        return False
    raise ValueError("unrecognized tiledata.mul length/layout")


def _read_flags(data: bytes, offset: int, size: int) -> int:
    if size == 8:
        return struct.unpack_from("<Q", data, offset)[0]
    return struct.unpack_from("<I", data, offset)[0]


def _read_name(data: bytes, offset: int) -> str:
    return (
        data[offset : offset + 20].split(b"\0", 1)[0].decode("utf-8", errors="replace")
    )
