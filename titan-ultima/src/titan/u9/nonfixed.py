"""
``runtime/nonfixed.%d`` reader for Ultima 9: Ascension.

These files hold U9's *dynamic* world data -- the objects whose state the
game may change and write back, as opposed to the immutable geometry in
``static/``. One file per region, ``%d`` in 0..239 with gaps.

A region is a ``width`` x ``height`` grid of 4096-unit-square chunks. Each
populated chunk owns a linked list of 4 KiB pages, and each page holds a
pool of 32-byte entity records plus 16-byte extra-data blocks. Byte-for-byte::

    File header
    0x00  unknown[5]        u32 x 5  -- [3] is a payload-size watermark
    0x14  width             u32      -- region width in chunks
    0x18  height            u32      -- region height in chunks
    0x1C  unknown           u32      -- always 1
    0x20  chunk_table       u32 x width*height, row-major
    ...   unknown           u32      -- allocation cursor

Header size is therefore ``36 + 4*width*height``. **Every other offset in
the format is relative to the end of this header**; this module calls those
"region-relative" and stores them as-is.

``chunk_table[cy*width + cx]`` and ``next_page`` are **biased by one**: a
stored ``v`` means offset ``v - 1``, and a stored ``0`` means "none". No
other offset in the format carries that bias::

    Page header (0x60 bytes)
    0x00  next_page           u32  -- biased by one, 0 = end of chain
    0x04  end_entity_offset   u32
    0x08  end_trigger_offset  u32
    0x0C  base_x              u32  -- == chunk_x * 4096
    0x10  base_y              u32  -- == chunk_y * 4096
    0x14  entity_count        u32  -- entities in THIS page, not the chunk
    0x18  trigger_count       u32
    0x1C  bucket_heads        u32 x 17 -- heads of the entity linked lists

    Entity (0x20 bytes)
    0x00  next_entity         u32  -- region-relative, 0 = end of list
    0x04  offset_x            u16  -- relative to the page's base_x
    0x06  offset_y            u16  -- relative to the page's base_y
    0x08  z                   u16
    0x0A  type_index          u16  -- static/TYPES.DAT, static/TYPENAME.FLX
    0x0C  rotation            i16 x 4 -- quaternion, 0.16 fixed point
    0x14  flags               u32
    0x18  mesh_index          u16  -- static/sappear.flx
    0x1A  trigger_id          u16
    0x1C  extra_data_offset   u32  -- region-relative, 0 = none

    Extra data (0x10 bytes)
    0x00  arg_count           u8   -- 1..3
    0x01  arg_types           u8 x 3 -- 0 for unused slots
    0x04  values              u32 x 3

Entities cannot be enumerated by striding the pool: extra-data blocks are
16-byte aligned and interleave with the 32-byte entities, so a stride scan
reads some of them as entity-shaped garbage. Enumerate by walking the 17
``bucket_heads`` of the chunk's **first** page through ``next_entity``
instead -- see :meth:`U9Nonfixed.chunk`.

Starting point was the community-documented layout; every field above was
then verified against 166 real region files (2,791 chunks, 3,198 pages,
96,995 entities, 34,586 extra-data blocks) from a GOG 1.19 install and the
pristine v1.19H patch originals. Two things came out different from the
published documentation:

* ``next_entity`` is a ``u32``, not a ``u16`` followed by an unknown ``u16``.
  The high half is zero only while the target sits in the first 64 KiB, so
  the 16-bit reading looks fine on small regions and fails on large ones.
  Reading it as ``u32`` takes chunk enumeration from 51.2% to 95.4% exact
  and walked-position validity from 99.5% to 100.0000%.
* The one-based bias applies to the chunk table too, which the documentation
  notes only for ``next_page``.

``base_x``/``base_y`` equal ``(chunk_x, chunk_y) * 4096`` on 3,198 of 3,198
pages, which is what pins the header, the row-major table order, the bias
and the page walk down simultaneously.

**Known limitation.** The bucket walk recovers the declared entity count
exactly for 95.4% of chunks. Every residual is an *undershoot* -- fewer
entities than declared, never more, never out of bounds -- so a caller may
see an incomplete chunk but never an invented entity.
:attr:`U9Chunk.is_complete` reports it per chunk. See
``reference/u9/nonfixed/u9_nonfixed_reference.md`` for the full analysis.

Triggers are counted but not decoded; their record layout is unknown.

Example::

    from titan.u9.nonfixed import U9Nonfixed

    region = U9Nonfixed.from_file("runtime/nonfixed.22")
    print(region.width, region.height)          # 2 2
    chunk = region.chunk(1, 0)
    print(chunk.declared_entity_count)           # 76
    for entity in chunk.entities:
        print(entity.world_x, entity.world_y, entity.type_index)
"""

from __future__ import annotations

__all__ = [
    "U9Chunk",
    "U9Entity",
    "U9ExtraData",
    "U9Nonfixed",
    "U9NonfixedError",
    "U9Page",
]

import os
import struct
from dataclasses import dataclass

FIXED_HEADER_SIZE = 0x20
WIDTH_OFFSET = 0x14
HEIGHT_OFFSET = 0x18
TABLE_OFFSET = 0x20
TRAILER_SIZE = 4

PAGE_HEADER_SIZE = 0x60
PAGE_HEADER_STRUCT = "<7I"
BUCKET_COUNT = 17
BUCKET_OFFSET = 0x1C

ENTITY_SIZE = 0x20
ENTITY_STRUCT = "<IHHHH4hIHHI"

EXTRA_SIZE = 0x10
EXTRA_STRUCT = "<B3B3I"

CHUNK_SPAN = 4096
QUATERNION_SCALE = 32767.0

# Regions observed in real data are square and small; this only guards
# against reading a wild width/height out of a non-nonfixed file.
MAX_GRID_DIM = 256


class U9NonfixedError(Exception):
    """Raised on malformed ``runtime/nonfixed.%d`` data."""


@dataclass(frozen=True)
class U9ExtraData:
    """One 16-byte extra-data block hanging off an entity."""

    offset: int
    arg_count: int
    arg_types: tuple[int, int, int]
    values: tuple[int, int, int]

    @property
    def args(self) -> list[tuple[int, int]]:
        """The ``(type, value)`` pairs actually in use, per ``arg_count``."""
        return [(self.arg_types[i], self.values[i]) for i in range(min(self.arg_count, 3))]


@dataclass(frozen=True)
class U9Entity:
    """One 32-byte dynamic object record."""

    offset: int
    next_entity: int
    offset_x: int
    offset_y: int
    z: int
    type_index: int
    rotation: tuple[int, int, int, int]
    flags: int
    mesh_index: int
    trigger_id: int
    extra_data_offset: int
    base_x: int
    base_y: int

    @property
    def world_x(self) -> int:
        return self.base_x + self.offset_x

    @property
    def world_y(self) -> int:
        return self.base_y + self.offset_y

    @property
    def quaternion(self) -> tuple[float, float, float, float]:
        """``rotation`` as floats -- the stored 0.16 fixed point over 32767."""
        x, y, z, w = self.rotation
        return (x / QUATERNION_SCALE, y / QUATERNION_SCALE, z / QUATERNION_SCALE, w / QUATERNION_SCALE)

    @property
    def has_extra_data(self) -> bool:
        return self.extra_data_offset != 0


@dataclass(frozen=True)
class U9Page:
    """One 4 KiB page header in a chunk's page chain."""

    offset: int
    next_page: int
    end_entity_offset: int
    end_trigger_offset: int
    base_x: int
    base_y: int
    entity_count: int
    trigger_count: int
    bucket_heads: tuple[int, ...]


@dataclass(frozen=True)
class U9Chunk:
    """One populated chunk: its page chain and the entities walked from it."""

    index: int
    chunk_x: int
    chunk_y: int
    base_x: int
    base_y: int
    pages: tuple[U9Page, ...]
    entities: tuple[U9Entity, ...]

    @property
    def declared_entity_count(self) -> int:
        """Sum of ``entity_count`` over the chunk's pages -- the expected total."""
        return sum(p.entity_count for p in self.pages)

    @property
    def trigger_count(self) -> int:
        return sum(p.trigger_count for p in self.pages)

    @property
    def is_complete(self) -> bool:
        """True when the bucket walk recovered every declared entity.

        False means the walk undershot; see the module docstring. It never
        means extra or invalid entities were produced.
        """
        return len(self.entities) == self.declared_entity_count


class U9Nonfixed:
    """Reader for one ``runtime/nonfixed.%d`` region file."""

    def __init__(self, data: bytes) -> None:
        if len(data) < TABLE_OFFSET + TRAILER_SIZE:
            raise U9NonfixedError(f"data too small to contain a nonfixed header: {len(data)} bytes")

        self.width, self.height = struct.unpack_from("<II", data, WIDTH_OFFSET)
        if not (1 <= self.width <= MAX_GRID_DIM and 1 <= self.height <= MAX_GRID_DIM):
            raise U9NonfixedError(
                f"implausible region grid {self.width}x{self.height} -- not a nonfixed file?"
            )

        self.header_size = TABLE_OFFSET + self.width * self.height * 4 + TRAILER_SIZE
        if len(data) < self.header_size:
            raise U9NonfixedError(
                f"truncated: {self.width}x{self.height} grid needs a "
                f"{self.header_size}-byte header, file is {len(data)} bytes"
            )

        self._data = data
        self.unknown = struct.unpack_from("<5I", data, 0)
        self.chunk_table = struct.unpack_from(f"<{self.width * self.height}I", data, TABLE_OFFSET)
        self.trailer = struct.unpack_from("<I", data, self.header_size - TRAILER_SIZE)[0]

        # Advisory only: 0 on empty regions that still carry a preallocated
        # payload, and larger than the file in at least one shipped region.
        self.declared_payload_size = self.unknown[3]

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Nonfixed:
        with open(filepath, "rb") as f:
            return cls(f.read())

    @property
    def payload_size(self) -> int:
        """Bytes after the header -- the region-relative address space."""
        return len(self._data) - self.header_size

    @property
    def num_chunks(self) -> int:
        return self.width * self.height

    def _in_payload(self, rel: int, size: int) -> bool:
        return 0 <= rel and rel + size <= self.payload_size

    def used_chunk_indices(self) -> list[int]:
        """Indices of chunks that have a page chain."""
        return [i for i, v in enumerate(self.chunk_table) if v != 0]

    def pages(self, index: int) -> list[U9Page]:
        """The page chain for one chunk index, first page first."""
        if index < 0 or index >= self.num_chunks:
            raise U9NonfixedError(f"chunk index {index} out of range (0..{self.num_chunks - 1})")

        result: list[U9Page] = []
        seen: set[int] = set()
        # Chunk table and next_page are both biased by one.
        value = self.chunk_table[index]
        while value:
            rel = value - 1
            if rel in seen or not self._in_payload(rel, PAGE_HEADER_SIZE):
                break
            seen.add(rel)
            base = self.header_size + rel
            next_page, end_ent, end_trg, base_x, base_y, n_ent, n_trg = struct.unpack_from(
                PAGE_HEADER_STRUCT, self._data, base
            )
            heads = struct.unpack_from(f"<{BUCKET_COUNT}I", self._data, base + BUCKET_OFFSET)
            result.append(
                U9Page(
                    offset=rel,
                    next_page=next_page,
                    end_entity_offset=end_ent,
                    end_trigger_offset=end_trg,
                    base_x=base_x,
                    base_y=base_y,
                    entity_count=n_ent,
                    trigger_count=n_trg,
                    bucket_heads=heads,
                )
            )
            value = next_page
        return result

    def _read_entity(self, rel: int, base_x: int, base_y: int) -> U9Entity:
        f = struct.unpack_from(ENTITY_STRUCT, self._data, self.header_size + rel)
        return U9Entity(
            offset=rel,
            next_entity=f[0],
            offset_x=f[1],
            offset_y=f[2],
            z=f[3],
            type_index=f[4],
            rotation=(f[5], f[6], f[7], f[8]),
            flags=f[9],
            mesh_index=f[10],
            trigger_id=f[11],
            extra_data_offset=f[12],
            base_x=base_x,
            base_y=base_y,
        )

    def chunk(self, chunk_x: int, chunk_y: int) -> U9Chunk | None:
        """One chunk by grid coordinate, or ``None`` if it holds no pages."""
        if not (0 <= chunk_x < self.width and 0 <= chunk_y < self.height):
            raise U9NonfixedError(
                f"chunk ({chunk_x}, {chunk_y}) out of range for a {self.width}x{self.height} region"
            )
        return self.chunk_at(chunk_y * self.width + chunk_x)

    def chunk_at(self, index: int) -> U9Chunk | None:
        """One chunk by table index, or ``None`` if it holds no pages."""
        pages = self.pages(index)
        if not pages:
            return None

        base_x, base_y = pages[0].base_x, pages[0].base_y

        # Only the first page carries the chunk's live list heads; later
        # pages' arrays are stale. Walk each head through next_entity,
        # de-duplicating across buckets and guarding against cycles.
        entities: list[U9Entity] = []
        seen: set[int] = set()
        for head in pages[0].bucket_heads:
            rel = head
            local: set[int] = set()
            while rel and rel not in seen and rel not in local:
                if not self._in_payload(rel, ENTITY_SIZE):
                    break
                local.add(rel)
                seen.add(rel)
                entity = self._read_entity(rel, base_x, base_y)
                entities.append(entity)
                rel = entity.next_entity

        entities.sort(key=lambda e: e.offset)
        return U9Chunk(
            index=index,
            chunk_x=index % self.width,
            chunk_y=index // self.width,
            base_x=base_x,
            base_y=base_y,
            pages=tuple(pages),
            entities=tuple(entities),
        )

    def chunks(self) -> list[U9Chunk]:
        """Every populated chunk, in table order."""
        result = []
        for index in self.used_chunk_indices():
            chunk = self.chunk_at(index)
            if chunk is not None:
                result.append(chunk)
        return result

    def entities(self) -> list[U9Entity]:
        """Every entity in the region, chunk by chunk."""
        return [e for chunk in self.chunks() for e in chunk.entities]

    def extra_data(self, entity: U9Entity) -> U9ExtraData | None:
        """Decode an entity's extra-data block, or ``None`` if it has none."""
        rel = entity.extra_data_offset
        if not rel or not self._in_payload(rel, EXTRA_SIZE):
            return None
        f = struct.unpack_from(EXTRA_STRUCT, self._data, self.header_size + rel)
        return U9ExtraData(
            offset=rel,
            arg_count=f[0],
            arg_types=(f[1], f[2], f[3]),
            values=(f[4], f[5], f[6]),
        )
