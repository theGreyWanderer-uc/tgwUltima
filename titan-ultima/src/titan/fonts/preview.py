"""Colour previews of font pixels after mapping them to the game palette."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from titan.u7.palette import U7Palette

PREVIEW_CODES = (65, 103, 87, 63, 52)  # A g W ? 4


def preview_codes(glyphs: dict[int, np.ndarray]) -> list[int]:
    return [code for code in PREVIEW_CODES if code in glyphs] or list(glyphs)[:5]


def validate_preview_text(text: str, glyphs: dict[int, np.ndarray]) -> None:
    if not 1 <= len(text) <= 8 or not text.isprintable() or not text.strip():
        raise ValueError("Enter 1-8 printable characters.")
    missing = list(
        dict.fromkeys(char for char in text if char != " " and ord(char) not in glyphs)
    )
    if missing:
        raise ValueError(
            f"These characters are not available in this font: {', '.join(repr(char) for char in missing)}"
        )


def compose_text(
    glyphs: dict[int, np.ndarray], text: str, h_lead: int = 0
) -> np.ndarray:
    """Compose existing glyph pixels with the font's spacing; never rerender them."""
    validate_preview_text(text, glyphs)
    widths = sorted(
        bitmap.shape[1] for bitmap in glyphs.values() if bitmap.shape[1] > 1
    )
    height = max(bitmap.shape[0] for bitmap in glyphs.values())
    space_width = (
        max(widths[len(widths) // 2] // 2, 2) if widths else max(height // 3, 2)
    )
    space = np.full((height, space_width), 255, dtype=np.uint8)
    positioned = []
    x = 0
    for char in text:
        bitmap = space if char == " " else glyphs[ord(char)]
        positioned.append((x, bitmap))
        x += max(1, bitmap.shape[1] + h_lead)
    width = max(x + bitmap.shape[1] for x, bitmap in positioned)
    result = np.full((height, width), 255, dtype=np.uint8)
    for x, bitmap in positioned:
        target = result[: bitmap.shape[0], x : x + bitmap.shape[1]]
        np.copyto(target, bitmap, where=bitmap != 255)
    return result


def preview_items(
    glyphs: dict[int, np.ndarray], text: str | None = None, h_lead: int = 0
) -> list[tuple[str, np.ndarray]]:
    if text is not None:
        return [(repr(text), compose_text(glyphs, text, h_lead))]
    return [(f"'{chr(code)}' ({code})", glyphs[code]) for code in preview_codes(glyphs)]


def glyph_image(pixels: np.ndarray, palette: U7Palette) -> Image.Image:
    """Index 0 remains visible ink; only index 255 becomes transparent."""
    colours = np.asarray(palette.colors, dtype=np.uint8)[pixels]
    alpha = np.where(pixels == 255, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack((colours, alpha)))


def preview_sheet(
    glyphs: dict[int, np.ndarray],
    palette: U7Palette,
    *,
    text: str | None = None,
    h_lead: int = 0,
) -> Image.Image:
    items = preview_items(glyphs, text, h_lead)
    if not items:
        raise ValueError("No glyphs to preview")
    images = [glyph_image(bitmap, palette) for _, bitmap in items]
    width = sum(image.width for image in images)
    height = max(image.height for image in images)
    scale = max(1, min(4, 1200 // max(1, width), 600 // max(1, height)))
    sheet = Image.new(
        "RGB",
        (max(420, width * scale + 24 * len(items)), height * scale + 60),
        (48, 48, 48),
    )
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (8, 8),
        "U7 palette 0: mapped glyph colours; index 255 is transparent",
        fill="white",
    )
    x, y = 12, 48
    for (label, _), image in zip(items, images):
        image = image.resize(
            (image.width * scale, image.height * scale), Image.Resampling.NEAREST
        )
        for cy in range(y, y + height * scale, 8):
            for cx in range(x, x + image.width, 8):
                colour = (
                    (96, 96, 96)
                    if ((cx - x) // 8 + (cy - y) // 8) % 2
                    else (160, 160, 160)
                )
                draw.rectangle(
                    (
                        cx,
                        cy,
                        min(cx + 7, x + image.width - 1),
                        min(cy + 7, y + height * scale - 1),
                    ),
                    fill=colour,
                )
        sheet.paste(image, (x, y), image)
        draw.text((x, 28), label, fill="white")
        x += image.width + 24
    return sheet
