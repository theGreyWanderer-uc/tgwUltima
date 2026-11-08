"""Shape context for Exult's IREG class dispatch, including supplemental flags."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from titan.u7.gump_metadata import U7GumpSources, load_u7_gump_sources
from titan.u7.text import U7TextMessages
from titan.u7.typeflag import U7TypeFlags


@dataclass
class U7IregContext:
    """A TFA class is separate from the body/jawbone flags in Exult text data."""

    tfa: U7TypeFlags | None = None
    game: str = "bg"
    bodies: dict[int, bool] = field(default_factory=dict)
    jawbones: dict[int, bool] = field(default_factory=dict)
    bodies_complete: bool = False
    jawbones_complete: bool = False
    sources: dict[tuple[str, int], str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_sources(
        cls, sources: U7GumpSources, tfa: U7TypeFlags | None = None, *, game: str = "bg"
    ) -> U7IregContext:
        if game.lower() not in ("bg", "si"):
            raise ValueError("IREG game must be bg or si")
        result = cls(tfa, game.lower(), warnings=list(sources.warnings))
        for layer in sources.layers:
            if layer.name not in ("BODIES.TXT", "SHAPE_INFO.TXT"):
                continue
            parsed = U7TextMessages.from_bytes(layer.data)
            result.warnings.extend(parsed.warnings)
            version = int(next(iter(parsed.sections.get("version", {}).values()), "1"))
            body = layer.name == "BODIES.TXT"
            section = "bodyshapes" if body else "is_jawbone"
            target = result.bodies if body else result.jawbones
            if not layer.patch:
                if body:
                    result.bodies_complete = True
                else:
                    result.jawbones_complete = True
            for index, value in sorted(parsed.sections.get(section, {}).items()):
                fields = value.split("#", 1)[0].strip().split("/")
                if body and version == 1:
                    shape = index
                else:
                    shape = int(fields.pop(0), 10)
                target[shape] = (
                    int(fields[0], 10) != 0 if fields and fields[0] else True
                )
                result.sources[section, shape] = f"{layer.source}#{section}:{index}"
        return result

    @classmethod
    def from_dir(
        cls,
        static_dir: str | Path | None,
        *,
        patch_dir: str | Path | None = None,
        tfa: U7TypeFlags | None = None,
        game: str = "bg",
        custom_game: bool = False,
        exult_flx: str | Path | None = None,
    ) -> U7IregContext:
        return cls.from_sources(
            load_u7_gump_sources(
                static_dir,
                patch_dir=patch_dir,
                game=game,
                custom_game=custom_game,
                exult_flx=exult_flx,
            ),
            tfa,
            game=game,
        )
