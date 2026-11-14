"""
Ultima 8: Pagan — CLI sub-app.

Registered as ``titan u8 <command>`` in the root CLI.

Each command family lives in its own module of this package; this module
owns the Typer app and the ordered command table, which is also the order
``titan u8 --help`` lists them in.
"""

from __future__ import annotations

__all__ = ["u8_app"]

import typer

from titan.u8.save_cli import register_u8_save_commands
from titan.u8.shape_browser_ui import register_u8_shape_browser
from titan.u8.npc_animation_cli import register_u8_npc_animation_report
from titan.u8.npc_browser_ui import register_u8_npc_browser
from titan.u8.save_browser_ui import register_u8_save_browser
from titan.u8.map_browser_ui import register_u8_map_browser
from titan.u8.container_browser_ui import register_u8_container_browser
from titan.u8.palette_browser_ui import register_u8_palette_browser
from titan.u8.world_search_ui import register_u8_world_search

from titan.u8.cli import palettes, shapes, audio, gamedata, saves, maps

u8_app = typer.Typer(
    name="u8",
    help="Ultima 8: Pagan — shape, map, music, sound, save, and data commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

# Command table. Order here is the order shown by ``titan u8 --help``.
register_u8_save_commands(u8_app)
register_u8_shape_browser(u8_app)
register_u8_npc_animation_report(u8_app)
register_u8_npc_browser(u8_app)
register_u8_save_browser(u8_app)
register_u8_map_browser(u8_app)
register_u8_container_browser(u8_app)
register_u8_palette_browser(u8_app)
register_u8_world_search(u8_app)
u8_app.command("palette-export")(palettes.palette_export_cmd)
u8_app.command("shape-export")(shapes.shape_export_cmd)
u8_app.command("shape-batch")(shapes.shape_batch_cmd)
u8_app.command("shape-import")(shapes.shape_import_cmd)
u8_app.command("shape-convert-u7")(shapes.shape_convert_u7_cmd)
u8_app.command("shape-convert-u7-all")(shapes.shape_convert_u7_all_cmd)
u8_app.command("music-export")(audio.music_export_cmd)
u8_app.command("sound-export-all")(audio.sound_export_all_cmd)
u8_app.command("sound-export")(audio.sound_export_cmd)
u8_app.command("sound-batch")(audio.sound_batch_cmd)
u8_app.command("credits-decrypt")(gamedata.credits_decrypt_cmd)
u8_app.command("xformpal-export")(palettes.xformpal_export_cmd)
u8_app.command("anim-dump")(gamedata.anim_dump_cmd)
u8_app.command("wpnovlay-dump")(gamedata.wpnovlay_dump_cmd)
u8_app.command("itemcach-dump")(gamedata.itemcach_dump_cmd)
u8_app.command("npcdata-dump")(gamedata.npcdata_dump_cmd)
u8_app.command("nonfixed-dump")(gamedata.map_items_dump_cmd)
u8_app.command("fixed-dump")(gamedata.map_items_dump_cmd)
u8_app.command("typeflag-dump")(gamedata.typeflag_dump_cmd)
u8_app.command("gumpinfo-dump")(gamedata.gumpinfo_dump_cmd)
u8_app.command("unkcoff-dump")(gamedata.unkcoff_dump_cmd)
u8_app.command("save-list")(saves.save_list_cmd)
u8_app.command("save-extract")(saves.save_extract_cmd)
u8_app.command("map-render")(maps.map_render_cmd)
u8_app.command("map-render-all")(maps.map_render_all_cmd)
u8_app.command("map-sample")(maps.map_sample_cmd)
u8_app.command("map-sample-all")(maps.map_sample_all_cmd)
