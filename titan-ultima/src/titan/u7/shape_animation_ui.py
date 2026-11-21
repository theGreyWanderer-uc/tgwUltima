"""Ask whether imported U7 artwork animates (``--animate`` / ``--no-animate`` skip it).

The rules live in :mod:`titan.u7.shape_animation_flag`, which never prompts.
"""

from __future__ import annotations

from titan import _wizard_ui as ui
from titan.u7.shape import U7Shape
from titan.u7.shape_animation_flag import can_animate, resolve_u7_shape_animation


def choose_u7_shape_animation(
    shape: U7Shape,
    *,
    animated: bool | None = None,
    default: bool | None = None,
) -> bool | None:
    """Prompt for multi-frame RLE artwork; flats and single-frame shapes do not auto-animate."""
    if animated is not None or not can_animate(shape):
        return resolve_u7_shape_animation(shape, animated=animated, default=default)
    try:
        return (
            ui.choice(
                f"  Should these {len(shape.frames)} frames animate? [y/N] ",
                ["Y", "N"],
                "Y" if default else "N",
                message=f"Should these {len(shape.frames)} frames animate?",
            )
            == "Y"
        )
    except EOFError:
        # Existing noninteractive pipelines retain their imported/default choice.
        # Scripts can use --animate/--no-animate for an explicit result.
        return default
    except OSError:
        # pytest's captured stdin and similarly unavailable input are not a TTY.
        if ui.menus_enabled():
            raise
        return default


def ask_record_animation(
    number: int, shape: U7Shape, default: bool | None
) -> bool | None:
    """The ``choose`` callback for :func:`prepare_u7_flex_animation_import`."""
    return choose_u7_shape_animation(shape, default=default)
