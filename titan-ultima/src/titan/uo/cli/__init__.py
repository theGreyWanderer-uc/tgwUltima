"""
Ultima Online Classic Client CLI sub-app.

Registered as ``titan uo <command>`` in the root CLI.

Each command family lives in its own module of this package; this module
owns the Typer app and the ordered command table, which is also the order
``titan uo --help`` lists them in.
"""

from __future__ import annotations

__all__ = ["uo_app"]

import typer

from titan.uo.cli import graphics, maps, housing, data, animations

uo_app = typer.Typer(
    name="uo",
    help="Ultima Online Classic Client commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

# Command table. Order here is the order shown by ``titan uo --help``.
uo_app.command("art-export")(graphics.art_export_cmd)
uo_app.command("gump-export")(graphics.gump_export_cmd)
uo_app.command("texture-export")(graphics.texture_export_cmd)
uo_app.command("light-export")(graphics.light_export_cmd)
uo_app.command("hue-export")(graphics.hue_export_cmd)
uo_app.command("radar-export")(maps.radar_export_cmd)
uo_app.command("map-export")(maps.map_export_cmd)
uo_app.command("map-render")(maps.map_render_cmd)
uo_app.command("map-tiles")(maps.map_tiles_cmd)
uo_app.command("map-inventory")(maps.map_inventory_cmd)
uo_app.command("house-footprints")(housing.house_footprints_cmd)
uo_app.command("house-capacity")(housing.house_capacity_cmd)
uo_app.command("tiledata-export")(data.tiledata_export_cmd)
uo_app.command("animdata-export")(data.animdata_export_cmd)
uo_app.command("artdef-export")(data.artdef_export_cmd)
uo_app.command("def-export")(data.def_export_cmd)
uo_app.command("localization-export")(data.localization_export_cmd)
uo_app.command("multi-export")(maps.multi_export_cmd)
uo_app.command("font-export")(graphics.font_export_cmd)
uo_app.command("sound-export")(data.sound_export_cmd)
uo_app.command("animation-export")(animations.animation_export_cmd)
uo_app.command("animation-resolution-export")(
    animations.animation_resolution_export_cmd
)
uo_app.command("animation-body-names-export")(
    animations.animation_body_names_export_cmd
)
