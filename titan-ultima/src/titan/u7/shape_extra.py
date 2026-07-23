"""
Ultima 7 shape "Extra" metadata: shared, non-TFA `Shape_info` data sourced
from Exult's ``shape_info.txt`` (``%%section field_type`` / ``barge_type``
/ ``mountain_tops``).

Distinct from :mod:`titan.u7.typeflag` (TFA — binary shape traits shared by
every instance of a shape) and per-instance IREG object state (an
individual placement's runtime flags). See Exult's ``shapes/shapeinf.h``
(``Field_types`` enum) and ``shapes/shapevga.cc``
(``Shapes_vga_file::Read_Shapeinf_text_data_file``).

``shape_info.txt`` is not part of the original game data -- it is Exult's
own supplementary text config, normally compiled into ``exult_bg.flx`` /
``exult_si.flx`` (record 7 for BG, record 4 for SI; confirmed against
``data/bg/flx.in`` and ``data/si/flx.in``) rather than shipped loose in a
game's STATIC directory. :meth:`U7ShapeExtraTable.from_dir` checks a loose
``shape_info.txt`` in ``static_dir`` first (for patched/modded installs),
then falls back to extracting it from a real ``exult_bg.flx``/
``exult_si.flx`` via ``exult_flx_path``.
"""

from __future__ import annotations

__all__ = [
    "U7FieldType",
    "U7ShapeExtra",
    "U7ShapeExtraTable",
    "U7ShapeInfo",
]

from dataclasses import dataclass
from enum import IntEnum

from titan.u7.shapeinfo import _exult_record, _find_file

_EXULT_BG_SHAPE_INFO_RECORD = 7
_EXULT_SI_SHAPE_INFO_RECORD = 4


class U7FieldType(IntEnum):
    """Exult's ``shapes/shapeinf.h`` ``Field_types`` enum."""

    NONE = -1
    FIRE = 0
    SLEEP = 1
    POISON = 2
    CALTROPS = 3
    CAMPFIRE = 4


def _extract_section(text: str, name: str) -> str:
    """Return the raw lines between ``%%section name`` and ``%%endsection``."""
    marker = f"%%section {name}"
    start = text.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = text.find("%%endsection", start)
    if end == -1:
        end = len(text)
    return text[start:end]


def _parse_single_value_section(text: str, name: str) -> dict[int, int]:
    """Parse a ``:shapenum/value`` section into ``{shapenum: value}``."""
    result: dict[int, int] = {}
    for raw_line in _extract_section(text, name).splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line.startswith(":"):
            continue
        parts = line[1:].split("/")
        if len(parts) < 2:
            continue
        try:
            shape_num = int(parts[0])
            value = int(parts[1])
        except ValueError:
            continue
        result[shape_num] = value
    return result


@dataclass
class U7ShapeExtra:
    """Shared, non-TFA shape metadata for a single shape number."""

    shape_id: int
    field_type: U7FieldType = U7FieldType.NONE
    barge_type: int | None = None
    mountain_top: int | None = None
    gump_shape: int | None = None
    gump_font: int | None = None


class U7ShapeExtraTable:
    """Table of :class:`U7ShapeExtra` records parsed from ``shape_info.txt``."""

    def __init__(self) -> None:
        self._by_shape: dict[int, U7ShapeExtra] = {}

    def get(self, shape_id: int) -> U7ShapeExtra:
        """Return the extra record for ``shape_id``, defaulting if unset."""
        return self._by_shape.get(shape_id, U7ShapeExtra(shape_id=shape_id))

    @classmethod
    def from_text(cls, text: str) -> U7ShapeExtraTable:
        obj = cls()
        field_types = _parse_single_value_section(text, "field_type")
        barge_types = _parse_single_value_section(text, "barge_type")
        mountain_tops = _parse_single_value_section(text, "mountain_tops")

        for shape_num in set(field_types) | set(barge_types) | set(mountain_tops):
            raw_field_type = field_types.get(shape_num)
            obj._by_shape[shape_num] = U7ShapeExtra(
                shape_id=shape_num,
                field_type=(
                    U7FieldType(raw_field_type)
                    if raw_field_type is not None
                    else U7FieldType.NONE
                ),
                barge_type=barge_types.get(shape_num),
                mountain_top=mountain_tops.get(shape_num),
            )
        return obj

    @classmethod
    def from_file(cls, filepath: str) -> U7ShapeExtraTable:
        with open(filepath, "r", encoding="latin-1") as f:
            return cls.from_text(f.read())

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        game: str = "bg",
        exult_flx_path: str | None = None,
    ) -> U7ShapeExtraTable:
        path = _find_file(static_dir, ("shape_info.txt", "SHAPE_INFO.TXT"))
        if path:
            return cls.from_file(str(path))
        record_index = (
            _EXULT_BG_SHAPE_INFO_RECORD
            if game.lower() == "bg"
            else _EXULT_SI_SHAPE_INFO_RECORD
        )
        data = _exult_record(exult_flx_path, record_index)
        if not data:
            return cls()
        return cls.from_text(data.decode("latin-1"))


@dataclass
class U7ShapeInfo:
    """Combined shape-info facade: TFA + Extra, matching Exult's ``Shape_info``."""

    tfa: object  # titan.u7.typeflag.U7TypeFlags.ShapeEntry
    extra: U7ShapeExtra

    @property
    def is_typed_field(self) -> bool:
        return self.extra.field_type != U7FieldType.NONE

    @property
    def becomes_field_object(self) -> bool:
        """Exult's ``gamemap.cc`` condition: ``has_contact_effect() &&
        get_field_type() >= 0`` (``gamemap.cc:1141-1142``)."""
        return bool(self.tfa.has_contact_effect) and self.is_typed_field
