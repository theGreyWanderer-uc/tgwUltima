"""The ``u7 shape-create --config`` recipe, described for front ends.

:func:`titan.u7.shape_wizard_ui.run_from_config` reads these fields; a test keeps
the two in step. The schema is also documented in ``cli_reference.md``.
"""

from __future__ import annotations

from titan._meta import RecipeField, RecipeSpec

__all__ = ["shape_recipe"]

_ARCHIVE_OUTPUT = ("output.format", ("flex", "both"))


def shape_recipe() -> RecipeSpec:
    """Every field a shape recipe can set."""
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
                "static",
                "path",
                None,
                "STATIC folder of the base archives; from titan.toml when unset.",
                kind="input-dir",
            ),
            F(
                "target",
                "patch",
                "path",
                None,
                "Default destination folder (a mod's patch).",
                kind="output-dir",
            ),
            F(
                "target",
                "standalone",
                "bool",
                False,
                "Own archives that don't inherit retail BG/SI.",
            ),
            # [source]
            F(
                "source",
                "path",
                "path",
                None,
                "One PNG, or a folder of PNG frames.",
                kind="input-file",
                required=True,
            ),
            # [palette]
            F(
                "palette",
                "file",
                "path",
                None,
                "Palette to map colours to; from titan.toml when unset.",
                kind="palette",
            ),
            F("palette", "index", "int", 0, "Palette record in the file."),
            # [conversion]
            F(
                "conversion",
                "allow_cycling",
                "bool",
                False,
                "Let colour matching use cycling colours 224-254.",
            ),
            F(
                "conversion",
                "flat",
                "bool",
                False,
                "Raw 8x8 flats (opaque, slots 0-149) instead of RLE objects.",
            ),
            F(
                "conversion",
                "animated",
                "bool",
                None,
                "Cycle multiple RLE object frames automatically; "
                "unset leaves the archive's setting alone.",
            ),
            F(
                "conversion",
                "origin_x",
                "int",
                0,
                "Exult Studio right extent; 0 anchors at the right edge.",
            ),
            F(
                "conversion",
                "origin_y",
                "int",
                0,
                "Exult Studio bottom extent; 0 anchors at the bottom edge.",
            ),
            # [archive]
            F(
                "archive",
                "source",
                "path",
                None,
                "Archive to add the shape to (SHAPES.VGA, ...); "
                "unset for a new library.",
                kind="input-file",
                when=_ARCHIVE_OUTPUT,
            ),
            F(
                "archive",
                "base",
                "path",
                None,
                "Base archive when source is a sparse mod patch.",
                kind="input-file",
                when=_ARCHIVE_OUTPUT,
            ),
            F(
                "archive",
                "kind",
                "str",
                "shapes",
                "shapes: SHAPES.VGA slot rules (objects from 150); "
                "generic: any library.",
                ("shapes", "generic"),
                when=_ARCHIVE_OUTPUT,
            ),
            F(
                "archive",
                "mode",
                "str",
                "patch",
                "A new destination: a sparse patch, or a copy of the archive.",
                ("patch", "copy"),
                when=_ARCHIVE_OUTPUT,
            ),
            F(
                "archive",
                "slot",
                "int",
                None,
                "Slot to write; the first free permitted slot when unset.",
                when=_ARCHIVE_OUTPUT,
            ),
            F(
                "archive",
                "replace",
                "bool",
                False,
                "Replace an occupied slot; needs an explicit slot.",
                when=_ARCHIVE_OUTPUT,
            ),
            # [output]
            F(
                "output",
                "format",
                "str",
                "shp",
                "shp: a shape file; flex: into an archive; both.",
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
                "archive",
                "path",
                None,
                "The archive to write for flex/both.",
                kind="output-file",
                when=_ARCHIVE_OUTPUT,
            ),
            F(
                "output",
                "preview",
                "path",
                None,
                "A PNG comparing the source with the converted shape.",
                kind="output-file",
            ),
            F("output", "force", "bool", False, "Replace existing outputs."),
            F(
                "output",
                "in_place",
                "bool",
                False,
                "Write into the source archive itself.",
                when=_ARCHIVE_OUTPUT,
            ),
        ),
    )
