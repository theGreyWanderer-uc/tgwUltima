"""Tests for UU2 texture descriptions and per-level texture usage.

STRINGS.PAK block 10 stores a wall description at the texture's own index and
the matching floor description at ``510 - texture_id``; TERRAIN.DAT supplies
the property word for the same ID. These tests pin that join and the per-role
usage aggregation without needing a real STRINGS.PAK.
"""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from titan.uw2.texture_catalog import (
    FLOOR_STRING_BASE,
    TEXTURE_ID_COUNT,
    TEXTURE_STRING_BLOCK,
    USAGE_ROLES,
    build_texture_catalog,
    catalog_by_texture_id,
    export_texture_usage,
    level_texture_usage,
)


class _FakeGameStrings:
    """Returns a marker naming the block and index it was asked for."""

    def __init__(self, values: dict[tuple[int, int], str] | None = None):
        self.values = values or {}
        self.requests: list[tuple[int, int]] = []

    def get(self, block_id: int, string_index: int, default: str = "") -> str:
        self.requests.append((block_id, string_index))
        return self.values.get((block_id, string_index), default)

    def summary(self) -> dict:
        return {"block_count": 1, "blocks": [{"block_id": TEXTURE_STRING_BLOCK}]}


def _terrain_dat_bytes(words: dict[int, int]) -> bytes:
    block = bytearray(TEXTURE_ID_COUNT * 2)
    for texture_id, value in words.items():
        struct.pack_into("<H", block, texture_id * 2, value)
    return bytes(block)


def _tile(x: int, y: int, floor: int, wall: int, ceiling: int) -> dict:
    return {
        "x": x,
        "y": y,
        "display_y": 63 - y,
        "type_name": "open",
        "texture_floor": floor,
        "texture_wall": wall,
        "texture_ceiling_runtime": ceiling,
        "texture_ceiling_ua": ceiling,
    }


class UW2TextureCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "DATA"
        self.data.mkdir()
        (self.data / "STRINGS.PAK").write_bytes(b"placeholder")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_wall_and_floor_descriptions_use_the_mirrored_string_indices(self) -> None:
        strings = _FakeGameStrings(
            {
                (TEXTURE_STRING_BLOCK, 40): "a sandstone wall&",
                (TEXTURE_STRING_BLOCK, FLOOR_STRING_BASE - 40): "a sandstone floor&",
            }
        )
        (self.data / "TERRAIN.DAT").write_bytes(_terrain_dat_bytes({40: 0x0010}))

        with patch(
            "titan.uw2.texture_catalog.GameStrings.from_file", return_value=strings
        ):
            catalog = build_texture_catalog(self.root)

        entry = catalog_by_texture_id(catalog)[40]
        self.assertEqual(entry["wall_string_index"], 40)
        self.assertEqual(entry["floor_string_index"], FLOOR_STRING_BASE - 40)
        self.assertEqual(entry["wall_description"], "Sandstone Wall")
        self.assertEqual(entry["floor_description"], "Sandstone Floor")
        self.assertEqual(entry["image"], "textures/t64_040.png")

    def test_covers_every_texture_id_and_joins_terrain_properties(self) -> None:
        (self.data / "TERRAIN.DAT").write_bytes(_terrain_dat_bytes({40: 0x0010}))

        with patch(
            "titan.uw2.texture_catalog.GameStrings.from_file",
            return_value=_FakeGameStrings(),
        ):
            catalog = build_texture_catalog(self.root)

        self.assertEqual(len(catalog["textures"]), TEXTURE_ID_COUNT)
        by_id = catalog_by_texture_id(catalog)
        self.assertEqual(by_id[40]["terrain"]["label"], "water")
        self.assertTrue(by_id[40]["terrain"]["is_water"])
        self.assertEqual(by_id[41]["terrain"]["label"], "normal")

    def test_missing_terrain_dat_leaves_entries_without_properties(self) -> None:
        with patch(
            "titan.uw2.texture_catalog.GameStrings.from_file",
            return_value=_FakeGameStrings(),
        ):
            catalog = build_texture_catalog(self.root)

        self.assertIsNone(catalog["terrain_dat"])
        self.assertIsNone(catalog_by_texture_id(catalog)[40]["terrain"])


class UW2TextureUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.level = {
            "slot_index": 3,
            "level_id_1based": 4,
            "world_name": "Britannia",
            "level_name": "Britannia - Sewer 2",
            "tiles": [
                _tile(0, 0, floor=10, wall=20, ceiling=30),
                _tile(1, 0, floor=10, wall=20, ceiling=30),
                _tile(2, 0, floor=11, wall=20, ceiling=30),
            ],
        }
        self.catalog_by_id = {
            10: {
                "texture_id": 10,
                "image": "textures/t64_010.png",
                "wall_description": "Brick Wall",
                "floor_description": "Brick Floor",
                "terrain": {"label": "normal", "terrain_hex": "0x0000"},
            }
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_groups_tiles_by_texture_and_role(self) -> None:
        usage = level_texture_usage(self.level, self.catalog_by_id)

        by_id = {entry["texture_id"]: entry for entry in usage["textures"]}
        self.assertEqual(sorted(by_id), [10, 11, 20, 30])
        self.assertEqual(by_id[10]["counts"]["floor"], 2)
        self.assertEqual(by_id[10]["counts"]["wall"], 0)
        self.assertEqual(by_id[20]["counts"]["wall"], 3)
        # Both ceiling interpretations are reported side by side.
        self.assertEqual(by_id[30]["counts"]["ceiling_runtime"], 3)
        self.assertEqual(by_id[30]["counts"]["ceiling_ua"], 3)
        self.assertEqual([tile["x"] for tile in by_id[10]["tiles"]["floor"]], [0, 1])

    def test_carries_catalog_descriptions_and_tolerates_missing_entries(self) -> None:
        usage = level_texture_usage(self.level, self.catalog_by_id)

        by_id = {entry["texture_id"]: entry for entry in usage["textures"]}
        self.assertEqual(by_id[10]["wall_description"], "Brick Wall")
        self.assertEqual(by_id[10]["terrain_label"], "normal")
        self.assertIsNone(by_id[20]["wall_description"])
        self.assertIsNone(by_id[20]["terrain_label"])

    def test_export_writes_one_file_per_level_plus_a_summary(self) -> None:
        catalog = {
            "source": "fake",
            "textures": list(self.catalog_by_id.values()),
        }

        written = export_texture_usage([self.level], catalog, self.root)

        self.assertEqual(
            [path.name for path in written],
            ["level_003_texture_usage.json", "texture_usage_summary.json"],
        )
        self.assertTrue(all(path.is_file() for path in written))

    def test_summary_totals_every_role(self) -> None:
        catalog = {"source": "fake", "textures": list(self.catalog_by_id.values())}
        export_texture_usage([self.level], catalog, self.root)

        summary = json.loads(
            (self.root / "texture_usage_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(summary["level_count"], 1)
        row = summary["levels"][0]
        self.assertEqual(row["slot_index"], 3)
        self.assertEqual(row["texture_count"], 4)
        for role in USAGE_ROLES:
            self.assertEqual(row["role_counts"][role], 3)


if __name__ == "__main__":
    unittest.main()
