"""Convert the two U8 north/south grave frames to U7 oblique sprites.

The affine projection is applied before an exact-size pixel-art fit. By default,
each output keeps its source frame's canvas dimensions.
Running the script without positional arguments converts both known frame 0197
sources and writes sibling files whose names end in ``_u7.png``.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import cast

from PIL import Image
from titan.u7.palette import U7Palette


DEFAULT_SOURCES = (
    Path(r"D:\_Repos\tgwUltima\u8data\0197_GRAVE_NS_f0000.png"),
    Path(r"D:\_Repos\tgwUltima\u8data\0197_GRAVE_NS_f0001.png"),
)
DEFAULT_U7_PALETTE = Path(r"C:\Ultima\ultima7si\SERPENT\STATIC\PALETTES.FLX")
U7_FIRST_EFFECT_INDEX = 224
U7_TRANSPARENT_INDEX = 255

# North/south U7 orientation. Swapping the U7 ground axes from the standard
# matrix is required by this project's NS shape convention.
U8_TO_U7 = ((-0.25, 0.5), (0.25, 0.5))
# Inverse matrix used by Pillow, which samples output coordinates -> input.
U7_TO_U8 = ((-2.0, 2.0), (1.0, 1.0))


def alpha_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    """Return the non-transparent pixel bounds of a sprite."""
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("source image is fully transparent")
    return bbox


def transform_u8_point_to_u7(x: float, y: float) -> tuple[float, float]:
    """Transform one U8 screen coordinate into U7 screen coordinates."""
    return (
        U8_TO_U7[0][0] * x + U8_TO_U7[0][1] * y,
        U8_TO_U7[1][0] * x + U8_TO_U7[1][1] * y,
    )


def projected_u7_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    """Return integer U7 bounds of the non-transparent U8 pixel-cell bounds."""
    left, top, right, bottom = alpha_bbox(image)
    corners = (
        transform_u8_point_to_u7(left, top),
        transform_u8_point_to_u7(right, top),
        transform_u8_point_to_u7(left, bottom),
        transform_u8_point_to_u7(right, bottom),
    )
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return (
        math.floor(min(xs)),
        math.floor(min(ys)),
        math.ceil(max(xs)),
        math.ceil(max(ys)),
    )


def project_u8_grave_to_u7(image: Image.Image, supersample: int = 4) -> Image.Image:
    """Apply the grave's U8-to-U7 affine projection with supersampling."""
    if supersample < 1:
        raise ValueError("supersample must be at least 1")

    source = image.convert("RGBA")
    min_x, min_y, max_x, max_y = projected_u7_bounds(source)
    out_width = max_x - min_x
    out_height = max_y - min_y
    scaled = source.resize(
        (source.width * supersample, source.height * supersample),
        Image.Resampling.NEAREST,
    )

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


def fit_grave_pixel_art(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Fit a complete projected grave into an exact binary-alpha frame."""
    width, height = size
    if width < 1 or height < 1:
        raise ValueError("output dimensions must be positive")

    fitted = image.resize((width, height), Image.Resampling.NEAREST)
    binary_alpha = fitted.getchannel("A").point(
        lambda alpha: 255 if alpha >= 128 else 0
    )
    fitted.putalpha(binary_alpha)
    return fitted


def u7_color_distance(
    source: tuple[int, int, int], candidate: tuple[int, int, int]
) -> int:
    """Return a red-mean weighted RGB distance for palette matching."""
    red_delta = source[0] - candidate[0]
    green_delta = source[1] - candidate[1]
    blue_delta = source[2] - candidate[2]
    red_mean = (source[0] + candidate[0]) // 2
    return (
        ((512 + red_mean) * red_delta * red_delta) // 256
        + 4 * green_delta * green_delta
        + ((767 - red_mean) * blue_delta * blue_delta) // 256
    )


def remap_grave_to_u7_palette(image: Image.Image, palette: U7Palette) -> Image.Image:
    """Remap visible RGB pixels to safe U7 colors while preserving RGBA transparency."""
    opaque_colors = palette.colors[:U7_FIRST_EFFECT_INDEX]
    nearest_indices: dict[tuple[int, int, int], int] = {}
    indexed_pixels: list[int] = []

    rgba_pixels = cast(
        list[tuple[int, int, int, int]],
        image.convert("RGBA").get_flattened_data(),
    )
    for red, green, blue, alpha in rgba_pixels:
        if alpha < 128:
            indexed_pixels.append(U7_TRANSPARENT_INDEX)
            continue

        source_color = (red, green, blue)
        nearest_index = nearest_indices.get(source_color)
        if nearest_index is None:
            nearest_index = min(
                range(len(opaque_colors)),
                key=lambda index: u7_color_distance(source_color, opaque_colors[index]),
            )
            nearest_indices[source_color] = nearest_index
        indexed_pixels.append(nearest_index)

    indexed = Image.new("P", image.size, U7_TRANSPARENT_INDEX)
    indexed.putpalette(palette.to_flat_rgb())
    indexed.putdata(indexed_pixels)
    indexed.info["transparency"] = U7_TRANSPARENT_INDEX
    rgba = indexed.convert("RGBA")
    transparent_black = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    return Image.alpha_composite(transparent_black, rgba)


def parse_output_size(value: str) -> tuple[int, int]:
    """Parse a WIDTHxHEIGHT command-line value."""
    try:
        width, height = value.lower().split("x", 1)
        return int(width), int(height)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            "size must be WIDTHxHEIGHT, e.g. 31x45"
        ) from error


def default_output_path(source: Path, output_dir: Path | None) -> Path:
    """Build the non-destructive U7 output path for a source frame."""
    directory = output_dir if output_dir is not None else source.parent
    return directory / f"{source.stem}_u7.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="source frames (default: both 0197_GRAVE_NS frames)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="output directory (default: beside each source)",
    )
    parser.add_argument(
        "--size",
        type=parse_output_size,
        help="override final size as WIDTHxHEIGHT (default: source frame size)",
    )
    parser.add_argument(
        "--native-size",
        action="store_true",
        help="save each affine result without fitting it to --size",
    )
    parser.add_argument("--supersample", type=int, default=4)
    parser.add_argument(
        "--palette",
        type=Path,
        default=DEFAULT_U7_PALETTE,
        help=f"U7 PALETTES.FLX path (default: {DEFAULT_U7_PALETTE})",
    )
    parser.add_argument(
        "--palette-index",
        type=int,
        default=0,
        help="palette record to apply (default: 0, main daytime palette)",
    )
    return parser.parse_args()


def convert_grave_frame(
    source_path: Path,
    output_path: Path,
    output_size: tuple[int, int] | None,
    supersample: int,
    native_size: bool,
    palette: U7Palette,
) -> None:
    """Convert and save one U8 grave frame."""
    with Image.open(source_path) as source:
        source_size = source.size
        projected = project_u8_grave_to_u7(source, supersample)
    fitted_size = output_size if output_size is not None else source_size
    sized = projected if native_size else fit_grave_pixel_art(projected, fitted_size)
    result = remap_grave_to_u7_palette(sized, palette)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(output_path)
    print(
        f"{output_path} ({result.width}x{result.height}; "
        f"native projection {projected.width}x{projected.height})"
    )


def main() -> None:
    args = parse_args()
    sources = tuple(args.inputs) if args.inputs else DEFAULT_SOURCES
    palette = U7Palette.from_file(str(args.palette), palette_index=args.palette_index)
    for source_path in sources:
        convert_grave_frame(
            source_path=source_path,
            output_path=default_output_path(source_path, args.output_dir),
            output_size=args.size,
            supersample=args.supersample,
            native_size=args.native_size,
            palette=palette,
        )


if __name__ == "__main__":
    main()
