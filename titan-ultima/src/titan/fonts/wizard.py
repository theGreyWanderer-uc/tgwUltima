"""U7 font shape creation: settings, rendering, encoding and output, with no terminal I/O.

The ``u7 font-create`` wizard (:mod:`titan.fonts.wizard_ui`) prompts for a
:class:`WizardConfig` and calls these functions. A front end can do the same
without a terminal::

    config = config_from_recipe_data(form_values, base_dir)
    result = create_font(config)

or step by step, to show a preview before writing::

    rendered = render(config)          # glyph bitmaps, resolved gradient
    glyphs = mapped_glyphs(config, rendered)   # palette indices, for a preview
    encoded = encode(config, rendered)
    written = write_outputs(config, encoded.data)

Errors are ``ValueError`` / ``OSError`` (and ``freetype.FT_Exception`` for a
bad font file). Progress ("Shape written: ...") is logged under ``titan``.
"""

from __future__ import annotations

__all__ = [
    "WizardConfig",
    "GradientResolution",
    "RenderedFont",
    "EncodedFont",
    "WrittenFont",
    "CreatedFont",
    "engine_h_lead",
    "read_archive_slots",
    "validate_config",
    "resolve_ttf",
    "resolve_lut",
    "resolve_gradient",
    "game_palette",
    "use_exult_palette",
    "apply_output_override",
    "output_paths",
    "render",
    "mapped_glyphs",
    "encode",
    "write_outputs",
    "config_from_recipe",
    "config_from_recipe_data",
    "create_font",
]

import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional

import numpy as np

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from titan._results import record_output
from titan.fonts.archive import game_paths, read_font_archive
from titan.fonts.encoder import (
    GlyphBitmap,
    glyph_to_font_frame,
    glyphs_to_shape,
)
from titan.fonts.exult_cfg import ExultGamePaths, resolve_font_vga_path
from titan.fonts.palette import (
    GradientPreset,
    PaletteLUT,
    get_builtin_lut,
    get_gradient_preset,
    list_builtin_luts,
    resolve_game_palette,
    resolve_gradient_to_indices,
)
from titan.fonts.presets import (
    BUNDLED_TTFS,
    FONT_SHAPES,
    get_ttf_path,
    presets_for_game,
)
from titan.fonts.renderer import (
    render_all_glyphs_grayscale,
    render_all_glyphs_hollow_gradient,
    render_all_glyphs_mono,
)
from titan.u7.palette import U7Palette
from titan.errors import InvalidDataError

if TYPE_CHECKING:
    from titan._meta import Installation

log = logging.getLogger(__name__)


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
    # The configured install (``titan._meta.configured_install``); supplies the
    # game palette when ``palette_file`` is unset. The CLI/UI layer fills it.
    install: Optional[Installation] = None

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
    standalone: bool = False


@dataclass
class GradientResolution:
    """A gradient preset fitted to the game palette (see :func:`resolve_gradient`)."""

    preset: GradientPreset
    palette: U7Palette
    indices: list[int]
    stroke: int
    steps: int

    def colour(self, index: int) -> str:
        r, g, b = self.palette.colors[index]
        return f"#{r:02x}{g:02x}{b:02x}"

    @property
    def colours(self) -> list[str]:
        """The resolved colour of each gradient step, as ``#rrggbb``."""
        return [self.colour(index) for index in self.indices]

    @property
    def distinct(self) -> int:
        """How many different colours the steps resolved to."""
        return len({self.palette.colors[index] for index in self.indices})

    @property
    def repeats(self) -> bool:
        """Some steps share a colour, because the palette has no closer match."""
        return self.distinct < self.steps and len(set(self.preset.colors)) > 1

    @property
    def single_colour(self) -> bool:
        """Every step resolved to the same colour: the preset won't show."""
        return self.repeats and self.distinct == 1


@dataclass
class RenderedFont:
    """Glyph bitmaps from :func:`render`, keyed by character code."""

    glyphs: dict[int, np.ndarray]
    is_mono: bool = True
    is_indexed: bool = False  # bitmaps already hold palette indices
    pixel_size: int = 0
    oversized: bool = False  # a frame exceeds 72x72 pixels
    gradient: GradientResolution | None = None


@dataclass
class EncodedFont:
    """A font shape from :func:`encode`."""

    data: bytes
    frame_count: int
    preview_source: int | None = None
    """Character copied into Exult Studio's empty preview frame, if any."""


@dataclass
class WrittenFont:
    """What :func:`write_outputs` wrote."""

    shape: Path | None = None
    archive: Path | None = None
    size: int = 0


@dataclass
class CreatedFont:
    """Everything :func:`create_font` produced."""

    rendered: RenderedFont
    encoded: EncodedFont
    written: WrittenFont


def engine_h_lead(slot: int) -> int:
    """The horizontal lead Exult uses for font *slot* (it isn't stored in the shape)."""
    # Exult shapes/fontvga.cc, Fonts_vga_file::init().
    leads = (-2, -1, 0, -1, 0, 0, -1, -2, -1, -1)
    return leads[slot] if 0 <= slot < len(leads) else 0


def read_archive_slots(
    archive_path: Path,
    game: str = "BG",
    base_archive: str | None = None,
    *,
    paths: ExultGamePaths | None = None,
    infer_base: bool = True,
    install: Installation | None = None,
) -> dict[int, dict]:
    """Read a font Flex archive and extract live slot data.

    Returns a dict keyed by slot number with ``name``, ``cell_height``,
    ``h_lead``, ``total_frames``, and ``frame_range`` for each non-empty
    record.  Falls back to the static preset name if the slot is known.
    """
    from titan.u7.shape import U7Shape

    archive = read_font_archive(
        archive_path,
        game=game,
        base_archive=base_archive,
        paths=paths,
        infer_base=infer_base,
        install=install,
    )
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


def validate_config(config: WizardConfig) -> None:
    """Raise ``ValueError`` for any setting titan can't encode."""

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
    if type(config.h_lead) is not int or config.h_lead != engine_h_lead(config.slot):
        raise ValueError(
            f"Exult fixes h_lead at {engine_h_lead(config.slot)} for slot {config.slot}; it cannot be overridden in a shape"
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
        resolve_lut(config)
    if config.palette_file:
        resolve_game_palette(config.game, config.palette_file)


def resolve_ttf(config: WizardConfig) -> Path | None:
    """The TrueType file *config* names, or ``None`` if it isn't there."""
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


def resolve_lut(config: WizardConfig) -> PaletteLUT:
    """The palette LUT *config* names; a mono mapping by default."""
    if config.lut_path:
        return PaletteLUT.from_toml(config.lut_path)
    if config.lut_key:
        return get_builtin_lut(config.lut_key)
    return PaletteLUT.mono(config.ink_index)


def game_palette(config: WizardConfig) -> U7Palette | None:
    """The game palette for previews and gradient matching, if one is available."""
    if config.palette_file or not config.standalone:
        return resolve_game_palette(
            config.game, config.palette_file, install=config.install
        )
    return None


def resolve_gradient(config: WizardConfig, steps: int = 6) -> GradientResolution:
    """Fit *config*'s gradient preset to the game palette.

    Interpolates the preset's colours into *steps* stops and matches each to
    the palette. Updates ``config.gradient_indices`` and
    ``config.stroke_index`` in place, and returns the details for display.
    """
    preset = get_gradient_preset(config.gradient_preset or "")
    pal = (
        resolve_game_palette(
            config.game, palette_file=config.palette_file, install=config.install
        )
        if config.palette_file or not config.standalone
        else None
    )
    if pal is None:
        raise ValueError(
            f"No {config.game} palette found; supply palette.file to match gradient colours"
        )

    indices, stroke = resolve_gradient_to_indices(
        preset, pal, steps=steps, allow_cycling=config.allow_cycling
    )
    config.gradient_indices = indices
    config.stroke_index = stroke
    return GradientResolution(preset, pal, indices, stroke, steps)


def use_exult_palette(config: WizardConfig, paths: ExultGamePaths | None) -> None:
    """Set ``config.palette_file`` from the Exult game's PALETTES.FLX, if it has none."""
    if config.palette_file or not paths:
        return
    from titan.u7.shape_archive import find_archive

    for directory in (paths.patch_path, paths.static_path):
        palette = find_archive(Path(directory), "palettes.flx") if directory else None
        if palette:
            from titan.u7.palette import PaletteRecordEmptyError

            try:
                U7Palette.from_file(str(palette))
            except PaletteRecordEmptyError:
                continue
            config.palette_file = str(palette)
            break


def apply_output_override(config: WizardConfig, output_override: str | None) -> None:
    """Point *config* at ``--output``: the archive for flex output, else the shape."""
    if output_override:
        if config.output_format == "flex":
            config.flex_source = output_override
        else:
            config.output_path = output_override


def output_paths(config: WizardConfig) -> list[Path]:
    """The files :func:`write_outputs` will write: the shape, then the archive.

    Resolves the Exult font archive into ``config.flex_source`` when flex
    output has no explicit path.
    """
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


def render(config: WizardConfig) -> RenderedFont:
    """Validate *config* and render its glyphs.

    For a hollow gradient with a preset, the preset is fitted to the game
    palette first (see :func:`resolve_gradient`).
    """
    validate_config(config)
    font_path = resolve_ttf(config)
    if font_path is None:
        raise ValueError(f"Font not found: {config.ttf_path or config.ttf_key}")
    gradient = None
    if config.render_method == "hollow_gradient" and config.gradient_preset:
        gradient = resolve_gradient(config, config.gradient_steps)
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
    return RenderedFont(glyphs, is_mono, is_indexed, px_size, oversized, gradient)


def mapped_glyphs(
    config: WizardConfig, rendered: RenderedFont
) -> dict[int, np.ndarray]:
    """The glyphs as the palette indices they'll be stored with, for a preview."""
    if rendered.is_indexed:
        return rendered.glyphs
    lut = resolve_lut(config)
    return {
        code: glyph_to_font_frame(
            GlyphBitmap(code, bitmap, rendered.is_mono), lut, config.ink_index
        ).pixels
        for code, bitmap in rendered.glyphs.items()
    }


# Exult Studio previews a font with frame 65 ('A'). For scripts without an
# 'A', copy the first letter of the script's name there instead.
_PREVIEW_PREF: dict[str | None, tuple[int, ...]] = {
    "gargish": (71,),  # 'G'
    "ophidean": (83,),  # 'S' (Serpentine)
    "brit_plaques": (82,),  # 'R' (Runic)
    "brit_plaquesSmall": (82,),
    "brit_signs": (82,),
}


def encode(config: WizardConfig, rendered: RenderedFont) -> EncodedFont:
    """Encode rendered glyphs as a U7 font shape."""
    validate_config(config)
    lut = resolve_lut(config)
    glyphs = rendered.glyphs

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

    shape, preview_src = glyphs_to_shape(
        glyphs,
        config.total_frames,
        lut,
        ink_index=config.ink_index,
        is_mono=rendered.is_mono,
        is_indexed=rendered.is_indexed,
        cell_height=config.cell_height,
        space_width=space_w,
        preview_preferred=_PREVIEW_PREF.get(config.ttf_key, ()),
        ink_height=config.ink_height,
    )
    return EncodedFont(shape.to_bytes(), len(shape.frames), preview_src)


def write_outputs(config: WizardConfig, data: bytes) -> WrittenFont:
    """Write the shape file and/or patch the font archive, as *config* says.

    Checks every destination (and reads the archive) before writing either.
    Existing files need ``config.force``. Each written file is logged and
    reported to ``TITAN_RESULTS_FILE``.
    """
    from titan.u7.flex import U7FlexArchive
    from titan.u7.flex_shape_add import save_u7_flex_atomically
    from titan.u7.shape_validation import validate_u7_shape_data

    validate_config(config)
    validate_u7_shape_data(data)
    paths = output_paths(config)
    for path in paths:
        if path.exists() and not config.force:
            raise FileExistsError(
                f"Output exists: {path}; use --force or output.force = true to replace it"
            )
        if path.exists() and not path.is_file():
            raise InvalidDataError(f"Output is not a file: {path}")
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
            if config.template_archive:
                template = U7FlexArchive.from_file(config.template_archive, strict=True)
                archive.magic2 = template.magic2
                archive.reserved_header = template.reserved_header
            archive.title = config.shape_name or f"Font slot {config.slot}"
        archive.records.extend([b""] * max(0, config.slot + 1 - len(archive.records)))
        archive.records[config.slot] = data
    written = WrittenFont(size=len(data))
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
        written.shape = output
        record_output(output)
        log.info("  Shape written: %s (%s bytes)", output, f"{len(data):,}")
    if archive is not None:
        save_u7_flex_atomically(archive, paths[-1])
        written.archive = paths[-1]
        record_output(paths[-1])
        log.info("  Font archive written: %s", paths[-1])
    return written


def config_from_recipe(
    config_path: str | os.PathLike[str],
    output_override: str | None = None,
    *,
    force: bool = False,
    allow_cycling: bool = False,
    base_archive: str | None = None,
    install: Installation | None = None,
) -> WizardConfig:
    """Load a ``font-create`` recipe TOML; its paths are relative to the file."""
    recipe = Path(config_path).expanduser().resolve()
    with recipe.open("rb") as stream:
        data = tomllib.load(stream)
    return config_from_recipe_data(
        data,
        recipe.parent,
        output_override,
        force=force,
        allow_cycling=allow_cycling,
        base_archive=base_archive,
        install=install,
    )


def config_from_recipe_data(
    data: Mapping[str, Any],
    base_dir: str | os.PathLike[str],
    output_override: str | None = None,
    *,
    force: bool = False,
    allow_cycling: bool = False,
    base_archive: str | None = None,
    install: Installation | None = None,
) -> WizardConfig:
    """Build a validated :class:`WizardConfig` from recipe tables, without a file.

    *data* has the recipe's ``target``, ``source``, ``rendering``, ``palette``
    and ``output`` tables (see :func:`titan.fonts.recipe.font_recipe`);
    relative paths in it resolve against *base_dir*. Output destinations are
    resolved too, so nothing is left to prompt for. *install* (see
    :attr:`WizardConfig.install`) supplies the game palette when the recipe
    names none.
    """
    base = Path(base_dir)

    def recipe_path(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise InvalidDataError("File paths must be non-empty strings")
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else base / path)

    target = data.get("target", {})
    config = WizardConfig(install=install)
    config.game = target.get("game", "BG").upper()
    config.slot = target.get("slot", 0)
    if type(config.slot) is not int:
        raise InvalidDataError("Font slot must be an integer")
    preset = presets_for_game(config.game).get(config.slot)
    if preset:
        for name in ("cell_height", "ink_height", "total_frames", "render_method"):
            setattr(config, name, preset[name])
        config.code_range = tuple(preset["frame_range"])
        config.lut_key = preset.get("palette_lut")
    config.h_lead = engine_h_lead(config.slot)
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
        slots = read_archive_slots(
            Path(config.template_archive),
            config.game,
            config.base_archive,
            install=install,
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
        use_exult_palette(config, game_paths(config.game))

    output = data.get("output", {})
    config.output_format = output.get("format", "shp")
    config.output_path = recipe_path(output.get("path"))
    config.flex_source = recipe_path(output.get("flex_source"))
    if config.output_format == "flex" and not config.flex_source:
        config.flex_source = config.output_path
    config.force = force or output.get("force", False)
    config.shape_name = output.get("name")
    apply_output_override(config, output_override)
    validate_config(config)
    # Resolve output before rendering; never fall back to a prompt.
    output_paths(config)
    return config


def create_font(config: WizardConfig) -> CreatedFont:
    """Render, encode and write *config*'s font in one call."""
    rendered = render(config)
    encoded = encode(config, rendered)
    return CreatedFont(rendered, encoded, write_outputs(config, encoded.data))
