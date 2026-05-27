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
import os
from dataclasses import dataclass, field
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
from titan.u7.names import U7ShapeNames


# ---------------------------------------------------------------------------
# Flag name → ShapeEntry property lookup
# ---------------------------------------------------------------------------

_FLAG_ACCESSORS: dict[str, str] = {
    "animated":         "is_animated",
    "barge_part":       "is_barge_part",
    "building":         "is_building",
    "door":             "is_door",
    "has_sfx":          "has_sfx",
    "light_source":     "is_light_source",
    "poisonous":        "is_poisonous",
    "solid":            "is_solid",
    "strange_movement": "has_strange_movement",
    "translucency":     "has_translucency",
    "transparent":      "is_transparent",
    "water":            "is_water",
}

ALL_FLAG_NAMES: list[str] = sorted(_FLAG_ACCESSORS.keys())

# ---------------------------------------------------------------------------
# Shape class options (matches U7TypeFlags.SHAPE_CLASS_NAMES)
# ---------------------------------------------------------------------------

_SHAPE_CLASS_OPTIONS: dict[str, int] = {
    name: code
    for code, name in U7TypeFlags.SHAPE_CLASS_NAMES.items()
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class WorldQueryParams:
    """All filters for a world-query run."""

    static_dir: str
    gamedat_dir: Optional[str] = None

    # Shape filtering
    shape_classes: list[int] = field(default_factory=list)   # empty = all
    shape_nums: list[int] = field(default_factory=list)       # empty = all

    # TFA flag filtering (all must be true if multi-selected)
    tfa_flags: list[str] = field(default_factory=list)        # empty = all

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
    include_ireg: bool = True

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

    @property
    def count(self) -> int:
        return len(self.records)


# ---------------------------------------------------------------------------
# Core query engine
# ---------------------------------------------------------------------------

def run_query(params: WorldQueryParams) -> WorldResult:
    """Scan IFIX/IREG across the requested superchunks and return matches."""

    tfa: Optional[U7TypeFlags] = None
    try:
        tfa = U7TypeFlags.from_dir(params.static_dir)
    except (FileNotFoundError, OSError):
        pass

    shape_names: Optional[U7ShapeNames] = None
    if params.text_flx_path:
        try:
            shape_names = U7ShapeNames.from_file(params.text_flx_path)
        except (FileNotFoundError, OSError):
            pass
    if shape_names is None:
        shape_names = U7ShapeNames.from_static_dir(params.static_dir)

    static = Path(params.static_dir)
    gamedat = Path(params.gamedat_dir) if params.gamedat_dir else None

    # Which superchunks to scan
    total_sc = C_NUM_SCHUNKS * C_NUM_SCHUNKS
    if params.superchunks:
        sc_list = params.superchunks
    elif params.tile_rect:
        sc_list = _superchunks_for_rect(*params.tile_rect)
    else:
        sc_list = list(range(total_sc))

    result = WorldResult(params=params)

    for sc in sc_list:
        objects: list[U7MapObject] = []

        if params.include_ifix:
            ifix_name = f"U7IFIX{sc:02X}"
            if params.map_num > 0:
                ifix_dir = static / f"map{params.map_num:02x}"
                ifix_path = ifix_dir / ifix_name
                if not ifix_path.exists():
                    ifix_path = ifix_dir / ifix_name.lower()
            else:
                ifix_path = static / ifix_name
                if not ifix_path.exists():
                    ifix_path = static / ifix_name.lower()
            if ifix_path.exists():
                for obj in U7MapRenderer.parse_ifix(str(ifix_path), sc):
                    obj.source = "ifix"
                    objects.append(obj)

        if params.include_ireg and gamedat:
            ireg_name = f"u7ireg{sc:02X}"
            if params.map_num > 0:
                ireg_path = gamedat / f"map{params.map_num:02x}" / ireg_name
            else:
                ireg_path = gamedat / ireg_name
                if not ireg_path.exists():
                    ireg_path = gamedat / "map00" / ireg_name
            if ireg_path.exists():
                for obj in U7MapRenderer.parse_ireg(str(ireg_path), sc):
                    obj.source = "ireg"
                    objects.append(obj)

        for obj in objects:
            if not _matches(obj, params, tfa, shape_names):
                continue

            entry = tfa.get(obj.shape) if tfa else None
            sc_num = entry.shape_class if entry else 0
            sc_name_str = (
                U7TypeFlags.SHAPE_CLASS_NAMES.get(sc_num, f"unknown({sc_num})")
                if entry else "unknown"
            )
            flags = entry.flag_names() if entry else []
            name = shape_names.get(obj.shape) if shape_names else ""

            result.records.append(PlacementRecord(
                tx=obj.tx, ty=obj.ty, tz=obj.tz,
                shape=obj.shape, frame=obj.frame, quality=obj.quality,
                source=obj.source,
                shape_class=sc_num,
                shape_class_name=sc_name_str,
                flags=flags,
                shape_name=name,
            ))

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
) -> bool:
    """Return True if obj passes all active filters."""

    if params.tile_rect:
        tx0, ty0, tx1, ty1 = params.tile_rect
        if not (tx0 <= obj.tx <= tx1 and ty0 <= obj.ty <= ty1):
            return False

    if params.shape_nums and obj.shape not in params.shape_nums:
        return False

    if params.name_filter:
        name = shape_names.get(obj.shape) if shape_names else ""
        if params.name_filter.lower() not in name.lower():
            return False

    entry = tfa.get(obj.shape) if tfa else None

    if params.shape_classes:
        sc = entry.shape_class if entry else 0
        if sc not in params.shape_classes:
            return False

    if params.tfa_flags and entry is not None:
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
        f"(ifix={sum(1 for r in result.records if r.source=='ifix')}  "
        f"ireg={sum(1 for r in result.records if r.source=='ireg')})"
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

    return "\n".join(lines)


def _format_csv(result: WorldResult) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow([
        "source", "shape", "shape_hex", "shape_name", "frame", "quality",
        "tx", "ty", "tz", "shape_class", "shape_class_name", "flags",
    ])
    for rec in result.records:
        writer.writerow([
            rec.source,
            rec.shape,
            f"0x{rec.shape:04X}",
            rec.shape_name,
            rec.frame,
            rec.quality,
            rec.tx,
            rec.ty,
            rec.tz,
            rec.shape_class,
            rec.shape_class_name,
            "|".join(rec.flags),
        ])
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
) -> int:
    """Interactive questionary-based world-query wizard. Returns exit code."""
    try:
        import questionary
    except ImportError:
        print("questionary is required for the interactive wizard.")
        print("Install it with: pip install questionary>=2.0")
        return 1

    _SEPARATOR = "─" * 55

    print()
    print("  U7 World Query")
    print(f"  {_SEPARATOR}")

    # ── 1. Paths ────────────────────────────────────────────────────────────
    if not static_dir:
        static_dir = questionary.path(
            "STATIC directory:",
            only_directories=True,
        ).ask()
        if static_dir is None:
            return 0

    # ── 2. Shape class filter ───────────────────────────────────────────────
    print()
    print(f"  {_SEPARATOR}")
    class_choices = _build_checkbox_choices(
        list(U7TypeFlags.SHAPE_CLASS_NAMES.values()),
        all_label="(all shape classes)",
    )
    selected_classes_raw: list[str] = questionary.checkbox(
        "Filter by shape class? (space to toggle, leave blank for none, enter to confirm)",
        choices=class_choices,
    ).ask()
    if selected_classes_raw is None:
        return 0

    if "(all shape classes)" in selected_classes_raw or not selected_classes_raw:
        shape_classes: list[int] = []
    else:
        shape_classes = [
            _SHAPE_CLASS_OPTIONS[name]
            for name in selected_classes_raw
            if name in _SHAPE_CLASS_OPTIONS
        ]

    # Warn if only IREG-only classes were selected without IREG
    _IREG_ONLY_CLASSES = {
        U7TypeFlags.SHAPE_CLASS_CONTAINER,
        U7TypeFlags.SHAPE_CLASS_EGG,
        U7TypeFlags.SHAPE_CLASS_MONSTER,
        U7TypeFlags.SHAPE_CLASS_HUMAN,
    }
    _ireg_only_selected = (
        shape_classes
        and all(c in _IREG_ONLY_CLASSES for c in shape_classes)
    )

    ireg_default = bool(gamedat_dir) or _ireg_only_selected
    ireg_prompt = "Include IREG (dynamic / runtime objects)?"
    if _ireg_only_selected:
        print()
        print("  Note: containers, NPCs, eggs, and monsters are IREG-only.")

    use_ireg = questionary.confirm(
        ireg_prompt,
        default=ireg_default,
    ).ask()
    if use_ireg is None:
        return 0

    if use_ireg and not gamedat_dir:
        gamedat_dir = questionary.path(
            "GAMEDAT directory (or leave blank to skip):",
            only_directories=True,
        ).ask()
        if gamedat_dir == "":
            gamedat_dir = None
            use_ireg = False

    # ── 3. Shape filter (number or name) ───────────────────────────────────
    print()
    print(f"  {_SEPARATOR}")

    # Try to load names now so we can offer name search and show hints
    _names: Optional[U7ShapeNames] = None
    if text_flx:
        try:
            _names = U7ShapeNames.from_file(text_flx)
        except (FileNotFoundError, OSError):
            pass
    if _names is None and static_dir:
        _names = U7ShapeNames.from_static_dir(static_dir)

    name_filter = ""
    shape_nums: list[int] = []

    name_input = questionary.text(
        "Search by name? (substring, leave blank to skip)",
        default="",
    ).ask()
    if name_input is None:
        return 0
    name_filter = name_input.strip()

    # Show matching shape numbers as a hint when TEXT.FLX is available
    if name_filter and _names:
        matches = _names.find_shapes(name_filter)
        if matches:
            hint = ", ".join(
                f"{n} ({_names.get(n)})" for n in matches[:8]
            )
            suffix = f"  …+{len(matches)-8} more" if len(matches) > 8 else ""
            print(f"  Matching shapes: {hint}{suffix}")
        else:
            print("  No shapes found with that name.")

    shape_input = questionary.text(
        "Filter by shape number(s)? (comma-separated, or leave blank for all)",
        default="",
    ).ask()
    if shape_input is None:
        return 0

    if shape_input.strip():
        for token in shape_input.split(","):
            token = token.strip()
            try:
                shape_nums.append(int(token, 0))
            except ValueError:
                pass

    # ── 4. TFA flag filter ──────────────────────────────────────────────────
    print()
    print(f"  {_SEPARATOR}")
    flag_choices = _build_checkbox_choices(
        ALL_FLAG_NAMES,
        all_label="(all TFA flags)",
    )
    selected_flags_raw: list[str] = questionary.checkbox(
        "Filter by TFA flag? (space to toggle, leave blank for none, enter to confirm)",
        choices=flag_choices,
    ).ask()
    if selected_flags_raw is None:
        return 0

    if "(all TFA flags)" in selected_flags_raw or not selected_flags_raw:
        tfa_flags: list[str] = []
    else:
        tfa_flags = [f for f in selected_flags_raw if f in _FLAG_ACCESSORS]

    # ── 5. Area filter ──────────────────────────────────────────────────────
    print()
    print(f"  {_SEPARATOR}")
    area_all = questionary.confirm(
        "Search the entire world? (no = specify area)",
        default=True,
    ).ask()
    if area_all is None:
        return 0

    superchunks: list[int] = []
    tile_rect: Optional[tuple[int, int, int, int]] = None

    if not area_all:
        area_type = questionary.select(
            "Area filter type:",
            choices=["Superchunks", "Tile rectangle"],
        ).ask()
        if area_type is None:
            return 0

        if area_type == "Superchunks":
            sc_input = questionary.text(
                "Superchunk numbers (hex or decimal, comma-separated, e.g. 0x55,0x56):",
                default="",
            ).ask()
            if sc_input is None:
                return 0
            for token in sc_input.split(","):
                token = token.strip()
                try:
                    superchunks.append(int(token, 0))
                except ValueError:
                    pass

        else:
            _TILE_MAX = C_NUM_SCHUNKS * C_CHUNKS_PER_SCHUNK * C_TILES_PER_CHUNK - 1
            print(f"  Tile coordinates are 0–{_TILE_MAX} on each axis.")
            tx0_raw = questionary.text("Top-left tile X:").ask()
            if tx0_raw is None:
                return 0
            ty0_raw = questionary.text("Top-left tile Y:").ask()
            if ty0_raw is None:
                return 0
            tx1_raw = questionary.text("Bottom-right tile X:").ask()
            if tx1_raw is None:
                return 0
            ty1_raw = questionary.text("Bottom-right tile Y:").ask()
            if ty1_raw is None:
                return 0
            try:
                tx0 = max(0, int(tx0_raw.strip(), 0))
                ty0 = max(0, int(ty0_raw.strip(), 0))
                tx1 = min(_TILE_MAX, int(tx1_raw.strip(), 0))
                ty1 = min(_TILE_MAX, int(ty1_raw.strip(), 0))
                # Normalise so top-left is always the smaller coordinate
                tile_rect = (min(tx0, tx1), min(ty0, ty1), max(tx0, tx1), max(ty0, ty1))
            except ValueError:
                print("  Invalid tile coordinates — searching entire world.")
                tile_rect = None

    # ── 6. Output format ────────────────────────────────────────────────────
    print()
    print(f"  {_SEPARATOR}")
    fmt_choice = questionary.select(
        "Output format:",
        choices=["summary", "full_text", "csv"],
        default="summary",
    ).ask()
    if fmt_choice is None:
        return 0

    output_path: Optional[str] = None
    save_to_file = questionary.confirm(
        "Save output to a file?",
        default=False,
    ).ask()
    if save_to_file is None:
        return 0
    if save_to_file:
        output_path = questionary.path(
            "Output file path:",
        ).ask()
        if output_path is None:
            return 0

    # ── Run ──────────────────────────────────────────────────────────────────
    print()
    print(f"  {_SEPARATOR}")
    print("  Running query…")

    params = WorldQueryParams(
        static_dir=static_dir,
        gamedat_dir=gamedat_dir if use_ireg else None,
        shape_classes=shape_classes,
        shape_nums=shape_nums,
        name_filter=name_filter,
        text_flx_path=text_flx,
        tfa_flags=tfa_flags,
        superchunks=superchunks,
        tile_rect=tile_rect,
        include_ifix=True,
        include_ireg=use_ireg,
        output_format=fmt_choice,
        output_path=output_path,
    )

    result = run_query(params)
    output = format_result(result)

    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        print(f"  Wrote {result.count} result(s) to {output_path}")
    else:
        print()
        print(output)

    return 0


def _build_checkbox_choices(
    names: list[str],
    all_label: str,
) -> list:
    """Build a questionary choices list with an 'all' option at the bottom."""
    try:
        from questionary import Choice, Separator
    except ImportError:
        return names + [all_label]

    items: list = [Choice(name) for name in names]
    items.append(Separator())
    items.append(Choice(all_label))
    return items
