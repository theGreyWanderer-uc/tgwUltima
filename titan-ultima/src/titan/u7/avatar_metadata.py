"""Resolve Exult imported skin variables and Avatar appearance metadata with provenance."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from titan.u7.gump_metadata import U7GumpSources
from titan.u7.text import U7TextMessages


def _number(value: str) -> int:
    """Shapeinfo lookup accepts decimal integers and positive 0x hexadecimal integers."""
    value = value.strip()
    if re.fullmatch(r"(?:[+-]?[0-9]+|0[xX][0-9a-fA-F]+)", value) is None:
        raise ValueError(f"U7 Avatar metadata: invalid integer {value!r}")
    return int(value, 16 if value.lower().startswith("0x") else 10)


@dataclass(frozen=True)
class U7AvatarSkin:
    skin: int
    female: bool
    shape: int
    naked_shape: int
    face_shape: int
    face_frame: int
    alternate_face_shape: int
    alternate_face_frame: int
    copy_info: bool
    source: str


@dataclass
class U7AvatarMetadata:
    """Keep shape imports separate from skin IDs and actual runtime import availability."""

    skin_shapes: dict[str, int] = field(default_factory=dict)
    skin_shape_sources: dict[str, str] = field(default_factory=dict)
    imports: list[tuple[int, int]] = field(default_factory=list)
    skins: dict[tuple[int, bool], U7AvatarSkin] = field(default_factory=dict)
    base_shapes: dict[bool, int] = field(default_factory=dict)
    default_skin: int | None = None
    default_female: bool | None = None
    raw_sources: dict[str, bytes] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    _next_shape: int = 2048  # Exult c_max_shapes; shared across default and patch.

    def apply_imports(self, data: bytes, source: str = "") -> None:
        """Skip repeated source shapes before allocating automatic IDs, as Shape_imports_parser does."""
        parsed = U7TextMessages.from_bytes(data)
        self.raw_sources[source] = data
        self.warnings.extend(parsed.warnings)
        for index, row in sorted(
            parsed.sections.get("multiracial_imports", {}).items()
        ):
            parts = row.split("#", 1)[0].strip().split("/")
            if len(parts) != 2:
                raise ValueError(
                    f"U7 Avatar metadata: malformed import in {source}: {row!r}"
                )
            original = _number(parts[0].strip())
            if any(imported == original for _, imported in self.imports):
                continue
            target = parts[1].strip()
            if target.startswith("%"):
                shape = self._next_shape
                self._next_shape += 1
                self.skin_shapes[target] = shape
                self.skin_shape_sources[target] = (
                    f"{source}#multiracial_imports:{index}"
                )
            else:
                shape = _number(target)
            self.imports.append((shape, original))

    def apply_avatars(
        self, data: bytes, source: str = "", *, patch: bool = False
    ) -> None:
        """Apply skin/sex keys after all imports, including imports introduced by PATCH."""
        parsed = U7TextMessages.from_bytes(data)
        self.raw_sources[source] = data
        self.warnings.extend(parsed.warnings)
        version = _number(next(iter(parsed.sections.get("version", {}).values()), "1"))
        for section in ("defaultshape", "baseracesex", "multiracial_table"):
            for index, row in sorted(parsed.sections.get(section, {}).items()):
                parts = [
                    part.strip() for part in row.split("#", 1)[0].strip().split("/")
                ]
                required = {
                    "defaultshape": 4,
                    "baseracesex": 2,
                    "multiracial_table": 8,
                }[section]
                if len(parts) < required:
                    raise ValueError(
                        f"U7 Avatar metadata: incomplete {section} in {source}: {row!r}"
                    )
                row_source = f"{source}#{section}:{index}"
                if section == "multiracial_table":
                    unresolved = [
                        value
                        for value in parts[2:4]
                        if value.startswith("%") and value not in self.skin_shapes
                    ]
                    if unresolved:
                        self.warnings.append(
                            f"U7 Avatar metadata: unresolved skin references {unresolved} in {row_source}"
                        )
                        continue
                    values = [
                        _number(part)
                        if position not in (2, 3) or not part.startswith("%")
                        else self.skin_shapes[part]
                        for position, part in enumerate(parts[:8])
                    ]
                    if values[2] < 0 or values[3] < 0:
                        continue  # Engine rejects unresolved/negative shape references.
                    key = values[0], bool(values[1])
                    if key in self.skins and not patch:
                        continue  # GetSkinInfo returns the first matching default row.
                    self.skins[key] = U7AvatarSkin(
                        values[0],
                        bool(values[1]),
                        values[2],
                        values[3],
                        values[4],
                        values[5],
                        values[6],
                        values[7],
                        version != 2 or len(parts) < 9 or bool(_number(parts[8])),
                        row_source,
                    )
                elif section == "defaultshape":
                    values = [_number(part) for part in parts[:4]]
                    self.base_shapes[bool(values[0])] = values[1]
                else:
                    self.default_skin = _number(parts[0])
                    self.default_female = bool(_number(parts[1]))

    def resolve_shape(
        self,
        *,
        skin: int | None,
        female: bool | None,
        naked: bool = False,
        have_si_shapes: bool | None = None,
    ) -> dict[str, object]:
        """Resolve both availability branches; request runtime context only when results differ."""
        missing = []
        if female is None:
            missing.append("avatar_sex")
        if skin is None:
            missing.append("avatar_skin")
        if female is None or skin is None:
            return {"resolved_shape": None, "required_context": missing}
        requested = self.skins.get((skin, female))
        fallback = (
            self.skins.get((self.default_skin, female))
            if self.default_skin is not None
            else None
        )
        imported = {shape for shape, _ in self.imports}

        def choose(available: bool) -> U7AvatarSkin | None:
            if requested is not None and (
                available or not {requested.shape, requested.naked_shape} & imported
            ):
                return requested
            if fallback is not None and (
                available or not {fallback.shape, fallback.naked_shape} & imported
            ):
                return fallback
            return None

        candidates = [choose(available) for available in (False, True)]
        shapes = [
            None if row is None else row.naked_shape if naked else row.shape
            for row in candidates
        ]
        selected = int(have_si_shapes) if have_si_shapes is not None else 0
        if have_si_shapes is None and shapes[0] != shapes[1]:
            missing.append("have_si_shapes")
        elif shapes[selected] is None:
            missing.append("avatar_skin_metadata")
        row = candidates[selected]
        return {
            "resolved_shape": None if missing else shapes[selected],
            "required_context": missing,
            "without_si_shapes": shapes[0],
            "with_si_shapes": shapes[1],
            "skin": skin,
            "female": female,
            "naked": naked,
            "source": row.source if row is not None and not missing else None,
        }


def read_u7_skin_imports(sources: U7GumpSources) -> U7AvatarMetadata:
    """Resolve skin IDs without requiring unrelated Avatar table rows to be readable."""
    result = U7AvatarMetadata(warnings=list(sources.warnings))
    for layer in sources.layers:
        if layer.name == "SHAPE_FILES.TXT":
            result.apply_imports(layer.data, layer.source)
    return result


def read_u7_avatar_metadata(sources: U7GumpSources) -> U7AvatarMetadata:
    """Resolve all shape-file layers before any Avatar skin references."""
    result = read_u7_skin_imports(sources)
    for layer in sources.layers:
        if layer.name == "AVATAR_DATA.TXT":
            result.apply_avatars(layer.data, layer.source, patch=layer.patch)
    return result
