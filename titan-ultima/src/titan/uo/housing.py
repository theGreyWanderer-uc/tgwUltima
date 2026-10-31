"""House placement footprints from client multis and an emulator's house table.

The client holds each house's layout (``MultiCollection.uop`` or
``multi.mul``). Which houses a server offers, and where each one anchors
relative to the placement cursor, lives server side. Titan reads that from a
RunUO/ServUO ``HousePlacementTool.cs`` the user supplies. The footprint
rules follow RunUO ``HousePlacement.Check`` and
``HouseFoundation.AddStairsTo``.
"""

from __future__ import annotations

__all__ = [
    "HouseFootprint",
    "HousePlacementEntry",
    "footprint_sheet",
    "house_footprint",
    "parse_house_placement_tool",
    "render_footprint",
]

from dataclasses import dataclass
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont

from titan.uo.multi import UOMulti
from titan.uo.tiledata import UOTileData

YARD_SIZE = 5  # RunUO HousePlacement.YardSize
STAIR_ITEM = 0x63  # HouseFoundation.AddStairsTo
_FOUNDATION_IDS = range(0x13EC, 0x1D00)  # customizable foundations get stairs
_FLAG_WALL = 0x10
_FLAG_SURFACE = 0x200

_TABLE = re.compile(r"HousePlacementEntry\s*\[\]\s*(\w+)\s*=\s*new\s+HousePlacementEntry\s*\[\]")
_ENTRY = re.compile(
    r"new\s+HousePlacementEntry\s*\(\s*typeof\s*\(\s*(\w+)\s*\)\s*,"
    r"\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,"
    r"\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*\)"
)


@dataclass(frozen=True)
class HousePlacementEntry:
    """One row of an emulator's house placement menu."""

    category: str
    type_name: str
    cliloc: int
    storage: int
    lockdowns: int
    new_storage: int
    new_lockdowns: int
    vendors: int
    cost: int
    offset: tuple[int, int, int]
    multi_id: int


@dataclass(frozen=True)
class HouseFootprint:
    """Cells a house uses, relative to its centre (the multi origin).

    ``occupied`` holds cells with any component, including added stairs.
    ``foundation`` holds cells with a z=0 Wall tile. ``border`` is the ring
    that must be free of impassable land and statics. ``yard`` is the area
    (foundation +-1 in x, +-5 in y) that must not overlap another house.
    """

    multi_id: int
    occupied: frozenset[tuple[int, int]]
    foundation: frozenset[tuple[int, int]]
    border: frozenset[tuple[int, int]]
    yard: frozenset[tuple[int, int]]
    stairs_added: bool

    @staticmethod
    def extent(cells: frozenset[tuple[int, int]]) -> tuple[int, int, int, int]:
        if not cells:
            return (0, 0, 0, 0)
        xs = [x for x, _ in cells]
        ys = [y for _, y in cells]
        return (min(xs), max(xs), min(ys), max(ys))


_SHEET_COLORS = {
    "background": (24, 24, 28),
    "panel": (36, 36, 42),
    "yard": (52, 70, 96),
    "border": (196, 120, 48),
    "occupied": (150, 150, 158),
    "foundation": (214, 186, 120),
    "centre": (220, 60, 60),
    "cursor": (90, 200, 120),
    "grid": (30, 30, 34),
    "text": (232, 228, 220),
    "muted": (160, 156, 148),
}


def render_footprint(
    footprint: HouseFootprint, offset: tuple[int, int, int], scale: int = 6
) -> Image.Image:
    """Draw one footprint: yard, border, occupied and foundation cells.

    The house centre is marked red. The placement cursor (centre + offset)
    is marked green.
    """
    cursor = (offset[0], offset[1])
    cells = footprint.yard | footprint.border | footprint.occupied | {cursor, (0, 0)}
    min_x, max_x, min_y, max_y = HouseFootprint.extent(frozenset(cells))
    width = (max_x - min_x + 1) * scale
    height = (max_y - min_y + 1) * scale
    image = Image.new("RGB", (width, height), _SHEET_COLORS["panel"])
    draw = ImageDraw.Draw(image)

    def box(cell: tuple[int, int], color, inset: int = 0) -> None:
        x0 = (cell[0] - min_x) * scale + inset
        y0 = (cell[1] - min_y) * scale + inset
        draw.rectangle(
            (x0, y0, x0 + scale - 1 - inset, y0 + scale - 1 - inset), fill=color
        )

    for cell in footprint.yard:
        box(cell, _SHEET_COLORS["yard"])
    for cell in footprint.border:
        box(cell, _SHEET_COLORS["border"])
    for cell in footprint.occupied:
        box(cell, _SHEET_COLORS["occupied"])
    for cell in footprint.foundation:
        box(cell, _SHEET_COLORS["foundation"])
    if scale >= 4:
        for x in range(0, width, scale):
            draw.line((x, 0, x, height), fill=_SHEET_COLORS["grid"])
        for y in range(0, height, scale):
            draw.line((0, y, width, y), fill=_SHEET_COLORS["grid"])
    inset = max(1, scale // 4)
    box((0, 0), _SHEET_COLORS["centre"], inset)
    box(cursor, _SHEET_COLORS["cursor"], inset)
    return image


def footprint_sheet(
    items: list[tuple[HousePlacementEntry, str, HouseFootprint]],
    *,
    scale: int = 6,
    max_width: int = 2000,
    title: str = "",
) -> Image.Image:
    """Lay out labelled footprints, one section per placement category."""
    font = _sheet_font(13)
    small = _sheet_font(11)
    pad, label_h = 12, 34
    sections: dict[str, list[tuple[HousePlacementEntry, str, HouseFootprint, Image.Image]]] = {}
    for entry, name, footprint in items:
        sections.setdefault(entry.category, []).append(
            (entry, name, footprint, render_footprint(footprint, entry.offset, scale))
        )

    placed: list[tuple[int, int, object]] = []  # (x, y, drawable)
    y = pad
    if title:
        placed.append((pad, y, ("title", title)))
        y += 30
    for category, thumbs in sections.items():
        placed.append((pad, y, ("heading", f"{category} ({len(thumbs)})")))
        y += 24
        x, row_h = pad, 0
        for entry, name, footprint, thumb in thumbs:
            cell_w = max(thumb.width, 150)
            if x + cell_w > max_width - pad and x > pad:
                x, y = pad, y + row_h + pad
                row_h = 0
            placed.append((x, y, ("thumb", entry, name, footprint, thumb)))
            row_h = max(row_h, thumb.height + label_h)
            x += cell_w + pad
        y += row_h + pad * 2
    legend_y = y
    sheet = Image.new("RGB", (max_width, legend_y + 30), _SHEET_COLORS["background"])
    draw = ImageDraw.Draw(sheet)
    for x, y, item in placed:
        kind = item[0]
        if kind == "title":
            draw.text((x, y), item[1], fill=_SHEET_COLORS["text"], font=_sheet_font(18))
        elif kind == "heading":
            draw.text((x, y), item[1], fill=_SHEET_COLORS["muted"], font=font)
        else:
            _, entry, name, footprint, thumb = item
            min_x, max_x, min_y, max_y = HouseFootprint.extent(footprint.occupied)
            fp_w, fp_h = max_x - min_x + 1, max_y - min_y + 1
            draw.text((x, y), _clip(name or entry.type_name, 24), fill=_SHEET_COLORS["text"], font=small)
            draw.text(
                (x, y + 14),
                f"0x{entry.multi_id:04X}  {fp_w}x{fp_h}",
                fill=_SHEET_COLORS["muted"],
                font=small,
            )
            sheet.paste(thumb, (x, y + label_h))
    legend = (
        ("foundation", "foundation"),
        ("occupied", "house tile"),
        ("border", "border (no impassable)"),
        ("yard", "yard (no other house)"),
        ("centre", "centre"),
        ("cursor", "placement cursor"),
    )
    lx = pad
    for key, text in legend:
        draw.rectangle((lx, legend_y + 4, lx + 12, legend_y + 16), fill=_SHEET_COLORS[key])
        draw.text((lx + 18, legend_y + 3), text, fill=_SHEET_COLORS["muted"], font=small)
        lx += 30 + int(draw.textlength(text, font=small))
    return sheet


def _clip(text: str, length: int) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


def _sheet_font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def parse_house_placement_tool(path: str | Path) -> list[HousePlacementEntry]:
    """Parse the ``HousePlacementEntry`` tables of a RunUO/ServUO source file.

    Each entry's category is the name of the array it sits in, without the
    ``m_`` prefix (for example ``ClassicHouses`` or ``TwoStoryFoundations``).
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    tables = [(m.start(), m.group(1)) for m in _TABLE.finditer(text)]
    entries: list[HousePlacementEntry] = []
    for match in _ENTRY.finditer(text):
        category = ""
        for start, name in tables:
            if start < match.start():
                category = name[2:] if name.startswith("m_") else name
        values = match.groups()
        entries.append(
            HousePlacementEntry(
                category=category,
                type_name=values[0],
                cliloc=int(values[1]),
                storage=int(values[2]),
                lockdowns=int(values[3]),
                new_storage=int(values[4]),
                new_lockdowns=int(values[5]),
                vendors=int(values[6]),
                cost=int(values[7]),
                offset=(int(values[8]), int(values[9]), int(values[10])),
                multi_id=int(values[11], 0),
            )
        )
    if not entries:
        raise ValueError(f"no HousePlacementEntry rows found in {path}")
    return entries


def house_footprint(multi: UOMulti, tiledata: UOTileData) -> HouseFootprint:
    """Rebuild RunUO's placement footprint for one house multi."""
    tiles: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for component in multi.components:
        tiles.setdefault((component.x, component.y), []).append(
            (component.item_id, component.z)
        )

    stairs = multi.multi_id in _FOUNDATION_IDS and bool(tiles)
    if stairs:
        xs = [x for x, _ in tiles]
        stair_y = max(y for _, y in tiles) + 1
        for x in range(min(xs), max(xs) + 1):
            tiles.setdefault((x, stair_y), []).append((STAIR_ITEM, 0))

    def flags(item_id: int) -> int:
        return tiledata.statics[item_id].flags if item_id < len(tiledata.statics) else 0

    def height(item_id: int) -> int:
        return tiledata.statics[item_id].height if item_id < len(tiledata.statics) else 0

    foundation = {
        cell
        for cell, items in tiles.items()
        if any(z == 0 and flags(item) & _FLAG_WALL for item, z in items)
    }

    def has_base_floor(cell: tuple[int, int]) -> bool:
        return any(
            height(item) == 0 and z <= 8 and flags(item) & _FLAG_SURFACE
            for item, z in tiles.get(cell, ())
        )

    border: set[tuple[int, int]] = set()
    yard: set[tuple[int, int]] = set()
    for fx, fy in foundation:
        for dx in (-1, 0, 1):
            for dy in range(-YARD_SIZE, YARD_SIZE + 1):
                yard.add((fx + dx, fy + dy))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                cell = (fx + dx, fy + dy)
                # RunUO: a neighbour under a base floor (z <= 8) is not border.
                if has_base_floor(cell):
                    continue
                border.add(cell)

    return HouseFootprint(
        multi_id=multi.multi_id,
        occupied=frozenset(tiles),
        foundation=frozenset(foundation),
        border=frozenset(border),
        yard=frozenset(yard),
        stairs_added=stairs,
    )
