"""
Ultima 7 — CLI sub-app.

Registered as ``titan u7 <command>`` in the root CLI.
Commands for Ultima 7: The Black Gate and Serpent Isle.
"""

from __future__ import annotations

__all__ = ["u7_app"]

import csv
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer
from titan._config import get_config

u7_app = typer.Typer(
    name="u7",
    help="Ultima 7 — The Black Gate / Serpent Isle commands.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _resolve_u7_paths(game: str) -> tuple[Optional[str], Optional[str]]:
    """Resolve STATIC and palette paths from multi-game config for BG/SI."""
    cfg = get_config() or {}
    section_key = "u7bg" if game.lower() == "bg" else "u7si"
    section = cfg.get(section_key, {}) if isinstance(cfg, dict) else {}
    game_cfg = section.get("game", {}) if isinstance(section, dict) else {}
    paths_cfg = section.get("paths", {}) if isinstance(section, dict) else {}

    base = game_cfg.get("base") if isinstance(game_cfg, dict) else None
    base_path = Path(str(base)).expanduser() if base else None

    def _abs_from_cfg(value: object) -> Optional[str]:
        if not value:
            return None
        p = Path(str(value)).expanduser()
        if p.is_absolute() or base_path is None:
            return str(p)
        return str(base_path / p)

    static = _abs_from_cfg(paths_cfg.get("static"))
    palette = _abs_from_cfg(paths_cfg.get("palette"))

    # Reasonable fallback if only base was configured.
    if static is None and base_path is not None:
        static = str(base_path / "STATIC")
    if palette is None and static is not None:
        palette = str(Path(static) / "PALETTES.FLX")

    return static, palette


def _resolve_u7_text_flx(game: str, static_dir: Optional[str] = None) -> Optional[str]:
    """Resolve TEXT.FLX path from config, with fallback to STATIC dir."""
    cfg = get_config() or {}
    section_key = "u7bg" if game.lower() == "bg" else "u7si"
    section = cfg.get(section_key, {}) if isinstance(cfg, dict) else {}
    game_cfg = section.get("game", {}) if isinstance(section, dict) else {}
    paths_cfg = section.get("paths", {}) if isinstance(section, dict) else {}

    base = game_cfg.get("base") if isinstance(game_cfg, dict) else None
    base_path = Path(str(base)).expanduser() if base else None

    configured = paths_cfg.get("text") if isinstance(paths_cfg, dict) else None
    if configured:
        p = Path(str(configured)).expanduser()
        if p.is_absolute() or base_path is None:
            candidate = p
        else:
            candidate = base_path / p
        if candidate.exists():
            return str(candidate)

    # Fall back to STATIC directory discovery
    search_dirs: list[Path] = []
    if static_dir:
        search_dirs.append(Path(static_dir))
    if base_path:
        search_dirs.append(base_path / "STATIC")
    for d in search_dirs:
        for name in ("TEXT.FLX", "text.flx"):
            p = d / name
            if p.exists():
                return str(p)
    return None


def _resolve_u7_gamedat(game: str) -> Optional[str]:
    """Resolve loose GAMEDAT path from multi-game config for BG/SI."""
    cfg = get_config() or {}
    section_key = "u7bg" if game.lower() == "bg" else "u7si"
    section = cfg.get(section_key, {}) if isinstance(cfg, dict) else {}
    game_cfg = section.get("game", {}) if isinstance(section, dict) else {}
    paths_cfg = section.get("paths", {}) if isinstance(section, dict) else {}

    base = game_cfg.get("base") if isinstance(game_cfg, dict) else None
    base_path = Path(str(base)).expanduser() if base else None

    configured = paths_cfg.get("gamedat") if isinstance(paths_cfg, dict) else None
    if configured:
        path = Path(str(configured)).expanduser()
        if path.is_absolute() or base_path is None:
            return str(path)
        return str(base_path / path)

    if base_path is not None:
        for name in ("gamedat", "GAMEDAT"):
            candidate = base_path / name
            if candidate.is_dir():
                return str(candidate)
    return None


def _resolve_u7_exult_flx(game: str) -> Optional[str]:
    """Resolve installed Exult per-game FLX bundle path."""
    from titan._config import exult_cfg

    game_key = "bg" if game.lower() == "bg" else "si"
    configured = exult_cfg(f"{game_key}_flx")
    if configured and Path(configured).is_file():
        return configured

    flx_name = f"exult_{game_key}.flx"
    candidates: list[Path] = []
    for drive in ("C", "D"):
        candidates.extend(
            [
                Path(f"{drive}:\\Program Files\\Exult\\data") / flx_name,
                Path(f"{drive}:\\Program Files (x86)\\Exult\\data") / flx_name,
                Path(f"{drive}:\\Program Files\\Exult") / flx_name,
                Path(f"{drive}:\\Program Files (x86)\\Exult") / flx_name,
            ]
        )
    candidates.extend(
        [
            Path("/usr/share/exult") / flx_name,
            Path("/usr/local/share/exult") / flx_name,
            Path("/opt/exult") / flx_name,
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _resolve_ucxt_intrinsics_data(
    game: str,
    intrinsics_data: str | None = None,
) -> Optional[str]:
    """Resolve optional UCXT intrinsic-name table for U7 raw usecode output."""
    if intrinsics_data and Path(intrinsics_data).is_file():
        return intrinsics_data
    game_key = game.lower()
    filename = "u7bgintrinsics.data" if game_key == "bg" else "u7siintrinsics.data"
    candidates: list[Path] = []
    for drive in ("C", "D"):
        candidates.extend(
            [
                Path(f"{drive}:\\Program Files\\Exult\\Tools\\data") / filename,
                Path(f"{drive}:\\Program Files (x86)\\Exult\\Tools\\data") / filename,
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _exult_profile_root() -> Optional[Path]:
    """Return the standard per-user Exult profile root, if it exists."""
    local_appdata = os.getenv("LOCALAPPDATA")
    if not local_appdata:
        return None
    root = Path(local_appdata) / "Exult"
    return root if root.is_dir() else None


def _exult_game_slug(game: str) -> str:
    return "blackgate" if game.lower() == "bg" else "serpentisle"


def _resolve_u7_mod_gamedat(game: str, mod: Optional[str]) -> Optional[str]:
    """Resolve per-user Exult runtime GAMEDAT for a base game or mod."""
    cfg = get_config() or {}
    section_key = "u7bg" if game.lower() == "bg" else "u7si"
    section = cfg.get(section_key, {}) if isinstance(cfg, dict) else {}
    game_cfg = section.get("game", {}) if isinstance(section, dict) else {}
    mods_cfg = section.get("mods", {}) if isinstance(section, dict) else {}
    if mod and isinstance(mods_cfg, dict):
        mod_cfg = mods_cfg.get(mod, {})
        if isinstance(mod_cfg, dict):
            paths_cfg = mod_cfg.get("paths", {})
            if isinstance(paths_cfg, dict):
                configured = paths_cfg.get("gamedat")
                if configured:
                    path = Path(str(configured)).expanduser()
                    if (path / "npc.dat").is_file():
                        return str(path)

    root = _exult_profile_root()
    if root is None:
        return None
    base = root / _exult_game_slug(game)
    candidate = base / "gamedat" if not mod else base / "mods" / mod / "gamedat"
    if (candidate / "npc.dat").is_file():
        return str(candidate)

    base_path = game_cfg.get("base") if isinstance(game_cfg, dict) else None
    if mod and base_path:
        install_candidate = Path(str(base_path)).expanduser() / "mods" / mod / "gamedat"
        if (install_candidate / "npc.dat").is_file():
            return str(install_candidate)
    return None


def _resolve_u7_mod_archive(game: str, mod: Optional[str]) -> Optional[str]:
    """Resolve configured Exult mod archive data, such as patch/initgame.dat."""
    if not mod:
        return None
    cfg = get_config() or {}
    section_key = "u7bg" if game.lower() == "bg" else "u7si"
    section = cfg.get(section_key, {}) if isinstance(cfg, dict) else {}
    game_cfg = section.get("game", {}) if isinstance(section, dict) else {}
    mods_cfg = section.get("mods", {}) if isinstance(section, dict) else {}
    mod_cfg = mods_cfg.get(mod, {}) if isinstance(mods_cfg, dict) else {}
    paths_cfg = mod_cfg.get("paths", {}) if isinstance(mod_cfg, dict) else {}
    archive = paths_cfg.get("archive") if isinstance(paths_cfg, dict) else None
    if archive:
        path = Path(str(archive)).expanduser()
        if path.is_file():
            return str(path)
    base_path = game_cfg.get("base") if isinstance(game_cfg, dict) else None
    if base_path:
        mod_root = Path(str(base_path)).expanduser() / "mods" / mod
        for candidate in (
            mod_root / "patch" / "initgame.dat",
            mod_root / "data" / "initgame.dat",
        ):
            if candidate.is_file():
                return str(candidate)
    return None


def _resolve_loose_data_file(path: str, filename: str) -> str:
    """Resolve either a direct file path or a directory containing *filename*."""
    candidate = Path(path)
    if candidate.is_dir():
        candidate = candidate / filename
    return str(candidate)


def _infer_static_dir_for_data_file(filepath: str) -> str | None:
    """Infer a sibling STATIC directory from a loose GAMEDAT file path."""
    parent = Path(filepath).resolve().parent
    candidates = [
        parent.with_name("STATIC"),
        parent.parent / "STATIC",
    ]
    for candidate in candidates:
        if (candidate / "TFA.DAT").is_file() or (candidate / "tfa.dat").is_file():
            return str(candidate)
    return None


def _load_container_shapes(
    args: SimpleNamespace,
    fallback_static: str | None = None,
) -> set[int] | None:
    """Load TFA container shape IDs for reliable NPC inventory skipping."""
    static_dir = getattr(args, "static", None)
    if not static_dir:
        static_dir, _ = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not static_dir:
        static_dir = fallback_static
    if static_dir:
        from titan.u7.typeflag import U7TypeFlags

        tfa = U7TypeFlags.from_dir(static_dir)
        container_shapes = {
            entry.shape_num for entry in tfa.entries if entry.shape_class == 6
        }
        print(f"TFA:    {len(container_shapes)} container shapes loaded")
        return container_shapes

    print("TFA:    (no --static, using heuristic container detection)")
    return None


def _load_shape_count(
    args: SimpleNamespace,
    fallback_static: str | None = None,
) -> int | None:
    """Load SHAPES.VGA record count for filtering non-shape pseudo IDs."""
    static_dir = getattr(args, "static", None)
    if not static_dir:
        static_dir, _ = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not static_dir:
        static_dir = fallback_static
    if not static_dir:
        return None

    from titan.u7.flex import U7FlexArchive

    for name in ("SHAPES.VGA", "shapes.vga"):
        path = Path(static_dir) / name
        if path.is_file():
            return len(U7FlexArchive.from_file(str(path)).records)
    return None


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — PALETTE
# ============================================================================


def cmd_palette_export(args: SimpleNamespace) -> int:
    """Export palette(s) from PALETTES.FLX or a .pal file."""
    from titan.u7.palette import U7Palette

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or "palettes"
    os.makedirs(outdir, exist_ok=True)

    slots = U7Palette.enumerate_slots(filepath)
    count = len(slots)
    encoding = getattr(args, "encoding", None) or "auto"

    if args.index is not None:
        if args.index < 0 or args.index >= count:
            print(
                f"ERROR: Palette index {args.index} out of range "
                f"(file has {count} slots)",
                file=sys.stderr,
            )
            return 1
        indices = [args.index]
    else:
        for s in slots:
            if s.is_empty:
                print(f"  Skipping palette {s.index}: empty slot")
            elif not s.is_valid:
                print(f"  Skipping palette {s.index}: {s.error}")
        indices = [s.index for s in slots if not s.is_empty and s.is_valid]

    base = Path(filepath).stem
    exported = 0

    for idx in indices:
        try:
            pal = U7Palette.from_file(filepath, palette_index=idx, encoding=encoding)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        tag = f"{base}_pal{idx:02d}" if count > 1 else base

        img_path = os.path.join(outdir, f"{tag}_swatch.png")
        img = pal.to_pil_image(swatch_size=16)
        img.save(img_path)
        print(f"Swatch saved: {img_path}")

        txt_path = os.path.join(outdir, f"{tag}.txt")
        with open(txt_path, "w") as f:
            f.write(pal.to_text())
            f.write("\n")
        print(f"  Text saved: {txt_path}")
        exported += 1

    print(f"Exported {exported} palette(s) to {outdir}/")
    return 0


def _palette_inspection_rows(filepath: str) -> list[dict]:
    """One row per Flex slot: occupancy, validity, semantic name, and
    (for populated/valid slots) decoded encoding."""
    from titan.u7.palette import U7Palette
    from titan.u7.palette_semantics import palette_slot_name

    rows: list[dict] = []
    for slot in U7Palette.enumerate_slots(filepath):
        row = {
            "index": slot.index,
            "offset": slot.offset,
            "length": slot.length,
            "is_empty": slot.is_empty,
            "is_valid": slot.is_valid,
            "error": slot.error or "",
            "name": palette_slot_name(slot.index) or "",
            "encoding": "",
        }
        if not slot.is_empty and slot.is_valid:
            try:
                pal = U7Palette.from_file(filepath, palette_index=slot.index)
                row["encoding"] = pal.encoding
            except ValueError:
                pass
        rows.append(row)
    return rows


def _palette_info_text(filepath: str, rows: list[dict], detail: bool) -> str:
    from titan.u7.palette_semantics import CYCLE_RANGES

    lines = [f"{filepath}: {len(rows)} slot(s), {sum(1 for r in rows if not r['is_empty'])} populated"]
    for row in rows:
        if not detail and row["is_empty"]:
            continue
        name = f" ({row['name']})" if row["name"] else ""
        enc = f" [{row['encoding']}]" if row["encoding"] else ""
        if row["is_empty"]:
            status = "empty"
        elif not row["is_valid"]:
            status = f"invalid: {row['error']}"
        else:
            status = "ok"
        prefix = (
            f"  slot {row['index']:2d}: offset=0x{row['offset']:06x} length={row['length']:4d} "
            if detail
            else f"  {row['index']:2d}: "
        )
        lines.append(f"{prefix}{status}{name}{enc}")

    if detail:
        lines.append("")
        lines.append("Colour-cycling ranges (apply to every populated palette; see titan.u7.palette_cycle):")
        for r in CYCLE_RANGES:
            lines.append(f"  {r.name:8s} {r.start:3d}-{r.end:3d}")

    return "\n".join(lines)


def cmd_palette_info(args: SimpleNamespace) -> int:
    """Inspect a PALETTES.FLX archive: slot occupancy, semantic names,
    encoding, and colour-cycling ranges."""
    from titan.u7.palette_semantics import CYCLE_RANGES

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    fmt = getattr(args, "format", None) or "summary"
    rows = _palette_inspection_rows(filepath)

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
        content = buf.getvalue()
    elif fmt == "json":
        content = json.dumps(
            {
                "slots": rows,
                "cycle_ranges": [
                    {"name": r.name, "start": r.start, "end": r.end} for r in CYCLE_RANGES
                ],
            },
            indent=2,
        )
    else:
        content = _palette_info_text(filepath, rows, detail=(fmt == "detail"))

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"Palette info written to: {args.output}")
    else:
        print(content)

    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — SHAPE
# ============================================================================


def _load_translucent_bg_indices(path: str, num_frames: int) -> "list | None":
    """Load an indexed ('P' mode) PNG produced by ``--indexed`` and reuse
    its pixel-index array as the exact-compositing background for every
    frame.  Returns ``None`` (with a printed error) if the file isn't
    already palette-indexed -- this command doesn't attempt to quantize
    an arbitrary RGB image down to indices."""
    import numpy as np
    from PIL import Image

    img = Image.open(path)
    if img.mode != "P":
        print(
            f"ERROR: --translucent-bg file must be a palette-indexed ('P' "
            f"mode) PNG, e.g. produced by --indexed; got mode {img.mode!r}",
            file=sys.stderr,
        )
        return None
    arr = np.array(img)
    return [arr] * num_frames


def cmd_shape_export(args: SimpleNamespace) -> int:
    """Export frames from a U7 shape to PNG."""
    from titan.u7.shape import U7Shape
    from titan.u7.palette import U7Palette
    from titan.u7.flex import U7FlexArchive

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    # Load palette
    if args.palette:
        pal = U7Palette.from_file(args.palette)
    else:
        pal = U7Palette.default_palette()

    translucency = None
    if getattr(args, "translucent", False) or getattr(args, "translucent_bg", None):
        if not getattr(args, "static", None):
            print(
                "ERROR: --static DIR is required (with --translucent or "
                "--translucent-bg) to load real XFORM.TBL/BLENDS.DAT data",
                file=sys.stderr,
            )
            return 1
        from titan.u7.translucency import U7Translucency

        translucency = U7Translucency.from_dir(args.static)

    # Determine if file is a Flex archive (VGA) or standalone .shp.
    is_flex = U7FlexArchive.is_u7_flex(filepath)

    if is_flex:
        if args.shape is None:
            print(
                "ERROR: --shape N is required when the input is a VGA "
                "Flex archive (e.g. SHAPES.VGA).",
                file=sys.stderr,
            )
            return 1
        archive = U7FlexArchive.from_file(filepath)
        shape_idx = args.shape
        num_records = len(archive.records)
        if shape_idx < 0 or shape_idx >= num_records:
            print(
                f"ERROR: Shape index {shape_idx} out of range "
                f"(archive has {num_records} records)",
                file=sys.stderr,
            )
            return 1
        rec = archive.get_record(shape_idx)
        if not rec:
            print(f"ERROR: Shape {shape_idx} is empty", file=sys.stderr)
            return 1
        from titan.u7.shape import FIRST_OBJ_SHAPE

        shape = U7Shape.from_data(rec, is_tile=(shape_idx < FIRST_OBJ_SHAPE))
        name = f"shape_{shape_idx:04d}"
    else:
        shape = U7Shape.from_file(filepath)
        name = Path(filepath).stem

    if not shape.frames:
        print(f"WARNING: No frames found in {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or name
    os.makedirs(outdir, exist_ok=True)

    if args.frame is not None:
        if args.frame < 0 or args.frame >= len(shape.frames):
            print(
                f"ERROR: Frame {args.frame} out of range "
                f"(shape has {len(shape.frames)} frames)",
                file=sys.stderr,
            )
            return 1
        frames_to_export = [(args.frame, shape.frames[args.frame])]
    else:
        frames_to_export = list(enumerate(shape.frames))

    indexed = getattr(args, "indexed", False)
    cycle_phase_ms = getattr(args, "cycle_phase", 0) or 0
    is_translucent = getattr(args, "translucent", False)
    translucent_bg_path = getattr(args, "translucent_bg", None)

    exact_background = None
    if translucent_bg_path:
        exact_background = _load_translucent_bg_indices(translucent_bg_path, len(shape.frames))
        if exact_background is None:
            return 1
        is_translucent = True

    if (cycle_phase_ms or is_translucent) and not indexed:
        print(
            "NOTE: RGBA export flattens palette cycling/translucency state "
            "into fixed colours; original pixel indices are not preserved. "
            "Use --indexed to keep exact index values.",
            file=sys.stderr,
        )

    images = shape.to_pngs(
        pal,
        indexed=indexed,
        cycle_phase_ms=cycle_phase_ms,
        has_translucency=is_translucent,
        translucency=translucency,
        exact_background=exact_background,
    )

    for idx, _frame in frames_to_export:
        img = images[idx]
        out_path = os.path.join(outdir, f"{name}_f{idx:04d}.png")
        img.save(out_path)

    print(f"Exported {len(frames_to_export)} frame(s) from {name} to {outdir}/")
    return 0


# LCM of the six colour-cycle range lengths (8,8,4,4,4,3) -- the number of
# 100ms ticks for every cycling range to simultaneously return to its
# original alignment (see titan.u7.palette_cycle).
_CYCLE_FULL_WRAP_STEPS = 24


def cmd_shape_animate(args: SimpleNamespace) -> int:
    """Render a shape's animation (frame-sequence or palette-cycle) to an
    animated GIF."""
    from titan.u7.palette import U7Palette
    from titan.u7.shape import U7Shape, FIRST_OBJ_SHAPE
    from titan.u7.flex import U7FlexArchive
    from titan.u7.shape_animation import (
        TICK_MS,
        default_animation_for_tfa,
        has_cycle_pixels,
        save_gif,
        simulate_frame_sequence,
    )

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    pal = U7Palette.from_file(args.palette) if args.palette else U7Palette.default_palette()

    is_flex = U7FlexArchive.is_u7_flex(filepath)
    if is_flex:
        if args.shape is None:
            print(
                "ERROR: --shape N is required when the input is a VGA "
                "Flex archive (e.g. SHAPES.VGA).",
                file=sys.stderr,
            )
            return 1
        archive = U7FlexArchive.from_file(filepath)
        rec = archive.get_record(args.shape)
        if not rec:
            print(f"ERROR: Shape {args.shape} is empty", file=sys.stderr)
            return 1
        shape = U7Shape.from_data(rec, is_tile=(args.shape < FIRST_OBJ_SHAPE))
        name = f"shape_{args.shape:04d}"
    else:
        shape = U7Shape.from_file(filepath)
        name = Path(filepath).stem

    if not shape.frames:
        print(f"WARNING: No frames found in {filepath}", file=sys.stderr)
        return 1

    target_frame = args.frame or 0
    if target_frame < 0 or target_frame >= len(shape.frames):
        print(
            f"ERROR: Frame {target_frame} out of range "
            f"(shape has {len(shape.frames)} frames)",
            file=sys.stderr,
        )
        return 1

    translucency = None
    if args.static:
        from titan.u7.translucency import U7Translucency

        translucency = U7Translucency.from_dir(args.static)

    anim = None
    is_translucent = False
    if args.static and args.shape is not None:
        from titan.u7.typeflag import U7TypeFlags

        tfa = U7TypeFlags.from_dir(args.static)
        entry = tfa.get(args.shape)
        if entry is not None:
            anim = default_animation_for_tfa(entry.anim_type, len(shape.frames))
            # Real per-shape TFA flag -- NOT the same thing as "this frame
            # happens to contain pixels in the 224-254 cycle range" (checked
            # below via has_cycle_pixels). Indices 238-254 are dual-purpose:
            # plain colour cycling on an ordinary shape, but a translucency
            # blend override on one flagged translucent (see
            # titan.u7.translucency). Passing the wrong one here would make
            # a merely-cycling shape's colours freeze at a static blend
            # preview instead of actually animating.
            is_translucent = entry.has_translucency

    mode = args.mode or "auto"
    if mode == "auto":
        mode = "frames" if anim is not None else "cycle"

    outpath = args.output or f"{name}.gif"

    if mode == "frames":
        if anim is None:
            print(
                "ERROR: --mode frames requires --static DIR and --shape N "
                "resolving to a TFA-animated shape (see u7 typeflag-dump)",
                file=sys.stderr,
            )
            return 1

        images = shape.to_pngs(pal)
        default_steps = 24 if anim.ani_type.name == "HOURLY" else anim.nframes
        steps = args.steps or default_steps
        frame_indices = simulate_frame_sequence(anim, 0, steps, hour_start=args.hour_start or 0)
        gif_frames = [images[i] for i in frame_indices if 0 <= i < len(images)]
        default_duration = 200 if anim.ani_type.name == "HOURLY" else TICK_MS * anim.frame_delay
        duration = args.duration or default_duration
        print(f"Animating {name}: {anim.ani_type.name.lower()} frame sequence, "
              f"{len(gif_frames)} steps @ {duration}ms")
    else:
        if not has_cycle_pixels(shape.frames[target_frame].pixels):
            print(
                f"NOTE: frame {target_frame} has no colour-cycling pixels; "
                "the animation will look static.",
                file=sys.stderr,
            )
        steps = args.steps or _CYCLE_FULL_WRAP_STEPS
        duration = args.duration or TICK_MS
        gif_frames = []
        for step in range(steps):
            imgs = shape.to_pngs(
                pal,
                cycle_phase_ms=step * TICK_MS,
                has_translucency=is_translucent,
                translucency=translucency if is_translucent else None,
            )
            gif_frames.append(imgs[target_frame])
        label = " (translucency-composited)" if is_translucent else ""
        print(f"Animating {name} frame {target_frame}: colour-cycle preview{label}, "
              f"{steps} steps @ {duration}ms")

    if not gif_frames:
        print("ERROR: No frames produced for animation", file=sys.stderr)
        return 1

    save_gif(gif_frames, outpath, duration_ms=duration)
    print(f"Saved animated GIF: {outpath}")
    return 0


def cmd_shape_batch(args: SimpleNamespace) -> int:
    """Batch-export shapes from a VGA Flex archive to PNG."""
    from titan.u7.shape import U7Shape, FIRST_OBJ_SHAPE
    from titan.u7.palette import U7Palette
    from titan.u7.flex import U7FlexArchive

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    # Load palette
    if args.palette:
        pal = U7Palette.from_file(args.palette)
    else:
        pal = U7Palette.default_palette()

    archive = U7FlexArchive.from_file(filepath)
    base = Path(filepath).stem

    outdir = args.output or f"{base}_png"
    os.makedirs(outdir, exist_ok=True)

    num_records = len(archive.records)
    start = args.range_start if args.range_start is not None else 0
    end = args.range_end if args.range_end is not None else num_records

    indexed = getattr(args, "indexed", False)
    cycle_phase_ms = getattr(args, "cycle_phase", 0) or 0
    if cycle_phase_ms and not indexed:
        print(
            "NOTE: RGBA export flattens palette cycling state into fixed "
            "colours; original pixel indices are not preserved. Use "
            "--indexed to keep exact index values.",
            file=sys.stderr,
        )

    total_frames = 0
    total_shapes = 0

    for shape_idx in range(start, min(end, num_records)):
        rec = archive.get_record(shape_idx)
        if not rec:
            continue

        shape = U7Shape.from_data(rec, is_tile=(shape_idx < FIRST_OBJ_SHAPE))
        if not shape.frames:
            continue

        images = shape.to_pngs(pal, indexed=indexed, cycle_phase_ms=cycle_phase_ms)
        shape_dir = os.path.join(outdir, f"{shape_idx:04d}")
        os.makedirs(shape_dir, exist_ok=True)

        for fi, img in enumerate(images):
            out_path = os.path.join(shape_dir, f"{shape_idx:04d}_f{fi:04d}.png")
            img.save(out_path)

        total_shapes += 1
        total_frames += len(images)

    print(f"Exported {total_frames} frame(s) from {total_shapes} shape(s) to {outdir}/")
    return 0


def _resolved_animation_fields(anim) -> dict:
    """Descriptor columns for a shape's resolved animation parameters
    (type, frame count used, recycle, freeze chance, frame delay) --
    not just a boolean, so a client can reproduce the actual timing.
    Empty/None fields when the shape isn't actually frame-animated."""
    if anim is None:
        return {
            "resolved_ani_type": None,
            "resolved_nframes": None,
            "recycle": None,
            "freeze_first_chance": None,
            "frame_delay": None,
        }
    return {
        "resolved_ani_type": anim.ani_type.name.lower(),
        "resolved_nframes": anim.nframes,
        "recycle": anim.recycle,
        "freeze_first_chance": anim.freeze_first_chance,
        "frame_delay": anim.frame_delay,
    }


def cmd_shape_cycle_scan(args: SimpleNamespace) -> int:
    """Scan a VGA archive for colour-cycling/translucency/frame-animation
    content; export indexed frames and a descriptor for every affected
    shape."""
    from titan.u7.flex import U7FlexArchive
    from titan.u7.names import U7ShapeNames
    from titan.u7.palette import U7Palette
    from titan.u7.shape import U7Shape, FIRST_OBJ_SHAPE
    from titan.u7.shape_cycle_scan import scan_shape
    from titan.u7.translucency import U7Translucency
    from titan.u7.typeflag import U7TypeFlags

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1
    if not args.static:
        print(
            "ERROR: --static DIR is required for TFA animation-type and "
            "translucency lookup",
            file=sys.stderr,
        )
        return 1

    archive = U7FlexArchive.from_file(filepath)
    tfa = U7TypeFlags.from_dir(args.static)
    translucency = U7Translucency.from_dir(args.static)
    xfstart = translucency.xfstart if translucency.num_slots else 238
    names = U7ShapeNames.from_static_dir(args.static)

    pal = U7Palette.from_file(args.palette) if args.palette else U7Palette.default_palette()

    outdir = args.output or "shape_cycle_scan"
    os.makedirs(outdir, exist_ok=True)

    num_records = len(archive.records)
    start = args.range_start if args.range_start is not None else 0
    end = args.range_end if args.range_end is not None else num_records

    reports = []
    for shnum in range(start, min(end, num_records)):
        rec = archive.get_record(shnum)
        if not rec:
            continue
        shape = U7Shape.from_data(rec, is_tile=(shnum < FIRST_OBJ_SHAPE))
        if not shape.frames:
            continue

        name = names.get(shnum) if names else ""
        report = scan_shape(shape, shnum, tfa, xfstart=xfstart, name=name)
        if not report.is_affected:
            continue
        reports.append(report)

        shape_dir = os.path.join(outdir, f"{shnum:04d}")
        os.makedirs(shape_dir, exist_ok=True)
        for fi, img in enumerate(shape.to_pngs(pal, indexed=True)):
            img.save(os.path.join(shape_dir, f"{shnum:04d}_f{fi:04d}.png"))

    rows = [
        {
            "shape": r.shape_num,
            "name": r.name,
            "frame_count": r.frame_count,
            "is_tile_shape": r.is_tile_shape,
            "is_animated": r.is_animated,
            "anim_type": r.anim_type,
            "anim_type_name": r.anim_type_name,
            **_resolved_animation_fields(r.resolved_animation),
            "is_translucent": r.is_translucent,
            "has_any_cycle": r.has_any_cycle,
            "has_any_translucency": r.has_any_translucency,
            "cycle_frame_indices": sorted(r.cycle_frame_indices),
            "translucent_frame_indices": sorted(r.translucent_frame_indices),
            "cycle_indices": sorted(r.all_cycle_indices),
            "translucent_indices": sorted(r.all_translucent_indices),
            "index_255_frame_indices": sorted(r.index_255_frame_indices),
        }
        for r in reports
    ]

    fmt = args.format or "json"
    desc_path = os.path.join(outdir, f"descriptor.{fmt}")
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
        with open(desc_path, "w", newline="") as f:
            f.write(buf.getvalue())
    else:
        with open(desc_path, "w") as f:
            json.dump(rows, f, indent=2)

    translucent_n = sum(1 for r in reports if r.is_translucent)
    animated_n = sum(1 for r in reports if r.has_frame_animation)
    cycle_n = sum(1 for r in reports if r.has_any_cycle and not r.is_translucent)
    print(
        f"Scanned {min(end, num_records) - start} shape(s): {len(reports)} affected "
        f"({translucent_n} translucent, {animated_n} frame-animated, "
        f"{cycle_n} colour-cycling non-translucent)"
    )
    print(f"Indexed frames + {desc_path} written to {outdir}/")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — MUSIC
# ============================================================================


def cmd_music_export(args: SimpleNamespace) -> int:
    """Extract music tracks from a U7 music Flex archive to MIDI."""
    from titan.u7.music import extract_music, convert_xmidi_file

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_midi"
    os.makedirs(outdir, exist_ok=True)
    target = (args.target or "mt32").lower()

    # Check if this is a standalone XMIDI file (e.g. ENDSCORE.XMI)
    with open(filepath, "rb") as f:
        magic = f.read(4)

    if magic == b"FORM":
        ok = convert_xmidi_file(filepath, outdir, target=target)
        if ok:
            flavor = "General MIDI" if target == "gm" else "MT-32 MIDI"
            print(f"Converted XMIDI to {flavor} in {outdir}/")
            return 0
        else:
            print("ERROR: Failed to convert XMIDI file", file=sys.stderr)
            return 1

    # Otherwise treat as a Flex archive containing MIDI / XMIDI records
    count = extract_music(filepath, outdir, target=target)
    ext = ".MID"
    flavor = "General MIDI" if target == "gm" else "MT-32 MIDI"
    print(f"Extracted {count} {flavor} track(s) as {ext} to {outdir}/")
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — VOC / SPEECH
# ============================================================================


def cmd_voc_export(args: SimpleNamespace) -> int:
    """Decode a Creative Voice (.voc) file to WAV."""
    from titan.u7.sound import VocDecoder

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)

    base = Path(filepath).stem
    out_path = os.path.join(outdir, f"{base}.wav")
    VocDecoder.to_wav(filepath, out_path)

    with open(filepath, "rb") as f:
        data = f.read()
    pcm, rate = VocDecoder.decode(data)
    duration = len(pcm) / rate if rate else 0

    print(f"Decoded VOC to WAV: {out_path}")
    print(
        f"  Sample rate: {rate} Hz, duration: {duration:.1f}s, size: {len(pcm):,} bytes"
    )
    return 0


def cmd_speech_export(args: SimpleNamespace) -> int:
    """Extract and decode all speech from a U7 speech Flex archive."""
    from titan.u7.sound import VocDecoder
    from titan.u7.flex import U7FlexArchive

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or f"{Path(filepath).stem}_wav"

    # Check if this is a single VOC file or a Flex archive
    with open(filepath, "rb") as f:
        header = f.read(max(VOC_HEADER_CHECK, 0x60))

    if VocDecoder.is_voc(header):
        # Single VOC file
        os.makedirs(outdir, exist_ok=True)
        base = Path(filepath).stem
        out_path = os.path.join(outdir, f"{base}.wav")
        VocDecoder.to_wav(filepath, out_path)
        print(f"Decoded 1 VOC file to {outdir}/")
        return 0

    # Flex archive — extract and decode each VOC record
    archive = U7FlexArchive.from_file(filepath)
    os.makedirs(outdir, exist_ok=True)

    decoded = 0
    skipped = 0

    for idx, rec in enumerate(archive.records):
        if not rec:
            continue

        if VocDecoder.is_voc(rec):
            out_path = os.path.join(outdir, f"{idx:04d}.wav")
            VocDecoder.to_wav(filepath, out_path, data=rec)
            decoded += 1
        else:
            # Non-VOC record — save raw (might be text transcripts etc.)
            ext = ".txt" if _looks_like_text(rec) else ".dat"
            out_path = os.path.join(outdir, f"{idx:04d}{ext}")
            with open(out_path, "wb") as f:
                f.write(rec)
            skipped += 1

    print(f"Decoded {decoded} VOC file(s) to WAV in {outdir}/")
    if skipped:
        print(f"  ({skipped} non-VOC record(s) saved as raw)")
    return 0


# 26 bytes needed to check VOC magic
VOC_HEADER_CHECK = 26


def _looks_like_text(data: bytes) -> bool:
    """Heuristic: check if data is likely ASCII text."""
    if not data:
        return False
    # Check first 64 bytes for printable ASCII
    sample = data[:64]
    return all((0x20 <= b <= 0x7E) or b in (0x0A, 0x0D, 0x09) for b in sample)


# ============================================================================
# TYPER COMMAND WRAPPERS
# ============================================================================

# ---- palette ---------------------------------------------------------------


@u7_app.command("palette-export")
def palette_export_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to PALETTES.FLX or a standalone .pal file")
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    index: Annotated[
        Optional[int],
        typer.Option("--index", help="Export only this palette index (default: all)"),
    ] = None,
    encoding: Annotated[
        Literal["auto", "6bit", "8bit"],
        typer.Option(
            "--encoding",
            help="Component encoding: auto-detect (default), or force 6-bit/8-bit",
        ),
    ] = "auto",
) -> None:
    """Export palettes from PALETTES.FLX as PNG colour swatches and text dumps."""
    raise SystemExit(
        cmd_palette_export(
            SimpleNamespace(
                file=file,
                output=output,
                index=index,
                encoding=encoding,
            )
        )
    )


@u7_app.command("palette-info")
def palette_info_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to PALETTES.FLX or a standalone .pal file")
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write info dump to this file"),
    ] = None,
    format: Annotated[
        Literal["summary", "detail", "csv", "json"],
        typer.Option(
            "-f", "--format",
            help="Output format: summary (default), detail, csv, json",
        ),
    ] = "summary",
) -> None:
    """Inspect a PALETTES.FLX archive: slot occupancy, semantic names,
    raw encoding, and colour-cycling ranges -- without exporting any files."""
    raise SystemExit(
        cmd_palette_info(
            SimpleNamespace(
                file=file,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("shape-export")
def shape_export_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to .shp file or VGA Flex archive (e.g. SHAPES.VGA)"),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to PALETTES.FLX or .pal file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    shape: Annotated[
        Optional[int],
        typer.Option("--shape", help="Shape index (required when input is a VGA Flex)"),
    ] = None,
    frame: Annotated[
        Optional[int],
        typer.Option("--frame", help="Export only this frame number"),
    ] = None,
    indexed: Annotated[
        bool,
        typer.Option(
            "--indexed",
            help="Preserve palette indices ('P'-mode PNG) instead of flattening to RGBA",
        ),
    ] = False,
    cycle_phase: Annotated[
        int,
        typer.Option(
            "--cycle-phase",
            help="Preview the palette rotated to this elapsed time in milliseconds",
        ),
    ] = 0,
    translucent: Annotated[
        bool,
        typer.Option(
            "--translucent",
            help="Treat this shape as TFA-translucent (shape-export has no "
            "STATIC dir to look this up automatically -- assert it explicitly)",
        ),
    ] = False,
    translucent_bg: Annotated[
        Optional[str],
        typer.Option(
            "--translucent-bg",
            help="Indexed ('P'-mode) PNG background for exact translucency "
            "compositing (implies --translucent); without it, translucent "
            "pixels use the approximate RGBA preview blend colour",
        ),
    ] = None,
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static",
            help="STATIC directory to load real XFORM.TBL/BLENDS.DAT from "
            "(required together with --translucent or --translucent-bg)",
        ),
    ] = None,
) -> None:
    """Export frames from a U7 shape file to PNG."""
    raise SystemExit(
        cmd_shape_export(
            SimpleNamespace(
                file=file,
                palette=palette,
                output=output,
                shape=shape,
                frame=frame,
                indexed=indexed,
                cycle_phase=cycle_phase,
                translucent=translucent,
                translucent_bg=translucent_bg,
                static=static,
            )
        )
    )


@u7_app.command("shape-animate")
def shape_animate_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to .shp file or VGA Flex archive (e.g. SHAPES.VGA)"),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to PALETTES.FLX or .pal file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output .gif path (default: <name>.gif)"),
    ] = None,
    shape: Annotated[
        Optional[int],
        typer.Option(
            "--shape",
            help="Shape index (required for VGA input; also used as the TFA "
            "shape number for --mode frames/auto when --static is given)",
        ),
    ] = None,
    frame: Annotated[
        Optional[int],
        typer.Option("--frame", help="Frame to animate in --mode cycle (default: 0)"),
    ] = None,
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static",
            help="STATIC directory for TFA animation-type lookup and real "
            "XFORM.TBL/BLENDS.DAT translucency data",
        ),
    ] = None,
    mode: Annotated[
        Literal["auto", "frames", "cycle"],
        typer.Option(
            "--mode",
            help="auto (default): use TFA frame-sequence animation if --static "
            "resolves one, else colour-cycle preview. frames/cycle force one.",
        ),
    ] = "auto",
    steps: Annotated[
        Optional[int],
        typer.Option("--steps", help="Number of animation steps (default depends on mode/type)"),
    ] = None,
    duration: Annotated[
        Optional[int],
        typer.Option("--duration", help="Milliseconds per GIF frame (default depends on mode/type)"),
    ] = None,
    hour_start: Annotated[
        Optional[int],
        typer.Option("--hour-start", help="Starting in-game hour for HOURLY-type animations"),
    ] = None,
) -> None:
    """Render a shape's frame-sequence or palette-cycle animation to an
    animated GIF."""
    raise SystemExit(
        cmd_shape_animate(
            SimpleNamespace(
                file=file,
                palette=palette,
                output=output,
                shape=shape,
                frame=frame,
                static=static,
                mode=mode,
                steps=steps,
                duration=duration,
                hour_start=hour_start,
            )
        )
    )


@u7_app.command("shape-batch")
def shape_batch_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to a VGA Flex archive (e.g. SHAPES.VGA, FACES.VGA)"),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to PALETTES.FLX or .pal file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First shape index to export (default: 0)"),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last shape index (exclusive; default: all)"),
    ] = None,
    indexed: Annotated[
        bool,
        typer.Option(
            "--indexed",
            help="Preserve palette indices ('P'-mode PNG) instead of flattening to RGBA",
        ),
    ] = False,
    cycle_phase: Annotated[
        int,
        typer.Option(
            "--cycle-phase",
            help="Preview the palette rotated to this elapsed time in milliseconds",
        ),
    ] = 0,
) -> None:
    """Batch-export shapes from a VGA Flex archive to PNG."""
    raise SystemExit(
        cmd_shape_batch(
            SimpleNamespace(
                file=file,
                palette=palette,
                output=output,
                range_start=range_start,
                range_end=range_end,
                indexed=indexed,
                cycle_phase=cycle_phase,
            )
        )
    )


@u7_app.command("shape-cycle-scan")
def shape_cycle_scan_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to a VGA Flex archive (e.g. SHAPES.VGA)"),
    ],
    static: Annotated[
        str,
        typer.Option(
            "--static",
            help="STATIC directory for TFA animation-type and real "
            "XFORM.TBL/BLENDS.DAT translucency lookup (required)",
        ),
    ],
    palette: Annotated[
        Optional[str],
        typer.Option("-p", "--palette", help="Path to PALETTES.FLX or .pal file"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: shape_cycle_scan/)"),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First shape index to scan (default: 0)"),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last shape index (exclusive; default: all)"),
    ] = None,
    format: Annotated[
        Literal["json", "csv"],
        typer.Option("-f", "--format", help="Descriptor format: json (default) or csv"),
    ] = "json",
) -> None:
    """Scan a VGA archive for colour-cycling, translucency, and TFA
    frame-animation content, exporting indexed frames plus a descriptor
    for every affected shape."""
    raise SystemExit(
        cmd_shape_cycle_scan(
            SimpleNamespace(
                file=file,
                static=static,
                palette=palette,
                output=output,
                range_start=range_start,
                range_end=range_end,
                format=format,
            )
        )
    )


# ---- music -----------------------------------------------------------------


@u7_app.command("music-export")
def music_export_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to a U7 music archive (ADLIBMUS.DAT, MT32MUS.DAT) "
            "or standalone XMIDI file (ENDSCORE.XMI)"
        ),
    ],
    target: Annotated[
        Literal["mt32", "gm"],
        typer.Option(
            "--target",
            help="Export target: original MT-32 MIDI (.MID) or "
            "General MIDI rewrite (.MID)",
            case_sensitive=False,
        ),
    ] = "mt32",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract U7 music tracks from a Flex archive to MIDI files."""
    raise SystemExit(
        cmd_music_export(
            SimpleNamespace(
                file=file,
                output=output,
                target=target,
            )
        )
    )


# ---- voc / speech ----------------------------------------------------------


@u7_app.command("voc-export")
def voc_export_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to a Creative Voice (.voc) file (e.g. INTROSND.DAT)"),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Decode a Creative Voice (.voc) file to WAV."""
    raise SystemExit(
        cmd_voc_export(
            SimpleNamespace(
                file=file,
                output=output,
            )
        )
    )


@u7_app.command("speech-export")
def speech_export_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to U7SPEECH.SPC (Flex of VOC records) or a single VOC file"
        ),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Extract and decode U7 speech from a Flex archive of VOC files to WAV."""
    raise SystemExit(
        cmd_speech_export(
            SimpleNamespace(
                file=file,
                output=output,
            )
        )
    )


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — MAP
# ============================================================================


def _parse_hex_rgba(color: str) -> tuple[int, int, int, int]:
    """Parse #RRGGBB or #RRGGBBAA into RGBA tuple."""
    txt = color.strip()
    if txt.startswith("#"):
        txt = txt[1:]

    if len(txt) not in (6, 8):
        raise ValueError(f"Color '{color}' must be #RRGGBB or #RRGGBBAA.")

    try:
        r = int(txt[0:2], 16)
        g = int(txt[2:4], 16)
        b = int(txt[4:6], 16)
        a = int(txt[6:8], 16) if len(txt) == 8 else 255
    except ValueError as exc:
        raise ValueError(f"Color '{color}' is not valid hex.") from exc

    return (r, g, b, a)


def _parse_highlight_tile_rect(
    value: str,
) -> tuple[int, int, int, int, tuple[int, int, int, int], str]:
    """Parse tx0,ty0,tx1,ty1,#RRGGBB[AA][,label] into a typed tuple."""
    parts = [p.strip() for p in value.split(",", 5)]
    if len(parts) not in (5, 6):
        raise ValueError("Expected 'tx0,ty0,tx1,ty1,#RRGGBB[,label]' (or #RRGGBBAA).")

    try:
        tx0 = int(parts[0], 10)
        ty0 = int(parts[1], 10)
        tx1 = int(parts[2], 10)
        ty1 = int(parts[3], 10)
    except ValueError as exc:
        raise ValueError(f"Tile coordinates must be integers in '{value}'.") from exc

    rgba = _parse_hex_rgba(parts[4])
    default_label = f"{tx0},{ty0},{tx1},{ty1}"
    label = parts[5] if len(parts) == 6 and parts[5] else default_label
    return (tx0, ty0, tx1, ty1, rgba, label)


def cmd_map_render(args: SimpleNamespace) -> int:
    """Render a U7 map region (superchunk, chunk range, or full world) to PNG."""
    from titan.u7.map import U7MapRenderer, U7TileRectOverlay
    from titan.u7.palette import U7Palette

    static_dir = args.static
    if not static_dir:
        static_dir, _ = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}", file=sys.stderr)
        return 1

    shapes_path = os.path.join(static_dir, "SHAPES.VGA")
    if not os.path.isfile(shapes_path):
        print(f"ERROR: SHAPES.VGA not found in {static_dir}", file=sys.stderr)
        return 1

    palette_path = args.palette
    if not palette_path:
        _, palette_path = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not palette_path:
        palette_path = os.path.join(static_dir, "PALETTES.FLX")
    if not os.path.isfile(palette_path):
        print(f"ERROR: Palette not found: {palette_path}", file=sys.stderr)
        return 1

    pal = U7Palette.from_file(palette_path)
    map_num = int(getattr(args, "map_num", 0) or 0)
    renderer = U7MapRenderer(static_dir, map_num=map_num)

    view = args.view or "classic"
    if view not in U7MapRenderer.PROJECTIONS:
        print(
            f"ERROR: Unknown view '{view}'. "
            f"Available: {', '.join(U7MapRenderer.PROJECTIONS.keys())}",
            file=sys.stderr,
        )
        return 1

    # Build exclude set
    exclude: set[int] = set()
    if args.exclude_flags:
        tfa = renderer.tfa
        exclude_kw: dict[str, bool] = {}
        for flag_name in args.exclude_flags:
            exclude_kw[flag_name] = True
        exclude = tfa.build_exclude_set(**exclude_kw)
        active_names = [k for k in exclude_kw if exclude_kw[k]]
        print(
            f"Typeflag filter: {', '.join(active_names)} -> "
            f"{len(exclude)} shapes excluded"
        )

    gamedat = getattr(args, "gamedat", None)
    if gamedat and map_num > 0:
        map_ireg_dir = os.path.join(gamedat, f"map{map_num:02x}")
        if os.path.isdir(map_ireg_dir):
            gamedat = map_ireg_dir
    overlay_tuples = getattr(args, "highlight_rects", None) or []
    overlays = [
        U7TileRectOverlay(
            tx0=tx0,
            ty0=ty0,
            tx1=tx1,
            ty1=ty1,
            color=color,
            label=label,
        )
        for tx0, ty0, tx1, ty1, color, label in overlay_tuples
    ]
    highlight_width = max(1, int(getattr(args, "highlight_width", 3) or 3))
    highlight_lift = int(getattr(args, "highlight_lift", 0) or 0)
    highlight_fill_alpha = max(
        0, min(255, int(getattr(args, "highlight_fill_alpha", 128) or 128))
    )
    highlight_labels = bool(getattr(args, "highlight_labels", True))
    ml = getattr(args, "max_lift", None)

    if args.superchunk is not None:
        sc = args.superchunk
        if sc < 0 or sc > 143:
            print(f"ERROR: Superchunk must be 0–143 (got {sc})", file=sys.stderr)
            return 1

        scx = sc % 12
        scy = sc // 12
        print(
            f"Rendering superchunk {sc} (0x{sc:02X}) at grid ({scx}, {scy}) "
            f"view={view} ..."
        )

        img = renderer.render_superchunk(
            sc,
            pal,
            view=view,
            include_ireg=gamedat,
            exclude_shapes=exclude,
            max_lift=ml,
            grid=args.grid,
            grid_size=args.grid_size,
            highlight_rects=overlays,
            highlight_width=highlight_width,
            highlight_lift=highlight_lift,
            highlight_fill_alpha=highlight_fill_alpha,
            highlight_labels=highlight_labels,
        )

        out_path = args.output or f"u7_sc{sc:02X}_{view}.png"
    else:
        cx0 = args.chunk_x0
        cy0 = args.chunk_y0
        cx1 = args.chunk_x1 if args.chunk_x1 is not None else cx0 + 15
        cy1 = args.chunk_y1 if args.chunk_y1 is not None else cy0 + 15

        print(f"Rendering chunks ({cx0},{cy0}) to ({cx1},{cy1}) view={view} ...")

        img = renderer.render_region(
            cx0,
            cy0,
            cx1,
            cy1,
            pal,
            view=view,
            gamedat_dir=gamedat,
            exclude_shapes=exclude,
            max_lift=ml,
            grid=args.grid,
            grid_size=args.grid_size,
            highlight_rects=overlays,
            highlight_width=highlight_width,
            highlight_lift=highlight_lift,
            highlight_fill_alpha=highlight_fill_alpha,
            highlight_labels=highlight_labels,
        )

        out_path = args.output or f"u7_c{cx0}-{cy0}_c{cx1}-{cy1}_{view}.png"

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Output: {img.width}×{img.height} -> {out_path}")
    return 0


def cmd_map_sample(args: SimpleNamespace) -> int:
    """Render a colour-sampled minimap of U7 world."""
    from titan.u7.map import U7MapRenderer, U7MapSampler
    from titan.u7.palette import U7Palette

    static_dir = args.static
    if not static_dir:
        static_dir, _ = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}", file=sys.stderr)
        return 1

    palette_path = args.palette
    if not palette_path:
        _, palette_path = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not palette_path:
        palette_path = os.path.join(static_dir, "PALETTES.FLX")
    if not os.path.isfile(palette_path):
        print(f"ERROR: Palette not found: {palette_path}", file=sys.stderr)
        return 1

    pal = U7Palette.from_file(palette_path)
    renderer = U7MapRenderer(static_dir)

    scale = args.scale
    grid = getattr(args, "grid", False)
    grid_size = getattr(args, "grid_size", 1)

    # Build exclude set
    exclude: set[int] = set()
    if args.exclude_flags:
        tfa = renderer.tfa
        exclude_kw: dict[str, bool] = {}
        for flag_name in args.exclude_flags:
            exclude_kw[flag_name] = True
        exclude = tfa.build_exclude_set(**exclude_kw)
        print(f"Typeflag filter: {len(exclude)} shapes excluded")

    schunks: list[int] | None = None
    if args.superchunks:
        schunks = args.superchunks

    print(f"Sampling minimap at scale {scale} tiles/pixel ...")

    img = U7MapSampler.sample_map(
        renderer,
        pal,
        schunks=schunks,
        scale=scale,
        grid=grid,
        grid_size=grid_size,
        exclude_shapes=exclude,
    )

    out_path = args.output or f"u7_minimap_s{scale}.png"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    print(f"Output: {img.width}×{img.height} -> {out_path}")
    return 0


def cmd_typeflag_dump(args: SimpleNamespace) -> int:
    """Dump U7 type flag information."""
    from titan.u7.typeflag import U7TypeFlags

    static_dir = args.static
    if not static_dir:
        static_dir, _ = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}", file=sys.stderr)
        return 1

    tfa = U7TypeFlags.from_dir(static_dir)
    print(f"Loaded {len(tfa)} shape entries from {static_dir}")

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = tfa.dump_csv()
    elif fmt == "detail":
        content = tfa.dump_detail()
    else:
        content = tfa.dump_summary()

    if args.output:
        out_path = args.output
        with open(out_path, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {out_path}")
    else:
        # Print stats to terminal (always useful)
        stats = tfa._compute_stats()
        for label, count in stats:
            if label == "":
                print()
            elif label.startswith("---"):
                print(f"\n{label}")
            else:
                print(f"  {label:30s}: {count:5d}")

    return 0


def cmd_wihh_dump(args: SimpleNamespace) -> int:
    """Dump U7 weapon-in-hand offsets from WIHH.DAT."""
    from titan.u7.names import U7ShapeNames
    from titan.u7.wihh import U7WeaponInHandOffsets

    static_dir = args.static
    if not static_dir:
        static_dir, _ = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not static_dir or not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}", file=sys.stderr)
        return 1

    shape_count = _load_shape_count(args, fallback_static=static_dir)
    wihh = U7WeaponInHandOffsets.from_dir(static_dir, shape_count=shape_count)
    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        names = U7ShapeNames.from_static_dir(static_dir)
        content = wihh.dump_csv(
            names,
            include_empty=getattr(args, "include_empty", False),
        )
    else:
        content = wihh.dump_summary()

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"WIHH dump written to: {args.output}")
    else:
        print(content)
    return 0


def cmd_static_data_dump(args: SimpleNamespace) -> int:
    """Dump U7 static metadata tables."""
    from titan.u7.names import U7ShapeNames
    from titan.u7.shapeinfo import (
        U7Ammos,
        U7Armors,
        U7Blends,
        U7Containers,
        U7UsecodeIndex,
        U7Weapons,
        U7Xforms,
    )

    static_dir = args.static
    if not static_dir:
        static_dir, _ = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not static_dir or not os.path.isdir(static_dir):
        print(f"ERROR: STATIC directory not found: {static_dir}", file=sys.stderr)
        return 1

    kind = args.kind.lower()
    names = U7ShapeNames.from_static_dir(static_dir)
    game = getattr(args, "game", "bg")
    exult_flx_path = getattr(args, "exult_flx", None) or _resolve_u7_exult_flx(game)
    if kind in ("weapons", "weapon"):
        weapons = U7Weapons.from_dir(static_dir, game=game)
        content = weapons.dump_csv(names)
        label = f"{len(weapons.records)} weapon row(s)"
    elif kind in ("ammo", "ammos"):
        ammos = U7Ammos.from_dir(static_dir)
        content = ammos.dump_csv(names)
        label = f"{len(ammos.records)} ammo row(s)"
    elif kind in ("armor", "armors"):
        armors = U7Armors.from_dir(static_dir)
        content = armors.dump_csv(names)
        label = f"{len(armors.records)} armor row(s)"
    elif kind in ("container", "containers"):
        containers = U7Containers.from_dir(
            static_dir,
            game=game,
            exult_flx_path=exult_flx_path,
        )
        content = containers.dump_csv(names)
        label = f"{len(containers.records)} container row(s)"
    elif kind in ("xform", "xforms"):
        xforms = U7Xforms.from_dir(static_dir)
        content = xforms.dump_csv()
        label = f"{len(xforms.tables)} xform table(s)"
    elif kind in ("blend", "blends"):
        blends = U7Blends.from_dir(
            static_dir,
            game=game,
            exult_flx_path=exult_flx_path,
        )
        content = blends.dump_csv()
        label = f"{len(blends.records)} blend row(s)"
    elif kind in ("usecode",):
        path = Path(static_dir) / "usecode"
        if not path.is_file():
            path = Path(static_dir) / "USECODE"
        if not path.is_file():
            print(f"ERROR: usecode file not found in {static_dir}", file=sys.stderr)
            return 1
        usecode = U7UsecodeIndex.from_file(str(path))
        content = usecode.dump_csv()
        label = f"{len(usecode.functions)} usecode function row(s)"
    else:
        print(
            "ERROR: kind must be weapons, ammo, armor, container, xforms, blends, or usecode",
            file=sys.stderr,
        )
        return 1

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"{kind} dump written to: {args.output} ({label})")
    else:
        if content:
            print(content, end="" if content.endswith("\n") else "\n")
        else:
            print(f"No data parsed ({label}).")
    return 0


def _load_u7_intrinsic_names_for_cli(args: SimpleNamespace) -> dict[int, str]:
    from titan.u7.usecode import load_u7_intrinsic_names

    path = _resolve_ucxt_intrinsics_data(
        getattr(args, "game", "bg"),
        getattr(args, "intrinsics_data", None),
    )
    if not path:
        return {}
    try:
        return load_u7_intrinsic_names(path)
    except (OSError, ValueError):
        return {}


def cmd_usecode_scan_intrinsic(args: SimpleNamespace) -> int:
    """Scan a U7 USECODE file for intrinsic call sites."""
    from titan.u7.usecode import U7UsecodeFile

    if not os.path.isfile(args.file):
        print(f"ERROR: USECODE file not found: {args.file}", file=sys.stderr)
        return 1
    try:
        intrinsic_id = int(str(args.intrinsic), 0)
    except ValueError:
        print(f"ERROR: invalid intrinsic id: {args.intrinsic}", file=sys.stderr)
        return 1

    names = _load_u7_intrinsic_names_for_cli(args)
    usecode = U7UsecodeFile.from_file(args.file)
    fmt = (getattr(args, "format", None) or "table").lower()
    if fmt == "csv":
        content = usecode.scan_intrinsic_csv(intrinsic_id, names)
    else:
        calls = usecode.scan_intrinsic(intrinsic_id, names)
        lines = [
            f"Intrinsic 0x{intrinsic_id:04X}: {names.get(intrinsic_id, '')}",
            f"Matches: {len(calls)}",
        ]
        for call in calls:
            op = "callis" if call.returns_value else "calli"
            lines.append(
                f"0x{call.function_id:04X} "
                f"func@0x{call.function_offset:08X} "
                f"file@0x{call.file_offset:08X} "
                f"rel@0x{call.relative_offset:04X} "
                f"code@0x{call.code_offset:04X} "
                f"{op}@{call.arg_count:02d} "
                f"{call.raw.hex(' ').upper()}"
            )
        content = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            if content and not content.endswith("\n"):
                f.write("\n")
        print(f"usecode intrinsic scan written to: {args.output}")
    else:
        print(content if content else "No matches.")
    return 0


def cmd_usecode_disasm(args: SimpleNamespace) -> int:
    """Raw-disassemble a single U7 USECODE function."""
    from titan.u7.usecode import U7UsecodeFile

    if not os.path.isfile(args.file):
        print(f"ERROR: USECODE file not found: {args.file}", file=sys.stderr)
        return 1
    disasm_all = bool(getattr(args, "all_functions", False))
    if disasm_all and args.function is not None:
        print("ERROR: use either FUNCTION or --all, not both", file=sys.stderr)
        return 1
    if not disasm_all and args.function is None:
        print("ERROR: provide FUNCTION or --all", file=sys.stderr)
        return 1

    names = _load_u7_intrinsic_names_for_cli(args)
    usecode = U7UsecodeFile.from_file(args.file)
    if disasm_all:
        content = usecode.disassemble_all(names)
    else:
        try:
            func_id = int(str(args.function), 0)
        except ValueError:
            print(f"ERROR: invalid function id: {args.function}", file=sys.stderr)
            return 1
        try:
            content = usecode.disassemble(func_id, names)
        except KeyError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            if content and not content.endswith("\n"):
                f.write("\n")
        print(f"usecode disassembly written to: {args.output}")
    else:
        print(content)
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — LOOSE GAMEDAT FILES
# ============================================================================


def cmd_npc_dump(args: SimpleNamespace) -> int:
    """Dump NPC data from loose npc.dat, GAMEDAT, or INITGAME.DAT."""
    from titan.u7.flex import U7FlexArchive
    from titan.u7.save import U7NPCData, U7Save

    input_path = Path(args.file)
    looks_like_initgame = (
        input_path.is_file() and input_path.name.lower() == "initgame.dat"
    )
    initgame_source = looks_like_initgame and U7FlexArchive.is_u7_flex(str(input_path))
    archive_source = False
    archive: Optional[U7Save] = None
    if looks_like_initgame and not initgame_source:
        try:
            archive = U7Save.from_file(str(input_path))
            archive_source = archive.has_entry("npc.dat")
        except ValueError:
            archive_source = False
        if not archive_source:
            print(
                "ERROR: INITGAME.DAT is neither a U7 Flex archive nor an "
                f"Exult ZIP archive with npc.dat: {input_path}",
                file=sys.stderr,
            )
            return 1
    filepath = (
        str(input_path)
        if initgame_source
        else _resolve_loose_data_file(
            args.file,
            "npc.dat",
        )
    )
    if not archive_source and not os.path.isfile(filepath):
        print(
            f"ERROR: npc.dat or INITGAME.DAT not found: {filepath}",
            file=sys.stderr,
        )
        return 1

    if initgame_source:
        source_note = "INITGAME.DAT Flex:npc.dat"
    elif archive_source:
        source_note = "Exult archive:npc.dat"
        filepath = str(input_path)
    else:
        source_note = "loose npc.dat"
    print(f"Source: {filepath} ({source_note})")
    container_shapes = _load_container_shapes(
        args,
        fallback_static=(
            str(Path(filepath).resolve().parent)
            if initgame_source
            else _infer_static_dir_for_data_file(filepath)
        ),
    )
    valid_shape_count = _load_shape_count(
        args,
        fallback_static=(
            str(Path(filepath).resolve().parent)
            if initgame_source
            else _infer_static_dir_for_data_file(filepath)
        ),
    )
    if initgame_source:
        print("Sex:    decoded from original new-game data (raw bit 9 inverted)")
        npcs = U7NPCData.from_initgame_file(
            filepath,
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
        )
    elif archive_source and archive is not None:
        print("Sex:    decoded from Exult runtime type_flags bit 9")
        npcs = U7NPCData.from_save(
            archive,
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
        )
    else:
        npcs = U7NPCData.from_file(
            filepath,
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
            npc_flavor="auto",
        )
        if npcs.npc_flavor == "original-new-game":
            print("Sex:    auto-detected original new-game data (raw bit 9 inverted)")
        elif npcs.npc_flavor == "runtime":
            print("Sex:    auto-detected Exult runtime type_flags bit 9")
        else:
            print("Sex:    unknown; loose npc.dat has no reliable flavor marker")

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = npcs.dump_csv()
    elif fmt == "detail":
        content = npcs.dump_detail()
    else:
        content = npcs.dump_summary()

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print()
        print(content)
    return 0


def cmd_schedule_dump(args: SimpleNamespace) -> int:
    """Dump NPC schedules from a loose schedule.dat file or directory."""
    from titan.u7.save import U7NPCData, U7Save, U7Schedules

    filepath = _resolve_loose_data_file(args.file, "schedule.dat")
    if not os.path.isfile(filepath):
        print(f"ERROR: schedule.dat not found: {filepath}", file=sys.stderr)
        return 1

    print(f"Source: {filepath} (loose schedule.dat)")
    sched = U7Schedules.from_file(filepath)

    npc_names: dict[int, str] | None = None
    npc_file_arg = getattr(args, "npc_file", None)
    npc_file: Optional[str] = None
    npc_save: Optional[U7Save] = None
    if npc_file_arg:
        npc_path = Path(npc_file_arg)
        if (
            npc_path.is_file()
            and npc_path.suffix.lower() == ".dat"
            and npc_path.name.lower() != "npc.dat"
        ):
            try:
                npc_save = U7Save.from_file(str(npc_path))
                if not npc_save.has_entry("npc.dat"):
                    npc_save = None
            except ValueError:
                npc_save = None
        if npc_save is None:
            npc_file = _resolve_loose_data_file(npc_file_arg, "npc.dat")
    else:
        sibling = Path(filepath).with_name("npc.dat")
        npc_file = str(sibling) if sibling.is_file() else None

    if npc_save is not None or npc_file:
        try:
            container_shapes = _load_container_shapes(args, fallback_static=None)
            valid_shape_count = _load_shape_count(args, fallback_static=None)
            if npc_save is not None:
                npc_data = U7NPCData.from_save(
                    npc_save,
                    container_shapes=container_shapes,
                    valid_shape_count=valid_shape_count,
                )
                print(
                    f"Names:  {len(npc_data.npcs)} NPC names loaded from {npc_file_arg}"
                )
            else:
                if npc_file is None:
                    raise ValueError("npc.dat path could not be resolved")
                npc_data = U7NPCData.from_file(
                    npc_file,
                    container_shapes=container_shapes,
                    valid_shape_count=valid_shape_count,
                )
                print(f"Names:  {len(npc_data.npcs)} NPC names loaded from {npc_file}")
            npc_names = npc_data.name_map()
        except (OSError, ValueError) as exc:
            print(f"Names:  unavailable ({exc})")
    else:
        print("Names:  (no sibling npc.dat or --npc-file)")

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = sched.dump_csv(npc_names)
    elif fmt == "detail":
        content = sched.dump_detail(npc_names)
    else:
        content = sched.dump_summary(npc_names)

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print()
        print(content)
    return 0


def cmd_gamedat_info(args: SimpleNamespace) -> int:
    """Inspect a loose Exult GAMEDAT directory or Exult archive."""
    from titan.u7.flex import U7FlexArchive
    from titan.u7.map import U7MapRenderer
    from titan.u7.save import (
        U7FrameFlags,
        U7GameState,
        U7GlobalFlags,
        U7Identity,
        U7Keyring,
        U7NPCData,
        U7Save,
        U7SaveInfo,
        U7Schedules,
        U7UsecodeData,
        U7UsecodeVars,
    )
    from titan.u7.shape import U7Shape

    source = getattr(args, "directory", None)
    mod = getattr(args, "mod", None)
    if not source:
        source = _resolve_u7_mod_gamedat(getattr(args, "game", "bg"), mod)
    if not source:
        source = _resolve_u7_mod_archive(getattr(args, "game", "bg"), mod)
    if not source:
        source = _resolve_u7_gamedat(getattr(args, "game", "bg"))
    if not source:
        print(
            "ERROR: GAMEDAT source not supplied and no configured/default "
            f"[u7{getattr(args, 'game', 'bg')}] source was found.",
            file=sys.stderr,
        )
        return 1

    root = Path(source)
    archive: Optional[U7Save] = None
    initgame_flex_source = False
    initgame_entries: dict[str, bytes] = {}
    if root.is_file():
        initgame_flex_source = (
            root.name.lower() == "initgame.dat" and U7FlexArchive.is_u7_flex(str(root))
        )
        if initgame_flex_source:
            initgame = U7FlexArchive.from_file(str(root))
            for record in initgame.records:
                if len(record) <= 13:
                    continue
                entry = (
                    record[:13]
                    .split(b"\x00", 1)[0]
                    .decode("ascii", errors="replace")
                    .rstrip(".")
                    .lower()
                )
                initgame_entries[entry] = record[13:]
        if not initgame_flex_source:
            try:
                archive = U7Save.from_file(str(root))
            except ValueError as exc:
                print(
                    f"ERROR: GAMEDAT source is not a directory or Exult archive: {exc}",
                    file=sys.stderr,
                )
                return 1
    elif not root.is_dir():
        print(f"ERROR: GAMEDAT source not found: {root}", file=sys.stderr)
        return 1

    def data_for(name: str) -> Optional[bytes]:
        if initgame_flex_source:
            return initgame_entries.get(name.lower())
        if archive is not None:
            return archive.get_data(name)
        path = root / name
        return path.read_bytes() if path.is_file() else None

    def source_size(name: str) -> int:
        if initgame_flex_source:
            data = data_for(name)
            return len(data) if data is not None else 0
        if archive is not None:
            data = archive.get_data(name)
            return len(data) if data is not None else 0
        path = root / name
        return path.stat().st_size if path.exists() else 0

    def entry_names() -> list[str]:
        if initgame_flex_source:
            return sorted(initgame_entries)
        if archive is not None:
            return sorted(name for name, _ in archive.list_entries())
        return sorted(path.name for path in root.iterdir() if path.is_file())

    container_shapes = _load_container_shapes(
        args,
        fallback_static=(
            None
            if archive is not None
            else _infer_static_dir_for_data_file(str(root / "npc.dat"))
        ),
    )
    valid_shape_count = _load_shape_count(
        args,
        fallback_static=(
            None
            if archive is not None
            else _infer_static_dir_for_data_file(str(root / "npc.dat"))
        ),
    )

    rows: list[tuple[str, int, str, str]] = []

    def add_row(name: str, status: str, note: str = "") -> None:
        rows.append((name, source_size(name), status, note))

    source_kind = (
        "INITGAME.DAT Flex archive"
        if initgame_flex_source
        else (f"{archive.container_format.upper()} archive" if archive else "directory")
    )
    lines: list[str] = [
        "=== Loose GAMEDAT Info ===",
        f"Source: {root} ({source_kind})",
        "",
    ]

    identity_data = data_for("identity")
    if identity_data is not None:
        ident = U7Identity.from_bytes(identity_data)
        lines.append(f"Identity: {ident.game}")
        add_row("identity", "parsed", ident.game)

    for name in ("exult.ver", "newgame.ver"):
        data = data_for(name)
        if data is not None:
            first = data.decode("ascii", errors="replace").splitlines()[0]
            add_row(name, "parsed text", first)

    npc_names: dict[int, str] | None = None
    npc_data = data_for("npc.dat")
    if npc_data is not None:
        npcs = U7NPCData.from_bytes(
            npc_data,
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
            npc_flavor=("original-new-game" if initgame_flex_source else "runtime"),
        )
        npc_names = npcs.name_map()
        lines.append(npcs.dump_summary())
        female_count = sum(1 for npc in npcs.npcs if npc.is_female)
        male_count = sum(1 for npc in npcs.npcs if npc.is_female is False)
        if npcs.npc_flavor == "original-new-game":
            lines.append(
                "NPC sex: decoded from original new-game data "
                f"(raw bit 9 inverted; {female_count} female, {male_count} male)."
            )
        else:
            lines.append(
                "NPC sex: decoded from Exult runtime type_flags bit 9 "
                f"({female_count} female, {male_count} male)."
            )
        add_row(
            "npc.dat",
            "parsed",
            f"{len(npcs.npcs)} NPCs; {female_count} female, {male_count} male",
        )

    mon_data = data_for("monsnpcs.dat")
    if mon_data is not None:
        monsters = U7NPCData.from_monsnpcs_bytes(
            mon_data,
            container_shapes=container_shapes,
        )
        lines.append(
            f"Monster NPCs: {len(monsters.npcs)} parsed ({monsters.num_npcs1} declared)"
        )
        add_row("monsnpcs.dat", "parsed", f"{len(monsters.npcs)} monsters")

    sched_data = data_for("schedule.dat")
    if sched_data is not None:
        sched = U7Schedules.from_bytes(sched_data)
        lines.append(sched.dump_summary(npc_names))
        total = sum(len(entries) for entries in sched.entries.values())
        add_row("schedule.dat", "parsed", f"{total} entries ({sched.format})")

    flag_data = data_for("flaginit")
    if flag_data is not None:
        gflags = U7GlobalFlags.from_bytes(flag_data)
        lines.append(gflags.dump_summary())
        add_row("flaginit", "parsed", f"{gflags.nonzero_count} nonzero")

    saveinfo_data = data_for("saveinfo.dat")
    if saveinfo_data is not None:
        info = U7SaveInfo.from_bytes(saveinfo_data)
        lines.append(
            f"Save info: {info.real_year:04d}-{info.real_month:02d}-"
            f"{info.real_day:02d} {info.real_hour:02d}:"
            f"{info.real_minute:02d}:{info.real_second:02d}, "
            f"party size {info.party_size}"
        )
        add_row("saveinfo.dat", "parsed", f"party size {info.party_size}")

    gwin_data = data_for("gamewin.dat")
    if gwin_data is not None:
        gwin = U7GameState.from_bytes(gwin_data)
        lines.append(
            f"Game window: camera=({gwin.scroll_tx},{gwin.scroll_ty}), "
            f"day {gwin.clock_day}, {gwin.clock_hour:02d}:"
            f"{gwin.clock_minute:02d}"
        )
        add_row("gamewin.dat", "parsed", "camera/time state")

    usedat_data = data_for("usecode.dat")
    if usedat_data is not None:
        usedat = U7UsecodeData.from_bytes(usedat_data)
        nonzero = sum(1 for timer in usedat.timers if timer.value != 0)
        lines.append(
            f"Usecode runtime: party={usedat.party_members}, "
            f"timers={len(usedat.timers)} ({nonzero} nonzero)"
        )
        add_row("usecode.dat", "parsed summary", "party/timers/saved pos")

    usevars_data = data_for("usecode.var")
    if usevars_data is not None:
        usevars = U7UsecodeVars.from_bytes(usevars_data)
        add_row(
            "usecode.var",
            "parsed summary",
            f"{usevars.global_static_count} global statics",
        )

    keyring_data = data_for("keyring.dat")
    if keyring_data is not None:
        keyring = U7Keyring.from_bytes(keyring_data)
        add_row("keyring.dat", "parsed", f"{len(keyring.keys)} keys")

    frames_data = data_for("frames.flg")
    if frames_data is not None:
        frames = U7FrameFlags.from_bytes(frames_data)
        add_row(
            "frames.flg",
            "parsed",
            f"{len(frames.values)} entries, {frames.non_default_count} set",
        )

    if archive is None:
        screenshot_path = root / "scrnshot.shp"
        if screenshot_path.is_file():
            shape = U7Shape.from_file(str(screenshot_path))
            if shape.frames:
                frame = shape.frames[0]
                add_row(
                    "scrnshot.shp",
                    "parsed",
                    f"{len(shape.frames)} frame(s), {frame.width}x{frame.height}",
                )
            else:
                add_row("scrnshot.shp", "parsed", "0 frames")

    ireg_names = [
        name
        for name in entry_names()
        if name.startswith("u7ireg") and len(Path(name).name) == 8
    ]
    if ireg_names:
        total_bytes = sum(source_size(name) for name in ireg_names)
        if archive is None:
            simple_objects = 0
            for name in ireg_names:
                path = root / name
                schunk = int(path.name[-2:], 16)
                simple_objects += len(U7MapRenderer.parse_ireg(str(path), schunk))
            note = f"{len(ireg_names)} files; {simple_objects} simple objects"
            lines.append(
                f"IREG: {len(ireg_names)} files, {simple_objects} simple "
                "objects parsed by current partial parser"
            )
        else:
            note = f"{len(ireg_names)} files; archive bytes counted"
            lines.append(
                f"IREG: {len(ireg_names)} files present; object parsing is "
                "available for loose files"
            )
        rows.append(("u7iregNN", total_bytes, "partially parsed", note))

    known = {name for name, _, _, _ in rows}
    known.add("u7iregNN")
    for name in entry_names():
        plain_name = Path(name).name
        if plain_name in known or name in known:
            continue
        if plain_name.startswith("u7ireg") and len(plain_name) == 8:
            continue
        if Path(plain_name).suffix.lower() in {".csv", ".md"}:
            rows.append((name, source_size(name), "generated artifact", ""))
        else:
            rows.append((name, source_size(name), "unrecognized", ""))

    fmt = getattr(args, "format", "summary") or "summary"
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["file", "size", "status", "note"])
        writer.writerows(rows)
        content = buf.getvalue()
    elif fmt == "detail":
        lines.append("")
        lines.append("--- File Coverage ---")
        for name, size, status, note in rows:
            suffix = f" - {note}" if note else ""
            lines.append(f"{name:<24} {size:>8}  {status}{suffix}")
        content = "\n".join(lines)
    else:
        content = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print(content)
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — MONSTERS
# ============================================================================


def cmd_monster_defs(args: SimpleNamespace) -> int:
    """Dump static U7 MONSTERS.DAT monster definitions."""
    from titan.u7.monster import U7MonsterDefinitions

    source = Path(args.file)
    if source.is_dir():
        defs = U7MonsterDefinitions.from_dir(str(source), game=args.game)
    else:
        defs = U7MonsterDefinitions.from_file(str(source), game=args.game)

    mod_file = getattr(args, "mod_file", None)
    if mod_file:
        mod_defs = U7MonsterDefinitions.from_file(mod_file, game=args.game)
        defs = U7MonsterDefinitions.merge(defs, mod_defs)

    fmt = getattr(args, "format", "summary") or "summary"
    content = defs.dump_csv() if fmt == "csv" else defs.dump_summary()

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"Monster definitions written to: {args.output}")
    else:
        print(content)
    return 0


def cmd_monster_dump(args: SimpleNamespace) -> int:
    """Dump live monster actors from monsnpcs.dat, GAMEDAT, or save archive."""
    from titan.u7.monster import live_monsters_csv, live_monsters_from_source

    input_path = Path(args.file)
    container_shapes = _load_container_shapes(
        args,
        fallback_static=(
            _infer_static_dir_for_data_file(str(input_path / "monsnpcs.dat"))
            if input_path.is_dir()
            else None
        ),
    )
    monsters, source_file = live_monsters_from_source(
        args.file,
        container_shapes=container_shapes,
    )
    fmt = getattr(args, "format", "summary") or "summary"
    if fmt == "csv":
        content = live_monsters_csv(monsters, source_file)
    else:
        lines = [
            f"Source: {source_file}",
            f"Live monsters: {len(monsters.npcs)} parsed",
        ]
        for idx, monster in enumerate(monsters.npcs[:30]):
            lines.append(
                f"  {idx:3d} shape={monster.shape:4d} "
                f"tile=({monster.tile_x},{monster.tile_y},{monster.lift}) "
                f"HP={monster.health:3d} sched={monster.schedule_name}"
            )
        if len(monsters.npcs) > 30:
            lines.append(f"  ... {len(monsters.npcs) - 30} more")
        content = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"Live monster dump written to: {args.output}")
    else:
        print(content)
    return 0


def _parse_int_list(value: str | None) -> set[int]:
    if not value:
        return set()
    parsed: set[int] = set()
    for token in value.split(","):
        token = token.strip()
        if token:
            parsed.add(int(token, 0))
    return parsed


def cmd_monster_equipment(args: SimpleNamespace) -> int:
    """Calculate possible monster equipment from MONSTERS.DAT + equip.dat."""
    from titan.u7.monster import monster_equipment_csv, monster_equipment_summary

    static = getattr(args, "static", None)
    if not static:
        static, _ = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not static:
        print("ERROR: STATIC directory not supplied or configured.", file=sys.stderr)
        return 1

    monster_shapes = _parse_int_list(getattr(args, "monster_shape", None))
    fmt = getattr(args, "format", "summary") or "summary"
    if fmt == "csv":
        content = monster_equipment_csv(
            static,
            game=getattr(args, "game", "bg"),
            mod_monsters=getattr(args, "mod_monsters", None),
            equip_file=getattr(args, "equip_file", None),
            monster_shapes=monster_shapes or None,
        )
    else:
        content = monster_equipment_summary(
            static,
            game=getattr(args, "game", "bg"),
            mod_monsters=getattr(args, "mod_monsters", None),
            equip_file=getattr(args, "equip_file", None),
            monster_shapes=monster_shapes or None,
        )

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"Monster equipment calculation written to: {args.output}")
    else:
        print(content)
    return 0


def cmd_monster_report(args: SimpleNamespace) -> int:
    """Write joined monster definitions, live actors, eggs, and placements."""
    from titan.u7.monster import monster_report

    static = getattr(args, "static", None)
    if not static:
        static, _ = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not static:
        print("ERROR: STATIC directory not supplied or configured.", file=sys.stderr)
        return 1

    gamedat = getattr(args, "gamedat", None)
    if not gamedat:
        gamedat = _resolve_u7_mod_gamedat(
            getattr(args, "game", "bg"),
            getattr(args, "mod", None),
        )
    if not gamedat:
        gamedat = _resolve_u7_gamedat(getattr(args, "game", "bg"))

    live_source = getattr(args, "live_source", None) or gamedat
    out_dir = getattr(args, "output_dir", None)
    outputs = monster_report(
        static_dir=static,
        gamedat_dir=gamedat,
        live_source=live_source,
        game=getattr(args, "game", "bg"),
        mod_monsters=getattr(args, "mod_monsters", None),
        mod_equip=getattr(args, "mod_equip", None),
        output_dir=out_dir,
    )
    if out_dir:
        print(f"Monster report written to: {out_dir}")
        for name in sorted(outputs):
            print(f"  {name}")
    else:
        print(outputs["manifest.txt"])
    return 0


def cmd_npc_equipment(args: SimpleNamespace) -> int:
    """Dump actual NPC inventory/equipment from save, GAMEDAT, or npc.dat."""
    from titan.u7.names import U7ShapeNames
    from titan.u7.save import U7NPCData, U7ReadyTypes, U7Save

    source = Path(args.file)
    static = getattr(args, "static", None)
    if not static:
        static, _ = _resolve_u7_paths(getattr(args, "game", "bg"))
    if not static:
        static = (
            _infer_static_dir_for_data_file(str(source / "npc.dat"))
            if source.is_dir()
            else _infer_static_dir_for_data_file(str(source))
        )
    if not static:
        print("ERROR: STATIC directory not supplied or inferred.", file=sys.stderr)
        return 1

    container_shapes = _load_container_shapes(args, fallback_static=static)
    valid_shape_count = _load_shape_count(args, fallback_static=static)
    if source.is_dir() or source.name.lower() == "npc.dat":
        npc_file = _resolve_loose_data_file(str(source), "npc.dat")
        npcs = U7NPCData.from_file(
            npc_file,
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
            npc_flavor="auto",
        )
        print(f"Source: {npc_file} (loose npc.dat)")
    else:
        save = U7Save.from_file(str(source))
        npcs = U7NPCData.from_save(
            save,
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
        )
        print(f"Source: {source} ({save.container_format.upper()} save)")

    names = U7ShapeNames.from_static_dir(static)
    ready_types = U7ReadyTypes.from_dir(static, game=getattr(args, "game", "bg"))
    npc_nums = _parse_int_list(getattr(args, "npc", None))
    content = npcs.dump_inventory_csv(names, ready_types, npc_nums or None)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"NPC equipment dump written to: {args.output}")
    else:
        print(content)
    return 0


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — SAVE
# ============================================================================


def cmd_save_list(args: SimpleNamespace) -> int:
    """List contents of an Exult U7 savegame file."""
    from titan.u7.save import U7Save

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    entries = save.list_entries()

    print(f"U7 Save: {filepath}")
    print(f"Title:   {save.title}")
    print(f"Format:  {save.container_format.upper()}")
    print(f"Entries: {len(entries)}")
    print()
    print(f"{'Name':<24} {'Size':>10}")
    print("-" * 36)
    total = 0
    for name, size in entries:
        print(f"{name:<24} {size:>10,}")
        total += size
    print("-" * 36)
    print(f"{'Total':<24} {total:>10,}")
    return 0


def cmd_save_extract(args: SimpleNamespace) -> int:
    """Extract files from an Exult U7 savegame archive."""
    from titan.u7.save import U7Save

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    entries = save.list_entries()

    outdir = args.output or Path(filepath).stem
    os.makedirs(outdir, exist_ok=True)

    entry_filter = getattr(args, "entry", None)
    extracted = 0
    for name, size in entries:
        if entry_filter and name.lower() != entry_filter.lower():
            continue
        data = save.get_data(name)
        if data is None:
            continue
        # Handle entries with subdirectory names (e.g. "map00/u7ireg12")
        out_path = os.path.join(outdir, name)
        out_parent = os.path.dirname(out_path)
        if out_parent:
            os.makedirs(out_parent, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"  {name:<24} {size:>10,} bytes")
        extracted += 1

    if entry_filter and extracted == 0:
        print(f"ERROR: Entry '{entry_filter}' not found in archive", file=sys.stderr)
        return 1

    print(f"\nExtracted {extracted} file(s) -> {outdir.rstrip(os.sep)}/")
    return 0


def cmd_gflag_dump(args: SimpleNamespace) -> int:
    """Dump global flags from a savegame or loose flaginit file."""
    from titan.u7.save import U7Save, U7GlobalFlags

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    # Determine whether this is a .sav archive or a loose flaginit file
    ext = os.path.splitext(filepath)[1].lower()
    basename = os.path.basename(filepath).lower()

    if ext == ".sav":
        save = U7Save.from_file(filepath)
        gflags = U7GlobalFlags.from_save(save)
        print(f"Source: {filepath} ({save.container_format.upper()} save)")
        print(f"Title:  {save.title}")
    elif basename == "flaginit":
        gflags = U7GlobalFlags.from_file(filepath)
        print(f"Source: {filepath} (loose flaginit file)")
    else:
        # Try as .sav first, fallback to raw flaginit
        try:
            save = U7Save.from_file(filepath)
            gflags = U7GlobalFlags.from_save(save)
            print(f"Source: {filepath} ({save.container_format.upper()} save)")
            print(f"Title:  {save.title}")
        except (ValueError, KeyError):
            gflags = U7GlobalFlags.from_file(filepath)
            print(f"Source: {filepath} (raw flaginit)")

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = gflags.dump_csv()
    elif fmt == "detail":
        content = gflags.dump_detail()
    else:
        content = gflags.dump_summary()

    if args.output:
        out_path = args.output
        with open(out_path, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {out_path}")
    else:
        print()
        print(content)

    return 0


def cmd_save_info(args: SimpleNamespace) -> int:
    """Show identity, save metadata, party roster, and game state."""
    from titan.u7.save import (
        U7Save,
        U7Identity,
        U7SaveInfo,
        U7GameState,
        U7Schedules,
    )

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    lines: list[str] = []
    lines.append("=== U7 Save Info ===")
    lines.append(f"File:    {filepath}")
    lines.append(f"Title:   {save.title}")
    lines.append(f"Format:  {save.container_format.upper()}")

    # Identity
    try:
        ident = U7Identity.from_save(save)
        lines.append(f"Game:    {ident.game}")
    except (ValueError, KeyError):
        pass

    lines.append("")

    # Save metadata
    try:
        info = U7SaveInfo.from_save(save)
        lines.append(info.dump())
    except (ValueError, KeyError):
        lines.append("(saveinfo.dat not found)")

    lines.append("")

    # Game state
    try:
        gs = U7GameState.from_save(save)
        lines.append(gs.dump())
    except (ValueError, KeyError):
        lines.append("(gamewin.dat not found)")

    lines.append("")

    # Schedule summary
    try:
        sched = U7Schedules.from_save(save)
        lines.append(sched.dump_summary())
    except (ValueError, KeyError):
        pass

    content = "\n".join(lines)

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"Save info written to: {args.output}")
    else:
        print(content)
    return 0


def cmd_save_npcs(args: SimpleNamespace) -> int:
    """Dump NPC data from a savegame."""
    from titan.u7.save import U7Save, U7NPCData

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    print(f"Source: {filepath} ({save.container_format.upper()} save)")
    print(f"Title:  {save.title}")

    container_shapes = _load_container_shapes(args)
    valid_shape_count = _load_shape_count(args)
    npcs = U7NPCData.from_save(
        save,
        container_shapes=container_shapes,
        valid_shape_count=valid_shape_count,
    )

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = npcs.dump_csv()
    elif fmt == "detail":
        content = npcs.dump_detail()
    else:
        content = npcs.dump_summary()

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print()
        print(content)
    return 0


def cmd_save_schedules(args: SimpleNamespace) -> int:
    """Dump NPC schedules from a savegame."""
    from titan.u7.save import U7Save, U7NPCData, U7Schedules

    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    save = U7Save.from_file(filepath)
    print(f"Source: {filepath} ({save.container_format.upper()} save)")
    print(f"Title:  {save.title}")

    sched = U7Schedules.from_save(save)
    npc_names: dict[int, str] | None = None
    try:
        container_shapes = _load_container_shapes(args)
        valid_shape_count = _load_shape_count(args)
        npc_names = U7NPCData.npc_name_map(
            save,
            container_shapes=container_shapes,
            valid_shape_count=valid_shape_count,
        )
    except (ValueError, KeyError):
        pass

    fmt = getattr(args, "format", "summary") or "summary"

    if fmt == "csv":
        content = sched.dump_csv(npc_names)
    elif fmt == "detail":
        content = sched.dump_detail(npc_names)
    else:
        content = sched.dump_summary(npc_names)

    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
            f.write("\n")
        print(f"\n{fmt.title()} dump written to: {args.output}")
    else:
        print()
        print(content)
    return 0


# ============================================================================
# TYPER COMMAND WRAPPERS — MAP
# ============================================================================

# Common exclude flag names (matches U7TypeFlags.build_exclude_set kwargs)
_EXCLUDE_FLAG_CHOICES = [
    "no_solid",
    "no_water",
    "no_animated",
    "no_sfx",
    "no_transparent",
    "no_translucent",
    "no_door",
    "no_barge",
    "no_light",
    "no_poisonous",
    "no_strange_movement",
    "no_building",
]


@u7_app.command("map-render")
def map_render_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory containing U7MAP, U7CHUNKS, "
            "SHAPES.VGA, etc. (default: from titan.toml u7bg/u7si)"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    superchunk: Annotated[
        Optional[str],
        typer.Option(
            "--superchunk",
            "--sc",
            help="Superchunk number 0–143 (decimal or hex, e.g. 85 or 0x55)",
        ),
    ] = None,
    chunk_x0: Annotated[
        Optional[int],
        typer.Option("--cx0", help="Start chunk X (0–191)"),
    ] = None,
    chunk_y0: Annotated[
        Optional[int],
        typer.Option("--cy0", help="Start chunk Y (0–191)"),
    ] = None,
    chunk_x1: Annotated[
        Optional[int],
        typer.Option("--cx1", help="End chunk X (inclusive)"),
    ] = None,
    chunk_y1: Annotated[
        Optional[int],
        typer.Option("--cy1", help="End chunk Y (inclusive)"),
    ] = None,
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to PALETTES.FLX (default: STATIC/PALETTES.FLX)",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output PNG path"),
    ] = None,
    view: Annotated[
        Optional[str],
        typer.Option("--view", help="Projection view: classic, flat, steep"),
    ] = None,
    gamedat: Annotated[
        Optional[str],
        typer.Option(
            "--gamedat", help="Path to gamedat/ directory for IREG dynamic objects"
        ),
    ] = None,
    grid: Annotated[
        bool,
        typer.Option(
            "--grid/--no-grid",
            help="Overlay chunk grid (blue) and superchunk "
            "borders (red) with coordinate labels",
        ),
    ] = False,
    grid_size: Annotated[
        int,
        typer.Option("--grid-size", help="Grid line width in pixels"),
    ] = 1,
    full: Annotated[
        bool,
        typer.Option(
            "--full",
            help="Render the entire world map (shorthand for "
            "--cx0 0 --cy0 0 --cx1 191 --cy1 191)",
        ),
    ] = False,
    exclude: Annotated[
        Optional[list[str]],
        typer.Option(
            "--exclude",
            help=f"Exclude shapes by TFA flag. "
            f"Repeatable. Choices: {', '.join(_EXCLUDE_FLAG_CHOICES)}",
        ),
    ] = None,
    max_lift: Annotated[
        Optional[int],
        typer.Option(
            "--max-lift",
            help="Maximum object lift (tz) to render (0-15). "
            "Objects above this lift are hidden.",
        ),
    ] = None,
    highlight_tile_rect: Annotated[
        Optional[list[str]],
        typer.Option(
            "--highlight-tile-rect",
            "--hrect",
            help=(
                "Highlight tile rectangle (repeatable): "
                "tx0,ty0,tx1,ty1,#RRGGBB[,label] or #RRGGBBAA[,label]"
            ),
        ),
    ] = None,
    highlight_width: Annotated[
        int,
        typer.Option(
            "--highlight-width",
            help="Highlight outline width in pixels",
        ),
    ] = 3,
    highlight_lift: Annotated[
        int,
        typer.Option(
            "--highlight-lift",
            help="Projection lift value for highlighted rectangles",
        ),
    ] = 0,
    highlight_fill_alpha: Annotated[
        int,
        typer.Option(
            "--highlight-fill-alpha",
            help="Highlight fill alpha (0-255)",
        ),
    ] = 128,
    highlight_labels: Annotated[
        bool,
        typer.Option(
            "--highlight-labels/--no-highlight-labels",
            help="Draw labels on highlighted rectangles",
        ),
    ] = True,
    zone_profile: Annotated[
        Optional[str],
        typer.Option(
            "--zone-profile",
            help=(
                "Load named zone profile overlay data and convert it to "
                "highlight rectangles (e.g. si_zones, bg_zones)"
            ),
        ),
    ] = None,
    zone_id: Annotated[
        Optional[list[str]],
        typer.Option(
            "--zone-id",
            help=(
                "Zone ID to include from --zone-profile. Repeatable. "
                "Examples: --zone-id 3 --zone-id 13 or --zone-id A"
            ),
        ),
    ] = None,
    all_zones: Annotated[
        bool,
        typer.Option(
            "--all-zones",
            help=(
                "Include all zones from --zone-profile. "
                "Default behavior when no --zone-id is supplied"
            ),
        ),
    ] = False,
    map_num: Annotated[
        int,
        typer.Option(
            "--map-num",
            help=(
                "Map number: 0 = default world map (root STATIC), "
                "1+ = mapNN/ subdirectory inside STATIC and gamedat (default: 0)"
            ),
        ),
    ] = 0,
) -> None:
    """Render a U7 map region (superchunk, chunk range, or full world) to PNG."""
    if full:
        chunk_x0, chunk_y0, chunk_x1, chunk_y1 = 0, 0, 191, 191
    if superchunk is None and chunk_x0 is None:
        print(
            "ERROR: Specify --superchunk N, --full, or --cx0/--cy0 chunk range.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    sc_int: int | None = None
    if superchunk is not None:
        try:
            sc_int = int(superchunk, 0)
        except ValueError:
            print(
                f"ERROR: --superchunk '{superchunk}' is not a valid integer.",
                file=sys.stderr,
            )
            raise SystemExit(1)

    parsed_highlights: list[
        tuple[int, int, int, int, tuple[int, int, int, int], str]
    ] = []
    if highlight_tile_rect:
        for raw in highlight_tile_rect:
            try:
                parsed_highlights.append(_parse_highlight_tile_rect(raw))
            except ValueError as exc:
                print(f"ERROR: --highlight-tile-rect '{raw}': {exc}", file=sys.stderr)
                raise SystemExit(1)

    if zone_profile is None and (zone_id or all_zones):
        print("ERROR: --zone-id/--all-zones requires --zone-profile.", file=sys.stderr)
        raise SystemExit(1)

    if zone_profile:
        from titan.u7.zones import (
            U7ZoneProfileError,
            build_zone_highlight_rects,
        )

        try:
            profile_rects = build_zone_highlight_rects(
                zone_profile,
                zone_ids=zone_id,
                include_all=all_zones,
            )
        except U7ZoneProfileError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            raise SystemExit(1)

        parsed_highlights.extend(profile_rects)
        print(f"Zone profile '{zone_profile}' -> {len(profile_rects)} rectangle(s)")

    raise SystemExit(
        cmd_map_render(
            SimpleNamespace(
                game=game,
                static=static,
                superchunk=sc_int,
                chunk_x0=chunk_x0 or 0,
                chunk_y0=chunk_y0 or 0,
                chunk_x1=chunk_x1,
                chunk_y1=chunk_y1,
                palette=palette,
                output=output,
                view=view,
                gamedat=gamedat,
                grid=grid,
                grid_size=grid_size,
                exclude_flags=exclude,
                max_lift=max_lift,
                map_num=map_num,
                highlight_rects=parsed_highlights,
                highlight_width=highlight_width,
                highlight_lift=highlight_lift,
                highlight_fill_alpha=highlight_fill_alpha,
                highlight_labels=highlight_labels,
            )
        )
    )


@u7_app.command("map-sample")
def map_sample_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    palette: Annotated[
        Optional[str],
        typer.Option(
            "-p",
            "--palette",
            help="Path to PALETTES.FLX (default: STATIC/PALETTES.FLX)",
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output PNG path"),
    ] = None,
    scale: Annotated[
        int,
        typer.Option(
            "--scale", help="Tiles per output pixel (1=full, 4=768px, 8=384px)"
        ),
    ] = 4,
    grid: Annotated[
        bool,
        typer.Option(
            "--grid/--no-grid",
            help="Overlay chunk grid (blue, scale<=2) and "
            "superchunk grid (red) with coordinate labels",
        ),
    ] = False,
    grid_size: Annotated[
        int,
        typer.Option("--grid-size", help="Grid line width in pixels"),
    ] = 1,
    superchunks: Annotated[
        Optional[list[int]],
        typer.Option("--sc", help="Only sample these superchunks (repeatable)"),
    ] = None,
    exclude: Annotated[
        Optional[list[str]],
        typer.Option("--exclude", help="Exclude shapes by TFA flag (repeatable)"),
    ] = None,
) -> None:
    """Render a colour-sampled U7 world minimap to PNG."""
    raise SystemExit(
        cmd_map_sample(
            SimpleNamespace(
                game=game,
                static=static,
                palette=palette,
                output=output,
                scale=scale,
                grid=grid,
                grid_size=grid_size,
                superchunks=superchunks,
                exclude_flags=exclude,
            )
        )
    )


@u7_app.command("typeflag-dump")
def typeflag_dump_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory containing TFA.DAT (default: from titan.toml u7bg/u7si)"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Dump U7 type flag data (TFA.DAT, SHPDIMS.DAT, WGTVOL.DAT, OCCLUDE.DAT)."""
    raise SystemExit(
        cmd_typeflag_dump(
            SimpleNamespace(
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("wihh-dump")
def wihh_dump_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory containing WIHH.DAT (default: from titan.toml u7bg/u7si)"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: summary (default), csv"),
    ] = None,
    include_empty: Annotated[
        bool,
        typer.Option(
            "--include-empty",
            help="Include shapes with no WIHH record in CSV output",
        ),
    ] = False,
) -> None:
    """Dump U7 WIHH.DAT weapon-in-hand actor offsets."""
    raise SystemExit(
        cmd_wihh_dump(
            SimpleNamespace(
                game=game,
                static=static,
                output=output,
                format=format,
                include_empty=include_empty,
            )
        )
    )


@u7_app.command("static-data-dump")
def static_data_dump_cmd(
    kind: Annotated[
        str,
        typer.Argument(
            help="Table to dump: weapons, ammo, armor, container, xforms, blends, usecode"
        ),
    ],
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write CSV dump to this file"),
    ] = None,
    exult_flx: Annotated[
        Optional[str],
        typer.Option(
            "--exult-flx",
            help="Path to exult_bg.flx/exult_si.flx for Exult bundled fallbacks",
        ),
    ] = None,
) -> None:
    """Dump U7 static metadata tables as CSV."""
    raise SystemExit(
        cmd_static_data_dump(
            SimpleNamespace(
                kind=kind,
                game=game,
                static=static,
                output=output,
                exult_flx=exult_flx,
            )
        )
    )


@u7_app.command("usecode-scan-intrinsic")
def usecode_scan_intrinsic_cmd(
    file: Annotated[str, typer.Argument(help="Path to U7 USECODE file")],
    intrinsic: Annotated[
        str,
        typer.Argument(help="Intrinsic id to scan for, hex or decimal"),
    ],
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI intrinsic-name table"),
    ] = "bg",
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: table (default), csv"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write scan output to this file"),
    ] = None,
    intrinsics_data: Annotated[
        Optional[str],
        typer.Option(
            "--intrinsics-data",
            help="Optional UCXT-style intrinsic-name table",
        ),
    ] = None,
) -> None:
    """Scan raw U7 USECODE for CALLI/CALLIS references to one intrinsic."""
    raise SystemExit(
        cmd_usecode_scan_intrinsic(
            SimpleNamespace(
                file=file,
                intrinsic=intrinsic,
                game=game,
                format=format,
                output=output,
                intrinsics_data=intrinsics_data,
            )
        )
    )


@u7_app.command("usecode-disasm")
def usecode_disasm_cmd(
    file: Annotated[str, typer.Argument(help="Path to U7 USECODE file")],
    function: Annotated[
        Optional[str],
        typer.Argument(help="Function id to disassemble, hex or decimal"),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI intrinsic-name table"),
    ] = "bg",
    all_functions: Annotated[
        bool,
        typer.Option("--all", help="Disassemble every function in the USECODE file"),
    ] = False,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write raw disassembly to this file"),
    ] = None,
    intrinsics_data: Annotated[
        Optional[str],
        typer.Option(
            "--intrinsics-data",
            help="Optional UCXT-style intrinsic-name table",
        ),
    ] = None,
) -> None:
    """Raw-disassemble one U7 USECODE function, or all functions with --all."""
    raise SystemExit(
        cmd_usecode_disasm(
            SimpleNamespace(
                file=file,
                function=function,
                game=game,
                all_functions=all_functions,
                output=output,
                intrinsics_data=intrinsics_data,
            )
        )
    )


# ============================================================================
# TYPER COMMAND WRAPPERS — SAVE
# ============================================================================


@u7_app.command("npc-dump")
def npc_dump_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to npc.dat, a GAMEDAT directory, or STATIC/INITGAME.DAT"
        ),
    ],
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static",
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Dump NPC data from loose Exult GAMEDAT npc.dat or INITGAME.DAT."""
    raise SystemExit(
        cmd_npc_dump(
            SimpleNamespace(
                file=file,
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("schedule-dump")
def schedule_dump_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to schedule.dat or a directory containing schedule.dat"
        ),
    ],
    npc_file: Annotated[
        Optional[str],
        typer.Option(
            "--npc-file", help="Optional npc.dat file or directory for NPC names"
        ),
    ] = None,
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static", help="Path to STATIC directory for npc.dat inventory parsing"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Dump NPC schedules from loose Exult schedule.dat."""
    raise SystemExit(
        cmd_schedule_dump(
            SimpleNamespace(
                file=file,
                npc_file=npc_file,
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("gamedat-info")
def gamedat_info_cmd(
    directory: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to a loose Exult GAMEDAT directory or archive (default: titan.toml/user profile)"
        ),
    ] = None,
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static", help="Path to STATIC directory for npc.dat inventory parsing"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    mod: Annotated[
        Optional[str],
        typer.Option(
            "--mod", help="Resolve user-profile Exult runtime GAMEDAT for this mod"
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Inspect loose Exult GAMEDAT files or archives."""
    raise SystemExit(
        cmd_gamedat_info(
            SimpleNamespace(
                directory=directory,
                game=game,
                mod=mod,
                static=static,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("monster-defs")
def monster_defs_cmd(
    file: Annotated[
        str, typer.Argument(help="Path to MONSTERS.DAT or STATIC directory")
    ],
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI decoding rules"),
    ] = "bg",
    mod_file: Annotated[
        Optional[str],
        typer.Option("--mod-file", help="Optional mod MONSTERS.DAT to merge over base"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: summary (default), csv"),
    ] = None,
) -> None:
    """Dump decoded MONSTERS.DAT monster definitions."""
    raise SystemExit(
        cmd_monster_defs(
            SimpleNamespace(
                file=file,
                game=game,
                mod_file=mod_file,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("monster-dump")
def monster_dump_cmd(
    file: Annotated[
        str,
        typer.Argument(
            help="Path to monsnpcs.dat, GAMEDAT directory, or Exult save archive"
        ),
    ],
    static: Annotated[
        Optional[str],
        typer.Option("--static", help="Path to STATIC directory for inventory parsing"),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: summary (default), csv"),
    ] = None,
) -> None:
    """Dump live monster actors from Exult monsnpcs.dat."""
    raise SystemExit(
        cmd_monster_dump(
            SimpleNamespace(
                file=file,
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("monster-equipment")
def monster_equipment_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(help="Path to STATIC directory (default: titan.toml)"),
    ] = None,
    monster_shape: Annotated[
        Optional[str],
        typer.Option(
            "--monster-shape",
            help="Monster shape filter, comma-separated; accepts decimal or 0xHEX",
        ),
    ] = None,
    mod_monsters: Annotated[
        Optional[str],
        typer.Option("--mod-monsters", help="Optional mod MONSTERS.DAT override file"),
    ] = None,
    equip_file: Annotated[
        Optional[str],
        typer.Option("--equip-file", help="Optional equip.dat file"),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI decoding rules"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: summary (default), csv"),
    ] = None,
) -> None:
    """Calculate possible monster equipment from MONSTERS.DAT + equip.dat."""
    raise SystemExit(
        cmd_monster_equipment(
            SimpleNamespace(
                static=static,
                monster_shape=monster_shape,
                mod_monsters=mod_monsters,
                equip_file=equip_file,
                game=game,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("monster-report")
def monster_report_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(help="Path to STATIC directory (default: titan.toml)"),
    ] = None,
    gamedat: Annotated[
        Optional[str],
        typer.Option("--gamedat", help="Path to Exult GAMEDAT directory"),
    ] = None,
    live_source: Annotated[
        Optional[str],
        typer.Option("--live-source", help="monsnpcs.dat, GAMEDAT, or save archive"),
    ] = None,
    mod_monsters: Annotated[
        Optional[str],
        typer.Option("--mod-monsters", help="Optional mod MONSTERS.DAT override file"),
    ] = None,
    mod_equip: Annotated[
        Optional[str],
        typer.Option("--mod-equip", help="Optional mod equip.dat override file"),
    ] = None,
    mod: Annotated[
        Optional[str],
        typer.Option(
            "--mod", help="Resolve user-profile Exult runtime GAMEDAT for this mod"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI"),
    ] = "bg",
    output_dir: Annotated[
        Optional[str],
        typer.Option("-o", "--output-dir", help="Directory for joined CSV report"),
    ] = None,
) -> None:
    """Export monster definitions, live actors, spawn eggs, and placements."""
    raise SystemExit(
        cmd_monster_report(
            SimpleNamespace(
                static=static,
                gamedat=gamedat,
                live_source=live_source,
                mod_monsters=mod_monsters,
                mod_equip=mod_equip,
                mod=mod,
                game=game,
                output_dir=output_dir,
            )
        )
    )


@u7_app.command("npc-equipment")
def npc_equipment_cmd(
    file: Annotated[
        str,
        typer.Argument(help="Path to save archive, GAMEDAT directory, or npc.dat"),
    ],
    static: Annotated[
        Optional[str],
        typer.Option("--static", help="Path to STATIC directory"),
    ] = None,
    npc: Annotated[
        Optional[str],
        typer.Option(
            "--npc",
            help="NPC number filter, comma-separated; accepts decimal or 0xHEX",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: csv"),
    ] = "csv",
) -> None:
    """Dump actual NPC inventory/equipment with readied/backpack location split."""
    raise SystemExit(
        cmd_npc_equipment(
            SimpleNamespace(
                file=file,
                static=static,
                npc=npc,
                game=game,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("save-list")
def save_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to Exult .sav file")],
) -> None:
    """List contents of an Exult U7 savegame file (ZIP or FLEX)."""
    raise SystemExit(cmd_save_list(SimpleNamespace(file=file)))


@u7_app.command("save-extract")
def save_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to Exult .sav file")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output directory (default: save filename stem)"
        ),
    ] = None,
    entry: Annotated[
        Optional[str],
        typer.Option("-e", "--entry", help="Extract only this named entry"),
    ] = None,
) -> None:
    """Extract files from an Exult U7 savegame archive."""
    raise SystemExit(
        cmd_save_extract(
            SimpleNamespace(
                file=file,
                output=output,
                entry=entry,
            )
        )
    )


@u7_app.command("gflag-dump")
def gflag_dump_cmd(
    file: Annotated[str, typer.Argument(help="Exult .sav file or loose flaginit file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Dump global flags from a U7 savegame or flaginit file."""
    raise SystemExit(
        cmd_gflag_dump(
            SimpleNamespace(
                file=file,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("save-info")
def save_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to Exult .sav file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write output to this file"),
    ] = None,
) -> None:
    """Show save metadata: identity, timestamp, party, game state."""
    raise SystemExit(
        cmd_save_info(
            SimpleNamespace(
                file=file,
                output=output,
            )
        )
    )


@u7_app.command("save-npcs")
def save_npcs_cmd(
    file: Annotated[str, typer.Argument(help="Path to Exult .sav file")],
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static",
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Dump NPC data from an Exult U7 savegame."""
    raise SystemExit(
        cmd_save_npcs(
            SimpleNamespace(
                file=file,
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


@u7_app.command("save-schedules")
def save_schedules_cmd(
    file: Annotated[str, typer.Argument(help="Path to Exult .sav file")],
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static", help="Path to STATIC directory for npc.dat inventory parsing"
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI defaults"),
    ] = "bg",
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write dump to this file"),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), detail, csv"
        ),
    ] = None,
) -> None:
    """Dump NPC schedules from an Exult U7 savegame."""
    raise SystemExit(
        cmd_save_schedules(
            SimpleNamespace(
                file=file,
                game=game,
                static=static,
                output=output,
                format=format,
            )
        )
    )


# ============================================================================
# CMD_* IMPLEMENTATION FUNCTIONS — FONT CREATE
# ============================================================================


def cmd_font_create(args: SimpleNamespace) -> int:
    """Create a U7 font shape from a TrueType font."""
    from titan.fonts.wizard import run_wizard, run_from_config

    if args.config:
        return run_from_config(args.config, output_override=args.output)
    return run_wizard()


@u7_app.command("font-create")
def font_create_cmd(
    config: Annotated[
        Optional[str],
        typer.Option(
            "--config", "-c", help="TOML config file (skip interactive prompts)"
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output file path"),
    ] = None,
) -> None:
    """Interactive wizard for creating U7 font shapes from TrueType fonts.

    When run without --config, launches an interactive step-by-step
    wizard that walks through game selection, font slot, TTF source,
    rendering method, dimensions, palette, preview, and output.

    With --config, reads all parameters from a TOML recipe file and
    generates the shape non-interactively.
    """
    raise SystemExit(
        cmd_font_create(
            SimpleNamespace(
                config=config,
                output=output,
            )
        )
    )


# ============================================================================
# TYPER COMMAND WRAPPERS — WORLD QUERY
# ============================================================================


@u7_app.command("world-query")
def world_query_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI"),
    ] = "bg",
    gamedat: Annotated[
        Optional[str],
        typer.Option(
            "--gamedat", help="Path to gamedat/ directory for IREG dynamic objects"
        ),
    ] = None,
    text: Annotated[
        Optional[str],
        typer.Option("--text", help="Path to TEXT.FLX for shape name lookup"),
    ] = None,
    # ── Non-interactive filters ──────────────────────────────────────────────
    shape_class: Annotated[
        Optional[list[str]],
        typer.Option(
            "--class",
            help="Shape class filter (repeatable): container, human, monster, …",
        ),
    ] = None,
    shape_num: Annotated[
        Optional[list[str]],
        typer.Option(
            "--shape",
            help="Shape number filter, hex or decimal (repeatable): 522, 0x20A",
        ),
    ] = None,
    name: Annotated[
        Optional[str],
        typer.Option("--name", help="Shape name substring filter (case-insensitive)"),
    ] = None,
    flag: Annotated[
        Optional[list[str]],
        typer.Option(
            "--flag", help="TFA flag filter (repeatable): solid, animated, door, …"
        ),
    ] = None,
    tile_rect: Annotated[
        Optional[str],
        typer.Option("--tile-rect", help="Tile rectangle filter: tx0,ty0,tx1,ty1"),
    ] = None,
    sc: Annotated[
        Optional[list[str]],
        typer.Option(
            "--sc", help="Superchunk number filter, hex or decimal (repeatable): 0x55"
        ),
    ] = None,
    ireg: Annotated[
        bool,
        typer.Option(
            "--ireg/--no-ireg", help="Include IREG dynamic objects (default: auto)"
        ),
    ] = False,
    map_num: Annotated[
        int,
        typer.Option(
            "--map-num",
            help="Map number: 0 = default world map, 1+ = mapNN/ subdirectory inside STATIC and gamedat (default: 0)",
        ),
    ] = 0,
    format: Annotated[
        Optional[str],
        typer.Option(
            "-f", "--format", help="Output format: summary (default), full_text, csv"
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write output to this file"),
    ] = None,
) -> None:
    """Query world object placements from IFIX and IREG.

    With no filter flags, launches an interactive wizard (requires questionary).
    Supply any filter flag to run non-interactively.

    \\b
    Non-interactive examples:
      titan u7 world-query STATIC/ --gamedat gamedat/ --class container --tile-rect 512,512,2048,2048
      titan u7 world-query STATIC/ --name "locked chest" --ireg --gamedat gamedat/ -f csv -o out.csv
      titan u7 world-query STATIC/ --shape 522 --ireg --gamedat gamedat/ -f full_text
    """
    from titan.u7.world import (
        run_wizard as _world_wizard,
        WorldQueryParams,
        run_query,
        format_result,
    )
    from titan.u7.typeflag import U7TypeFlags

    static_dir = static
    if not static_dir:
        resolved, _ = _resolve_u7_paths(game)
        static_dir = resolved

    gamedat_dir = gamedat
    if not gamedat_dir:
        gamedat_dir = _resolve_u7_gamedat(game)

    text_flx = text or _resolve_u7_text_flx(game, static_dir)

    # Non-interactive mode when any filter flag is supplied
    _non_interactive = any(
        [shape_class, shape_num, name, flag, tile_rect, sc, format, output, ireg]
    )

    if not _non_interactive:
        raise SystemExit(
            _world_wizard(
                static_dir=static_dir,
                gamedat_dir=gamedat_dir,
                text_flx=text_flx,
            )
        )

    # ── Parse CLI filters ────────────────────────────────────────────────────
    shape_class_ids: list[int] = []
    if shape_class:
        _class_map = {v: k for k, v in U7TypeFlags.SHAPE_CLASS_NAMES.items()}
        for cls_name in shape_class:
            cid = _class_map.get(cls_name.lower())
            if cid is not None:
                shape_class_ids.append(cid)
            else:
                typer.echo(
                    f"Unknown shape class: {cls_name!r}. Valid: {', '.join(_class_map)}",
                    err=True,
                )
                raise SystemExit(1)

    shape_nums: list[int] = []
    if shape_num:
        for token in shape_num:
            try:
                shape_nums.append(int(token, 0))
            except ValueError:
                typer.echo(f"Invalid shape number: {token!r}", err=True)
                raise SystemExit(1)

    superchunks: list[int] = []
    if sc:
        for token in sc:
            try:
                superchunks.append(int(token, 0))
            except ValueError:
                typer.echo(f"Invalid superchunk number: {token!r}", err=True)
                raise SystemExit(1)

    parsed_rect: Optional[tuple[int, int, int, int]] = None
    if tile_rect:
        parts = tile_rect.split(",")
        if len(parts) != 4:
            typer.echo("--tile-rect must be tx0,ty0,tx1,ty1", err=True)
            raise SystemExit(1)
        try:
            tx0, ty0, tx1, ty1 = (int(p.strip(), 0) for p in parts)
            parsed_rect = (min(tx0, tx1), min(ty0, ty1), max(tx0, tx1), max(ty0, ty1))
        except ValueError:
            typer.echo("--tile-rect values must be integers", err=True)
            raise SystemExit(1)

    use_ireg = ireg or bool(
        gamedat_dir and any([cls in (6, 7, 12, 13) for cls in shape_class_ids])
    )

    params = WorldQueryParams(
        static_dir=static_dir or "",
        gamedat_dir=gamedat_dir if use_ireg else None,
        shape_classes=shape_class_ids,
        shape_nums=shape_nums,
        name_filter=name or "",
        text_flx_path=text_flx,
        tfa_flags=list(flag) if flag else [],
        superchunks=superchunks,
        tile_rect=parsed_rect,
        include_ifix=True,
        include_ireg=use_ireg,
        map_num=map_num,
        output_format=format or "summary",
        output_path=output,
    )

    result = run_query(params)
    out = format_result(result)

    if output:
        from pathlib import Path as _Path

        _Path(output).write_text(out, encoding="utf-8")
        typer.echo(f"Wrote {result.count} result(s) to {output}")
    else:
        typer.echo(out)


@u7_app.command("container-browse")
def container_browse_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI"),
    ] = "bg",
    gamedat: Annotated[
        Optional[str],
        typer.Option(
            "--gamedat", help="Path to gamedat/ directory (required for IREG)"
        ),
    ] = None,
    text: Annotated[
        Optional[str],
        typer.Option("--text", help="Path to TEXT.FLX for shape name lookup"),
    ] = None,
    exult_flx: Annotated[
        Optional[str],
        typer.Option(
            "--exult-flx",
            help="Path to exult_bg.flx (or exult_si.flx) for per-frame item names",
        ),
    ] = None,
    mod_data: Annotated[
        Optional[str],
        typer.Option(
            "--mod-data",
            help="Path to mod patch/data directory (textmsg.txt + shape_info.txt for mod-specific names)",
        ),
    ] = None,
    map_num: Annotated[
        int,
        typer.Option(
            "--map-num",
            help="Map number to query: 0 = default world map, 1+ = mod map subdirectory (mapNN/)",
        ),
    ] = 0,
    # ── Container identity filters ───────────────────────────────────────────
    container_shape: Annotated[
        Optional[list[str]],
        typer.Option(
            "--container-shape",
            help="Container shape number(s), hex or decimal (repeatable)",
        ),
    ] = None,
    container_name: Annotated[
        Optional[str],
        typer.Option(
            "--container-name",
            help="Container name substring filter (case-insensitive)",
        ),
    ] = None,
    # ── Contents filters ─────────────────────────────────────────────────────
    contains_shape: Annotated[
        Optional[list[str]],
        typer.Option(
            "--contains-shape",
            help="Only show containers holding item with this shape (repeatable)",
        ),
    ] = None,
    contains_name: Annotated[
        Optional[str],
        typer.Option(
            "--contains-name",
            help="Only show containers holding item matching name substring",
        ),
    ] = None,
    # ── Area filters ─────────────────────────────────────────────────────────
    tile_rect: Annotated[
        Optional[str],
        typer.Option("--tile-rect", help="Tile rectangle filter: tx0,ty0,tx1,ty1"),
    ] = None,
    sc: Annotated[
        Optional[list[str]],
        typer.Option(
            "--sc", help="Superchunk number filter, hex or decimal (repeatable)"
        ),
    ] = None,
    # ── Output ───────────────────────────────────────────────────────────────
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: tree (default), csv"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write output to this file"),
    ] = None,
) -> None:
    """Browse container contents from IREG, with full nesting support.

    With no filter flags, launches an interactive wizard (requires questionary).
    Supply any filter flag to run non-interactively.

    \\b
    Non-interactive examples:
      titan u7 container-browse STATIC/ --gamedat gamedat/
      titan u7 container-browse STATIC/ --gamedat gamedat/ --container-name chest
      titan u7 container-browse STATIC/ --gamedat gamedat/ --container-shape 522
      titan u7 container-browse STATIC/ --gamedat gamedat/ --contains-name sword -f csv -o containers.csv
      titan u7 container-browse STATIC/ --gamedat gamedat/ --tile-rect 512,512,2048,2048 -f tree
    """
    from titan.u7.container import (
        browse_containers,
        ContainerQueryParams,
        format_results,
        run_wizard as _container_wizard,
    )
    from titan.u7.names import U7ShapeNames, U7FrameNames
    from titan._config import exult_cfg

    static_dir = static
    if not static_dir:
        resolved, _ = _resolve_u7_paths(game)
        static_dir = resolved

    gamedat_dir = gamedat
    if not gamedat_dir:
        gamedat_dir = _resolve_u7_gamedat(game)

    text_flx = text or _resolve_u7_text_flx(game, static_dir)

    _non_interactive = any(
        [
            container_shape,
            container_name,
            contains_shape,
            contains_name,
            tile_rect,
            sc,
            format,
            output,
        ]
    )

    _exult_flx = exult_flx or exult_cfg(f"{game}_flx") or None

    if not _non_interactive:
        raise SystemExit(
            _container_wizard(
                static_dir=static_dir,
                gamedat_dir=gamedat_dir,
                text_flx=text_flx,
                exult_flx_path=_exult_flx,
                mod_data_dir=mod_data,
                map_num=map_num,
            )
        )

    # ── Parse filters ────────────────────────────────────────────────────────
    container_shape_nums: list[int] = []
    if container_shape:
        for token in container_shape:
            try:
                container_shape_nums.append(int(token, 0))
            except ValueError:
                typer.echo(f"Invalid shape number: {token!r}", err=True)
                raise SystemExit(1)

    contains_shape_nums: list[int] = []
    if contains_shape:
        for token in contains_shape:
            try:
                contains_shape_nums.append(int(token, 0))
            except ValueError:
                typer.echo(f"Invalid shape number: {token!r}", err=True)
                raise SystemExit(1)

    superchunks: list[int] = []
    if sc:
        for token in sc:
            try:
                superchunks.append(int(token, 0))
            except ValueError:
                typer.echo(f"Invalid superchunk number: {token!r}", err=True)
                raise SystemExit(1)

    parsed_rect: Optional[tuple[int, int, int, int]] = None
    if tile_rect:
        parts = tile_rect.split(",")
        if len(parts) != 4:
            typer.echo("--tile-rect must be tx0,ty0,tx1,ty1", err=True)
            raise SystemExit(1)
        try:
            tx0, ty0, tx1, ty1 = (int(p.strip(), 0) for p in parts)
            parsed_rect = (min(tx0, tx1), min(ty0, ty1), max(tx0, tx1), max(ty0, ty1))
        except ValueError:
            typer.echo("--tile-rect values must be integers", err=True)
            raise SystemExit(1)

    if not gamedat_dir:
        typer.echo(
            "Error: --gamedat is required for container-browse (containers live in IREG)",
            err=True,
        )
        raise SystemExit(1)

    names: Optional[U7ShapeNames] = None
    if text_flx:
        try:
            names = U7ShapeNames.from_file(text_flx)
        except (FileNotFoundError, OSError):
            pass
    if names is None and static_dir:
        names = U7ShapeNames.from_static_dir(static_dir)

    frame_names: Optional[U7FrameNames] = None
    if _exult_flx and text_flx and Path(_exult_flx).exists():
        try:
            frame_names = U7FrameNames.from_flx(_exult_flx, text_flx, game=game)
        except Exception:
            pass

    # Overlay mod-specific names on top of base data
    if mod_data and Path(mod_data).is_dir():
        names = U7ShapeNames.from_mod_dir(mod_data, base=names) or names
        if text_flx:
            frame_names = (
                U7FrameNames.from_mod_dir(mod_data, text_flx, base=frame_names)
                or frame_names
            )

    params = ContainerQueryParams(
        static_dir=static_dir or "",
        gamedat_dir=gamedat_dir,
        container_shape_nums=container_shape_nums,
        container_name_filter=container_name or "",
        contains_shape_nums=contains_shape_nums,
        contains_name_filter=contains_name or "",
        superchunks=superchunks,
        tile_rect=parsed_rect,
        text_flx_path=text_flx,
        exult_flx_path=_exult_flx,
        map_num=map_num,
        output_format=format or "tree",
        output_path=output,
    )

    results = browse_containers(params)
    out = format_results(results, params, names, frame_names)

    if output:
        from pathlib import Path as _Path

        _Path(output).write_text(out, encoding="utf-8")
        typer.echo(f"Wrote {len(results)} container(s) to {output}")
    else:
        typer.echo(out)


@u7_app.command("egg-query")
def egg_query_cmd(
    static: Annotated[
        Optional[str],
        typer.Argument(
            help="Path to STATIC directory (default: from titan.toml u7bg/u7si)",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use config section for BG or SI"),
    ] = "bg",
    gamedat: Annotated[
        Optional[str],
        typer.Option("--gamedat", help="Path to gamedat/ directory (required)"),
    ] = None,
    egg_type: Annotated[
        Optional[list[str]],
        typer.Option(
            "--type", help="Egg type filter (repeatable): usecode, monster, teleport, …"
        ),
    ] = None,
    fn: Annotated[
        Optional[str],
        typer.Option(
            "--fn", help="Usecode function number filter, hex or decimal: 0x06BC"
        ),
    ] = None,
    tile_rect: Annotated[
        Optional[str],
        typer.Option("--tile-rect", help="Tile rectangle filter: tx0,ty0,tx1,ty1"),
    ] = None,
    sc: Annotated[
        Optional[list[str]],
        typer.Option(
            "--sc", help="Superchunk number filter, hex or decimal (repeatable)"
        ),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: table (default), csv"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write output to this file"),
    ] = None,
) -> None:
    """Query egg trigger objects from IREG, showing type, function, and location.

    With no filter flags, launches an interactive wizard (requires questionary).
    Supply any filter flag to run non-interactively.

    \\b
    Non-interactive examples:
      titan u7 egg-query STATIC/ --gamedat gamedat/
      titan u7 egg-query STATIC/ --gamedat gamedat/ --type usecode
      titan u7 egg-query STATIC/ --gamedat gamedat/ --fn 0x06BC
      titan u7 egg-query STATIC/ --gamedat gamedat/ --type monster --tile-rect 512,512,2048,2048
      titan u7 egg-query STATIC/ --gamedat gamedat/ --type usecode -f csv -o eggs.csv
    """
    from titan.u7.eggs import (
        query_eggs,
        EggQueryParams,
        format_results,
        run_wizard as _egg_wizard,
    )

    static_dir = static
    if not static_dir:
        resolved, _ = _resolve_u7_paths(game)
        static_dir = resolved

    gamedat_dir = gamedat
    if not gamedat_dir:
        gamedat_dir = _resolve_u7_gamedat(game)

    _non_interactive = any([egg_type, fn, tile_rect, sc, format, output])

    if not _non_interactive:
        raise SystemExit(
            _egg_wizard(
                static_dir=static_dir,
                gamedat_dir=gamedat_dir,
            )
        )

    # ── Validate --type values ───────────────────────────────────────────────
    from titan.u7.map import EGG_TYPE_NAMES as _ETN

    _valid_types = set(_ETN.values())
    for t in egg_type or []:
        if t not in _valid_types:
            typer.echo(
                f"Unknown egg type: {t!r}. Valid: {', '.join(sorted(_valid_types))}",
                err=True,
            )
            raise SystemExit(1)

    # ── Parse --fn ───────────────────────────────────────────────────────────
    fn_filter: Optional[int] = None
    if fn:
        try:
            fn_filter = int(fn, 0)
        except ValueError:
            typer.echo(f"Invalid function number: {fn!r}", err=True)
            raise SystemExit(1)

    # ── Parse --sc ───────────────────────────────────────────────────────────
    superchunks: list[int] = []
    if sc:
        for token in sc:
            try:
                superchunks.append(int(token, 0))
            except ValueError:
                typer.echo(f"Invalid superchunk number: {token!r}", err=True)
                raise SystemExit(1)

    # ── Parse --tile-rect ────────────────────────────────────────────────────
    parsed_rect: Optional[tuple[int, int, int, int]] = None
    if tile_rect:
        parts = tile_rect.split(",")
        if len(parts) != 4:
            typer.echo("--tile-rect must be tx0,ty0,tx1,ty1", err=True)
            raise SystemExit(1)
        try:
            tx0, ty0, tx1, ty1 = (int(p.strip(), 0) for p in parts)
            parsed_rect = (min(tx0, tx1), min(ty0, ty1), max(tx0, tx1), max(ty0, ty1))
        except ValueError:
            typer.echo("--tile-rect values must be integers", err=True)
            raise SystemExit(1)

    if not gamedat_dir:
        typer.echo(
            "Error: --gamedat is required for egg-query (eggs live in IREG)", err=True
        )
        raise SystemExit(1)

    params = EggQueryParams(
        static_dir=static_dir or "",
        gamedat_dir=gamedat_dir,
        egg_types=list(egg_type) if egg_type else [],
        fn_filter=fn_filter,
        superchunks=superchunks,
        tile_rect=parsed_rect,
        output_format=format or "table",
        output_path=output,
    )

    results = query_eggs(params)
    out = format_results(results, params)

    if output:
        from pathlib import Path as _Path

        _Path(output).write_text(out, encoding="utf-8")
        typer.echo(f"Wrote {len(results)} egg(s) to {output}")
    else:
        typer.echo(out)
