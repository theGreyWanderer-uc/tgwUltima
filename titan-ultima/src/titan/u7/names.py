"""
Ultima 7 shape name table from TEXT.FLX, and per-frame names from shape_info.txt.

TEXT.FLX is a Flex archive where record N is the null-terminated display name
for shape N (e.g. record 522 → "locked chest").  Records 0x500+ are misc_names
— per-frame item names such as "gavel", "quill", "inkwell" for shape 675.

shape_info.txt (Exult supplemental data) maps (shape, frame) → misc_name index
via ``%%section framenames`` entries of the form ``:shape/frame/qual/type/msgid``.

Example::

    from titan.u7.names import U7ShapeNames, U7FrameNames

    names  = U7ShapeNames.from_file("STATIC/TEXT.FLX")
    frames = U7FrameNames.from_files("exult/data/bg/shape_info.txt", "STATIC/TEXT.FLX")

    print(names.get(675))                # "desk item"
    print(frames.get(675, 1))            # "quill"
    print(frames.label(675, 1, names))   # "quill"
"""

from __future__ import annotations

__all__ = ["U7ShapeNames", "U7FrameNames"]

import os
from pathlib import Path
from typing import Optional

from titan.u7.flex import U7FlexArchive


def _clean_article_name(raw: str) -> str:
    """Strip Exult article/plural formatting from a TEXT.FLX name.

    Records in TEXT.FLX use the format ``article/name/prefix/suffix`` where
    the article is a short word like ``a``, ``an``, or ``the``, and suffix
    encodes plural rules (e.g. ``s``).  Examples::

        '/potion//s'      → 'potion'
        'a/black pearl//s' → 'black pearl'
        '/gold coin//s'   → 'gold coin'
        'lockpick'        → 'lockpick'   (unchanged)
    """
    if "/" not in raw:
        return raw
    parts = raw.split("/")
    # First segment is an article (empty, or 1-3 chars: "a", "an", "the").
    if len(parts) >= 2 and len(parts[0]) <= 3:
        return parts[1].strip()
    return parts[0].strip()


class U7ShapeNames:
    """Shape display names loaded from TEXT.FLX."""

    def __init__(self, names: list[str]) -> None:
        self._names = names

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str) -> "U7ShapeNames":
        """Load TEXT.FLX from an explicit path."""
        flex = U7FlexArchive.from_file(path)
        names: list[str] = []
        for i in range(len(flex.records)):
            rec = flex.get_record(i)
            if rec:
                text = rec.split(b"\x00", 1)[0].decode("latin-1", errors="replace").strip()
                text = _clean_article_name(text)
            else:
                text = ""
            names.append(text)
        return cls(names)

    @classmethod
    def from_static_dir(cls, static_dir: str) -> Optional["U7ShapeNames"]:
        """Try to load TEXT.FLX from a STATIC directory. Returns None if absent."""
        for name in ("TEXT.FLX", "text.flx"):
            path = Path(static_dir) / name
            if path.exists():
                return cls.from_file(str(path))
        return None

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, shape_num: int) -> str:
        """Return the display name for shape_num, or empty string if unknown."""
        if 0 <= shape_num < len(self._names):
            return self._names[shape_num]
        return ""

    def label(self, shape_num: int) -> str:
        """Return '522 (locked chest)' style label, or just '522' if unnamed."""
        name = self.get(shape_num)
        if name:
            return f"{shape_num} ({name})"
        return str(shape_num)

    def find_shapes(self, pattern: str) -> list[int]:
        """Return shape numbers whose name contains pattern (case-insensitive)."""
        lower = pattern.lower()
        return [i for i, n in enumerate(self._names) if lower in n.lower()]

    def __len__(self) -> int:
        return len(self._names)


class U7FrameNames:
    """Per-frame shape names loaded from shape_info.txt + TEXT.FLX misc_names.

    Exult's ``%%section framenames`` in *shape_info.txt* maps every
    ``(shape, frame)`` pair to an index into the misc_names region of
    TEXT.FLX (records 0x500+).  This class parses both sources and
    exposes a ``get(shape, frame)`` lookup.
    """

    def __init__(self, lookup: dict[tuple[int, int], str]) -> None:
        self._lookup = lookup  # (shape, frame) → name; frame=-1 means wildcard

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_misc_name(raw: str) -> str:
        return _clean_article_name(raw)

    # Record index of shape_info.txt inside exult_bg.flx / exult_si.flx.
    _FLX_RECORD_BG = 7
    _FLX_RECORD_SI = 4

    @classmethod
    def _load_misc_names(cls, text_flx_path: str) -> list[str]:
        """Return misc_names list from TEXT.FLX (records 0x500+)."""
        flex = U7FlexArchive.from_file(text_flx_path)
        result: list[str] = []
        for i in range(0x500, len(flex.records)):
            rec = flex.get_record(i)
            raw = (
                rec.split(b"\x00", 1)[0].decode("latin-1", errors="replace").strip()
                if rec
                else ""
            )
            result.append(cls._clean_misc_name(raw))
        return result

    @classmethod
    def _parse_framenames(
        cls, lines: "list[str]", misc_names: list[str]
    ) -> "dict[tuple[int, int], str]":
        """Parse ``%%section framenames`` lines → lookup dict."""
        lookup: dict[tuple[int, int], str] = {}
        in_section = False
        for line in lines:
            line = line.strip()
            if line == "%%section framenames":
                in_section = True
                continue
            if line.startswith("%%"):
                if in_section:
                    break
                continue
            if not in_section or not line.startswith(":") or line.startswith("#"):
                continue
            parts = line[1:].split("/")
            if len(parts) < 4:
                continue
            try:
                shape = int(parts[0])
                frame = int(parts[1])
                typ   = int(parts[3])
            except ValueError:
                continue
            if typ == 0 and len(parts) >= 5:
                try:
                    msgid = int(parts[4])
                except ValueError:
                    continue
                if 0 <= msgid < len(misc_names) and misc_names[msgid]:
                    lookup[(shape, frame)] = misc_names[msgid]
            elif typ == -1:
                lookup[(shape, frame)] = ""  # explicitly unnamed
        return lookup

    @classmethod
    def from_files(cls, shape_info_path: str, text_flx_path: str) -> "U7FrameNames":
        """Parse shape_info.txt framenames + TEXT.FLX misc_names.

        Args:
            shape_info_path: Path to Exult's ``data/bg/shape_info.txt``.
            text_flx_path:   Path to the game's ``STATIC/TEXT.FLX``.
        """
        misc_names = cls._load_misc_names(text_flx_path)
        with open(shape_info_path, encoding="latin-1") as fh:
            lines = fh.readlines()
        return cls(cls._parse_framenames(lines, misc_names))

    @classmethod
    def from_flx(
        cls,
        exult_flx_path: str,
        text_flx_path: str,
        game: str = "bg",
    ) -> "U7FrameNames":
        """Load frame names from an installed ``exult_bg.flx`` / ``exult_si.flx``.

        shape_info.txt is embedded as record 7 (BG) or record 4 (SI) inside
        the Exult binary Flex archive that ships with every Exult installation.

        Args:
            exult_flx_path: Path to ``exult_bg.flx`` or ``exult_si.flx``.
            text_flx_path:  Path to the game's ``STATIC/TEXT.FLX``.
            game:           ``"bg"`` or ``"si"`` — selects the record index.
        """
        record_idx = cls._FLX_RECORD_BG if game == "bg" else cls._FLX_RECORD_SI
        flx = U7FlexArchive.from_file(exult_flx_path)
        rec = flx.get_record(record_idx)
        if not rec:
            raise ValueError(
                f"Record {record_idx} in {exult_flx_path} is empty; "
                "expected shape_info.txt content."
            )
        text = rec.decode("latin-1", errors="replace")
        misc_names = cls._load_misc_names(text_flx_path)
        return cls(cls._parse_framenames(text.splitlines(), misc_names))

    @classmethod
    def from_static_and_exult(
        cls,
        static_dir: str,
        exult_data_dir: str,
        game: str = "bg",
    ) -> Optional["U7FrameNames"]:
        """Convenience loader given a STATIC dir and an Exult data source.

        Tries three sources in order:
        1. ``exult_data_dir/exult_bg.flx`` — installed Exult binary Flex archive.
        2. ``exult_data_dir/data/exult_bg.flx`` — alternate layout.
        3. ``exult_data_dir/<game>/shape_info.txt`` — Exult source tree.

        Args:
            static_dir:     Path to the game's STATIC directory.
            exult_data_dir: Exult install directory, ``data/`` subdirectory,
                            or Exult source ``data/`` root.
            game:           ``"bg"`` or ``"si"``.
        """
        text_flx = None
        for name in ("TEXT.FLX", "text.flx"):
            p = Path(static_dir) / name
            if p.exists():
                text_flx = str(p)
                break
        if text_flx is None:
            return None

        flx_name = f"exult_bg.flx" if game == "bg" else "exult_si.flx"
        data_root = Path(exult_data_dir)

        # Try binary .flx first (installed Exult)
        for candidate in (
            data_root / flx_name,
            data_root / "data" / flx_name,
        ):
            if candidate.exists():
                return cls.from_flx(str(candidate), text_flx, game=game)

        # Fall back to raw text file (Exult source tree layout: data/bg/shape_info.txt)
        shape_info = data_root / game / "shape_info.txt"
        if shape_info.exists():
            return cls.from_files(str(shape_info), text_flx)

        return None

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, shape: int, frame: int) -> str:
        """Return the frame-specific name, or empty string if unknown.

        Tries exact ``(shape, frame)`` first, then the wildcard
        ``(shape, -1)`` entry (which applies to all frames).
        """
        return self._lookup.get((shape, frame), self._lookup.get((shape, -1), ""))

    def label(
        self,
        shape: int,
        frame: int,
        shape_names: Optional["U7ShapeNames"] = None,
    ) -> str:
        """Return the best available display name.

        Frame name takes priority; falls back to shape name from
        *shape_names* if provided, then empty string.
        """
        name = self.get(shape, frame)
        if name:
            return name
        if shape_names is not None:
            return shape_names.get(shape)
        return ""
