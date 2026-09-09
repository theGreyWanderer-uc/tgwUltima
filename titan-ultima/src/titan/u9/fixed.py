"""
``static/fixed.%d`` reader for Ultima 9: Ascension.

The immovable half of U9's world -- trees, buildings, terrain clutter -- one
file per region, ``%d`` in 0..239 with gaps. Its counterpart is
:mod:`titan.u9.nonfixed`, which holds the objects whose state the game can
change; together they are the whole map.

The two formats are close siblings but **not** identical, and the differences
are exactly where a reader written for one breaks on the other::

    File header
    0x00  unknown         u32 x 2
    0x08  payload size    u32   -- a watermark, advisory
    0x0C  0x00C00000      u32   -- the same constant nonfixed carries
    0x10  width           u32   -- region width in chunks
    0x14  height          u32   -- region height in chunks
    0x18  unknown         u32
    0x1C  1               u32
    0x20  chunk_table     u32 x width*height

Header size is ``0x20 + 4*width*height``. Note that is **32 + 4WH**, where
nonfixed is 36 + 4WH: this format has one fewer leading field and no trailing
allocation cursor. Every offset after the header is relative to its end.

Chunk table entries are **biased by one**, as in nonfixed: a stored ``v`` means
offset ``v - 1`` and a stored ``0`` means "no pages". ``next_page`` carries the
same bias::

    Page (0x1000 bytes)
    0x00  next_page          u32  -- biased by one, 0 = end of chain
    0x04  free_list_head     u32  -- region-relative, 0 = no free slots
    0x08  zero               u32
    0x0C  base_x             u32  -- chunk origin, always a multiple of 4096
    0x10  base_y             u32
    0x14  live_count         u32
    0x18  unknown            u32 x 18
    0x60  objects            24 bytes each

    Object (0x18 bytes)
    0x00  reference   u32
    0x04  x           u16  -- relative to the page's base_x
    0x06  y           u16  -- relative to the page's base_y
    0x08  z           u16  -- elevation
    0x0A  type_index  u16  -- static/TYPES.DAT, static/TYPENAME.FLX
    0x0C  rotation    i16 x 4  -- quaternion, 0.16 fixed point
    0x14  flags       u32

All integers are little-endian.

Verified against 164 real region files -- 2,815 chunks, 3,315 pages, 152,383
live objects:

* every page's ``base_x``/``base_y`` is a multiple of 4096 (2,815/2,815 first
  pages), and every page in a chunk's chain repeats that chunk's origin
  (2,815/2,815);
* every object's ``x`` and ``y`` is below 4096 (152,383/152,383), so they really
  are chunk-relative;
* reading four rotation components produces the expected near-unit quaternion
  on 152,382/152,383 live objects at a 1% squared-norm tolerance; reading only
  three reaches that tolerance on just 12,686/152,383.

Three corrections to the published community documentation came out of that:

* The Ultima Codex documents ``0x12`` as a ``uint16`` **flags** field and the
  rotation as three components. It is the quaternion's fourth component. Taken
  as three the vector is normalised on only 10.7% of objects; taken as four it
  is normalised on **100%**. The giveaway is objects reading
  ``(16383, 16383, 16383, 16383)`` -- a clean 0.5/0.5/0.5/0.5 rotation.
* **The chunk table is not in ``[x + y*width]`` order.** Only 1 of 2,815
  entries lands where row-major indexing predicts. The Codex hedges on this
  ("may be in [x + y * width] order, but that doesn't seem to corroborate");
  it is not. Take the chunk from the page's own ``base_x``/``base_y``, which
  this reader does -- ``U9FixedChunk.chunk_x`` is derived, not assumed. This is
  the sharpest difference from nonfixed, whose table *is* row-major on
  3,198/3,198 pages.

Objects are a **sparse** array over the page's 166 slots, not a run.

``0x04`` is the head of a free list, not the end of the objects. Each free
record's first dword -- the field this reader calls ``reference`` -- is the next
link, both region-relative. ``u9.exe`` builds the list in ``FUN_004D1C30``::

    page = record & 0xFFFFF000
    record[0x00]   = page[0x04]          # reference = old head
    page[0x04]     = record - base       # head = this record
    page[0x14]    -= 1                   # live count

So ``(head - page_offset - 0x60) / 24`` measures the distance to the *first free
slot*. It divides cleanly on 2,814 of 2,815 pages because the head is always on
a slot boundary, and on a page where nothing was ever freed it does equal the
object count -- but on any page with a hole it truncates, silently dropping
every object past it. Comparing actual slot identities on ``fixed.9``, that old
interpretation omits 5,294 live objects across 168 pages and also misreads 1,880
free slots as live across 124 pages. Correct enumeration therefore changes the
total from 14,204 to 17,618, including both Region 9 roofs the earlier
missing-roof investigation concluded were absent from the file.

``page[0x14]`` **is** the live count. Its documented 55% agreement with the
derived figure was the symptom, not a reason to distrust it: the two agree only
where nothing was freed.

Correct enumeration is to walk the free list and take every slot it did not
visit. Verified on ``fixed.9``: the walk terminates cleanly on **354 of 354**
pages and ``166 - len(free)`` equals ``page[0x14]`` on every one of them. The
free list covers unused slots too, including those never yet allocated, exactly
as ``nonfixed``'s 250-cell identity does.

A count alone is not a usable bound either, because the array is sparse: a live
object sits at slot 100 on a page whose live count is 52.

If the walk does not validate -- a malformed link, a cycle, or a total that
disagrees with ``page[0x14]`` -- this reader falls back to the old derived span
so that odd or synthetic pages still read.

Example::

    from titan.u9.fixed import U9Fixed

    region = U9Fixed.from_file("static/fixed.22")
    print(region.width, region.height)
    for chunk in region.chunks():
        for obj in chunk.objects:
            print(obj.world_x, obj.world_y, obj.type_index)
"""

from __future__ import annotations

__all__ = ["U9Fixed", "U9FixedChunk", "U9FixedError", "U9FixedObject", "U9FixedPage"]

import os
import struct
from dataclasses import dataclass

TABLE_OFFSET = 0x20
WIDTH_OFFSET = 0x10
HEIGHT_OFFSET = 0x14
PAYLOAD_SIZE_OFFSET = 0x08

PAGE_SIZE = 0x1000
PAGE_HEADER_SIZE = 0x60
PAGE_HEADER_STRUCT = "<6I"

OBJECT_SIZE = 0x18
OBJECT_STRUCT = "<I4H4hI"

FREE_LIST_HEAD_OFFSET = 0x04

CHUNK_SPAN = 4096
QUATERNION_SCALE = 32767.0
MAX_OBJECTS_PER_PAGE = 166
MAX_GRID_DIM = 256


class U9FixedError(Exception):
    """Raised on malformed ``static/fixed.%d`` data."""


@dataclass(frozen=True)
class U9FixedObject:
    """One 24-byte immovable object."""

    offset: int
    reference: int
    x: int
    y: int
    z: int
    type_index: int
    rotation: tuple[int, int, int, int]
    flags: int
    base_x: int
    base_y: int

    @property
    def world_x(self) -> int:
        return self.base_x + self.x

    @property
    def world_y(self) -> int:
        return self.base_y + self.y

    @property
    def quaternion(self) -> tuple[float, float, float, float]:
        """Return the stored native-U9 X/Y/Z/W quaternion as floats."""
        x, y, z, w = self.rotation
        return (
            x / QUATERNION_SCALE,
            y / QUATERNION_SCALE,
            z / QUATERNION_SCALE,
            w / QUATERNION_SCALE,
        )


@dataclass(frozen=True)
class U9FixedPage:
    """One 4 KiB page header in a chunk's chain."""

    offset: int
    next_page: int
    end_object_offset: int
    """Raw ``page+0x04``. This is the free-list head; the name is kept for
    compatibility. It is *not* the end of the object array."""
    base_x: int
    base_y: int
    object_count: int
    live_count: int = 0
    """Raw ``page+0x14``, the engine's own count of live objects."""
    live_slots: tuple[int, ...] = ()
    """Occupied slot indices. Sparse: not necessarily ``range(object_count)``."""
    free_list_walked: bool = False
    """True when the free list validated against ``live_count``. False means
    this page fell back to the old ``end_object_offset`` span."""

    @property
    def free_list_head(self) -> int:
        """Region-relative free-list head; preferred over the compatibility name."""
        return self.end_object_offset


@dataclass(frozen=True)
class U9FixedChunk:
    """One populated chunk: its page chain and every object in it."""

    base_x: int
    base_y: int
    table_index: int
    pages: tuple[U9FixedPage, ...]
    objects: tuple[U9FixedObject, ...]

    @property
    def chunk_x(self) -> int:
        """Grid X, derived from ``base_x`` -- *not* from the table index."""
        return self.base_x // CHUNK_SPAN

    @property
    def chunk_y(self) -> int:
        return self.base_y // CHUNK_SPAN


class U9Fixed:
    """Reader for one ``static/fixed.%d`` region file."""

    def __init__(self, data: bytes) -> None:
        if len(data) < TABLE_OFFSET:
            raise U9FixedError(
                f"data too small to contain a fixed header: {len(data)} bytes"
            )

        self.width, self.height = struct.unpack_from("<II", data, WIDTH_OFFSET)
        if not (1 <= self.width <= MAX_GRID_DIM and 1 <= self.height <= MAX_GRID_DIM):
            raise U9FixedError(
                f"implausible region grid {self.width}x{self.height} -- not a fixed file?"
            )

        self.header_size = TABLE_OFFSET + self.width * self.height * 4
        if len(data) < self.header_size:
            raise U9FixedError(
                f"truncated: a {self.width}x{self.height} grid needs a "
                f"{self.header_size}-byte header, file is {len(data)} bytes"
            )

        self._data = data
        self.chunk_table = struct.unpack_from(
            f"<{self.width * self.height}I", data, TABLE_OFFSET
        )
        # Advisory: it disagrees with the real payload on 10 of 164 shipped
        # files, the same way nonfixed's watermark does.
        self.declared_payload_size = struct.unpack_from(
            "<I", data, PAYLOAD_SIZE_OFFSET
        )[0]

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Fixed:
        with open(filepath, "rb") as f:
            return cls(f.read())

    @property
    def payload_size(self) -> int:
        return len(self._data) - self.header_size

    @property
    def num_chunks(self) -> int:
        return self.width * self.height

    def used_table_indices(self) -> list[int]:
        """Chunk-table slots that point at a page chain."""
        return [i for i, v in enumerate(self.chunk_table) if v != 0]

    def _in_payload(self, rel: int, size: int) -> bool:
        return 0 <= rel and rel + size <= self.payload_size

    def _free_slots(self, rel: int) -> set[int] | None:
        """Slot indices on this page's free list, or ``None`` if unwalkable.

        ``page+0x04`` is the head and each free record's first dword is the next
        link, both region-relative, terminating at zero. Anything that is not a
        slot boundary, runs out of the page, or revisits a slot means this is
        not a free list we understand, and the caller falls back.
        """
        base = self.header_size + rel
        (head,) = struct.unpack_from("<I", self._data, base + FREE_LIST_HEAD_OFFSET)
        out: set[int] = set()
        while head:
            offset = head - rel - PAGE_HEADER_SIZE
            if offset < 0 or offset % OBJECT_SIZE:
                return None
            index = offset // OBJECT_SIZE
            if index >= MAX_OBJECTS_PER_PAGE or index in out:
                return None
            record = rel + PAGE_HEADER_SIZE + index * OBJECT_SIZE
            if not self._in_payload(record, OBJECT_SIZE):
                return None
            out.add(index)
            (head,) = struct.unpack_from("<I", self._data, self.header_size + record)
        return out

    def _live_slots(
        self, rel: int, free_head: int, live_count: int
    ) -> tuple[tuple[int, ...], bool]:
        """Occupied slots on a page, and whether the free list was trusted."""
        free = self._free_slots(rel)
        if free is not None and MAX_OBJECTS_PER_PAGE - len(free) == live_count:
            return tuple(i for i in range(MAX_OBJECTS_PER_PAGE) if i not in free), True

        # Fall back to the historical span. Wrong on any page with a hole, but
        # it is what synthetic and malformed pages still read correctly under.
        span = free_head - rel - PAGE_HEADER_SIZE
        count = span // OBJECT_SIZE if free_head and span >= 0 else 0
        return tuple(range(min(count, MAX_OBJECTS_PER_PAGE))), False

    def pages(self, table_index: int) -> list[U9FixedPage]:
        """The page chain for one table slot, first page first."""
        if table_index < 0 or table_index >= self.num_chunks:
            raise U9FixedError(
                f"table index {table_index} out of range (0..{self.num_chunks - 1})"
            )
        out: list[U9FixedPage] = []
        seen: set[int] = set()
        value = self.chunk_table[table_index]
        while value:
            rel = value - 1  # biased by one, as in nonfixed
            if rel in seen or not self._in_payload(rel, PAGE_HEADER_SIZE):
                break
            seen.add(rel)
            base = self.header_size + rel
            next_page, free_head, _zero, base_x, base_y, live_count = (
                struct.unpack_from(PAGE_HEADER_STRUCT, self._data, base)
            )
            slots, walked = self._live_slots(rel, free_head, live_count)
            out.append(
                U9FixedPage(
                    offset=rel,
                    next_page=next_page,
                    end_object_offset=free_head,
                    base_x=base_x,
                    base_y=base_y,
                    object_count=len(slots),
                    live_count=live_count,
                    live_slots=slots,
                    free_list_walked=walked,
                )
            )
            value = next_page
        return out

    def _read_object(self, rel: int, base_x: int, base_y: int) -> U9FixedObject:
        f = struct.unpack_from(OBJECT_STRUCT, self._data, self.header_size + rel)
        return U9FixedObject(
            offset=rel,
            reference=f[0],
            x=f[1],
            y=f[2],
            z=f[3],
            type_index=f[4],
            rotation=(f[5], f[6], f[7], f[8]),
            flags=f[9],
            base_x=base_x,
            base_y=base_y,
        )

    def chunk_at(self, table_index: int) -> U9FixedChunk | None:
        """One chunk by table slot, or ``None`` if the slot holds no pages."""
        pages = self.pages(table_index)
        if not pages:
            return None
        base_x, base_y = pages[0].base_x, pages[0].base_y

        objects: list[U9FixedObject] = []
        for page in pages:
            start = page.offset + PAGE_HEADER_SIZE
            for i in page.live_slots:
                rel = start + i * OBJECT_SIZE
                if not self._in_payload(rel, OBJECT_SIZE):
                    break
                objects.append(self._read_object(rel, base_x, base_y))
        return U9FixedChunk(
            base_x=base_x,
            base_y=base_y,
            table_index=table_index,
            pages=tuple(pages),
            objects=tuple(objects),
        )

    def chunks(self) -> list[U9FixedChunk]:
        """Every populated chunk, in table order."""
        out = []
        for index in self.used_table_indices():
            chunk = self.chunk_at(index)
            if chunk is not None:
                out.append(chunk)
        return out

    def chunk(self, chunk_x: int, chunk_y: int) -> U9FixedChunk | None:
        """One chunk by grid coordinate.

        Resolved by scanning for a chunk whose ``base_x``/``base_y`` match,
        because the table is not in row-major order -- see the module
        docstring.
        """
        if not (0 <= chunk_x < self.width and 0 <= chunk_y < self.height):
            raise U9FixedError(
                f"chunk ({chunk_x}, {chunk_y}) out of range for a "
                f"{self.width}x{self.height} region"
            )
        want = (chunk_x * CHUNK_SPAN, chunk_y * CHUNK_SPAN)
        for chunk in self.chunks():
            if (chunk.base_x, chunk.base_y) == want:
                return chunk
        return None

    def objects(self) -> list[U9FixedObject]:
        """Every object in the region, chunk by chunk."""
        return [o for chunk in self.chunks() for o in chunk.objects]
