"""U7 container gump mappings, native storage bounds and direct-item composition.

CONTAINER.DAT supplies the world shape to GUMPS.VGA mapping. Exult's
Gump.cc Container_gump::initialize supplies fallback rectangles; owner-scoped
gump_info.txt container_area sections override them. Coordinates are relative
to the gump draw anchor, not the PNG top-left. No save positions are changed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from titan.u7.archive_targets import ArchiveTarget
from titan.u7.shape_extra import _parse_single_value_section
from titan.u7.shapeinfo import U7Containers
from titan.u7.gump_metadata import (
    U7GumpArea,
    U7GumpMetadata,
    load_u7_gump_sources,
    read_u7_gump_metadata,
)


@dataclass
class U7ContainerGumps:
    """Captured owner mappings and bounds; explicit owner disables take precedence."""

    mappings: dict[int, tuple[int, str]] = field(default_factory=dict)
    areas: dict[int, U7GumpArea] = field(default_factory=dict)
    special: set[int] = field(default_factory=set)
    locked: dict[int, bool] = field(default_factory=dict)
    disabled: set[int] = field(default_factory=set)
    source_files: list[Path] = field(default_factory=list)
    metadata: U7GumpMetadata = field(default_factory=U7GumpMetadata)
    bindings: U7Containers = field(default_factory=lambda: U7Containers(0, []))
    warnings: list[str] = field(default_factory=list)

    def resolve(self, shape: int) -> tuple[int, U7GumpArea, str]:
        """Resolve a container's gump without substituting unrelated artwork."""
        number, source = self.mappings.get(shape, (-1, "no mapping"))
        if number < 0 and shape not in self.disabled and self.locked.get(shape):
            # Retail locked chest 522 becomes unlocked chest 800 (Exult's
            # bgkeyring keyring.uc and BG/SI shape constants). Honour this
            # owner's unlocked mapping, and explicit locked-shape disable records.
            if shape == 522 and self.mappings.get(800, (-1, ""))[0] >= 0:
                number, original_source = self.mappings[800]
                source = (
                    f"Preview locked chest via unlocked shape 800; {original_source}"
                )
            else:
                # Exult Container_game_object::show_gump uses gump 1 in
                # pickpocket mode for locked containers with no direct mapping.
                number, source = (
                    1,
                    "Preview locked container via Exult pickpocket fallback",
                )
        if number < 0:
            raise ValueError(
                f"U7 container gump: no artwork mapping for shape {shape}; usecode may select its gump"
            )
        if number in self.special:
            raise ValueError(
                f"U7 container gump: shape {number} is not a container gump"
            )
        # Exult uses this rectangle for unrecognised container gump shapes.
        area = self.areas.get(number, U7GumpArea(52, 22, 60, 40))
        if area.width <= 0 or area.height <= 0:
            raise ValueError(
                f"U7 container gump: invalid storage area for gump {number}"
            )
        return number, area, source


def load_u7_container_gumps(
    target: ArchiveTarget,
    game: str,
    *,
    exult_flx: str | None = None,
    custom_game: bool | None = None,
    discover_defaults: bool = True,
) -> U7ContainerGumps:
    """Select engine defaults and patch records; standalone/custom games use STATIC explicitly."""
    is_custom = target.standalone if custom_game is None else custom_game
    sources = load_u7_gump_sources(
        target.static,
        patch_dir=target.patch,
        game=game,
        exult_flx=exult_flx,
        custom_game=is_custom,
        discover_defaults=discover_defaults,
    )
    result = U7ContainerGumps()
    # Current Exult data/bg|si/shape_info.txt locked_containers defaults.
    # Older installed bundles omit this section (notably SI); text overlays
    # below may clear these flags or supply mod-specific locked shapes.
    if not is_custom:
        result.locked = {522: True, (798 if game == "bg" else 914): True}
    areas = {
        0: (46, 28, 74, 32),
        1: (50, 20, 80, 24),
        8: (32, 32, 40, 40),
        9: (48, 20, 66, 44),
        10: (36, 36, 85, 40),
        11: (42, 32, 70, 26),
        (22 if game == "bg" else 18): (40, 18, 60, 37),
        (26 if game == "bg" else 21): (38, 10, 82, 80),
        (27 if game == "bg" else 22): (36, 12, 70, 26),
        (53 if game == "bg" else 48): (36, 46, 84, 40),
    }
    if game != "bg":
        areas[64] = (62, 22, 36, 44)
    result.areas = {number: U7GumpArea(*bounds) for number, bounds in areas.items()}
    bindings = []
    for layer in sources.layers:
        if layer.name != "CONTAINER.DAT":
            continue
        table = U7Containers.from_bytes(layer.data, source=layer.source, strict=True)
        bindings.append(table)
        for row in table.records:
            number = row.gump_shape
            result.mappings[row.shape] = (number, layer.source)
            # Bundled SI's -1 locked-chest entry means usecode opens it.
            # Explicit owner/mod -1 records must still disable this preview.
            if (layer.patch or is_custom) and number < 0:
                result.disabled.add(row.shape)
            else:
                result.disabled.discard(row.shape)

    result.bindings = U7Containers.merge(*bindings)
    result.metadata = read_u7_gump_metadata(sources)
    result.areas.update(result.metadata.areas)
    result.special.update(result.metadata.special)
    result.warnings = [*result.metadata.warnings, *result.bindings.warnings]
    result.source_files = list(dict.fromkeys(layer.path for layer in sources.layers))
    for layer in sources.layers:
        if layer.name != "SHAPE_INFO.TXT":
            continue
        result.locked.update(
            {
                number: bool(value)
                for number, value in _parse_single_value_section(
                    layer.data.decode("latin-1"), "locked_containers"
                ).items()
            }
        )
    return result


@dataclass(frozen=True)
class U7GumpItemSprite:
    """Direct child's PNG, draw anchor and captured IREG gump coordinates."""

    item_id: int | str
    image: Image.Image
    xleft: int
    yabove: int
    saved_x: int
    saved_y: int


@dataclass
class U7GumpComposition:
    """Native image and reproducible placement evidence for previews and reports."""

    image: Image.Image
    area: U7GumpArea
    pixel_area: tuple[int, int, int, int]
    placements: list[dict[str, int | str | bool]]
    diagnostics: list[str]
    layout: str
    seed: int


def compose_u7_container_gump(
    artwork: Image.Image,
    area: U7GumpArea,
    sprites: list[U7GumpItemSprite],
    *,
    gump_origin: tuple[int, int] = (0, 0),
    layout: str = "random",
    seed: int = 0,
) -> U7GumpComposition:
    """Paint direct sprites at native size; keep valid saved anchors, otherwise arrange."""
    if layout not in {"random", "saved"}:
        raise ValueError("U7 container gump: layout must be random or saved")
    if area.width <= 0 or area.height <= 0:
        raise ValueError("U7 container gump: invalid storage area")
    ax, ay = area.x + gump_origin[0], area.y + gump_origin[1]
    left, top = max(0, ax), max(0, ay)
    right, bottom = (
        min(artwork.width, ax + area.width),
        min(artwork.height, ay + area.height),
    )
    if right <= left or bottom <= top:
        raise ValueError("U7 container gump: storage area is outside artwork")
    result = U7GumpComposition(
        artwork.convert("RGBA"), area, (left, top, right, bottom), [], [], layout, seed
    )
    if (left, top, right, bottom) != (ax, ay, ax + area.width, ay + area.height):
        result.diagnostics.append(
            "Storage area intersects artwork edge; visible bounds used"
        )
    # Non-security randomness: reproduce a visual layout from its report seed.
    rng = random.Random(seed)  # nosec B311
    # Exult check_elem_positions detects unopened inventories with identical positions.
    same_positions = (
        len(sprites) > 1
        and len({(item.saved_x, item.saved_y) for item in sprites}) == 1
    )
    curx = cury = loop = 0
    for item in sprites:
        image = item.image.convert("RGBA")
        width, height = min(image.width, right - left), min(image.height, bottom - top)
        if width <= 0 or height <= 0:
            result.diagnostics.append(f"{item.item_id}: empty sprite")
            continue
        x, y = ax + item.saved_x - item.xleft, ay + item.saved_y - item.yabove
        saved_valid = (
            not same_positions
            and left <= x <= right - image.width
            and top <= y <= bottom - image.height
            and (item.saved_x, item.saved_y) != (255, 255)
        )
        if layout == "saved" and saved_valid:
            source = "saved"
        elif layout == "saved":
            # Gump::paint arranges unplaced sprites in rows with an eight-pixel step.
            x, y = (
                left + min(curx + 1, right - left - width),
                top + min(cury + 1, bottom - top - height),
            )
            source = "auto"
            curx += max(1, image.width - 1)
            if curx >= right - left:
                curx = 0
                cury += 8
                if cury >= bottom - top:
                    loop += 1
                    cury = 2 * loop
        else:

            def overlap(px: int, py: int) -> int:
                return sum(
                    max(
                        0,
                        min(px + width, int(p["left"]) + int(p["width"]))
                        - max(px, int(p["left"])),
                    )
                    * max(
                        0,
                        min(py + height, int(p["top"]) + int(p["height"]))
                        - max(py, int(p["top"])),
                    )
                    for p in result.placements
                )

            best: tuple[int, int, int] | None = None
            for _ in range(128):
                px, py = (
                    rng.randint(left, right - width),
                    rng.randint(top, bottom - height),
                )
                candidate = overlap(px, py), px, py
                if best is None or candidate[0] < best[0]:
                    best = candidate
                if candidate[0] == 0:
                    break
            if best is None:
                raise ValueError("U7 container gump: could not choose item position")
            _, x, y = best
            source = "random"
        clipped = image.size != (width, height)
        overlap_area = sum(
            max(
                0,
                min(x + width, int(p["left"]) + int(p["width"]))
                - max(x, int(p["left"])),
            )
            * max(
                0,
                min(y + height, int(p["top"]) + int(p["height"]))
                - max(y, int(p["top"])),
            )
            for p in result.placements
        )
        if overlap_area:
            result.diagnostics.append(
                f"{item.item_id}: inventory items overlap ({overlap_area} bounding-box pixels)"
            )
        if clipped:
            result.diagnostics.append(
                f"{item.item_id}: sprite exceeds storage bounds; clipped at native size"
            )
        result.image.alpha_composite(image.crop((0, 0, width, height)), (x, y))
        result.placements.append(
            {
                "item_id": item.item_id,
                "left": x,
                "top": y,
                "width": width,
                "height": height,
                "anchor_x": x + item.xleft - ax,
                "anchor_y": y + item.yabove - ay,
                "position_source": source,
                "clipped": clipped,
                "overlap_area": overlap_area,
            }
        )
    return result
