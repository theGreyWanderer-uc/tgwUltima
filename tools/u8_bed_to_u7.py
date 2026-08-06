"""Convert an Ultima VIII dimetric sprite to Ultima VII oblique projection.

The projection is applied before the optional final-size fit.  This matters for
the bed: its cropped native projection is 21x33, while the requested U7 shape
frame is 31x45.  ``--size`` therefore performs an explicit, nearest-neighbour
pixel-art fit after projection rather than inventing new geometry.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image


DEFAULT_SOURCE = Path(r"D:\_Repos\tgwUltima\u8data\0175_BEDNS_f0000.png")
DEFAULT_OUTPUT = Path(r"D:\_Repos\tgwUltima\u8data\0175_BEDNS_f0000_u7.png")

# U8 screen coordinates -> U7 screen coordinates for a north/south shape.
#
# The commonly quoted matrix ((.25, .5), (-.25, .5)) assigns the U8 +X
# ground vector to U7's horizontal screen axis. BEDNS uses that ground axis for
# its length, so the result lies east/west. Swapping the U7 X/Y ground axes
# gives the vertical north/south shape requested here.
U8_TO_U7 = ((-0.25, 0.5), (0.25, 0.5))
# Inverse matrix, used by Pillow because Image.transform samples output -> input.
U7_TO_U8 = ((-2.0, 2.0), (1.0, 1.0))


def alpha_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("source image is fully transparent")
    return bbox


def transform_point(x: float, y: float) -> tuple[float, float]:
    return (
        U8_TO_U7[0][0] * x + U8_TO_U7[0][1] * y,
        U8_TO_U7[1][0] * x + U8_TO_U7[1][1] * y,
    )


def projected_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    """Return integer U7 bounds of the non-transparent U8 pixel-cell bounds."""
    left, top, right, bottom = alpha_bbox(image)
    corners = (
        transform_point(left, top),
        transform_point(right, top),
        transform_point(left, bottom),
        transform_point(right, bottom),
    )
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    # Matrix coefficients are quarter/half pixels, so floor/ceil are exact here.
    return (
        math.floor(min(xs)),
        math.floor(min(ys)),
        math.ceil(max(xs)),
        math.ceil(max(ys)),
    )


def project_u8_to_u7(image: Image.Image, supersample: int = 4) -> Image.Image:
    """Apply the U8->U7 affine projection with coverage-aware supersampling."""
    if supersample < 1:
        raise ValueError("supersample must be at least 1")

    source = image.convert("RGBA")
    min_x, min_y, max_x, max_y = projected_bounds(source)
    out_width = max_x - min_x
    out_height = max_y - min_y

    scaled = source.resize(
        (source.width * supersample, source.height * supersample),
        Image.Resampling.NEAREST,
    )

    # For output coordinate q, Pillow needs the source coordinate
    # p = inverse(M) * (q + projected_min). Coordinates are supersampled,
    # hence only the translation terms need multiplying by supersample.
    a, b = U7_TO_U8[0]
    d, e = U7_TO_U8[1]
    c = (a * min_x + b * min_y) * supersample
    f = (d * min_x + e * min_y) * supersample
    projected_large = scaled.transform(
        (out_width * supersample, out_height * supersample),
        Image.Transform.AFFINE,
        (a, b, c, d, e, f),
        resample=Image.Resampling.NEAREST,
        fillcolor=(0, 0, 0, 0),
    )
    projected = projected_large.resize((out_width, out_height), Image.Resampling.BOX)
    return projected.crop(alpha_bbox(projected))


def fit_pixel_art(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Fit the complete projected sprite to an exact frame using hard pixels."""
    width, height = size
    if width < 1 or height < 1:
        raise ValueError("output dimensions must be positive")

    fitted = image.resize((width, height), Image.Resampling.NEAREST)
    # Nearest-neighbour resizing keeps existing partial alpha from the affine
    # coverage pass. Snap it to the binary transparency expected by U7 shapes.
    binary_alpha = fitted.getchannel("A").point(
        lambda alpha: 255 if alpha >= 128 else 0
    )
    fitted.putalpha(binary_alpha)
    return fitted


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = value.lower().split("x", 1)
        return int(width), int(height)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            "size must be WIDTHxHEIGHT, e.g. 31x45"
        ) from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--size",
        type=parse_size,
        default=(31, 45),
        help="exact final frame size after projection (default: 31x45)",
    )
    parser.add_argument(
        "--native-size",
        action="store_true",
        help="save the affine result without fitting it to --size",
    )
    parser.add_argument("--supersample", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = Image.open(args.input).convert("RGBA")
    projected = project_u8_to_u7(source, args.supersample)
    result = projected if args.native_size else fit_pixel_art(projected, args.size)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.save(args.output)
    print(
        f"{args.output} ({result.width}x{result.height}; "
        f"native projection {projected.width}x{projected.height})"
    )


if __name__ == "__main__":
    main()
