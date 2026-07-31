"""Ultima Online DEF file metadata support."""

from __future__ import annotations

__all__ = [
    "UOBodyConvDefEntry",
    "UODefFile",
    "UODefLine",
    "UOEquipConvDefEntry",
    "UORedirectDefEntry",
    "load_all_defs",
]

from dataclasses import dataclass
from pathlib import Path
import re

_REDIRECT_RE = re.compile(
    r"^\s*(?P<source>-?\d+)\s+\{(?P<targets>[-?\d,\s]+)\}\s*(?P<hue>-?\d+)?"
)
_BODYCONV_RE = re.compile(
    r"^\s*(?P<body>\d+)\s+"
    r"(?P<anim2>-?\d+)\s+"
    r"(?P<anim3>-?\d+)\s+"
    r"(?P<anim4>-?\d+)\s+"
    r"(?P<anim5>-?\d+)\s+"
    r"(?P<anim6>-?\d+)"
)
_EQUIPCONV_RE = re.compile(
    r"^\s*(?P<body>\d+)\s+"
    r"(?P<equipment>\d+)\s+"
    r"(?P<convert_to>-?\d+)\s+"
    r"(?P<gump>-?\d+)\s+"
    r"(?P<hue>-?\d+)"
)
_DEF_NAMES = (
    "Anim1.def",
    "Anim2.def",
    "art.def",
    "Body.def",
    "Bodyconv.def",
    "Corpse.def",
    "Equipconv.def",
    "gump.def",
    "Intrface.def",
    "Music.def",
    "Sound.def",
    "stitchin.def",
    "TexTerr.def",
)


@dataclass(frozen=True)
class UORedirectDefEntry:
    """One DEF redirect entry: source id, replacement ids, and optional hue."""

    source: int
    targets: tuple[int, ...]
    hue: int | None
    line_number: int
    raw: str

    @property
    def first_target(self) -> int | None:
        return self.targets[0] if self.targets else None


@dataclass(frozen=True)
class UOBodyConvDefEntry:
    """One bodyconv.def archive conversion row."""

    body: int
    anim2: int
    anim3: int
    anim4: int
    anim5: int
    anim6: int
    line_number: int
    raw: str

    def archive_for_set(self, set_name: str) -> int | None:
        value = {
            "anim2": self.anim2,
            "anim3": self.anim3,
            "anim4": self.anim4,
            "anim5": self.anim5,
            "anim6": self.anim6,
        }.get(set_name)
        return value if value is not None and value >= 0 else None


@dataclass(frozen=True)
class UOEquipConvDefEntry:
    """One equipconv.def equipment conversion row."""

    body: int
    equipment: int
    convert_to: int
    gump: int
    hue: int
    comment: str
    line_number: int
    raw: str


@dataclass(frozen=True)
class UODefLine:
    """One parsed or preserved DEF line."""

    file: str
    line_number: int
    kind: str
    command: str
    args: tuple[str, ...]
    comment: str
    raw: str


class UODefFile:
    """Parsed contents of a UO DEF/configuration file."""

    def __init__(
        self,
        *,
        path: Path,
        lines: list[UODefLine],
        redirects: dict[int, UORedirectDefEntry],
        bodyconv: dict[int, UOBodyConvDefEntry],
        equipconv: list[UOEquipConvDefEntry],
    ) -> None:
        self.path = path
        self.lines = lines
        self.redirects = redirects
        self.bodyconv = bodyconv
        self.equipconv = equipconv

    @classmethod
    def from_file(cls, path: str | Path) -> UODefFile:
        source = Path(path)
        lines: list[UODefLine] = []
        redirects: dict[int, UORedirectDefEntry] = {}
        bodyconv: dict[int, UOBodyConvDefEntry] = {}
        equipconv: list[UOEquipConvDefEntry] = []

        current_definition = ""
        for line_number, raw_line in enumerate(_read_def_text(source).splitlines(), 1):
            body, comment = _split_comment(raw_line)
            line = body.strip()
            comment = comment.strip()
            if not line:
                if comment:
                    lines.append(
                        UODefLine(
                            source.name,
                            line_number,
                            "comment",
                            "",
                            (),
                            comment,
                            raw_line,
                        )
                    )
                continue

            if line.startswith("#"):
                current_definition = line[1:].strip()
                lines.append(
                    UODefLine(
                        source.name,
                        line_number,
                        "definition",
                        current_definition,
                        (),
                        comment,
                        raw_line,
                    )
                )
                continue

            redirect = _parse_redirect(line, line_number, raw_line)
            if redirect is not None:
                redirects[redirect.source] = redirect
                lines.append(
                    UODefLine(
                        source.name,
                        line_number,
                        "redirect",
                        str(redirect.source),
                        tuple(str(value) for value in redirect.targets),
                        "" if redirect.hue is None else str(redirect.hue),
                        raw_line,
                    )
                )
                continue

            bodyconv_entry = (
                _parse_bodyconv(line, line_number, raw_line)
                if source.name.lower() == "bodyconv.def"
                else None
            )
            if bodyconv_entry is not None:
                bodyconv[bodyconv_entry.body] = bodyconv_entry
                lines.append(
                    UODefLine(
                        source.name,
                        line_number,
                        "bodyconv",
                        str(bodyconv_entry.body),
                        (
                            str(bodyconv_entry.anim2),
                            str(bodyconv_entry.anim3),
                            str(bodyconv_entry.anim4),
                            str(bodyconv_entry.anim5),
                            str(bodyconv_entry.anim6),
                        ),
                        comment,
                        raw_line,
                    )
                )
                continue

            equip_entry = (
                _parse_equipconv(line, comment, line_number, raw_line)
                if source.name.lower() == "equipconv.def"
                else None
            )
            if equip_entry is not None:
                equipconv.append(equip_entry)
                lines.append(
                    UODefLine(
                        source.name,
                        line_number,
                        "equipconv",
                        str(equip_entry.body),
                        (
                            str(equip_entry.equipment),
                            str(equip_entry.convert_to),
                            str(equip_entry.gump),
                            str(equip_entry.hue),
                        ),
                        comment,
                        raw_line,
                    )
                )
                continue

            parts = line.split()
            command = parts[0] if parts else ""
            args = tuple(parts[1:])
            if command == "enddef":
                current_definition = ""
            lines.append(
                UODefLine(
                    source.name,
                    line_number,
                    "script",
                    command or current_definition,
                    args,
                    comment,
                    raw_line,
                )
            )

        return cls(
            path=source,
            lines=lines,
            redirects=redirects,
            bodyconv=bodyconv,
            equipconv=equipconv,
        )


def load_all_defs(client: str | Path) -> dict[str, UODefFile]:
    """Load every known DEF file found in a client directory."""
    root = Path(client)
    defs: dict[str, UODefFile] = {}
    for name in _DEF_NAMES:
        path = root / name
        if path.is_file():
            defs[name.lower()] = UODefFile.from_file(path)
    for path in sorted(root.glob("*.def")):
        key = path.name.lower()
        if key not in defs:
            defs[key] = UODefFile.from_file(path)
    return defs


def _read_def_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe") or data[1:2] == b"\x00":
        return data.decode("utf-16", errors="ignore")
    return data.decode("utf-8", errors="ignore")


def _split_comment(line: str) -> tuple[str, str]:
    positions = [
        pos
        for pos in (line.find("//"), line.find("#"))
        if pos >= 0 and (pos == 0 or line[pos - 1].isspace())
    ]
    if not positions:
        return line, ""
    pos = min(positions)
    return line[:pos], line[pos:].lstrip("#/").strip()


def _parse_redirect(
    line: str, line_number: int, raw_line: str
) -> UORedirectDefEntry | None:
    match = _REDIRECT_RE.match(line)
    if match is None:
        return None
    targets = tuple(
        int(value.strip(), 10)
        for value in match.group("targets").split(",")
        if value.strip()
    )
    hue_text = match.group("hue")
    return UORedirectDefEntry(
        source=int(match.group("source"), 10),
        targets=targets,
        hue=None if hue_text is None else int(hue_text, 10),
        line_number=line_number,
        raw=raw_line,
    )


def _parse_bodyconv(
    line: str, line_number: int, raw_line: str
) -> UOBodyConvDefEntry | None:
    match = _BODYCONV_RE.match(line)
    if match is None:
        return None
    return UOBodyConvDefEntry(
        body=int(match.group("body"), 10),
        anim2=int(match.group("anim2"), 10),
        anim3=int(match.group("anim3"), 10),
        anim4=int(match.group("anim4"), 10),
        anim5=int(match.group("anim5"), 10),
        anim6=int(match.group("anim6"), 10),
        line_number=line_number,
        raw=raw_line,
    )


def _parse_equipconv(
    line: str, comment: str, line_number: int, raw_line: str
) -> UOEquipConvDefEntry | None:
    match = _EQUIPCONV_RE.match(line)
    if match is None:
        return None
    return UOEquipConvDefEntry(
        body=int(match.group("body"), 10),
        equipment=int(match.group("equipment"), 10),
        convert_to=int(match.group("convert_to"), 10),
        gump=int(match.group("gump"), 10),
        hue=int(match.group("hue"), 10),
        comment=comment,
        line_number=line_number,
        raw=raw_line,
    )
