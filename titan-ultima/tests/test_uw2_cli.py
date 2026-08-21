"""Tests for native ``titan uw2`` CLI commands."""

from __future__ import annotations

import json
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
    cmd_map_verify,
    cmd_model_export,
    cmd_model_render,
    cmd_object_info,
    cmd_shape_export,
    cmd_texture_catalog,
    cmd_texture_usage,
)
from titan.uw2.map3d import DEFAULT_ZOOM
from titan.uw2.object_data import ANIMATION_TABLE_OFFSET
from titan.uw2.scene3d import DEFAULT_Z_SCALE


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
                slot=[0],
                region="17,46,22,52",
                views=["top"],
                size=512,
                width=None,
                height=None,
                include_ceilings=False,
                no_sprites=False,
                model_scale=2.0,
                sprite_scale=1.0,
                tick=0,
                ceiling_source="runtime",
                z_scale=DEFAULT_Z_SCALE,
                zoom=DEFAULT_ZOOM,
                fit_margin=1.0,
                supersample=1,
                downsample_filter="lanczos",
                texture_filter="linear",
                texture_scale=1,
                backend="auto",
                name_files=False,
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
            width=None,
            height=None,
            include_ceilings=False,
            include_sprites=True,
            model_scale=2.0,
            sprite_scale=1.0,
            tick=0,
            ceiling_source="runtime",
            z_scale=DEFAULT_Z_SCALE,
            zoom=DEFAULT_ZOOM,
            fit_margin=1.0,
            supersample=1,
            downsample_filter="lanczos",
            texture_filter="linear",
            texture_scale=1,
            backend="auto",
            name_files=False,
        )

    @patch("titan.uw2.cli.render_map_scene")
    def test_map_3d_render_repeats_for_every_requested_slot(self, render_mock) -> None:
        output = self.root / "scene"
        render_mock.return_value = [output / "top.png"]

        result = cmd_map_3d_render(
            SimpleNamespace(
                gamedir=str(self.root),
                output=str(output),
                slot=[0, 24],
                region=None,
                views=["top"],
                size=512,
                width=None,
                height=None,
                include_ceilings=False,
                no_sprites=False,
                model_scale=1.0,
                sprite_scale=1.0,
                tick=0,
                ceiling_source="ua",
                z_scale=DEFAULT_Z_SCALE,
                zoom=DEFAULT_ZOOM,
                fit_margin=1.0,
                supersample=1,
                downsample_filter="lanczos",
                texture_filter="nearest",
                texture_scale=4,
                backend="auto",
                name_files=True,
            )
        )

        self.assertEqual(result, 0)
        self.assertEqual(render_mock.call_count, 2)
        self.assertEqual(
            [call.kwargs["slot"] for call in render_mock.call_args_list], [0, 24]
        )
        self.assertEqual(render_mock.call_args.kwargs["ceiling_source"], "ua")
        self.assertEqual(render_mock.call_args.kwargs["texture_filter"], "nearest")

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
                ceiling_source="runtime",
                z_scale=DEFAULT_Z_SCALE,
                name_files=False,
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
            ceiling_source="runtime",
            z_scale=DEFAULT_Z_SCALE,
            name_files=False,
        )

    @patch("titan.uw2.cli.verify_maps")
    def test_map_verify_reports_success_and_writes_optional_report(
        self, verify_mock
    ) -> None:
        (self.data / "LEV.ARK").write_bytes(b"placeholder")
        report = self.root / "verify.json"
        verify_mock.return_value = {
            "lev_ark": str(self.data / "LEV.ARK"),
            "header_prefix_hex": "400100000000",
            "block_count": 320,
            "expected_block_count": 320,
            "available_blocks": 90,
            "populated_level_slots": [0, 1],
            "level_markers": {"0x7577": 2},
            "errors": [],
            "ok": True,
        }

        result = cmd_map_verify(
            SimpleNamespace(
                gamedir=str(self.root),
                json_output=False,
                output=str(report),
            )
        )

        self.assertEqual(result, 0)
        verify_mock.assert_called_once_with(self.root)
        self.assertTrue(json.loads(report.read_text(encoding="utf-8"))["ok"])

    @patch("titan.uw2.cli.verify_maps")
    def test_map_verify_fails_when_the_report_lists_errors(self, verify_mock) -> None:
        (self.data / "LEV.ARK").write_bytes(b"placeholder")
        verify_mock.return_value = {
            "lev_ark": str(self.data / "LEV.ARK"),
            "header_prefix_hex": "00",
            "block_count": 12,
            "expected_block_count": 320,
            "available_blocks": 0,
            "populated_level_slots": [],
            "level_markers": {},
            "errors": ["expected 320 blocks, found 12"],
            "ok": False,
        }

        result = cmd_map_verify(
            SimpleNamespace(gamedir=str(self.root), json_output=True, output=None)
        )

        self.assertEqual(result, 1)

    def test_map_verify_requires_the_map_archive(self) -> None:
        result = cmd_map_verify(
            SimpleNamespace(gamedir=str(self.root), json_output=False, output=None)
        )

        self.assertEqual(result, 1)

    @patch("titan.uw2.cli.export_texture_catalog")
    def test_texture_catalog_resolves_the_install_data_directory(
        self, catalog_mock
    ) -> None:
        (self.data / "STRINGS.PAK").write_bytes(b"placeholder")
        output = self.root / "catalog"
        catalog_mock.return_value = output / "texture_catalog.json"

        result = cmd_texture_catalog(
            SimpleNamespace(gamedir=str(self.root), output=str(output))
        )

        self.assertEqual(result, 0)
        catalog_mock.assert_called_once_with(self.root, str(output))

    def test_texture_catalog_requires_the_string_archive(self) -> None:
        result = cmd_texture_catalog(
            SimpleNamespace(gamedir=str(self.root), output=str(self.root / "catalog"))
        )

        self.assertEqual(result, 1)

    @patch("titan.uw2.cli.export_texture_usage")
    @patch("titan.uw2.cli.load_levels")
    @patch("titan.uw2.cli.build_texture_catalog")
    def test_texture_usage_defaults_to_every_map_slot(
        self, catalog_mock, levels_mock, usage_mock
    ) -> None:
        (self.data / "STRINGS.PAK").write_bytes(b"placeholder")
        (self.data / "LEV.ARK").write_bytes(b"placeholder")
        output = self.root / "usage"
        catalog_mock.return_value = {"textures": []}
        levels_mock.return_value = [{"slot_index": 0}]
        usage_mock.return_value = [output / "texture_usage_summary.json"]

        result = cmd_texture_usage(
            SimpleNamespace(
                gamedir=str(self.root),
                output=str(output),
                slots=None,
                write_catalog=False,
            )
        )

        self.assertEqual(result, 0)
        self.assertEqual(levels_mock.call_args.args[0], self.root)
        self.assertEqual(list(levels_mock.call_args.args[1]), list(range(80)))
        usage_mock.assert_called_once_with(
            [{"slot_index": 0}], {"textures": []}, str(output)
        )

    @patch("titan.uw2.cli.export_texture_usage")
    @patch("titan.uw2.cli.load_levels")
    @patch("titan.uw2.cli.build_texture_catalog")
    def test_texture_usage_fails_when_no_requested_slot_is_populated(
        self, catalog_mock, levels_mock, usage_mock
    ) -> None:
        (self.data / "STRINGS.PAK").write_bytes(b"placeholder")
        (self.data / "LEV.ARK").write_bytes(b"placeholder")
        catalog_mock.return_value = {"textures": []}
        levels_mock.return_value = []

        result = cmd_texture_usage(
            SimpleNamespace(
                gamedir=str(self.root),
                output=str(self.root / "usage"),
                slots=[5],
                write_catalog=False,
            )
        )

        self.assertEqual(result, 1)
        usage_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
