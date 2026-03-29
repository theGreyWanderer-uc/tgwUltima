"""
Interactive wizard for U7 font shape creation.

Walks the user through game selection, font slot, TTF source,
rendering method, dimensions, palette, preview, and output — then
generates the shape file.

Also supports non-interactive mode via TOML config files.
"""

from __future__ import annotations

__all__ = ["run_wizard", "run_from_config", "WizardConfig"]

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from titan.fonts.presets import (
    FONT_SHAPES,
    BUNDLED_TTFS,
    get_ttf_path,
    presets_for_game,
)
from titan.fonts.palette import (
    PaletteLUT, get_builtin_lut, list_builtin_luts, resolve_game_palette,
    GRADIENT_PRESETS, list_gradient_presets, get_gradient_preset,
    resolve_gradient_to_indices,
)
from titan.fonts.exult_cfg import (
    find_exult_cfg, parse_exult_cfg, resolve_font_vga_path,
    scan_font_archives,
    ExultGamePaths, FONT_FILE_MAP, DEFAULT_FONT_CONFIG,
)
from titan.fonts.renderer import (
    find_pixel_size_for_cap,
    render_all_glyphs_mono,
    render_all_glyphs_grayscale,
    render_all_glyphs_hollow_gradient,
)
from titan.fonts.encoder import glyphs_to_shape, EXULT_STUDIO_PREVIEW_FRAME


@dataclass
class WizardConfig:
    """All parameters needed to produce a font shape."""

    game: str = "BG"                # "BG" or "SI"
    slot: int = 0                   # FONTS.VGA shape index
    cell_height: int = 14
    ink_height: int = 13
    h_lead: int = -2
    total_frames: int = 128

    # Source font
    ttf_key: Optional[str] = None   # Built-in key (e.g. "dosVga437")
    ttf_path: Optional[str] = None  # Custom TTF path

    # Rendering
    render_method: str = "mono"     # "mono", "lut", "threshold", "hollow_gradient"
    lut_key: Optional[str] = None   # Built-in LUT key
    lut_path: Optional[str] = None  # Custom LUT TOML path
    threshold: int = 128            # Grayscale threshold (for "threshold")

    # Hollow gradient options
    gradient_preset: Optional[str] = None  # preset key (e.g. "warm_flame")
    stroke_width: int = 1
    stroke_index: int = 0
    gradient_indices: list[int] = field(
        default_factory=lambda: [36, 181, 182, 183, 184, 185]
    )

    # Palette (mono/threshold only)
    ink_index: int = 0
    transparent_index: int = 255

    # Game palette file for validation/preview
    palette_file: Optional[str] = None

    # Glyph layout
    layout: str = "standard"        # "standard" or path to mapping TOML
    code_range: tuple[int, int] = (0x21, 0x7E)

    # Naming
    shape_name: Optional[str] = None  # Descriptive name (e.g. "Pagan gold title")

    # Output
    output_format: str = "shp"      # "shp", "flex", "both"
    output_path: Optional[str] = None
    flex_source: Optional[str] = None  # Path to FONTS.VGA for patching


# ---------------------------------------------------------------------------
# ASCII-art preview helper
# ---------------------------------------------------------------------------

_INK = "\u2588"   # █
_EMPTY = "\u00b7"  # ·


def _preview_glyph(bmp: np.ndarray, is_mono: bool = True) -> list[str]:
    """Render a glyph bitmap as ASCII art lines."""
    lines: list[str] = []
    for row in bmp:
        line = ""
        for px in row:
            if is_mono:
                line += _INK if px else _EMPTY
            else:
                line += _INK if px > 0 else _EMPTY
        lines.append(line)
    return lines


def _show_preview(
    glyphs: dict[int, np.ndarray],
    is_mono: bool = True,
) -> None:
    """Print ASCII art preview of representative glyphs."""
    preview_codes = [65, 103, 87, 63, 52]  # A g W ? 4
    available = [c for c in preview_codes if c in glyphs]
    if not available:
        available = list(glyphs.keys())[:5]

    if not available:
        print("  (no glyphs to preview)")
        return

    # Render each glyph as ASCII art
    rendered: list[tuple[str, list[str]]] = []
    for code in available:
        bmp = glyphs[code]
        art = _preview_glyph(bmp, is_mono)
        label = f"'{chr(code)}' ({code})"
        rendered.append((label, art))

    # Find max height for alignment
    max_h = max(len(art) for _, art in rendered)

    # Print labels
    labels = "  ".join(f"{lbl:<{len(art[0]) + 2}}" for lbl, art in rendered)
    print(f"\n  {labels}")

    # Print rows
    for row_idx in range(max_h):
        parts: list[str] = []
        for _, art in rendered:
            if row_idx < len(art):
                parts.append(f"  {art[row_idx]}")
            else:
                parts.append("  " + " " * len(art[0]))
        print("".join(parts))
    print()


def _show_palette_info(config: "WizardConfig") -> None:
    """Show palette color info for the indices used by the current LUT."""
    pal = resolve_game_palette(config.game, config.palette_file)
    if pal is None:
        print("  (no game palette found — skipping colour preview)")
        return

    game_label = "Black Gate" if config.game.upper() == "BG" else "Serpent Isle"
    print(f"\n  Palette colours ({game_label}, palette 0):")

    # Collect relevant indices from the LUT or mono ink
    indices: set[int] = set()
    if config.render_method in ("mono", "threshold"):
        indices.add(config.ink_index)
    if config.lut_key or config.lut_path:
        try:
            lut = _resolve_lut(config)
            for _, _, idx in lut.mapping:
                if idx != lut.transparent:
                    indices.add(idx)
        except Exception:
            pass

    if not indices:
        indices.add(config.ink_index)

    for idx in sorted(indices):
        r, g, b = pal.colors[idx]
        print(f"    index {idx:>3d}: #{r:02x}{g:02x}{b:02x}  "
              f"({r}, {g}, {b})")
    print()


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def _prompt_choice(prompt: str, choices: list[str], default: str = "") -> str:
    """Simple numbered-choice prompt."""
    while True:
        resp = input(prompt).strip()
        if not resp and default:
            return default
        if resp in choices:
            return resp
        print(f"  Please enter one of: {', '.join(choices)}")


def _prompt_int(prompt: str, default: int) -> int:
    """Prompt for an integer with a default."""
    while True:
        resp = input(prompt).strip()
        if not resp:
            return default
        try:
            return int(resp)
        except ValueError:
            print("  Please enter a valid integer.")


def _step_game() -> str:
    """Step 1: Choose game."""
    print("\n" + "=" * 50)
    print("  Titan Font Shape Wizard")
    print("=" * 50)
    print("\nWhich game?")
    print("  [1] Black Gate")
    print("  [2] Serpent Isle")
    resp = _prompt_choice("> ", ["1", "2"])
    return "BG" if resp == "1" else "SI"


def _read_archive_slots(archive_path: Path) -> dict[int, dict]:
    """Read a font Flex archive and extract live slot data.

    Returns a dict keyed by slot number with ``name``, ``cell_height``,
    ``h_lead``, ``total_frames``, and ``frame_range`` for each non-empty
    record.  Falls back to the static preset name if the slot is known.
    """
    from titan.u7.flex import U7FlexArchive
    from titan.u7.shape import U7Shape

    archive = U7FlexArchive.from_file(str(archive_path))
    presets = {**FONT_SHAPES}  # for name/h_lead lookups

    slots: dict[int, dict] = {}
    for idx, rec in enumerate(archive.records):
        if not rec:
            continue
        try:
            shape = U7Shape.from_data(rec)
        except Exception:
            continue
        if not shape.frames:
            continue

        # Derive cell_height: max frame height across all frames
        heights = [f.height for f in shape.frames if f.pixels is not None]
        cell_h = max(heights) if heights else 0

        # h_lead is not stored in the shape — use static preset if known
        if idx in presets:
            h_lead = presets[idx]["h_lead"]
            name = presets[idx]["name"]
        else:
            h_lead = 0
            name = f"(slot {idx})"

        # Frame range: first and last non-empty frame indices
        nonempty = [i for i, f in enumerate(shape.frames) if f.pixels is not None]
        if nonempty:
            frame_range = (nonempty[0], nonempty[-1])
        else:
            frame_range = (0, 0)

        slots[idx] = {
            "name": name,
            "cell_height": cell_h,
            "h_lead": h_lead,
            "total_frames": len(shape.frames),
            "frame_range": frame_range,
        }

    return slots


def _step_slot(game: str, source_archive: Path | None = None) -> tuple[int | None, dict | None]:
    """Step 2: Choose font slot.

    Returns ``(slot_number, slot_data)`` or ``(None, None)`` for custom.
    *slot_data* contains at minimum ``cell_height``, ``h_lead``,
    ``total_frames``, and ``frame_range``.
    """
    # Use live data from archive if available, else static presets
    if source_archive and source_archive.is_file():
        try:
            live_slots = _read_archive_slots(source_archive)
        except Exception as e:
            print(f"\n  WARNING: Could not read archive: {e}")
            live_slots = None
    else:
        live_slots = None

    if live_slots is not None:
        slots = live_slots
        print(f"\n  VIEWING: {source_archive}")
    else:
        slots = presets_for_game(game)
        if source_archive:
            print(f"\n  VIEWING: {source_archive}  [COULD NOT READ — showing defaults]")

    source_label = "archive" if live_slots else "original game font"
    print(f"\nUse an existing {game} font slot as a template?")
    print(f"  Selecting a slot pre-fills cell height, h-lead,")
    print(f"  and frame count from the {source_label}.")
    print("  " + "-" * 60)
    print(f"  {'Slot':>4}  {'Name':<30}  {'Cell H':>6}  {'Frames':>6}  {'H-lead':>6}")
    print("  " + "-" * 60)
    for slot in sorted(slots):
        p = slots[slot]
        print(f"  {slot:>4}  {p['name']:<30}  {p['cell_height']:>4} px  {p['total_frames']:>6}  {p['h_lead']:>6}")
    print("  " + "-" * 60)
    print("  [C] Custom (set all dimensions manually)")

    valid = [str(s) for s in sorted(slots)] + ["c", "C"]
    resp = _prompt_choice("> ", valid)
    if resp.upper() == "C":
        return None, None
    chosen = int(resp)
    return chosen, slots[chosen]


def _step_ttf_source() -> tuple[str | None, str | None]:
    """Step 3: Choose source font. Returns (ttf_key, custom_path)."""
    print("\nSource TrueType font:")
    print("  Built-in:")
    keys = list(BUNDLED_TTFS.keys())
    for i, key in enumerate(keys, 1):
        entry = BUNDLED_TTFS[key]
        print(f"  [{i}] {entry['label']}")
    print("\n  Custom:")
    print("  [P] Path to a TTF file")

    valid = [str(i) for i in range(1, len(keys) + 1)] + ["p", "P"]
    resp = _prompt_choice("> ", valid)

    if resp.upper() == "P":
        path = input("  TTF file path: ").strip().strip('"').strip("'")
        if not Path(path).is_file():
            print(f"  WARNING: File not found: {path}")
        return None, path

    idx = int(resp) - 1
    return keys[idx], None


def _step_render_method() -> tuple[str, str | None]:
    """Step 4: Choose rendering method. Returns (method, lut_key)."""
    print("\nRendering method:")
    print("  [1] Hinted mono (1-bit, crisp single-color pixels)")
    print("  [2] LUT downscale (multi-shade via palette lookup table)")
    print("  [3] Grayscale threshold (1-bit with configurable cutoff)")
    print("  [4] Hollow gradient (stroke outline + vertical gradient fill)")
    resp = _prompt_choice("> ", ["1", "2", "3", "4"])

    if resp == "1":
        return "mono", None
    elif resp == "3":
        return "threshold", None
    elif resp == "4":
        return "hollow_gradient", None

    # LUT selection
    print("\nPalette LUT:")
    lut_keys = list_builtin_luts()
    for i, key in enumerate(lut_keys, 1):
        lut = get_builtin_lut(key)
        print(f"  [{i}] {lut.name}")
    print(f"  [F] Custom LUT file (TOML)")

    valid = [str(i) for i in range(1, len(lut_keys) + 1)] + ["f", "F"]
    resp2 = _prompt_choice("> ", valid)
    if resp2.upper() == "F":
        path = input("  LUT TOML path: ").strip()
        return "lut", path
    return "lut", lut_keys[int(resp2) - 1]


def _step_dimensions(preset: dict | None) -> tuple[int, int, int]:
    """Step 5: Confirm/override dimensions."""
    if preset:
        ch = preset["cell_height"]
        ih = preset.get("ink_height", ch - 1)
        hl = preset["h_lead"]
        print(f"\nDimensions (from preset):")
    else:
        ch = 14
        ih = 13
        hl = -2
        print(f"\nDimensions (custom):")

    print(f"  Cell height:  [{ch}]")
    print(f"  Ink height:   [{ih}]")
    print(f"  H-lead:       [{hl}]")

    resp = input("\nOverride any values? [y/N] ").strip().lower()
    if resp == "y":
        ch = _prompt_int(f"  Cell height [{ch}]: ", ch)
        ih = _prompt_int(f"  Ink height [{ih}]: ", ih)
        hl = _prompt_int(f"  H-lead [{hl}]: ", hl)

    return ch, ih, hl


def _step_palette_mono() -> int:
    """Step 6: Choose ink palette index (mono/threshold only)."""
    print("\nInk palette index:")
    print("  [0]   Black (default)")
    print("  [15]  White")
    print("  [N]   Custom index")
    return _prompt_int("> ink index [0]: ", 0)


def _step_hollow_gradient(config: WizardConfig) -> None:
    """Step 6b: Configure hollow gradient parameters via preset or manual."""
    keys = list_gradient_presets()
    print("\nGradient preset:")
    for i, key in enumerate(keys, 1):
        p = get_gradient_preset(key)
        print(f"  [{i:2d}] {p.name:24s} {p.description}  {p.swatches}")
    print(f"  [M]  Manual (enter palette indices directly)")

    valid = [str(i) for i in range(1, len(keys) + 1)] + ["m", "M"]
    resp = _prompt_choice("> ", valid)

    if resp.upper() == "M":
        # Manual entry — raw palette indices
        config.stroke_index = _prompt_int(
            f"  Stroke index [{config.stroke_index}]: ", config.stroke_index)
        raw = input(f"  Gradient indices (comma-separated) [{','.join(str(i) for i in config.gradient_indices)}]: ").strip()
        if raw:
            config.gradient_indices = [int(x.strip()) for x in raw.split(",")]
    else:
        idx = int(resp) - 1
        config.gradient_preset = keys[idx]
        preset = get_gradient_preset(config.gradient_preset)
        print(f"  Selected: {preset.name} ({preset.description})  {preset.swatches}")
        print("  (Indices will be resolved from game palette at render time)")

    config.stroke_width = _prompt_int(
        f"  Stroke width [{config.stroke_width}]: ", config.stroke_width)
    steps = _prompt_int("  Gradient steps [6]: ", 6)
    config._gradient_steps = steps  # stash for resolution


def _step_naming(config: WizardConfig) -> None:
    """Step 7b: Ask for the shape name and output .shp filename."""
    # --- Shape name (descriptive label) ---
    # Pre-populate from the preset name if the slot was from an archive/preset
    existing = FONT_SHAPES.get(config.slot)
    default_label = existing["name"] if existing else ""
    if default_label:
        print(f"\nShape name (descriptive label for slot {config.slot}):")
        name = input(f"  [{default_label}]: ").strip() or default_label
    else:
        print(f"\nShape name (descriptive label for slot {config.slot}):")
        name = input("  > ").strip()
    config.shape_name = name or f"Font slot {config.slot}"
    print(f"  Name: {config.shape_name}")

    # --- Output .shp filename ---
    safe = config.shape_name.lower().replace(" ", "_")
    safe = "".join(c for c in safe if c.isalnum() or c == "_")
    ttf_label = config.ttf_key or Path(config.ttf_path or "custom").stem
    default_shp = f"font{config.slot}_{safe}_{ttf_label}.shp"
    path = input(f"  Output .shp filename [{default_shp}]: ").strip() or default_shp
    config.output_path = path
    print(f"  File: {config.output_path}")


def _step_output(
    config: WizardConfig,
    exult_paths: ExultGamePaths | None = None,
) -> tuple[str, str | None]:
    """Step 8: Choose output format and path."""
    print("\nOutput:")
    print("  [1] Single shape file (.shp)")
    print("  [2] Patch into Exult font archive")
    print("  [3] Both")
    resp = _prompt_choice("> ", ["1", "2", "3"])

    fmt_map = {"1": "shp", "2": "flex", "3": "both"}
    fmt = fmt_map[resp]

    # Resolve the Flex target if patching
    if fmt in ("flex", "both"):
        _step_resolve_flex_target(config, exult_paths)

    return fmt, config.output_path


def _step_resolve_flex_target(
    config: WizardConfig,
    exult_paths: ExultGamePaths | None = None,
) -> None:
    """Resolve the font VGA file path via exult.cfg or manual entry.

    If *exult_paths* was already parsed (from the game-selection step),
    reuses it instead of re-parsing.

    Populates ``config.flex_source`` with the validated path.
    """
    # If flex_source was already set (from archive selection step), confirm it
    if config.flex_source:
        exists = Path(config.flex_source).is_file()
        status = "EXISTS" if exists else "WILL BE CREATED"
        print(f"\n  Font archive target: {config.flex_source}  [{status}]")
        print(f"\n  [A] Accept")
        print("  [P] Enter a different path")
        resp = _prompt_choice("> ", ["a", "A", "p", "P"])
        if resp.upper() == "P":
            config.flex_source = input(
                "  Full path to font VGA file: "
            ).strip().strip('"').strip("'") or None
        return

    if exult_paths is None:
        # Try to find and parse exult.cfg now
        print("\n  Resolving Exult font archive...")
        cfg_file = find_exult_cfg()
        if cfg_file:
            print(f"  Found exult.cfg: {cfg_file}")
            try:
                exult_paths = parse_exult_cfg(cfg_file, config.game)
            except Exception as e:
                print(f"  WARNING: Failed to parse exult.cfg: {e}",
                      file=sys.stderr)
        else:
            print("  exult.cfg not found in default locations.")
            manual = input("  Path to exult.cfg (or Enter to skip): ").strip().strip('"').strip("'")
            if manual and Path(manual).is_file():
                try:
                    exult_paths = parse_exult_cfg(manual, config.game)
                except Exception as e:
                    print(f"  WARNING: Failed to parse: {e}", file=sys.stderr)

    if exult_paths:
        # Display what we found
        print(f"\n  Game:         {exult_paths.game}")
        print(f"  Game path:    {exult_paths.game_path or '(not set)'}")
        print(f"  Patch dir:    {exult_paths.patch_path or '(not set)'}")
        print(f"  Font config:  \"{exult_paths.font_config}\"")
        print(f"  Font file:    {exult_paths.font_filename}")
        if exult_paths.font_vga_path:
            exists = Path(exult_paths.font_vga_path).is_file()
            status = "EXISTS" if exists else "NOT FOUND"
            print(f"  Full path:    {exult_paths.font_vga_path}  [{status}]")
        if exult_paths.mods_path:
            print(f"  Mods dir:     {exult_paths.mods_path}")

        resolved_path = exult_paths.font_vga_path

        # Offer to accept, override, or enter mod path
        print(f"\n  [A] Accept: {resolved_path}")
        print("  [M] Use a mod's patch directory instead")
        print("  [P] Enter a custom path to the font archive")
        resp = _prompt_choice("> ", ["a", "A", "m", "M", "p", "P"])

        if resp.upper() == "M":
            mod_patch = input("  Mod patch directory: ").strip().strip('"').strip("'")
            if mod_patch:
                resolved_path = str(
                    Path(mod_patch) / exult_paths.font_filename
                )
                exists = Path(resolved_path).is_file()
                status = "EXISTS" if exists else "NOT FOUND"
                print(f"  Resolved: {resolved_path}  [{status}]")
        elif resp.upper() == "P":
            resolved_path = input("  Full path to font VGA file: ").strip().strip('"').strip("'")

        config.flex_source = resolved_path
    else:
        # No config — manual entry
        print("  Could not resolve font path from exult.cfg.")
        manual = input("  Full path to font VGA file: ").strip().strip('"').strip("'")
        config.flex_source = manual if manual else None


def _show_exult_info(game: str) -> ExultGamePaths | None:
    """Display Exult installation info for *game* after game selection.

    Returns the parsed paths if exult.cfg was found, else ``None``.
    """
    cfg_file = find_exult_cfg()
    if not cfg_file:
        print("\n  exult.cfg: not found (checked %LOCALAPPDATA%\\Exult, ~/.exult.cfg)")
        return None

    try:
        paths = parse_exult_cfg(cfg_file, game)
    except Exception as e:
        print(f"\n  exult.cfg: {cfg_file}")
        print(f"  WARNING: parse failed — {e}")
        return None

    print(f"\n  Exult config:  {cfg_file}")
    print(f"  Game path:     {paths.game_path or '(not set)'}")
    print(f"  Patch dir:     {paths.patch_path or '(not set)'}")
    print(f"  Font config:   \"{paths.font_config}\"  (exult.cfg → gameplay/fonts)")
    print(f"                 This setting controls which font file Exult loads from patch dirs:")
    print(f"                   disabled → fonts.vga  |  original → fonts_original.vga  |  serif → fonts_serif.vga")
    print(f"                 Current:  {paths.font_filename}")
    return paths


def _step_select_archive(
    exult_paths: ExultGamePaths | None,
) -> Path | None:
    """Scan the game directory for font VGA archives and let user pick one.

    Returns the selected archive path, or ``None`` if skipped.
    """
    if not exult_paths or not exult_paths.game_path:
        print("\n  No game path available — cannot scan for font archives.")
        manual = input(
            "  Enter path to a font VGA file (or Enter to skip): "
        ).strip().strip('"').strip("'")
        if manual and Path(manual).is_file():
            return Path(manual)
        return None

    archives = scan_font_archives(exult_paths.game_path)

    if not archives:
        print(f"\n  No *font*.vga files found under {exult_paths.game_path}")
        manual = input(
            "  Enter path to a font VGA file (or Enter to skip): "
        ).strip().strip('"').strip("'")
        if manual and Path(manual).is_file():
            return Path(manual)
        return None

    game_root = Path(exult_paths.game_path)
    print(f"\n  Font archives found under {exult_paths.game_path}:")
    for i, path in enumerate(archives, 1):
        try:
            rel = path.relative_to(game_root)
        except ValueError:
            rel = path
        exists_tag = "" if path.is_file() else "  [MISSING]"
        print(f"    [{i}] {rel}{exists_tag}")
    print(f"    [P] Enter a custom path")
    print(f"    [S] Skip — no source archive")

    valid = [str(i) for i in range(1, len(archives) + 1)] + ["p", "P", "s", "S"]
    resp = _prompt_choice("  Select font archive> ", valid)

    if resp.upper() == "S":
        return None
    if resp.upper() == "P":
        manual = input(
            "  Full path to font VGA file: "
        ).strip().strip('"').strip("'")
        return Path(manual) if manual else None

    return archives[int(resp) - 1]


# ---------------------------------------------------------------------------
# Wizard orchestrator
# ---------------------------------------------------------------------------

def run_wizard() -> int:
    """Run the interactive font creation wizard. Returns exit code."""
    try:
        # Step 1 — Game
        game = _step_game()

        # Show Exult installation info
        exult_paths = _show_exult_info(game)

        # Step 1b — Select font archive (scan game directory)
        source_archive = _step_select_archive(exult_paths)

        # Step 2 — Font slot
        slot, slot_data = _step_slot(game, source_archive)

        config = WizardConfig(game=game)

        # Pre-populate flex_source from archive selection
        if source_archive:
            config.flex_source = str(source_archive)

        if slot is not None and slot_data:
            config.slot = slot
            config.cell_height = slot_data["cell_height"]
            config.ink_height = slot_data.get("ink_height", slot_data["cell_height"] - 1)
            config.h_lead = slot_data["h_lead"]
            config.total_frames = slot_data["total_frames"]
            config.code_range = slot_data["frame_range"]
            config.render_method = slot_data.get("render_method", "mono")
            config.lut_key = slot_data.get("palette_lut")
        else:
            print("\n  The FONTS.VGA slot number determines where this shape")
            print("  is stored when patching a Flex archive (0-10 = existing,")
            print("  11+ = new slot).")
            config.slot = _prompt_int("  FONTS.VGA slot number: ", 0)
            config.total_frames = _prompt_int("  Total frames: ", 128)

        # Step 3 — Source font
        ttf_key, ttf_path = _step_ttf_source()
        config.ttf_key = ttf_key
        config.ttf_path = ttf_path

        # Step 4 — Rendering method
        method, lut_choice = _step_render_method()
        config.render_method = method
        if lut_choice:
            # Check if it's a file path or a built-in key
            if Path(lut_choice).is_file():
                config.lut_path = lut_choice
            else:
                config.lut_key = lut_choice

        # Step 5 — Dimensions
        ch, ih, hl = _step_dimensions(slot_data)
        config.cell_height = ch
        config.ink_height = ih
        config.h_lead = hl

        # Step 6 — Palette (mono/threshold) or hollow gradient config
        if config.render_method in ("mono", "threshold"):
            config.ink_index = _step_palette_mono()
        elif config.render_method == "hollow_gradient":
            _step_hollow_gradient(config)

        # Resolve gradient preset → palette indices (if a preset was chosen)
        if config.render_method == "hollow_gradient" and config.gradient_preset:
            _resolve_gradient_config(config,
                                     getattr(config, "_gradient_steps", 6))

        # Resolve TTF path
        font_path = _resolve_ttf(config)
        if font_path is None:
            print("ERROR: Could not resolve TTF font path.", file=sys.stderr)
            return 1

        # Auto-calibrate pixel size
        px_size = find_pixel_size_for_cap(str(font_path), config.ink_height)
        print(f"\n  Auto-calibrated pixel_size: {px_size}")

        # Render glyphs
        print("  Rendering glyphs...")
        code_range = range(config.code_range[0], config.code_range[1] + 1)
        is_mono = config.render_method in ("mono", "threshold")
        is_indexed = config.render_method == "hollow_gradient"

        if is_indexed:
            glyphs, _ = render_all_glyphs_hollow_gradient(
                str(font_path), config.cell_height,
                config.gradient_indices,
                stroke_width=config.stroke_width,
                stroke_index=config.stroke_index,
                code_range=code_range)
        elif is_mono:
            glyphs, _ = render_all_glyphs_mono(
                str(font_path), config.cell_height, code_range)
        else:
            glyphs, _ = render_all_glyphs_grayscale(
                str(font_path), config.cell_height, code_range)

        print(f"  Rendered {len(glyphs)} glyphs.")

        # Step 7 — Preview
        print("\nPreview — representative glyphs:")
        _show_preview(glyphs, is_mono=is_mono)
        _show_palette_info(config)

        resp = input("  [Y] Looks good — generate  [R] Redo  [Q] Quit\n> ").strip().upper()
        if resp == "Q":
            print("Cancelled.")
            return 0
        if resp == "R":
            print("(Restarting is not implemented yet — please re-run the command.)")
            return 0

        # Step 7b — Naming
        _step_naming(config)

        # Step 8 — Output
        fmt, output_path = _step_output(config, exult_paths)
        config.output_format = fmt
        config.output_path = output_path

        # Generate
        return _generate(config, glyphs, is_mono, is_indexed=is_indexed)

    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0


def _resolve_ttf(config: WizardConfig) -> Path | None:
    """Resolve the TTF path from config."""
    if config.ttf_path:
        p = Path(config.ttf_path)
        if p.is_file():
            return p
        return None
    if config.ttf_key:
        try:
            return get_ttf_path(config.ttf_key)
        except KeyError:
            return None
    return None


def _resolve_lut(config: WizardConfig) -> PaletteLUT:
    """Resolve the palette LUT from config."""
    if config.lut_path:
        return PaletteLUT.from_toml(config.lut_path)
    if config.lut_key:
        return get_builtin_lut(config.lut_key)
    # Default: mono mapping
    return PaletteLUT.mono(config.ink_index)


def _resolve_gradient_config(config: WizardConfig, steps: int = 6) -> None:
    """Resolve a gradient preset to palette indices on *config*.

    Loads the game palette, interpolates the preset hex colours into
    *steps* stops, and maps each to the nearest palette entry.  Updates
    ``config.gradient_indices`` and ``config.stroke_index`` in place.
    """
    preset = get_gradient_preset(config.gradient_preset)
    pal = resolve_game_palette(config.game, palette_file=config.palette_file)
    if pal is None:
        print(f"  WARNING: No game palette found for {config.game}; "
              "using preset hex colours with default greyscale palette.",
              file=sys.stderr)
        from titan.u7.palette import U7Palette
        pal = U7Palette.default_palette()

    indices, stroke = resolve_gradient_to_indices(preset, pal, steps=steps)
    config.gradient_indices = indices
    config.stroke_index = stroke

    # Show what was resolved
    print(f"  Gradient preset: {preset.name} ({preset.description})  {preset.swatches}")
    hex_colors = [f"#{pal.colors[i][0]:02x}{pal.colors[i][1]:02x}{pal.colors[i][2]:02x}"
                  for i in indices]
    resolved_swatches = []
    for i in indices:
        r, g, b = pal.colors[i]
        resolved_swatches.append(f"\033[38;2;{r};{g};{b}m\u2588\u2588\033[0m")
    print(f"  Resolved indices: {indices}")
    print(f"  Resolved colours: {' → '.join(hex_colors)}  {' '.join(resolved_swatches)}")
    print(f"  Stroke index: {stroke} "
          f"(#{pal.colors[stroke][0]:02x}{pal.colors[stroke][1]:02x}{pal.colors[stroke][2]:02x})")


def _generate(
    config: WizardConfig,
    glyphs: dict[int, np.ndarray],
    is_mono: bool,
    *,
    is_indexed: bool = False,
) -> int:
    """Encode glyphs into a U7Shape and write output files."""
    lut = _resolve_lut(config)

    # Derive space width from rendered glyphs — use ~half of median
    # glyph width, clamped to a sensible range.
    widths = [g.shape[1] for g in glyphs.values() if g.shape[1] > 1]
    if widths:
        median_w = sorted(widths)[len(widths) // 2]
        space_w = max(median_w // 2, 2)
    else:
        space_w = max(config.cell_height // 3, 2)

    # Determine preferred preview glyph for Exult Studio frame 65.
    # Maps font type → first letter of the script name.
    _PREVIEW_PREF: dict[str | None, tuple[int, ...]] = {
        "gargish":          (71,),   # 'G'
        "ophidean":         (83,),   # 'S' (Serpentine)
        "brit_plaques":     (82,),   # 'R' (Runic)
        "brit_plaquesSmall":(82,),
        "brit_signs":       (82,),
    }
    preview_pref = _PREVIEW_PREF.get(config.ttf_key, ())

    shape, preview_src = glyphs_to_shape(
        glyphs,
        config.total_frames,
        lut,
        ink_index=config.ink_index,
        is_mono=is_mono,
        is_indexed=is_indexed,
        cell_height=config.cell_height,
        space_width=space_w,
        preview_preferred=preview_pref,
    )

    print(f"  Encoded {len(shape.frames)} frames.")
    if preview_src is not None:
        label = chr(preview_src) if 33 <= preview_src <= 126 else f"#{preview_src}"
        print(f"  Frame {EXULT_STUDIO_PREVIEW_FRAME} ('A') was empty — "
              f"copied glyph '{label}' (frame {preview_src}) as "
              f"Exult Studio preview placeholder.")

    data = shape.to_bytes()

    if config.output_format in ("shp", "both"):
        out = config.output_path or f"font{config.slot}.shp"
        with open(out, "wb") as f:
            f.write(data)
        print(f"  Shape written: {out} ({len(data):,} bytes)")

    if config.output_format in ("flex", "both"):
        flex_src = config.flex_source
        if not flex_src:
            flex_src = input("  Path to font VGA file: ").strip()
        if flex_src and Path(flex_src).is_file():
            from titan.u7.flex import U7FlexArchive
            archive = U7FlexArchive.from_file(flex_src)
            # Auto-extend if the slot is beyond the current record count
            while len(archive.records) <= config.slot:
                archive.records.append(b'')
            archive.records[config.slot] = data
            archive.save(flex_src)
            print(f"  Patched font archive: {flex_src}")
        elif flex_src:
            # File doesn't exist yet — create a new archive
            from titan.u7.flex import U7FlexArchive
            archive = U7FlexArchive()
            archive.title = config.shape_name or f"Font slot {config.slot}"
            while len(archive.records) <= config.slot:
                archive.records.append(b'')
            archive.records[config.slot] = data
            archive.save(flex_src)
            print(f"  Created font archive: {flex_src}")
        else:
            print("  WARNING: No font archive path provided, skipping Flex output.",
                  file=sys.stderr)

    print("\nDone!")
    return 0


# ---------------------------------------------------------------------------
# Non-interactive config mode
# ---------------------------------------------------------------------------

def run_from_config(config_path: str, output_override: str | None = None) -> int:
    """Run font creation from a TOML config file (non-interactive)."""
    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    config = WizardConfig()

    # [target]
    target = data.get("target", {})
    config.game = target.get("game", "BG").upper()
    config.slot = target.get("slot", 0)

    # Apply preset defaults if slot is known
    if config.slot in FONT_SHAPES:
        preset = FONT_SHAPES[config.slot]
        config.cell_height = preset["cell_height"]
        config.ink_height = preset["ink_height"]
        config.h_lead = preset["h_lead"]
        config.total_frames = preset["total_frames"]
        config.code_range = tuple(preset["frame_range"])
        config.render_method = preset["render_method"]
        config.lut_key = preset.get("palette_lut")

    # Override with explicit config values
    config.cell_height = target.get("cell_height", config.cell_height)
    config.ink_height = target.get("ink_height", config.ink_height)
    config.h_lead = target.get("h_lead", config.h_lead)

    # [source]
    source = data.get("source", {})
    font_ref = source.get("font", "dosVga437")
    if font_ref in BUNDLED_TTFS:
        config.ttf_key = font_ref
    else:
        config.ttf_path = font_ref

    # [rendering]
    rendering = data.get("rendering", {})
    config.render_method = rendering.get("method", config.render_method)
    lut_ref = rendering.get("lut")
    if lut_ref:
        if Path(lut_ref).is_file():
            config.lut_path = lut_ref
        else:
            config.lut_key = lut_ref
    config.threshold = rendering.get("threshold", config.threshold)
    config.stroke_width = rendering.get("stroke_width", config.stroke_width)
    config.stroke_index = rendering.get("stroke_index", config.stroke_index)
    config.gradient_preset = rendering.get("gradient_preset", config.gradient_preset)
    grad = rendering.get("gradient_indices")
    if grad is not None:
        config.gradient_indices = list(grad)

    # [palette]
    pal = data.get("palette", {})
    config.ink_index = pal.get("ink", config.ink_index)
    config.transparent_index = pal.get("transparent", config.transparent_index)
    config.palette_file = pal.get("file", config.palette_file)

    # [output]
    output = data.get("output", {})
    config.output_format = output.get("format", "shp")
    config.output_path = output_override or output.get("path")
    config.flex_source = output.get("flex_source")

    # Show palette info if available
    _show_palette_info(config)

    # Resolve gradient preset → palette indices (if set)
    if config.render_method == "hollow_gradient" and config.gradient_preset:
        steps = rendering.get("gradient_steps", 6)
        _resolve_gradient_config(config, steps)

    # Resolve TTF
    font_path = _resolve_ttf(config)
    if font_path is None:
        print(f"ERROR: Font not found: {font_ref}", file=sys.stderr)
        return 1

    # Render
    code_range = range(config.code_range[0], config.code_range[1] + 1)
    is_mono = config.render_method in ("mono", "threshold")
    is_indexed = config.render_method == "hollow_gradient"

    if is_indexed:
        glyphs, px_size = render_all_glyphs_hollow_gradient(
            str(font_path), config.cell_height,
            config.gradient_indices,
            stroke_width=config.stroke_width,
            stroke_index=config.stroke_index,
            code_range=code_range)
    elif is_mono:
        glyphs, px_size = render_all_glyphs_mono(
            str(font_path), config.cell_height, code_range)
    else:
        glyphs, px_size = render_all_glyphs_grayscale(
            str(font_path), config.cell_height, code_range)

    print(f"Rendered {len(glyphs)} glyphs at pixel_size={px_size}")

    return _generate(config, glyphs, is_mono, is_indexed=is_indexed)
