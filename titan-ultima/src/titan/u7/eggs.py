"""
Ultima 7 egg scanner.

Scans IREG for egg objects (shape 275) and surfaces their trigger metadata:
type, usecode function number, probability, distance, criteria, and flags.

Entry points::

    from titan.u7.eggs import query_eggs, EggQueryParams
    results = query_eggs(params)

    from titan.u7.eggs_ui import run_wizard
    exit_code = run_wizard(static_dir, gamedat_dir)
"""

from __future__ import annotations

__all__ = [
    "EggQueryParams",
    "EggResult",
    "query_eggs",
    "format_table",
    "format_csv",
    "format_results",
]

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from titan.u7.map import (
    U7MapRenderer,
    U7MapObject,
    EggMeta,
    EGG_TYPE_NAMES,
    _EGG_SHAPE,
    C_NUM_SCHUNKS,
)
from titan.u7.save import ALIGNMENT_NAMES, SCHEDULE_TYPE_NAMES
from titan.u7.typeflag import U7TypeFlags
from titan.u7.world import _superchunks_for_rect


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


@dataclass
class EggQueryParams:
    """Filters for an egg-query run."""

    static_dir: str
    gamedat_dir: str

    # Filters
    egg_types: list[str] = field(default_factory=list)  # e.g. ["usecode", "monster"]
    fn_filter: Optional[int] = None  # usecode function number
    superchunks: list[int] = field(default_factory=list)
    tile_rect: Optional[tuple[int, int, int, int]] = None

    # Output
    output_format: str = "table"  # "table" or "csv"
    output_path: Optional[str] = None
    patch_dir: Optional[str] = None
    map_num: int = 0


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class EggResult:
    """A single egg with its decoded metadata."""

    obj: U7MapObject
    superchunk: int

    @property
    def meta(self) -> EggMeta:
        return self.obj.egg_meta  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------


def query_eggs(params: EggQueryParams) -> list[EggResult]:
    """Scan IREG and return matching egg objects."""

    tfa: Optional[U7TypeFlags] = None
    try:
        tfa = U7TypeFlags.from_dir(params.static_dir)
    except (FileNotFoundError, OSError):
        pass

    gamedat = Path(params.gamedat_dir)
    if params.patch_dir:
        from titan.u7.world import WorldQueryParams, load_query_metadata

        tfa, _, _, _ = load_query_metadata(
            WorldQueryParams(
                static_dir=params.static_dir,
                base_static=params.static_dir,
                patch_dir=params.patch_dir,
            )
        )

    if params.superchunks:
        sc_list = params.superchunks
    elif params.tile_rect:
        sc_list = _superchunks_for_rect(*params.tile_rect)
    else:
        sc_list = list(range(C_NUM_SCHUNKS * C_NUM_SCHUNKS))

    # Build numeric type filter from names
    _name_to_type = {v: k for k, v in EGG_TYPE_NAMES.items()}
    type_filter: set[int] = {
        _name_to_type[n] for n in params.egg_types if n in _name_to_type
    }

    results: list[EggResult] = []

    for sc in sc_list:
        ireg_name = f"u7ireg{sc:02X}"
        from titan.u7.world import _world_file
        from titan.u7.shape_archive import find_archive

        ireg_path = _world_file(gamedat, ireg_name, params.map_num)
        if ireg_path is None and params.map_num == 0:
            ireg_path = find_archive(gamedat / "map00", ireg_name)
        if ireg_path is None:
            continue

        objects = U7MapRenderer.parse_ireg_deep(str(ireg_path), sc, tfa)

        for obj in objects:
            if obj.shape != _EGG_SHAPE or obj.egg_meta is None:
                continue

            meta = obj.egg_meta

            if type_filter and meta.egg_type not in type_filter:
                continue

            if params.fn_filter is not None:
                if meta.egg_type != 5 or meta.data2 != params.fn_filter:
                    continue

            if params.tile_rect:
                tx0, ty0, tx1, ty1 = params.tile_rect
                if not (tx0 <= obj.tx <= tx1 and ty0 <= obj.ty <= ty1):
                    continue

            results.append(EggResult(obj=obj, superchunk=sc))

    return results


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def format_table(results: list[EggResult]) -> str:
    lines: list[str] = [f"Egg query: {len(results)} egg(s) found.", ""]

    if not results:
        return "\n".join(lines)

    lines.append(
        f"  {'sc':<6}  {'tx':<6}  {'ty':<6}  {'tz':<4}  "
        f"{'type':<12}  {'fn':<8}  {'prob':>5}  {'dist':>4}  "
        f"{'criteria':<16}  flags"
    )
    lines.append("  " + "─" * 88)

    for res in results:
        m = res.meta
        fn_str = f"0x{m.data2:04X}" if m.egg_type == 5 else ""
        monster = ""
        if m.egg_type == 1:
            monster = (
                f"shape={m.monster_shape} frame={m.monster_frame} "
                f"count={m.monster_count}"
            )
        flags = []
        if m.once:
            flags.append("once")
        if m.nocturnal:
            flags.append("nocturnal")
        if m.auto_reset:
            flags.append("auto_reset")
        if m.hatched:
            flags.append("hatched")

        lines.append(
            f"  0x{res.superchunk:02X}  "
            f"{res.obj.tx:<6}  {res.obj.ty:<6}  {res.obj.tz:<4}  "
            f"{m.type_name:<12}  {fn_str:<8}  {m.probability:>4}%  "
            f"{m.distance:>4}  {m.criteria_name:<16}  "
            f"{monster:<30}  {'  '.join(flags)}"
        )

    return "\n".join(lines) + "\n"


def format_csv(results: list[EggResult]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "sc",
            "tx",
            "ty",
            "tz",
            "egg_type",
            "egg_type_name",
            "fn",
            "probability",
            "distance",
            "criteria",
            "criteria_name",
            "monster_shape",
            "monster_frame",
            "monster_count",
            "monster_schedule",
            "monster_schedule_name",
            "monster_alignment",
            "monster_alignment_name",
            "once",
            "nocturnal",
            "auto_reset",
            "hatched",
            "data1",
            "data2",
        ]
    )
    for res in results:
        m = res.meta
        writer.writerow(
            [
                f"0x{res.superchunk:02X}",
                res.obj.tx,
                res.obj.ty,
                res.obj.tz,
                m.egg_type,
                m.type_name,
                f"0x{m.data2:04X}" if m.egg_type == 5 else "",
                m.probability,
                m.distance,
                m.criteria,
                m.criteria_name,
                "" if m.monster_shape is None else m.monster_shape,
                "" if m.monster_frame is None else m.monster_frame,
                "" if m.monster_count is None else m.monster_count,
                "" if m.monster_schedule is None else m.monster_schedule,
                (
                    ""
                    if m.monster_schedule is None
                    else SCHEDULE_TYPE_NAMES.get(
                        m.monster_schedule, f"?{m.monster_schedule}"
                    )
                ),
                "" if m.monster_alignment is None else m.monster_alignment,
                (
                    ""
                    if m.monster_alignment is None
                    else ALIGNMENT_NAMES.get(
                        m.monster_alignment, f"?{m.monster_alignment}"
                    )
                ),
                int(m.once),
                int(m.nocturnal),
                int(m.auto_reset),
                int(m.hatched),
                m.data1,
                m.data2,
            ]
        )
    return buf.getvalue()


def format_results(results: list[EggResult], params: EggQueryParams) -> str:
    if params.output_format == "csv":
        return format_csv(results)
    return format_table(results)


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------
