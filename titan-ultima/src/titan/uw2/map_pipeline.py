"""Native UU2 map extraction and rendering pipeline."""

from __future__ import annotations

import json
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

from PIL import Image

from titan.uw2.ark import ArkArchive
from titan.uw2.exe_models import UW2ModelArchive
from titan.uw2.gr import UW2GRArchive
from titan.uw2.level import (
    COUNTERS_OFFSET,
    LEVEL_BLOCK_MIN_SIZE,
    level_name_for_slot,
    parse_level,
    parse_shades_dat,
    parse_terrain_dat,
    parse_texture_mapping,
    world_name_for_slot,
)
from titan.uw2.map_render import render_level
from titan.uw2.object_data import UW2AnimationTable, UW2CommonObjectTable
from titan.uw2.palette import UW2Palette
from titan.uw2.render_common import (
    load_gr_textures,
    load_terrain_textures,
    render_output_filename,
)
from titan.uw2.strings import GameStrings
from titan.uw2.terrain import TRArchive, make_contact_sheet

ARK_BLOCK_COUNT = 320
"""LEV.ARK stores 80 slots across four block ranges."""

MAP_SLOT_COUNT = 80
"""Map, texture-mapping, automap, and note blocks are indexed per slot."""

TEXTURE_MAPPING_BLOCK_SIZE = 0x86
"""64 texture-mapping words followed by six door-texture bytes."""

AUTOMAP_BLOCK_SIZE = 0x1000
"""One automap byte per 64x64 tile."""

MARKER_OFFSET = COUNTERS_OFFSET + 6
"""The 0x7c06 word that follows the free-list counters."""


@dataclass(frozen=True)
class MapRenderAssets:
    """Decoded, in-memory assets needed by UU2 cutaway rendering."""

    terrain: dict[int, Image.Image]
    doors: dict[int, Image.Image]
    tmflat: dict[int, Image.Image]
    tmobj: dict[int, Image.Image]
    objects: dict[int, Image.Image]
    animo: dict[int, Image.Image]
    common_objects: UW2CommonObjectTable
    animations: UW2AnimationTable
    models: UW2ModelArchive | None
    palette: UW2Palette
    strings: GameStrings | None = None


def data_directory(source: str | Path) -> Path:
    """Return the DATA directory for an install root or DATA path."""
    source_path = Path(source).expanduser()
    return source_path if source_path.name.upper() == "DATA" else source_path / "DATA"


def load_levels(source: str | Path, slots: Iterable[int]) -> list[dict]:
    """Decode selected LEV.ARK slots directly into memory."""
    data_dir = data_directory(source)
    archive = ArkArchive.from_file(data_dir / "LEV.ARK")
    light_levels = _read_optional(data_dir / "DL.DAT")
    levels: list[dict] = []
    for slot in sorted(set(slots)):
        if slot < 0 or slot >= 80:
            raise ValueError(f"UU2 map slot must be in 0..79: {slot}")
        if not archive.is_available(slot):
            continue
        level_block = archive.get_decoded_block(slot)
        texture_block = archive.get_decoded_block(slot + 80)
        light_level = (
            light_levels[slot]
            if light_levels is not None and slot < len(light_levels)
            else None
        )
        levels.append(
            parse_level(
                slot,
                level_block,
                parse_texture_mapping(texture_block),
                _optional_archive_block(archive, slot + 160),
                _optional_archive_block(archive, slot + 240),
                light_level,
            )
        )
    return levels


def load_terrain_images(source: str | Path) -> dict[int, Image.Image]:
    """Decode T64.TR terrain textures into memory, keyed by texture ID."""
    data_dir = data_directory(source)
    palette = UW2Palette.from_file(data_dir / "PALS.DAT")
    archive = TRArchive.from_file(data_dir / "T64.TR")
    palette_rgb = palette.flattened_rgb()
    return {
        texture.index: texture.to_image(palette_rgb) for texture in archive.textures
    }


def load_render_assets(source: str | Path) -> MapRenderAssets:
    """Decode every archive used by map rendering without writing PNG files."""
    data_dir = data_directory(source)
    palette = UW2Palette.from_file(data_dir / "PALS.DAT")
    terrain = load_terrain_images(source)
    allpals = data_dir / "ALLPALS.DAT"
    executable = data_dir.parent / "UW2.EXE"

    def load_gr(name: str) -> dict[int, Image.Image]:
        path = data_dir / name
        if not path.is_file():
            return {}
        archive = UW2GRArchive.from_file(path, allpals if allpals.is_file() else None)
        return {record.index: record.to_image(palette) for record in archive.images}

    return MapRenderAssets(
        terrain=terrain,
        doors=load_gr("DOORS.GR"),
        tmflat=load_gr("TMFLAT.GR"),
        tmobj=load_gr("TMOBJ.GR"),
        objects=load_gr("OBJECTS.GR"),
        animo=load_gr("ANIMO.GR"),
        common_objects=UW2CommonObjectTable.from_file(data_dir / "COMOBJ.DAT"),
        animations=UW2AnimationTable.from_file(data_dir / "OBJECTS.DAT"),
        models=UW2ModelArchive.from_file(executable) if executable.is_file() else None,
        palette=palette,
        strings=_optional_strings(data_dir / "STRINGS.PAK"),
    )


def extract_maps(
    source: str | Path,
    output: str | Path,
    *,
    slots: Iterable[int] | None = None,
    write_decoded_blocks: bool = False,
) -> list[dict]:
    """Decode LEV.ARK map slots and write renderer-ready JSON files."""
    source_path = Path(source).expanduser()
    data_dir = data_directory(source_path)
    output_path = Path(output)
    levels_dir = output_path / "levels"
    blocks_dir = output_path / "decoded_blocks"
    levels_dir.mkdir(parents=True, exist_ok=True)
    if write_decoded_blocks:
        blocks_dir.mkdir(parents=True, exist_ok=True)

    archive = ArkArchive.from_file(data_dir / "LEV.ARK")
    _write_json(output_path / "archive_summary.json", archive.summary())
    light_levels = _read_optional(data_dir / "DL.DAT")
    terrain = _read_optional(data_dir / "TERRAIN.DAT")
    shades = _read_optional(data_dir / "SHADES.DAT")
    if terrain is not None:
        _write_json(output_path / "terrain_dat.json", parse_terrain_dat(terrain))
    if shades is not None:
        _write_json(output_path / "shades_dat.json", parse_shades_dat(shades))
    if light_levels is not None:
        _write_json(
            output_path / "dl_dat.json",
            {
                "raw_size": len(light_levels),
                "light_levels": [
                    {
                        "slot_index": index,
                        "level_id_1based": index + 1,
                        "light_level": value,
                    }
                    for index, value in enumerate(light_levels[:80])
                ],
            },
        )

    requested = set(range(80) if slots is None else slots)
    summaries: list[dict] = []
    for slot in sorted(requested):
        if slot < 0 or slot >= 80:
            raise ValueError(f"UU2 map slot must be in 0..79: {slot}")
        if not archive.is_available(slot):
            continue
        level_block = archive.get_decoded_block(slot)
        texture_block = archive.get_decoded_block(slot + 80)
        automap_block = _optional_archive_block(archive, slot + 160)
        notes_block = _optional_archive_block(archive, slot + 240)
        if write_decoded_blocks:
            _write_block(blocks_dir / f"level_{slot:03d}_map.bin", level_block)
            _write_block(blocks_dir / f"level_{slot:03d}_textures.bin", texture_block)
            if automap_block is not None:
                _write_block(
                    blocks_dir / f"level_{slot:03d}_automap.bin", automap_block
                )
            if notes_block is not None:
                _write_block(blocks_dir / f"level_{slot:03d}_notes.bin", notes_block)
        light_level = (
            light_levels[slot]
            if light_levels is not None and slot < len(light_levels)
            else None
        )
        level = parse_level(
            slot,
            level_block,
            parse_texture_mapping(texture_block),
            automap_block,
            notes_block,
            light_level,
        )
        _write_json(levels_dir / f"level_{slot:03d}.json", level)
        summaries.append(
            {
                "slot_index": slot,
                "level_id_1based": slot + 1,
                "world_name": world_name_for_slot(slot),
                "level_name": level_name_for_slot(slot),
                "light_level": light_level,
                "block_indices": {
                    "map": slot,
                    "texture_mapping": slot + 80,
                    "automap": slot + 160,
                    "notes": slot + 240,
                },
                "decoded_sizes": {
                    "map": len(level_block),
                    "texture_mapping": len(texture_block),
                    "automap": len(automap_block)
                    if automap_block is not None
                    else None,
                    "notes": len(notes_block) if notes_block is not None else None,
                },
                **level["summary"],
            }
        )
    _write_json(
        output_path / "levels_summary.json",
        {
            "source": str(source_path),
            "lev_ark": str(data_dir / "LEV.ARK"),
            "level_count": len(summaries),
            "levels": summaries,
        },
    )
    return summaries


def verify_maps(source: str | Path) -> dict:
    """Smoke-check LEV.ARK block shapes and confirm every slot still decodes.

    Reports rather than raises, so one malformed slot does not hide the rest.
    """
    data_dir = data_directory(source)
    archive = ArkArchive.from_file(data_dir / "LEV.ARK")
    errors: list[str] = []
    markers: Counter = Counter()
    populated: list[int] = []

    if len(archive.blocks) != ARK_BLOCK_COUNT:
        errors.append(f"expected {ARK_BLOCK_COUNT} blocks, found {len(archive.blocks)}")

    for slot in range(MAP_SLOT_COUNT):
        if not archive.is_available(slot):
            continue
        populated.append(slot)

        if not archive.is_available(slot + 80):
            errors.append(
                f"slot {slot}: texture mapping block {slot + 80} is unavailable"
            )
            continue

        try:
            level_block = archive.get_decoded_block(slot)
            texture_block = archive.get_decoded_block(slot + 80)
        except (IndexError, KeyError, ValueError) as error:
            errors.append(f"slot {slot}: block decode failed: {error}")
            continue

        if len(level_block) != LEVEL_BLOCK_MIN_SIZE:
            errors.append(
                f"slot {slot}: map size {len(level_block):#x} "
                f"!= {LEVEL_BLOCK_MIN_SIZE:#x}"
            )
        if len(texture_block) != TEXTURE_MAPPING_BLOCK_SIZE:
            errors.append(
                f"slot {slot}: texture size {len(texture_block):#x} "
                f"!= {TEXTURE_MAPPING_BLOCK_SIZE:#x}"
            )

        try:
            automap_block = _optional_archive_block(archive, slot + 160)
        except (IndexError, KeyError, ValueError) as error:
            errors.append(f"slot {slot}: automap decode failed: {error}")
            automap_block = None
        if automap_block is not None and len(automap_block) != AUTOMAP_BLOCK_SIZE:
            errors.append(
                f"slot {slot}: automap size {len(automap_block):#x} "
                f"!= {AUTOMAP_BLOCK_SIZE:#x}"
            )

        if len(level_block) >= MARKER_OFFSET + 2:
            markers[struct.unpack_from("<H", level_block, MARKER_OFFSET)[0]] += 1

        try:
            notes_block = _optional_archive_block(archive, slot + 240)
            parse_level(
                slot,
                level_block,
                parse_texture_mapping(texture_block),
                automap_block,
                notes_block,
                None,
            )
        except (IndexError, KeyError, ValueError, struct.error) as error:
            errors.append(f"slot {slot}: level parse failed: {error}")

    return {
        "lev_ark": str(data_dir / "LEV.ARK"),
        "header_prefix_hex": archive.header_prefix.hex(),
        "block_count": len(archive.blocks),
        "expected_block_count": ARK_BLOCK_COUNT,
        "available_blocks": sum(1 for block in archive.blocks if block.available),
        "populated_level_slots": populated,
        "level_markers": {
            f"0x{marker:04x}": count for marker, count in sorted(markers.items())
        },
        "errors": errors,
        "ok": not errors,
    }


def export_terrain_textures(
    source: str | Path,
    output: str | Path,
    *,
    contact_sheet: bool = False,
    scale: int = 1,
) -> dict[str, object]:
    """Export every T64.TR terrain texture as PNG, plus an optional sheet."""
    if scale < 1:
        raise ValueError("terrain texture scale must be at least 1")
    data_dir = data_directory(source)
    palette = UW2Palette.from_file(data_dir / "PALS.DAT")
    archive = TRArchive.from_file(data_dir / "T64.TR")
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    palette_rgb = palette.flattened_rgb()
    images: list[Image.Image] = []
    for texture in archive.textures:
        image = texture.to_image(palette_rgb)
        if scale > 1:
            image = image.resize(
                (image.width * scale, image.height * scale),
                Image.Resampling.NEAREST,
            )
        image.save(output_path / f"t64_{texture.index:03d}.png")
        images.append(image)
    _write_json(output_path / "t64_summary.json", archive.summary())

    sheet_path: Path | None = None
    if contact_sheet and images:
        sheet_path = output_path / "t64_contact_sheet.png"
        make_contact_sheet(images).save(sheet_path)

    return {
        "count": len(images),
        "resolution": archive.resolution,
        "contact_sheet": str(sheet_path) if sheet_path is not None else None,
    }


def export_render_assets(source: str | Path, output: str | Path) -> dict[str, int]:
    """Export terrain, door, and flat-decal textures used by the map renderer."""
    data_dir = data_directory(source)
    output_path = Path(output)
    palette = UW2Palette.from_file(data_dir / "PALS.DAT")
    terrain_archive = TRArchive.from_file(data_dir / "T64.TR")
    terrain_dir = output_path / "textures"
    terrain_dir.mkdir(parents=True, exist_ok=True)
    palette_rgb = palette.flattened_rgb()
    for texture in terrain_archive.textures:
        texture.to_image(palette_rgb).save(terrain_dir / f"t64_{texture.index:03d}.png")
    _write_json(terrain_dir / "t64_summary.json", terrain_archive.summary())

    counts = {"terrain": len(terrain_archive.textures)}
    allpals = data_dir / "ALLPALS.DAT"
    for archive_name in ("DOORS.GR", "TMFLAT.GR", "TMOBJ.GR"):
        archive_path = data_dir / archive_name
        if not archive_path.is_file():
            continue
        archive = UW2GRArchive.from_file(
            archive_path, allpals if allpals.is_file() else None
        )
        stem = archive_path.stem.lower()
        archive_dir = output_path / "gr_textures" / stem
        archive_dir.mkdir(parents=True, exist_ok=True)
        for record in archive.images:
            record.to_image(palette).save(
                archive_dir / f"{stem}_{record.index:03d}.png"
            )
        _write_json(archive_dir / f"{stem}_summary.json", archive.summary())
        counts[stem] = len(archive.images)
    return counts


def render_maps(
    extracted: str | Path,
    output: str | Path,
    *,
    slots: Iterable[int],
    **options: object,
) -> list[Path]:
    """Render extracted level JSON with the established U7-style projection."""
    extracted_path = Path(extracted)
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)
    textures = load_terrain_textures(extracted_path / "textures")
    doors = load_gr_textures(extracted_path / "gr_textures" / "doors", "doors")
    tmflat = load_gr_textures(extracted_path / "gr_textures" / "tmflat", "tmflat")
    tmobj = load_gr_textures(extracted_path / "gr_textures" / "tmobj", "tmobj")
    args = SimpleNamespace(**_render_options(options))
    written: list[Path] = []
    for slot in slots:
        level_path = extracted_path / "levels" / f"level_{slot:03d}.json"
        level = json.loads(level_path.read_text(encoding="utf-8"))
        image = render_level(level, textures, doors, tmflat, tmobj, args)
        filename = render_output_filename(
            slot, level, "u7_style_noceilings", args.name_files
        )
        destination = output_path / filename
        image.save(destination)
        written.append(destination)
    return written


def render_maps_direct(
    source: str | Path,
    output: str | Path,
    *,
    slots: Iterable[int],
    **options: object,
) -> list[Path]:
    """Read original UU2 files in memory and write only final map PNG files."""
    requested = list(slots)
    levels = load_levels(source, requested)
    found = {int(level["slot_index"]) for level in levels}
    missing = sorted(set(requested) - found)
    if missing:
        raise ValueError(f"unavailable UU2 map slots: {missing}")
    assets = load_render_assets(source)
    args = SimpleNamespace(**_render_options(options))
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for level in levels:
        slot = int(level["slot_index"])
        image = render_level(
            level,
            assets.terrain,
            assets.doors,
            assets.tmflat,
            assets.tmobj,
            args,
            object_textures=assets.objects,
            animation_textures=assets.animo,
            common_objects=assets.common_objects,
            animations=assets.animations,
            models=assets.models,
            palette=assets.palette,
        )
        filename = render_output_filename(
            slot, level, "u7_style_noceilings", args.name_files
        )
        destination = output_path / filename
        image.save(destination)
        written.append(destination)
    return written


def _render_options(overrides: dict[str, object]) -> dict[str, object]:
    defaults: dict[str, object] = {
        "tile_size": 64,
        "lift_pixels": 4.0,
        "floor_height_per_lift": 8.0,
        "wall_height_scale": 1.0,
        "max_wall_height": 24.0,
        "no_obstruction_clip": False,
        "margin": 96,
        "background": "#08090b",
        "orientation": "display",
        "floor_texture_transform": "auto",
        "no_doors": False,
        "no_flat_objects": False,
        "no_objects": False,
        "tick": 0,
        "object_scale": 2.0,
        "no_models": False,
        "model_style": "icons",
        "model_icon_scale": 2.0,
        "model_scale": 1.0,
        "solid_fill": "none",
        "solid_fill_texture": "wall",
        "solid_fill_brightness": 0.42,
        "no_lighting": False,
        "min_brightness": 0.35,
        "debug_grid": False,
        "grid_label_step": 1,
        "grid_coordinate_mode": "display",
        "name_files": False,
    }
    defaults.update(overrides)
    return defaults


def _optional_archive_block(archive: ArkArchive, index: int) -> bytes | None:
    return archive.get_decoded_block(index) if archive.is_available(index) else None


def _optional_strings(path: Path) -> GameStrings | None:
    """Decode STRINGS.PAK when present; sign text is optional for rendering."""
    if not path.is_file():
        return None
    try:
        return GameStrings.from_file(path)
    except (OSError, ValueError, struct.error):
        return None


def _read_optional(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _write_block(path: Path, value: bytes) -> None:
    path.write_bytes(value)
