"""Create standalone Ultima 7 SHP files from alphabetically sorted PNG frames."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from titan.u7.shape import U7Shape


class U7ImportPalette(Protocol):
    """Palette data needed to map RGBA source frames to U7 palette indices."""

    colors: list[tuple[int, int, int]]


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


def quantize_u7_rgba_frame(image: Image.Image, palette: U7ImportPalette) -> np.ndarray:
    """Map one RGBA frame to U7 indices; alpha below 128 becomes index 255."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width = rgba.shape[:2]
    rgb = rgba[:, :, :3].astype(np.int32)
    alpha = rgba[:, :, 3]

    # Index 255 is reserved for shape transparency, so opaque source pixels
    # may only select indices 0..254 even if palette entry 255 is a close RGB match.
    palette_rgb = np.asarray(palette.colors[:255], dtype=np.int32)
    flat_rgb = rgb.reshape(-1, 3)
    differences = flat_rgb[:, None, :] - palette_rgb[None, :, :]
    distances_squared = np.sum(differences * differences, axis=2)
    pixels = (
        np.argmin(distances_squared, axis=1).astype(np.uint8).reshape(height, width)
    )
    pixels[alpha < 128] = 0xFF
    return pixels


def create_u7_shape_from_pngs(
    png_paths: list[Path],
    palette: U7ImportPalette,
) -> U7Shape:
    """Create an RLE U7 shape using Exult Studio's default Origin (0, 0)."""
    shape = U7Shape()
    for png_path in png_paths:
        with Image.open(png_path) as image:
            pixels = quantize_u7_rgba_frame(image, palette)

        frame = U7Shape.Frame()
        frame.width = pixels.shape[1]
        frame.height = pixels.shape[0]
        # Exult Studio Origin X/Y are xright/ybelow.  (0, 0) places the
        # drawing anchor at the bottom-right pixel; WIHH weapon attachment
        # offsets are separate data and are not stored in this SHP frame.
        frame.origin_x = 0
        frame.origin_y = 0
        frame.pixels = pixels
        shape.frames.append(frame)

    return shape
