"""
Ultima 9 subpackage.

Modules for Ultima 9: Ascension file formats.

Canonical imports::

    from titan.u9.flx_archive import U9FlxArchive
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
    from titan.u9.palette import U9Palette
    from titan.u9.preview import render_preview  # optional, needs `pip install pyvista`
    from titan.u9.icon import icon_entry_indices
"""

from __future__ import annotations

from titan.u9.adpcm import AdpcmDecodeError, decode_mono as decode_adpcm_mono, decode_stereo
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError, U9FlxDirEntry
from titan.u9.icon import icon_entry_indices, used_texture_ids
from titan.u9.mesh_export import MeshExportError, export_obj, export_stl
from titan.u9.microtalk import MicroTalkDecodeError, decode_mono as decode_microtalk_mono
from titan.u9.model import (
    U9Limb,
    U9Material,
    U9Model,
    U9ModelError,
    U9SubmeshLod,
    U9Triangle,
    U9TriangleCorner,
)
from titan.u9.model_naming import label_for_model, names_for_model, slugify
from titan.u9.nonfixed import (
    U9Chunk,
    U9Entity,
    U9ExtraData,
    U9Nonfixed,
    U9NonfixedError,
    U9Page,
)
from titan.u9.palette import U9Palette, U9PaletteError
from titan.u9.preview import PreviewError, PreviewUnavailableError, render_preview
from titan.u9.sound import U9SoundRecord, U9SoundRecordError
from titan.u9.texture import U9TextureError, U9TextureFrame, decode_frame
from titan.u9.typename import U9TypeNameEntry, U9TypeNames
from titan.u9.types_dat import U9TypeRecord, U9TypesDat

__all__ = [
    "U9FlxArchive",
    "U9FlxArchiveError",
    "U9FlxDirEntry",
    "U9TypeNames",
    "U9TypeNameEntry",
    "U9SoundRecord",
    "U9SoundRecordError",
    "decode_stereo",
    "decode_adpcm_mono",
    "AdpcmDecodeError",
    "decode_microtalk_mono",
    "MicroTalkDecodeError",
    "U9Model",
    "U9ModelError",
    "U9Limb",
    "U9SubmeshLod",
    "U9Triangle",
    "U9TriangleCorner",
    "U9Material",
    "decode_frame",
    "U9TextureFrame",
    "U9TextureError",
    "export_obj",
    "export_stl",
    "MeshExportError",
    "U9TypesDat",
    "U9TypeRecord",
    "label_for_model",
    "names_for_model",
    "slugify",
    "U9Nonfixed",
    "U9NonfixedError",
    "U9Chunk",
    "U9Page",
    "U9Entity",
    "U9ExtraData",
    "U9Palette",
    "U9PaletteError",
    "render_preview",
    "PreviewError",
    "PreviewUnavailableError",
    "icon_entry_indices",
    "used_texture_ids",
]
