"""
Ultima 9: Ascension — CLI sub-app.

Registered as ``titan u9 <command>`` in the root CLI.

Each command family lives in its own module of this package; this module
owns the Typer app and the ordered command table, which is also the order
``titan u9 --help`` lists them in.
"""

from __future__ import annotations

__all__ = ["u9_app"]

from titan.u9.cli_paths import ConfiguredU9App
from titan.u9.save_browser_ui import register_u9_save_browser

from titan.u9.cli import (
    archives,
    typenames,
    sound,
    palettes,
    models,
    textures,
    regions,
    zones,
    animations,
    scripts,
    npcs,
    text,
    saves,
    maps,
)

u9_app = ConfiguredU9App(
    name="u9",
    help="Ultima 9: Ascension — archive, palette, texture, sound, model, world, script, and navigation commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

# Command table. Order here is the order shown by ``titan u9 --help``.
register_u9_save_browser(u9_app)
u9_app.command("flx-list")(archives.flx_list_cmd)
u9_app.command("flx-extract")(archives.flx_extract_cmd)
u9_app.command("flx-extract-all")(archives.flx_extract_all_cmd)
u9_app.command("typename-dump")(typenames.typename_dump_cmd)
u9_app.command("typename-csv")(typenames.typename_csv_cmd)
u9_app.command("typename-import")(typenames.typename_import_cmd)
u9_app.command("types-csv")(typenames.types_csv_cmd)
u9_app.command("sound-category-list")(sound.sound_category_list_cmd)
u9_app.command("sound-category-csv")(sound.sound_category_csv_cmd)
u9_app.command("sound-environment-list")(sound.sound_environment_list_cmd)
u9_app.command("sound-environment-csv")(sound.sound_environment_csv_cmd)
u9_app.command("sound-template-csv")(sound.sound_template_csv_cmd)
u9_app.command("sound-association-csv")(sound.sound_association_csv_cmd)
u9_app.command("palette-info")(palettes.palette_info_cmd)
u9_app.command("palette-export")(palettes.palette_export_cmd)
u9_app.command("sound-list")(sound.sound_list_cmd)
u9_app.command("sound-extract-pcm")(sound.sound_extract_pcm_cmd)
u9_app.command("sound-extract")(sound.sound_extract_cmd)
u9_app.command("sound-report")(sound.sound_report_cmd)
u9_app.command("sound-import")(sound.sound_import_cmd)
u9_app.command("sound-import-batch")(sound.sound_import_batch_cmd)
u9_app.command("model-info")(models.model_info_cmd)
u9_app.command("model-material-report")(models.model_material_report_cmd)
u9_app.command("model-export")(models.model_export_cmd)
u9_app.command("model-export-all")(models.model_export_all_cmd)
u9_app.command("texture-info")(textures.texture_info_cmd)
u9_app.command("texture-frame-report")(textures.texture_frame_report_cmd)
u9_app.command("texture-export")(textures.texture_export_cmd)
u9_app.command("texture-export-all")(textures.texture_export_all_cmd)
u9_app.command("icon-list")(textures.icon_list_cmd)
u9_app.command("icon-export")(textures.icon_export_cmd)
u9_app.command("icon-export-all")(textures.icon_export_all_cmd)
u9_app.command("nonfixed-info")(regions.nonfixed_info_cmd)
u9_app.command("nonfixed-chunks")(regions.nonfixed_chunks_cmd)
u9_app.command("nonfixed-entities")(regions.nonfixed_entities_cmd)
u9_app.command("nonfixed-diff")(regions.nonfixed_diff_cmd)
u9_app.command("highway-info")(zones.highway_info_cmd)
u9_app.command("highway-points")(zones.highway_points_cmd)
u9_app.command("highway-routes")(zones.highway_routes_cmd)
u9_app.command("animation-list")(animations.animation_list_cmd)
u9_app.command("animation-show")(animations.animation_show_cmd)
u9_app.command("animation-library-plan")(animations.animation_library_plan_cmd)
u9_app.command("animation-library-export")(animations.animation_library_export_cmd)
u9_app.command("animation-model-report", deprecated=True)(
    animations.animation_model_report_cmd
)
u9_app.command("animation-pose-export")(animations.animation_pose_export_cmd)
u9_app.command("animation-bundle-export")(animations.animation_bundle_export_cmd)
u9_app.command("animation-set-export")(animations.animation_set_export_cmd)
u9_app.command("avatar-animation-library-export")(
    animations.avatar_animation_library_export_cmd
)
u9_app.command("dimension-info")(models.dimension_info_cmd)
u9_app.command("dimension-show")(models.dimension_show_cmd)
u9_app.command("dimension-csv")(models.dimension_csv_cmd)
u9_app.command("spaces-info")(zones.spaces_info_cmd)
u9_app.command("spaces-show")(zones.spaces_show_cmd)
u9_app.command("spaces-csv")(zones.spaces_csv_cmd)
u9_app.command("treedat-info")(zones.treedat_info_cmd)
u9_app.command("treedat-show")(zones.treedat_show_cmd)
u9_app.command("treedat-csv")(zones.treedat_csv_cmd)
u9_app.command("areas-info")(zones.areas_info_cmd)
u9_app.command("areas-show")(zones.areas_show_cmd)
u9_app.command("areas-csv")(zones.areas_csv_cmd)
u9_app.command("trigger-list")(scripts.trigger_list_cmd)
u9_app.command("trigger-show")(scripts.trigger_show_cmd)
u9_app.command("trigger-opcodes")(scripts.trigger_opcodes_cmd)
u9_app.command("activity-list")(scripts.activity_list_cmd)
u9_app.command("activity-show")(scripts.activity_show_cmd)
u9_app.command("activity-opcodes")(scripts.activity_opcodes_cmd)
u9_app.command("script-research-export")(scripts.script_research_export_cmd)
u9_app.command("npc-list")(npcs.npc_list_cmd)
u9_app.command("npc-show")(npcs.npc_show_cmd)
u9_app.command("npc-classes")(npcs.npc_classes_cmd)
u9_app.command("npc-diff")(npcs.npc_diff_cmd)
u9_app.command("npc-csv")(npcs.npc_csv_cmd)
u9_app.command("sdinfo-list")(textures.sdinfo_list_cmd)
u9_app.command("sdinfo-show")(textures.sdinfo_show_cmd)
u9_app.command("sdinfo-verify")(textures.sdinfo_verify_cmd)
u9_app.command("text-list")(text.text_list_cmd)
u9_app.command("text-blocks")(text.text_blocks_cmd)
u9_app.command("text-search")(text.text_search_cmd)
u9_app.command("text-export")(text.text_export_cmd)
u9_app.command("text-import")(text.text_import_cmd)
u9_app.command("text-keys-info")(text.text_keys_info_cmd)
u9_app.command("text-key-lookup")(text.text_key_lookup_cmd)
u9_app.command("text-keys-export")(text.text_keys_export_cmd)
u9_app.command("shade-info")(palettes.shade_info_cmd)
u9_app.command("shade-csv")(palettes.shade_csv_cmd)
u9_app.command("color-cube-info")(palettes.color_cube_info_cmd)
u9_app.command("color-cube-lookup")(palettes.color_cube_lookup_cmd)
u9_app.command("color-cube-csv")(palettes.color_cube_csv_cmd)
u9_app.command("save-check")(saves.save_check_cmd)
u9_app.command("fixed-info")(regions.fixed_info_cmd)
u9_app.command("fixed-chunks")(regions.fixed_chunks_cmd)
u9_app.command("fixed-objects")(regions.fixed_objects_cmd)
u9_app.command("fixed-types")(regions.fixed_types_cmd)
u9_app.command("terrain-info")(regions.terrain_info_cmd)
u9_app.command("terrain-tiles")(regions.terrain_tiles_cmd)
u9_app.command("terrain-chunk")(regions.terrain_chunk_cmd)
u9_app.command("terrain-textures")(regions.terrain_textures_cmd)
u9_app.command("terrain-heightmap")(regions.terrain_heightmap_cmd)
u9_app.command("terrain-export")(regions.terrain_export_cmd)
u9_app.command("map-atlas")(maps.map_atlas_cmd)
u9_app.command("map-render")(maps.map_render_cmd)
u9_app.command("map-export-glb")(maps.map_export_glb_cmd)
u9_app.command("map-render-3d")(maps.map_render_3d_cmd)
u9_app.command("books-list")(text.books_list_cmd)
u9_app.command("books-show")(text.books_show_cmd)
u9_app.command("books-search")(text.books_search_cmd)
u9_app.command("books-export")(text.books_export_cmd)
u9_app.command("flx-pack")(archives.flx_pack_cmd)
u9_app.command("flx-repack")(archives.flx_repack_cmd)
u9_app.command("texture-import")(textures.texture_import_cmd)
