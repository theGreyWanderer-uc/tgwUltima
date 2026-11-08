"""Paperdoll character/item overlays and native slot layout inspection; no widget execution."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Mapping

from titan.u7.gump_metadata import U7GumpSources
from titan.u7.text import U7TextMessages

PAPERDOLL_SLOT_NAMES = (
    "head",
    "back",
    "belt",
    "left_hand",
    "left_finger",
    "legs",
    "feet",
    "right_finger",
    "right_hand",
    "torso",
    "neck",
    "ammo",
    "back2",
    "back3",
    "ears",
    "cloak",
    "gloves",
    "usecode_container",
)
PAPERDOLL_SLOT_POSITIONS = (
    (76, 20),
    (115, 27),
    (105, 65),
    (38, 55),
    (55, 62),
    (80, 80),
    (84, 105),
    (90, 50),
    (117, 55),
    (45, 35),
    (44, 26),
    (69, 59),
    (59, 19),
    (94, 20),
    (76, 26),
    (76, 33),
    (73, 53),
    (0, 0),
)
PAPERDOLL_BLUE_POSITIONS = (
    (76, 20),
    (64, 27),
    (54, 56),
    (30, 58),
    (55, 62),
    (80, 80),
    (84, 105),
    (90, 50),
    (68, 50),
    (45, 37),
    (22, 26),
    (69, 59),
    (59, 19),
    (94, 20),
    (76, 26),
    (76, 33),
    (73, 53),
    (0, 0),
)
PAPERDOLL_HOT_POSITIONS = (
    (76, 20),
    (94, 27),
    (92, 61),
    (38, 55),
    (55, 62),
    (80, 80),
    (84, 105),
    (90, 50),
    (117, 55),
    (83, 43),
    (76, 41),
    (69, 59),
    (59, 19),
    (94, 20),
    (76, 26),
    (76, 33),
    (73, 53),
    (0, 0),
)


@dataclass
class U7PaperdollMetadata:
    """Retain raw rows and resolve characters/items by their distinct replacement keys."""

    characters: dict[int, dict[str, object]] = field(default_factory=dict)
    items: dict[tuple[int, int, int], dict[str, object]] = field(default_factory=dict)
    raw_sources: dict[str, bytes] = field(default_factory=dict)
    raw_rows: list[dict[str, object]] = field(default_factory=list)
    unresolved: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def apply_text(
        self,
        data: bytes,
        source: str = "",
        *,
        skin_shapes: Mapping[str, int] | None = None,
    ) -> None:
        parsed = U7TextMessages.from_bytes(data)
        self.raw_sources[source] = data
        self.warnings.extend(parsed.warnings)
        version = int(next(iter(parsed.sections.get("version", {}).values()), "1"), 10)
        for section in ("characters", "items"):
            for index, value in sorted(parsed.sections.get(section, {}).items()):
                parts = [
                    part.strip() for part in value.split("#", 1)[0].strip().split("/")
                ]
                row = {
                    "source": f"{source}#{section}:{index}",
                    "raw": value,
                    "version": version,
                }
                self.raw_rows.append(row)
                shape_text = parts[0]
                if shape_text.startswith("%"):
                    shape = (skin_shapes or {}).get(shape_text)
                    if shape is None or shape < 0:
                        self.unresolved.append(row)
                        self.warnings.append(
                            f"U7 paperdoll metadata: skin binding {shape_text} needs matching SHAPE_FILES.TXT imports in {source}"
                        )
                        continue
                else:
                    try:
                        if re.fullmatch(r"[+-]?[0-9]+", shape_text) is None:
                            raise ValueError("decimal shape required")
                        shape = int(shape_text, 10)
                    except ValueError as error:
                        raise ValueError(
                            f"U7 paperdoll metadata: invalid shape in {source}: {value!r}"
                        ) from error
                try:
                    if any(
                        re.fullmatch(r"[+-]?[0-9]+", part) is None for part in parts[1:]
                    ):
                        raise ValueError("decimal fields required")
                    values = [int(part, 10) for part in parts[1:]]
                except ValueError as error:
                    raise ValueError(
                        f"U7 paperdoll metadata: invalid decimal fields in {source}: {value!r}"
                    ) from error
                if section == "characters":
                    if values and values[0] == -255:
                        self.characters.pop(shape, None)
                        continue
                    names: tuple[str, ...] = (
                        "female",
                        "translucent",
                        "body_shape",
                        "body_frame",
                        "head_shape",
                        "head_frame",
                        "head_frame_helm",
                        "arms_shape",
                        "arms_frame",
                        "arms_frame_two_handed",
                        "arms_frame_staff",
                    )
                    if len(values) != len(names):
                        raise ValueError(
                            f"U7 paperdoll metadata: incomplete character row in {source}"
                        )
                    self.characters[shape] = {**row, **dict(zip(names, values))}
                else:
                    if len(values) < 4:
                        raise ValueError(
                            f"U7 paperdoll metadata: incomplete item key in {source}"
                        )
                    key = (shape, values[0], values[2])
                    if values[3] == -255:
                        self.items.pop(key, None)
                        continue
                    if not 7 <= len(values) <= 10:
                        raise ValueError(
                            f"U7 paperdoll metadata: incomplete item row in {source}"
                        )
                    padded = values + [-1] * (10 - len(values))
                    names = (
                        "world_frame",
                        "translucent",
                        "spot",
                        "type_raw",
                        "gender",
                        "shape",
                        "frame0",
                        "frame1",
                        "frame2",
                        "frame3",
                    )
                    ty = padded[3]
                    resolved_type = (
                        0
                        if padded[2] not in (0, 3)
                        else (1 if ty in (2, 7) else 2 if ty == 3 else 0)
                        if version == 1
                        else ty
                    )
                    self.items[key] = {
                        **row,
                        **dict(zip(names, padded)),
                        "type": resolved_type,
                    }

    def dump_csv(self) -> str:
        """Export distinct character/item keys plus all native slot/hot/blue coordinates."""
        rows = []
        for shape, value in self.characters.items():
            rows.append(
                {
                    "section": "characters",
                    "key": str(shape),
                    "fields": json.dumps(value),
                }
            )
        for key, value in self.items.items():
            rows.append(
                {
                    "section": "items",
                    "key": "/".join(map(str, key)),
                    "fields": json.dumps(value),
                }
            )
        for number, name in enumerate(PAPERDOLL_SLOT_NAMES):
            rows.append(
                {
                    "section": "slot_layout",
                    "key": name,
                    "fields": json.dumps(
                        {
                            "slot": number,
                            "position": PAPERDOLL_SLOT_POSITIONS[number],
                            "blue_position": PAPERDOLL_BLUE_POSITIONS[number],
                            "hot_position": PAPERDOLL_HOT_POSITIONS[number],
                            "source": "Exult Paperdoll_gump.cc",
                        }
                    ),
                }
            )
        for row in self.unresolved:
            rows.append({"section": "unresolved", "key": "", "fields": json.dumps(row)})
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["section", "key", "fields"])
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()


def read_u7_paperdoll_metadata(
    sources: U7GumpSources, *, skin_shapes: Mapping[str, int] | None = None
) -> U7PaperdollMetadata:
    """Inspect matching bundle/custom defaults then keyed patch rows, keeping unresolved skin references."""
    from titan.u7.avatar_metadata import read_u7_skin_imports

    avatar = read_u7_skin_imports(sources)
    bindings = {**avatar.skin_shapes, **(skin_shapes or {})}
    result = U7PaperdollMetadata(warnings=list(avatar.warnings))
    for layer in sources.layers:
        if layer.name == "PAPERDOL_INFO.TXT":
            result.apply_text(layer.data, layer.source, skin_shapes=bindings)
    return result
