"""Exult actor_flags rows, source selection and legacy monster-ability composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from titan.u7.flex import U7FlexArchive
from titan.u7.names import _text_file
from titan.u7.text import TextEncoding, U7TextMessages, decode_text_source

ACTOR_FLAG_NAMES = (
    "cold_immune",
    "doesnt_eat",
    "can_teleport",
    "can_summon",
    "can_be_invisible",
    "armageddon_safe",
    "quake_walk",
    "goblin",
)


@dataclass(frozen=True)
class U7ActorFlagRecord:
    """One complete replacement actor-flag byte and its text-row provenance."""

    shape: int
    flags: int
    source: str = ""


@dataclass(frozen=True)
class U7ActorFlagResolution:
    """Known effective bits; unavailable defaults leave other bits explicitly unknown."""

    shape: int
    flags: int
    known_mask: int
    text_source: str
    legacy_source: str = ""
    legacy_mask: int = 0

    def flag_value(self, bit: int) -> bool | None:
        """Return a known boolean, or None when this bit has no available source."""
        if not 0 <= bit < 8:
            raise ValueError("U7 actor flag bit must be between 0 and 7")
        return bool(self.flags & (1 << bit)) if self.known_mask & (1 << bit) else None

    @property
    def flag_names(self) -> str:
        """Names of known true effective flags; an empty list alone is not completeness."""
        return "|".join(
            name for bit, name in enumerate(ACTOR_FLAG_NAMES) if self.flags & (1 << bit)
        )

    def as_row(self) -> dict[str, object]:
        """Export effective values alongside known-bit and source metadata."""
        row: dict[str, object] = {
            "effective_actor_flags": self.flags if self.known_mask == 255 else "",
            "actor_flags_known_mask": self.known_mask,
            "effective_actor_flag_names": self.flag_names,
            "actor_flags_source": self.text_source,
            "legacy_actor_flags_source": self.legacy_source,
            "legacy_actor_flags_migrated": self.legacy_mask,
        }
        for bit, name in enumerate(ACTOR_FLAG_NAMES):
            value = self.flag_value(bit)
            row["effective_" + name] = "" if value is None else int(value)
        return row

    def summary(self) -> str:
        """Describe known flags while retaining any uncertainty about absent defaults."""
        suffix = (
            " (other flags unknown; defaults unavailable)"
            if self.known_mask != 255
            else ""
        )
        return (
            self.flag_names or ("none" if self.known_mask == 255 else "unknown")
        ) + suffix


@dataclass
class U7ActorFlags:
    """Layer shape-keyed complete text rows; an omitted patch section preserves defaults."""

    records: dict[int, U7ActorFlagRecord] = field(default_factory=dict)
    defaults_available: bool = False
    default_source: str = ""
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        source: str = "",
        defaults: bool = False,
    ) -> U7ActorFlags:
        """Parse decimal actor_flags fields; omitted trailing booleans become false."""
        parsed = U7TextMessages.from_bytes(text.encode("utf-8"))
        result = cls(
            defaults_available=defaults,
            default_source=source if defaults else "",
            sources=[source] if source else [],
            warnings=list(parsed.warnings),
        )
        for index, value in sorted(parsed.sections.get("actor_flags", {}).items()):
            parts = value.split("/")
            try:
                shape = int(parts[0].strip(), 10)
                flags = [int(part.strip() or "0", 10) for part in parts[1:9]]
            except ValueError as error:
                raise ValueError(
                    f"U7 actor_flags invalid decimal row {index} in {source}: {value!r}"
                ) from error
            if not 0 <= shape <= 0xFFFF:
                raise ValueError(
                    f"U7 actor_flags shape outside u16 in {source}: {shape}"
                )
            mask = sum(1 << bit for bit, enabled in enumerate(flags) if enabled)
            result.records[shape] = U7ActorFlagRecord(
                shape, mask, f"{source}#actor_flags:{index}"
            )
            if len(parts) > 9:
                result.warnings.append(
                    f"U7 actor_flags row {index} in {source} has extra fields; only eight flags are read."
                )
        return result

    def overlay(self, patch: U7ActorFlags) -> U7ActorFlags:
        """Replace present rows, including explicit zero bytes, without mutating either input."""
        return U7ActorFlags(
            {**self.records, **patch.records},
            self.defaults_available or patch.defaults_available,
            patch.default_source if patch.defaults_available else self.default_source,
            list(dict.fromkeys([*self.sources, *patch.sources])),
            [*self.warnings, *patch.warnings],
        )

    def resolve(
        self,
        shape: int,
        *,
        legacy_flags: int = 0,
        legacy_source: str = "",
    ) -> U7ActorFlagResolution:
        """Apply the post-text legacy 0F-bit migration without mutating stored monster data."""
        record = self.records.get(shape)
        flags = record.flags if record is not None else 0
        known = 255 if record is not None or self.defaults_available else 0
        migrated = (legacy_flags & 7) << 2
        return U7ActorFlagResolution(
            shape,
            flags | migrated,
            known | migrated,
            record.source if record is not None else self.default_source,
            legacy_source if migrated else "",
            migrated,
        )


def load_u7_actor_flags(
    *,
    game: str = "bg",
    exult_flx_path: str | Path | None = None,
    default_shape_info_path: str | Path | None = None,
    patch_dirs: Sequence[str | Path] = (),
    patch_files: Sequence[str | Path] = (),
    discover_defaults: bool = True,
    encoding: TextEncoding = "auto",
) -> U7ActorFlags:
    """Load matching bundle defaults then low-to-high patches; no source means unknown defaults.

    default_shape_info_path explicitly selects an inspection baseline instead of
    a bundle. BG/SI STATIC text is never silently substituted for engine defaults.
    Known legacy bits can still establish true abilities when defaults are absent.
    """
    game = game.lower()
    if game not in ("bg", "si"):
        raise ValueError(f"U7 actor_flags game must be bg or si: {game}")
    if default_shape_info_path is not None and exult_flx_path is not None:
        raise ValueError(
            "U7 actor_flags select one default shape_info file or Exult bundle"
        )
    result = U7ActorFlags()
    if default_shape_info_path is not None:
        path = Path(default_shape_info_path).expanduser()
        text, _ = decode_text_source(path.read_bytes(), encoding)
        result = U7ActorFlags.from_text(
            text,
            source=str(path),
            defaults=True,
        )
    else:
        bundle = str(exult_flx_path) if exult_flx_path is not None else None
        if bundle is None and discover_defaults:
            from titan.u7.cli import _resolve_u7_exult_flx

            bundle = _resolve_u7_exult_flx(game)
        if bundle is not None:
            path = Path(bundle).expanduser()
            archive = U7FlexArchive.from_file(str(path), strict=True)
            index = 7 if game == "bg" else 4
            if index >= len(archive.records) or not archive.records[index]:
                raise ValueError(
                    f"U7 actor_flags missing shape_info resource {index} in {path}"
                )
            result = U7ActorFlags.from_text(
                archive.records[index].decode("latin-1"),
                source=f"{path}#record={index}",
                defaults=True,
            )
    paths = [
        candidate
        for directory in patch_dirs
        if (candidate := _text_file(Path(directory), "shape_info.txt")) is not None
    ]
    paths.extend(Path(path).expanduser() for path in patch_files)
    for path in dict.fromkeys(path.resolve() for path in paths):
        text, _ = decode_text_source(path.read_bytes(), encoding)
        result = result.overlay(U7ActorFlags.from_text(text, source=str(path)))
    return result
