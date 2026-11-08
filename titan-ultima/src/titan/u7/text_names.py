"""Select Exult text banks before layering frame-name rules for all U7 inspection features."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Sequence

from titan.u7.flex import U7FlexArchive
from titan.u7.names import U7FrameNames, U7ShapeNames, _text_file
from titan.u7.text import (
    SIVariant,
    TextEncoding,
    U7TextBanks,
    U7TextMessages,
    decode_text_source,
)


@dataclass
class U7TextNames:
    """Selected banks, retained naming rules, source provenance and loading diagnostics."""

    names: U7ShapeNames | None = None
    frames: U7FrameNames | None = None
    banks: U7TextBanks | None = None
    sources: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _engine_messages(
    bundle: Path | None,
    patches: Sequence[Path],
    language: str,
    encoding: TextEncoding,
) -> tuple[dict[int, str], list[str]]:
    resources: list[bytes] = []
    language_indices = {"en": None, "de": 21, "es": 22, "fr": 23}
    if language not in language_indices:
        raise ValueError(f"Unsupported Exult text language: {language}")
    if bundle is not None:
        common = _text_file(bundle.parent, "exult.flx")
        if common:
            archive = U7FlexArchive.from_file(str(common), strict=True)
            indices = [20]
            localized = language_indices[language]
            if localized is not None:
                indices.append(localized)
            resources.extend(
                archive.get_record(i) for i in indices if i < len(archive.records)
            )
    for patch in patches:
        for name in (
            "exultmsg.txt",
            f"exultmsg_{language}.txt" if language != "en" else "",
        ):
            path = _text_file(patch, name) if name else None
            if path:
                resources.append(path.read_bytes())
    merged: dict[int, str] = {}
    warnings = []
    for data in resources:
        parsed = U7TextMessages.from_bytes(data, encoding=encoding)
        warnings.extend(parsed.warnings)
        merged.update(
            {
                index - 0x400: value
                for index, value in parsed.sections.get("", {}).items()
                if index >= 0x400
            }
        )
    return merged, warnings


def load_u7_text_names(
    static_dir: str | Path | None,
    *,
    patch_dirs: Sequence[str | Path] = (),
    text_flx_path: str | Path | None = None,
    exult_flx_path: str | Path | None = None,
    game: str = "bg",
    si_variant: SIVariant = "unmapped",
    encoding: TextEncoding = "auto",
    language: Literal["en", "de", "es", "fr"] = "en",
) -> U7TextNames:
    """Select textmsg over Flex, replace shape/misc banks, then bind default/patch rules.

    patch_dirs are ordered low to high priority. An explicit text_flx_path
    intentionally selects that bank over automatic textmsg discovery. SI
    remapping is opt-in through si_variant; 'unmapped' never guesses expansion.
    Unicode authoring text is retained for inspection, without simulating fonts.
    """
    if game.lower() not in ("bg", "si"):
        raise ValueError(f"U7 text requires BG or SI: {game}")
    game = game.lower()
    root = Path(static_dir) if static_dir is not None else None
    patches = list(dict.fromkeys(Path(path) for path in patch_dirs))
    bundle = Path(exult_flx_path) if exult_flx_path else None
    if bundle is not None and not bundle.is_file():
        raise ValueError(f"Exult naming resource not found: {bundle}")
    result = U7TextNames()
    search = [*reversed(patches), *([root] if root is not None else [])]
    selected_textmsg = next(
        (p for d in search if (p := _text_file(d, "textmsg.txt"))), None
    )
    selected_flex = (
        Path(text_flx_path)
        if text_flx_path is not None
        else next((p for d in search if (p := _text_file(d, "text.flx"))), None)
    )
    if text_flx_path is not None:
        selected_textmsg = None
        if selected_flex is None or not selected_flex.is_file():
            raise ValueError(f"TEXT.FLX not found: {text_flx_path}")
    if selected_textmsg is None and selected_flex is None:
        return result
    engine, warnings = _engine_messages(bundle, patches, language, encoding)
    result.warnings.extend(warnings)
    default_messages = [""] * (max(engine, default=-1) + 1)
    for index, value in engine.items():
        default_messages[index] = value
    if selected_textmsg is not None:
        parsed = U7TextMessages.from_file(selected_textmsg, encoding=encoding)
        banks = U7TextBanks.from_textmsg(
            parsed,
            source=str(selected_textmsg),
            game=game,
            base_messages=default_messages,
        )
    else:
        if selected_flex is None:
            return result
        banks = U7TextBanks.from_file(selected_flex, game=game, si_variant=si_variant)
        # Original message-bank slots win over conflicting exultmsg resources.
        messages = list(banks.messages)
        original_count = len(messages)
        for index, value in engine.items():
            if index < original_count:
                continue
            if index >= len(messages):
                messages.extend([""] * (index + 1 - len(messages)))
            messages[index] = value
        banks.messages = tuple(messages)
    result.banks = banks
    result.names = U7ShapeNames(banks.shapes, banks=banks, warnings=banks.warnings)
    result.sources["text"] = banks.source
    result.warnings.extend(result.names.warnings)
    frames = U7FrameNames(misc_names=banks.misc, game=game, si_variant=si_variant)
    if bundle is not None:
        archive = U7FlexArchive.from_file(str(bundle), strict=True)
        index = 7 if game == "bg" else 4
        if index >= len(archive.records) or not archive.records[index]:
            raise ValueError(f"Exult naming resource {index} is absent: {bundle}")
        text = archive.records[index].decode("latin-1")
        frames = U7FrameNames.from_text(
            text, banks.misc, game=game, source=str(bundle), si_variant=si_variant
        )
        result.sources["frame_defaults"] = f"{bundle}#{index}"
    elif root is not None:
        source = _text_file(root, "shape_info.txt")
        if source:
            text, _ = decode_text_source(source.read_bytes(), encoding)
            frames = U7FrameNames.from_text(
                text, banks.misc, game=game, source=str(source), si_variant=si_variant
            )
            result.sources["frame_defaults"] = str(source)
    for index, directory in enumerate(patches):
        source = _text_file(directory, "shape_info.txt")
        if source:
            text, _ = decode_text_source(source.read_bytes(), encoding)
            frames = frames.merged_with(
                U7FrameNames.from_text(
                    text,
                    banks.misc,
                    game=game,
                    source=str(source),
                    si_variant=si_variant,
                )
            )
            result.sources[f"frame_patch_{index}"] = str(source)
    result.frames = frames if frames.rules else None
    result.warnings.extend(frames.warnings)
    result.warnings = list(dict.fromkeys(result.warnings))
    return result
