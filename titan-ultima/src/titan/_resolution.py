"""Map output size: ``--resolution full|75|50|25`` for every 2D map renderer.

A whole map at full size can be tens of thousands of pixels (a U7 world is about
25000 px square), so a whole-map render defaults to 25%; a crop (``--region``, a
superchunk) defaults to full size. Renderers that can draw small do so (U7);
the rest render at full size and shrink with area averaging (:func:`scaled`).
"""

from __future__ import annotations

__all__ = [
    "RESOLUTIONS",
    "RESOLUTION_HELP",
    "Resolution",
    "default_resolution",
    "resolution_factor",
    "scaled",
    "scale_file",
    "size_tag",
]

from pathlib import Path
from typing import Literal, Optional

Resolution = Literal["full", "75", "50", "25"]
"""``--resolution``'s choices: full size, or that percentage of it."""

RESOLUTIONS = {"full": 1.0, "75": 0.75, "50": 0.5, "25": 0.25}
"""``--resolution`` choice -> scale factor."""

RESOLUTION_HELP = (
    "Output size in percent of full resolution "
    "(default: 25 for a whole map, full for a crop)"
)


def default_resolution(whole_map: bool) -> str:
    """``"25"`` for a whole map, ``"full"`` for a crop."""
    return "25" if whole_map else "full"


def resolution_factor(choice: Optional[str], *, whole_map: bool = True) -> float:
    """The scale factor for a ``--resolution`` value; ``None`` takes the default."""
    return RESOLUTIONS[choice or default_resolution(whole_map)]


def size_tag(factor: float) -> str:
    """The file-name tag for a size: ``""`` at full size, else ``"_25pct"`` and so on."""
    return "" if factor == 1.0 else f"_{round(factor * 100)}pct"


def scaled(image, factor: float):
    """*image* (a PIL image) at *factor* of its size; area averaging keeps a shrunken
    map faithful. Full size returns *image* itself."""
    if factor == 1.0:
        return image
    from PIL import Image

    size = (max(1, round(image.width * factor)), max(1, round(image.height * factor)))
    return image.resize(size, Image.Resampling.BOX)


def scale_file(path: str | Path, factor: float) -> None:
    """Shrink the image file at *path* in place (for renderers that write files)."""
    if factor == 1.0:
        return
    from PIL import Image

    with Image.open(path) as image:
        image.load()
        small = scaled(image, factor)
    small.save(path)
