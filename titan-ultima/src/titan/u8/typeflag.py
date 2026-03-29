"""
TYPEFLAG.DAT parser for Ultima 8.

Provides :class:`U8TypeFlags` for decoding shape metadata from
TYPEFLAG.DAT (physics, flags, footpad dimensions, etc.).

Example::

    from titan.typeflag import U8TypeFlags

    entries = U8TypeFlags.from_file("TYPEFLAG.DAT")
    for e in entries:
        if e.is_container():
            print(f"Shape {e.shape_num}: {e.flag_names()}")
"""

from __future__ import annotations

__all__ = ["U8TypeFlags"]

import os
import struct
from dataclasses import dataclass


class U8TypeFlags:
    """
    Full parser for TYPEFLAG.DAT (U8 format: 8 bytes per shape, up to 2048).

    Based on graphics/TypeFlags.cpp and graphics/ShapeInfo.h.
    Decodes all fields from the original 8-byte records.
    """

    # Bit flags from ShapeInfo.h (SFlags enum)
    FLAG_NAMES: dict[int, str] = {
        0x0001: "SI_FIXED",
        0x0002: "SI_SOLID",
        0x0004: "SI_SEA",
        0x0008: "SI_LAND",
        0x0010: "SI_OCCL",
        0x0020: "SI_BAG",
        0x0040: "SI_DAMAGING",
        0x0080: "SI_NOISY",
        0x0100: "SI_DRAW",
        0x0200: "SI_IGNORE",
        0x0400: "SI_ROOF",
        0x0800: "SI_TRANSL",
        0x1000: "SI_EDITOR",
        0x2000: "SI_EXPLODE",
        0x4000: "SI_UNKNOWN46",
        0x8000: "SI_UNKNOWN47",
    }

    # Family names from ShapeInfo.h (SFamily enum)
    FAMILY_NAMES: dict[int, str] = {
        0: "generic",
        1: "quality",
        2: "quantity",
        3: "globegg",
        4: "unkegg",
        5: "breakable",
        6: "container",
        7: "monsteregg",
        8: "teleportegg",
        9: "reagent",
        15: "sf_15",
    }

    # Equip type names from ShapeInfo.h (SEquipType enum)
    EQUIP_NAMES: dict[int, str] = {
        0: "none",
        1: "shield",
        2: "arm",
        3: "head",
        4: "body",
        5: "legs",
        6: "weapon",
    }

    @dataclass
    class ShapeEntry:
        """Decoded typeflag entry for a single shape."""

        shape_num: int
        flags: int
        family: int
        equiptype: int
        x: int  # footpad X dimension
        y: int  # footpad Y dimension
        z: int  # footpad Z dimension
        animtype: int
        animdata: int
        unknown: int  # byte 5, low nibble
        weight: int
        volume: int

        def flag_names(self) -> list[str]:
            """Return list of set flag names."""
            return [name for bit, name in U8TypeFlags.FLAG_NAMES.items()
                    if self.flags & bit]

        def family_name(self) -> str:
            """Return the human-readable family name."""
            return U8TypeFlags.FAMILY_NAMES.get(self.family, f"unk_{self.family}")

        def equip_name(self) -> str:
            """Return the human-readable equip-type name."""
            return U8TypeFlags.EQUIP_NAMES.get(self.equiptype, f"unk_{self.equiptype}")

        def is_fixed(self) -> bool:
            """Whether this shape has the SI_FIXED flag."""
            return bool(self.flags & 0x0001)

        def is_solid(self) -> bool:
            """Whether this shape has the SI_SOLID flag."""
            return bool(self.flags & 0x0002)

        def is_container(self) -> bool:
            """Whether this shape is a container (family == 6)."""
            return self.family == 6

        def footpad_world(self, flipped: bool = False) -> tuple[int, int, int]:
            """World-unit footpad ``(X*32, Y*32, Z*8)``, as ShapeInfo::getFootpadWorld."""
            zw = self.z * 8
            if flipped:
                return (self.y * 32, self.x * 32, zw)
            return (self.x * 32, self.y * 32, zw)

    @classmethod
    def from_file(cls, filepath: str) -> list[U8TypeFlags.ShapeEntry]:
        """Load and parse TYPEFLAG.DAT."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.parse(data)

    @classmethod
    def parse(cls, data: bytes) -> list[U8TypeFlags.ShapeEntry]:
        """
        Parse raw TYPEFLAG.DAT bytes into ShapeEntry list.

        Layout per shape (8 bytes)::

            Byte 0: flags low byte (FIXED, SOLID, SEA, LAND, OCCL, BAG, DAMAGING, NOISY)
            Byte 1: bits 0-3 = flags high (DRAW, IGNORE, ROOF, TRANSL), bits 4-7 = family
            Byte 2: bits 0-3 = equip type, bits 4-7 = X footpad
            Byte 3: bits 0-3 = Y footpad, bits 4-7 = Z footpad
            Byte 4: bits 0-3 = anim type, bits 4-7 = anim data
            Byte 5: bits 0-3 = unknown, bit 4=EDITOR, bit 5=EXPLODE, bit 6=UNK46, bit 7=UNK47
            Byte 6: weight (0-255)
            Byte 7: volume (0-255)
        """
        block = 8
        count = len(data) // block
        entries: list[U8TypeFlags.ShapeEntry] = []

        for i in range(count):
            off = i * block
            d = data[off:off + 8]

            # Byte 0: low flags
            flags = d[0]
            # Byte 1: high flags (bits 0-3) + family (bits 4-7)
            flags |= (d[1] & 0x0F) << 8
            family = d[1] >> 4
            # Byte 2: equip type (bits 0-3) + X (bits 4-7)
            equiptype = d[2] & 0x0F
            x = d[2] >> 4
            # Byte 3: Y (bits 0-3) + Z (bits 4-7)
            y = d[3] & 0x0F
            z = d[3] >> 4
            # Byte 4: animtype (bits 0-3) + animdata (bits 4-7)
            animtype = d[4] & 0x0F
            animdata = d[4] >> 4
            # Byte 5: unknown (bits 0-3) + high flags (bits 4-7)
            unknown = d[5] & 0x0F
            if d[5] & 0x10:
                flags |= 0x1000  # SI_EDITOR
            if d[5] & 0x20:
                flags |= 0x2000  # SI_EXPLODE
            if d[5] & 0x40:
                flags |= 0x4000  # SI_UNKNOWN46
            if d[5] & 0x80:
                flags |= 0x8000  # SI_UNKNOWN47
            # Bytes 6-7
            weight = d[6]
            volume = d[7]

            entries.append(cls.ShapeEntry(
                shape_num=i,
                flags=flags,
                family=family,
                equiptype=equiptype,
                x=x, y=y, z=z,
                animtype=animtype,
                animdata=animdata,
                unknown=unknown,
                weight=weight,
                volume=volume,
            ))

        return entries

    @classmethod
    def container_shapes(cls, data: bytes) -> set[int]:
        """Return set of shape numbers that are containers (family == 6)."""
        block = 8
        result: set[int] = set()
        for i in range(len(data) // block):
            family = data[i * block + 1] >> 4
            if family == 6:
                result.add(i)
        return result
