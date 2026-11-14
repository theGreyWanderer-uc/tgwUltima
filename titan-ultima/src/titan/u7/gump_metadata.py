"""Container/gump resource selection and section-aware Exult layout metadata."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from titan.u7.flex import U7FlexArchive
from titan.u7.shape_archive import find_archive
from titan.u7.text import U7TextMessages


@dataclass(frozen=True)
class U7GumpSource:
    """One selected binary/text resource, with default versus patch provenance."""

    name: str
    data: bytes
    source: str
    path: Path
    patch: bool = False


@dataclass
class U7GumpSources:
    """Selected sources in default-then-patch order; unavailable defaults remain explicit."""

    layers: list[U7GumpSource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_u7_gump_sources(
    static_dir: str | Path | None,
    *,
    patch_dir: str | Path | None = None,
    game: str = "bg",
    exult_flx: str | Path | None = None,
    custom_game: bool = False,
    discover_defaults: bool = True,
) -> U7GumpSources:
    """Select BG/SI bundle defaults or explicit custom-game STATIC, then sparse PATCH.

    A patch directory equal to STATIC is not an extra override. Missing bundle
    resources never silently substitute loose BG/SI STATIC files.
    """
    game = game.lower()
    if game not in ("bg", "si"):
        raise ValueError(f"U7 gump metadata game must be bg or si: {game}")
    result = U7GumpSources()
    resources = {
        "CONTAINER.DAT": 11 if game == "bg" else 8,
        "GUMP_INFO.TXT": 16 if game == "bg" else 20,
        "SHAPE_INFO.TXT": 7 if game == "bg" else 4,
        "PAPERDOL_INFO.TXT": 6 if game == "bg" else 3,
        "SHAPE_FILES.TXT": 8 if game == "bg" else 5,
        "AVATAR_DATA.TXT": 9 if game == "bg" else 6,
        "BODIES.TXT": 5 if game == "bg" else 2,
    }
    static = Path(static_dir).expanduser() if static_dir is not None else None
    if custom_game:
        for name in resources:
            path = find_archive(static, name) if static is not None else None
            if path is not None:
                result.layers.append(
                    U7GumpSource(name, path.read_bytes(), str(path), path)
                )
    else:
        if exult_flx is None and discover_defaults:
            from titan.u7.install import resolve_u7_exult_flx

            exult_flx = resolve_u7_exult_flx(game)
        if exult_flx is None:
            result.warnings.append(
                f"U7 gump metadata: {game.upper()} default bundle unavailable; default mappings and text are unknown."
            )
        else:
            path = Path(exult_flx).expanduser()
            archive = U7FlexArchive.from_file(str(path), strict=True)
            for name, index in resources.items():
                if index < len(archive.records) and archive.records[index]:
                    result.layers.append(
                        U7GumpSource(
                            name, archive.records[index], f"{path}#record={index}", path
                        )
                    )
                else:
                    result.warnings.append(
                        f"U7 gump metadata: {name} resource {index} unavailable in {path}."
                    )
    patch = Path(patch_dir).expanduser() if patch_dir is not None else None
    if patch is not None and (static is None or patch.resolve() != static.resolve()):
        for name in resources:
            path = find_archive(patch, name)
            if path is not None:
                result.layers.append(
                    U7GumpSource(name, path.read_bytes(), str(path), path, True)
                )
    return result


@dataclass(frozen=True)
class U7GumpArea:
    """Storage rectangle in native pixels relative to the gump's draw anchor."""

    x: int
    y: int
    width: int
    height: int
    source: str = "Exult Container_gump::initialize"


@dataclass(frozen=True)
class U7GumpCheckmark:
    """Close-button anchor coordinates and artwork shape, separate from the storage area."""

    x: int
    y: int
    shape: int
    source: str = ""


@dataclass
class U7GumpMetadata:
    """Inspect area, checkmark, special and debug sections without executing gump widgets."""

    areas: dict[int, U7GumpArea] = field(default_factory=dict)
    checkmarks: dict[int, U7GumpCheckmark] = field(default_factory=dict)
    special: set[int] = field(default_factory=set)
    special_sources: dict[int, str] = field(default_factory=dict)
    debug_flags: dict[int, int] = field(default_factory=dict)
    debug_sources: dict[int, str] = field(default_factory=dict)
    raw_sources: dict[str, bytes] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    widgets: dict[str, dict[int, list[dict[str, object]]]] = field(default_factory=dict)

    def apply_text(self, data: bytes, source: str = "", *, patch: bool = False) -> None:
        """Replace present section fields; omitted debug fields and sections inherit."""
        parsed = U7TextMessages.from_bytes(data)
        self.raw_sources[source] = data
        self.warnings.extend(parsed.warnings)
        self._apply_widgets(parsed, source, patch)
        for section in ("container_area", "checkmark_pos", "special"):
            for index, value in sorted(parsed.sections.get(section, {}).items()):
                parts = value.split("#", 1)[0].strip().split("/")
                required = (
                    5
                    if section == "container_area"
                    else 4
                    if section == "checkmark_pos"
                    else 1
                )
                fields = parts[: required + (section == "container_area")]
                if len(parts) < required or any(
                    re.fullmatch(r"[+-]?[0-9]+", part.strip()) is None
                    for part in fields
                ):
                    raise ValueError(
                        f"U7 gump metadata: malformed {section} in {source}: {value!r}; decimal integers required"
                    )
                values = [int(part, 10) for part in fields]
                number = values[0]
                if not 0 <= number <= 65535:
                    raise ValueError(
                        f"U7 gump metadata: {section} shape outside u16 in {source}: {number}"
                    )
                row_source = f"{source}#{section}:{index}"
                if section == "container_area":
                    self.areas[number] = U7GumpArea(
                        values[1], values[2], values[3], values[4], row_source
                    )
                    if len(values) == 6:
                        self.debug_flags[number] = values[5]
                        self.debug_sources[number] = row_source
                    elif number not in self.debug_flags:
                        self.debug_flags[number] = 0
                        self.debug_sources[number] = (
                            "Exult Gump_info initialization (omitted debug field)"
                        )
                elif section == "checkmark_pos":
                    self.checkmarks[number] = U7GumpCheckmark(
                        values[1], values[2], values[3], row_source
                    )
                else:
                    self.special.add(number)
                    self.special_sources[number] = row_source

    def as_row(self, number: int) -> dict[str, object]:
        """Keep absent metadata distinct from explicit zero fields, including provenance."""
        area, checkmark = self.areas.get(number), self.checkmarks.get(number)
        return {
            "gump_shape": number,
            "area": asdict(area) if area is not None else None,
            "checkmark": asdict(checkmark) if checkmark is not None else None,
            "special": number in self.special,
            "special_source": self.special_sources.get(number, ""),
            "debug_flags": self.debug_flags.get(number),
            "debug_flags_source": self.debug_sources.get(number, ""),
            "widgets": {
                section: records[number]
                for section, records in self.widgets.items()
                if number in records
            },
        }

    def _apply_widgets(self, parsed: U7TextMessages, source: str, patch: bool) -> None:
        schemas = {
            "snap_zones": (
                "zone_id",
                "zone_x",
                "zone_y",
                "zone_w",
                "zone_h",
                "snap_x",
                "snap_y",
                "priority",
                "zone_type",
            ),
            "dynamic_buttons": (
                "button_shape",
                "pos_x",
                "pos_y",
                "default_frame",
                "clicked_frame",
                "sound_fx",
                "usecode_fn",
                "action_type",
                "visibility_flag",
                "usecode_param",
            ),
            "dynamic_texts": (
                "field_id",
                "pos_x",
                "pos_y",
                "font_num",
                "halign",
                "valign",
            ),
            "dynamic_shapes": (
                "field_id",
                "pos_x",
                "pos_y",
                "shape_num",
                "frame_num",
                "shapefile",
            ),
            "dynamic_sliders": (
                "field_id",
                "pos_x",
                "pos_y",
                "dec_shape",
                "inc_shape",
                "thumb_shape",
                "min_val",
                "max_val",
                "step",
                "default_val",
                "extent",
                "usecode_fn",
                "orientation",
            ),
        }
        for section, fields in schemas.items():
            replaced: set[int] = set()
            for index, value in sorted(parsed.sections.get(section, {}).items()):
                parts = value.split("#", 1)[0].split("/")
                required = 5 if section == "dynamic_texts" else len(fields) + 1
                if not required <= len(parts) <= len(fields) + 1:
                    raise ValueError(
                        f"U7 gump metadata: malformed {section} in {source}: {value!r}"
                    )
                values: dict[str, object] = {}
                try:
                    if re.fullmatch(r"[+-]?[0-9]+", parts[0].strip()) is None:
                        raise ValueError("decimal shape required")
                    number = int(parts[0], 10)
                    for field_name, part in zip(fields, parts[1:]):
                        if section == "snap_zones" and field_name in (
                            "zone_id",
                            "zone_type",
                        ):
                            values[field_name] = (
                                part.rstrip("\r\n ")
                                if field_name == "zone_type"
                                else part
                            )
                        else:
                            if re.fullmatch(r"[+-]?[0-9]+", part.strip()) is None:
                                raise ValueError("decimal integer required")
                            values[field_name] = int(part, 10)
                except ValueError as error:
                    raise ValueError(
                        f"U7 gump metadata: malformed {section} in {source}: {value!r}"
                    ) from error
                if not 0 <= number <= 65535:
                    raise ValueError(
                        f"U7 gump metadata: {section} shape outside u16: {number}"
                    )
                rows = self.widgets.setdefault(section, {})
                if patch and number not in replaced:
                    rows[number] = []
                    replaced.add(number)
                if section == "dynamic_texts":
                    values.setdefault("halign", 0)
                    values.setdefault("valign", 0)
                if section == "snap_zones" and (
                    int(str(values["zone_w"])) <= 0 or int(str(values["zone_h"])) <= 0
                ):
                    self.warnings.append(
                        f"U7 gump metadata: rejected nonpositive snap zone in {source}"
                    )
                    continue
                rows.setdefault(number, []).append(
                    {"source": f"{source}#{section}:{index}", **values}
                )

    def dump_csv(self) -> str:
        """Export geometry, close-button and debug fields with separate section sources."""
        numbers = sorted(
            self.areas.keys()
            | self.checkmarks.keys()
            | self.special
            | {number for rows in self.widgets.values() for number in rows}
        )
        if not numbers:
            return ""
        rows = []
        for number in numbers:
            area, checkmark = self.areas.get(number), self.checkmarks.get(number)
            rows.append(
                {
                    "gump_shape": number,
                    **{
                        f"area_{key}": getattr(area, key) if area is not None else ""
                        for key in ("x", "y", "width", "height", "source")
                    },
                    **{
                        f"checkmark_{key}": getattr(checkmark, key)
                        if checkmark is not None
                        else ""
                        for key in ("x", "y", "shape", "source")
                    },
                    "special": int(number in self.special),
                    "special_source": self.special_sources.get(number, ""),
                    "debug_flags": self.debug_flags.get(number, ""),
                    "debug_flags_source": self.debug_sources.get(number, ""),
                    "widgets": json.dumps(
                        {
                            section: records[number]
                            for section, records in self.widgets.items()
                            if number in records
                        }
                    ),
                }
            )
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()


def read_u7_gump_metadata(sources: U7GumpSources) -> U7GumpMetadata:
    """Compose selected gump text sources without loading graphics or binary mappings."""
    result = U7GumpMetadata(warnings=list(sources.warnings))
    for layer in sources.layers:
        if layer.name == "GUMP_INFO.TXT":
            result.apply_text(layer.data, layer.source, patch=layer.patch)
    return result
