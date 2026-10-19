"""UO map inventory: per-tile counts, altitude and spread, name rollup, outputs."""

from __future__ import annotations

import csv
import json
import struct

from titan.uo.map import UOMap
from titan.uo.map_inventory import build_uo_map_inventory, tile_category, write_uo_map_inventory
from titan.uo.tiledata import UOLandTile, UOStaticTile, UOTileData

# 16x16 tiles -> 2x2 blocks, column-major block order.
BLOCKS = 2


def _land() -> bytes:
    out = bytearray()
    for bx in range(BLOCKS):
        for by in range(BLOCKS):
            out += struct.pack("<I", 0)
            for ty in range(8):
                for tx in range(8):
                    # Grass everywhere except a row of sand at y == 0.
                    tile_id = 0x16 if by == 0 and ty == 0 else 0x03
                    out += struct.pack("<Hb", tile_id, 5)
    return bytes(out)


def _statics() -> tuple[bytes, bytes]:
    blocks = {
        0: [(0x0010, 1, 1, 0, 0), (0x0010, 2, 1, 0, 0), (0x0011, 3, 1, 20, 0x21)],
        3: [(0x0010, 4, 4, 10, 0x21), (0x0010, 5, 4, 10, 0)],
    }
    index, data = bytearray(), bytearray()
    for block in range(BLOCKS * BLOCKS):
        records = blocks.get(block)
        if records is None:
            index += struct.pack("<III", 0xFFFFFFFF, 0, 0xFFFFFFFF)
            continue
        index += struct.pack("<III", len(data), len(records) * 7, 0)
        for record in records:
            data += struct.pack("<HBBbH", *record)
    return bytes(index), bytes(data)


def _tiledata() -> UOTileData:
    land = [UOLandTile(i, 0, 0, "") for i in range(0x20)]
    land[0x03] = UOLandTile(0x03, 0, 3, "grass")
    land[0x16] = UOLandTile(0x16, 0, 22, "sand")
    statics = [UOStaticTile(i, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "") for i in range(0x20)]
    wall_flags = 0x10 | 0x40  # wall | impassable
    statics[0x10] = UOStaticTile(0x10, wall_flags, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 20, "plaster wall")
    statics[0x11] = UOStaticTile(0x11, wall_flags, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 20, "plaster wall")
    return UOTileData(is_new_format=True, land=land, statics=statics)


def test_inventory_counts_ranks_and_rolls_up_by_name(tmp_path):
    index, data = _statics()
    facet_map = UOMap(_land(), index, data, 16, 16)
    inv = build_uo_map_inventory(tmp_path, 0, tiledata=_tiledata(), facet_map=facet_map)

    wall = inv.statics[0]
    assert (wall.tile_id, wall.placements, wall.z_min, wall.z_max, wall.z_common) == (0x10, 4, 0, 10, 0)
    assert wall.blocks == 2 and wall.hued == 1 and wall.hues == 1
    assert [r.tile_id for r in inv.land] == [0x03, 0x16]
    assert inv.land[1].placements == 16 and inv.land[0].placements == 256 - 16

    summary = write_uo_map_inventory(inv, tmp_path / "out", previews=False)
    assert summary["statics"] == {
        **summary["statics"],
        "placements": 5,
        "tile_ids": 2,
        "names": 1,
        "by_category": {"wall": 5},
    }
    assert summary["land"]["cells"] == 256
    rows = list(csv.DictReader(open(tmp_path / "out" / "statics.csv", encoding="utf-8")))
    assert [(r["tile_hex"], r["name"], r["placements"], r["cumulative_pct"]) for r in rows] == [
        ("0x0010", "plaster wall", "4", "80.0"),
        ("0x0011", "plaster wall", "1", "100.0"),
    ]
    names = list(csv.DictReader(open(tmp_path / "out" / "names.csv", encoding="utf-8")))
    assert names[0]["name"] == "plaster wall" and names[0]["ids"] == "0x0010 0x0011"
    assert json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))["facet"] == 0


def test_tile_category_prefers_specific_flags():
    assert tile_category(("wall", "door"), "wooden door") == "door"
    assert tile_category(("surface",), "marble floor") == "floor"
    assert tile_category(("wet", "impassable"), "water") == "water"
    assert tile_category((), "grasses") == "other"
