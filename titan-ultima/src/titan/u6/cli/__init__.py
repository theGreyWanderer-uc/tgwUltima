"""
Ultima 6: The False Prophet — CLI sub-app.

Registered as ``titan u6 <command>`` in the root CLI.

Most commands accept ``-g/--game-dir`` (a directory containing the
standard, fixed U6 filenames: MASKTYPE.VGA, MAPTILES.VGA, OBJTILES.VGA,
U6PAL, ANIMDATA, MAP, CHUNKS) rather than per-file paths, since -- unlike
U7/U8 -- a real U6 install has no path variability to account for.
Falls back to ``[u6.game] base`` in ``titan.toml`` if ``--game-dir`` is
omitted.
"""

from __future__ import annotations

__all__ = [
    "u6_app",
    "cmd_actor_list",
    "cmd_book_dump",
    "cmd_converse_dump",
    "cmd_egg_list",
    "cmd_flags_compare",
    "cmd_flags_dump",
    "cmd_flags_set",
    "cmd_font_export",
    "cmd_gamestate_dump",
    "cmd_lib_extract",
    "cmd_lib_extract_all",
    "cmd_lib_list",
    "cmd_look_dump",
    "cmd_lzw_decompress",
    "cmd_map_audit_zorder",
    "cmd_map_render",
    "cmd_object_list",
    "cmd_palette_export",
    "cmd_schedule_dump",
    "cmd_tile_export",
    "cmd_tile_export_all",
    "cmd_tileflag_dump",
]

import typer

from titan._cli_aliases import alias_group
from titan.u6.cli import archives, graphics, maps, text, world
from titan.u6.cli.archives import (
    cmd_lib_extract,
    cmd_lib_extract_all,
    cmd_lib_list,
    cmd_lzw_decompress,
)
from titan.u6.cli.graphics import (
    cmd_font_export,
    cmd_palette_export,
    cmd_tile_export,
    cmd_tile_export_all,
    cmd_tileflag_dump,
)
from titan.u6.cli.maps import cmd_map_audit_zorder, cmd_map_render
from titan.u6.cli.text import cmd_book_dump, cmd_converse_dump, cmd_look_dump
from titan.u6.cli.world import (
    cmd_actor_list,
    cmd_egg_list,
    cmd_flags_compare,
    cmd_flags_dump,
    cmd_flags_set,
    cmd_gamestate_dump,
    cmd_object_list,
    cmd_schedule_dump,
)

u6_app = typer.Typer(
    cls=alias_group({"--gamedir": "--game-dir", "--output": "--output-dir"}),
    name="u6",
    help="Ultima 6: The False Prophet — tile, map, library, and data commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

u6_app.command("lzw-decompress")(archives.lzw_decompress_cmd)
u6_app.command("lib-list")(archives.lib_list_cmd)
u6_app.command("lib-extract")(archives.lib_extract_cmd)
u6_app.command("lib-extract-all")(archives.lib_extract_all_cmd)
u6_app.command("tileflag-dump")(graphics.tileflag_dump_cmd)
u6_app.command("palette-export")(graphics.palette_export_cmd)
u6_app.command("tile-export")(graphics.tile_export_cmd)
u6_app.command("tile-export-all")(graphics.tile_export_all_cmd)
u6_app.command("map-render")(maps.map_render_cmd)
u6_app.command("map-audit-zorder")(maps.map_audit_zorder_cmd)
u6_app.command("object-list")(world.object_list_cmd)
u6_app.command("egg-list")(world.egg_list_cmd)
u6_app.command("actor-list")(world.actor_list_cmd)
u6_app.command("gamestate-dump")(world.gamestate_dump_cmd)
u6_app.command("flags-dump")(world.flags_dump_cmd)
u6_app.command("flags-compare")(world.flags_compare_cmd)
u6_app.command("flags-set")(world.flags_set_cmd)
u6_app.command("converse-dump")(text.converse_dump_cmd)
u6_app.command("font-export")(graphics.font_export_cmd)
u6_app.command("look-dump")(text.look_dump_cmd)
u6_app.command("book-dump")(text.book_dump_cmd)
u6_app.command("schedule-dump")(world.schedule_dump_cmd)
