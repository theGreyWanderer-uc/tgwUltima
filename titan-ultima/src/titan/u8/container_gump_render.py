"""Native-pixel U8 gump inventory composition inside verified GUMPAGE rectangles."""

from __future__ import annotations

import random
from dataclasses import dataclass

from PIL import Image

from titan.u8.gumpage import U8GumpItemArea
from titan.u8.container_records import U8InventoryId


@dataclass(frozen=True)
class U8GumpItemSprite:
    """One direct inventory child, with its draw origin and packed native gump coordinates."""

    item_id: U8InventoryId
    shape: int
    frame: int
    image: Image.Image
    xoff: int
    yoff: int
    gump_x: int
    gump_y: int
    editor: bool = False


@dataclass(frozen=True)
class U8GumpPlacement:
    """Painted pixel rectangle and the item's origin relative to the native storage area."""

    item_id: U8InventoryId
    shape: int
    frame: int
    left: int
    top: int
    width: int
    height: int
    anchor_x: int
    anchor_y: int
    position_source: str
    editor: bool
    clipped: bool
    overlap_area: int


@dataclass
class U8GumpComposition:
    """Preview pixels plus placement evidence; no coordinates are written to the save."""

    image: Image.Image
    area: U8GumpItemArea | None
    pixel_area: tuple[int, int, int, int] | None
    placements: list[U8GumpPlacement]
    diagnostics: list[str]
    layout: str
    seed: int


def _overlap_area(box: tuple[int, int, int, int], placed: list[U8GumpPlacement]) -> int:
    left, top, right, bottom = box
    return sum(
        max(0, min(right, item.left + item.width) - max(left, item.left))
        * max(0, min(bottom, item.top + item.height) - max(top, item.top))
        for item in placed
    )


def _signed_gump_coord(value: int) -> int:
    # Native ContainerGumpBox::draw casts only values >= 0xC0 to signed char.
    return value - 256 if value >= 0xC0 else value


def _clamp_saved_gump_position(value: int, start: int, end: int) -> int:
    # Native draw moves underflow one pixel inward, then enforces the far edge.
    return max(start, min(end, start + 1 if value < start else value))


def compose_u8_container_gump(
    artwork: Image.Image,
    area: U8GumpItemArea,
    sprites: list[U8GumpItemSprite],
    *,
    gump_origin: tuple[int, int] = (0, 0),
    layout: str = "random",
    seed: int = 0,
) -> U8GumpComposition:
    """Scatter direct children or clamp saved anchors; alpha composite at native resolution."""
    if layout not in {"random", "saved"}:
        raise ValueError("U8 gump layout must be random or saved")
    if area.width <= 0 or area.height <= 0:
        raise ValueError(
            f"GUMPAGE.DAT: gump shape {area.shape} has an empty or inverted storage rectangle"
        )
    # Sprite PNG top-left is (-xoff,-yoff) relative to the native gump origin.
    native_box = (
        area.left + gump_origin[0],
        area.top + gump_origin[1],
        area.right + gump_origin[0],
        area.bottom + gump_origin[1],
    )
    left, top, right, bottom = (
        max(0, native_box[0]),
        max(0, native_box[1]),
        min(artwork.width, native_box[2]),
        min(artwork.height, native_box[3]),
    )
    if right <= left or bottom <= top:
        raise ValueError("GUMPAGE.DAT: storage rectangle is outside the gump artwork")
    canvas = artwork.convert("RGBA")
    result = U8GumpComposition(
        canvas, area, (left, top, right, bottom), [], [], layout, seed
    )
    if result.pixel_area != native_box:
        result.diagnostics.append(
            "storage rectangle extends outside artwork; composition uses its intersection with the image"
        )
    # Visual layout randomness is reproducible and has no security purpose.
    rng = random.Random(seed)  # nosec B311 - reproducible visual layout only
    for sprite in sprites:
        image = sprite.image.convert("RGBA")
        width, height = min(image.width, right - left), min(image.height, bottom - top)
        if width <= 0 or height <= 0:
            result.diagnostics.append(f"cache ID {sprite.item_id}: empty sprite")
            continue
        clipped = width != image.width or height != image.height
        if clipped:
            result.diagnostics.append(
                f"cache ID {sprite.item_id}: sprite exceeds storage area and is clipped at native pixel size"
            )
        source = "random"
        if layout == "saved" and (sprite.gump_x or sprite.gump_y):
            x = _clamp_saved_gump_position(
                area.left
                + gump_origin[0]
                + _signed_gump_coord(sprite.gump_x)
                - sprite.xoff,
                left,
                right - width,
            )
            y = _clamp_saved_gump_position(
                area.top
                + gump_origin[1]
                + _signed_gump_coord(sprite.gump_y)
                - sprite.yoff,
                top,
                bottom - height,
            )
            source = "saved"
            overlap = _overlap_area((x, y, x + width, y + height), result.placements)
        else:
            best = None
            for _ in range(128):
                x, y = (
                    rng.randint(left, right - width),
                    rng.randint(top, bottom - height),
                )
                overlap = _overlap_area(
                    (x, y, x + width, y + height), result.placements
                )
                candidate = (overlap, x, y)
                if best is None or overlap < best[0]:
                    best = candidate
                if overlap == 0:
                    break
            if best is None:
                raise ValueError("U8 gump layout: could not choose a position")
            overlap, x, y = best
        if overlap:
            result.diagnostics.append(
                f"cache ID {sprite.item_id}: inventory sprites overlap ({overlap} bounding-box pixels)"
            )
        canvas.alpha_composite(image.crop((0, 0, width, height)), (x, y))
        result.placements.append(
            U8GumpPlacement(
                sprite.item_id,
                sprite.shape,
                sprite.frame,
                x,
                y,
                width,
                height,
                x + sprite.xoff - area.left - gump_origin[0],
                y + sprite.yoff - area.top - gump_origin[1],
                source,
                sprite.editor,
                clipped,
                overlap,
            )
        )
    return result
