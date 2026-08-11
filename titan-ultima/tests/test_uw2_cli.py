"""Tests for native ``titan uw2`` CLI commands."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from titan.uw2.cli import (
    cmd_map_3d_export,
    cmd_map_3d_render,
    cmd_map_extract,
    cmd_map_render,
    cmd_model_export,
    cmd_model_render,
    cmd_object_info,
    cmd_shape_export,
)
from titan.uw2.object_data import ANIMATION_TABLE_OFFSET


class UW2CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "DATA"
        self.data.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_shape_export_resolves_config_style_game_directory(self) -> None:
        palette = bytearray(768)
        palette[3:6] = bytes((63, 0, 0))
        (self.data / "PALS.DAT").write_bytes(palette)
        record = bytes((0x04, 1, 1)) + struct.pack("<H", 1) + b"\x01"
        (self.data / "OBJECTS.GR").write_bytes(
            bytes((1, 1, 0)) + struct.pack("<I", 7) + record
        )
        output = self.root / "out"

        result = cmd_shape_export(
            SimpleNamespace(
                file="OBJECTS.GR",
                index=0,
                palette=None,
                allpals=None,
                palette_index=0,
                transparent_index=0,
                output=str(output),
                gamedir=str(self.root),
            )
        )

        self.assertEqual(result, 0)
        self.assertTrue((output / "objects_000.png").is_file())

    def test_object_info_includes_animation_record(self) -> None:
        common = bytearray(2 + 512 * 11)
        common_offset = 2 + 457 * 11
        common[common_offset + 9] = 0x3C
        (self.data / "COMOBJ.DAT").write_bytes(common)
        objects = bytearray(ANIMATION_TABLE_OFFSET + 16 * 4)
        animation_offset = ANIMATION_TABLE_OFFSET + (457 & 0x0F) * 4
        objects[animation_offset : animation_offset + 4] = bytes((33, 0, 5, 4))
        (self.data / "OBJECTS.DAT").write_bytes(objects)

        result = cmd_object_info(
            SimpleNamespace(
                item_id=457,
                comobj=None,
                objects=None,
                gamedir=str(self.root),
            )
        )

        self.assertEqual(result, 0)

    @patch("titan.uw2.cli.extract_maps")
    def test_map_extract_uses_install_data_directory(self, extract_mock) -> None:
        (self.data / "LEV.ARK").write_bytes(b"placeholder")
        extract_mock.return_value = [{"slot_index": 0}]
        output = self.root / "maps"

        result = cmd_map_extract(
            SimpleNamespace(
                gamedir=str(self.root),
                output=str(output),
                slots=[0],
                write_decoded_blocks=False,
            )
        )

        self.assertEqual(result, 0)
        extract_mock.assert_called_once_with(
            self.root,
            str(output),
            slots=[0],
            write_decoded_blocks=False,
        )

    @patch("titan.uw2.cli.render_maps_direct")
    @patch("titan.uw2.cli.export_render_assets")
    @patch("titan.uw2.cli.extract_maps")
    def test_map_render_reads_original_files_without_intermediates(
        self, extract_mock, assets_mock, direct_render_mock
    ) -> None:
        output = self.root / "renders"
        workdir = self.root / "work"
        direct_render_mock.return_value = [output / "level_000.png"]

        result = cmd_map_render(
            SimpleNamespace(
                gamedir=str(self.root),
                output=str(output),
                workdir=str(workdir),
                slots=[0],
                reuse_workdir=False,
                keep_intermediates=False,
                tile_size=64,
            )
        )

        self.assertEqual(result, 0)
        extract_mock.assert_not_called()
        assets_mock.assert_not_called()
        direct_render_mock.assert_called_once_with(
            self.root, output, slots=[0], tile_size=64
        )

    @patch("titan.uw2.cli.render_object_models")
    def test_model_render_accepts_hex_item_ids(self, render_mock) -> None:
        output = self.root / "models"
        render_mock.return_value = [output / "table.png"]

        result = cmd_model_render(
            SimpleNamespace(
                gamedir=str(self.root),
                output=str(output),
                items=["0x158", "348"],
                flags=0,
                size=512,
                views=["iso"],
            )
        )

        self.assertEqual(result, 0)
        render_mock.assert_called_once_with(
            self.root,
            str(output),
            item_ids=[0x158, 348],
            flags=0,
            size=512,
            views=["iso"],
        )

    @patch("titan.uw2.cli.export_object_models")
    def test_model_export_omits_item_filter_to_export_all(self, export_mock) -> None:
        output = self.root / "models"
        export_mock.return_value = [output / "table.obj"]

        result = cmd_model_export(
            SimpleNamespace(
                gamedir=str(self.root),
                output=str(output),
                items=None,
                flags=0,
            )
        )

        self.assertEqual(result, 0)
        export_mock.assert_called_once_with(
            self.root,
            str(output),
            item_ids=None,
            flags=0,
        )

    @patch("titan.uw2.cli.render_map_scene")
    def test_map_3d_render_parses_region_and_views(self, render_mock) -> None:
        output = self.root / "scene"
        render_mock.return_value = [output / "top.png"]
        result = cmd_map_3d_render(
            SimpleNamespace(
                gamedir=str(self.root),
                output=str(output),
                slot=0,
                region="17,46,22,52",
                views=["top"],
                size=512,
                include_ceilings=False,
                no_sprites=False,
                model_scale=2.0,
                sprite_scale=1.0,
                tick=0,
            )
        )
        self.assertEqual(result, 0)
        render_mock.assert_called_once_with(
            self.root,
            str(output),
            slot=0,
            region=(17, 46, 22, 52),
            views=["top"],
            size=512,
            include_ceilings=False,
            include_sprites=True,
            model_scale=2.0,
            sprite_scale=1.0,
            tick=0,
        )

    @patch("titan.uw2.cli.export_map_scene")
    def test_map_3d_export_preserves_sprite_option(self, export_mock) -> None:
        output = self.root / "scene"
        export_mock.return_value = output / "scene.glb"
        result = cmd_map_3d_export(
            SimpleNamespace(
                gamedir=str(self.root),
                output=str(output),
                slot=0,
                region=None,
                include_ceilings=True,
                no_sprites=True,
                model_scale=2.0,
                sprite_scale=1.0,
                tick=3,
            )
        )
        self.assertEqual(result, 0)
        export_mock.assert_called_once_with(
            self.root,
            str(output),
            slot=0,
            region=(0, 0, 63, 63),
            include_ceilings=True,
            include_sprites=False,
            model_scale=2.0,
            sprite_scale=1.0,
            tick=3,
        )


if __name__ == "__main__":
    unittest.main()
