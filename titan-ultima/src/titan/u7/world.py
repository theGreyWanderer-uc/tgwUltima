"""
Interactive world-query wizard for Ultima 7.

Walks the user through filtering world objects by shape class, shape number,
TFA flags, and area, then reports matching placements from IFIX and IREG.

Entry points::

    from titan.u7.world import run_wizard
    exit_code = run_wizard(static_dir, gamedat_dir)

Or non-interactively::

    from titan.u7.world import run_query, WorldQueryParams
    result = run_query(params)
"""

from __future__ import annotations

__all__ = [
    "WorldQueryParams",
    "PlacementRecord",
    "WorldResult",
    "run_query",
    "run_wizard",
]

import csv
import io
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from titan.u7.map import (
    U7MapRenderer,
    U7MapObject,
    C_NUM_SCHUNKS,
    C_CHUNKS_PER_SCHUNK,
    C_TILES_PER_CHUNK,
)
from titan.u7.typeflag import U7TypeFlags
from titan.u7.names import U7ShapeNames, U7FrameNames
from titan.u7.shape_archive import find_archive
from titan.u7.ireg import object_flag_names


# ---------------------------------------------------------------------------
# Flag name → ShapeEntry property lookup
# ---------------------------------------------------------------------------

_FLAG_ACCESSORS: dict[str, str] = {
    "animated": "is_animated",
    "barge_part": "is_barge_part",
    "building": "is_building",
    "door": "is_door",
    "has_sfx": "has_sfx",
    "light_source": "is_light_source",
    "poisonous": "is_poisonous",
    "solid": "is_solid",
    "strange_movement": "has_strange_movement",
    "translucency": "has_translucency",
    "transparent": "is_transparent",
    "water": "is_water",
}

ALL_FLAG_NAMES: list[str] = sorted(_FLAG_ACCESSORS.keys())

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class WorldQueryParams:
    """All filters for a world-query run."""

    static_dir: str
    gamedat_dir: Optional[str] = None

    # Shape filtering
    shape_classes: list[int] = field(default_factory=list)  # empty = all
    shape_nums: list[int] = field(default_factory=list)  # empty = all
    frames: list[int] = field(default_factory=list)
    game: str = "bg"
    base_static: Optional[str] = None
    patch_dir: Optional[str] = None
    mod_data_dir: Optional[str] = None

    # TFA flag filtering (all must be true if multi-selected)
    tfa_flags: list[str] = field(default_factory=list)  # empty = all

    # Name filter — case-insensitive substring match; empty = all
    name_filter: str = ""

    # Path to TEXT.FLX for name lookup (optional)
    text_flx_path: Optional[str] = None

    # Area filtering — superchunk numbers (empty = all)
    superchunks: list[int] = field(default_factory=list)
    # Area filtering — tile rectangle (tx0, ty0, tx1, ty1); None = all
    tile_rect: Optional[tuple[int, int, int, int]] = None

    # Sources to scan
    include_ifix: bool = True
    include_ireg: bool = False

    # Map number: 0 = default world map, 1+ = mapNN/ subdirectory
    map_num: int = 0

    # Output format: "summary", "full_text", "csv"
    output_format: str = "summary"

    # Write to file instead of stdout
    output_path: Optional[str] = None


@dataclass
class PlacementRecord:
    """A single matching object placement."""

    tx: int
    ty: int
    tz: int
    shape: int
    frame: int
    quality: int
    source: str
    shape_class: int
    shape_class_name: str
    flags: list[str]
    shape_name: str = ""

    # Per-instance IREG object state (titan.u7.ireg): quality_raw is the
    # undecoded byte, quality is the normalized value (0 for quality_flags
    # class), object_flags names invisible/okay_to_take/temporary -- kept
    # separate from `flags` above, which are shared TFA shape flags.
    quality_raw: int = 0
    object_flags: list[str] = field(default_factory=list)

    def shape_label(self) -> str:
        """Return '522 (locked chest)' or just '522' if unnamed."""
        if self.shape_name:
            return f"{self.shape} ({self.shape_name})"
        return str(self.shape)


@dataclass
class WorldResult:
    """Collected results from a world-query run."""

    params: WorldQueryParams
    records: list[PlacementRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)


# ---------------------------------------------------------------------------
# Core query engine
# ---------------------------------------------------------------------------

TILE_MAX = C_NUM_SCHUNKS * C_CHUNKS_PER_SCHUNK * C_TILES_PER_CHUNK - 1


def parse_numbers(value: str, maximum: int, label: str) -> list[int]:
    """Parse a complete list, rejecting malformed tokens instead of dropping them."""
    if not value.strip():
        return []
    values = []
    for token in value.split(","):
        token = token.strip()
        try:
            number = (
                int(token, 16) if token.lower().startswith("0x") else int(token, 10)
            )
        except ValueError as error:
            raise ValueError(f"Invalid {label}: {token!r}") from error
        if not 0 <= number <= maximum:
            raise ValueError(f"{label} must be between 0 and {maximum}")
        if number not in values:
            values.append(number)
    return values


def parse_rectangle(value: str) -> tuple[int, int, int, int]:
    parts = value.split(",")
    if len(parts) != 4:
        raise ValueError("Tile rectangle must contain tx0,ty0,tx1,ty1")
    coords = [parse_numbers(part, TILE_MAX, "Tile coordinate") for part in parts]
    if any(len(part) != 1 for part in coords):
        raise ValueError("Each tile coordinate must be an integer")
    x0, y0, x1, y1 = (part[0] for part in coords)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def validate_params(params: WorldQueryParams, *, require_gamedat: bool = True) -> None:
    if params.game not in ("bg", "si"):
        raise ValueError("Game must be bg or si")
    for values, maximum, label in (
        (params.shape_nums, 65535, "Shape number"),
        (params.frames, 255, "Frame number"),
        (params.superchunks, C_NUM_SCHUNKS**2 - 1, "Superchunk"),
        ([params.map_num], 255, "Map number"),
    ):
        if any(type(n) is not int or not 0 <= n <= maximum for n in values):
            raise ValueError(f"{label} must be between 0 and {maximum}")
    if any(
        type(c) is not int or c not in U7TypeFlags.SHAPE_CLASS_NAMES
        for c in params.shape_classes
    ):
        raise ValueError("Unknown shape class")
    if any(f not in ALL_FLAG_NAMES for f in params.tfa_flags):
        raise ValueError("Unknown TFA flag; valid flags: " + ", ".join(ALL_FLAG_NAMES))
    if params.tile_rect is not None:
        if len(params.tile_rect) != 4 or any(
            type(n) is not int or not 0 <= n <= TILE_MAX for n in params.tile_rect
        ):
            raise ValueError(f"Tile coordinates must be between 0 and {TILE_MAX}")
        x0, y0, x1, y1 = params.tile_rect
        if x0 > x1 or y0 > y1:
            raise ValueError("Tile rectangle corners must be ordered")
    if params.output_format not in ("summary", "full_text", "csv"):
        raise ValueError("Output format must be summary, full_text, or csv")
    if not params.include_ifix and not params.include_ireg:
        raise ValueError("Select at least one source: IFIX or IREG")
    if require_gamedat and params.include_ireg and not params.gamedat_dir:
        raise ValueError("IREG search requires a GAMEDAT directory")


def resolve_world_sources(params: WorldQueryParams) -> tuple[Path, Optional[Path]]:
    """Resolve a base world and optional mod patch without modifying either."""
    if not params.static_dir and not params.base_static:
        raise ValueError("Provide a STATIC directory or configure one in titan.toml")
    selected = Path(params.static_dir or params.base_static or "").expanduser()
    patch = Path(params.patch_dir).expanduser() if params.patch_dir else None
    if (
        patch is None
        and params.base_static
        and selected.resolve() != Path(params.base_static).expanduser().resolve()
    ):
        patch = selected
    if patch is None and any(
        part.lower() in {"patch", "mods"} for part in selected.parts
    ):
        patch = selected
    base = Path(params.base_static).expanduser() if params.base_static else selected
    if patch is not None and base.resolve() == patch.resolve():
        candidates = [
            ancestor / name
            for ancestor in patch.resolve().parents
            for name in ("STATIC", "static")
        ]
        inferred = next(
            (p for p in candidates if p.is_dir() and p.resolve() != patch.resolve()),
            None,
        )
        if inferred is None:
            raise ValueError(
                "Cannot resolve the mod's base STATIC; supply --base-static"
            )
        base = inferred
    for label, directory in (
        ("STATIC", selected),
        ("Base STATIC", base),
        ("Patch", patch),
        (
            "Mod data",
            Path(params.mod_data_dir).expanduser() if params.mod_data_dir else None,
        ),
        (
            "GAMEDAT",
            Path(params.gamedat_dir).expanduser()
            if params.include_ireg and params.gamedat_dir
            else None,
        ),
    ):
        if directory is not None and not directory.is_dir():
            raise ValueError(f"{label} directory does not exist: {directory}")
    return base, patch


def _world_file(directory: Path, filename: str, map_num: int) -> Optional[Path]:
    if map_num:
        name = f"map{map_num:02x}"
        directory = next(
            (p for p in directory.iterdir() if p.is_dir() and p.name.lower() == name),
            directory / name,
        )
    return find_archive(directory, filename)


def load_query_metadata(
    params: WorldQueryParams,
) -> tuple[U7TypeFlags, Optional[U7ShapeNames], Optional[U7FrameNames], int]:
    base, patch = resolve_world_sources(params)

    def effective_file(name: str) -> Optional[Path]:
        return (find_archive(patch, name) if patch else None) or find_archive(
            base, name
        )

    blobs = []
    for name in ("TFA.DAT", "SHPDIMS.DAT", "WGTVOL.DAT", "OCCLUDE.DAT"):
        path = effective_file(name)
        blobs.append(path.read_bytes() if path else b"")
    tfa = U7TypeFlags.parse(*blobs)
    raw_tfa = blobs[0]
    # Retail TFA has an animation tail. Exult patch TFA can have >1024 records.
    patch_tfa = find_archive(patch, "TFA.DAT") if patch else None
    count = (
        len(raw_tfa) // 3
        if patch_tfa and len(raw_tfa) != 3584
        else min(len(raw_tfa), 3072) // 3
    )
    if patch_tfa and len(raw_tfa) != 3584 and len(raw_tfa) % 3:
        raise ValueError(f"Incomplete TFA shape record: {patch_tfa}")
    for index in range(1024, count):
        entry = U7TypeFlags.parse(raw_tfa[index * 3 : index * 3 + 3]).get(0)
        if entry is not None:
            entry.shape_num = index
            if index < len(tfa.entries):
                tfa.entries[index] = entry
            else:
                tfa.entries.append(entry)
            tfa._by_num[index] = entry
    # Auxiliary files may create entries without TFA: these are not known classes.
    for entry in tfa.entries[count:]:
        tfa._by_num.pop(entry.shape_num, None)

    text = (
        Path(params.text_flx_path).expanduser()
        if params.text_flx_path
        else effective_file("TEXT.FLX")
    )
    if text is not None and not text.is_file():
        raise ValueError(f"TEXT.FLX does not exist: {text}")
    names = U7ShapeNames.from_file(str(text)) if text else None
    frames = None
    mod_dirs = list(
        dict.fromkeys(
            str(p)
            for p in (
                patch,
                Path(params.mod_data_dir).expanduser() if params.mod_data_dir else None,
            )
            if p
        )
    )
    for mod_dir in mod_dirs:
        names = U7ShapeNames.from_mod_dir(mod_dir, base=names)
        if text:
            frames = U7FrameNames.from_mod_dir(mod_dir, str(text), base=frames)
    return tfa, names, frames, count


def run_query(params: WorldQueryParams) -> WorldResult:
    """Scan IFIX/IREG across the requested superchunks and return matches."""

    validate_params(params)
    static, patch = resolve_world_sources(params)
    tfa, shape_names, frame_names, tfa_count = load_query_metadata(params)
    if (params.shape_classes or params.tfa_flags) and not tfa_count:
        raise ValueError(
            "Cannot evaluate class/flag filters: TFA.DAT is missing or empty"
        )
    if params.name_filter and shape_names is None and frame_names is None:
        raise ValueError(
            "Cannot evaluate name filter: TEXT.FLX or mod names are required"
        )
    gamedat = Path(params.gamedat_dir).expanduser() if params.gamedat_dir else None

    # Which superchunks to scan
    total_sc = C_NUM_SCHUNKS * C_NUM_SCHUNKS
    if params.superchunks:
        sc_list = params.superchunks
    elif params.tile_rect:
        sc_list = _superchunks_for_rect(*params.tile_rect)
    else:
        sc_list = list(range(total_sc))

    result = WorldResult(params=params)
    if not tfa_count:
        result.warnings.append(
            "TFA.DAT is missing or empty; classes, flags and class-dependent IREG decoding are unavailable."
        )
    if shape_names is None:
        result.warnings.append(
            "Shape names are unavailable; numeric shape IDs are shown."
        )
    source_counts: Counter[str] = Counter()
    unknown_properties = 0
    unknown_names = 0
    without_properties = replace(params, shape_classes=[], tfa_flags=[])
    without_name = replace(params, name_filter="")

    for sc in sc_list:
        objects: list[U7MapObject] = []

        if params.include_ifix:
            ifix_name = f"U7IFIX{sc:02X}"
            ifix_path = (
                _world_file(patch, ifix_name, params.map_num) if patch else None
            ) or _world_file(static, ifix_name, params.map_num)
            if ifix_path is not None:
                source_counts["IFIX"] += 1
                for obj in U7MapRenderer.parse_ifix(str(ifix_path), sc):
                    obj.source = "ifix"
                    objects.append(obj)

        if params.include_ireg and gamedat:
            ireg_name = f"u7ireg{sc:02X}"
            ireg_path = _world_file(gamedat, ireg_name, params.map_num)
            if ireg_path is None and params.map_num == 0:
                ireg_path = find_archive(gamedat / "map00", ireg_name)
            if ireg_path is not None:
                source_counts["IREG"] += 1
                for obj in U7MapRenderer.parse_ireg(str(ireg_path), sc, tfa):
                    obj.source = "ireg"
                    objects.append(obj)

        for obj in objects:
            name = (
                frame_names.label(obj.shape, obj.frame, shape_names)
                if frame_names
                else shape_names.get(obj.shape)
                if shape_names
                else ""
            )
            if (
                params.name_filter
                and not name
                and _matches(obj, without_name, tfa, shape_names, frame_names)
            ):
                unknown_names += 1
            if (params.shape_classes or params.tfa_flags) and tfa.get(
                obj.shape
            ) is None:
                if _matches(obj, without_properties, tfa, shape_names, frame_names):
                    unknown_properties += 1
            if not _matches(obj, params, tfa, shape_names, frame_names):
                continue

            entry = tfa.get(obj.shape) if tfa else None
            sc_num = entry.shape_class if entry else 0
            sc_name_str = (
                U7TypeFlags.SHAPE_CLASS_NAMES.get(sc_num, f"unknown({sc_num})")
                if entry
                else "unknown"
            )
            flags = entry.flag_names() if entry else []
            result.records.append(
                PlacementRecord(
                    tx=obj.tx,
                    ty=obj.ty,
                    tz=obj.tz,
                    shape=obj.shape,
                    frame=obj.frame,
                    quality=obj.quality,
                    source=obj.source,
                    shape_class=sc_num,
                    shape_class_name=sc_name_str,
                    flags=flags,
                    shape_name=name,
                    quality_raw=obj.raw_quality,
                    object_flags=object_flag_names(obj.object_flags),
                )
            )

    for enabled, source in (
        (params.include_ifix, "IFIX"),
        (params.include_ireg, "IREG"),
    ):
        if enabled and not source_counts[source]:
            result.warnings.append(
                f"No {source} files found for map {params.map_num} in the selected area."
            )
    if unknown_properties:
        result.warnings.append(
            f"Excluded {unknown_properties} placement(s) with unavailable TFA properties from class/flag filtering."
        )
    if unknown_names:
        result.warnings.append(
            f"Excluded {unknown_names} placement(s) with unavailable names from name filtering."
        )
    return result


def _superchunks_for_rect(tx0: int, ty0: int, tx1: int, ty1: int) -> list[int]:
    """Return all superchunk numbers whose tile range overlaps the given rect."""
    sc_tiles = C_CHUNKS_PER_SCHUNK * C_TILES_PER_CHUNK  # 256 tiles/superchunk
    sc_x0 = tx0 // sc_tiles
    sc_x1 = tx1 // sc_tiles
    sc_y0 = ty0 // sc_tiles
    sc_y1 = ty1 // sc_tiles
    result: list[int] = []
    for sy in range(sc_y0, min(sc_y1 + 1, C_NUM_SCHUNKS)):
        for sx in range(sc_x0, min(sc_x1 + 1, C_NUM_SCHUNKS)):
            result.append(sy * C_NUM_SCHUNKS + sx)
    return result


def _matches(
    obj: U7MapObject,
    params: WorldQueryParams,
    tfa: Optional[U7TypeFlags],
    shape_names: Optional[U7ShapeNames] = None,
    frame_names: Optional[U7FrameNames] = None,
) -> bool:
    """Return True if obj passes all active filters."""

    if params.tile_rect:
        tx0, ty0, tx1, ty1 = params.tile_rect
        if not (tx0 <= obj.tx <= tx1 and ty0 <= obj.ty <= ty1):
            return False

    if params.shape_nums and obj.shape not in params.shape_nums:
        return False
    if params.frames and obj.frame not in params.frames:
        return False

    if params.name_filter:
        name = (
            frame_names.label(obj.shape, obj.frame, shape_names)
            if frame_names
            else shape_names.get(obj.shape)
            if shape_names
            else ""
        )
        if params.name_filter.lower() not in name.lower():
            return False

    entry = tfa.get(obj.shape) if tfa else None

    if params.shape_classes:
        if entry is None:
            return False
        sc = entry.shape_class if entry else 0
        if sc not in params.shape_classes:
            return False

    if params.tfa_flags:
        if entry is None:
            return False
        for flag_name in params.tfa_flags:
            attr = _FLAG_ACCESSORS.get(flag_name)
            if attr and not getattr(entry, attr, False):
                return False

    return True


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _format_summary(result: WorldResult) -> str:
    lines: list[str] = []
    lines.append(f"World query matched {result.count} placement(s).")
    if result.count == 0:
        return "\n".join(lines)

    # Group by shape
    by_shape: dict[int, list[PlacementRecord]] = {}
    for rec in result.records:
        by_shape.setdefault(rec.shape, []).append(rec)

    lines.append(f"Unique shapes: {len(by_shape)}")
    lines.append("")

    for shape_num in sorted(by_shape.keys()):
        recs = by_shape[shape_num]
        sample = recs[0]
        label = sample.shape_label()
        lines.append(
            f"  {label:<30}  0x{shape_num:04X}  "
            f"class={sample.shape_class_name:<14}  "
            f"count={len(recs)}"
        )

    return "\n".join(lines)


def _format_full_text(result: WorldResult) -> str:
    lines: list[str] = []
    lines.append(
        f"World query: {result.count} match(es)  "
        f"(ifix={sum(1 for r in result.records if r.source == 'ifix')}  "
        f"ireg={sum(1 for r in result.records if r.source == 'ireg')})"
    )
    lines.append("")

    for rec in result.records:
        flags_str = ", ".join(rec.flags) if rec.flags else "—"
        lines.append(
            f"  [{rec.source:4s}] {rec.shape_label():<30}  0x{rec.shape:04X}  "
            f"frame={rec.frame:3d}  "
            f"tile=({rec.tx},{rec.ty})  lift={rec.tz}  "
            f"class={rec.shape_class_name}"
        )
        if flags_str != "—":
            lines.append(f"         flags: {flags_str}")
        if rec.source == "ireg":
            lines.append(
                f"         quality_raw=0x{rec.quality_raw:02X}  "
                f"quality={rec.quality}  "
                f"flags={'|'.join(rec.object_flags) if rec.object_flags else '-'}"
            )

    return "\n".join(lines)


def _format_csv(result: WorldResult) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "source",
            "shape",
            "shape_hex",
            "shape_name",
            "frame",
            "quality",
            "quality_raw",
            "object_flags",
            "tx",
            "ty",
            "tz",
            "shape_class",
            "shape_class_name",
            "flags",
        ]
    )
    for rec in result.records:
        writer.writerow(
            [
                rec.source,
                rec.shape,
                f"0x{rec.shape:04X}",
                rec.shape_name,
                rec.frame,
                rec.quality,
                f"0x{rec.quality_raw:02X}",
                "|".join(rec.object_flags),
                rec.tx,
                rec.ty,
                rec.tz,
                rec.shape_class,
                rec.shape_class_name,
                "|".join(rec.flags),
            ]
        )
    return buf.getvalue()


def format_result(result: WorldResult) -> str:
    if result.params.output_format == "csv":
        return _format_csv(result)
    if result.params.output_format == "full_text":
        return _format_full_text(result)
    return _format_summary(result)


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------


def run_wizard(
    static_dir: Optional[str] = None,
    gamedat_dir: Optional[str] = None,
    text_flx: Optional[str] = None,
    *,
    game: str = "bg",
    map_num: int = 0,
    base_static: Optional[str] = None,
    patch_dir: Optional[str] = None,
    mod_data_dir: Optional[str] = None,
) -> int:
    """Launch the repeatable world-query workflow using the existing CLI context."""
    from titan.u7.world_workflow import run_wizard as workflow

    return workflow(
        WorldQueryParams(
            static_dir=static_dir or "",
            gamedat_dir=gamedat_dir,
            text_flx_path=text_flx,
            game=game,
            map_num=map_num,
            base_static=base_static,
            patch_dir=patch_dir,
            mod_data_dir=mod_data_dir,
            include_ireg=bool(gamedat_dir),
        )
    )
