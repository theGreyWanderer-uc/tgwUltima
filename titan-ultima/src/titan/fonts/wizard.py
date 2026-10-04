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
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import freetype

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
    PaletteLUT,
    get_builtin_lut,
    list_builtin_luts,
    resolve_game_palette,
    list_gradient_presets,
    get_gradient_preset,
    resolve_gradient_to_indices,
)
from titan.fonts.exult_cfg import (
    find_exult_cfg,
    parse_exult_cfg,
    resolve_font_vga_path,
    scan_font_archives,
    ExultGamePaths,
)
from titan.fonts.renderer import (
    render_all_glyphs_mono,
    render_all_glyphs_grayscale,
    render_all_glyphs_hollow_gradient,
)
from titan.fonts.encoder import (
    glyphs_to_shape,
    glyph_to_font_frame,
    EXULT_STUDIO_PREVIEW_FRAME,
)
from titan.fonts.encoder import GlyphBitmap
from titan.fonts.archive import read_font_archive, game_paths


@dataclass
class WizardConfig:
    """All parameters needed to produce a font shape."""

    game: str = "BG"  # "BG" or "SI"
    slot: int = 0  # FONTS.VGA shape index
    cell_height: int = 14
    ink_height: int = 13
    h_lead: int = -2
    total_frames: int = 128

    # Source font
    ttf_key: Optional[str] = None  # Built-in key (e.g. "dosVga437")
    ttf_path: Optional[str] = None  # Custom TTF path

    # Rendering
    render_method: str = "mono"  # "mono", "lut", "threshold", "hollow_gradient"
    lut_key: Optional[str] = None  # Built-in LUT key
    lut_path: Optional[str] = None  # Custom LUT TOML path
    threshold: int = 128  # Grayscale threshold (for "threshold")

    # Hollow gradient options
    gradient_preset: Optional[str] = None  # preset key (e.g. "warm_flame")
    gradient_steps: int = 6
    allow_cycling: bool = False
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
    layout: str = "standard"  # "standard" or path to mapping TOML
    code_range: tuple[int, int] = (0x21, 0x7E)

    # Naming
    shape_name: Optional[str] = None  # Descriptive name (e.g. "Pagan gold title")

    # Output
    output_format: str = "shp"  # "shp", "flex", "both"
    output_path: Optional[str] = None
    flex_source: Optional[str] = None  # Path to FONTS.VGA for patching
    template_archive: Optional[str] = None
    base_archive: Optional[str] = None
    force: bool = False


# ---------------------------------------------------------------------------
# ASCII-art preview helper
# ---------------------------------------------------------------------------

_INK = "\u2588"  # █
_EMPTY = "\u00b7"  # ·


def _preview_glyph(
    bmp: np.ndarray, is_mono: bool = True, *, is_indexed: bool = False
) -> list[str]:
    """Render a glyph bitmap as ASCII art lines."""
    lines: list[str] = []
    for row in bmp:
        line = ""
        for px in row:
            if is_indexed:
                line += _INK if px != 255 else _EMPTY
            elif is_mono:
                line += _INK if px else _EMPTY
            else:
                line += _INK if px > 0 else _EMPTY
        lines.append(line)
    return lines


def _show_preview(
    glyphs: dict[int, np.ndarray],
    is_mono: bool = True,
    *,
    is_indexed: bool = False,
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
        art = _preview_glyph(bmp, is_mono, is_indexed=is_indexed)
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
    elif config.render_method == "hollow_gradient":
        indices.update(config.gradient_indices)
        indices.add(config.stroke_index)
    else:
        lut = _resolve_lut(config)
        indices.update(idx for _, _, idx in lut.mapping if idx != lut.transparent)

    if not indices:
        indices.add(config.ink_index)

    for idx in sorted(indices):
        r, g, b = pal.colors[idx]
        print(f"    index {idx:>3d}: #{r:02x}{g:02x}{b:02x}  ({r}, {g}, {b})")
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


def _prompt_int(prompt: str, default: int, minimum: int = 0, maximum: int = 255) -> int:
    """Prompt for an integer with a default."""
    while True:
        resp = input(prompt).strip()
        try:
            value = int(resp) if resp else default
            if minimum <= value <= maximum:
                return value
            print(f"  Please enter a value within {minimum}-{maximum}.")
        except ValueError:
            print("  Please enter a valid integer.")


def _prompt_file(prompt: str, *, optional: bool = False) -> str:
    while True:
        value = input(prompt).strip().strip('"').strip("'")
        if not value and optional:
            return ""
        path = Path(value).expanduser()
        if value and path.is_file():
            return str(path)
        print(f"  File not found: {value}")


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


def _read_archive_slots(
    archive_path: Path, game: str = "BG", base_archive: str | None = None
) -> dict[int, dict]:
    """Read a font Flex archive and extract live slot data.

    Returns a dict keyed by slot number with ``name``, ``cell_height``,
    ``h_lead``, ``total_frames``, and ``frame_range`` for each non-empty
    record.  Falls back to the static preset name if the slot is known.
    """
    from titan.u7.shape import U7Shape

    archive = read_font_archive(archive_path, game=game, base_archive=base_archive)
    presets = {**FONT_SHAPES}  # for name/h_lead lookups

    slots: dict[int, dict] = {}
    for idx, rec in enumerate(archive.records):
        if not rec:
            continue
        shape = U7Shape.from_data(rec, strict=True)
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
        nonempty = [
            i
            for i, f in enumerate(shape.frames)
            if f.pixels is not None and np.any(f.pixels != 255)
        ]
        if nonempty:
            frame_range = (nonempty[0], nonempty[-1])
        else:
            frame_range = (0x21, min(0x7E, len(shape.frames) - 1))

        slots[idx] = {
            "name": name,
            "cell_height": cell_h,
            "h_lead": h_lead,
            "total_frames": len(shape.frames),
            "frame_range": frame_range,
        }

    return slots


def _step_slot(
    game: str, source_archive: Path | None = None, base_archive: str | None = None
) -> tuple[int | None, dict | None]:
    """Step 2: Choose font slot.

    Returns ``(slot_number, slot_data)`` or ``(None, None)`` for custom.
    *slot_data* contains at minimum ``cell_height``, ``h_lead``,
    ``total_frames``, and ``frame_range``.
    """
    # Use live data from archive if available, else static presets
    if source_archive and source_archive.is_file():
        live_slots = _read_archive_slots(source_archive, game, base_archive)
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
    print("  Selecting a slot pre-fills cell height, h-lead,")
    print(f"  and frame count from the {source_label}.")
    print("  " + "-" * 60)
    print(f"  {'Slot':>4}  {'Name':<30}  {'Cell H':>6}  {'Frames':>6}  {'H-lead':>6}")
    print("  " + "-" * 60)
    for slot in sorted(slots):
        p = slots[slot]
        print(
            f"  {slot:>4}  {p['name']:<30}  {p['cell_height']:>4} px  {p['total_frames']:>6}  {p['h_lead']:>6}"
        )
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
        path = _prompt_file("  TTF file path: ")
        freetype.Face(path)
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
    print("  [F] Custom LUT file (TOML)")

    valid = [str(i) for i in range(1, len(lut_keys) + 1)] + ["f", "F"]
    resp2 = _prompt_choice("> ", valid)
    if resp2.upper() == "F":
        path = _prompt_file("  LUT TOML path: ")
        PaletteLUT.from_toml(path)
        return "lut", path
    return "lut", lut_keys[int(resp2) - 1]


def _step_dimensions(preset: dict | None) -> tuple[int, int, int]:
    """Step 5: Confirm/override dimensions."""
    if preset:
        ch = preset["cell_height"]
        ih = preset.get("ink_height", ch - 1)
        hl = preset["h_lead"]
        print("\nDimensions (from preset):")
    else:
        ch = 14
        ih = 13
        hl = -2
        print("\nDimensions (custom):")

    print(f"  Cell height:  [{ch}]")
    print(f"  Ink height:   [{ih}]")
    print(f"  Exult h-lead: [{hl}] (fixed by font slot; not stored in the shape)")

    resp = input("\nOverride any values? [y/N] ").strip().lower()
    if resp == "y":
        ch = _prompt_int(f"  Cell height [{ch}]: ", ch, 2, 200)
        ih = _prompt_int(
            f"  Ink height [{min(ih, ch - 1)}]: ", min(ih, ch - 1), 1, ch - 1
        )

    return ch, ih, hl


def _step_palette_mono() -> int:
    """Step 6: Choose ink palette index (mono/threshold only)."""
    print("\nInk palette index:")
    print("  [0]   Black (default)")
    print("  [15]  White")
    print("        Or enter any ink index 0-254 (255 is transparency)")
    return _prompt_int("> ink index [0]: ", 0, 0, 254)


def _step_hollow_gradient(config: WizardConfig) -> None:
    """Step 6b: Configure hollow gradient parameters via preset or manual."""
    keys = list_gradient_presets()
    print("\nGradient preset:")
    for i, key in enumerate(keys, 1):
        p = get_gradient_preset(key)
        print(f"  [{i:2d}] {p.name:24s} {p.description}  {p.swatches}")
    print("  [M]  Manual (enter palette indices directly)")

    valid = [str(i) for i in range(1, len(keys) + 1)] + ["m", "M"]
    resp = _prompt_choice("> ", valid)

    if resp.upper() == "M":
        config.gradient_preset = None
        # Manual entry — raw palette indices
        config.stroke_index = _prompt_int(
            f"  Stroke index [{config.stroke_index}]: ", config.stroke_index, 0, 254
        )
        while True:
            raw = input(
                f"  Gradient indices (comma-separated) [{','.join(str(i) for i in config.gradient_indices)}]: "
            ).strip()
            if not raw:
                break
            try:
                indices = [int(x.strip()) for x in raw.split(",")]
                if not indices or any(not 0 <= i <= 254 for i in indices):
                    raise ValueError
                config.gradient_indices = indices
                break
            except ValueError:
                print("  Enter comma-separated palette indices within 0-254.")
    else:
        idx = int(resp) - 1
        config.gradient_preset = keys[idx]
        preset = get_gradient_preset(config.gradient_preset or "")
        print(f"  Selected: {preset.name} ({preset.description})  {preset.swatches}")
        print("  (Indices will be resolved from game palette at render time)")
        default = "Y" if config.allow_cycling else "N"
        config.allow_cycling = (
            _prompt_choice(
                f"  Allow cycling colours (224-254)? [{default}] ",
                ["y", "Y", "n", "N"],
                default,
            ).upper()
            == "Y"
        )

    config.stroke_width = _prompt_int(
        f"  Stroke width [{config.stroke_width}]: ",
        config.stroke_width,
        0,
        config.cell_height,
    )
    config.gradient_steps = _prompt_int(
        f"  Gradient steps [{config.gradient_steps}]: ", config.gradient_steps, 1, 256
    )


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


def _step_shape_path(config: WizardConfig) -> None:
    # --- Output .shp filename ---
    safe = (config.shape_name or f"Font slot {config.slot}").lower().replace(" ", "_")
    safe = "".join(c for c in safe if c.isalnum() or c == "_")
    ttf_label = config.ttf_key or Path(config.ttf_path or "custom").stem
    default_shp = f"font{config.slot}_{safe}_{ttf_label}.shp"
    path = input(f"  Output .shp filename [{default_shp}]: ").strip() or default_shp
    config.output_path = path
    print(f"  File: {config.output_path}")


def _step_output(
    config: WizardConfig,
    exult_paths: ExultGamePaths | None = None,
    output_override: str | None = None,
) -> tuple[str, str | None]:
    """Step 8: Choose output format and path."""
    print("\nOutput:")
    print("  [1] Single shape file (.shp)")
    print("  [2] Patch into Exult font archive")
    print("  [3] Both")
    resp = _prompt_choice("> ", ["1", "2", "3"])

    fmt_map = {"1": "shp", "2": "flex", "3": "both"}
    fmt = fmt_map[resp]

    if fmt in ("shp", "both"):
        if output_override:
            config.output_path = output_override
        else:
            _step_shape_path(config)

    # Resolve the Flex target if patching
    if fmt in ("flex", "both"):
        if fmt == "flex" and output_override:
            config.flex_source = output_override
        else:
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
        print("\n  [A] Accept")
        print("  [P] Enter a different path")
        resp = _prompt_choice("> ", ["a", "A", "p", "P"])
        if resp.upper() == "P":
            config.flex_source = (
                input("  Full path to font VGA file: ").strip().strip('"').strip("'")
                or None
            )
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
                print(f"  WARNING: Failed to parse exult.cfg: {e}", file=sys.stderr)
        else:
            print("  exult.cfg not found in default locations.")
            manual = (
                input("  Path to exult.cfg (or Enter to skip): ")
                .strip()
                .strip('"')
                .strip("'")
            )
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
        print(f'  Font config:  "{exult_paths.font_config}"')
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
                resolved_path = str(Path(mod_patch) / exult_paths.font_filename)
                exists = Path(resolved_path).is_file()
                status = "EXISTS" if exists else "NOT FOUND"
                print(f"  Resolved: {resolved_path}  [{status}]")
        elif resp.upper() == "P":
            resolved_path = (
                input("  Full path to font VGA file: ").strip().strip('"').strip("'")
            )

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
    print(f'  Font config:   "{paths.font_config}"  (exult.cfg → gameplay/fonts)')
    print(
        "                 This setting controls which font file Exult loads from patch dirs:"
    )
    print(
        "                   disabled → fonts.vga  |  original → fonts_original.vga  |  serif → fonts_serif.vga"
    )
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
        manual = _prompt_file(
            "  Enter path to a font VGA file (or Enter to skip): ", optional=True
        )
        if manual:
            return Path(manual)
        return None

    archives = scan_font_archives(exult_paths.game_path)

    if not archives:
        print(f"\n  No *font*.vga files found under {exult_paths.game_path}")
        manual = _prompt_file(
            "  Enter path to a font VGA file (or Enter to skip): ", optional=True
        )
        if manual:
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
    print("    [P] Enter a custom path")
    print("    [S] Skip — no source archive")

    valid = [str(i) for i in range(1, len(archives) + 1)] + ["p", "P", "s", "S"]
    resp = _prompt_choice("  Select font archive> ", valid)

    if resp.upper() == "S":
        return None
    if resp.upper() == "P":
        return Path(_prompt_file("  Full path to font VGA file: "))

    return archives[int(resp) - 1]


# ---------------------------------------------------------------------------
# Wizard orchestrator
# ---------------------------------------------------------------------------


def _engine_h_lead(slot: int) -> int:
    # Exult shapes/fontvga.cc, Fonts_vga_file::init().
    leads = (-2, -1, 0, -1, 0, 0, -1, -2, -1, -1)
    return leads[slot] if 0 <= slot < len(leads) else 0


def _validate_config(config: WizardConfig) -> None:
    def bounded(name: str, value: int, low: int, high: int) -> None:
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{name} must be an integer within {low}-{high}")

    if config.game not in ("BG", "SI"):
        raise ValueError("Game must be BG or SI")
    bounded("Font slot", config.slot, 0, 65535)
    bounded("Cell height", config.cell_height, 2, 200)
    bounded("Ink height", config.ink_height, 1, config.cell_height - 1)
    bounded("Total frames", config.total_frames, 33, 256)
    if len(config.code_range) != 2:
        raise ValueError("code_range must contain a first and last character code")
    bounded("First character", config.code_range[0], 0, config.total_frames - 1)
    bounded(
        "Last character",
        config.code_range[1],
        config.code_range[0],
        config.total_frames - 1,
    )
    bounded("Ink index", config.ink_index, 0, 254)
    bounded("Threshold", config.threshold, 1, 255)
    bounded("Stroke width", config.stroke_width, 0, config.cell_height)
    bounded("Stroke index", config.stroke_index, 0, 254)
    bounded("Gradient steps", config.gradient_steps, 1, 256)
    if not config.gradient_indices:
        raise ValueError("At least one gradient index is required")
    for index in config.gradient_indices:
        bounded("Gradient index", index, 0, 254)
    if type(config.transparent_index) is not int or config.transparent_index != 255:
        raise ValueError("U7 font transparency must be palette index 255")
    if type(config.h_lead) is not int or config.h_lead != _engine_h_lead(config.slot):
        raise ValueError(
            f"Exult fixes h_lead at {_engine_h_lead(config.slot)} for slot {config.slot}; it cannot be overridden in a shape"
        )
    if type(config.force) is not bool or type(config.allow_cycling) is not bool:
        raise ValueError("force and allow_cycling must be booleans")
    if config.render_method not in ("mono", "threshold", "lut", "hollow_gradient"):
        raise ValueError("Unknown rendering method")
    if config.output_format not in ("shp", "flex", "both"):
        raise ValueError("Output format must be shp, flex or both")
    if config.layout != "standard":
        raise ValueError("Only the standard character layout is supported")
    if config.render_method == "lut":
        if not (config.lut_key or config.lut_path):
            raise ValueError("LUT rendering requires a built-in LUT name or a LUT file")
        _resolve_lut(config)
    if config.palette_file:
        resolve_game_palette(config.game, config.palette_file)


def _render(config: WizardConfig) -> tuple[dict[int, np.ndarray], bool, bool]:
    _validate_config(config)
    font_path = _resolve_ttf(config)
    if font_path is None:
        raise ValueError(f"Font not found: {config.ttf_path or config.ttf_key}")
    if config.render_method == "hollow_gradient" and config.gradient_preset:
        _resolve_gradient_config(config, config.gradient_steps)
    codes = range(config.code_range[0], config.code_range[1] + 1)
    is_mono = config.render_method in ("mono", "threshold")
    is_indexed = config.render_method == "hollow_gradient"
    if is_indexed:
        glyphs, px_size = render_all_glyphs_hollow_gradient(
            str(font_path),
            config.cell_height,
            config.gradient_indices,
            stroke_width=config.stroke_width,
            stroke_index=config.stroke_index,
            code_range=codes,
            ink_height=config.ink_height,
        )
    elif config.render_method == "mono":
        glyphs, px_size = render_all_glyphs_mono(
            str(font_path),
            config.cell_height,
            codes,
            ink_height=config.ink_height,
        )
    else:
        glyphs, px_size = render_all_glyphs_grayscale(
            str(font_path),
            config.cell_height,
            codes,
            ink_height=config.ink_height,
        )
        if config.render_method == "threshold":
            glyphs = {
                code: (bitmap >= config.threshold).astype(np.uint8)
                for code, bitmap in glyphs.items()
            }
    if not glyphs or not any(
        np.any(g != (255 if is_indexed else 0)) for g in glyphs.values()
    ):
        raise ValueError("No visible glyphs were rendered with these settings")
    from titan.u7.shape_import import validate_u7_import_frame_size

    oversized = False
    for code, bitmap in glyphs.items():
        height, width = bitmap.shape
        validate_u7_import_frame_size(width, height, f"font character {code}")
        oversized |= width > 72 or height > 72
    if oversized:
        print("  WARNING: Font frames exceed 72x72 pixels.", file=sys.stderr)
    print(f"  Rendered {len(glyphs)} glyphs at pixel_size={px_size}")
    return glyphs, is_mono, is_indexed


def _mapped_preview(
    config: WizardConfig, glyphs: dict[int, np.ndarray], is_mono: bool, is_indexed: bool
) -> None:
    lut = _resolve_lut(config)
    mapped = (
        glyphs
        if is_indexed
        else {
            code: glyph_to_font_frame(
                GlyphBitmap(code, bitmap, is_mono), lut, config.ink_index
            ).pixels
            for code, bitmap in glyphs.items()
        }
    )
    print("\nPreview — representative glyphs (after palette mapping):")
    _show_preview(mapped, is_mono=False, is_indexed=True)
    _show_palette_info(config)


def _apply_output_override(config: WizardConfig, output_override: str | None) -> None:
    if output_override:
        if config.output_format == "flex":
            config.flex_source = output_override
        else:
            config.output_path = output_override


def run_wizard(
    output_override: str | None = None,
    *,
    force: bool = False,
    allow_cycling: bool = False,
    base_archive: str | None = None,
) -> int:
    """Run the original sequence, with a retry loop around font settings."""
    try:
        game = _step_game()
        exult_paths = _show_exult_info(game)
        source_archive = _step_select_archive(exult_paths)
        slot, slot_data = _step_slot(game, source_archive, base_archive)
        config = WizardConfig(
            game=game,
            force=force,
            allow_cycling=allow_cycling,
            base_archive=base_archive,
        )
        if source_archive:
            config.template_archive = str(source_archive)
        if slot is not None and slot_data:
            config.slot = slot
            config.cell_height = slot_data["cell_height"]
            config.ink_height = slot_data.get("ink_height", config.cell_height - 1)
            config.total_frames = slot_data["total_frames"]
            config.code_range = tuple(slot_data["frame_range"])
            config.render_method = slot_data.get("render_method", "mono")
            config.lut_key = slot_data.get("palette_lut")
        else:
            print("\n  The font slot determines where the shape is stored.")
            config.slot = _prompt_int("  FONTS.VGA slot number [0]: ", 0, 0, 65535)
            config.total_frames = _prompt_int("  Total frames [128]: ", 128, 33, 256)
            config.code_range = (32, min(126, config.total_frames - 1))
        config.h_lead = _engine_h_lead(config.slot)
        _use_exult_palette(config, exult_paths)
        while True:
            try:
                config.ttf_key, config.ttf_path = _step_ttf_source()
                config.render_method, lut_choice = _step_render_method()
                config.lut_path = config.lut_key = None
                if lut_choice:
                    if Path(lut_choice).is_file():
                        config.lut_path = lut_choice
                    else:
                        config.lut_key = lut_choice
                dimensions = dict(
                    cell_height=config.cell_height,
                    ink_height=config.ink_height,
                    h_lead=config.h_lead,
                )
                config.cell_height, config.ink_height, config.h_lead = _step_dimensions(
                    dimensions
                )
                if config.render_method in ("mono", "threshold"):
                    config.ink_index = _step_palette_mono()
                    if config.render_method == "threshold":
                        config.threshold = _prompt_int(
                            f"  Grayscale threshold [{config.threshold}]: ",
                            config.threshold,
                            1,
                            255,
                        )
                elif config.render_method == "hollow_gradient":
                    _step_hollow_gradient(config)
                glyphs, is_mono, is_indexed = _render(config)
                _mapped_preview(config, glyphs, is_mono, is_indexed)
            except (ValueError, OSError, KeyError, freetype.FT_Exception) as error:
                print(f"  ERROR: {error}", file=sys.stderr)
                if (
                    _prompt_choice(
                        "  [R] Retry font settings  [Q] Quit\n> ", ["R", "r", "Q", "q"]
                    ).upper()
                    == "Q"
                ):
                    return 1
                continue
            answer = _prompt_choice(
                "  [Y] Looks good — generate  [R] Redo  [Q] Quit\n> ",
                ["Y", "y", "R", "r", "Q", "q"],
            )
            if answer.upper() == "Q":
                print("Cancelled.")
                return 0
            if answer.upper() == "Y":
                break
        _step_naming(config)
        config.output_format, config.output_path = _step_output(
            config, exult_paths, output_override
        )
        _apply_output_override(config, output_override)
        if not config.force:
            for path in _output_paths(config):
                if path.exists():
                    answer = _prompt_choice(
                        f"  Replace {path}? [y/N] ", ["y", "Y", "n", "N"], "N"
                    )
                    if answer.upper() != "Y":
                        print("Cancelled.")
                        return 0
            config.force = True
        return _generate(config, glyphs, is_mono, is_indexed=is_indexed)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
    except (ValueError, OSError, KeyError, TypeError, freetype.FT_Exception) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


def _use_exult_palette(config: WizardConfig, paths: ExultGamePaths | None) -> None:
    if config.palette_file or not paths or not paths.static_path:
        return
    from titan.u7.shape_archive import find_archive

    palette = find_archive(Path(paths.static_path), "palettes.flx")
    if palette:
        config.palette_file = str(palette)


def _resolve_ttf(config: WizardConfig) -> Path | None:
    """Resolve the TTF path from config."""
    if config.ttf_path:
        p = Path(config.ttf_path).expanduser()
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
    preset = get_gradient_preset(config.gradient_preset or "")
    pal = resolve_game_palette(config.game, palette_file=config.palette_file)
    if pal is None:
        raise ValueError(
            f"No {config.game} palette found; supply palette.file to match gradient colours"
        )

    indices, stroke = resolve_gradient_to_indices(
        preset, pal, steps=steps, allow_cycling=config.allow_cycling
    )
    config.gradient_indices = indices
    config.stroke_index = stroke

    # Show what was resolved
    print(f"  Gradient preset: {preset.name} ({preset.description})  {preset.swatches}")
    hex_colors = [
        f"#{pal.colors[i][0]:02x}{pal.colors[i][1]:02x}{pal.colors[i][2]:02x}"
        for i in indices
    ]
    resolved_swatches = []
    for i in indices:
        r, g, b = pal.colors[i]
        resolved_swatches.append(f"\033[38;2;{r};{g};{b}m\u2588\u2588\033[0m")
    print(f"  Resolved indices: {indices}")
    print(
        f"  Resolved colours: {' → '.join(hex_colors)}  {' '.join(resolved_swatches)}"
    )
    print(
        f"  Stroke index: {stroke} "
        f"(#{pal.colors[stroke][0]:02x}{pal.colors[stroke][1]:02x}{pal.colors[stroke][2]:02x})"
    )


def _generate(
    config: WizardConfig,
    glyphs: dict[int, np.ndarray],
    is_mono: bool,
    *,
    is_indexed: bool = False,
) -> int:
    """Encode glyphs into a U7Shape and write output files."""
    _validate_config(config)
    lut = _resolve_lut(config)

    from titan.u7.shape_import import validate_u7_import_frame_size

    for code, bitmap in glyphs.items():
        if type(code) is not int or not 0 <= code < config.total_frames:
            raise ValueError("Glyph character code is outside the output frame range")
        height, width = bitmap.shape
        validate_u7_import_frame_size(width, height, f"font character {code}")

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
        "gargish": (71,),  # 'G'
        "ophidean": (83,),  # 'S' (Serpentine)
        "brit_plaques": (82,),  # 'R' (Runic)
        "brit_plaquesSmall": (82,),
        "brit_signs": (82,),
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
        ink_height=config.ink_height,
    )

    print(f"  Encoded {len(shape.frames)} frames.")
    if preview_src is not None:
        label = chr(preview_src) if 33 <= preview_src <= 126 else f"#{preview_src}"
        print(
            f"  Frame {EXULT_STUDIO_PREVIEW_FRAME} ('A') was empty — "
            f"copied glyph '{label}' (frame {preview_src}) as "
            f"Exult Studio preview placeholder."
        )

    data = shape.to_bytes()

    _write_outputs(config, data)
    print("\nDone!")
    return 0


def _output_paths(config: WizardConfig) -> list[Path]:
    paths: list[Path] = []
    if config.output_format in ("shp", "both"):
        paths.append(Path(config.output_path or f"font{config.slot}.shp").expanduser())
    if config.output_format in ("flex", "both"):
        if not config.flex_source:
            _, config.flex_source = resolve_font_vga_path(config.game)
        paths.append(Path(config.flex_source).expanduser())
    if len(paths) == 2 and paths[0].resolve() == paths[1].resolve():
        raise ValueError("Shape and archive outputs must use different paths")
    return paths


def _write_outputs(config: WizardConfig, data: bytes) -> None:
    from titan.u7.flex import U7FlexArchive
    from titan.u7.flex_shape_add import save_u7_flex_atomically
    from titan.u7.shape_validation import validate_u7_shape_data

    _validate_config(config)
    validate_u7_shape_data(data)
    paths = _output_paths(config)
    for path in paths:
        if path.exists() and not config.force:
            raise FileExistsError(
                f"Output exists: {path}; use --force or output.force = true to replace it"
            )
        if path.exists() and not path.is_file():
            raise ValueError(f"Output is not a file: {path}")
    # Read/validate the archive BEFORE writing either output; keep patch holes.
    archive = None
    if config.output_format in ("flex", "both"):
        target = paths[-1]
        archive = (
            U7FlexArchive.from_file(str(target), strict=True)
            if target.is_file()
            else U7FlexArchive()
        )
        if not target.is_file():
            archive.title = config.shape_name or f"Font slot {config.slot}"
        archive.records.extend([b""] * max(0, config.slot + 1 - len(archive.records)))
        archive.records[config.slot] = data
    if config.output_format in ("shp", "both"):
        output = paths[0]
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, output)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        print(f"  Shape written: {output} ({len(data):,} bytes)")
    if archive is not None:
        save_u7_flex_atomically(archive, paths[-1])
        print(f"  Font archive written: {paths[-1]}")


# ---------------------------------------------------------------------------
# Non-interactive config mode
# ---------------------------------------------------------------------------


def run_from_config(
    config_path: str,
    output_override: str | None = None,
    *,
    force: bool = False,
    allow_cycling: bool = False,
    base_archive: str | None = None,
) -> int:
    """Generate without prompts; recipe paths are relative to the recipe file."""
    try:
        recipe = Path(config_path).expanduser().resolve()
        with recipe.open("rb") as stream:
            data = tomllib.load(stream)

        def recipe_path(value: str | None) -> str | None:
            if value is None:
                return None
            if not isinstance(value, str) or not value.strip():
                raise ValueError("File paths must be non-empty strings")
            path = Path(value).expanduser()
            return str(path if path.is_absolute() else recipe.parent / path)

        target = data.get("target", {})
        config = WizardConfig()
        config.game = target.get("game", "BG").upper()
        config.slot = target.get("slot", 0)
        if type(config.slot) is not int:
            raise ValueError("Font slot must be an integer")
        preset = presets_for_game(config.game).get(config.slot)
        if preset:
            for name in ("cell_height", "ink_height", "total_frames", "render_method"):
                setattr(config, name, preset[name])
            config.code_range = tuple(preset["frame_range"])
            config.lut_key = preset.get("palette_lut")
        config.h_lead = _engine_h_lead(config.slot)
        for name in ("cell_height", "ink_height", "h_lead", "total_frames", "layout"):
            if name in target:
                setattr(config, name, target[name])
        if "cell_height" in target and "ink_height" not in target:
            config.ink_height = config.cell_height - 1
        if "code_range" in target:
            config.code_range = tuple(target["code_range"])
        source = data.get("source", {})
        font_ref = source.get("font", "dosVga437")
        if font_ref in BUNDLED_TTFS:
            config.ttf_key = font_ref
        else:
            config.ttf_path = recipe_path(font_ref)
        config.template_archive = recipe_path(source.get("archive"))
        config.base_archive = base_archive or recipe_path(source.get("base_archive"))
        if config.template_archive:
            slots = _read_archive_slots(
                Path(config.template_archive), config.game, config.base_archive
            )
            if config.slot in slots:
                live = slots[config.slot]
                for name in ("cell_height", "total_frames"):
                    if name not in target:
                        setattr(config, name, live[name])
                if "ink_height" not in target:
                    config.ink_height = config.cell_height - 1
                if "code_range" not in target:
                    config.code_range = tuple(live["frame_range"])
        rendering = data.get("rendering", {})
        for name in (
            "threshold",
            "stroke_width",
            "stroke_index",
            "gradient_preset",
            "gradient_steps",
            "gradient_indices",
            "allow_cycling",
        ):
            if name in rendering:
                setattr(config, name, rendering[name])
        config.allow_cycling = allow_cycling or config.allow_cycling
        config.render_method = rendering.get("method", config.render_method)
        lut_ref = rendering.get("lut")
        if lut_ref:
            if lut_ref in list_builtin_luts():
                config.lut_key = lut_ref
            else:
                config.lut_key = None
                config.lut_path = recipe_path(lut_ref)
        pal = data.get("palette", {})
        config.ink_index = pal.get("ink", config.ink_index)
        config.transparent_index = pal.get("transparent", config.transparent_index)
        config.palette_file = recipe_path(pal.get("file"))
        if not config.palette_file:
            _use_exult_palette(config, game_paths(config.game))
        output = data.get("output", {})
        config.output_format = output.get("format", "shp")
        config.output_path = recipe_path(output.get("path"))
        config.flex_source = recipe_path(output.get("flex_source"))
        if config.output_format == "flex" and not config.flex_source:
            config.flex_source = config.output_path
        config.force = force or output.get("force", False)
        config.shape_name = output.get("name")
        _apply_output_override(config, output_override)
        _validate_config(config)
        # Resolve output before rendering; never fall back to an input() prompt.
        _output_paths(config)
        glyphs, is_mono, is_indexed = _render(config)
        _show_palette_info(config)
        return _generate(config, glyphs, is_mono, is_indexed=is_indexed)
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        freetype.FT_Exception,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
