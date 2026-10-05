"""Owner-scoped, read-only properties for the interactive shape browser."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from titan.u7.save import U7ReadyTypes
from titan.u7.shape_extra import _parse_single_value_section, U7FieldType
from titan.u7.shapeinfo import U7Ammos, U7Armors, U7Containers, U7Weapons, _read_count
from titan.u7.typeflag import U7TypeFlags

if TYPE_CHECKING:
    from titan.u7.shape_browser import ShapeLibrary
    from titan.u7.shape import U7Shape


@dataclass
class ShapeProperties:
    tables: dict[str, dict[int, dict[str, object]]] = field(default_factory=dict)
    blobs: dict[str, bytes] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    extra: dict[str, dict[int, int]] = field(default_factory=dict)
    extra_sources: dict[tuple[str, int], str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    scoped: bool = True
    extended_tfa: bool = False


def combat_rows(kind: str, data: bytes, game: str) -> dict[int, dict[str, object]]:
    if kind == "weapon":
        text = U7Weapons.from_bytes(data, game).dump_csv()
    elif kind == "ammo":
        text = U7Ammos.from_bytes(data).dump_csv()
    elif kind == "armor":
        text = U7Armors.from_bytes(data).dump_csv()
    else:
        raise ValueError("Unknown combat table")
    return {int(row["shape"]): dict(row) for row in csv.DictReader(io.StringIO(text))}


def overlay_table(
    properties: ShapeProperties, kind: str, data: bytes, source: str, game: str
) -> None:
    """Sparse keyed records inherit; combat deletion markers remove base rows."""
    sizes = {"weapon": 21, "ammo": 13, "armor": 10, "ready": 9}
    if not data:
        return
    if data[0] == 255 and len(data) < 3:
        raise ValueError("Incomplete extended record count")
    count, pos = _read_count(data)
    size = sizes[kind]
    if pos + count * size > len(data):
        raise ValueError(f"Incomplete {kind} table: declares {count} records")
    if kind == "ready":
        ready = U7ReadyTypes.from_bytes(data, game)
        rows: dict[int, dict[str, object]] = {
            shape: {"slot": slot, "slot_name": ready.slot_name_for_shape(shape)}
            for shape, slot in ready.slots.items()
        }
    else:
        rows = combat_rows(kind, data, game)
    combined = properties.tables.setdefault(kind, {})
    for start in range(pos, pos + count * size, size):
        raw = data[start : start + size]
        shape = int.from_bytes(raw[:2], "little")
        if kind != "ready" and raw[-1] == 255:
            combined.pop(shape, None)
        elif shape in rows:
            combined[shape] = {**rows[shape], "source": source}
            if kind == "ready":
                combined[shape]["spell_flag"] = bool(raw[2] & 1)


def container_records(data: bytes) -> U7Containers:
    if not data:
        return U7Containers(0, [])
    if len(data) < 2 or (data[1] == 255 and len(data) < 4):
        raise ValueError("Incomplete container record count")
    count, pos = _read_count(data, 1)
    size = 6 if data[0] >= 2 else 4
    if pos + count * size > len(data):
        raise ValueError("Incomplete container table")
    return U7Containers.from_bytes(data)


def load_properties(library: ShapeLibrary) -> ShapeProperties:
    from titan.u7 import shape_browser as browser
    from titan.u7.cli import _resolve_u7_exult_flx
    from titan.u7.shapeinfo import _exult_record, _exult_container_record_index

    result = ShapeProperties()
    owner_dirs = [
        directory
        for directory in (library.target.static, library.target.patch)
        if directory
    ]
    if not library.is_shapes or library.path.parent.resolve() not in {
        p.resolve() for p in owner_dirs
    }:
        result.scoped = False
        result.warnings.append(
            "World physics/combat metadata belongs to the owner's SHAPES.VGA; this library has frame properties only."
        )
        return result
    for name in ("TFA.DAT", "SHPDIMS.DAT", "WGTVOL.DAT", "OCCLUDE.DAT"):
        path = browser.owner_file(library.target, name)
        if path:
            result.blobs[name] = path.read_bytes()
            result.sources[name] = str(path)
    tfa = result.blobs.get("TFA.DAT", b"")
    result.extended_tfa = bool(
        len(tfa) != 3584
        and (
            len(tfa) > 3072
            or (
                result.sources.get("TFA.DAT")
                and Path(result.sources["TFA.DAT"]).parent.resolve()
                == library.target.patch.resolve()
            )
        )
    )
    if tfa and len(tfa) != 3584 and len(tfa) % 3:
        result.warnings.append(
            "TFA.DAT contains an incomplete record; physical properties are unavailable."
        )
        result.blobs["TFA.DAT"] = b""
    if not tfa:
        result.warnings.append(
            "TFA.DAT is missing/empty; shape classes and physical flags are unknown."
        )
    for kind, name in (
        ("weapon", "WEAPONS.DAT"),
        ("ammo", "AMMO.DAT"),
        ("armor", "ARMOR.DAT"),
        ("ready", "READY.DAT"),
    ):
        seen: set[Path] = set()
        for directory in owner_dirs:
            path = browser.find_archive(directory, name)
            if path and path.resolve() not in seen:
                seen.add(path.resolve())
                try:
                    overlay_table(
                        result, kind, path.read_bytes(), str(path), library.game
                    )
                except (OSError, ValueError) as error:
                    # A broken patch must not be presented as valid base data.
                    result.tables[kind] = {}
                    result.warnings.append(
                        f"{path}: {error}; {kind} properties unavailable."
                    )
    exult = _resolve_u7_exult_flx(library.game)
    try:
        base_container = (
            browser.find_archive(library.target.static, "CONTAINER.DAT")
            if library.target.static
            else None
        )
        containers = container_records(
            base_container.read_bytes()
            if base_container
            else _exult_record(exult, _exult_container_record_index(library.game))
        )
        for row in containers.records:
            result.tables.setdefault("container", {})[row.shape] = {
                "gump_shape": row.gump_shape,
                "gump_font": row.gump_font,
                "source": str(base_container or exult or "not found"),
            }
        patch_container = browser.find_archive(library.target.patch, "CONTAINER.DAT")
        if patch_container:
            for row in container_records(patch_container.read_bytes()).records:
                result.tables.setdefault("container", {})[row.shape] = {
                    "gump_shape": row.gump_shape,
                    "gump_font": row.gump_font,
                    "source": str(patch_container),
                }
    except (OSError, ValueError) as error:
        result.tables["container"] = {}
        result.warnings.append(f"Container properties unavailable: {error}")
    try:
        text_layers = []
        bundled = _exult_record(exult, 7 if library.game == "bg" else 4)
        if bundled:
            text_layers.append((bundled.decode("latin-1"), exult or "Exult bundle"))
        for directory in owner_dirs:
            path = browser.find_archive(directory, "SHAPE_INFO.TXT")
            if path:
                text_layers.append((path.read_text(encoding="latin-1"), str(path)))
        for text, source in text_layers:
            for section in ("field_type", "barge_type", "mountain_tops"):
                for shape, value in _parse_single_value_section(text, section).items():
                    result.extra.setdefault(section, {})[shape] = value
                    result.extra_sources[section, shape] = source
    except (OSError, ValueError) as error:
        result.warnings.append(f"Exult supplementary properties: {error}")
    return result


def properties_for(library: ShapeLibrary) -> ShapeProperties:
    if library.properties is None:
        library.properties = load_properties(library)
    return library.properties


def metadata_entry(
    library: ShapeLibrary, props: ShapeProperties, number: int
) -> U7TypeFlags.ShapeEntry | None:
    raw_tfa = props.blobs.get("TFA.DAT", b"")
    entry = library.tfa.get(number) if props.scoped and raw_tfa else None
    if props.scoped and props.extended_tfa and (number + 1) * 3 <= len(raw_tfa):
        entry = U7TypeFlags.parse(raw_tfa[number * 3 : (number + 1) * 3]).get(0)
        if entry:
            entry.shape_num = number
    if entry is None:
        return None
    entry = replace(entry)
    # Extended TFA entries must retain auxiliary values at their real shape ID.
    dims = props.blobs.get("SHPDIMS.DAT", b"")
    index = number - 150
    if index >= 0 and (index + 1) * 2 <= len(dims):
        entry.shpdims_y_raw, entry.shpdims_x_raw = dims[index * 2 : index * 2 + 2]
    occlude = props.blobs.get("OCCLUDE.DAT", b"")
    if number // 8 < len(occlude):
        entry.occludes = bool(occlude[number // 8] & (1 << (number % 8)))
    if props.extended_tfa:
        entry.anim_type = -1
    return entry


def filtered_ids(library: ShapeLibrary, mode: str) -> list[int]:
    if mode == "all":
        return library.ids
    props = properties_for(library)
    if not props.scoped:
        return []
    if mode in props.tables or mode in {
        "weapon",
        "ammo",
        "armor",
        "ready",
        "container",
    }:
        return [
            number for number in library.ids if number in props.tables.get(mode, {})
        ]
    result = []
    for number in library.ids:
        entry = metadata_entry(library, props, number)
        if mode == "unknown" and entry is None:
            result.append(number)
        elif entry:
            if mode.startswith("class:") and entry.shape_class == int(
                mode.partition(":")[2]
            ):
                result.append(number)
            elif (
                mode.startswith("flag:")
                and mode.partition(":")[2] in entry.flag_names()
            ):
                result.append(number)
    return result


def choose_filter(library: ShapeLibrary) -> None:
    from titan.u7 import shape_browser as browser

    labels = {
        "A": "All populated shapes",
        "C": "Shape class",
        "F": "Physical flag",
        "W": "Weapons",
        "M": "Ammunition",
        "R": "Armour",
        "E": "Ready-slot data",
        "G": "Container gump mappings",
        "U": "Unknown TFA metadata",
        "Q": "Keep current filter",
    }
    selected = browser._menu("Filter shapes:", labels, "A")
    mode = {
        "A": "all",
        "W": "weapon",
        "M": "ammo",
        "R": "armor",
        "E": "ready",
        "G": "container",
        "U": "unknown",
    }.get(selected)
    if selected == "C":
        classes = {
            str(number): f"{number}: {name}"
            for number, name in U7TypeFlags.SHAPE_CLASS_NAMES.items()
        }
        classes["Q"] = "Back"
        choice = browser._menu("Shape class:", classes, "6")
        mode = "class:" + choice if choice != "Q" else None
    elif selected == "F":
        flags = (
            list(U7TypeFlags.BYTE0_FLAG_NAMES.values())
            + list(U7TypeFlags.BYTE1_FLAG_NAMES.values())
            + list(U7TypeFlags.BYTE2_FLAG_NAMES.values())
            + ["occludes", "x_obstacle", "y_obstacle"]
        )
        options = {str(i): name for i, name in enumerate(flags, 1)}
        options["Q"] = "Back"
        choice = browser._menu("Physical flag:", options, "4")
        mode = "flag:" + options[choice] if choice != "Q" else None
    if mode is not None:
        library.property_filter = mode
        print(f"  Filter: {mode}; {len(filtered_ids(library, mode))} populated shapes.")


def property_report(
    library: ShapeLibrary, shape: U7Shape, number: int, frame: int
) -> dict[str, object]:
    props = properties_for(library)
    item = shape.frames[frame]
    selected = library.archive.selected.records
    archive_source = (
        library.path
        if number < len(selected) and selected[number]
        else library.base_path
    )
    report: dict[str, object] = {
        "shape": number,
        "name": library.name(number),
        "archive": str(archive_source),
        "frame_count": len(shape.frames),
        "frame": frame,
        "frame_type": "raw flat" if item.is_tile else "RLE object",
        "pixel_size": [item.width, item.height],
        "origin_right_bottom": [item.origin_x, item.origin_y],
        "maximum_frame_size": [
            max(f.width for f in shape.frames),
            max(f.height for f in shape.frames),
        ],
        "index_255": "opaque" if item.is_tile else "transparent",
        "warnings": props.warnings,
    }
    entry = metadata_entry(library, props, number)
    if entry:
        flags = [
            flag
            for flag in entry.flag_names()
            if not (props.extended_tfa and flag.startswith("anim:"))
        ]
        report["physics"] = {
            "class": entry.shape_class_name,
            "class_id": entry.shape_class,
            "tfa_hex": entry.tfa.hex(),
            "tile_dimensions": [entry.dims_x, entry.dims_y, entry.dims_z],
            "frame_bit5_reflection": len(shape.frames) <= 32,
            "flags": flags,
            "tfa_animation": "not stored in extended TFA"
            if props.extended_tfa
            else entry.anim_type_name,
        }
    else:
        report["physics"] = "Unknown / unavailable"
    if props.scoped:
        for name, stride, index in (
            ("WGTVOL.DAT", 2, number),
            ("SHPDIMS.DAT", 2, number - 150),
        ):
            blob = props.blobs.get(name, b"")
            if index >= 0 and (index + 1) * stride <= len(blob):
                raw = blob[index * stride : (index + 1) * stride]
                report[
                    "weight_volume" if name == "WGTVOL.DAT" else "obstacle_dimensions"
                ] = (
                    {"weight": raw[0], "volume": raw[1], "units": "stored game units"}
                    if name == "WGTVOL.DAT"
                    else {
                        "x": raw[1] >> 1,
                        "y": raw[0] >> 1,
                        "x_obstacle": bool(raw[1] & 1),
                        "y_obstacle": bool(raw[0] & 1),
                    }
                )
        report["metadata_sources"] = props.sources
        for kind, rows in props.tables.items():
            if number in rows:
                report[kind] = rows[number]
        extra = {}
        for section, values in props.extra.items():
            if number in values:
                value = values[number]
                extra[section] = {
                    "value": value,
                    "source": props.extra_sources[section, number],
                }
                if section == "field_type":
                    extra[section]["name"] = (
                        U7FieldType(value).name.lower()
                        if value in U7FieldType._value2member_map_
                        else "unknown"
                    )
        report["exult_extra"] = extra
    return report


def report_lines(report: dict[str, object]) -> list[str]:
    lines: list[str] = []
    for key, value in report.items():
        if key == "warnings":
            if isinstance(value, list):
                lines.extend(
                    f"  NOTE: {warning}"
                    for warning in value
                    if isinstance(warning, str)
                )
        elif isinstance(value, dict):
            lines.append(key.replace("_", " ").title() + ":")
            lines.extend(
                f"  {name.replace('_', ' ')}: {item}" for name, item in value.items()
            )
        else:
            lines.append(f"{key.replace('_', ' ').title()}: {value}")
    return lines


def export_report(library: ShapeLibrary, report: dict[str, object]) -> None:
    from titan.u7 import shape_browser as browser

    path = browser._path(
        "JSON report (new file)", f"shape_{report['shape']}_properties.json"
    )
    resolved = path.resolve()
    protected = [
        directory.resolve()
        for directory in (
            library.target.static,
            library.target.patch,
            library.target.root,
            library.target.gamedat,
            library.target.save_root,
        )
        if directory
    ]
    if any(
        resolved == directory or directory in resolved.parents
        for directory in protected
    ) or resolved in {
        p.resolve()
        for p in (library.path, library.base_path, library.palette_path)
        if p
    }:
        raise ValueError(
            "Choose a report output outside game/mod folders and source archives."
        )
    browser.save_bytes(
        path, (json.dumps(report, indent=2, default=str) + "\n").encode("utf-8")
    )
    print(f"  Saved: {path}")


def show_properties(
    library: ShapeLibrary, shape: U7Shape, number: int, frame: int
) -> None:
    from titan.u7 import shape_browser as browser

    report = property_report(library, shape, number, frame)
    lines = report_lines(report)
    page, size = 0, 15
    last = (len(lines) - 1) // size
    while True:
        print(f"\nShape {number} properties — page {page + 1}/{last + 1}")
        print("\n".join(lines[page * size : (page + 1) * size]))
        labels = {"E": "Export JSON properties report", "Q": "Back to shape"}
        if page < last:
            labels["N"] = "Next page"
        if page:
            labels["B"] = "Previous page"
        action = browser._menu(
            "Shape properties:", labels, "N" if "N" in labels else "Q"
        )
        if action == "Q":
            return
        if action == "E":
            try:
                export_report(library, report)
            except (OSError, ValueError) as error:
                print(f"  ERROR: {error}")
        else:
            page += 1 if action == "N" else -1
