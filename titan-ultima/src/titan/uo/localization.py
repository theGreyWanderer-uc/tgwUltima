"""Ultima Online localization and name metadata support."""

from __future__ import annotations

__all__ = [
    "UOCliloc",
    "UOClilocEntry",
    "UOIndexedText",
    "UOSkillEntry",
    "UOSkillGroup",
    "UOSkillGroups",
    "UOSkills",
    "UOSpeech",
    "UOSpeechEntry",
    "find_language_files",
    "find_localized_text_files",
    "parse_iff_text_file",
]

from dataclasses import dataclass
from pathlib import Path
import struct

from titan.uo.uop import _bwt_decompress


@dataclass(frozen=True)
class UOClilocEntry:
    """One cliloc string entry."""

    number: int
    flag: int
    text: str


class UOCliloc:
    """Parsed Cliloc.<lang> string table."""

    def __init__(self, *, language: str, entries: dict[int, UOClilocEntry]) -> None:
        self.language = language
        self.entries = entries

    @classmethod
    def from_file(cls, path: str | Path) -> UOCliloc:
        source = Path(path)
        data = source.read_bytes()
        if len(data) > 3 and data[3] == 0x8E:
            data = _bwt_decompress(data)
        pos = 6
        entries: dict[int, UOClilocEntry] = {}
        while pos + 7 <= len(data):
            number, flag, byte_length = struct.unpack_from("<iBh", data, pos)
            pos += 7
            if byte_length < 0 or pos + byte_length > len(data):
                break
            raw_text = data[pos : pos + byte_length]
            pos += byte_length
            entries[number] = UOClilocEntry(
                number=number,
                flag=flag,
                text=raw_text.decode("utf-8", errors="replace"),
            )
        return cls(language=source.suffix.lstrip(".").lower(), entries=entries)


@dataclass(frozen=True)
class UOSpeechEntry:
    """One speech keyword entry."""

    keyword_id: int
    text: str


class UOSpeech:
    """Parsed speech.mul keyword table."""

    def __init__(self, entries: list[UOSpeechEntry]) -> None:
        self.entries = entries

    @classmethod
    def from_file(cls, path: str | Path) -> UOSpeech:
        data = Path(path).read_bytes()
        pos = 0
        entries: list[UOSpeechEntry] = []
        while pos + 4 <= len(data):
            keyword_id, byte_length = struct.unpack_from(">HH", data, pos)
            pos += 4
            if pos + byte_length > len(data):
                break
            raw_text = data[pos : pos + byte_length]
            pos += byte_length
            entries.append(
                UOSpeechEntry(
                    keyword_id=keyword_id,
                    text=raw_text.decode("utf-8", errors="replace"),
                )
            )
        return cls(entries)


@dataclass(frozen=True)
class UOSkillEntry:
    """One skills.mul indexed skill name."""

    skill_id: int
    action: int
    name: str


class UOSkills:
    """Parsed skills.idx/skills.mul skill table."""

    def __init__(self, entries: list[UOSkillEntry]) -> None:
        self.entries = entries

    @classmethod
    def from_files(cls, idx_path: str | Path, mul_path: str | Path) -> UOSkills:
        idx_data = Path(idx_path).read_bytes()
        mul_data = Path(mul_path).read_bytes()
        entries: list[UOSkillEntry] = []
        for skill_id in range(len(idx_data) // 12):
            offset, length, extra = struct.unpack_from("<III", idx_data, skill_id * 12)
            if offset == 0xFFFFFFFF or length == 0:
                continue
            if offset > len(mul_data) or length > len(mul_data) - offset:
                continue
            payload = mul_data[offset : offset + length]
            if not payload:
                continue
            name = payload[1:].split(b"\0", 1)[0].decode("ascii", errors="replace")
            entries.append(
                UOSkillEntry(skill_id=skill_id, action=payload[0], name=name)
            )
            _ = extra
        return cls(entries)


@dataclass(frozen=True)
class UOSkillGroup:
    """One skill group and its assigned skill IDs."""

    group_id: int
    name: str
    skills: tuple[int, ...]


class UOSkillGroups:
    """Parsed skillgrp.mul skill grouping metadata."""

    def __init__(self, groups: list[UOSkillGroup]) -> None:
        self.groups = groups

    @classmethod
    def from_file(cls, path: str | Path) -> UOSkillGroups:
        data = Path(path).read_bytes()
        if len(data) < 4:
            return cls([])

        pos = 0
        count = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        unicode = count == -1
        if unicode:
            if len(data) < 8:
                return cls([])
            count = struct.unpack_from("<i", data, pos)[0]
            pos += 4

        if count <= 0 or count > 1024:
            return cls([])

        name_width = 34 if unicode else 17
        names = ["Misc"]
        for _ in range(max(0, count - 1)):
            if pos + name_width > len(data):
                break
            raw_name = data[pos : pos + name_width]
            pos += name_width
            if unicode:
                name = raw_name.split(b"\0\0", 1)[0].decode(
                    "utf-16le", errors="replace"
                )
            else:
                name = raw_name.split(b"\0", 1)[0].decode("ascii", errors="replace")
            names.append(name)

        assignments: list[int] = []
        while pos + 4 <= len(data):
            assignments.append(struct.unpack_from("<i", data, pos)[0])
            pos += 4

        grouped: list[list[int]] = [[] for _ in names]
        for skill_id, group_id in enumerate(assignments):
            if 0 <= group_id < len(grouped):
                grouped[group_id].append(skill_id)

        return cls(
            [
                UOSkillGroup(group_id=index, name=name, skills=tuple(grouped[index]))
                for index, name in enumerate(names)
            ]
        )


@dataclass(frozen=True)
class UOIndexedText:
    """One text entry from a localized IFF-style text list."""

    language: str
    source: str
    index: int
    text: str
    keys: tuple[int, ...]


def find_language_files(client: str | Path, stem: str) -> list[Path]:
    """Find language-specific files by case-insensitive stem."""
    root = Path(client)
    return sorted(
        path
        for path in root.iterdir()
        if path.is_file() and path.stem.lower() == stem.lower()
    )


def find_localized_text_files(client: str | Path) -> list[Path]:
    """Find localized FORM/TEXT files in a client directory."""
    root = Path(client)
    languages = {"enu", "deu", "esp", "fra", "jpn", "kor", "cht", "chs"}
    return sorted(
        path
        for path in root.iterdir()
        if path.is_file()
        and path.suffix.lstrip(".").lower() in languages
        and path.stem.lower() != "cliloc"
        and path.read_bytes()[:4] == b"FORM"
    )


def parse_iff_text_file(path: str | Path) -> list[UOIndexedText]:
    """Parse UO IFF-like localized TEXT/TKEY files.

    TEXT is exported as ordinal strings. TKEY is decoded when it matches the observed
    little-endian group/count table used by Tilehelp and related files.
    """
    source = Path(path)
    data = source.read_bytes()
    text_chunk = _find_chunk(data, b"TEXT")
    if text_chunk is None:
        return []

    texts = [
        item.decode("utf-8", errors="replace")
        for item in text_chunk.split(b"\0")
        if item
    ]
    key_map = _parse_tkey(_find_chunk(data, b"TKEY"))
    language = source.suffix.lstrip(".").lower()
    return [
        UOIndexedText(
            language=language,
            source=source.name,
            index=index,
            text=text,
            keys=tuple(key_map.get(index, ())),
        )
        for index, text in enumerate(texts)
    ]


def _find_chunk(data: bytes, tag: bytes) -> bytes | None:
    pos = data.find(tag)
    if pos < 0 or pos + 8 > len(data):
        return None
    size = int.from_bytes(data[pos + 4 : pos + 8], "big")
    start = pos + 8
    if size < 0 or start + size > len(data):
        return None
    return data[start : start + size]


def _parse_tkey(chunk: bytes | None) -> dict[int, list[int]]:
    if chunk is None:
        return {}
    pos = 0
    mapping: dict[int, list[int]] = {}
    while pos + 8 <= len(chunk):
        text_index = int.from_bytes(chunk[pos : pos + 4], "little")
        key_count = int.from_bytes(chunk[pos + 4 : pos + 8], "little")
        pos += 8
        if key_count > 10000 or pos + key_count * 4 > len(chunk):
            return {}
        keys = [
            int.from_bytes(chunk[pos + idx * 4 : pos + idx * 4 + 4], "little")
            for idx in range(key_count)
        ]
        pos += key_count * 4
        mapping[text_index] = keys
    return mapping
