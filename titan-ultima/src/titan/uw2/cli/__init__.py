"""Ultima Underworld II CLI, registered as ``titan uw2``."""

from __future__ import annotations

__all__ = [
    "uw2_app",
    "cmd_map_3d_export",
    "cmd_map_3d_render",
    "cmd_map_extract",
    "cmd_map_grid",
    "cmd_map_render",
    "cmd_map_stack",
    "cmd_map_verify",
    "cmd_model_export",
    "cmd_model_render",
    "cmd_object_dump",
    "cmd_object_info",
    "cmd_palette_export",
    "cmd_shape_batch",
    "cmd_shape_export",
    "cmd_shape_info",
    "cmd_terrain_export",
    "cmd_texture_catalog",
    "cmd_texture_usage",
]

import typer

from titan._cli_aliases import alias_group
from titan.uw2.cli import graphics, maps, models, objects, textures
from titan.uw2.cli.graphics import (
    cmd_palette_export,
    cmd_shape_batch,
    cmd_shape_export,
    cmd_shape_info,
    cmd_terrain_export,
)
from titan.uw2.cli.maps import (
    cmd_map_3d_export,
    cmd_map_3d_render,
    cmd_map_extract,
    cmd_map_grid,
    cmd_map_render,
    cmd_map_stack,
    cmd_map_verify,
)
from titan.uw2.cli.models import cmd_model_export, cmd_model_render
from titan.uw2.cli.objects import cmd_object_dump, cmd_object_info
from titan.uw2.cli.textures import cmd_texture_catalog, cmd_texture_usage

uw2_app = typer.Typer(
    cls=alias_group(
        {
            "--gamedir": "--game-dir",
            "--output": "--output-dir",
            "--json": ("--format", "json"),
        }
    ),
    name="uw2",
    help="Ultima Underworld II — maps, palettes, shapes, and object metadata.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

uw2_app.command("model-render")(models.model_render_cmd)
uw2_app.command("model-export")(models.model_export_cmd)
uw2_app.command("map-extract")(maps.map_extract_cmd)
uw2_app.command("map-verify")(maps.map_verify_cmd)
uw2_app.command("map-3d-render")(maps.map_3d_render_cmd)
uw2_app.command("map-stack")(maps.map_stack_cmd)
uw2_app.command("map-3d-export")(maps.map_3d_export_cmd)
uw2_app.command("map-render")(maps.map_render_cmd)
uw2_app.command("map-grid")(maps.map_grid_cmd)
uw2_app.command("texture-catalog")(textures.texture_catalog_cmd)
uw2_app.command("texture-usage")(textures.texture_usage_cmd)
uw2_app.command("palette-export")(graphics.palette_export_cmd)
uw2_app.command("shape-info")(graphics.shape_info_cmd)
uw2_app.command("shape-export")(graphics.shape_export_cmd)
uw2_app.command("shape-batch")(graphics.shape_batch_cmd)
uw2_app.command("terrain-export")(graphics.terrain_export_cmd)
uw2_app.command("object-info")(objects.object_info_cmd)
uw2_app.command("object-dump")(objects.object_dump_cmd)
