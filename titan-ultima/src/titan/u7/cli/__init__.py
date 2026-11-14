"""
Ultima 7 — CLI sub-app.

Registered as ``titan u7 <command>`` in the root CLI.
Commands for Ultima 7: The Black Gate and Serpent Isle.

Each command family lives in its own module of this package; this module
owns the Typer app and the ordered command table, which is also the order
``titan u7 --help`` lists them in.
"""

from __future__ import annotations

__all__ = ["u7_app"]

import typer

from titan.u7.ireg_rewrite_cli import ireg_rewrite_cmd
from titan.u7.save_repack_cli import save_repack_cmd
from titan.u7.ireg_tree_cli import ireg_tree_cmd, ireg_tree_edit_cmd
from titan.u7.actor_rewrite_cli import actor_headers_cmd, actor_rewrite_cmd

from titan.u7.cli import (
    archives,
    shapes,
    palettes,
    audio,
    fonts,
    maps,
    world,
    gamedata,
    usecode,
    npcs,
    saves,
)

u7_app = typer.Typer(
    name="u7",
    help="Ultima 7 — The Black Gate / Serpent Isle commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

# Command table. Order here is the order shown by ``titan u7 --help``.
u7_app.command("ireg-rewrite")(ireg_rewrite_cmd)
u7_app.command("save-repack")(save_repack_cmd)
u7_app.command("ireg-tree")(ireg_tree_cmd)
u7_app.command("ireg-tree-edit")(ireg_tree_edit_cmd)
u7_app.command("actor-headers")(actor_headers_cmd)
u7_app.command("actor-rewrite")(actor_rewrite_cmd)
u7_app.command("ireg-dump")(world.ireg_dump_cmd)
u7_app.command("flex-create")(archives.u7_flex_create_cmd)
u7_app.command("flex-add-shape")(archives.u7_flex_add_shape_cmd)
u7_app.command("shape-create")(shapes.shape_create_cmd)
u7_app.command("shape-browse")(shapes.shape_browse_cmd)
u7_app.command("palette-browse")(palettes.palette_browse_cmd)
u7_app.command("palette-export")(palettes.palette_export_cmd)
u7_app.command("palette-info")(palettes.palette_info_cmd)
u7_app.command("shape-export")(shapes.shape_export_cmd)
u7_app.command("shape-import")(shapes.shape_import_cmd)
u7_app.command("shape-frame-report")(shapes.shape_frame_report_cmd)
u7_app.command("shape-animate")(shapes.shape_animate_cmd)
u7_app.command("shape-batch")(shapes.shape_batch_cmd)
u7_app.command("shape-cycle-scan")(shapes.shape_cycle_scan_cmd)
u7_app.command("music-export")(audio.music_export_cmd)
u7_app.command("voc-export")(audio.voc_export_cmd)
u7_app.command("speech-export")(audio.speech_export_cmd)
u7_app.command("map-create")(maps.map_create_cmd)
u7_app.command("map-export-json")(maps.map_export_json_cmd)
u7_app.command("map-render-json")(maps.map_render_json_cmd)
u7_app.command("map-render")(maps.map_render_cmd)
u7_app.command("map-sample")(maps.map_sample_cmd)
u7_app.command("typeflag-dump")(gamedata.typeflag_dump_cmd)
u7_app.command("wihh-dump")(gamedata.wihh_dump_cmd)
u7_app.command("static-data-dump")(gamedata.static_data_dump_cmd)
u7_app.command("usecode-scan-intrinsic")(usecode.usecode_scan_intrinsic_cmd)
u7_app.command("usecode-disasm")(usecode.usecode_disasm_cmd)
u7_app.command("monster-browse")(npcs.monster_browse_cmd)
u7_app.command("npc-browse")(npcs.npc_browse_cmd)
u7_app.command("save-browse")(saves.save_browse_cmd)
u7_app.command("npc-dump")(npcs.npc_dump_cmd)
u7_app.command("schedule-dump")(npcs.schedule_dump_cmd)
u7_app.command("gamedat-info")(saves.gamedat_info_cmd)
u7_app.command("monster-defs")(npcs.monster_defs_cmd)
u7_app.command("monster-dump")(npcs.monster_dump_cmd)
u7_app.command("monster-equipment")(npcs.monster_equipment_cmd)
u7_app.command("monster-report")(npcs.monster_report_cmd)
u7_app.command("npc-equipment")(npcs.npc_equipment_cmd)
u7_app.command("save-list")(saves.save_list_cmd)
u7_app.command("save-extract")(saves.save_extract_cmd)
u7_app.command("gflag-dump")(saves.gflag_dump_cmd)
u7_app.command("save-info")(saves.save_info_cmd)
u7_app.command("save-npcs")(saves.save_npcs_cmd)
u7_app.command("save-schedules")(saves.save_schedules_cmd)
u7_app.command("font-create")(fonts.font_create_cmd)
u7_app.command("map-inventory")(maps.map_inventory_cmd)
u7_app.command("world-query")(world.world_query_cmd)
u7_app.command("container-browse")(world.container_browse_cmd)
u7_app.command("egg-query")(world.egg_query_cmd)
