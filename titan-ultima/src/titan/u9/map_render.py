"""Textured bird's-eye rendering for one Ultima IX terrain region."""

from __future__ import annotations

__all__ = [
    "MAX_MAP_PIXELS_PER_CELL",
    "TOPDOWN_RESOLUTION_PRESETS",
    "U9_WATER_TEXTURE_ID",
    "U9MapRenderDiagnostics",
    "U9MapRenderError",
    "U9MapRenderResult",
    "U9MapTextureSource",
    "U9ObjectTextureProvider",
    "U9TerrainTextureProvider",
    "render_region_map",
    "resolve_topdown_pixels_per_cell",
]

import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

import numpy as np
from PIL import Image, ImageDraw

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.object_placement import (
    U9ModelBoundsProvider,
    U9ModelProvider,
    U9ObjectFootprintFilter,
    U9ObjectPlacementError,
    U9ObjectPlacementResolution,
    U9ObjectPlacementResult,
    resolve_region_object_placements,
)
from titan.u9.palette import U9Palette, U9PaletteError
from titan.u9.region_scene import TERRAIN_POINT_WORLD_XY, U9RegionScene
from titan.u9.sdinfo import U9SdInfo, U9SdInfoError
from titan.u9.terrain import CHUNK_POINTS
from titan.u9.texture import U9TextureError, decode_frame
from titan.u9.types_dat import U9TypesDat

_TEXTURE_KEY_COUNT = 1024 * 32 * 4
MAX_MAP_PIXELS_PER_CELL = 32
TOPDOWN_RESOLUTION_PRESETS = {
    "full": 28,
    "75": 21,
    "50": 14,
    "25": 7,
}
"""Named 2D scales; percentages are relative to the 28-pixel baseline."""
# Texture set used by U9's separate map-wide water surface.
U9_WATER_TEXTURE_ID = 49
_SDINFO_NAMES = {
    "bitmapsh.flx": "sdInfo.flx",
    "bitmap16.flx": "sdInfo16.flx",
    "bitmapc.flx": "sdInfoC.flx",
}


class U9MapRenderError(Exception):
    """Raised when a U9 region map cannot be rendered faithfully."""


def resolve_topdown_pixels_per_cell(
    resolution: str = "full", pixels_per_cell: int | None = None
) -> int:
    """Resolve a named 2D output scale, allowing an explicit detail override."""
    if pixels_per_cell is not None:
        if not 1 <= pixels_per_cell <= MAX_MAP_PIXELS_PER_CELL:
            raise U9MapRenderError(
                f"pixels_per_cell must be from 1 to {MAX_MAP_PIXELS_PER_CELL}"
            )
        return pixels_per_cell
    try:
        return TOPDOWN_RESOLUTION_PRESETS[resolution]
    except KeyError as error:
        choices = ", ".join(TOPDOWN_RESOLUTION_PRESETS)
        raise U9MapRenderError(
            f"top-down resolution must be one of {choices}, got {resolution!r}"
        ) from error


class U9TerrainTextureProvider(Protocol):
    """Provide complete oriented texture tiles for terrain-map rendering."""

    def tile_image(
        self,
        texture_id: int,
        frame: int,
        quarter_turns: int,
        pixels_per_cell: int,
    ) -> Image.Image:
        """Return one RGBA image sized to one rendered terrain cell."""
        ...


class U9ObjectTextureProvider(Protocol):
    """Provide complete decoded texture frames for model materials."""

    def frame_image(self, texture_id: int, frame: int) -> Image.Image:
        """Return one RGBA-compatible model texture frame."""
        ...


@dataclass(frozen=True)
class U9MapRenderDiagnostics:
    """Machine-readable coverage and alignment results for a rendered map."""

    terrain_name: str
    terrain_cells: int
    hole_cells: int
    texture_keys: int
    missing_texture_keys: tuple[str, ...]
    missing_texture_cells: int
    water_enabled: bool
    water_level: int
    wave_amplitude: float
    water_texture_id: int
    water_frame: int
    water_visible_cells: int
    water_visible_pixels: int
    water_texture_missing: bool
    fixed_objects: int
    fixed_objects_in_bounds: int
    fixed_objects_out_of_bounds: int
    fixed_chunk_position_mismatches: int
    nonfixed_indexed_entities: int
    nonfixed_unlinked_entities: int
    nonfixed_allocated_entities: int
    nonfixed_entities_in_bounds: int
    nonfixed_entities_out_of_bounds: int
    nonfixed_chunk_position_mismatches: int
    nonfixed_incomplete_chunks: int
    nonfixed_markers_drawn: int
    object_meshes_enabled: bool
    object_mesh_lod: int
    object_mesh_placements_selected: int
    object_mesh_placements_drawn: int
    object_mesh_models_drawn: int
    object_mesh_triangles_considered: int
    object_mesh_triangles_drawn: int
    object_mesh_pixels_drawn: int
    missing_object_texture_keys: tuple[str, ...]
    object_footprints_enabled: bool
    object_footprints_drawn: int
    object_footprints_resolved_total: int
    object_footprints_filtered_out: int
    fixed_footprints_drawn: int
    nonfixed_indexed_footprints_drawn: int
    nonfixed_unlinked_footprints_drawn: int
    object_footprint_source_filter: str
    object_footprint_type_filter: tuple[int, ...]
    object_footprint_model_filter: tuple[int, ...]
    object_footprint_style: str
    object_footprint_legend_enabled: bool
    fixed_footprints_resolved: int
    fixed_footprints_without_model: int
    fixed_footprints_unresolved: int
    nonfixed_footprints_resolved: int
    nonfixed_footprints_unresolved: int
    object_model_ids_requested: tuple[int, ...]
    object_model_ids_resolved: tuple[int, ...]
    object_model_ids_drawn: tuple[int, ...]
    missing_object_model_ids: tuple[int, ...]
    malformed_object_model_ids: tuple[int, ...]
    image_width: int
    image_height: int
    pixels_per_cell: int
    flip_y: bool

    def to_dict(self) -> dict[str, object]:
        """Return JSON-ready rendering diagnostics."""
        return asdict(self)


@dataclass(frozen=True)
class U9MapRenderResult:
    """Rendered RGBA image plus the evidence needed to audit it."""

    image: Image.Image
    diagnostics: U9MapRenderDiagnostics


def _find_case_insensitive(directory: Path, filename: str) -> Path | None:
    if not directory.is_dir():
        return None
    wanted = filename.casefold()
    return next(
        (path for path in directory.iterdir() if path.name.casefold() == wanted),
        None,
    )


class U9MapTextureSource:
    """Decode terrain textures with their matching palette and sdInfo selector."""

    def __init__(
        self,
        archive: U9FlxArchive,
        *,
        palette: U9Palette | None,
        selectors: dict[int, int],
        archive_path: Path,
        palette_path: Path | None,
        sdinfo_path: Path | None,
    ) -> None:
        self.archive = archive
        self.palette = palette
        self.selectors = selectors
        self.archive_path = archive_path
        self.palette_path = palette_path
        self.sdinfo_path = sdinfo_path
        self._frame_cache: dict[tuple[int, int], Image.Image] = {}
        self._tile_cache: dict[tuple[int, int, int, int], Image.Image] = {}

    @classmethod
    def from_file(
        cls,
        archive_path: str | os.PathLike[str],
        *,
        palette_path: str | os.PathLike[str] | None = None,
        sdinfo_path: str | os.PathLike[str] | None = None,
    ) -> U9MapTextureSource:
        """Open a bitmap tier and auto-discover its adjacent support files."""
        archive_file = Path(archive_path)
        if not archive_file.is_file():
            raise U9MapRenderError(f"texture archive not found: {archive_file}")
        try:
            archive = U9FlxArchive.from_file(archive_file)
        except (OSError, U9FlxArchiveError) as error:
            raise U9MapRenderError(
                f"could not read texture archive {archive_file}: {error}"
            ) from error

        palette_file = Path(palette_path) if palette_path is not None else None
        if palette_file is None:
            palette_file = _find_case_insensitive(archive_file.parent, "ankh.pal")
        palette = None
        if palette_file is not None:
            try:
                palette = U9Palette.from_file(palette_file)
            except (OSError, U9PaletteError) as error:
                raise U9MapRenderError(
                    f"could not read palette {palette_file}: {error}"
                ) from error

        sdinfo_file = Path(sdinfo_path) if sdinfo_path is not None else None
        if sdinfo_file is None:
            partner = _SDINFO_NAMES.get(archive_file.name.casefold())
            if partner is not None:
                sdinfo_file = _find_case_insensitive(archive_file.parent, partner)
        selectors: dict[int, int] = {}
        if sdinfo_file is not None:
            try:
                sdinfo = U9SdInfo.from_file(sdinfo_file)
                selectors = {
                    record.index: record.format_selector for record in sdinfo.records()
                }
            except (OSError, U9SdInfoError) as error:
                raise U9MapRenderError(
                    f"could not read texture metadata {sdinfo_file}: {error}"
                ) from error

        return cls(
            archive,
            palette=palette,
            selectors=selectors,
            archive_path=archive_file,
            palette_path=palette_file,
            sdinfo_path=sdinfo_file,
        )

    def frame_image(self, texture_id: int, frame: int) -> Image.Image:
        """Decode one full-resolution texture frame for 2D or 3D rendering."""
        key = (texture_id, frame)
        cached = self._frame_cache.get(key)
        if cached is not None:
            return cached
        try:
            blob = self.archive.read_entry(texture_id)
            if not blob:
                raise U9MapRenderError(
                    f"texture {texture_id} is an unused archive slot"
                )
            surface = decode_frame(
                blob,
                frame,
                palette=self.palette,
                selector=self.selectors.get(texture_id),
            )
        except (U9FlxArchiveError, U9TextureError) as error:
            raise U9MapRenderError(
                f"texture {texture_id} frame {frame} could not be decoded: {error}"
            ) from error
        image = Image.frombytes(
            "RGBA", (surface.width, surface.height), surface.pixels_rgba
        )
        self._frame_cache[key] = image
        return image

    def tile_image(
        self,
        texture_id: int,
        frame: int,
        quarter_turns: int,
        pixels_per_cell: int,
    ) -> Image.Image:
        """Decode, orient, and downsample one complete terrain-cell texture."""
        key = (texture_id, frame, quarter_turns & 3, pixels_per_cell)
        cached = self._tile_cache.get(key)
        if cached is not None:
            return cached
        image = self.frame_image(texture_id, frame)
        transforms = (
            None,
            Image.Transpose.ROTATE_90,
            Image.Transpose.ROTATE_180,
            Image.Transpose.ROTATE_270,
        )
        transform = transforms[quarter_turns & 3]
        if transform is not None:
            image = image.transpose(transform)
        image = image.resize((pixels_per_cell, pixels_per_cell), Image.Resampling.BOX)
        self._tile_cache[key] = image
        return image


def _terrain_word_grid(scene: U9RegionScene) -> np.ndarray:
    """Expand the terrain's chunk references into one uint32 cell grid."""
    terrain = scene.terrain
    words = np.empty((terrain.height, terrain.width), dtype=np.uint32)
    chunk_cache: dict[int, np.ndarray] = {}
    for tile_y in range(terrain.tile_height):
        for tile_x in range(terrain.tile_width):
            chunk_index = terrain.tile(tile_x, tile_y)
            chunk_words = chunk_cache.get(chunk_index)
            if chunk_words is None:
                chunk_words = np.asarray(
                    terrain.chunk(chunk_index).values, dtype=np.uint32
                ).reshape((CHUNK_POINTS, CHUNK_POINTS))
                chunk_cache[chunk_index] = chunk_words
            y = tile_y * CHUNK_POINTS
            x = tile_x * CHUNK_POINTS
            words[y : y + CHUNK_POINTS, x : x + CHUNK_POINTS] = chunk_words
    return words


def _missing_texture_tile(pixels_per_cell: int) -> Image.Image:
    """Return an explicit magenta diagnostic tile, never a guessed texture."""
    y, x = np.indices((pixels_per_cell, pixels_per_cell))
    bright = ((x + y) & 1) == 0
    pixels = np.empty((pixels_per_cell, pixels_per_cell, 4), dtype=np.uint8)
    pixels[bright] = (255, 0, 255, 255)
    pixels[~bright] = (32, 0, 32, 255)
    return Image.fromarray(pixels)


def _apply_hillshade(
    pixels: np.ndarray,
    heights: np.ndarray,
    pixels_per_cell: int,
    strength: float,
) -> None:
    """Apply world-scale Lambert-style relief while preserving flat colours."""
    gradient_y, gradient_x = np.gradient(
        heights.astype(np.float32),
        float(TERRAIN_POINT_WORLD_XY),
        float(TERRAIN_POINT_WORLD_XY),
    )
    normal_x = -gradient_x
    normal_y = -gradient_y
    normal_z = np.ones_like(normal_x)
    length = np.sqrt(normal_x * normal_x + normal_y * normal_y + normal_z)

    altitude = math.radians(45.0)
    azimuth = math.radians(315.0)
    light_x = math.cos(altitude) * math.sin(azimuth)
    light_y = -math.cos(altitude) * math.cos(azimuth)
    light_z = math.sin(altitude)
    dot = (normal_x * light_x + normal_y * light_y + normal_z * light_z) / length
    factor = 1.0 + max(0.0, min(1.0, strength)) * (dot - light_z)
    factor = np.clip(factor, 0.35, 1.65)
    if pixels_per_cell > 1:
        factor = np.repeat(
            np.repeat(factor, pixels_per_cell, axis=0),
            pixels_per_cell,
            axis=1,
        )
    rgb = pixels[:, :, :3].astype(np.float32) * factor[:, :, None]
    pixels[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)


def _terrain_surface_height(
    north_west: np.ndarray,
    north_east: np.ndarray,
    south_west: np.ndarray,
    south_east: np.ndarray,
    split: np.ndarray,
    u: float,
    v: float,
) -> np.ndarray:
    """Interpolate raw terrain Z on the packed cell's selected triangle."""
    north_west_to_south_east = np.where(
        v <= u,
        north_west + u * (north_east - north_west) + v * (south_east - north_east),
        north_west + u * (south_east - south_west) + v * (south_west - north_west),
    )
    north_east_to_south_west = np.where(
        u + v <= 1.0,
        north_west + u * (north_east - north_west) + v * (south_west - north_west),
        south_east
        + (1.0 - u) * (south_west - south_east)
        + (1.0 - v) * (north_east - south_east),
    )
    return np.where(split, north_west_to_south_east, north_east_to_south_west)


def _apply_global_water_surface(
    pixels: np.ndarray,
    source_words: np.ndarray,
    water_tile: np.ndarray,
    *,
    water_level: int,
    pixels_per_cell: int,
    flip_y: bool,
) -> tuple[int, int]:
    """Depth-test the map-wide water plane against terrain triangles."""
    point_heights = ((source_words & 0xFFF) * 4).astype(np.float32)
    north_west = point_heights
    north_east = np.roll(point_heights, -1, axis=1)
    south_west = np.roll(point_heights, -1, axis=0)
    south_east = np.roll(south_west, -1, axis=1)
    split = ((source_words >> 15) & 1).astype(bool)
    holes = ((source_words >> 12) & 1).astype(bool)

    if flip_y:
        north_west = north_west[::-1]
        north_east = north_east[::-1]
        south_west = south_west[::-1]
        south_east = south_east[::-1]
        split = split[::-1]
        holes = holes[::-1]

    visible_cells = np.zeros(holes.shape, dtype=bool)
    visible_pixels = 0
    for pixel_y in range(pixels_per_cell):
        display_v = (pixel_y + 0.5) / pixels_per_cell
        v = 1.0 - display_v if flip_y else display_v
        for pixel_x in range(pixels_per_cell):
            u = (pixel_x + 0.5) / pixels_per_cell
            terrain_height = _terrain_surface_height(
                north_west,
                north_east,
                south_west,
                south_east,
                split,
                u,
                v,
            )
            visible = holes | (float(water_level) >= terrain_height)
            target = pixels[pixel_y::pixels_per_cell, pixel_x::pixels_per_cell]
            target[visible] = water_tile[pixel_y, pixel_x]
            visible_cells |= visible
            visible_pixels += int(np.count_nonzero(visible))
    return int(np.count_nonzero(visible_cells)), visible_pixels


def _surface_depth_map(
    source_words: np.ndarray,
    *,
    water_enabled: bool,
    water_level: int,
    pixels_per_cell: int,
    flip_y: bool,
) -> np.ndarray:
    """Build the terrain/water top surface used to occlude object triangles."""
    point_heights = ((source_words & 0xFFF) * 4).astype(np.float32)
    north_west = point_heights
    north_east = np.roll(point_heights, -1, axis=1)
    south_west = np.roll(point_heights, -1, axis=0)
    south_east = np.roll(south_west, -1, axis=1)
    split = ((source_words >> 15) & 1).astype(bool)
    holes = ((source_words >> 12) & 1).astype(bool)
    if flip_y:
        north_west = north_west[::-1]
        north_east = north_east[::-1]
        south_west = south_west[::-1]
        south_east = south_east[::-1]
        split = split[::-1]
        holes = holes[::-1]

    height, width = source_words.shape
    depth = np.empty(
        (height * pixels_per_cell, width * pixels_per_cell), dtype=np.float32
    )
    for pixel_y in range(pixels_per_cell):
        display_v = (pixel_y + 0.5) / pixels_per_cell
        v = 1.0 - display_v if flip_y else display_v
        for pixel_x in range(pixels_per_cell):
            u = (pixel_x + 0.5) / pixels_per_cell
            terrain_depth = _terrain_surface_height(
                north_west,
                north_east,
                south_west,
                south_east,
                split,
                u,
                v,
            )
            if water_enabled:
                terrain_depth = np.where(
                    holes | (float(water_level) >= terrain_depth),
                    float(water_level),
                    terrain_depth,
                )
            else:
                terrain_depth = np.where(holes, -np.inf, terrain_depth)
            depth[pixel_y::pixels_per_cell, pixel_x::pixels_per_cell] = terrain_depth
    return depth


def _draw_fixed_markers(
    image: Image.Image,
    scene: U9RegionScene,
    *,
    pixels_per_cell: int,
    flip_y: bool,
    radius: int,
) -> None:
    """Draw fixed-object anchor points using the same raw coordinate transform."""
    draw = ImageDraw.Draw(image, "RGBA")
    marker_radius = max(1, radius)
    for placement in scene.fixed_placements():
        px = placement.terrain_x * pixels_per_cell
        if flip_y:
            py = (scene.terrain.height - placement.terrain_y) * pixels_per_cell
        else:
            py = placement.terrain_y * pixels_per_cell
        box = (
            round(px - marker_radius),
            round(py - marker_radius),
            round(px + marker_radius),
            round(py + marker_radius),
        )
        draw.ellipse(box, fill=(255, 72, 32, 176), outline=(24, 0, 0, 224))


def _draw_nonfixed_markers(
    image: Image.Image,
    scene: U9RegionScene,
    *,
    pixels_per_cell: int,
    flip_y: bool,
    radius: int,
    include_unlinked: bool,
) -> int:
    """Draw indexed authored positions in cyan and optional unlinked ones in gold."""
    draw = ImageDraw.Draw(image, "RGBA")
    marker_radius = max(1, radius)
    placements = scene.nonfixed_placements(include_unlinked=include_unlinked)
    for placement in placements:
        px = placement.terrain_x * pixels_per_cell
        if flip_y:
            py = (scene.terrain.height - placement.terrain_y) * pixels_per_cell
        else:
            py = placement.terrain_y * pixels_per_cell
        box = (
            round(px - marker_radius),
            round(py - marker_radius),
            round(px + marker_radius),
            round(py + marker_radius),
        )
        if placement.is_spatially_indexed:
            fill = (24, 224, 255, 176)
            outline = (0, 32, 48, 224)
        else:
            fill = (255, 196, 32, 176)
            outline = (56, 32, 0, 224)
        draw.ellipse(box, fill=fill, outline=outline)
    return len(placements)


def _footprint_image_points(
    footprint_xy: tuple[tuple[float, float], ...],
    scene: U9RegionScene,
    *,
    pixels_per_cell: int,
    flip_y: bool,
) -> list[tuple[float, float]]:
    """Convert a native raw-world X/Y footprint to output-image coordinates."""
    points = []
    for world_x, world_y in footprint_xy:
        pixel_x = world_x / TERRAIN_POINT_WORLD_XY * pixels_per_cell
        terrain_y = world_y / TERRAIN_POINT_WORLD_XY
        pixel_y = (
            (scene.terrain.height - terrain_y) * pixels_per_cell
            if flip_y
            else terrain_y * pixels_per_cell
        )
        points.append((pixel_x, pixel_y))
    return points


def _draw_object_footprints(
    image: Image.Image,
    scene: U9RegionScene,
    placements: tuple[U9ObjectPlacementResolution, ...],
    *,
    pixels_per_cell: int,
    flip_y: bool,
    style: Literal["outline", "fill"],
) -> int:
    """Draw transformed model bounding-box hulls beneath object anchor markers."""
    draw = ImageDraw.Draw(image, "RGBA")
    drawn = 0
    for placement in placements:
        points = _footprint_image_points(
            placement.footprint_xy,
            scene,
            pixels_per_cell=pixels_per_cell,
            flip_y=flip_y,
        )
        if placement.source_kind == "fixed":
            fill = (255, 72, 32, 56)
            outline = (112, 16, 0, 208)
        elif placement.is_spatially_indexed:
            fill = (24, 224, 255, 72)
            outline = (0, 72, 96, 224)
        else:
            fill = (255, 196, 32, 72)
            outline = (96, 56, 0, 224)

        if len(points) >= 3:
            draw.polygon(
                points,
                fill=fill if style == "fill" else None,
                outline=outline,
            )
        elif len(points) == 2:
            draw.line(points, fill=outline, width=1)
        elif len(points) == 1:
            x, y = points[0]
            draw.point((round(x), round(y)), fill=outline)
        else:
            continue
        drawn += 1
    return drawn


def _format_legend_ids(values: tuple[int, ...]) -> str:
    """Keep an ID-filter summary readable inside the map legend."""
    if not values:
        return "all"
    shown = ",".join(str(value) for value in values[:6])
    if len(values) <= 6:
        return shown
    return f"{shown} (+{len(values) - 6})"


def _draw_object_footprint_legend(
    image: Image.Image,
    placements: tuple[U9ObjectPlacementResolution, ...],
    *,
    resolved_total: int,
    footprint_filter: U9ObjectFootprintFilter,
    style: Literal["outline", "fill"],
) -> None:
    """Embed the footprint key, active filters, and exact display counts."""
    fixed_count = sum(item.source_kind == "fixed" for item in placements)
    indexed_count = sum(
        item.source_kind == "nonfixed" and item.is_spatially_indexed
        for item in placements
    )
    unlinked_count = sum(
        item.source_kind == "nonfixed" and not item.is_spatially_indexed
        for item in placements
    )
    filtered_count = resolved_total - len(placements)
    type_ids = tuple(sorted(footprint_filter.type_ids))
    model_ids = tuple(sorted(footprint_filter.model_ids))
    rows = (
        ("U9 model footprints", (255, 255, 255, 255)),
        (
            f"Shown {len(placements)} / {resolved_total}; filtered {filtered_count}",
            (230, 230, 230, 255),
        ),
        (f"Fixed {fixed_count}", (255, 96, 56, 255)),
        (f"Nonfixed indexed {indexed_count}", (24, 224, 255, 255)),
        (f"Nonfixed unlinked {unlinked_count}", (255, 196, 32, 255)),
        (
            f"Source {footprint_filter.source}; style {style}",
            (210, 210, 210, 255),
        ),
        (f"Types {_format_legend_ids(type_ids)}", (210, 210, 210, 255)),
        (f"Models {_format_legend_ids(model_ids)}", (210, 210, 210, 255)),
    )
    draw = ImageDraw.Draw(image, "RGBA")
    padding = 5
    line_height = 12
    widths = [draw.textbbox((0, 0), text)[2] for text, _color in rows]
    panel_width = max(widths) + padding * 2
    panel_height = line_height * len(rows) + padding * 2
    draw.rectangle(
        (2, 2, panel_width + 2, panel_height + 2),
        fill=(0, 0, 0, 190),
        outline=(255, 255, 255, 160),
    )
    for row, (text, color) in enumerate(rows):
        draw.text((2 + padding, 2 + padding + row * line_height), text, fill=color)


def render_region_map(
    scene: U9RegionScene,
    textures: U9TerrainTextureProvider,
    *,
    pixels_per_cell: int = 1,
    hillshade: bool = True,
    hillshade_strength: float = 0.55,
    water: bool = True,
    water_frame: int = 0,
    fixed_markers: bool = True,
    fixed_marker_radius: int = 1,
    nonfixed_markers: bool = True,
    nonfixed_marker_radius: int = 1,
    include_unlinked_nonfixed: bool = False,
    object_meshes: bool = False,
    object_mesh_models: U9ModelProvider | None = None,
    object_textures: U9ObjectTextureProvider | None = None,
    object_lod: int = 0,
    object_footprints: bool = False,
    object_models: U9ModelBoundsProvider | None = None,
    object_types: U9TypesDat | None = None,
    object_footprint_source: Literal["all", "fixed", "nonfixed"] = "all",
    object_type_ids: tuple[int, ...] = (),
    object_model_ids: tuple[int, ...] = (),
    object_footprint_style: Literal["outline", "fill"] = "outline",
    object_legend: bool = True,
    flip_y: bool = True,
) -> U9MapRenderResult:
    """Render one complete U9 region as a textured bird's-eye RGBA image."""
    if not 1 <= pixels_per_cell <= MAX_MAP_PIXELS_PER_CELL:
        raise U9MapRenderError(
            f"pixels_per_cell must be from 1 to {MAX_MAP_PIXELS_PER_CELL}"
        )
    if not 0.0 <= hillshade_strength <= 1.0:
        raise U9MapRenderError("hillshade_strength must be from 0.0 to 1.0")
    if water_frame < 0:
        raise U9MapRenderError("water_frame must be zero or greater")
    if object_lod < 0:
        raise U9MapRenderError("object_lod cannot be negative")
    if object_meshes and object_mesh_models is None:
        raise U9MapRenderError(
            "object meshes require a full sappear.flx model provider"
        )
    if object_meshes and object_textures is None:
        raise U9MapRenderError("object meshes require a model texture provider")
    if object_footprints and object_models is None:
        raise U9MapRenderError(
            "object_footprints requires a sappear.flx model-bounds provider"
        )
    if object_footprint_style not in {"outline", "fill"}:
        raise U9MapRenderError("object_footprint_style must be outline or fill")
    try:
        footprint_filter = U9ObjectFootprintFilter(
            source=object_footprint_source,
            type_ids=frozenset(object_type_ids),
            model_ids=frozenset(object_model_ids),
        )
    except U9ObjectPlacementError as error:
        raise U9MapRenderError(str(error)) from error

    source_words = _terrain_word_grid(scene)
    heights = ((source_words & 0xFFF) * 4).astype(np.float32)
    holes = ((source_words >> 12) & 1).astype(bool)
    rotations = ((source_words >> 13) & 3).astype(np.uint32)
    frames = ((source_words >> 16) & 0x1F).astype(np.uint32)
    texture_ids = (source_words >> 22).astype(np.uint32)
    keys = ((texture_ids << 7) | (frames << 2) | rotations).astype(np.uint32)

    if flip_y:
        keys = keys[::-1]
        holes = holes[::-1]
        heights = heights[::-1]

    unique_keys, cell_counts = np.unique(keys[~holes], return_counts=True)
    tile_lut = np.zeros(
        (_TEXTURE_KEY_COUNT, pixels_per_cell, pixels_per_cell, 4), dtype=np.uint8
    )
    missing_keys: list[str] = []
    missing_cells = 0
    diagnostic_tile = np.asarray(_missing_texture_tile(pixels_per_cell))
    for raw_key, count in zip(unique_keys.tolist(), cell_counts.tolist()):
        rotation = raw_key & 3
        frame = (raw_key >> 2) & 0x1F
        texture_id = raw_key >> 7
        try:
            tile = textures.tile_image(texture_id, frame, rotation, pixels_per_cell)
            tile_lut[raw_key] = np.asarray(tile, dtype=np.uint8)
        except U9MapRenderError:
            tile_lut[raw_key] = diagnostic_tile
            missing_keys.append(f"{texture_id}:{frame}:{rotation}")
            missing_cells += count

    height, width = keys.shape
    pixels = np.empty(
        (height * pixels_per_cell, width * pixels_per_cell, 4), dtype=np.uint8
    )
    for pixel_y in range(pixels_per_cell):
        for pixel_x in range(pixels_per_cell):
            pixels[pixel_y::pixels_per_cell, pixel_x::pixels_per_cell] = tile_lut[
                keys, pixel_y, pixel_x
            ]

    expanded_holes = holes
    if pixels_per_cell > 1:
        expanded_holes = np.repeat(
            np.repeat(holes, pixels_per_cell, axis=0),
            pixels_per_cell,
            axis=1,
        )
    pixels[expanded_holes] = (0, 0, 0, 0)
    if hillshade:
        _apply_hillshade(pixels, heights, pixels_per_cell, hillshade_strength)

    water_visible_cells = 0
    water_visible_pixels = 0
    water_texture_missing = False
    if water:
        try:
            water_image = textures.tile_image(
                U9_WATER_TEXTURE_ID, water_frame, 0, pixels_per_cell
            )
            water_tile = np.asarray(water_image, dtype=np.uint8)
        except U9MapRenderError:
            water_tile = diagnostic_tile
            water_texture_missing = True
        water_visible_cells, water_visible_pixels = _apply_global_water_surface(
            pixels,
            source_words,
            water_tile,
            water_level=scene.terrain.water_level,
            pixels_per_cell=pixels_per_cell,
            flip_y=flip_y,
        )

    object_resolutions: U9ObjectPlacementResult | None = None
    selected_footprints: tuple[U9ObjectPlacementResolution, ...] = ()
    if object_footprints or object_meshes:
        resolution_models = object_mesh_models or object_models
        if resolution_models is None:
            raise U9MapRenderError("object rendering requires a sappear.flx provider")
        object_resolutions = resolve_region_object_placements(
            scene,
            resolution_models,
            types=object_types,
            include_unlinked_nonfixed=include_unlinked_nonfixed,
        )
        selected_footprints = footprint_filter.select(object_resolutions)

    object_mesh_placements_drawn = 0
    object_mesh_models_drawn = 0
    object_mesh_triangles_considered = 0
    object_mesh_triangles_drawn = 0
    object_mesh_pixels_drawn = 0
    missing_object_texture_keys: tuple[str, ...] = ()
    if object_meshes:
        if object_mesh_models is None or object_textures is None:
            raise U9MapRenderError("object meshes require model and texture providers")
        from titan.u9.object_raster import U9ObjectRasterError, rasterize_object_meshes

        surface_depth = _surface_depth_map(
            source_words,
            water_enabled=water,
            water_level=scene.terrain.water_level,
            pixels_per_cell=pixels_per_cell,
            flip_y=flip_y,
        )
        try:
            raster = rasterize_object_meshes(
                pixels,
                surface_depth,
                scene,
                object_mesh_models,
                object_textures,
                selected_footprints,
                pixels_per_cell=pixels_per_cell,
                lod=object_lod,
                flip_y=flip_y,
            )
        except U9ObjectRasterError as error:
            raise U9MapRenderError(str(error)) from error
        object_mesh_placements_drawn = raster.placements_drawn
        object_mesh_models_drawn = raster.models_drawn
        object_mesh_triangles_considered = raster.triangles_considered
        object_mesh_triangles_drawn = raster.triangles_drawn
        object_mesh_pixels_drawn = raster.pixels_drawn
        missing_object_texture_keys = raster.missing_texture_keys

    image = Image.fromarray(pixels)
    object_footprints_drawn = 0
    if object_footprints:
        object_footprints_drawn = _draw_object_footprints(
            image,
            scene,
            selected_footprints,
            pixels_per_cell=pixels_per_cell,
            flip_y=flip_y,
            style=object_footprint_style,
        )
    if fixed_markers and scene.fixed is not None:
        _draw_fixed_markers(
            image,
            scene,
            pixels_per_cell=pixels_per_cell,
            flip_y=flip_y,
            radius=fixed_marker_radius,
        )
    nonfixed_markers_drawn = 0
    if nonfixed_markers and scene.nonfixed is not None:
        nonfixed_markers_drawn = _draw_nonfixed_markers(
            image,
            scene,
            pixels_per_cell=pixels_per_cell,
            flip_y=flip_y,
            radius=nonfixed_marker_radius,
            include_unlinked=include_unlinked_nonfixed,
        )
    if object_footprints and object_legend:
        resolved_total = (
            len(object_resolutions.footprints) if object_resolutions is not None else 0
        )
        _draw_object_footprint_legend(
            image,
            selected_footprints,
            resolved_total=resolved_total,
            footprint_filter=footprint_filter,
            style=object_footprint_style,
        )

    alignment = scene.diagnostics()
    object_diagnostics = (
        object_resolutions.diagnostics if object_resolutions is not None else None
    )
    diagnostics = U9MapRenderDiagnostics(
        terrain_name=scene.terrain.name,
        terrain_cells=scene.terrain.width * scene.terrain.height,
        hole_cells=int(np.count_nonzero(holes)),
        texture_keys=len(unique_keys),
        missing_texture_keys=tuple(missing_keys),
        missing_texture_cells=missing_cells,
        water_enabled=water,
        water_level=scene.terrain.water_level,
        wave_amplitude=scene.terrain.wave_amplitude,
        water_texture_id=U9_WATER_TEXTURE_ID,
        water_frame=water_frame,
        water_visible_cells=water_visible_cells,
        water_visible_pixels=water_visible_pixels,
        water_texture_missing=water_texture_missing,
        fixed_objects=alignment.fixed_objects,
        fixed_objects_in_bounds=alignment.fixed_objects_in_bounds,
        fixed_objects_out_of_bounds=alignment.fixed_objects_out_of_bounds,
        fixed_chunk_position_mismatches=alignment.fixed_chunk_position_mismatches,
        nonfixed_indexed_entities=alignment.nonfixed_indexed_entities,
        nonfixed_unlinked_entities=alignment.nonfixed_unlinked_entities,
        nonfixed_allocated_entities=alignment.nonfixed_allocated_entities,
        nonfixed_entities_in_bounds=alignment.nonfixed_entities_in_bounds,
        nonfixed_entities_out_of_bounds=alignment.nonfixed_entities_out_of_bounds,
        nonfixed_chunk_position_mismatches=(
            alignment.nonfixed_chunk_position_mismatches
        ),
        nonfixed_incomplete_chunks=alignment.nonfixed_incomplete_chunks,
        nonfixed_markers_drawn=nonfixed_markers_drawn,
        object_meshes_enabled=object_meshes,
        object_mesh_lod=object_lod,
        object_mesh_placements_selected=(
            len(selected_footprints) if object_meshes else 0
        ),
        object_mesh_placements_drawn=object_mesh_placements_drawn,
        object_mesh_models_drawn=object_mesh_models_drawn,
        object_mesh_triangles_considered=object_mesh_triangles_considered,
        object_mesh_triangles_drawn=object_mesh_triangles_drawn,
        object_mesh_pixels_drawn=object_mesh_pixels_drawn,
        missing_object_texture_keys=missing_object_texture_keys,
        object_footprints_enabled=object_footprints,
        object_footprints_drawn=object_footprints_drawn,
        object_footprints_resolved_total=(
            len(object_resolutions.footprints) if object_resolutions else 0
        ),
        object_footprints_filtered_out=(
            len(object_resolutions.footprints) - len(selected_footprints)
            if object_resolutions
            else 0
        ),
        fixed_footprints_drawn=sum(
            item.source_kind == "fixed" for item in selected_footprints
        ),
        nonfixed_indexed_footprints_drawn=sum(
            item.source_kind == "nonfixed" and item.is_spatially_indexed
            for item in selected_footprints
        ),
        nonfixed_unlinked_footprints_drawn=sum(
            item.source_kind == "nonfixed" and not item.is_spatially_indexed
            for item in selected_footprints
        ),
        object_footprint_source_filter=object_footprint_source,
        object_footprint_type_filter=tuple(sorted(footprint_filter.type_ids)),
        object_footprint_model_filter=tuple(sorted(footprint_filter.model_ids)),
        object_footprint_style=object_footprint_style,
        object_footprint_legend_enabled=object_footprints and object_legend,
        fixed_footprints_resolved=(
            object_diagnostics.fixed_resolved if object_diagnostics else 0
        ),
        fixed_footprints_without_model=(
            object_diagnostics.fixed_without_model if object_diagnostics else 0
        ),
        fixed_footprints_unresolved=(
            object_diagnostics.fixed_unresolved if object_diagnostics else 0
        ),
        nonfixed_footprints_resolved=(
            object_diagnostics.nonfixed_resolved if object_diagnostics else 0
        ),
        nonfixed_footprints_unresolved=(
            object_diagnostics.nonfixed_unresolved if object_diagnostics else 0
        ),
        object_model_ids_requested=(
            object_diagnostics.model_ids_requested if object_diagnostics else ()
        ),
        object_model_ids_resolved=(
            object_diagnostics.model_ids_resolved if object_diagnostics else ()
        ),
        object_model_ids_drawn=tuple(
            sorted(
                {
                    item.model_id
                    for item in selected_footprints
                    if item.model_id is not None
                }
            )
        ),
        missing_object_model_ids=(
            object_diagnostics.missing_model_ids if object_diagnostics else ()
        ),
        malformed_object_model_ids=(
            object_diagnostics.malformed_model_ids if object_diagnostics else ()
        ),
        image_width=image.width,
        image_height=image.height,
        pixels_per_cell=pixels_per_cell,
        flip_y=flip_y,
    )
    return U9MapRenderResult(image=image, diagnostics=diagnostics)
