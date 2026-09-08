"""Batch-render and catalogue Ultima IX terrain regions without joining maps."""

from __future__ import annotations

__all__ = [
    "DEFAULT_ATLAS_PIXELS_PER_CELL",
    "U9MapAtlasDiagnostics",
    "U9MapAtlasError",
    "U9MapAtlasRegionRecord",
    "U9MapAtlasResult",
    "U9RegionFiles",
    "discover_region_files",
    "render_map_atlas",
]

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from titan.u9.fixed import U9FixedError
from titan.u9.map_render import (
    MAX_MAP_PIXELS_PER_CELL,
    U9MapRenderError,
    U9ObjectTextureProvider,
    U9TerrainTextureProvider,
    render_region_map,
)
from titan.u9.nonfixed import U9NonfixedError
from titan.u9.object_placement import (
    U9ModelBoundsProvider,
    U9ModelProvider,
    U9ObjectPlacementError,
)
from titan.u9.region_scene import U9RegionScene, U9RegionSceneError
from titan.u9.terrain import CHUNK_POINTS, U9Terrain, U9TerrainError
from titan.u9.types_dat import U9TypesDat, U9TypesDatError

_NUMBERED_FILE = re.compile(r"^(?P<prefix>[a-z]+)\.(?P<region>\d+)$", re.I)
_ATLAS_FORMAT = "titan-u9-map-atlas-v1"
_CELL_GRID_RGBA = (48, 220, 255, 96)
_TILE_GRID_RGBA = (255, 64, 192, 208)
_TILE_COORDINATE_RGBA = (64, 255, 128, 255)
_CHUNK_LABEL_RGBA = (255, 216, 64, 255)
DEFAULT_ATLAS_PIXELS_PER_CELL = 28


class U9MapAtlasError(Exception):
    """Raised when U9 region discovery or atlas rendering cannot proceed."""


@dataclass(frozen=True)
class U9RegionFiles:
    """One numeric U9 region and its available terrain/object files."""

    region_id: int
    terrain_path: Path
    fixed_path: Path | None = None
    nonfixed_path: Path | None = None


@dataclass(frozen=True)
class U9MapAtlasRegionRecord:
    """Manifest record for one successfully rendered or failed region."""

    region_id: int
    terrain_name: str
    width: int
    height: int
    terrain_path: Path
    fixed_path: Path | None
    nonfixed_path: Path | None
    preview_path: Path | None
    diagnostics: dict[str, object] | None
    error: str | None = None


@dataclass(frozen=True)
class U9MapAtlasDiagnostics:
    """Aggregate discovery and rendering coverage for one atlas."""

    requested_regions: int
    rendered_regions: int
    failed_regions: int
    regions_with_fixed: int
    regions_with_nonfixed: int
    total_terrain_cells: int
    total_fixed_objects: int
    total_nonfixed_indexed_entities: int
    regions_with_missing_textures: int

    def to_dict(self) -> dict[str, object]:
        """Return JSON-ready aggregate diagnostics."""
        return asdict(self)


@dataclass(frozen=True)
class U9MapAtlasResult:
    """Contact sheet path, region records, and aggregate diagnostics."""

    atlas_path: Path
    regions_directory: Path
    diagnostics: U9MapAtlasDiagnostics
    regions: tuple[U9MapAtlasRegionRecord, ...]
    columns: int
    thumbnail_size: int
    pixels_per_cell: int
    cell_grid: bool = False
    tile_grid: bool = False
    tile_coordinates: bool = False
    chunk_labels: bool = False

    def manifest(self) -> dict[str, object]:
        """Return a JSON-ready atlas manifest with explicit numeric ordering."""
        root = self.atlas_path.parent.resolve()

        def relative(path: Path | None) -> str | None:
            if path is None:
                return None
            return path.resolve().relative_to(root).as_posix()

        entries: list[dict[str, object]] = []
        for record in self.regions:
            entries.append(
                {
                    "region_id": record.region_id,
                    "terrain_name": record.terrain_name,
                    "width": record.width,
                    "height": record.height,
                    "tile_width": record.width // CHUNK_POINTS,
                    "tile_height": record.height // CHUNK_POINTS,
                    "terrain_file": str(record.terrain_path.resolve()),
                    "fixed_file": (
                        str(record.fixed_path.resolve()) if record.fixed_path else None
                    ),
                    "nonfixed_file": (
                        str(record.nonfixed_path.resolve())
                        if record.nonfixed_path
                        else None
                    ),
                    "preview": relative(record.preview_path),
                    "diagnostics": record.diagnostics,
                    "error": record.error,
                }
            )
        return {
            "format": _ATLAS_FORMAT,
            "atlas": relative(self.atlas_path),
            "ordering": "numeric region ID",
            "spatial_adjacency_inferred": False,
            "layout": {
                "columns": self.columns,
                "thumbnail_size": self.thumbnail_size,
                "pixels_per_cell": self.pixels_per_cell,
            },
            "grid_overlays": {
                "cell_grid": {
                    "enabled": self.cell_grid,
                    "spacing_cells": 1,
                    "color_rgba": list(_CELL_GRID_RGBA),
                },
                "tile_grid": {
                    "enabled": self.tile_grid,
                    "spacing_cells": CHUNK_POINTS,
                    "color_rgba": list(_TILE_GRID_RGBA),
                },
                "tile_coordinates": {
                    "enabled": self.tile_coordinates,
                    "format": "Ttile_x,tile_y / Ccell_origin_x,cell_origin_y",
                    "meaning": (
                        "stored terrain tile-grid coordinates and the first terrain "
                        "cell covered by that 16x16-cell placement"
                    ),
                    "color_rgba": list(_TILE_COORDINATE_RGBA),
                },
                "chunk_labels": {
                    "enabled": self.chunk_labels,
                    "meaning": "terrain chunk index referenced by each tile placement",
                    "color_rgba": list(_CHUNK_LABEL_RGBA),
                },
            },
            "summary": self.diagnostics.to_dict(),
            "regions": entries,
        }


def _discover_numbered_files(directory: Path, prefix: str) -> dict[int, Path]:
    if not directory.is_dir():
        raise U9MapAtlasError(f"directory not found: {directory}")
    result: dict[int, Path] = {}
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = _NUMBERED_FILE.fullmatch(path.name)
        if match is None or match.group("prefix").casefold() != prefix.casefold():
            continue
        region_id = int(match.group("region"))
        previous = result.get(region_id)
        if previous is not None:
            raise U9MapAtlasError(
                f"duplicate {prefix} region {region_id}: {previous.name}, {path.name}"
            )
        result[region_id] = path
    return result


def discover_region_files(
    static_directory: str | Path,
    *,
    runtime_directory: str | Path | None = None,
    region_ids: tuple[int, ...] = (),
) -> tuple[U9RegionFiles, ...]:
    """Discover and numerically pair ``terrain.N``, ``fixed.N``, and runtime data."""
    static = Path(static_directory)
    terrains = _discover_numbered_files(static, "terrain")
    if not terrains:
        raise U9MapAtlasError(f"no terrain.N files found in {static}")
    fixed = _discover_numbered_files(static, "fixed")
    nonfixed = (
        _discover_numbered_files(Path(runtime_directory), "nonfixed")
        if runtime_directory is not None
        else {}
    )
    if any(region_id < 0 for region_id in region_ids):
        raise U9MapAtlasError("region IDs cannot be negative")
    selected = sorted(set(region_ids)) if region_ids else sorted(terrains)
    missing = [region_id for region_id in selected if region_id not in terrains]
    if missing:
        values = ", ".join(str(region_id) for region_id in missing)
        raise U9MapAtlasError(f"terrain file not found for region {values}")
    return tuple(
        U9RegionFiles(
            region_id=region_id,
            terrain_path=terrains[region_id],
            fixed_path=fixed.get(region_id),
            nonfixed_path=nonfixed.get(region_id),
        )
        for region_id in selected
    )


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, width: int) -> str:
    if draw.textbbox((0, 0), text)[2] <= width:
        return text
    suffix = "..."
    candidate = text
    while candidate and draw.textbbox((0, 0), candidate + suffix)[2] > width:
        candidate = candidate[:-1]
    return candidate + suffix


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    width: int,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> tuple[str, ...]:
    """Wrap text to a measured pixel width without dropping words."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        while word and draw.textbbox((0, 0), word, font=font)[2] > width:
            split_at = len(word) - 1
            while (
                split_at > 1
                and draw.textbbox((0, 0), word[:split_at], font=font)[2] > width
            ):
                split_at -= 1
            lines.append(word[:split_at])
            word = word[split_at:]
        current = word
    if current:
        lines.append(current)
    return tuple(lines) or ("",)


def _pack_legend_rows(
    draw: ImageDraw.ImageDraw,
    parts: list[tuple[str, tuple[int, int, int, int]]],
    width: int,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> tuple[tuple[tuple[str, tuple[int, int, int, int]], ...], ...]:
    """Pack legend entries into as many measured rows as the sheet needs."""
    rows: list[list[tuple[str, tuple[int, int, int, int]]]] = []
    current: list[tuple[str, tuple[int, int, int, int]]] = []
    used_width = 0
    for part in parts:
        label, _color = part
        item_width = 11 + int(draw.textbbox((0, 0), label, font=font)[2])
        gap = 12 if current else 0
        if current and used_width + gap + item_width > width:
            rows.append(current)
            current = []
            used_width = 0
            gap = 0
        current.append(part)
        used_width += gap + item_width
    if current:
        rows.append(current)
    return tuple(tuple(row) for row in rows)


def _thumbnail(image: Image.Image, size: int) -> Image.Image:
    source = image.convert("RGB")
    resampling = (
        Image.Resampling.LANCZOS
        if source.width > size or source.height > size
        else Image.Resampling.NEAREST
    )
    source.thumbnail((size, size), resampling)
    result = Image.new("RGB", (size, size), (15, 18, 22))
    result.paste(source, ((size - source.width) // 2, (size - source.height) // 2))
    return result


def _grid_positions(length: int, spacing: int) -> tuple[int, ...]:
    """Return visible boundary pixels, including the far image edge."""
    return tuple(
        min(position, length - 1) for position in range(0, length + 1, spacing)
    )


def _draw_grid_lines(
    draw: ImageDraw.ImageDraw,
    *,
    image_size: tuple[int, int],
    spacing: int,
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    image_width, image_height = image_size
    for x in _grid_positions(image_width, spacing):
        draw.line(((x, 0), (x, image_height - 1)), fill=color, width=width)
    for y in _grid_positions(image_height, spacing):
        draw.line(((0, y), (image_width - 1, y)), fill=color, width=width)


def _draw_chunk_labels(
    image: Image.Image,
    terrain: U9Terrain,
    *,
    pixels_per_cell: int,
    flip_y: bool,
) -> Image.Image:
    draw = ImageDraw.Draw(image)
    tile_pixels = CHUNK_POINTS * pixels_per_cell
    font = ImageFont.load_default(size=max(10, min(32, tile_pixels // 10)))
    for tile_y in range(terrain.tile_height):
        screen_tile_y = terrain.tile_height - tile_y - 1 if flip_y else tile_y
        for tile_x in range(terrain.tile_width):
            label = str(terrain.tile(tile_x, tile_y))
            left = tile_x * tile_pixels
            top = screen_tile_y * tile_pixels
            bounds = draw.textbbox((0, 0), label, font=font, stroke_width=1)
            text_width = bounds[2] - bounds[0]
            text_height = bounds[3] - bounds[1]
            x = left + max(2, (tile_pixels - text_width) // 2)
            y = top + max(1, (tile_pixels - text_height) // 2)
            draw.text(
                (x, y),
                label,
                fill=_CHUNK_LABEL_RGBA,
                font=font,
                stroke_width=1,
                stroke_fill=(0, 0, 0, 255),
            )
    return image


def _draw_tile_coordinates(
    image: Image.Image,
    terrain: U9Terrain,
    *,
    pixels_per_cell: int,
    flip_y: bool,
) -> Image.Image:
    """Label tile placements with their stored X/Y grid coordinates."""
    draw = ImageDraw.Draw(image)
    tile_pixels = CHUNK_POINTS * pixels_per_cell
    font = ImageFont.load_default(size=max(8, min(32, tile_pixels // 10)))
    inset = max(3, pixels_per_cell // 2)
    stroke_width = 2 if pixels_per_cell >= 16 else 1
    for tile_y in range(terrain.tile_height):
        screen_tile_y = terrain.tile_height - tile_y - 1 if flip_y else tile_y
        for tile_x in range(terrain.tile_width):
            draw.multiline_text(
                (tile_x * tile_pixels + inset, screen_tile_y * tile_pixels + inset),
                (
                    f"T{tile_x},{tile_y}\n"
                    f"C{tile_x * CHUNK_POINTS},{tile_y * CHUNK_POINTS}"
                ),
                fill=_TILE_COORDINATE_RGBA,
                font=font,
                spacing=1,
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0, 255),
            )
    return image


def _apply_grid_overlays(
    image: Image.Image,
    terrain: U9Terrain,
    *,
    pixels_per_cell: int,
    cell_grid: bool,
    tile_grid: bool,
    tile_coordinates: bool,
    chunk_labels: bool,
    flip_y: bool,
) -> Image.Image:
    result = image.convert("RGBA")
    if cell_grid or tile_grid:
        overlay = Image.new("RGBA", result.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        if cell_grid:
            _draw_grid_lines(
                draw,
                image_size=result.size,
                spacing=pixels_per_cell,
                color=_CELL_GRID_RGBA,
                width=1,
            )
        if tile_grid:
            _draw_grid_lines(
                draw,
                image_size=result.size,
                spacing=CHUNK_POINTS * pixels_per_cell,
                color=_TILE_GRID_RGBA,
                width=max(1, min(pixels_per_cell, 3)),
            )
        result = Image.alpha_composite(result, overlay)
    if tile_coordinates:
        result = _draw_tile_coordinates(
            result,
            terrain,
            pixels_per_cell=pixels_per_cell,
            flip_y=flip_y,
        )
    if chunk_labels:
        result = _draw_chunk_labels(
            result,
            terrain,
            pixels_per_cell=pixels_per_cell,
            flip_y=flip_y,
        )
    return result


def _compose_contact_sheet(
    records_and_images: list[tuple[U9MapAtlasRegionRecord, Image.Image | None]],
    *,
    thumbnail_size: int,
    columns: int,
    cell_grid: bool,
    tile_grid: bool,
    tile_coordinates: bool,
    chunk_labels: bool,
) -> Image.Image:
    margin = 12
    gap = 8
    label_height = 52
    used_columns = min(columns, len(records_and_images))
    rows = math.ceil(len(records_and_images) / used_columns)
    cards_width = used_columns * thumbnail_size + (used_columns - 1) * gap
    width = max(240, margin * 2 + cards_width)
    card_origin_x = (width - cards_width) // 2
    content_width = width - margin * 2
    font = ImageFont.load_default()
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_lines = _wrap_text(
        measure,
        "Ultima IX regions - numeric ID order, not geographic adjacency",
        content_width,
        font,
    )
    legend_parts: list[tuple[str, tuple[int, int, int, int]]] = []
    if cell_grid:
        legend_parts.append(("1-cell grid", _CELL_GRID_RGBA))
    if tile_grid:
        legend_parts.append(("16x16 tile/chunk", _TILE_GRID_RGBA))
    if tile_coordinates:
        legend_parts.append(("T tile x,y / C cell origin", _TILE_COORDINATE_RGBA))
    if chunk_labels:
        legend_parts.append(("stored chunk ID", _CHUNK_LABEL_RGBA))
    legend_rows = _pack_legend_rows(measure, legend_parts, content_width, font)
    title_line_height = 12
    legend_line_height = 14
    legend_top = 8 + len(title_lines) * title_line_height + 3
    title_height = legend_top + len(legend_rows) * legend_line_height + 3
    card_height = thumbnail_size + label_height
    height = title_height + margin + rows * card_height + (rows - 1) * gap + margin
    atlas = Image.new("RGB", (width, height), (28, 31, 36))
    draw = ImageDraw.Draw(atlas)
    for line_index, line in enumerate(title_lines):
        draw.text(
            (margin, 8 + line_index * title_line_height),
            line,
            fill=(238, 241, 245),
            font=font,
        )
    for row_index, legend_row in enumerate(legend_rows):
        legend_x = margin
        legend_y = legend_top + row_index * legend_line_height
        for label, color in legend_row:
            draw.rectangle(
                (legend_x, legend_y, legend_x + 7, legend_y + 7),
                fill=color[:3],
            )
            legend_x += 11
            draw.text((legend_x, legend_y - 2), label, fill=color[:3], font=font)
            legend_x += int(draw.textbbox((0, 0), label, font=font)[2]) + 12
    for index, (record, preview) in enumerate(records_and_images):
        column = index % used_columns
        row = index // used_columns
        x = card_origin_x + column * (thumbnail_size + gap)
        y = title_height + margin + row * (card_height + gap)
        if preview is None:
            card = Image.new("RGB", (thumbnail_size, thumbnail_size), (78, 24, 28))
            card_draw = ImageDraw.Draw(card)
            card_draw.text((8, 8), "RENDER ERROR", fill=(255, 210, 210), font=font)
        else:
            card = _thumbnail(preview, thumbnail_size)
        atlas.paste(card, (x, y))

        label_y = y + thumbnail_size + 3
        available = thumbnail_size - 4
        name = record.terrain_name or "(unnamed)"
        lines = [
            f"Region {record.region_id} | {name}",
            (
                f"{record.width}x{record.height} cells = "
                f"{record.width // CHUNK_POINTS}x{record.height // CHUNK_POINTS} tiles"
            ),
        ]
        if record.diagnostics is not None:
            values = record.diagnostics
            missing_texture_keys = values["missing_texture_keys"]
            missing_texture_count = (
                len(missing_texture_keys)
                if isinstance(missing_texture_keys, (list, tuple))
                else 0
            )
            missing_object_texture_keys = values["missing_object_texture_keys"]
            if isinstance(missing_object_texture_keys, (list, tuple)):
                missing_texture_count += len(missing_object_texture_keys)
            lines.extend(
                (
                    f"water {values['water_level']} | fixed {values['fixed_objects']}",
                    (
                        f"nonfixed {values['nonfixed_indexed_entities']}"
                        f"+{values['nonfixed_unlinked_entities']} | "
                        f"missing {missing_texture_count}"
                    ),
                )
            )
        else:
            lines.append(_ellipsize(draw, record.error or "unknown error", available))
        for line_index, line in enumerate(lines[:4]):
            draw.text(
                (x + 2, label_y + line_index * 12),
                _ellipsize(draw, line, available),
                fill=(244, 220, 220) if record.error else (222, 226, 232),
                font=font,
            )
    return atlas


def render_map_atlas(
    sources: tuple[U9RegionFiles, ...],
    textures: U9TerrainTextureProvider,
    output_directory: str | Path,
    *,
    thumbnail_size: int = 224,
    columns: int = 6,
    pixels_per_cell: int = DEFAULT_ATLAS_PIXELS_PER_CELL,
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
    cell_grid: bool = False,
    tile_grid: bool = False,
    tile_coordinates: bool = False,
    chunk_labels: bool = False,
    flip_y: bool = True,
    continue_on_error: bool = True,
) -> U9MapAtlasResult:
    """Render full previews plus one labelled, numerically ordered contact sheet."""
    if not sources:
        raise U9MapAtlasError("atlas requires at least one terrain region")
    if not 32 <= thumbnail_size <= 1024:
        raise U9MapAtlasError("thumbnail_size must be from 32 to 1024")
    if not 1 <= columns <= 32:
        raise U9MapAtlasError("columns must be from 1 to 32")
    if not 1 <= pixels_per_cell <= MAX_MAP_PIXELS_PER_CELL:
        raise U9MapAtlasError(
            f"pixels_per_cell must be from 1 to {MAX_MAP_PIXELS_PER_CELL}"
        )
    if not 0.0 <= hillshade_strength <= 1.0:
        raise U9MapAtlasError("hillshade_strength must be from 0.0 to 1.0")
    if water_frame < 0:
        raise U9MapAtlasError("water_frame must be zero or greater")
    if fixed_marker_radius < 1 or nonfixed_marker_radius < 1:
        raise U9MapAtlasError("object marker radii must be at least one")
    if object_lod < 0:
        raise U9MapAtlasError("object_lod cannot be negative")
    if object_meshes and (object_mesh_models is None or object_textures is None):
        raise U9MapAtlasError("object meshes require model and texture providers")
    if cell_grid and pixels_per_cell < 4:
        raise U9MapAtlasError(
            "cell grids require pixels_per_cell of at least 4 for usable detail"
        )
    if chunk_labels and pixels_per_cell < 2:
        raise U9MapAtlasError(
            "chunk labels require pixels_per_cell of at least 2 for usable detail"
        )
    if tile_coordinates and pixels_per_cell < 4:
        raise U9MapAtlasError(
            "tile coordinates require pixels_per_cell of at least 4 for usable detail"
        )
    if object_footprint_source not in ("all", "fixed", "nonfixed"):
        raise U9MapAtlasError("object_footprint_source must be all, fixed, or nonfixed")
    if object_footprint_style not in ("outline", "fill"):
        raise U9MapAtlasError("object_footprint_style must be outline or fill")
    if object_footprints and object_models is None:
        raise U9MapAtlasError("object footprints require a model-bounds provider")
    if (
        (object_footprints or object_meshes)
        and object_types is None
        and any(source.fixed_path is not None for source in sources)
    ):
        raise U9MapAtlasError("fixed object rendering requires TYPES.DAT")
    ordered = tuple(sorted(sources, key=lambda item: item.region_id))
    if len({item.region_id for item in ordered}) != len(ordered):
        raise U9MapAtlasError("atlas source region IDs must be unique")

    destination = Path(output_directory)
    regions_directory = destination / "regions"
    regions_directory.mkdir(parents=True, exist_ok=True)
    digits = max(3, len(str(max(item.region_id for item in ordered))))
    records: list[U9MapAtlasRegionRecord] = []
    cards: list[tuple[U9MapAtlasRegionRecord, Image.Image | None]] = []
    total_terrain_cells = 0
    total_fixed_objects = 0
    total_nonfixed_indexed_entities = 0
    regions_with_missing_textures = 0
    known_errors = (
        OSError,
        U9FixedError,
        U9NonfixedError,
        U9TerrainError,
        U9RegionSceneError,
        U9MapRenderError,
        U9ObjectPlacementError,
        U9TypesDatError,
    )
    for source in ordered:
        try:
            scene = U9RegionScene.from_files(
                source.terrain_path,
                fixed_path=source.fixed_path,
                nonfixed_path=source.nonfixed_path,
            )
            rendered = render_region_map(
                scene,
                textures,
                pixels_per_cell=pixels_per_cell,
                hillshade=hillshade,
                hillshade_strength=hillshade_strength,
                water=water,
                water_frame=water_frame,
                fixed_markers=fixed_markers,
                fixed_marker_radius=fixed_marker_radius,
                nonfixed_markers=nonfixed_markers,
                nonfixed_marker_radius=nonfixed_marker_radius,
                include_unlinked_nonfixed=include_unlinked_nonfixed,
                object_meshes=object_meshes,
                object_mesh_models=object_mesh_models,
                object_textures=object_textures,
                object_lod=object_lod,
                object_footprints=object_footprints,
                object_models=object_models,
                object_types=object_types,
                object_footprint_source=object_footprint_source,
                object_type_ids=object_type_ids,
                object_model_ids=object_model_ids,
                object_footprint_style=object_footprint_style,
                object_legend=False,
                flip_y=flip_y,
            )
        except known_errors as error:
            if not continue_on_error:
                raise U9MapAtlasError(
                    f"region {source.region_id} could not be rendered: {error}"
                ) from error
            record = U9MapAtlasRegionRecord(
                region_id=source.region_id,
                terrain_name="",
                width=0,
                height=0,
                terrain_path=source.terrain_path,
                fixed_path=source.fixed_path,
                nonfixed_path=source.nonfixed_path,
                preview_path=None,
                diagnostics=None,
                error=str(error),
            )
            records.append(record)
            cards.append((record, None))
            continue

        preview = _apply_grid_overlays(
            rendered.image,
            scene.terrain,
            pixels_per_cell=pixels_per_cell,
            cell_grid=cell_grid,
            tile_grid=tile_grid,
            tile_coordinates=tile_coordinates,
            chunk_labels=chunk_labels,
            flip_y=flip_y,
        )
        preview_path = regions_directory / f"region_{source.region_id:0{digits}d}.png"
        preview.save(preview_path)
        region_diagnostics = rendered.diagnostics.to_dict()
        record = U9MapAtlasRegionRecord(
            region_id=source.region_id,
            terrain_name=rendered.diagnostics.terrain_name,
            width=rendered.diagnostics.image_width // pixels_per_cell,
            height=rendered.diagnostics.image_height // pixels_per_cell,
            terrain_path=source.terrain_path,
            fixed_path=source.fixed_path,
            nonfixed_path=source.nonfixed_path,
            preview_path=preview_path,
            diagnostics=region_diagnostics,
        )
        records.append(record)
        cards.append((record, _thumbnail(preview, thumbnail_size)))
        total_terrain_cells += rendered.diagnostics.terrain_cells
        total_fixed_objects += rendered.diagnostics.fixed_objects
        total_nonfixed_indexed_entities += (
            rendered.diagnostics.nonfixed_indexed_entities
        )
        regions_with_missing_textures += int(
            bool(
                rendered.diagnostics.missing_texture_keys
                or rendered.diagnostics.missing_object_texture_keys
            )
        )

    atlas_path = destination / "atlas.png"
    atlas = _compose_contact_sheet(
        cards,
        thumbnail_size=thumbnail_size,
        columns=columns,
        cell_grid=cell_grid,
        tile_grid=tile_grid,
        tile_coordinates=tile_coordinates,
        chunk_labels=chunk_labels,
    )
    atlas.save(atlas_path)
    successful = [record for record in records if record.diagnostics is not None]
    atlas_diagnostics = U9MapAtlasDiagnostics(
        requested_regions=len(ordered),
        rendered_regions=len(successful),
        failed_regions=len(records) - len(successful),
        regions_with_fixed=sum(item.fixed_path is not None for item in ordered),
        regions_with_nonfixed=sum(item.nonfixed_path is not None for item in ordered),
        total_terrain_cells=total_terrain_cells,
        total_fixed_objects=total_fixed_objects,
        total_nonfixed_indexed_entities=total_nonfixed_indexed_entities,
        regions_with_missing_textures=regions_with_missing_textures,
    )
    return U9MapAtlasResult(
        atlas_path=atlas_path,
        regions_directory=regions_directory,
        diagnostics=atlas_diagnostics,
        regions=tuple(records),
        columns=min(columns, len(records)),
        thumbnail_size=thumbnail_size,
        pixels_per_cell=pixels_per_cell,
        cell_grid=cell_grid,
        tile_grid=tile_grid,
        tile_coordinates=tile_coordinates,
        chunk_labels=chunk_labels,
    )
