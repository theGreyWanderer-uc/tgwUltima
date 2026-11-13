"""U7 text banks and bounded Exult message-file parsing, with explicit SI variants."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Sequence

from titan.u7.flex import U7FlexArchive

TextEncoding = Literal["auto", "utf-8", "latin-1"]
SIVariant = Literal["unmapped", "original", "silver-seed", "beta"]
MAX_TEXT_INDEX = 0xFFFF


def decode_text_source(data: bytes, encoding: TextEncoding = "auto") -> tuple[str, str]:
    """Decode authoring text as UTF-8 when valid, with explicit legacy Latin-1 support."""
    if encoding not in ("auto", "utf-8", "latin-1"):
        raise ValueError(f"U7 text encoding is unsupported: {encoding}")
    if encoding != "latin-1":
        try:
            return data.decode("utf-8-sig"), "utf-8"
        except UnicodeDecodeError:
            if encoding == "utf-8":
                raise
    return data.decode("latin-1"), "latin-1"


@dataclass
class U7TextMessages:
    """Sparse section entries retain explicit empty values and significant whitespace."""

    sections: dict[str, dict[int, str]] = field(default_factory=dict)
    encoding: str = "utf-8"
    raw: bytes = b""
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        encoding: TextEncoding = "auto",
        max_index: int = MAX_TEXT_INDEX,
    ) -> U7TextMessages:
        if len(data) > 32 * 1024 * 1024:
            raise ValueError("U7 text file exceeds the 32 MiB inspection limit")
        text, selected_encoding = decode_text_source(data, encoding)
        result = cls({"": {}}, selected_encoding, data)
        section = ""
        auto_index = 0
        for number, raw_line in enumerate(re.split(r"[\r\n]+", text), 1):
            line = raw_line.lstrip(" \t\b")
            if not line or line.startswith("#"):
                continue
            if line.startswith("%%section"):
                name = line[len("%%section") :].lstrip(" \t\b")
                if section or not name or name in result.sections:
                    raise ValueError(
                        f"U7 text invalid or duplicate section at line {number}"
                    )
                section = name
                result.sections[section] = {}
                continue
            if line.startswith("%%endsection"):
                if not section:
                    raise ValueError(f"U7 text unmatched endsection at line {number}")
                section = ""
                continue
            key, colon, value = line.partition(":")
            if not colon:
                result.warnings.append(f"U7 text line {number} has no colon; ignored.")
                continue
            if not key:
                index = auto_index
                auto_index += 1
            else:
                base = (
                    16
                    if key.lower().startswith("0x")
                    else 8
                    if key.startswith("0")
                    else 10
                )
                pattern = (
                    r"0[xX][0-9a-fA-F]+"
                    if base == 16
                    else r"[0-7]+"
                    if base == 8
                    else r"[0-9]+"
                )
                if not re.fullmatch(pattern, key):
                    raise ValueError(
                        f"U7 text invalid unsigned index at line {number}: {key!r}"
                    )
                index = int(key, base)
            if not 0 <= index <= max_index:
                raise ValueError(
                    f"U7 text index {index} exceeds inspection limit {max_index}"
                )
            result.sections[section][index] = value
        if section:
            raise ValueError(f"U7 text unclosed section: {section}")
        return result

    @classmethod
    def from_file(
        cls, path: str | Path, *, encoding: TextEncoding = "auto"
    ) -> U7TextMessages:
        return cls.from_bytes(Path(path).read_bytes(), encoding=encoding)

    def strings(self, section: str, base: Sequence[str] = ()) -> list[str]:
        """Overlay present slots on base; holes and explicit empty strings remain distinct."""
        strings = list(base)
        for index, value in self.sections.get(section, {}).items():
            if index >= len(strings):
                strings.extend([""] * (index + 1 - len(strings)))
            strings[index] = value
        return strings


def remap_si_misc_index(index: int, variant: SIVariant) -> int:
    """Map original/beta SI misc IDs into the Silver Seed naming namespace explicitly."""
    if variant not in ("unmapped", "original", "silver-seed", "beta"):
        raise ValueError(f"Unknown SI text variant: {variant}")
    if variant in ("unmapped", "silver-seed"):
        return index
    shifts = (
        (
            (0x146, 17),
            (0x135, 16),
            (0xF6, 15),
            (0xEA, 14),
            (0xE5, 13),
            (0xB1, 11),
            (0xAE, 10),
            (0xA2, 9),
            (0x94, 8),
            (0x8B, 7),
            (0x7F, 2),
        )
        if variant == "beta"
        else ((0xFA, 11), (0xB2, 10), (0xAF, 9), (0x94, 8), (0x8B, 7), (0x7F, 2))
    )
    return index + next((delta for threshold, delta in shifts if index >= threshold), 0)


@dataclass
class U7TextBanks:
    """Separate item, message and misc namespaces while retaining every raw Flex record."""

    shapes: tuple[str, ...] = ()
    messages: tuple[str, ...] = ()
    misc: tuple[str, ...] = ()
    raw_records: tuple[bytes, ...] = ()
    source: str = ""
    game: str = "bg"
    si_variant: SIVariant = "unmapped"
    warnings: list[str] = field(default_factory=list)
    authoring: U7TextMessages | None = None

    @classmethod
    def from_file(
        cls, path: str | Path, *, game: str = "bg", si_variant: SIVariant = "unmapped"
    ) -> U7TextBanks:
        return cls.from_records(
            U7FlexArchive.from_file(str(path), strict=True).records,
            game=game,
            si_variant=si_variant,
            source=str(path),
        )

    @classmethod
    def from_records(
        cls,
        records: Sequence[bytes],
        *,
        game: str = "bg",
        si_variant: SIVariant = "unmapped",
        source: str = "",
    ) -> U7TextBanks:
        game = game.lower()
        if game not in ("bg", "si"):
            raise ValueError(f"U7 text requires BG or SI: {game}")
        remap_si_misc_index(0, si_variant)
        if game == "bg" and si_variant != "unmapped":
            raise ValueError("SI text variants cannot be applied to BG")
        count = len(records)
        cap = 0x600 if game == "bg" else 0x686
        shapes = [""] * min(count, 0x400)
        messages = [""] * min(max(0, count - 0x400), 0x100)
        misc = [""] * min(max(0, count - 0x500), cap - 0x500)
        remap = game == "si" and si_variant in ("original", "beta")
        cutoff = max(0, min(count, cap) - (17 if remap else 0))
        warnings = []
        for index, record in enumerate(records[:cutoff]):
            if record and b"\x00" not in record:
                warnings.append(f"TEXT.FLX record {index} has no NUL terminator.")
            value = record.split(b"\x00", 1)[0].decode("latin-1")
            if index < 0x400:
                shapes[index] = value
            elif index < 0x500:
                logical = index - 0x400
                if game == "si" and si_variant == "beta" and logical >= 0xD2:
                    logical += 1
                if logical >= len(messages):
                    messages.extend([""] * (logical + 1 - len(messages)))
                messages[logical] = value
            else:
                logical = (
                    remap_si_misc_index(index - 0x500, si_variant)
                    if remap
                    else index - 0x500
                )
                if logical >= len(misc):
                    misc.extend([""] * (logical + 1 - len(misc)))
                misc[logical] = value
        return cls(
            tuple(shapes),
            tuple(messages),
            tuple(misc),
            tuple(records),
            source,
            game,
            si_variant,
            warnings,
        )

    @classmethod
    def from_textmsg(
        cls,
        messages: U7TextMessages,
        *,
        source: str = "",
        game: str = "bg",
        base_messages: Sequence[str] = (),
    ) -> U7TextBanks:
        """Selected textmsg replaces shapes/misc; only msgs merges with earlier messages."""
        return cls(
            tuple(messages.strings("shapes")),
            tuple(messages.strings("msgs", base_messages)),
            tuple(messages.strings("miscnames")),
            source=source,
            game=game,
            warnings=list(messages.warnings),
            authoring=messages,
        )

    @property
    def extra_records(self) -> tuple[bytes, ...]:
        """Return raw records beyond this engine's misc-bank cap without discarding them."""
        return self.raw_records[0x600 if self.game == "bg" else 0x686 :]
