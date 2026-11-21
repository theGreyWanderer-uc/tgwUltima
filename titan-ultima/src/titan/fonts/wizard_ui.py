"""
Interactive wizard for U7 font shape creation (``titan u7 font-create``).

Walks the user through game selection, font slot, TTF source,
rendering method, dimensions, palette, preview, and output — then
generates the shape file. :func:`run_from_config` is the recipe (batch)
mode's terminal front end.

The work itself is in :mod:`titan.fonts.wizard`, which never prints or
prompts; this module calls it through the module object, so patching a
library function there also affects the wizard.
"""

from __future__ import annotations

__all__ = ["run_wizard", "run_from_config"]

import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Mapping

import numpy as np
import freetype

from titan.fonts import wizard as wiz
from titan.fonts.wizard import RenderedFont, WizardConfig
from titan.fonts.presets import (
    FONT_SHAPES,
    BUNDLED_TTFS,
    presets_for_game,
)
from titan.fonts.palette import (
    PaletteLUT,
    get_builtin_lut,
    list_builtin_luts,
    list_gradient_presets,
    get_gradient_preset,
)
from titan.fonts.exult_cfg import (
    find_exult_cfg,
    parse_exult_cfg,
    scan_font_archives,
    ExultGamePaths,
)
from titan.fonts.encoder import EXULT_STUDIO_PREVIEW_FRAME
from titan.u7.target_picker import game_targets, select_target
from titan import _wizard_ui as ui
from titan._image_preview import open_preview
from titan.fonts.preview import preview_items, preview_sheet, validate_preview_text
from titan.u7.palette import U7Palette
from titan.errors import exit_code


# ---------------------------------------------------------------------------
# ASCII-art preview helper
# ---------------------------------------------------------------------------

_INK = "█"  # █
_EMPTY = "·"  # ·


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
    palette: U7Palette | None = None,
    preview_text: str | None = None,
    h_lead: int = 0,
) -> None:
    """Print representative glyphs, coloured when mapped palette data is available."""
    available = preview_items(glyphs, preview_text, h_lead)

    if not available:
        print("  (no glyphs to preview)")
        return

    # Render each glyph as ASCII art
    rendered: list[tuple[str, list[str]]] = []
    for label, bmp in available:
        art = _preview_glyph(bmp, is_mono, is_indexed=is_indexed)
        rendered.append((label, art))

    # Find max height for alignment
    max_h = max(len(art) for _, art in rendered)

    # Print labels
    labels = "  ".join(f"{lbl:<{len(art[0]) + 2}}" for lbl, art in rendered)
    print(f"\n  {labels}")

    # Print rows
    for row_idx in range(max_h):
        if palette is not None and is_indexed:
            fragments = []
            for _, bitmap in available:
                fragments.append(("", "  "))
                if row_idx >= bitmap.shape[0]:
                    fragments.append(("", " " * bitmap.shape[1]))
                    continue
                for px in bitmap[row_idx]:
                    if px == 255:
                        fragments.append(("fg:#a0a0a0 bg:#505050", _EMPTY))
                    else:
                        r, g, b = palette.colors[px]
                        fragments.append(
                            (f"fg:#{r:02x}{g:02x}{b:02x} bg:#505050", _INK)
                        )
            ui.print_coloured(fragments)
            continue
        parts: list[str] = []
        for _, art in rendered:
            if row_idx < len(art):
                parts.append(f"  {art[row_idx]}")
            else:
                parts.append("  " + " " * len(art[0]))
        print("".join(parts))
    print()


def _swatch_fragments(
    label: str, colours: list[str], *, label_style: str = ""
) -> list[tuple[str, str]]:
    fragments = [(label_style, label)]
    for colour in colours:
        fragments.extend([(f"bg:{colour}", "  "), ("", " ")])
    return fragments


def _print_swatches(label: str, colours: list[str]) -> None:
    ui.print_coloured(_swatch_fragments(label, colours))


def _show_palette_info(config: "WizardConfig") -> None:
    """Show palette color info for the indices used by the current LUT."""
    pal = wiz.game_palette(config)
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
        lut = wiz.resolve_lut(config)
        indices.update(idx for _, _, idx in lut.mapping if idx != lut.transparent)

    if not indices:
        indices.add(config.ink_index)

    for idx in sorted(indices):
        r, g, b = pal.colors[idx]
        _print_swatches(
            f"    index {idx:>3d}: #{r:02x}{g:02x}{b:02x}  ({r}, {g}, {b})  ",
            [f"#{r:02x}{g:02x}{b:02x}"],
        )
    print()


def _prompt_choice(
    prompt: str,
    choices: list[str],
    default: str = "",
    *,
    labels: Mapping[str, str | list[tuple[str, str]]] | None = None,
    message: str | None = None,
) -> str:
    """Simple numbered-choice prompt."""
    return ui.choice(prompt, choices, default, labels=labels, message=message)


def _prompt_int(prompt: str, default: int, minimum: int = 0, maximum: int = 255) -> int:
    """Prompt for an integer with a default."""
    while True:
        resp = ui.text(prompt, str(default)).strip()
        try:
            value = int(resp) if resp else default
            if minimum <= value <= maximum:
                return value
            print(f"  Please enter a value within {minimum}-{maximum}.")
        except ValueError:
            print("  Please enter a valid integer.")


def _prompt_file(prompt: str, *, optional: bool = False) -> str:
    while True:
        value = ui.path(prompt).strip().strip('"').strip("'")
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
    ui.legacy_menu("\nWhich game?", "  [1] Black Gate", "  [2] Serpent Isle")
    resp = _prompt_choice(
        "> ",
        ["1", "2"],
        message="Game flavour:",
        labels={"1": "Black Gate", "2": "Serpent Isle"},
    )
    return "BG" if resp == "1" else "SI"


def _step_slot(
    game: str,
    source_archive: Path | None = None,
    base_archive: str | None = None,
    *,
    paths: ExultGamePaths | None = None,
    infer_base: bool = True,
) -> tuple[int | None, dict | None]:
    """Step 2: Choose font slot.

    Returns ``(slot_number, slot_data)`` or ``(None, None)`` for custom.
    *slot_data* contains at minimum ``cell_height``, ``h_lead``,
    ``total_frames``, and ``frame_range``.
    """
    # Use live data from archive if available, else static presets
    if source_archive and source_archive.is_file():
        live_slots = wiz.read_archive_slots(
            source_archive,
            game,
            base_archive,
            paths=paths,
            infer_base=infer_base,
            install=_install_for(game),
        )
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
    ui.legacy_menu(
        "  " + "-" * 60,
        f"  {'Slot':>4}  {'Name':<30}  {'Cell H':>6}  {'Frames':>6}  {'H-lead':>6}",
        "  " + "-" * 60,
    )
    for slot in sorted(slots):
        p = slots[slot]
        ui.legacy_menu(
            f"  {slot:>4}  {p['name']:<30}  {p['cell_height']:>4} px  {p['total_frames']:>6}  {p['h_lead']:>6}"
        )
    ui.legacy_menu("  " + "-" * 60, "  [C] Custom (set all dimensions manually)")

    valid = [str(s) for s in sorted(slots)] + ["c", "C"]
    resp = _prompt_choice(
        "> ",
        valid,
        message="Font slot to use as a template:",
        labels={
            **{
                str(
                    slot
                ): f"{slot}: {p['name']} — {p['cell_height']}px, {p['total_frames']} frames"
                for slot, p in slots.items()
            },
            "C": "Custom (set dimensions manually)",
        },
    )
    if resp.upper() == "C":
        return None, None
    chosen = int(resp)
    return chosen, slots[chosen]


def _step_ttf_source() -> tuple[str | None, str | None]:
    """Step 3: Choose source font. Returns (ttf_key, custom_path)."""
    print("\nSource TrueType font:")
    ui.legacy_menu("  Built-in:")
    keys = list(BUNDLED_TTFS.keys())
    for i, key in enumerate(keys, 1):
        entry = BUNDLED_TTFS[key]
        ui.legacy_menu(f"  [{i}] {entry['label']}")
    ui.legacy_menu("\n  Custom:", "  [P] Path to a TTF file")

    valid = [str(i) for i in range(1, len(keys) + 1)] + ["p", "P"]
    resp = _prompt_choice(
        "> ",
        valid,
        message="Source TrueType font:",
        labels={
            **{str(i): BUNDLED_TTFS[key]["label"] for i, key in enumerate(keys, 1)},
            "P": "Custom TTF file",
        },
    )

    if resp.upper() == "P":
        path = _prompt_file("  TTF file path: ")
        freetype.Face(path)
        return None, path

    idx = int(resp) - 1
    return keys[idx], None


def _step_render_method() -> tuple[str, str | None]:
    """Step 4: Choose rendering method. Returns (method, lut_key)."""
    print("\nRendering method:")
    methods = {
        "1": "Hinted mono (crisp single-colour pixels)",
        "2": "LUT downscale (multiple palette shades)",
        "3": "Grayscale threshold (configurable cutoff)",
        "4": "Hollow gradient (outline and gradient fill)",
    }
    ui.legacy_menu(*(f"  [{key}] {value}" for key, value in methods.items()))
    resp = _prompt_choice(
        "> ", ["1", "2", "3", "4"], message="Rendering method:", labels=methods
    )

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
        ui.legacy_menu(f"  [{i}] {lut.name}")
    ui.legacy_menu("  [F] Custom LUT file (TOML)")

    valid = [str(i) for i in range(1, len(lut_keys) + 1)] + ["f", "F"]
    resp2 = _prompt_choice(
        "> ",
        valid,
        message="Palette lookup table:",
        labels={
            **{str(i): get_builtin_lut(key).name for i, key in enumerate(lut_keys, 1)},
            "F": "Custom LUT file (TOML)",
        },
    )
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

    resp = _prompt_choice(
        "\nOverride any values? [y/N] ", ["y", "Y", "n", "N"], "N"
    ).lower()
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
        if not ui.menus_enabled():
            _print_swatches(f"  [{i:2d}] {p.name:24s} {p.description}  ", p.colors)
    ui.legacy_menu("  [M]  Manual (enter palette indices directly)")

    valid = [str(i) for i in range(1, len(keys) + 1)] + ["m", "M"]
    resp = _prompt_choice(
        "> ",
        valid,
        message="Gradient preset:",
        labels={
            **{
                str(i): _swatch_fragments(
                    f"{get_gradient_preset(key).name:24s} ",
                    get_gradient_preset(key).colors,
                    label_style="class:choice-label",
                )
                for i, key in enumerate(keys, 1)
            },
            "M": "Manual palette indices",
        },
    )

    if resp.upper() == "M":
        config.gradient_preset = None
        # Manual entry — raw palette indices
        config.stroke_index = _prompt_int(
            f"  Stroke index [{config.stroke_index}]: ", config.stroke_index, 0, 254
        )
        while True:
            raw = ui.text(
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
        _print_swatches(
            f"  Selected: {preset.name} ({preset.description})  ", preset.colors
        )
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
        name = (
            ui.text(
                "Shape name:" if ui.menus_enabled() else f"  [{default_label}]: ",
                default_label,
            ).strip()
            or default_label
        )
    else:
        print(f"\nShape name (descriptive label for slot {config.slot}):")
        name = ui.text("Shape name:" if ui.menus_enabled() else "  > ").strip()
    config.shape_name = name or f"Font slot {config.slot}"
    print(f"  Name: {config.shape_name}")


def _step_shape_path(config: WizardConfig) -> None:
    # --- Output .shp filename ---
    safe = (config.shape_name or f"Font slot {config.slot}").lower().replace(" ", "_")
    safe = "".join(c for c in safe if c.isalnum() or c == "_")
    ttf_label = config.ttf_key or Path(config.ttf_path or "custom").stem
    default_shp = f"font{config.slot}_{safe}_{ttf_label}.shp"
    path = (
        ui.path(f"  Output .shp filename [{default_shp}]: ", default_shp).strip()
        or default_shp
    )
    config.output_path = path
    print(f"  File: {config.output_path}")


def _step_output(
    config: WizardConfig,
    exult_paths: ExultGamePaths | None = None,
    output_override: str | None = None,
) -> tuple[str, str | None]:
    """Step 8: Choose output format and path."""
    print("\nOutput:")
    ui.legacy_menu(
        "  [1] Single shape file (.shp)",
        "  [2] Patch into Exult font archive",
        "  [3] Both",
    )
    resp = _prompt_choice(
        "> ",
        ["1", "2", "3"],
        message="Output format:",
        labels={
            "1": "Single shape file (.shp)",
            "2": "Patch into Exult font archive",
            "3": "Both",
        },
    )

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
        ui.legacy_menu("\n  [A] Accept", "  [P] Enter a different path")
        resp = _prompt_choice(
            "> ",
            ["a", "A", "p", "P"],
            message="Font archive destination:",
            labels={
                "A": f"Accept: {config.flex_source}",
                "P": "Enter a different path",
            },
        )
        if resp.upper() == "P":
            config.flex_source = (
                ui.path("  Full path to font VGA file: ").strip().strip('"').strip("'")
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
                ui.path("  Path to exult.cfg (or Enter to skip): ")
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
        ui.legacy_menu(
            f"\n  [A] Accept: {resolved_path}",
            "  [M] Use a mod's patch directory instead",
            "  [P] Enter a custom path to the font archive",
        )
        resp = _prompt_choice(
            "> ",
            ["a", "A", "m", "M", "p", "P"],
            message="Font archive destination:",
            labels={
                "A": f"Accept: {resolved_path}",
                "M": "Use a different mod patch directory",
                "P": "Enter a custom archive path",
            },
        )

        if resp.upper() == "M":
            mod_patch = ui.path("  Mod patch directory: ").strip().strip('"').strip("'")
            if mod_patch:
                resolved_path = str(Path(mod_patch) / exult_paths.font_filename)
                exists = Path(resolved_path).is_file()
                status = "EXISTS" if exists else "NOT FOUND"
                print(f"  Resolved: {resolved_path}  [{status}]")
        elif resp.upper() == "P":
            resolved_path = (
                ui.path("  Full path to font VGA file: ").strip().strip('"').strip("'")
            )

        config.flex_source = resolved_path
    else:
        # No config — manual entry
        print("  Could not resolve font path from exult.cfg.")
        manual = ui.path("  Full path to font VGA file: ").strip().strip('"').strip("'")
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
    directories: list[Path] | None = None,
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

    archives = (
        sorted(
            set(
                path
                for directory in directories
                for path in scan_font_archives(str(directory))
            )
        )
        if directories
        else scan_font_archives(exult_paths.game_path)
    )

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
        ui.legacy_menu(f"    [{i}] {rel}{exists_tag}")
    ui.legacy_menu("    [P] Enter a custom path", "    [S] Skip — no source archive")

    valid = [str(i) for i in range(1, len(archives) + 1)] + ["p", "P", "s", "S"]
    resp = _prompt_choice(
        "  Select font archive> ",
        valid,
        message="Source font archive:",
        labels={
            **{str(i): str(path) for i, path in enumerate(archives, 1)},
            "P": "Enter a custom archive path",
            "S": "Skip (no source archive)",
        },
    )

    if resp.upper() == "S":
        return None
    if resp.upper() == "P":
        return Path(_prompt_file("  Full path to font VGA file: "))

    return archives[int(resp) - 1]


def _mapped_preview(
    config: WizardConfig,
    glyphs: dict[int, np.ndarray],
    is_mono: bool,
    is_indexed: bool,
    *,
    preview_text: str | None = None,
) -> Path | None:
    mapped = wiz.mapped_glyphs(
        config, RenderedFont(glyphs, is_mono=is_mono, is_indexed=is_indexed)
    )
    palette = wiz.game_palette(config)
    print("\nPreview — representative glyphs (after palette mapping):")
    _show_preview(
        mapped,
        is_mono=False,
        is_indexed=True,
        palette=palette,
        preview_text=preview_text,
        h_lead=config.h_lead,
    )
    _show_palette_info(config)
    if palette is None or not ui.menus_enabled():
        return None
    # Keep the PNG available while the desktop viewer opens asynchronously.
    with tempfile.NamedTemporaryFile(
        prefix="titan-u7-font-preview-", suffix=".png", delete=False
    ) as stream:
        preview_sheet(mapped, palette, text=preview_text, h_lead=config.h_lead).save(
            stream, format="PNG"
        )
        path = Path(stream.name)
    print(f"  Colour image preview (mapped U7 palette): {path}")
    if not open_preview(path):
        print(
            "  Could not open the image viewer automatically; open the PNG above to inspect it."
        )
    return path


def _prompt_preview_text(glyphs: dict[int, np.ndarray], default: str = "") -> str:
    while True:
        text = (
            ui.text("Custom preview text (1-8 characters): ", default).strip()
            or default
        )
        try:
            validate_preview_text(text, glyphs)
            return text
        except ValueError as error:
            print(f"  {error}")


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
        base, targets = game_targets(game)
        target = select_target(base, targets)
        if target is not base:
            exult_paths = replace(
                exult_paths or ExultGamePaths(game),
                game_path=str(target.root or target.patch.parent),
                static_path=str(target.static) if target.static else None,
                patch_path=str(target.patch),
                mods_path=None,
            )
            print(f"  Selected target: {target.name}")
        directories = (
            [path for path in (target.static, target.patch) if path and path.is_dir()]
            if target is not base
            else None
        )
        source_archive = _step_select_archive(exult_paths, directories)
        slot, slot_data = _step_slot(
            game,
            source_archive,
            base_archive,
            paths=exult_paths,
            infer_base=not target.standalone,
        )
        config = WizardConfig(
            game=game,
            force=force,
            allow_cycling=allow_cycling,
            base_archive=base_archive,
            standalone=target.standalone,
            install=_install_for(game),
        )
        if source_archive:
            config.template_archive = str(source_archive)
        if target is not base:
            config.flex_source = str(
                target.patch
                / (
                    source_archive.name
                    if source_archive
                    else exult_paths.font_filename
                    if exult_paths
                    else "fonts.vga"
                )
            )
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
        config.h_lead = wiz.engine_h_lead(config.slot)
        wiz.use_exult_palette(config, exult_paths)
        preview_text = ""
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
                rendered = _render(config)
                glyphs, is_mono, is_indexed = (
                    rendered.glyphs,
                    rendered.is_mono,
                    rendered.is_indexed,
                )
                _mapped_preview(config, glyphs, is_mono, is_indexed)
            except (ValueError, OSError, KeyError, freetype.FT_Exception) as error:
                print(f"  ERROR: {error}", file=sys.stderr)
                if (
                    _prompt_choice(
                        "  [R] Retry font settings  [Q] Quit\n> ",
                        ["R", "r", "Q", "q"],
                        message="Font settings failed:",
                        labels={"R": "Retry font settings", "Q": "Quit"},
                    ).upper()
                    == "Q"
                ):
                    return 1
                continue
            while True:
                answer = _prompt_choice(
                    "  [Y] Looks good — generate  [C] Custom text  [R] Redo  [Q] Quit\n> ",
                    ["Y", "y", "C", "c", "R", "r", "Q", "q"],
                    message="Review the font preview:",
                    labels={
                        "Y": "Looks good — generate",
                        "C": "Custom text (up to 8 characters)",
                        "R": "Redo font settings",
                        "Q": "Quit",
                    },
                )
                if answer.upper() != "C":
                    break
                preview_text = _prompt_preview_text(glyphs, preview_text)
                _mapped_preview(
                    config, glyphs, is_mono, is_indexed, preview_text=preview_text
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
        wiz.apply_output_override(config, output_override)
        if not config.force:
            for path in wiz.output_paths(config):
                if path.exists():
                    answer = _prompt_choice(
                        f"  Replace {path}? [y/N] ", ["y", "Y", "n", "N"], "N"
                    )
                    if answer.upper() != "Y":
                        print("Cancelled.")
                        return 0
            config.force = True
        return _generate(config, rendered)
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        return ui.cancelled()
    except (ValueError, OSError, KeyError, TypeError, freetype.FT_Exception) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return exit_code(error)


# ---------------------------------------------------------------------------
# Generation output (shared by the wizard and recipe mode)
# ---------------------------------------------------------------------------


def _show_gradient(gradient: wiz.GradientResolution) -> None:
    """Show a gradient preset and the palette colours it resolved to."""
    preset = gradient.preset
    _print_swatches(
        f"  Gradient preset: {preset.name} ({preset.description})  ", preset.colors
    )
    colours = gradient.colours
    print(f"  Resolved indices: {gradient.indices}")
    _print_swatches(f"  Resolved colours: {' → '.join(colours)}  ", colours)
    if gradient.repeats:
        print(
            f"  Palette ramp: {gradient.distinct} distinct colours across {gradient.steps} steps; some steps repeat to stay close to the preset."
        )
        if gradient.single_colour:
            print(
                "  WARNING: This preset resolves to a single colour in this palette; "
                "try another preset or manual palette indices."
            )
    print(f"  Stroke index: {gradient.stroke} ({gradient.colour(gradient.stroke)})")


def _render(config: WizardConfig) -> RenderedFont:
    """Render *config*'s glyphs and report how it went."""
    rendered = wiz.render(config)
    if rendered.gradient is not None:
        _show_gradient(rendered.gradient)
    if rendered.oversized:
        print("  WARNING: Font frames exceed 72x72 pixels.", file=sys.stderr)
    print(
        f"  Rendered {len(rendered.glyphs)} glyphs at pixel_size={rendered.pixel_size}"
    )
    return rendered


def _generate(config: WizardConfig, rendered: RenderedFont) -> int:
    """Encode and write the font, reporting each step."""
    encoded = wiz.encode(config, rendered)
    print(f"  Encoded {encoded.frame_count} frames.")
    if encoded.preview_source is not None:
        source = encoded.preview_source
        label = chr(source) if 33 <= source <= 126 else f"#{source}"
        print(
            f"  Frame {EXULT_STUDIO_PREVIEW_FRAME} ('A') was empty — "
            f"copied glyph '{label}' (frame {source}) as "
            f"Exult Studio preview placeholder."
        )
    wiz.write_outputs(config, encoded.data)  # logs each file it writes
    print("\nDone!")
    return 0


# ---------------------------------------------------------------------------
# Non-interactive config mode
# ---------------------------------------------------------------------------


def _install_for(game: str):
    """The configured install for ``"BG"``/``"SI"``."""
    from titan._meta import configured_install

    return configured_install("u7bg" if game.upper() == "BG" else "u7si")


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
        config = wiz.config_from_recipe(
            config_path,
            output_override,
            force=force,
            allow_cycling=allow_cycling,
            base_archive=base_archive,
        )
        config.install = _install_for(config.game)
        rendered = _render(config)
        _show_palette_info(config)
        return _generate(config, rendered)
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        AttributeError,
        freetype.FT_Exception,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return exit_code(error)
