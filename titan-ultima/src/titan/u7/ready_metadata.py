"""Exult READY load order, alternate spots and actor placement search order."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from titan.u7.save import U7ReadyRecord

from titan.u7.gameplay_metadata import U7GameplayFormat
from titan.u7.gump_metadata import U7GumpSources, load_u7_gump_sources
from titan.u7.paperdoll_metadata import U7PaperdollMetadata
from titan.u7.shape_archive import find_archive
from titan.u7.text import U7TextMessages


@dataclass(frozen=True)
class U7ReadyResolution:
    """Metadata preferences and ordered attempts, before actor fit/occupancy checks."""

    shape: int
    preferred: int
    alternate1: int
    alternate2: int
    spell: bool
    defaulted: bool
    source: str
    alternatives_source: str
    context_complete: bool

    @property
    def search_order(self) -> tuple[int, ...]:
        """Actor::find_best_spot order, retaining duplicate attempts."""
        return (self.preferred, self.alternate1, self.alternate2, 2, 1, 12, 13, 3, 8)

    def as_row(self) -> dict[str, object]:
        from titan.u7.save import _READY_SLOT_NAMES

        return {
            "effective_slot": self.preferred,
            "effective_slot_name": _READY_SLOT_NAMES.get(self.preferred, "unknown"),
            "alternate_slots": [self.alternate1, self.alternate2],
            "alternate_slot_names": [
                _READY_SLOT_NAMES.get(s, "unknown")
                for s in (self.alternate1, self.alternate2)
            ],
            "search_order": list(self.search_order),
            "spell_flag": self.spell,
            "defaulted": self.defaulted,
            "source": self.source,
            "alternatives_source": self.alternatives_source,
            "context_complete": self.context_complete,
            "fit_checks_applied": False,
            "model": "Exult",
        }


@dataclass
class U7ReadyMetadata:
    """Keep stored READY preferences separate from Exult's effective resolution."""

    game: str = "bg"
    preferred: dict[int, int] = field(default_factory=dict)
    alternatives: dict[int, tuple[int, int]] = field(default_factory=dict)
    spells: dict[int, bool] = field(default_factory=dict)
    sources: dict[int, str] = field(default_factory=dict)
    alternative_sources: dict[int, str] = field(default_factory=dict)
    paperdoll: U7PaperdollMetadata = field(default_factory=U7PaperdollMetadata)
    text_complete: bool = False
    paperdoll_complete: bool = False
    warnings: list[str] = field(default_factory=list)
    records: list[U7ReadyRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.game = self.game.lower()
        if self.game not in ("bg", "si"):
            raise ValueError("READY game must be bg or si")

    def apply_ready(
        self, data: bytes, source: str = "", *, data_format: U7GameplayFormat = "exult"
    ) -> None:
        """Apply every binary row in order; unassigned alternatives inherit."""
        from titan.u7.save import U7ReadyTypes

        ready = U7ReadyTypes.from_bytes(data, self.game, data_format=data_format)
        if (
            ready.table is None
            or ready.declared_count is None
            or ready.table.parsed_count < ready.declared_count
        ):
            raise ValueError(f"Incomplete READY table: {source}")
        self.warnings.extend(ready.warnings)
        self.records.extend(ready.records)
        for index, row in enumerate(ready.records):
            shape, slot = row.shape, row.slot
            origin = f"{source}#record={index}"
            self.preferred[shape] = slot
            self.spells[shape] = row.spell_flag
            self.sources[shape] = origin
            alt1, alt2 = self.alternatives.get(shape, (255, 255))
            if slot == 4:
                alt1 = 7
            elif slot == 3:
                alt1, alt2 = 8, 2
            elif slot == 18:
                alt1 = 12
            else:
                continue
            self.alternatives[shape] = alt1, alt2
            self.alternative_sources[shape] = origin

    def apply_sources(self, sources: U7GumpSources) -> None:
        """Text overrides are applied after both binary tables."""
        self.warnings.extend(sources.warnings)
        for layer in sources.layers:
            if layer.name == "SHAPE_INFO.TXT":
                if not layer.patch:
                    self.text_complete = True
                parsed = U7TextMessages.from_bytes(layer.data)
                self.warnings.extend(parsed.warnings)
                for index, value in sorted(parsed.sections.get("altready", {}).items()):
                    parts = value.split("#", 1)[0].strip().split("/")
                    shape = int(parts[0], 10)
                    alt = [int(s, 10) & 255 for s in parts[1:3]]
                    alt += [255] * (2 - len(alt))
                    self.alternatives[shape] = alt[0], alt[1]
                    self.alternative_sources[shape] = f"{layer.source}#altready:{index}"
            elif layer.name == "PAPERDOL_INFO.TXT":
                self.paperdoll.apply_text(layer.data, layer.source)
                if not layer.patch:
                    self.paperdoll_complete = True
        self.warnings.extend(self.paperdoll.warnings)

    @classmethod
    def from_dir(
        cls,
        static_dir: str | Path | None,
        *,
        patch_dir: str | Path | None = None,
        game: str = "bg",
        sources: U7GumpSources | None = None,
        data_format: U7GameplayFormat = "exult",
        custom_game: bool = False,
        exult_flx: str | Path | None = None,
    ) -> U7ReadyMetadata:
        result = cls(game)
        seen: set[Path] = set()
        for directory in (static_dir, patch_dir):
            path = find_archive(Path(directory), "READY.DAT") if directory else None
            if path is not None and path.resolve() not in seen:
                seen.add(path.resolve())
                result.apply_ready(
                    path.read_bytes(), str(path), data_format=data_format
                )
        result.apply_sources(
            sources
            if sources is not None
            else load_u7_gump_sources(
                static_dir,
                patch_dir=patch_dir,
                game=game,
                custom_game=custom_game,
                exult_flx=exult_flx,
            )
        )
        return result

    def resolve(self, shape: int, frame: int | None = None) -> U7ReadyResolution:
        """Resolve preferences; missing paperdoll/frame leaves handedness explicit."""
        stored = self.preferred.get(shape, 255)
        preferred = (1 if self.game == "bg" else 8) if stored == 255 else stored
        alt1, alt2 = self.alternatives.get(shape, (255, 255))
        alt1 = 3 if alt1 == 255 else alt1
        alt2 = 3 if alt2 == 255 else alt2
        complete = self.text_complete
        if preferred == 3:
            complete &= frame is not None and self.paperdoll_complete
            if frame is not None and self.paperdoll_complete:

                def allowed(spot: int) -> bool:
                    return (shape, frame, spot) in self.paperdoll.items or (
                        shape,
                        -1,
                        spot,
                    ) in self.paperdoll.items

                if allowed(8) and not allowed(3):
                    preferred = 8
                else:
                    alt1 = 8
        return U7ReadyResolution(
            shape,
            preferred,
            alt1,
            alt2,
            self.spells.get(shape, False),
            stored == 255,
            self.sources.get(shape, "Exult initialization"),
            self.alternative_sources.get(shape, "Exult initialization"),
            complete,
        )
