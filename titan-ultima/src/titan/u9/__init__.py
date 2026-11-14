"""
Ultima 9 subpackage.

Modules for Ultima 9: Ascension file formats.

Import from the module that defines a name; this package does not re-export
them, so loading one U9 module does not load all of the others.

Common imports::

    from titan.u9.activity import U9Activities
    from titan.u9.animation import U9Animations
    from titan.u9.books import U9Books
    from titan.u9.fixed import U9Fixed
    from titan.u9.flx_archive import U9FlxArchive
    from titan.u9.flx_writer import build_flx
    from titan.u9.highway import U9Highway
    from titan.u9.gameplay_zones import U9Areas
    from titan.u9.npc import U9Npcs
    from titan.u9.sdinfo import U9SdInfo
    from titan.u9.space_tree import U9VolumeLookupCache
    from titan.u9.spaces import U9Spaces
    from titan.u9.text import U9TextArchive
    from titan.u9.text_keys import U9TextKeyTable
    from titan.u9.terrain import U9Terrain
    from titan.u9.triggers import U9Triggers
    from titan.u9.typename import U9TypeNames
    from titan.u9.sound import U9SoundRecord
    from titan.u9.adpcm import decode_stereo, decode_mono as decode_adpcm_mono
    from titan.u9.microtalk import decode_mono as decode_microtalk_mono
    from titan.u9.model import U9Model
    from titan.u9.texture import decode_frame
    from titan.u9.mesh_export import export_obj, export_stl
    from titan.u9.types_dat import U9TypesDat
    from titan.u9.model_naming import label_for_model
    from titan.u9.nonfixed import U9Nonfixed
    from titan.u9.object_placement import resolve_region_object_placements
    from titan.u9.palette import U9Palette
    from titan.u9.region_scene import U9RegionScene
    from titan.u9.map_render import render_region_map
    from titan.u9.preview import render_preview  # optional, needs `pip install pyvista`
    from titan.u9.icon import icon_entry_indices
"""

from __future__ import annotations

__all__: list[str] = []
