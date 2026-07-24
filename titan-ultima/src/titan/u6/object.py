"""
World object placement decoder for Ultima 6 (``LZOBJBLK`` + ``LZDNGBLK``).

Neither file is documented in ``u6data/u6tech.txt``. Built from pu6e's
``obj.py`` and confirmed field-for-field against Nuvie's ``ObjManager.cpp``
(``loadObj``, ``load_super_chunk``) and ``SaveGame.cpp`` (``load_new``),
which independently agree on every byte. Validated end to end against a
real GOG-style install: parsing consumes ``LZOBJBLK``'s entire decompressed
buffer across all 64 surface blocks with zero leftover (9098 objects), and
the bytes remaining after ``LZDNGBLK``'s 5 dungeon blocks (7283 bytes)
match Nuvie's documented ``objlist`` table size almost exactly (see
:mod:`titan.u6.actor`, which decodes that trailing data).

Both ``LZOBJBLK`` and ``LZDNGBLK`` are LZW-compressed (unlike ``TILEINDX.VGA``,
this one really is -- see :mod:`titan.u6.lzw`). Each decompresses to a
sequence of "blocks" using the *same* superchunk numbering as
:mod:`titan.u6.map`: 64 surface blocks (one per surface superchunk, 0-63)
then, in the separate ``LZDNGBLK`` stream, 5 dungeon blocks (one per
dungeon level). A block is::

    block = num_objects: u16, set of object_record

    object_record = status: u8, h: u8, b1: u8, b2: u8,
                    obj_n_lo: u8, obj_n_hi: u8, qty: u8, quality: u8

    x = h | ((b1 & 0x03) << 8)             # 10 bits, world coordinate
    y = ((b1 & 0xFC) >> 2) | ((b2 & 0x0F) << 6)   # 10 bits
    z = (b2 & 0xF0) >> 4                   # 4 bits (0-5 used)
    obj_n = obj_n_lo | ((obj_n_hi & 0x03) << 8)   # 10 bits: base object type
    frame_n = (obj_n_hi & 0xFC) >> 2       # 6 bits: frame/variant offset

Object coordinates are already absolute world coordinates (matching
:mod:`titan.u6.map`'s 1024x1024 surface / 256x256-per-level dungeon
space) -- not block-relative.

``status``'s low 5 bits are independent flags; bits 3-4 together select
one of four mutually exclusive locations (:data:`STATUS_ON_MAP`,
:data:`STATUS_IN_CONTAINER`, :data:`STATUS_IN_INVENTORY`,
:data:`STATUS_READIED`). For contained objects, ``x`` doesn't hold a
coordinate at all -- it (plus the low 2 bits of ``y``) is an index into
the flat, in-file-order object list, pointing at the containing object.
For inventory/readied objects, ``x`` holds the owning actor's ID
(0-255) instead. This module resolves both into the tree of
:attr:`U6Object.contains` and the per-actor
:attr:`U6WorldObjects.actor_inventory` dict, respectively -- callers never
need to interpret the encoding.

``obj_n``'s actual displayed tile is ``BASETILE[obj_n] + frame_n``
(confirmed directly: ``BASETILE`` is 1024 words, and real object types'
entries land correctly in the tile-graphics ranges established in
:mod:`titan.u6.tile` -- e.g. ``BASETILE[1] == 512``, the first tile in
``OBJTILES.VGA``'s range).

One thing this module does *not* attempt: real quantities for stackable
object types (gold, reagents, ammunition, etc.) are actually 16-bit --
Nuvie computes ``qty = (quality << 8) + qty`` for those types, determined
by whether the object's name (from ``LOOK.LZD``, not yet implemented in
titan) has a plural form. Lacking that, :attr:`U6Object.qty` and
:attr:`U6Object.quality` are always exposed as their raw bytes; treat a
suspiciously large ``quality`` alongside a small, round-looking ``qty``
as a hint the real object type may be stackable.

Eggs (object spawners, :data:`EGG_OBJ_N` = 335) need no special-case
parsing at all -- they turn out to be an ordinary container (status
``STATUS_IN_CONTAINER``) holding exactly one contained object, already
handled generically by the container-threading above. Confirmed against
three independent community sources (pu6e's bundled ``doc/eggs.txt``/
``eggs2.txt``, and Jim Ursetto's ``u6notes.txt``), which agree: the egg's
own :attr:`~U6Object.qty` is a spawn probability out of 100 (checked each
time the egg is examined, e.g. ``0x64`` = 100%, ``0x32`` = 50%), and its
sole :attr:`~U6Object.contains` entry is the *template* of what to spawn
-- that template's own ``qty`` is the maximum number of copies created,
not a real placed-object quantity. :attr:`U6Object.is_egg`,
:attr:`~U6Object.spawn_probability`, and :attr:`~U6Object.spawn_target`
expose this without requiring callers to know the container encoding.
The spawned template's ``quality`` byte reportedly distinguishes docile
from aggressive monster behavior for at least some creature types (8 =
aggressive, 9 = docile, per ``eggs2.txt``'s empirical account) -- that
account is anecdotal, single-source, and not confirmed against engine
source, so it is documented here rather than exposed as a named property.

Read for byte-layout reference only -- this is a fresh implementation,
not a translation of GPL source.

Example::

    from titan.u6.object import U6WorldObjects, read_basetile

    basetile = read_basetile("C:/Ultima/Ultima6/BASETILE")
    world = U6WorldObjects.from_directory("C:/Ultima/Ultima6")
    for obj in world.surface_objects[0]:  # objects in surface block 0
        print(obj.x, obj.y, obj.z, obj.tile_num(basetile))
"""

from __future__ import annotations

__all__ = [
    "U6Object",
    "U6WorldObjects",
    "U6ObjectError",
    "read_basetile",
    "unpack_position",
    "pack_position",
    "STATUS_ON_MAP",
    "STATUS_IN_CONTAINER",
    "STATUS_IN_INVENTORY",
    "STATUS_READIED",
    "STATUS_LOCATION_MASK",
    "STATUS_OK_TO_TAKE",
    "STATUS_INVISIBLE",
    "STATUS_CHARMED",
    "STATUS_TEMPORARY",
    "STATUS_LIT",
    "EGG_OBJ_N",
]

import os
import struct
from dataclasses import dataclass, field

from titan.u6.lzw import U6Lzw
from titan.u6.map import DUNGEON_LEVELS, SURFACE_SIDE_SUPERCHUNKS, SURFACE_SUPERCHUNKS

# Location (mutually exclusive; status & STATUS_LOCATION_MASK == one of these)
STATUS_ON_MAP = 0x00
STATUS_IN_CONTAINER = 0x08
STATUS_IN_INVENTORY = 0x10
STATUS_READIED = 0x18
STATUS_LOCATION_MASK = 0x18

# Independent flags (confirmed against Nuvie's Obj.h)
STATUS_OK_TO_TAKE = 0x01
STATUS_INVISIBLE = 0x02
STATUS_CHARMED = 0x04
STATUS_TEMPORARY = 0x20
# 0x40 is overloaded (egg-active / broken / mutant / cursed, depending on
# object type) -- not exposed as a single named flag.
STATUS_LIT = 0x80

RECORD_SIZE = 8

# Object spawners; see the module docstring's "Eggs" paragraph.
EGG_OBJ_N = 335


class U6ObjectError(Exception):
    """Raised on malformed object-block data."""


def unpack_position(b0: int, b1: int, b2: int) -> tuple[int, int, int]:
    """
    Unpack the shared 3-byte position encoding used by both object
    records (after the status byte) and the actor position table in
    :mod:`titan.u6.actor`.
    """
    x = b0 | ((b1 & 0x03) << 8)
    y = ((b1 & 0xFC) >> 2) | ((b2 & 0x0F) << 6)
    z = (b2 & 0xF0) >> 4
    return x, y, z


def pack_position(x: int, y: int, z: int) -> tuple[int, int, int]:
    """Inverse of :func:`unpack_position`."""
    b0 = x & 0xFF
    b1 = ((x >> 8) & 0x03) | ((y << 2) & 0xFC)
    b2 = ((y >> 6) & 0x0F) | ((z << 4) & 0xF0)
    return b0, b1, b2


def read_basetile(filepath: str | os.PathLike[str]) -> tuple[int, ...]:
    """Read BASETILE: 1024 raw little-endian words, ``BASETILE[obj_n]`` = that object type's first tile number."""
    with open(filepath, "rb") as f:
        data = f.read()
    count = len(data) // 2
    return struct.unpack(f"<{count}H", data[:count * 2])


@dataclass
class U6Object:
    """One object record. ``x``/``y``/``z`` are absolute world coordinates when :attr:`is_on_map`."""

    status: int
    x: int
    y: int
    z: int
    obj_n: int
    frame_n: int
    qty: int
    quality: int
    contains: list[U6Object] = field(default_factory=list)

    @property
    def location(self) -> int:
        return self.status & STATUS_LOCATION_MASK

    @property
    def is_on_map(self) -> bool:
        return self.location == STATUS_ON_MAP

    @property
    def is_in_container(self) -> bool:
        return self.location == STATUS_IN_CONTAINER

    @property
    def is_in_inventory(self) -> bool:
        return self.location == STATUS_IN_INVENTORY

    @property
    def is_readied(self) -> bool:
        return self.location == STATUS_READIED

    @property
    def is_ok_to_take(self) -> bool:
        return bool(self.status & STATUS_OK_TO_TAKE)

    @property
    def is_invisible(self) -> bool:
        return bool(self.status & STATUS_INVISIBLE)

    @property
    def is_charmed(self) -> bool:
        return bool(self.status & STATUS_CHARMED)

    @property
    def is_temporary(self) -> bool:
        return bool(self.status & STATUS_TEMPORARY)

    @property
    def is_lit(self) -> bool:
        return bool(self.status & STATUS_LIT)

    @property
    def is_egg(self) -> bool:
        return self.obj_n == EGG_OBJ_N

    @property
    def spawn_probability(self) -> int | None:
        """Percent chance (0-100) this egg spawns its object; ``None`` if not an egg."""
        return self.qty if self.is_egg else None

    @property
    def spawn_target(self) -> U6Object | None:
        """The object template this egg spawns (its sole contained object), or ``None``."""
        if self.is_egg and self.contains:
            return self.contains[0]
        return None

    def tile_num(self, basetile: tuple[int, ...]) -> int:
        """Actual MAPTILES/OBJTILES tile number: ``BASETILE[obj_n] + frame_n``."""
        return basetile[self.obj_n] + self.frame_n


def _parse_block(data: bytes, pos: int) -> tuple[list[U6Object], dict[int, list[U6Object]], int]:
    """
    Parse one block starting at ``pos``.

    Returns ``(top_level_objects, actor_inventory, new_pos)``.
    ``top_level_objects`` holds only objects directly on the map (with
    containers/readied items threaded into their parent's
    :attr:`U6Object.contains`); ``actor_inventory`` maps actor ID to the
    (unnested, in-file-order) list of objects that actor is holding or
    wearing in this block.
    """
    if pos + 2 > len(data):
        raise U6ObjectError(f"block header runs past end of data at {pos}")
    num_objs = struct.unpack_from("<H", data, pos)[0]
    pos += 2

    flat: list[U6Object] = []
    top_level: list[U6Object] = []
    actor_inventory: dict[int, list[U6Object]] = {}

    for _ in range(num_objs):
        if pos + RECORD_SIZE > len(data):
            raise U6ObjectError(f"object record runs past end of data at {pos}")
        status, h, b1, b2, obj_n_lo, obj_n_hi, qty, quality = struct.unpack_from(
            "<BBBBBBBB", data, pos
        )
        pos += RECORD_SIZE

        x, y, z = unpack_position(h, b1, b2)
        obj_n = obj_n_lo | ((obj_n_hi & 0x03) << 8)
        frame_n = (obj_n_hi & 0xFC) >> 2
        obj = U6Object(status=status, x=x, y=y, z=z, obj_n=obj_n, frame_n=frame_n, qty=qty, quality=quality)

        location = status & STATUS_LOCATION_MASK
        if location == STATUS_IN_CONTAINER:
            idx = x | ((y & 0x03) << 10)
            if idx >= len(flat):
                raise U6ObjectError(f"container reference {idx} out of range (only {len(flat)} objects so far)")
            flat[idx].contains.append(obj)
        elif status & STATUS_IN_INVENTORY:  # catches both IN_INVENTORY and READIED (bit 4 set)
            actor_inventory.setdefault(x, []).append(obj)
        else:
            top_level.append(obj)

        flat.append(obj)

    return top_level, actor_inventory, pos


class U6WorldObjects:
    """World object placement, split into surface (per-superchunk) and dungeon (per-level) blocks."""

    def __init__(
        self,
        surface_objects: list[list[U6Object]],
        dungeon_objects: list[list[U6Object]],
        actor_inventory: dict[int, list[U6Object]],
        objlist_tail: bytes = b"",
    ) -> None:
        self.surface_objects = surface_objects  # 64 lists, index = surface superchunk number
        self.dungeon_objects = dungeon_objects  # 5 lists, index = dungeon level (0-based)
        self.actor_inventory = actor_inventory  # {actor_id: [objects]}, merged across all blocks
        self.objlist_tail = objlist_tail  # raw bytes after LZDNGBLK's 5 blocks; see titan.u6.actor

    @classmethod
    def from_directory(cls, gamedir: str | os.PathLike[str]) -> U6WorldObjects:
        def p(name: str) -> str:
            return os.path.join(gamedir, name)

        surface_data = U6Lzw.decompress_file(p("LZOBJBLK"))
        dungeon_data = U6Lzw.decompress_file(p("LZDNGBLK"))
        return cls.from_parts(surface_data, dungeon_data)

    @classmethod
    def from_savegame(cls, savegame_dir: str | os.PathLike[str]) -> U6WorldObjects:
        """
        Load world objects + ``objlist`` from a real save's ``SAVEGAME/``
        folder, instead of the packaged fresh-install ``LZOBJBLK``/``LZDNGBLK``.

        Confirmed against U6WorldEditor's ``ObjManager::load_objblk``/
        ``save_objblks`` (a tool built against the original DOS engine's
        save format, not Nuvie's own newer save format): each
        ``OBJBLK<col><row>`` file (``col``/``row`` in ``'A'``-``'H'``) is one
        surface superchunk's block, *uncompressed* and already in exactly
        the layout :func:`_parse_block` expects -- the same ``count: u16``
        + packed-bitfield-record format as a decompressed ``LZOBJBLK``,
        confirmed field-for-field against ``ObjManager.h``'s ``FileObjInfo``
        bitfield struct. Block index order (row outer, col inner) matches
        :mod:`titan.u6.map`'s superchunk numbering (``schunk_num = row * 8
        + col``), so ``surface_objects[i]`` lines up with the same world
        position whichever loader produced it. Dungeon level ``d`` (0-4) is
        ``OBJBLK<'A'+d>I``. ``OBJLIST`` is the exact same buffer
        :mod:`titan.u6.actor`/:mod:`titan.u6.gamestate` decode as
        ``objlist_tail`` elsewhere -- just a plain standalone file here
        instead of the tail of a compressed stream.

        Validated against a real save: ``OBJLIST`` parses successfully as
        both :class:`titan.u6.actor.U6Actors` and
        :class:`titan.u6.gamestate.U6GameState`, and the loaded party/actor
        state differs from the fresh-install baseline exactly where
        expected for a save taken mid-playthrough.
        """
        def p(name: str) -> str:
            return os.path.join(savegame_dir, name)

        surface_objects: list[list[U6Object]] = []
        actor_inventory: dict[int, list[U6Object]] = {}
        for row in range(SURFACE_SIDE_SUPERCHUNKS):
            for col in range(SURFACE_SIDE_SUPERCHUNKS):
                filename = f"OBJBLK{chr(ord('A') + col)}{chr(ord('A') + row)}"
                with open(p(filename), "rb") as f:
                    data = f.read()
                objs, inv, _ = _parse_block(data, 0)
                surface_objects.append(objs)
                for actor_id, items in inv.items():
                    actor_inventory.setdefault(actor_id, []).extend(items)

        dungeon_objects: list[list[U6Object]] = []
        for level in range(DUNGEON_LEVELS):
            filename = f"OBJBLK{chr(ord('A') + level)}I"
            with open(p(filename), "rb") as f:
                data = f.read()
            objs, inv, _ = _parse_block(data, 0)
            dungeon_objects.append(objs)
            for actor_id, items in inv.items():
                actor_inventory.setdefault(actor_id, []).extend(items)

        with open(p("OBJLIST"), "rb") as f:
            objlist_tail = f.read()

        return cls(surface_objects, dungeon_objects, actor_inventory, objlist_tail)

    @classmethod
    def from_parts(
        cls,
        surface_data: bytes,
        dungeon_data: bytes,
        num_surface: int = SURFACE_SUPERCHUNKS,
        num_dungeon: int = DUNGEON_LEVELS,
    ) -> U6WorldObjects:
        surface_objects: list[list[U6Object]] = []
        actor_inventory: dict[int, list[U6Object]] = {}

        pos = 0
        for _ in range(num_surface):
            objs, inv, pos = _parse_block(surface_data, pos)
            surface_objects.append(objs)
            for actor_id, items in inv.items():
                actor_inventory.setdefault(actor_id, []).extend(items)

        dungeon_objects: list[list[U6Object]] = []
        pos = 0
        for _ in range(num_dungeon):
            objs, inv, pos = _parse_block(dungeon_data, pos)
            dungeon_objects.append(objs)
            for actor_id, items in inv.items():
                actor_inventory.setdefault(actor_id, []).extend(items)

        return cls(surface_objects, dungeon_objects, actor_inventory, dungeon_data[pos:])

    def iter_surface(self):
        """Yield every top-level (on-map) surface object, across all 64 blocks."""
        for block in self.surface_objects:
            yield from block

    def iter_dungeon(self, level: int):
        """Yield every top-level (on-map) object on one dungeon level (0-based)."""
        yield from self.dungeon_objects[level]
