"""
Ultima 7 egg scanner.

Scans IREG for egg objects (shape 275) and surfaces their trigger metadata:
type, usecode function number, probability, distance, criteria, and flags.

Entry points::

    from titan.u7.eggs import query_eggs, EggQueryParams
    results = query_eggs(params)

    from titan.u7.eggs import run_wizard
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
    "run_wizard",
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
    EGG_CRITERIA_NAMES,
    _EGG_SHAPE,
    C_NUM_SCHUNKS,
    C_CHUNKS_PER_SCHUNK,
    C_TILES_PER_CHUNK,
)
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
    egg_types: list[str] = field(default_factory=list)   # e.g. ["usecode", "monster"]
    fn_filter: Optional[int] = None                       # usecode function number
    superchunks: list[int] = field(default_factory=list)
    tile_rect: Optional[tuple[int, int, int, int]] = None

    # Output
    output_format: str = "table"   # "table" or "csv"
    output_path: Optional[str] = None


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
        ireg_path = gamedat / ireg_name
        if not ireg_path.exists():
            ireg_path = gamedat / "map00" / ireg_name
        if not ireg_path.exists():
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
            f"{m.distance:>4}  {m.criteria_name:<16}  {'  '.join(flags)}"
        )

    return "\n".join(lines) + "\n"


def format_csv(results: list[EggResult]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "sc", "tx", "ty", "tz",
        "egg_type", "egg_type_name",
        "fn",
        "probability", "distance",
        "criteria", "criteria_name",
        "once", "nocturnal", "auto_reset", "hatched",
        "data1", "data2",
    ])
    for res in results:
        m = res.meta
        writer.writerow([
            f"0x{res.superchunk:02X}",
            res.obj.tx, res.obj.ty, res.obj.tz,
            m.egg_type, m.type_name,
            f"0x{m.data2:04X}" if m.egg_type == 5 else "",
            m.probability, m.distance,
            m.criteria, m.criteria_name,
            int(m.once), int(m.nocturnal), int(m.auto_reset), int(m.hatched),
            m.data1, m.data2,
        ])
    return buf.getvalue()


def format_results(results: list[EggResult], params: EggQueryParams) -> str:
    if params.output_format == "csv":
        return format_csv(results)
    return format_table(results)


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------

def run_wizard(
    static_dir: Optional[str] = None,
    gamedat_dir: Optional[str] = None,
) -> int:
    """Interactive questionary egg-query wizard. Returns exit code."""
    try:
        import questionary
    except ImportError:
        print("questionary is required for the interactive wizard.")
        print("Install it with: pip install questionary>=2.0")
        return 1

    _SEP = "─" * 55
    print()
    print("  U7 Egg Query")
    print(f"  {_SEP}")

    # ── 1. Paths ─────────────────────────────────────────────────────────────
    if not static_dir:
        static_dir = questionary.path("STATIC directory:", only_directories=True).ask()
        if static_dir is None:
            return 0

    if not gamedat_dir:
        gamedat_dir = questionary.path("GAMEDAT directory:", only_directories=True).ask()
        if not gamedat_dir:
            return 0

    # ── 2. Egg type filter ────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    type_choices = [v for k, v in sorted(EGG_TYPE_NAMES.items()) if k < 128]
    selected_types: list[str] = questionary.checkbox(
        "Filter by egg type? (space to toggle, leave blank for all)",
        choices=type_choices,
    ).ask() or []
    if selected_types is None:
        return 0

    # ── 3. Usecode function filter ────────────────────────────────────────────
    fn_filter: Optional[int] = None
    if not selected_types or "usecode" in selected_types:
        print()
        print(f"  {_SEP}")
        fn_raw = questionary.text(
            "Filter by usecode function number? (hex or decimal, leave blank for all)",
            default="",
        ).ask()
        if fn_raw is None:
            return 0
        fn_raw = fn_raw.strip()
        if fn_raw:
            try:
                fn_filter = int(fn_raw, 0)
            except ValueError:
                print(f"  Invalid function number {fn_raw!r} — ignored.")

    # ── 4. Area ───────────────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    area_all = questionary.confirm("Search the entire world?", default=True).ask()
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
                "Superchunk numbers (hex or decimal, comma-separated):",
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
            ty0_raw = questionary.text("Top-left tile Y:").ask()
            tx1_raw = questionary.text("Bottom-right tile X:").ask()
            ty1_raw = questionary.text("Bottom-right tile Y:").ask()
            if None in (tx0_raw, ty0_raw, tx1_raw, ty1_raw):
                return 0
            try:
                tx0 = int(tx0_raw.strip(), 0)
                ty0 = int(ty0_raw.strip(), 0)
                tx1 = int(tx1_raw.strip(), 0)
                ty1 = int(ty1_raw.strip(), 0)
                tile_rect = (min(tx0, tx1), min(ty0, ty1), max(tx0, tx1), max(ty0, ty1))
            except ValueError:
                print("  Invalid coordinates — searching entire world.")

    # ── 5. Output ─────────────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    fmt = questionary.select(
        "Output format:",
        choices=["table", "csv"],
        default="table",
    ).ask()
    if fmt is None:
        return 0

    output_path: Optional[str] = None
    if questionary.confirm("Save output to a file?", default=False).ask():
        output_path = questionary.path("Output file path:").ask()

    # ── Run ───────────────────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    print("  Scanning…")

    params = EggQueryParams(
        static_dir=static_dir,
        gamedat_dir=gamedat_dir,
        egg_types=selected_types,
        fn_filter=fn_filter,
        superchunks=superchunks,
        tile_rect=tile_rect,
        output_format=fmt,
        output_path=output_path,
    )

    results = query_eggs(params)
    output = format_results(results, params)

    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        print(f"  Wrote {len(results)} egg(s) to {output_path}")
    else:
        print()
        print(output)

    return 0
