"""Tests for titan.u9.nonfixed's runtime/nonfixed.%d decoder.

Fixtures are built to the exact byte layout verified against 166 real
region files -- see the module docstring and
``reference/u9/nonfixed/u9_nonfixed_reference.md``. The properties they
pin down are the ones that verification established:

* header size is ``36 + 4*width*height``;
* chunk-table entries and ``next_page`` are biased by one, and ``0``
  means "none" rather than "offset 0";
* ``base_x``/``base_y`` are ``(chunk_x, chunk_y) * 4096``;
* ``next_entity`` is a ``uint32``, region-relative -- a ``uint16``
  reading loses every link past the first 64 KiB;
* ``entity_count`` is per page, so a chunk's expected total is the sum
  over its page chain.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.nonfixed import U9Nonfixed, U9NonfixedError

PAGE_HEADER_SIZE = 0x60
ENTITY_SIZE = 0x20
EXTRA_SIZE = 0x10
BUCKET_COUNT = 17


def _header(width: int, height: int, table: list[int], payload_size: int = 0) -> bytes:
    """File header: 5 unknown u32, width, height, unknown, table, trailer."""
    out = struct.pack("<5I", 0, 0, 0, payload_size, 0x00C00000)
    out += struct.pack("<III", width, height, 1)
    out += struct.pack(f"<{width * height}I", *table)
    out += struct.pack("<I", 0)
    return out


def _page(
    *,
    next_page: int = 0,
    end_entity: int = 0,
    end_trigger: int = 0,
    base_x: int = 0,
    base_y: int = 0,
    entity_count: int = 0,
    trigger_count: int = 0,
    heads: list[int] | None = None,
) -> bytes:
    heads = list(heads or [])
    heads += [0] * (BUCKET_COUNT - len(heads))
    out = struct.pack(
        "<7I", next_page, end_entity, end_trigger, base_x, base_y, entity_count, trigger_count
    )
    out += struct.pack(f"<{BUCKET_COUNT}I", *heads)
    assert len(out) == PAGE_HEADER_SIZE
    return out


def _entity(
    *,
    next_entity: int = 0,
    x: int = 0,
    y: int = 0,
    z: int = 0,
    type_index: int = 0,
    rotation: tuple[int, int, int, int] = (0, 0, 0, -32768),
    flags: int = 0,
    mesh_index: int = 0,
    trigger_id: int = 0,
    extra: int = 0,
) -> bytes:
    out = struct.pack(
        "<IHHHH4hIHHI",
        next_entity, x, y, z, type_index,
        rotation[0], rotation[1], rotation[2], rotation[3],
        flags, mesh_index, trigger_id, extra,
    )
    assert len(out) == ENTITY_SIZE
    return out


def _extra(arg_count: int, arg_types: tuple[int, int, int], values: tuple[int, int, int]) -> bytes:
    out = struct.pack("<B3B3I", arg_count, *arg_types, *values)
    assert len(out) == EXTRA_SIZE
    return out


class NonfixedHeaderTests(unittest.TestCase):
    def test_header_size_formula(self) -> None:
        for width, height in ((2, 2), (4, 4), (8, 8), (32, 32)):
            data = _header(width, height, [0] * (width * height))
            region = U9Nonfixed(data)
            self.assertEqual(region.header_size, 36 + 4 * width * height)
            self.assertEqual(len(data), region.header_size)
            self.assertEqual(region.num_chunks, width * height)

    def test_zero_table_entry_means_empty_not_offset_zero(self) -> None:
        region = U9Nonfixed(_header(2, 2, [0, 0, 0, 0]))
        self.assertEqual(region.used_chunk_indices(), [])
        self.assertEqual(region.chunks(), [])
        self.assertIsNone(region.chunk(0, 0))

    def test_rejects_short_data(self) -> None:
        with self.assertRaises(U9NonfixedError):
            U9Nonfixed(b"\x00" * 8)

    def test_rejects_implausible_grid(self) -> None:
        data = bytearray(_header(2, 2, [0, 0, 0, 0]))
        struct.pack_into("<I", data, 0x14, 0xDEADBEEF)
        with self.assertRaises(U9NonfixedError):
            U9Nonfixed(bytes(data))

    def test_rejects_truncated_table(self) -> None:
        with self.assertRaises(U9NonfixedError):
            U9Nonfixed(_header(8, 8, [0] * 64)[:-40])

    def test_payload_size_is_measured_not_declared(self) -> None:
        # The 0x0C watermark is 0 on empty regions that still carry a
        # preallocated payload, and overstates it in at least one shipped file.
        data = _header(2, 2, [0, 0, 0, 0], payload_size=0) + b"\x00" * 0x1000
        region = U9Nonfixed(data)
        self.assertEqual(region.declared_payload_size, 0)
        self.assertEqual(region.payload_size, 0x1000)


class NonfixedChunkTests(unittest.TestCase):
    def setUp(self) -> None:
        # One 2x2 region. Chunk (1, 0) -- table index 1 -- has a single page
        # at region-relative offset 0, so its table entry is 1, not 0.
        entities = (
            _entity(next_entity=PAGE_HEADER_SIZE + ENTITY_SIZE, x=10, y=20, z=30, type_index=203, mesh_index=1210)
            + _entity(next_entity=0, x=40, y=50, z=60, type_index=295, mesh_index=3009, trigger_id=7)
        )
        payload = _page(
            base_x=4096, base_y=0, entity_count=2, trigger_count=3,
            end_entity=PAGE_HEADER_SIZE + 2 * ENTITY_SIZE,
            heads=[PAGE_HEADER_SIZE],
        ) + entities
        self.data = _header(2, 2, [0, 1, 0, 0], payload_size=len(payload)) + payload

    def test_chunk_lookup_and_base_coordinates(self) -> None:
        region = U9Nonfixed(self.data)
        self.assertEqual(region.used_chunk_indices(), [1])
        chunk = region.chunk(1, 0)
        assert chunk is not None
        self.assertEqual((chunk.chunk_x, chunk.chunk_y), (1, 0))
        self.assertEqual((chunk.base_x, chunk.base_y), (4096, 0))
        self.assertEqual(len(chunk.pages), 1)
        self.assertEqual(chunk.pages[0].offset, 0)

    def test_walks_entity_list(self) -> None:
        chunk = U9Nonfixed(self.data).chunk(1, 0)
        assert chunk is not None
        self.assertEqual(len(chunk.entities), 2)
        self.assertEqual(chunk.declared_entity_count, 2)
        self.assertTrue(chunk.is_complete)

        first, second = chunk.entities
        self.assertEqual((first.offset_x, first.offset_y, first.z), (10, 20, 30))
        self.assertEqual(first.type_index, 203)
        self.assertEqual(first.mesh_index, 1210)
        self.assertEqual(second.trigger_id, 7)

    def test_world_coordinates_add_the_chunk_base(self) -> None:
        chunk = U9Nonfixed(self.data).chunk(1, 0)
        assert chunk is not None
        first = chunk.entities[0]
        self.assertEqual(first.world_x, 4096 + 10)
        self.assertEqual(first.world_y, 0 + 20)

    def test_trigger_count_is_summed(self) -> None:
        chunk = U9Nonfixed(self.data).chunk(1, 0)
        assert chunk is not None
        self.assertEqual(chunk.trigger_count, 3)

    def test_out_of_range_chunk_raises(self) -> None:
        region = U9Nonfixed(self.data)
        with self.assertRaises(U9NonfixedError):
            region.chunk(2, 0)
        with self.assertRaises(U9NonfixedError):
            region.chunk_at(99)


class NonfixedPageChainTests(unittest.TestCase):
    """entity_count is per page; a chunk's total is the sum over the chain."""

    def setUp(self) -> None:
        # Page A at 0x0000 holds one entity and chains to page B at 0x1000,
        # which holds one more. Only page A carries the live bucket heads,
        # and one head's list spans both pages.
        page_a = _page(
            next_page=0x1000 + 1,  # biased by one
            base_x=0, base_y=0, entity_count=1,
            heads=[PAGE_HEADER_SIZE],
        )
        ent_a = _entity(next_entity=0x1000 + PAGE_HEADER_SIZE, x=1, y=2, type_index=11)
        filler = b"\x00" * (0x1000 - len(page_a) - len(ent_a))
        page_b = _page(base_x=0, base_y=0, entity_count=1, heads=[0])
        ent_b = _entity(next_entity=0, x=3, y=4, type_index=22)
        payload = page_a + ent_a + filler + page_b + ent_b
        self.data = _header(2, 2, [1, 0, 0, 0], payload_size=len(payload)) + payload

    def test_page_chain_is_followed(self) -> None:
        chunk = U9Nonfixed(self.data).chunk(0, 0)
        assert chunk is not None
        self.assertEqual([p.offset for p in chunk.pages], [0, 0x1000])

    def test_declared_count_sums_over_pages(self) -> None:
        chunk = U9Nonfixed(self.data).chunk(0, 0)
        assert chunk is not None
        self.assertEqual(chunk.declared_entity_count, 2)
        self.assertEqual(len(chunk.entities), 2)
        self.assertTrue(chunk.is_complete)
        self.assertEqual([e.type_index for e in chunk.entities], [11, 22])

    def test_cyclic_page_chain_terminates(self) -> None:
        data = bytearray(self.data)
        region = U9Nonfixed(bytes(data))
        # Point page B back at page A; the walk must stop rather than spin.
        struct.pack_into("<I", data, region.header_size + 0x1000, 0 + 1)
        chunk = U9Nonfixed(bytes(data)).chunk(0, 0)
        assert chunk is not None
        self.assertEqual([p.offset for p in chunk.pages], [0, 0x1000])


class NonfixedNextEntityWidthTests(unittest.TestCase):
    """next_entity is a uint32, not a uint16 plus an unknown uint16."""

    def setUp(self) -> None:
        # Two entities: the head in the first page, its successor past the
        # 64 KiB mark so the link needs all 32 bits.
        self.far = 0x10000 + PAGE_HEADER_SIZE
        page = _page(base_x=0, base_y=0, entity_count=2, heads=[PAGE_HEADER_SIZE])
        head = _entity(next_entity=self.far, x=1, y=1, type_index=100)
        pad = b"\x00" * (0x10000 - len(page) - len(head))
        far_page = _page(base_x=0, base_y=0, entity_count=0)
        far_entity = _entity(next_entity=0, x=2, y=2, type_index=200)
        payload = page + head + pad + far_page + far_entity
        self.data = _header(2, 2, [1, 0, 0, 0], payload_size=len(payload)) + payload

    def test_link_past_64k_is_followed(self) -> None:
        chunk = U9Nonfixed(self.data).chunk(0, 0)
        assert chunk is not None
        self.assertEqual(len(chunk.entities), 2)
        self.assertEqual([e.type_index for e in chunk.entities], [100, 200])
        self.assertEqual(chunk.entities[1].offset, self.far)
        self.assertTrue(chunk.is_complete)

    def test_high_half_is_not_a_separate_field(self) -> None:
        region = U9Nonfixed(self.data)
        chunk = region.chunk(0, 0)
        assert chunk is not None
        self.assertEqual(chunk.entities[0].next_entity, self.far)
        self.assertGreater(chunk.entities[0].next_entity, 0xFFFF)


class NonfixedRobustnessTests(unittest.TestCase):
    def test_cyclic_entity_list_terminates(self) -> None:
        # A list that points back at its own head must not spin.
        page = _page(base_x=0, base_y=0, entity_count=1, heads=[PAGE_HEADER_SIZE])
        ent = _entity(next_entity=PAGE_HEADER_SIZE, x=5, y=5)
        payload = page + ent
        data = _header(2, 2, [1, 0, 0, 0], payload_size=len(payload)) + payload
        chunk = U9Nonfixed(data).chunk(0, 0)
        assert chunk is not None
        self.assertEqual(len(chunk.entities), 1)

    def test_link_past_end_of_payload_is_dropped(self) -> None:
        page = _page(base_x=0, base_y=0, entity_count=2, heads=[PAGE_HEADER_SIZE])
        ent = _entity(next_entity=0xFFFFF0, x=5, y=5)
        payload = page + ent
        data = _header(2, 2, [1, 0, 0, 0], payload_size=len(payload)) + payload
        chunk = U9Nonfixed(data).chunk(0, 0)
        assert chunk is not None
        self.assertEqual(len(chunk.entities), 1)
        # Undershooting the declared count is reported, never papered over.
        self.assertFalse(chunk.is_complete)
        self.assertEqual(chunk.declared_entity_count, 2)

    def test_entities_shared_between_buckets_are_not_double_counted(self) -> None:
        page = _page(
            base_x=0, base_y=0, entity_count=1,
            heads=[PAGE_HEADER_SIZE, PAGE_HEADER_SIZE],
        )
        payload = page + _entity(next_entity=0, x=1, y=1)
        data = _header(2, 2, [1, 0, 0, 0], payload_size=len(payload)) + payload
        chunk = U9Nonfixed(data).chunk(0, 0)
        assert chunk is not None
        self.assertEqual(len(chunk.entities), 1)


class NonfixedExtraDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extra_off = PAGE_HEADER_SIZE + ENTITY_SIZE
        page = _page(base_x=0, base_y=0, entity_count=1, heads=[PAGE_HEADER_SIZE])
        ent = _entity(next_entity=0, x=1, y=1, extra=self.extra_off)
        payload = page + ent + _extra(2, (66, 62, 0), (1000, 2000, 0))
        self.data = _header(2, 2, [1, 0, 0, 0], payload_size=len(payload)) + payload

    def test_decodes_extra_data(self) -> None:
        region = U9Nonfixed(self.data)
        chunk = region.chunk(0, 0)
        assert chunk is not None
        entity = chunk.entities[0]
        self.assertTrue(entity.has_extra_data)

        extra = region.extra_data(entity)
        assert extra is not None
        self.assertEqual(extra.arg_count, 2)
        self.assertEqual(extra.arg_types, (66, 62, 0))
        self.assertEqual(extra.values, (1000, 2000, 0))
        self.assertEqual(extra.args, [(66, 1000), (62, 2000)])

    def test_entity_without_extra_data(self) -> None:
        page = _page(base_x=0, base_y=0, entity_count=1, heads=[PAGE_HEADER_SIZE])
        payload = page + _entity(next_entity=0, extra=0)
        region = U9Nonfixed(_header(2, 2, [1, 0, 0, 0], payload_size=len(payload)) + payload)
        chunk = region.chunk(0, 0)
        assert chunk is not None
        entity = chunk.entities[0]
        self.assertFalse(entity.has_extra_data)
        self.assertIsNone(region.extra_data(entity))

    def test_out_of_range_extra_offset_returns_none(self) -> None:
        data = bytearray(self.data)
        region = U9Nonfixed(bytes(data))
        struct.pack_into("<I", data, region.header_size + PAGE_HEADER_SIZE + 0x1C, 0xFFFFF0)
        region = U9Nonfixed(bytes(data))
        chunk = region.chunk(0, 0)
        assert chunk is not None
        self.assertIsNone(region.extra_data(chunk.entities[0]))


class NonfixedRotationTests(unittest.TestCase):
    def test_quaternion_is_scaled_by_32767(self) -> None:
        page = _page(base_x=0, base_y=0, entity_count=1, heads=[PAGE_HEADER_SIZE])
        payload = page + _entity(next_entity=0, rotation=(0, 0, 32767, -32767))
        region = U9Nonfixed(_header(2, 2, [1, 0, 0, 0], payload_size=len(payload)) + payload)
        chunk = region.chunk(0, 0)
        assert chunk is not None
        qx, qy, qz, qw = chunk.entities[0].quaternion
        self.assertEqual((qx, qy), (0.0, 0.0))
        self.assertAlmostEqual(qz, 1.0)
        self.assertAlmostEqual(qw, -1.0)


class NonfixedRegionTests(unittest.TestCase):
    def test_entities_spans_every_chunk(self) -> None:
        # Two populated chunks, one page each, one entity each.
        page0 = _page(base_x=0, base_y=0, entity_count=1, heads=[PAGE_HEADER_SIZE])
        ent0 = _entity(next_entity=0, x=1, y=1, type_index=7)
        block0 = page0 + ent0
        page1 = _page(base_x=4096, base_y=0, entity_count=1, heads=[len(block0) + PAGE_HEADER_SIZE])
        ent1 = _entity(next_entity=0, x=2, y=2, type_index=8)
        payload = block0 + page1 + ent1
        data = _header(2, 2, [1, len(block0) + 1, 0, 0], payload_size=len(payload)) + payload

        region = U9Nonfixed(data)
        self.assertEqual(len(region.chunks()), 2)
        entities = region.entities()
        self.assertEqual([e.type_index for e in entities], [7, 8])
        self.assertEqual([e.world_x for e in entities], [1, 4096 + 2])


if __name__ == "__main__":
    unittest.main()
