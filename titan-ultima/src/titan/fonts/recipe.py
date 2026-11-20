"""The ``u7 font-create --config`` recipe, described for front ends.

:func:`titan.fonts.wizard.run_from_config` reads these fields; a test keeps the
two in step. The schema is also documented in ``cli_reference.md``.
"""

from __future__ import annotations

from titan._meta import RecipeField, RecipeSpec

__all__ = ["font_recipe"]

_METHODS = ("mono", "lut", "threshold", "hollow_gradient")
_GRADIENT = ("rendering.method", ("hollow_gradient",))


def font_recipe() -> RecipeSpec:
    """Every field a font recipe can set. Loads the LUT and gradient tables."""
    from titan.fonts.palette import list_builtin_luts, list_gradient_presets
    from titan.fonts.presets import BUNDLED_TTFS

    F = RecipeField
    return RecipeSpec(
        "config",
        (
            # [target]
            F(
                "target",
                "game",
                "str",
                "BG",
                "Black Gate or Serpent Isle.",
                ("BG", "SI"),
            ),
            F(
                "target",
                "slot",
                "int",
                0,
                "FONTS.VGA font slot (0-7 BG, 0-10 SI). Known slots fill in size, "
                "frames, characters and rendering.",
            ),
            F(
                "target",
                "cell_height",
                "int",
                None,
                "Glyph cell height; from the slot.",
            ),
            F(
                "target",
                "ink_height",
                "int",
                None,
                "Capital height and baseline, 1 to cell_height - 1; "
                "cell_height - 1 when unset.",
            ),
            F(
                "target",
                "h_lead",
                "int",
                None,
                "Exult's fixed character spacing for the slot; only checked, "
                "never changed.",
            ),
            F("target", "total_frames", "int", None, "Frames in the font (33-256)."),
            F(
                "target",
                "code_range",
                "int-list",
                None,
                "First and last character code, inclusive; from the slot.",
            ),
            F(
                "target",
                "layout",
                "str",
                "standard",
                "Glyph layout: standard, or a mapping TOML file.",
                ("standard",),
                open=True,
                kind="input-file",
            ),
            # [source]
            F(
                "source",
                "font",
                "str",
                "dosVga437",
                "A bundled font, or a TTF file.",
                tuple(BUNDLED_TTFS),
                open=True,
                kind="input-file",
            ),
            F(
                "source",
                "archive",
                "path",
                None,
                "Font archive to copy the slot's size from (fonts.vga); "
                "separate from the output.",
                kind="input-file",
            ),
            F(
                "source",
                "base_archive",
                "path",
                None,
                "Base FONTS.VGA for a sparse template archive.",
                kind="input-file",
            ),
            # [rendering]
            F(
                "rendering",
                "method",
                "str",
                None,
                "How glyphs are drawn; from the slot, else mono.",
                _METHODS,
            ),
            F(
                "rendering",
                "lut",
                "str",
                None,
                "Palette LUT: a built-in name or a LUT TOML file. Required for lut.",
                tuple(list_builtin_luts()),
                open=True,
                kind="input-file",
                when=("rendering.method", ("lut",)),
            ),
            F(
                "rendering",
                "threshold",
                "int",
                128,
                "Grayscale cutoff, 1-255.",
                when=("rendering.method", ("threshold",)),
            ),
            F(
                "rendering",
                "gradient_preset",
                "str",
                None,
                "Named colour ramp; or set gradient_indices.",
                tuple(list_gradient_presets()),
                when=_GRADIENT,
            ),
            F(
                "rendering",
                "gradient_indices",
                "int-list",
                [36, 181, 182, 183, 184, 185],
                "Palette indices of the ramp, top to bottom.",
                when=_GRADIENT,
            ),
            F(
                "rendering",
                "gradient_steps",
                "int",
                6,
                "Colour stops when resolving a preset.",
                when=_GRADIENT,
            ),
            F(
                "rendering",
                "stroke_width",
                "int",
                1,
                "Outline width in pixels.",
                when=_GRADIENT,
            ),
            F(
                "rendering",
                "stroke_index",
                "int",
                0,
                "Outline palette index (a preset sets its own).",
                when=_GRADIENT,
            ),
            F(
                "rendering",
                "allow_cycling",
                "bool",
                False,
                "Let automatic matching use cycling colours 224-254.",
                when=_GRADIENT,
            ),
            # [palette]
            F(
                "palette",
                "ink",
                "int",
                0,
                "Palette index for ink pixels.",
                when=("rendering.method", ("mono", "threshold")),
            ),
            F("palette", "transparent", "int", 255, "Must be 255 for U7."),
            F(
                "palette",
                "file",
                "path",
                None,
                "Game palette for checking colours; found through Exult when unset.",
                kind="palette",
            ),
            # [output]
            F(
                "output",
                "format",
                "str",
                "shp",
                "shp: a shape file; flex: a font archive; both.",
                ("shp", "flex", "both"),
            ),
            F(
                "output",
                "path",
                "path",
                None,
                "The shape file; for flex, may name the archive instead.",
                kind="output-file",
            ),
            F(
                "output",
                "flex_source",
                "path",
                None,
                "Font archive to patch for flex/both; found through Exult when unset.",
                kind="input-file",
                when=("output.format", ("flex", "both")),
            ),
            F("output", "name", "str", None, "Descriptive name for the shape."),
            F("output", "force", "bool", False, "Replace existing outputs."),
        ),
    )
