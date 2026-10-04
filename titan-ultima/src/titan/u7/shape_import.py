"""Create standalone Ultima 7 SHP files from alphabetically sorted PNG frames."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from titan.u7.shape import U7Shape

U7_IMPORT_WARNING_SIZE = 72
U7_IMPORT_MAX_WIDTH = 320
U7_IMPORT_MAX_HEIGHT = 200
U7_QUANTIZE_BATCH_PIXELS = 4096


class U7ImportPalette(Protocol):
    """Palette data needed to map RGBA source frames to U7 palette indices."""

    colors: list[tuple[int, int, int]]


def validate_u7_import_frame_size(width: int, height: int, frame_name: str) -> None:
    """Reject import frames exceeding the independent 320x200 dimension limits."""
    if width > U7_IMPORT_MAX_WIDTH or height > U7_IMPORT_MAX_HEIGHT:
        raise ValueError(
            f"U7 import frame {frame_name} is {width}x{height}; maximum permitted "
            f"size is {U7_IMPORT_MAX_WIDTH}x{U7_IMPORT_MAX_HEIGHT} (width x height)"
        )


def _windows_filename_sort_key(path: Path) -> tuple:
    """Build a case-insensitive logical key matching Windows Explorer name sort."""
    parts = re.split(r"(\d+)", path.name.casefold())
    logical_parts = tuple(
        (1, int(part)) if part.isdigit() else (0, part) for part in parts
    )
    return logical_parts, path.name.casefold(), path.name


def sorted_png_frame_paths(directory: str | Path) -> list[Path]:
    """Return PNG files in Windows Explorer-style logical A-Z name order."""
    source_dir = Path(directory)
    png_paths = [
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".png"
    ]
    return sorted(png_paths, key=_windows_filename_sort_key)


def quantize_u7_rgba_frame(
    image: Image.Image, palette: U7ImportPalette, *, allow_cycling: bool = False
) -> np.ndarray:
    """Preserve matching PNG indices or quantize in bounded batches to U7 colours."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width = rgba.shape[:2]
    alpha = rgba[:, :, 3]
    if image.mode == "P":
        source_palette = image.getpalette("RGB")
        source_indices = np.asarray(image, dtype=np.uint8)
        used_indices = np.unique(source_indices[alpha >= 128])
        if source_palette is not None and all(
            tuple(source_palette[int(index) * 3 : int(index) * 3 + 3])
            == palette.colors[int(index)]
            for index in used_indices
        ):
            pixels = source_indices.copy()
            pixels[alpha < 128] = 0xFF
            return pixels

    # Ordinary artwork uses static colours. Cycling indices 224..254 are opt-in;
    # matching indexed PNGs above already express an intentional index choice.
    palette_end = 255 if allow_cycling else 224
    palette_rgb = np.asarray(palette.colors[:palette_end], dtype=np.int32)
    flat_rgb = rgba[:, :, :3].reshape(-1, 3)
    flat_pixels = np.empty(len(flat_rgb), dtype=np.uint8)
    for start in range(0, len(flat_rgb), U7_QUANTIZE_BATCH_PIXELS):
        end = start + U7_QUANTIZE_BATCH_PIXELS
        differences = (
            flat_rgb[start:end, None, :].astype(np.int32) - palette_rgb[None, :, :]
        )
        np.square(differences, out=differences)
        # Three squared 8-bit differences fit in int32 (maximum 195075).
        distances_squared = np.sum(differences, axis=2, dtype=np.int32)
        flat_pixels[start:end] = np.argmin(distances_squared, axis=1)
        del differences, distances_squared
    pixels = flat_pixels.reshape(height, width)
    pixels[alpha < 128] = 0xFF
    return pixels


def create_u7_shape_from_pngs(
    png_paths: list[Path],
    palette: U7ImportPalette,
    *,
    allow_cycling: bool = False,
    flat: bool = False,
) -> U7Shape:
    """Create RLE objects, or explicit opaque 8x8 raw flat frames."""
    shape = U7Shape()
    for png_path in png_paths:
        with Image.open(png_path) as image:
            validate_u7_import_frame_size(image.width, image.height, png_path.name)
            if flat:
                if image.size != (8, 8):
                    raise ValueError(
                        f"U7 flat frame {png_path.name} must be 8x8; "
                        f"got {image.width}x{image.height}"
                    )
                if image.convert("RGBA").getchannel("A").getextrema() != (255, 255):
                    raise ValueError(
                        f"U7 flat frame {png_path.name} must be fully opaque; "
                        "flat tiles do not support transparency"
                    )
            if (
                image.width > U7_IMPORT_WARNING_SIZE
                or image.height > U7_IMPORT_WARNING_SIZE
            ):
                print(
                    f"WARNING: U7 shape frame {png_path.name} is "
                    f"{image.width}x{image.height}; exceeds the "
                    f"{U7_IMPORT_WARNING_SIZE}x{U7_IMPORT_WARNING_SIZE} warning threshold. "
                    "Importing without resizing.",
                    file=sys.stderr,
                )
            pixels = quantize_u7_rgba_frame(image, palette, allow_cycling=allow_cycling)

        frame = U7Shape.Frame()
        frame.width = pixels.shape[1]
        frame.height = pixels.shape[0]
        # Exult Studio Origin X/Y are xright/ybelow.  (0, 0) places the
        # drawing anchor at the bottom-right pixel; WIHH weapon attachment
        # offsets are separate data and are not stored in this SHP frame.
        frame.origin_x = -1 if flat else 0
        frame.origin_y = -1 if flat else 0
        frame.is_tile = flat
        frame.pixels = pixels
        shape.frames.append(frame)

    return shape
