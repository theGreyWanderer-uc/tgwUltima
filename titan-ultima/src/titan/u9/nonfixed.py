"""Reader for Ultima IX ``runtime/nonfixed.%d`` region files.

These files contain runtime-mutable world objects. A region is a row-major
grid of 4096-unit chunks. Each populated chunk owns one or more 4 KiB pages;
the bytes after each 0x60-byte page header form a shared allocator containing
125 32-byte cells. A cell holds either one entity or two 16-byte extra-data
records.

All offsets after the file header are relative to the end of that header.
Chunk-table and ``next_page`` values are the only biased offsets: stored
``value`` means ``value - 1`` and zero means absent.

The page allocator is fully accounted for by::

    2 * entity_count + extra_data_count
      + 2 * free_entity_count + free_extra_data_count == 250

The identity holds on every one of 2,839 shipped pages checked. The two page
header fields previously called ``end_entity_offset`` and
``end_trigger_offset`` are actually free-list heads. Entity free nodes link
through byte 0; 16-byte free nodes link through byte 4.

The first bucket-head word is reserved and always zero in the corpus. The
remaining 16 heads are the chunk's 4x4 spatial index, in row-major order. An
entity at local ``(x, y)`` belongs to bucket
``1 + (y // 1024) * 4 + x // 1024``. Only a chunk's first page contains the
live heads; later-page copies are stale.

Some allocated entity records are not linked into that spatial index. They
are retained records rather than parser omissions: the free lists and the
allocator equation prove their allocation state. :attr:`U9Chunk.entities`
contains spatially indexed entities for compatibility, while
:attr:`U9Chunk.unlinked_entities` and :attr:`U9Chunk.allocated_entities`
expose the rest.
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

WIDTH_OFFSET = 0x14
HEIGHT_OFFSET = 0x18
TABLE_OFFSET = 0x20
TRAILER_SIZE = 4

PAGE_SIZE = 0x1000
PAGE_HEADER_SIZE = 0x60
PAGE_HEADER_STRUCT = "<7I"
BUCKET_COUNT = 17
BUCKET_OFFSET = 0x1C

ENTITY_SIZE = 0x20
ENTITY_STRUCT = "<IHHHH4hIHHI"

EXTRA_SIZE = 0x10
EXTRA_STRUCT = "<B3B3I"
FREE_EXTRA_LINK_OFFSET = 4

CHUNK_SPAN = 4096
BUCKET_SPAN = CHUNK_SPAN // 4
QUATERNION_SCALE = 32767.0
MAX_GRID_DIM = 256


class U9NonfixedError(Exception):
    """Raised on malformed ``runtime/nonfixed.%d`` data."""


@dataclass(frozen=True)
class U9ExtraData:
    """One allocated 16-byte entity property/argument record."""

    offset: int
    arg_count: int
    arg_types: tuple[int, int, int]
    values: tuple[int, int, int]

    @property
    def args(self) -> list[tuple[int, int]]:
        """Return the ``(type, value)`` pairs in use."""
        return [(self.arg_types[i], self.values[i]) for i in range(min(self.arg_count, 3))]


@dataclass(frozen=True)
class U9Entity:
    """One allocated 32-byte dynamic-object record."""

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
    def spatial_bucket(self) -> int:
        """The 1..16 page-header bucket selected by this local position."""
        return 1 + (self.offset_y // BUCKET_SPAN) * 4 + self.offset_x // BUCKET_SPAN

    @property
    def quaternion(self) -> tuple[float, float, float, float]:
        """Return ``rotation`` as floating-point 0.16 fixed-point values."""
        x, y, z, w = self.rotation
        return (
            x / QUATERNION_SCALE,
            y / QUATERNION_SCALE,
            z / QUATERNION_SCALE,
            w / QUATERNION_SCALE,
        )

    @property
    def has_extra_data(self) -> bool:
        return self.extra_data_offset != 0


@dataclass(frozen=True)
class U9Page:
    """One 4 KiB allocator page in a chunk's page chain."""

    offset: int
    next_page: int
    free_entity_head: int
    free_extra_data_head: int
    base_x: int
    base_y: int
    entity_count: int
    extra_data_count: int
    bucket_heads: tuple[int, ...]

    @property
    def reserved_bucket_head(self) -> int:
        """The unused first word in ``bucket_heads`` (zero in shipped data)."""
        return self.bucket_heads[0]

    @property
    def spatial_bucket_heads(self) -> tuple[int, ...]:
        """The 16 row-major heads for the chunk's 4x4 spatial grid."""
        return self.bucket_heads[1:]

    @property
    def end_entity_offset(self) -> int:
        """Deprecated alias for :attr:`free_entity_head`."""
        return self.free_entity_head

    @property
    def end_trigger_offset(self) -> int:
        """Deprecated alias for :attr:`free_extra_data_head`."""
        return self.free_extra_data_head

    @property
    def trigger_count(self) -> int:
        """Deprecated alias for :attr:`extra_data_count`."""
        return self.extra_data_count


@dataclass(frozen=True)
class U9Chunk:
    """One populated chunk and its decoded page allocations."""

    index: int
    chunk_x: int
    chunk_y: int
    base_x: int
    base_y: int
    pages: tuple[U9Page, ...]
    entities: tuple[U9Entity, ...]
    unlinked_entities: tuple[U9Entity, ...] = ()
    extra_data_records: tuple[U9ExtraData, ...] = ()
    free_entity_offsets: tuple[int, ...] = ()
    free_extra_data_offsets: tuple[int, ...] = ()
    entity_slots_complete: bool = False
    extra_data_slots_complete: bool = False
    stored_entity_count: int | None = None
    stored_extra_data_count: int | None = None

    @property
    def allocated_entities(self) -> tuple[U9Entity, ...]:
        """All allocated entities, whether or not the spatial index links them."""
        return tuple(sorted((*self.entities, *self.unlinked_entities), key=lambda e: e.offset))

    @property
    def declared_entity_count(self) -> int:
        """The effective entity allocation count stored for this chunk."""
        if self.stored_entity_count is not None:
            return self.stored_entity_count
        return sum(page.entity_count for page in self.pages)

    @property
    def extra_data_count(self) -> int:
        """The effective extra-data allocation count stored for this chunk."""
        if self.stored_extra_data_count is not None:
            return self.stored_extra_data_count
        return sum(page.extra_data_count for page in self.pages)

    @property
    def trigger_count(self) -> int:
        """Deprecated alias for :attr:`extra_data_count`."""
        return self.extra_data_count

    @property
    def is_complete(self) -> bool:
        """Whether every declared 32-byte entity allocation was decoded."""
        return self.entity_slots_complete

    @property
    def allocation_is_complete(self) -> bool:
        """Whether both entity and extra-data allocation counts were decoded."""
        return self.entity_slots_complete and self.extra_data_slots_complete


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
        self.chunk_table = struct.unpack_from(
            f"<{self.width * self.height}I", data, TABLE_OFFSET
        )
        self.trailer = struct.unpack_from("<I", data, self.header_size - TRAILER_SIZE)[0]
        self.declared_payload_size = self.unknown[3]

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9Nonfixed:
        with open(filepath, "rb") as file:
            return cls(file.read())

    def to_bytes(self) -> bytes:
        """Return the source bytes exactly, including allocator slack."""
        return self._data

    @property
    def payload_size(self) -> int:
        """Bytes after the header: the region-relative address space."""
        return len(self._data) - self.header_size

    @property
    def num_chunks(self) -> int:
        return self.width * self.height

    def _in_payload(self, rel: int, size: int) -> bool:
        return 0 <= rel and rel + size <= self.payload_size

    def used_chunk_indices(self) -> list[int]:
        """Return chunk-table indices that own a page chain."""
        return [index for index, value in enumerate(self.chunk_table) if value != 0]

    def pages(self, index: int) -> list[U9Page]:
        """Return one chunk's page chain, first page first."""
        if index < 0 or index >= self.num_chunks:
            raise U9NonfixedError(f"chunk index {index} out of range (0..{self.num_chunks - 1})")

        result: list[U9Page] = []
        seen: set[int] = set()
        value = self.chunk_table[index]
        while value:
            rel = value - 1
            if rel in seen or not self._in_payload(rel, PAGE_HEADER_SIZE):
                break
            seen.add(rel)
            base = self.header_size + rel
            next_page, free_entity, free_extra, base_x, base_y, entities, extras = (
                struct.unpack_from(PAGE_HEADER_STRUCT, self._data, base)
            )
            heads = struct.unpack_from(f"<{BUCKET_COUNT}I", self._data, base + BUCKET_OFFSET)
            result.append(
                U9Page(
                    offset=rel,
                    next_page=next_page,
                    free_entity_head=free_entity,
                    free_extra_data_head=free_extra,
                    base_x=base_x,
                    base_y=base_y,
                    entity_count=entities,
                    extra_data_count=extras,
                    bucket_heads=heads,
                )
            )
            value = next_page
        return result

    def _read_entity(self, rel: int, base_x: int, base_y: int) -> U9Entity:
        fields = struct.unpack_from(ENTITY_STRUCT, self._data, self.header_size + rel)
        return U9Entity(
            offset=rel,
            next_entity=fields[0],
            offset_x=fields[1],
            offset_y=fields[2],
            z=fields[3],
            type_index=fields[4],
            rotation=(fields[5], fields[6], fields[7], fields[8]),
            flags=fields[9],
            mesh_index=fields[10],
            trigger_id=fields[11],
            extra_data_offset=fields[12],
            base_x=base_x,
            base_y=base_y,
        )

    def _read_extra_data(self, rel: int) -> U9ExtraData:
        fields = struct.unpack_from(EXTRA_STRUCT, self._data, self.header_size + rel)
        return U9ExtraData(
            offset=rel,
            arg_count=fields[0],
            arg_types=(fields[1], fields[2], fields[3]),
            values=(fields[4], fields[5], fields[6]),
        )

    def _looks_like_extra_data(self, rel: int) -> bool:
        if not self._in_payload(rel, EXTRA_SIZE):
            return False
        arg_count, type_0, type_1, type_2 = struct.unpack_from(
            "<4B", self._data, self.header_size + rel
        )
        arg_types = (type_0, type_1, type_2)
        return 1 <= arg_count <= 3 and all(value == 0 for value in arg_types[arg_count:])

    def _walk_free_list(
        self, page: U9Page, head: int, *, size: int, link_offset: int
    ) -> tuple[tuple[int, ...], bool]:
        """Walk one page-local allocator free list and validate every link."""
        offsets: list[int] = []
        seen: set[int] = set()
        rel = head
        page_start = page.offset + PAGE_HEADER_SIZE
        page_end = page.offset + PAGE_SIZE
        while rel:
            if (
                rel in seen
                or rel < page_start
                or rel + size > page_end
                or (rel - page_start) % size != 0
                or not self._in_payload(rel, size)
            ):
                return tuple(offsets), False
            seen.add(rel)
            offsets.append(rel)
            rel = struct.unpack_from("<I", self._data, self.header_size + rel + link_offset)[0]
        return tuple(offsets), True

    def _page_allocations(
        self,
        page: U9Page,
        base_x: int,
        base_y: int,
    ) -> tuple[
        tuple[U9Entity, ...],
        tuple[U9ExtraData, ...],
        tuple[int, ...],
        tuple[int, ...],
        bool,
    ]:
        free_entities, entity_free_list_valid = self._walk_free_list(
            page, page.free_entity_head, size=ENTITY_SIZE, link_offset=0
        )
        free_extras, extra_free_list_valid = self._walk_free_list(
            page,
            page.free_extra_data_head,
            size=EXTRA_SIZE,
            link_offset=FREE_EXTRA_LINK_OFFSET,
        )
        if not self._in_payload(page.offset, PAGE_SIZE):
            return (), (), free_entities, free_extras, False

        free_entity_set = set(free_entities)
        free_extra_set = set(free_extras)
        entities: list[U9Entity] = []
        extras: list[U9ExtraData] = []

        for rel in range(
            page.offset + PAGE_HEADER_SIZE,
            page.offset + PAGE_SIZE,
            ENTITY_SIZE,
        ):
            if rel in free_entity_set:
                continue
            halves = (rel, rel + EXTRA_SIZE)
            half_is_extra = tuple(
                half in free_extra_set or self._looks_like_extra_data(half) for half in halves
            )
            if all(half_is_extra):
                extras.extend(
                    self._read_extra_data(half) for half in halves if half not in free_extra_set
                )
            else:
                entities.append(self._read_entity(rel, base_x, base_y))

        valid = (
            entity_free_list_valid
            and extra_free_list_valid
            and len(entities) == page.entity_count
            and len(extras) == page.extra_data_count
            and (
                2 * len(entities)
                + len(extras)
                + 2 * len(free_entities)
                + len(free_extras)
                == 250
            )
        )
        return (
            tuple(entities),
            tuple(extras),
            free_entities,
            free_extras,
            valid,
        )

    def chunk(self, chunk_x: int, chunk_y: int) -> U9Chunk | None:
        """Return one chunk by grid coordinate, or ``None`` when empty."""
        if not (0 <= chunk_x < self.width and 0 <= chunk_y < self.height):
            raise U9NonfixedError(
                f"chunk ({chunk_x}, {chunk_y}) out of range for a {self.width}x{self.height} region"
            )
        return self.chunk_at(chunk_y * self.width + chunk_x)

    def chunk_at(self, index: int) -> U9Chunk | None:
        """Return one chunk by table index, or ``None`` when empty."""
        pages = self.pages(index)
        if not pages:
            return None

        base_x, base_y = pages[0].base_x, pages[0].base_y

        # Only the first page has the live spatial heads. Include the raw
        # reserved head defensively for hand-built or previously documented
        # files, although it is zero throughout the shipped corpus.
        indexed: list[U9Entity] = []
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
                indexed.append(entity)
                rel = entity.next_entity
        indexed.sort(key=lambda entity: entity.offset)

        allocated_by_offset: dict[int, U9Entity] = {}
        extra_by_offset: dict[int, U9ExtraData] = {}
        free_entities: list[int] = []
        free_extras: list[int] = []
        page_entities_by_offset: dict[int, list[U9Entity]] = {
            page.offset: [] for page in pages
        }
        for entity in indexed:
            page_offset = entity.offset // PAGE_SIZE * PAGE_SIZE
            if page_offset in page_entities_by_offset:
                page_entities_by_offset[page_offset].append(entity)

        allocator_pages: set[int] = set()
        for page in pages:
            page_entities, page_extras, page_free_entities, page_free_extras, valid = (
                self._page_allocations(page, base_x, base_y)
            )
            free_entities.extend(page_free_entities)
            free_extras.extend(page_free_extras)

            indexed_offsets_on_page = {
                entity.offset for entity in page_entities_by_offset[page.offset]
            }
            scanned_offsets = {entity.offset for entity in page_entities}
            if valid and indexed_offsets_on_page <= scanned_offsets:
                allocator_pages.add(page.offset)
                allocated_by_offset.update((entity.offset, entity) for entity in page_entities)
                extra_by_offset.update((extra.offset, extra) for extra in page_extras)
            else:
                # Older savegame pages may retain correct spatial lists and
                # counts but omit allocator free-list state. Do not mistake
                # their stale cell contents for allocations.
                allocated_by_offset.update(
                    (entity.offset, entity)
                    for entity in page_entities_by_offset[page.offset]
                )

        # A spatial chain may legally cross a page boundary; retain indexed
        # records even when a compact fixture omits that page from next_page.
        for entity in indexed:
            allocated_by_offset.setdefault(entity.offset, entity)

        def effective_stored_count(field: str, known_legacy_records: int) -> int:
            """Combine exact pages with cumulative headers from older saves."""
            exact = sum(
                getattr(page, field)
                for page in pages
                if page.offset in allocator_pages
            )
            legacy_values = [
                getattr(page, field)
                for page in pages
                if page.offset not in allocator_pages
            ]
            if not legacy_values:
                return exact
            largest = max(legacy_values)
            # Old savegame pages carry cumulative chunk counts. Compact test
            # fixtures and damaged modern pages may instead carry per-page
            # counts; if the maximum cannot cover known records, use the sum.
            legacy = largest if largest >= known_legacy_records else sum(legacy_values)
            return exact + legacy

        indexed_offsets = {entity.offset for entity in indexed}
        known_legacy_entities = sum(
            len(page_entities_by_offset[page.offset])
            for page in pages
            if page.offset not in allocator_pages
        )
        stored_entity_count = effective_stored_count(
            "entity_count", known_legacy_entities
        )
        entity_slots_complete = len(allocated_by_offset) == stored_entity_count
        unlinked = tuple(
            entity
            for offset, entity in sorted(allocated_by_offset.items())
            if offset not in indexed_offsets
        )

        # Preserve directly referenced records on legacy savegame pages that
        # do not serialize usable allocator free lists.
        for entity in allocated_by_offset.values():
            extra = self.extra_data(entity)
            if extra is not None:
                extra_by_offset.setdefault(extra.offset, extra)
        known_legacy_extras = sum(
            extra.offset // PAGE_SIZE * PAGE_SIZE not in allocator_pages
            for extra in extra_by_offset.values()
        )
        stored_extra_data_count = effective_stored_count(
            "extra_data_count", known_legacy_extras
        )
        extra_slots_complete = len(extra_by_offset) == stored_extra_data_count

        return U9Chunk(
            index=index,
            chunk_x=index % self.width,
            chunk_y=index // self.width,
            base_x=base_x,
            base_y=base_y,
            pages=tuple(pages),
            entities=tuple(indexed),
            unlinked_entities=unlinked,
            extra_data_records=tuple(extra for _, extra in sorted(extra_by_offset.items())),
            free_entity_offsets=tuple(sorted(free_entities)),
            free_extra_data_offsets=tuple(sorted(free_extras)),
            entity_slots_complete=entity_slots_complete,
            extra_data_slots_complete=extra_slots_complete,
            stored_entity_count=stored_entity_count,
            stored_extra_data_count=stored_extra_data_count,
        )

    def chunks(self) -> list[U9Chunk]:
        """Return every populated chunk in table order."""
        result = []
        for index in self.used_chunk_indices():
            chunk = self.chunk_at(index)
            if chunk is not None:
                result.append(chunk)
        return result

    def entities(self) -> list[U9Entity]:
        """Return spatially indexed entities from every chunk."""
        return [entity for chunk in self.chunks() for entity in chunk.entities]

    def allocated_entities(self) -> list[U9Entity]:
        """Return every allocated entity, including unlinked records."""
        return [entity for chunk in self.chunks() for entity in chunk.allocated_entities]

    def extra_data_records(self) -> list[U9ExtraData]:
        """Return every allocated 16-byte extra-data record."""
        return [extra for chunk in self.chunks() for extra in chunk.extra_data_records]

    def extra_data(self, entity: U9Entity) -> U9ExtraData | None:
        """Decode the record referenced by an entity, or ``None`` if invalid."""
        rel = entity.extra_data_offset
        if not rel or not self._looks_like_extra_data(rel):
            return None
        return self._read_extra_data(rel)
