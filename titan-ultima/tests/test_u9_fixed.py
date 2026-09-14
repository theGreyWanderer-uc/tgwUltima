"""Tests for titan.u9.fixed's static/fixed.%d decoder.

Fixtures match the layout verified against 164 real region files (2,815
chunks, 3,315 pages, 152,383 live objects). The properties pinned down here are
the ones that separate this format from its sibling ``nonfixed``, and the ones
the published documentation gets wrong:

* the header is ``0x20 + 4*w*h``, one field shorter at each end than nonfixed;
* the chunk table is **not** row-major, so a chunk's grid position has to come
  from its page's base, not from the table slot;
* an object's rotation is **four** ``int16`` components, not three plus a
  flags word;
* page offset ``0x04`` heads a free-slot list and page offset ``0x14`` is the
  live-object count, so occupied slots are sparse rather than a dense prefix.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.fixed import (
    MAX_OBJECTS_PER_PAGE,
    OBJECT_SIZE,
    PAGE_HEADER_SIZE,
    U9Fixed,
    U9FixedError,
)

TABLE_OFFSET = 0x20


def _object(
    *,
    reference: int = 0,
    x: int = 0,
    y: int = 0,
    z: int = 0,
    type_index: int = 0,
    rotation: tuple[int, int, int, int] = (0, 0, 0, -32768),
    flags: int = 0,
) -> bytes:
    return struct.pack("<I4H4hI", reference, x, y, z, type_index, *rotation, flags)


def _page(
    *,
    base_x: int,
    base_y: int,
    objects: list[bytes],
    page_offset: int,
    next_page: int = 0,
) -> bytes:
    """Build a real-sized page with a dense live prefix and valid free list."""
    return _sparse_page(
        base_x=base_x,
        base_y=base_y,
        live_objects=dict(enumerate(objects)),
        page_offset=page_offset,
        next_page=next_page,
    )


def _sparse_page(
    *,
    base_x: int,
    base_y: int,
    live_objects: dict[int, bytes],
    page_offset: int,
    next_page: int = 0,
) -> bytes:
    """Build one real-sized page whose unused slots form the free list."""
    if any(not 0 <= slot < MAX_OBJECTS_PER_PAGE for slot in live_objects):
        raise ValueError("live object slot outside the 166-slot page")
    page = bytearray(0x1000)
    free_slots = [i for i in range(MAX_OBJECTS_PER_PAGE) if i not in live_objects]
    free_head = (
        page_offset + PAGE_HEADER_SIZE + free_slots[0] * OBJECT_SIZE
        if free_slots
        else 0
    )
    struct.pack_into(
        "<6I",
        page,
        0,
        next_page,
        free_head,
        0,
        base_x,
        base_y,
        len(live_objects),
    )
    for slot, record in live_objects.items():
        start = PAGE_HEADER_SIZE + slot * OBJECT_SIZE
        page[start : start + OBJECT_SIZE] = record
    for index, slot in enumerate(free_slots):
        next_free = (
            page_offset + PAGE_HEADER_SIZE + free_slots[index + 1] * OBJECT_SIZE
            if index + 1 < len(free_slots)
            else 0
        )
        struct.pack_into("<I", page, PAGE_HEADER_SIZE + slot * OBJECT_SIZE, next_free)
    return bytes(page)


def _build(width: int, height: int, table: list[int], payload: bytes) -> bytes:
    head = bytearray(TABLE_OFFSET + width * height * 4)
    struct.pack_into("<I", head, 0x08, len(payload))
    struct.pack_into("<I", head, 0x0C, 0x00C00000)
    struct.pack_into("<II", head, 0x10, width, height)
    struct.pack_into("<I", head, 0x1C, 1)
    struct.pack_into(f"<{width * height}I", head, TABLE_OFFSET, *table)
    return bytes(head) + payload


class FixedHeaderTests(unittest.TestCase):
    def test_header_size_formula(self) -> None:
        # 0x20 + 4wh -- nonfixed is 36 + 4wh, a field longer at each end.
        for w, h in ((2, 2), (4, 4), (32, 32)):
            region = U9Fixed(_build(w, h, [0] * (w * h), b""))
            self.assertEqual(region.header_size, 0x20 + 4 * w * h)
            self.assertEqual(region.num_chunks, w * h)

    def test_zero_table_entry_means_no_pages(self) -> None:
        region = U9Fixed(_build(2, 2, [0, 0, 0, 0], b""))
        self.assertEqual(region.used_table_indices(), [])
        self.assertEqual(region.chunks(), [])

    def test_rejects_short_data(self) -> None:
        with self.assertRaises(U9FixedError):
            U9Fixed(b"\x00" * 8)

    def test_rejects_implausible_grid(self) -> None:
        data = bytearray(_build(2, 2, [0, 0, 0, 0], b""))
        struct.pack_into("<I", data, 0x10, 0xDEADBEEF)
        with self.assertRaises(U9FixedError):
            U9Fixed(bytes(data))

    def test_rejects_truncated_table(self) -> None:
        with self.assertRaises(U9FixedError):
            U9Fixed(_build(8, 8, [0] * 64, b"")[:-40])


class FixedObjectTests(unittest.TestCase):
    def setUp(self) -> None:
        objects = [
            _object(
                reference=0x20A8,
                x=1852,
                y=3964,
                z=2469,
                type_index=642,
                rotation=(0, 0, 12539, -32768),
                flags=0x300033,
            ),
            _object(
                x=100,
                y=200,
                z=300,
                type_index=2836,
                rotation=(16383, 16383, 16383, 16383),
            ),
        ]
        payload = _page(base_x=4096, base_y=0, objects=objects, page_offset=0)
        # table is one-based, and slot 0 need not be chunk (0,0)
        self.data = _build(2, 2, [1, 0, 0, 0], payload)

    def test_object_fields(self) -> None:
        chunk = U9Fixed(self.data).chunk_at(0)
        assert chunk is not None
        self.assertEqual(len(chunk.objects), 2)
        o = chunk.objects[0]
        self.assertEqual(o.reference, 0x20A8)
        self.assertEqual((o.x, o.y, o.z), (1852, 3964, 2469))
        self.assertEqual(o.type_index, 642)
        self.assertEqual(o.rotation, (0, 0, 12539, -32768))
        self.assertEqual(o.flags, 0x300033)

    def test_rotation_is_four_components_and_normalised(self) -> None:
        # The Codex documents three components plus a u16 flags field. Read
        # that way this rotation is not a unit vector; read as four it is.
        chunk = U9Fixed(self.data).chunk_at(0)
        assert chunk is not None
        q = chunk.objects[1].quaternion
        self.assertEqual(len(q), 4)
        self.assertAlmostEqual(sum(v * v for v in q), 1.0, places=3)

    def test_world_coordinates_add_the_chunk_base(self) -> None:
        chunk = U9Fixed(self.data).chunk_at(0)
        assert chunk is not None
        o = chunk.objects[0]
        self.assertEqual(o.world_x, 4096 + 1852)
        self.assertEqual(o.world_y, 0 + 3964)


class FixedChunkTests(unittest.TestCase):
    """The table is not row-major; position comes from the page's base."""

    def setUp(self) -> None:
        a = _page(base_x=4096, base_y=0, objects=[_object(x=1)], page_offset=0)
        b = _page(
            base_x=0,
            base_y=4096,
            objects=[_object(x=2), _object(x=3)],
            page_offset=len(a),
        )
        # slot 0 -> chunk (1,0), slot 1 -> chunk (0,1): deliberately not row-major
        self.region = U9Fixed(_build(2, 2, [1, len(a) + 1, 0, 0], a + b))

    def test_grid_position_comes_from_the_base_not_the_slot(self) -> None:
        chunks = self.region.chunks()
        self.assertEqual(
            [(c.table_index, c.chunk_x, c.chunk_y) for c in chunks],
            [(0, 1, 0), (1, 0, 1)],
        )

    def test_lookup_by_grid_finds_the_right_slot(self) -> None:
        chunk = self.region.chunk(0, 1)
        assert chunk is not None
        self.assertEqual(chunk.table_index, 1)
        self.assertEqual(len(chunk.objects), 2)
        self.assertIsNone(self.region.chunk(0, 0))

    def test_lookup_out_of_range_raises(self) -> None:
        with self.assertRaises(U9FixedError):
            self.region.chunk(9, 9)

    def test_objects_spans_every_chunk(self) -> None:
        self.assertEqual([o.x for o in self.region.objects()], [1, 2, 3])


class FixedPageChainTests(unittest.TestCase):
    def setUp(self) -> None:
        second = _page(
            base_x=4096, base_y=4096, objects=[_object(x=9)], page_offset=0x1000
        )
        first = _page(
            base_x=4096,
            base_y=4096,
            objects=[_object(x=7), _object(x=8)],
            page_offset=0,
            next_page=0x1000 + 1,
        )
        payload = first + b"\x00" * (0x1000 - len(first)) + second
        self.data = _build(2, 2, [1, 0, 0, 0], payload)

    def test_chain_is_followed_and_objects_concatenated(self) -> None:
        chunk = U9Fixed(self.data).chunk_at(0)
        assert chunk is not None
        self.assertEqual([p.offset for p in chunk.pages], [0, 0x1000])
        self.assertEqual([o.x for o in chunk.objects], [7, 8, 9])

    def test_all_pages_in_a_chain_share_the_base(self) -> None:
        chunk = U9Fixed(self.data).chunk_at(0)
        assert chunk is not None
        self.assertEqual({(p.base_x, p.base_y) for p in chunk.pages}, {(4096, 4096)})

    def test_cyclic_chain_terminates(self) -> None:
        data = bytearray(self.data)
        region = U9Fixed(bytes(data))
        struct.pack_into("<I", data, region.header_size + 0x1000, 0 + 1)
        chunk = U9Fixed(bytes(data)).chunk_at(0)
        assert chunk is not None
        self.assertEqual([p.offset for p in chunk.pages], [0, 0x1000])


class FixedCountTests(unittest.TestCase):
    def test_sparse_slots_come_from_free_list_complement(self) -> None:
        # Slot zero is free while live objects sit later in the page. Treating
        # the free-list head as an end offset would incorrectly return zero.
        payload = _sparse_page(
            base_x=0,
            base_y=0,
            live_objects={43: _object(x=43), 100: _object(x=100)},
            page_offset=0,
        )
        chunk = U9Fixed(_build(2, 2, [1, 0, 0, 0], payload)).chunk_at(0)
        assert chunk is not None
        self.assertTrue(chunk.pages[0].free_list_walked)
        self.assertEqual(chunk.pages[0].free_list_head, PAGE_HEADER_SIZE)
        self.assertEqual(chunk.pages[0].live_count, 2)
        self.assertEqual(chunk.pages[0].live_slots, (43, 100))
        self.assertEqual(chunk.pages[0].object_count, 2)
        self.assertEqual([obj.x for obj in chunk.objects], [43, 100])
        self.assertEqual(len(chunk.objects), 2)

    def test_empty_synthetic_page_yields_no_objects(self) -> None:
        header = struct.pack("<6I", 0, 0, 0, 0, 0, 0) + b"\x00" * (
            PAGE_HEADER_SIZE - 24
        )
        chunk = U9Fixed(_build(2, 2, [1, 0, 0, 0], header)).chunk_at(0)
        assert chunk is not None
        self.assertEqual(chunk.objects, ())

    def test_malformed_fallback_count_is_capped_at_a_page(self) -> None:
        # 0x60 + 166*24 is as much as a 4 KiB page holds.
        header = struct.pack("<6I", 0, 0xFFFF, 0, 0, 0, 0) + b"\x00" * (
            PAGE_HEADER_SIZE - 24
        )
        region = U9Fixed(_build(2, 2, [1, 0, 0, 0], header + b"\x00" * 0x4000))
        chunk = region.chunk_at(0)
        assert chunk is not None
        self.assertLessEqual(chunk.pages[0].object_count, 166)


if __name__ == "__main__":
    unittest.main()
