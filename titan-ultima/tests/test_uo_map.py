"""Tests for UO facet terrain/statics reading and radar rendering."""

from __future__ import annotations

import struct

import pytest

from titan.uo.map import BLOCK_BYTES, UOMap
from titan.uo.radar import UORadarColor, UORadarColors
from titan.uo.uop import hash_uop_path

# 16x24 tiles -> 2 blocks wide, 3 blocks high, column-major block order.
WIDTH, HEIGHT = 16, 24
BLOCKS_HIGH = 3


def _land(cell_for) -> bytes:
    out = bytearray()
    for bx in range(2):
        for by in range(BLOCKS_HIGH):
            out += struct.pack("<I", bx * BLOCKS_HIGH + by)
            for ty in range(8):
                for tx in range(8):
                    tile_id, z = cell_for(bx * 8 + tx, by * 8 + ty)
                    out += struct.pack("<Hb", tile_id, z)
    return bytes(out)


def _statics(blocks: dict[int, list[tuple[int, int, int, int, int]]]):
    index = bytearray()
    data = bytearray()
    for block in range(2 * BLOCKS_HIGH):
        records = blocks.get(block)
        if records is None:
            index += struct.pack("<III", 0xFFFFFFFF, 0, 0xFFFFFFFF)
            continue
        index += struct.pack("<III", len(data), len(records) * 7, 0)
        for record in records:
            data += struct.pack("<HBBbH", *record)
    return bytes(index), bytes(data)


def _cell(x: int, y: int) -> tuple[int, int]:
    return (x + y * 100, (x - y) % 50)


def _uop(entries: list[tuple[str, bytes]]) -> bytes:
    header_size = 28
    table_offset = header_size
    table_size = 12 + 34 * len(entries)
    payload_offset = table_offset + table_size
    table = struct.pack("<IQ", len(entries), 0)
    payloads = b""
    for name, payload in entries:
        offset = payload_offset + len(payloads)
        table += struct.pack(
            "<QIIIQIh",
            offset,
            0,
            len(payload),
            len(payload),
            hash_uop_path(name),
            0,
            0,
        )
        payloads += payload
    header = struct.pack("<IIIQII", 0x0050594D, 5, 0xFD23EC43, table_offset, 1, len(entries))
    return header + table + payloads


def test_land_layout_is_column_major_blocks_row_major_cells():
    index, data = _statics({})
    facet = UOMap(_land(_cell), index, data, WIDTH, HEIGHT)

    assert facet.block_index(1, 2) == 1 * BLOCKS_HIGH + 2
    assert facet.block_header(1, 2) == 5
    for x, y in [(0, 0), (7, 0), (0, 7), (9, 3), (15, 23), (3, 17)]:
        assert facet.land_tile(x, y).tile_id == _cell(x, y)[0]
        assert facet.land_tile(x, y).z == _cell(x, y)[1]

    ids, z = facet.land_arrays()
    assert ids.shape == (HEIGHT, WIDTH)
    assert int(ids[17, 3]) == _cell(3, 17)[0]
    assert int(z[3, 9]) == _cell(9, 3)[1]


def test_statics_world_coordinates_and_empty_blocks():
    index, data = _statics(
        {
            4: [(0x100, 2, 5, 10, 0), (0x101, 2, 5, 20, 33)],  # block (1, 1)
            1: [],  # real offset, zero length: also empty
        }
    )
    facet = UOMap(_land(_cell), index, data, WIDTH, HEIGHT)

    items = facet.statics_at(10, 13)
    assert [(i.tile_id, i.z, i.hue) for i in items] == [(0x100, 10, 0), (0x101, 20, 33)]
    assert facet.statics_block(0, 1) == []
    assert facet.statics_block(0, 0) == []

    records = facet.static_records()
    assert list(records["x"]) == [10, 10]
    assert list(records["y"]) == [13, 13]
    summary = facet.static_index_summary()
    assert summary["static_count"] == 2
    assert summary["blocks_zero_length"] == 1
    assert summary["blocks_no_data"] == 4


def test_radar_uses_highest_static_at_or_above_land():
    land = _land(lambda x, y: (1, 0))
    index, data = _statics(
        {
            0: [(5, 1, 1, 0, 0), (6, 1, 1, 9, 0), (7, 2, 2, -5, 0)],
        }
    )
    facet = UOMap(land, index, data, WIDTH, HEIGHT)
    colors = [UORadarColor(i, 0) for i in range(0x4010)]
    colors[1] = UORadarColor(1, 0x001F)  # land: blue
    colors[0x4006] = UORadarColor(0x4006, 0x7C00)  # static 6: red
    colors[0x4007] = UORadarColor(0x4007, 0x03E0)  # static 7: green
    image = facet.render_radar(UORadarColors(colors))

    assert image.size == (WIDTH, HEIGHT)
    assert image.getpixel((1, 1)) == (255, 0, 0)
    assert image.getpixel((2, 2)) == (0, 0, 255)  # below ground: land shows
    assert image.getpixel((0, 0)) == (0, 0, 255)
    terrain = facet.render_radar(UORadarColors(colors), statics=False)
    assert terrain.getpixel((1, 1)) == (0, 0, 255)


def test_from_client_reads_uop_and_trims_trailing_block(tmp_path):
    land = _land(_cell)
    chunk = 4 * BLOCK_BYTES
    entries = [
        (f"build/map7legacymul/{i:08d}.dat", land[start : start + chunk])
        for i, start in enumerate(range(0, len(land), chunk))
    ]
    entries[-1] = (entries[-1][0], entries[-1][1] + bytes(BLOCK_BYTES))
    (tmp_path / "map7LegacyMUL.uop").write_bytes(_uop(entries))
    index, data = _statics({0: [(0x200, 0, 0, 0, 0)]})
    (tmp_path / "staidx7.mul").write_bytes(index)
    (tmp_path / "statics7.mul").write_bytes(data)

    facet = UOMap.from_client(tmp_path, 7, width=WIDTH, height=HEIGHT)
    assert facet.source.land_container == "uop"
    assert facet.source.trailing_land_blocks == 1
    assert facet.land == land

    with pytest.raises(ValueError, match="cannot infer"):
        UOMap.from_client(tmp_path, 7)


def test_static_and_land_patches(tmp_path):
    (tmp_path / "map0.mul").write_bytes(_land(_cell))
    index, data = _statics({0: [(0x200, 0, 0, 0, 0)]})
    (tmp_path / "staidx0.mul").write_bytes(index)
    (tmp_path / "statics0.mul").write_bytes(data)

    patched_block = bytes(4) + struct.pack("<Hb", 0x777, 3) * 64
    (tmp_path / "mapdifl0.mul").write_bytes(struct.pack("<I", 2))
    (tmp_path / "mapdif0.mul").write_bytes(patched_block)
    (tmp_path / "stadifl0.mul").write_bytes(struct.pack("<II", 0, 4))
    (tmp_path / "stadifi0.mul").write_bytes(
        struct.pack("<III", 0xFFFFFFFF, 0, 0) + struct.pack("<III", 0, 7, 0)
    )
    (tmp_path / "stadif0.mul").write_bytes(struct.pack("<HBBbH", 0x300, 1, 1, 4, 0))

    plain = UOMap.from_client(tmp_path, 0, width=WIDTH, height=HEIGHT)
    assert len(plain.statics_block(0, 0)) == 1

    facet = UOMap.from_client(tmp_path, 0, width=WIDTH, height=HEIGHT, patches=True)
    assert facet.source.land_patch_blocks == 1
    assert facet.source.static_patch_blocks == 2
    assert facet.land_tile(0, 16) == plain.land_tile(0, 16).__class__(0x777, 3)
    assert facet.statics_block(0, 0) == []
    assert [(i.tile_id, i.x, i.y) for i in facet.statics_block(1, 1)] == [(0x300, 9, 9)]
