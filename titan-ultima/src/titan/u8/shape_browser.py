"""U8 shape browser data, anchor-aligned sprite sequences and exclusive exports.

Actor previews follow ANIM nodes and optional WPNOVLAY screen offsets. They
show sprite choreography at a chosen preview speed, without executing game
movement, collision, sounds or usecode. Metadata stays with its archive owner.
"""

from __future__ import annotations

import io
import json
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from titan._config import cfg
from titan._terminal_image import FrameProvider, checkerboard
from titan.flex import FlexArchive
from titan.palette import U8Palette
from titan.u8.anim import DIRECTION_NAMES, U8AnimAction, U8AnimData
from titan.u8.anim_report import format_u8_anim_report
from titan.u8.shape import U8Shape
from titan.u8.shape_names import load_u8_shape_names
from titan.u8.typeflag import U8TypeFlags
from titan.u8.wpnovlay import U8WeaponOverlayData

U8_SHAPE_ARCHIVES = ("U8SHAPES.FLX", "U8GUMPS.FLX", "U8FONTS.FLX")
U8_BROWSER_OUTPUT = Path("titan-out/u8_shape_browse_export")


def find_u8_browser_file(directory: Path, filename: str) -> Path | None:
    """Find one owner's immediate file case-insensitively, without recursive mixing."""
    if not directory.is_dir():
        return None
    return next(
        (
            path
            for path in sorted(directory.iterdir())
            if path.is_file() and path.name.casefold() == filename.casefold()
        ),
        None,
    )


def configured_u8_browser_file(directory: Path, key: str) -> Path | None:
    """Use a configured asset only when it belongs to the selected STATIC owner."""
    value = cfg(key)
    if value:
        path = Path(value).expanduser().resolve()
        if path.parent == directory.resolve():
            return path
    return None


@dataclass(frozen=True)
class U8ShapeTarget:
    name: str
    static: Path


def discover_u8_shape_targets(directory: Path | None = None) -> list[U8ShapeTarget]:
    """Discover configured/explicit U8 STATIC owners and installed language variants."""
    configured = cfg("base", "game")
    shapes = cfg("u8shapes")
    base = directory or (
        Path(configured).expanduser()
        if configured
        else Path(shapes).expanduser().parent
        if shapes
        else None
    )
    if base is None or not base.is_dir():
        return []
    direct = next(
        (
            path
            for path in sorted(base.iterdir())
            if path.is_dir() and path.name.casefold() == "static"
        ),
        None,
    )
    if direct:
        return [U8ShapeTarget(base.name, direct)]
    targets = []
    for language in ("ENGLISH", "FRENCH", "GERMAN"):
        owner = next(
            (
                path
                for path in sorted(base.iterdir())
                if path.is_dir() and path.name.casefold() == language.casefold()
            ),
            None,
        )
        if owner:
            static = next(
                (
                    path
                    for path in sorted(owner.iterdir())
                    if path.is_dir() and path.name.casefold() == "static"
                ),
                None,
            )
            if static:
                targets.append(U8ShapeTarget(language.title(), static))
    return targets or [U8ShapeTarget(base.name, base)]


@dataclass
class U8ShapeLibrary:
    """One archive/standalone shape, palette and optional metadata from that owner."""

    path: Path
    records: dict[int, bytes]
    palette: U8Palette
    palette_path: Path
    world_shapes: bool
    names: dict[int, str]
    properties: dict[int, U8TypeFlags.ShapeEntry]
    animations: U8AnimData | None
    overlays: U8WeaponOverlayData | None
    source_paths: tuple[Path, ...]
    diagnostics: list[str]
    property_filter: str = "all"
    _shapes: dict[int, U8Shape] = field(default_factory=dict, repr=False)
    _size_adjustments: dict[int, int] = field(default_factory=dict, repr=False)

    @property
    def ids(self) -> list[int]:
        return sorted(self.records)

    def shape(self, number: int) -> U8Shape:
        """Validate record/frame bounds before invoking the existing U8 sprite decoder."""
        if number not in self.records:
            raise ValueError(
                f"U8 shape browser: slot {number} is empty or outside the library"
            )
        if number in self._shapes:
            return self._shapes[number]
        raw = self.records[number]
        if len(raw) < 6:
            raise ValueError(f"U8 shape browser: shape {number} has a truncated header")
        count = struct.unpack_from("<H", raw, 4)[0]
        table_end = 6 + count * 6
        if not 0 < count <= 20000 or table_end > len(raw):
            raise ValueError(
                f"U8 shape browser: shape {number} has an invalid frame table"
            )
        offsets = [
            int.from_bytes(raw[6 + index * 6 : 9 + index * 6], "little")
            for index in range(count)
        ]
        starts = sorted(set(offsets))
        ends = dict(zip(starts, starts[1:] + [len(raw)]))
        # Pentagram's U82DShapeFormat excludes the first eight frame bytes
        # from stored lengths. Recognize that exact convention across the
        # record, including standalone interface shapes, before bounds checks.
        adjustment = (
            8
            if all(
                offset + struct.unpack_from("<H", raw, 10 + index * 6)[0] + 8
                == ends[offset]
                for index, offset in enumerate(offsets)
            )
            else 0
        )
        pixels = 0
        for index in range(count):
            cell = 6 + index * 6
            offset = int.from_bytes(raw[cell : cell + 3], "little")
            size = struct.unpack_from("<H", raw, cell + 4)[0] + adjustment
            if offset < table_end or size < 18 or offset + size > len(raw):
                raise ValueError(
                    f"U8 shape browser: shape {number} frame {index} has invalid bounds"
                )
            width, height = struct.unpack_from("<hh", raw, offset + 10)
            if width > 0 and height > 0:
                pixels += width * height
                if pixels > 16_000_000 or 18 + height * 2 > size:
                    raise ValueError(
                        f"U8 shape browser: shape {number} frame {index} has invalid dimensions"
                    )
        decoded = U8Shape.from_data(raw)
        self._shapes[number] = decoded
        self._size_adjustments[number] = adjustment
        return decoded

    def actions(self, number: int) -> list[U8AnimAction]:
        return (
            [
                action
                for action in self.animations.iter_actions()
                if action.shape_num == number
            ]
            if self.animations
            else []
        )

    def image(self, number: int, frame: int, *, indexed: bool = False) -> Image.Image:
        """Render only one frame; indexed exports retain palette indices and 255 alpha."""
        shape = self.shape(number)
        if not 0 <= frame < len(shape.frames):
            raise ValueError(f"U8 shape browser: shape {number} has no frame {frame}")
        entry = shape.frames[frame]
        if entry.pixels is None:
            return Image.new("RGBA", (1, 1))
        if indexed:
            image = Image.fromarray(entry.pixels).convert("P")
            image.putpalette(self.palette.to_flat_rgb())
            image.info["transparency"] = 255
            return image
        single = U8Shape()
        single.frames = [entry]
        return single.to_pngs(self.palette)[0]


def load_u8_shape_library(
    path: Path,
    *,
    palette: Path | None = None,
    typeflag: Path | None = None,
    anim: Path | None = None,
    wpnovlay: Path | None = None,
    shape_id: int | None = None,
) -> U8ShapeLibrary:
    """Load owner-bound assets; explicit optional files fail clearly if malformed."""
    path = path.expanduser().resolve()
    world = (
        path.name.casefold() == "u8shapes.flx"
        or path == configured_u8_browser_file(path.parent, "u8shapes")
        or typeflag is not None
        or anim is not None
    )
    if path.suffix.casefold() == ".shp":
        if shape_id is None:
            prefix = path.stem.split("_", 1)[0]
            shape_id = int(prefix) if prefix.isdecimal() else 0
        records = {shape_id: path.read_bytes()}
    else:
        archive = FlexArchive.from_file(str(path), strict=True)
        records = {
            number: record for number, record in enumerate(archive.records) if record
        }
    palette = (
        palette
        or configured_u8_browser_file(path.parent, "palette")
        or find_u8_browser_file(path.parent, "U8PAL.PAL")
    )
    if palette is None:
        raise ValueError("U8 shape browser: no owner U8PAL.PAL; supply --palette")
    colour = U8Palette.from_file(str(palette))
    sources = [path, palette.resolve()]
    issues = []
    props: dict[int, U8TypeFlags.ShapeEntry] = {}
    animations = None
    overlays = None
    for filename, explicit in (
        ("TYPEFLAG.DAT", typeflag),
        ("ANIM.DAT", anim),
        ("WPNOVLAY.DAT", wpnovlay),
    ):
        source = explicit
        if source is None and world:
            source = configured_u8_browser_file(
                path.parent, filename.split(".")[0].lower()
            )
            source = source or find_u8_browser_file(path.parent, filename)
        if source is None:
            continue
        try:
            if filename == "TYPEFLAG.DAT":
                raw = source.read_bytes()
                if len(raw) % 8 or len(raw) > 2048 * 8:
                    raise ValueError(
                        "TYPEFLAG.DAT requires complete eight-byte records, at most 2048"
                    )
                props = {entry.shape_num: entry for entry in U8TypeFlags.parse(raw)}
            elif filename == "ANIM.DAT":
                animations = U8AnimData.from_file(source)
            elif animations is None:
                raise ValueError("WPNOVLAY.DAT requires valid paired ANIM.DAT")
            else:
                overlays = U8WeaponOverlayData.from_file(source, animations)
            sources.append(source.resolve())
        except (OSError, ValueError) as error:
            if explicit is not None:
                raise
            issues.append(f"{filename}: {error}")
    return U8ShapeLibrary(
        path,
        records,
        colour,
        palette.resolve(),
        world,
        load_u8_shape_names() if world else {},
        props,
        animations,
        overlays,
        tuple(sources),
        issues,
    )


def matching_u8_shapes(library: U8ShapeLibrary, search: str = "") -> list[int]:
    """Intersect ID/class-label searches with filters, preserving sparse native IDs."""

    def matches(number: int) -> bool:
        prop = library.properties.get(number)
        mode = library.property_filter
        if mode == "all":
            return True
        if mode == "animated":
            return bool(library.actions(number)) or bool(prop and prop.animtype)
        if prop is None:
            return False
        if mode == "container":
            return prop.is_container()
        if mode == "equipment":
            return bool(prop.equiptype)
        bits = {"solid": 2, "roof": 0x400, "translucent": 0x800, "fixed": 1}
        if mode not in bits:
            raise ValueError(f"U8 shape browser: unknown property filter {mode}")
        return bool(prop.flags & bits[mode])

    ids = [number for number in library.ids if matches(number)]
    search = search.strip()
    if not search:
        return ids
    try:
        number = int(search, 16 if search.casefold().startswith("0x") else 10)
        return [number] if number in ids else []
    except ValueError:
        return [
            number
            for number in ids
            if search.casefold() in library.names.get(number, "").casefold()
        ]


def aligned_u8_sequence(
    library: U8ShapeLibrary,
    number: int,
    *,
    action: int | None = None,
    direction: int = 0,
    overlay: int | None = None,
) -> tuple[list[Image.Image], list[dict[str, Any]]]:
    """Keep drawing origins stationary; flip actors and apply overlay screen offsets."""
    shape = library.shape(number)
    if not 0 <= direction < 8:
        raise ValueError("U8 shape browser: direction must be 0-7")
    stream = (
        library.animations.get_action(number, action)
        if library.animations and action is not None
        else None
    )
    if action is not None and stream is None:
        raise ValueError("U8 shape browser: this shape has no selected ANIM action")
    if overlay is not None and (
        number != 1 or stream is None or library.overlays is None
    ):
        raise ValueError(
            "U8 shape browser: weapon overlay needs avatar ANIM and WPNOVLAY"
        )
    components: list[list[tuple[Image.Image, int, int]]] = []
    rows: list[dict[str, Any]] = []
    indices = (
        list(range(len(shape.frames)))
        if stream is None
        else [node.frame for node in stream.directions[direction]]
    )
    for step, index in enumerate(indices):
        if not 0 <= index < len(shape.frames):
            raise ValueError(
                f"U8 shape browser: animation step {step} references missing frame {index}"
            )
        frame = shape.frames[index]
        node = stream.directions[direction][step] if stream else None
        image = library.image(number, index)
        flipped = bool(node and node.flipped)
        xoff = frame.width - 1 - frame.xoff if flipped else frame.xoff
        if flipped:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        parts = [(image, -xoff, -frame.yoff)]
        row: dict[str, Any] = {"step": step, "frame": index, "flipped": flipped}
        if node:
            row.update(
                {
                    key: value.hex() if isinstance(value, bytes) else value
                    for key, value in asdict(node).items()
                }
            )
        if overlay is not None:
            over = (
                library.overlays.get_action(action)
                if library.overlays is not None and action is not None
                else None
            )
            if over is None or not 0 <= overlay < len(over.overlays):
                raise ValueError(
                    "U8 shape browser: selected action has no such overlay slot"
                )
            slot = over.overlays[overlay]
            if slot.shape_num is None:
                raise ValueError(
                    "U8 shape browser: overlay slot has no native sprite mapping"
                )
            weapon = slot.directions[direction][step]
            wshape = library.shape(slot.shape_num)
            if weapon.frame >= len(wshape.frames):
                raise ValueError(
                    f"U8 shape browser: overlay references missing frame {weapon.frame}"
                )
            wframe = wshape.frames[weapon.frame]
            parts.append(
                (
                    library.image(slot.shape_num, weapon.frame),
                    weapon.x_offset - wframe.xoff,
                    weapon.y_offset - wframe.yoff,
                )
            )
            row["overlay"] = {
                "type": overlay,
                "name": slot.name,
                "shape": slot.shape_num,
                "frame": weapon.frame,
                "x_offset": weapon.x_offset,
                "y_offset": weapon.y_offset,
            }
        components.append(parts)
        rows.append(row)
    left = min(x for parts in components for _, x, _ in parts)
    top = min(y for parts in components for _, _, y in parts)
    right = max(x + image.width for parts in components for image, x, _ in parts)
    bottom = max(y + image.height for parts in components for image, _, y in parts)
    if (right - left) * (bottom - top) > 16_000_000 or (right - left) * (
        bottom - top
    ) * len(components) > 64_000_000:
        raise ValueError("U8 shape browser: drawing offsets make the preview too large")
    images = []
    for parts in components:
        canvas = Image.new("RGBA", (right - left, bottom - top))
        for image, x, y in parts:
            canvas.alpha_composite(image, (x - left, y - top))
        images.append(canvas)
    return images, rows


def u8_playback_provider(
    images: list[Image.Image], rows: list[dict[str, Any]]
) -> FrameProvider:
    """Loop a selected sprite preview; playback speed is a viewer setting."""

    def image_at(step: int, elapsed_ms: int) -> tuple[Image.Image, str]:
        index = step % len(images)
        return images[
            index
        ], f"Step {index + 1}/{len(images)}; sprite frame {rows[index]['frame']}"

    return image_at


def u8_frame_sheet(
    images: list[Image.Image],
    start: int = 0,
    *,
    label_offset: int = 0,
    title: str = "",
    labels: list[str] | None = None,
) -> Image.Image:
    """Show at most twelve frames with bounded tiles and uncropped artwork."""
    selected = images[start : start + 12]
    if not selected:
        raise ValueError("U8 shape browser: no frames in selected sheet")
    columns = min(4, len(selected))
    title_lines: list[str] = []
    if title:
        measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        for word in title.split():
            candidate = f"{title_lines[-1]} {word}" if title_lines else word
            if title_lines and measure.textlength(candidate) <= columns * 220 - 12:
                title_lines[-1] = candidate
            else:
                title_lines.append(word)
    heading = 16 + len(title_lines) * 16 if title_lines else 0
    sheet = Image.new(
        "RGB",
        (columns * 220, heading + ((len(selected) + columns - 1) // columns) * 200),
        (24, 24, 24),
    )
    draw = ImageDraw.Draw(sheet)
    for line, text in enumerate(title_lines):
        draw.text((6, 6 + line * 16), text, fill="white")
    for index, image in enumerate(selected):
        x, y = index % columns * 220, heading + index // columns * 200
        draw.text(
            (x + 6, y + 6),
            labels[start + index]
            if labels is not None
            else f"Frame/step {label_offset + start + index}: {image.width}x{image.height}",
            fill="white",
        )
        scale = min(3, 208 / image.width, 168 / image.height)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        cell = checkerboard(size)
        cell.alpha_composite(
            image.convert("RGBA").resize(size, Image.Resampling.NEAREST)
        )
        sheet.paste(cell.convert("RGB"), (x + 6, y + 26))
    return sheet


@dataclass(frozen=True)
class U8ContactSheetGroup:
    """A named raw frame page or complete ANIM action/direction sequence."""

    key: str
    label: str
    frame_count: int
    start: int = 0
    action: int | None = None
    direction: int = 0
    overlay: int | None = None


def u8_contact_sheet_groups(
    library: U8ShapeLibrary,
    number: int,
    *,
    animated: bool = False,
    overlay: int | None = None,
) -> list[U8ContactSheetGroup]:
    """List sets for one shape, preserving action IDs, directions and raw ranges."""
    shape = library.shape(number)
    if not animated:
        return [
            U8ContactSheetGroup(
                f"shape_{number:04d}_frames_{start:04d}_{min(start + 12, len(shape.frames)) - 1:04d}",
                f"Shape {number}: raw frames {start}-{min(start + 12, len(shape.frames)) - 1}",
                min(12, len(shape.frames) - start),
                start=start,
            )
            for start in range(0, len(shape.frames), 12)
        ]
    if overlay is not None and (number != 1 or library.overlays is None or overlay < 0):
        raise ValueError(
            "U8 shape browser: contact sheet overlay needs avatar WPNOVLAY"
        )
    groups = []
    for action in library.actions(number):
        weapon = (
            library.overlays.get_action(action.action_num) if library.overlays else None
        )
        selected_overlay = None
        if (
            overlay is not None
            and weapon is not None
            and overlay < len(weapon.overlays)
        ):
            if weapon.overlays[overlay].shape_num is None:
                raise ValueError(
                    "U8 shape browser: overlay slot has no native sprite mapping"
                )
            selected_overlay = overlay
        for direction, name in enumerate(DIRECTION_NAMES):
            key = f"shape_{number:04d}_action_{action.action_num:02d}_{FlexArchive._safe_filename(action.name).lower()}_{name.lower()}"
            label = f"Shape {number}: action {action.action_num} {action.name}, {name}"
            if selected_overlay is not None and weapon is not None:
                slot = weapon.overlays[selected_overlay]
                key += f"_overlay_{selected_overlay}_{FlexArchive._safe_filename(slot.name).lower()}"
                label += f", {slot.name} overlay"
            groups.append(
                U8ContactSheetGroup(
                    key,
                    label,
                    action.frame_count,
                    action=action.action_num,
                    direction=direction,
                    overlay=selected_overlay,
                )
            )
    return groups


def export_u8_browser_contact_sheets(
    library: U8ShapeLibrary,
    number: int,
    directory: Path,
    *,
    animated: bool = False,
    group: str | None = None,
    overlay: int | None = None,
) -> list[Path]:
    """Save one or all named sets, paging every step and preflighting all outputs."""
    groups = u8_contact_sheet_groups(
        library, number, animated=animated, overlay=overlay
    )
    if group is not None:
        groups = [entry for entry in groups if entry.key == group]
    if not groups:
        raise ValueError("U8 shape browser: no matching contact sheet frame sets")
    payloads = {}
    for entry in groups:
        if entry.action is None:
            images = [
                library.image(number, index)
                for index in range(entry.start, entry.start + entry.frame_count)
            ]
            labels = [
                f"Frame {entry.start + index}: {image.width}x{image.height}"
                for index, image in enumerate(images)
            ]
            pages = [(entry.key, 0, entry.label)]
        else:
            images, rows = aligned_u8_sequence(
                library,
                number,
                action=entry.action,
                direction=entry.direction,
                overlay=entry.overlay,
            )
            labels = [
                f"Step {index}: sprite frame {row['frame']}"
                for index, row in enumerate(rows)
            ]
            pages = [
                (
                    f"{entry.key}_steps_{start:04d}_{min(start + 12, len(images)) - 1:04d}",
                    start,
                    f"{entry.label}; steps {start}-{min(start + 12, len(images)) - 1}",
                )
                for start in range(0, len(images), 12)
            ]
        for key, start, title in pages:
            sheet = u8_frame_sheet(images, start, title=title, labels=labels)
            buffer = io.BytesIO()
            sheet.save(buffer, format="PNG")
            payloads[directory / f"{key}.png"] = buffer.getvalue()
    return _write_u8_browser_exports(library, payloads)


def describe_u8_browser_shape(library: U8ShapeLibrary, number: int) -> dict[str, Any]:
    """Describe frame origins, TYPEFLAG and ANIM data with explicit source coverage."""
    shape = library.shape(number)
    prop = library.properties.get(number)
    return {
        "archive": str(library.path),
        "palette": str(library.palette_path),
        "shape": number,
        "class_label": library.names.get(number, ""),
        "sources": [str(path) for path in library.source_paths],
        "diagnostics": library.diagnostics,
        "header0": shape.header0,
        "header1": shape.header1,
        "frame_count": len(shape.frames),
        "frame_length_adjustment": library._size_adjustments[number],
        "frames": [
            {
                "frame": index,
                "width": frame.width,
                "height": frame.height,
                "xoff": frame.xoff,
                "yoff": frame.yoff,
                "compressed": frame.compressed,
                "table_unknown": frame.table_unknown,
                "frame_unknown_hex": frame.frame_unknown.hex(),
            }
            for index, frame in enumerate(shape.frames)
        ],
        "properties": {
            **asdict(prop),
            "flag_names": prop.flag_names(),
            "family_name": prop.family_name(),
            "equip_name": prop.equip_name(),
            "footpad_world": prop.footpad_world(),
        }
        if prop
        else None,
        "animations": json.loads(
            format_u8_anim_report(
                library.animations, shape=number, frames=True, output_format="json"
            )
        )["actions"]
        if library.animations
        else [],
        "preview_notes": "Sprite sequence preview; speed is user-selected. Movement, collisions, sound and usecode are not executed. Palette colours are shown directly; destination-dependent transform blending is not simulated.",
    }


def _write_u8_browser_exports(
    library: U8ShapeLibrary, payloads: dict[Path, bytes]
) -> list[Path]:
    protected = {path.resolve() for path in library.source_paths}
    for path in payloads:
        if path.resolve() in protected or path.exists():
            raise ValueError(
                f"U8 shape browser: output already exists or is a source: {path}"
            )
    written = []
    for path, payload in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
        written.append(path)
    return written


def export_u8_browser_pngs(
    library: U8ShapeLibrary,
    number: int,
    directory: Path,
    *,
    frames: list[int] | None = None,
    indexed: bool = True,
) -> list[Path]:
    """Export raw shape frames to new PNGs, preserving source indices by default."""
    indices = (
        list(range(len(library.shape(number).frames))) if frames is None else frames
    )
    payloads = {}
    for index in indices:
        buffer = io.BytesIO()
        library.image(number, index, indexed=indexed).save(buffer, format="PNG")
        payloads[directory / f"shape_{number:04d}_f{index:04d}.png"] = buffer.getvalue()
    return _write_u8_browser_exports(library, payloads)


def export_u8_browser_gif(
    library: U8ShapeLibrary,
    number: int,
    path: Path,
    *,
    action: int | None = None,
    direction: int = 0,
    overlay: int | None = None,
    duration_ms: int = 100,
) -> Path:
    """Save an aligned sprite preview GIF at explicitly chosen milliseconds per step."""
    if path.suffix.casefold() != ".gif" or not 20 <= duration_ms <= 2000:
        raise ValueError("U8 shape browser: choose .gif and 20-2000 ms per step")
    images, _ = aligned_u8_sequence(
        library, number, action=action, direction=direction, overlay=overlay
    )
    buffer = io.BytesIO()
    images[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
        optimize=False,
    )
    _write_u8_browser_exports(library, {path: buffer.getvalue()})
    return path


def export_u8_browser_report(library: U8ShapeLibrary, number: int, path: Path) -> Path:
    """Write complete shape/property/ANIM metadata to a new JSON report."""
    if path.suffix.casefold() != ".json":
        raise ValueError("U8 shape browser: choose a .json report filename")
    payload = (
        json.dumps(describe_u8_browser_shape(library, number), indent=2) + "\n"
    ).encode("utf-8")
    _write_u8_browser_exports(library, {path: payload})
    return path
