"""
Ultima 9 subpackage.

Modules for Ultima 9: Ascension file formats.

Canonical imports::

    from titan.u9.activity import U9Activities
    from titan.u9.animation import U9Animations
    from titan.u9.books import U9Books
    from titan.u9.fixed import U9Fixed
    from titan.u9.flx_archive import U9FlxArchive
    from titan.u9.flx_writer import build_flx
    from titan.u9.highway import U9Highway
    from titan.u9.npc import U9Npcs
    from titan.u9.sdinfo import U9SdInfo
    from titan.u9.text import U9TextArchive
    from titan.u9.terrain import U9Terrain
    from titan.u9.triggers import U9Triggers
    from titan.u9.typename import U9TypeNames
    from titan.u9.sound import U9SoundRecord
    from titan.u9.activity import (
    U9Activities,
    U9Activity,
    U9ActivityError,
    U9ActivityRecord,
    U9ActivityStep,
)
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

from titan.u9.adpcm import (
    AdpcmDecodeError,
    decode_mono as decode_adpcm_mono,
    decode_stereo,
)
from titan.u9.animation import (
    U9Animation,
    U9AnimationError,
    U9AnimationFrame,
    U9AnimationPart,
    U9Animations,
    U9AnimationSuffix,
)
from titan.u9.books import U9Book, U9Books, U9BooksError
from titan.u9.fixed import (
    U9Fixed,
    U9FixedChunk,
    U9FixedError,
    U9FixedObject,
    U9FixedPage,
)
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError, U9FlxDirEntry
from titan.u9.flx_writer import (
    U9FlxWriteError,
    build_flx,
    repack,
    repack_equivalent,
    write_flx,
)
from titan.u9.highway import U9Highway, U9HighwayError, U9HighwayPoint, U9HighwayRoute
from titan.u9.icon import icon_entry_indices, used_texture_ids
from titan.u9.mesh_export import (
    MeshExportError,
    U9ModelMeshTriangle,
    U9ModelMeshVertex,
    export_obj,
    export_stl,
    flatten_model_triangles,
    model_limb_world_matrices,
)
from titan.u9.microtalk import (
    MicroTalkDecodeError,
    decode_mono as decode_microtalk_mono,
)
from titan.u9.model import (
    U9IndexedFace,
    U9Limb,
    U9Material,
    U9Model,
    U9ModelError,
    U9SubmeshLod,
    U9Triangle,
    U9TriangleCorner,
)
from titan.u9.model_naming import label_for_model, names_for_model, slugify
from titan.u9.map_atlas import (
    U9MapAtlasDiagnostics,
    U9MapAtlasError,
    U9MapAtlasRegionRecord,
    U9MapAtlasResult,
    U9RegionFiles,
    discover_region_files,
    render_map_atlas,
)
from titan.u9.map_render import (
    TOPDOWN_RESOLUTION_PRESETS,
    U9_WATER_TEXTURE_ID,
    U9MapRenderDiagnostics,
    U9MapRenderError,
    U9MapRenderResult,
    U9MapTextureSource,
    U9ObjectTextureProvider,
    U9TerrainTextureProvider,
    render_region_map,
    resolve_topdown_pixels_per_cell,
)
from titan.u9.nonfixed import (
    U9Chunk,
    U9Entity,
    U9ExtraData,
    U9Nonfixed,
    U9NonfixedError,
    U9Page,
)
from titan.u9.object_placement import (
    U9ModelBounds,
    U9ModelBoundsLookup,
    U9ModelBoundsProvider,
    U9ModelLookup,
    U9ModelProvider,
    U9ObjectFootprintFilter,
    U9ObjectPlacementDiagnostics,
    U9ObjectPlacementError,
    U9ObjectPlacementResolution,
    U9ObjectPlacementResult,
    U9SappearModelBounds,
    U9SappearModelSource,
    object_scale_from_extra_data,
    project_model_bounds_footprint,
    resolve_region_object_placements,
)
from titan.u9.object_raster import (
    U9ObjectRasterDiagnostics,
    U9ObjectRasterError,
    rasterize_object_meshes,
)
from titan.u9.npc import U9Npc, U9NpcError, U9Npcs
from titan.u9.palette import PALETTE_TRANSPARENCY_INDEX, U9Palette, U9PaletteError
from titan.u9.region_scene import (
    FIXED_CHUNK_TERRAIN_POINTS,
    REGION_CHUNK_TERRAIN_POINTS,
    TERRAIN_HEIGHT_WORLD_Z,
    TERRAIN_POINT_WORLD_XY,
    U9FixedPlacement,
    U9NonfixedPlacement,
    U9RegionScene,
    U9RegionSceneDiagnostics,
    U9RegionSceneError,
    U9TerrainCell,
    U9WorldPosition,
)
from titan.u9.region_glb import (
    DEFAULT_U9_GLB_SCALE,
    U9_WATER_SURFACE_EPSILON,
    U9CellRegion,
    U9GlbExportDiagnostics,
    U9GlbExportError,
    U9GlbObjectRecord,
    U9RegionGlbResult,
    export_region_glb,
)
from titan.u9.region_vtk import (
    ANTI_ALIASING_MODES,
    MAX_VTK_RENDER_EDGE,
    SOUTH_HIGH_CAMERA_OFFSET,
    TEXTURE_FILTERS,
    VTK_RESOLUTION_PRESETS,
    U9OrthographicCamera,
    U9VtkRenderDiagnostics,
    U9VtkRenderError,
    U9VtkRenderResult,
    U9VtkUnavailableError,
    fit_south_high_orthographic_camera,
    render_region_glb,
    resolve_vtk_render_size,
)
from titan.u9.preview import PreviewError, PreviewUnavailableError, render_preview
from titan.u9.sdinfo import U9SdInfo, U9SdInfoError, U9SdInfoRecord
from titan.u9.script_research import export_script_research_bundle
from titan.u9.sound import U9SoundRecord, U9SoundRecordError
from titan.u9.terrain import (
    U9Terrain,
    U9TerrainChunk,
    U9TerrainError,
    U9TerrainPoint,
)
from titan.u9.text import U9TextArchive, U9TextBlock, U9TextEntry, U9TextError
from titan.u9.texture import (
    U9TextureError,
    U9TextureFrame,
    U9TextureFrameInfo,
    U9TextureSet,
    decode_frame,
    mip_dimensions,
    parse_texture_set,
)
from titan.u9.texture_writer import (
    U9TextureWriteError,
    encode_alpha8,
    encode_alpha_intensity_44,
    encode_bc1,
    frame_encoding,
    replace_frame,
)
from titan.u9.triggers import U9Trigger, U9TriggerRecord, U9Triggers, U9TriggersError
from titan.u9.typename import U9TypeNameEntry, U9TypeNames
from titan.u9.types_dat import U9TypeRecord, U9TypesDat, U9TypesDatError

__all__ = [
    "U9FlxArchive",
    "U9FlxWriteError",
    "build_flx",
    "repack",
    "repack_equivalent",
    "write_flx",
    "U9FlxArchiveError",
    "U9FlxDirEntry",
    "U9TypeNames",
    "U9TypeNameEntry",
    "U9SoundRecord",
    "U9SoundRecordError",
    "decode_stereo",
    "decode_adpcm_mono",
    "AdpcmDecodeError",
    "U9Animation",
    "U9AnimationError",
    "U9AnimationFrame",
    "U9AnimationPart",
    "U9Animations",
    "U9AnimationSuffix",
    "decode_microtalk_mono",
    "MicroTalkDecodeError",
    "U9Model",
    "U9ModelError",
    "U9Limb",
    "U9IndexedFace",
    "U9SubmeshLod",
    "U9Triangle",
    "U9TriangleCorner",
    "U9Material",
    "decode_frame",
    "PALETTE_TRANSPARENCY_INDEX",
    "mip_dimensions",
    "parse_texture_set",
    "U9TextureFrame",
    "U9TextureFrameInfo",
    "U9TextureSet",
    "U9TextureError",
    "U9TextureWriteError",
    "encode_alpha8",
    "encode_alpha_intensity_44",
    "encode_bc1",
    "frame_encoding",
    "replace_frame",
    "export_obj",
    "export_stl",
    "MeshExportError",
    "U9ModelMeshTriangle",
    "U9ModelMeshVertex",
    "flatten_model_triangles",
    "model_limb_world_matrices",
    "U9TypesDat",
    "U9TypesDatError",
    "U9TypeRecord",
    "label_for_model",
    "names_for_model",
    "slugify",
    "U9Book",
    "U9Books",
    "U9BooksError",
    "U9Fixed",
    "U9FixedChunk",
    "U9FixedError",
    "U9FixedObject",
    "U9FixedPage",
    "U9Highway",
    "U9Activities",
    "U9Activity",
    "U9ActivityError",
    "U9ActivityRecord",
    "U9ActivityStep",
    "export_script_research_bundle",
    "U9Triggers",
    "U9TriggersError",
    "U9Trigger",
    "U9TriggerRecord",
    "U9HighwayError",
    "U9HighwayPoint",
    "U9HighwayRoute",
    "U9Terrain",
    "U9TerrainChunk",
    "U9TerrainError",
    "U9TerrainPoint",
    "U9TextArchive",
    "U9TextBlock",
    "U9TextEntry",
    "U9TextError",
    "U9SdInfo",
    "U9SdInfoError",
    "U9SdInfoRecord",
    "U9Npcs",
    "U9Npc",
    "U9NpcError",
    "U9Nonfixed",
    "U9NonfixedError",
    "U9Chunk",
    "U9Page",
    "U9Entity",
    "U9ExtraData",
    "U9ModelBounds",
    "U9ModelBoundsLookup",
    "U9ModelBoundsProvider",
    "U9ModelLookup",
    "U9ModelProvider",
    "U9ObjectFootprintFilter",
    "U9ObjectPlacementDiagnostics",
    "U9ObjectPlacementError",
    "U9ObjectPlacementResolution",
    "U9ObjectPlacementResult",
    "U9SappearModelBounds",
    "U9SappearModelSource",
    "object_scale_from_extra_data",
    "project_model_bounds_footprint",
    "resolve_region_object_placements",
    "U9Palette",
    "U9PaletteError",
    "U9RegionScene",
    "U9RegionSceneError",
    "U9RegionSceneDiagnostics",
    "U9TerrainCell",
    "U9FixedPlacement",
    "U9NonfixedPlacement",
    "U9WorldPosition",
    "TERRAIN_POINT_WORLD_XY",
    "TERRAIN_HEIGHT_WORLD_Z",
    "FIXED_CHUNK_TERRAIN_POINTS",
    "REGION_CHUNK_TERRAIN_POINTS",
    "DEFAULT_U9_GLB_SCALE",
    "U9_WATER_SURFACE_EPSILON",
    "U9CellRegion",
    "U9GlbExportDiagnostics",
    "U9GlbExportError",
    "U9GlbObjectRecord",
    "U9RegionGlbResult",
    "export_region_glb",
    "ANTI_ALIASING_MODES",
    "MAX_VTK_RENDER_EDGE",
    "SOUTH_HIGH_CAMERA_OFFSET",
    "TEXTURE_FILTERS",
    "U9OrthographicCamera",
    "U9VtkRenderDiagnostics",
    "U9VtkRenderError",
    "U9VtkRenderResult",
    "U9VtkUnavailableError",
    "fit_south_high_orthographic_camera",
    "render_region_glb",
    "resolve_vtk_render_size",
    "VTK_RESOLUTION_PRESETS",
    "TOPDOWN_RESOLUTION_PRESETS",
    "resolve_topdown_pixels_per_cell",
    "U9MapTextureSource",
    "U9_WATER_TEXTURE_ID",
    "U9TerrainTextureProvider",
    "U9ObjectTextureProvider",
    "U9MapRenderError",
    "U9MapRenderDiagnostics",
    "U9MapRenderResult",
    "render_region_map",
    "U9ObjectRasterDiagnostics",
    "U9ObjectRasterError",
    "rasterize_object_meshes",
    "U9MapAtlasDiagnostics",
    "U9MapAtlasError",
    "U9MapAtlasRegionRecord",
    "U9MapAtlasResult",
    "U9RegionFiles",
    "discover_region_files",
    "render_map_atlas",
    "render_preview",
    "PreviewError",
    "PreviewUnavailableError",
    "icon_entry_indices",
    "used_texture_ids",
]
