"""
``static/sdInfo*.flx`` reader for Ultima 9: Ascension.

A per-texture metadata table. Three archives ship, one beside each texture
archive, and each is **index-parallel** to its partner -- the same entry
indices are used in both, so ``sdInfo16.flx`` entry *n* describes
``bitmap16.flx`` entry *n*:

======================  ======================  =======
metadata                textures                entries
======================  ======================  =======
``static/sdInfo16.flx`` ``static/bitmap16.flx``   6,599
``static/sdInfo.flx``   ``static/bitmapsh.flx``   6,597
``static/sdInfoC.flx``  ``static/bitmapC.flx``    6,576
======================  ======================  =======

Every used entry is exactly 48 bytes -- twelve little-endian ``u32``::

    [0]   unknown
    [1]   packed: byte0 = log2(width), byte1 = log2(height),
                  byte2 = 0, byte3 = frame_count - 1
    [2]   low u16  = mip level count; high u16 = a flag
    [3]   unknown; only three values occur
    [4]   unknown
    [5]   width  of frame 0
    [6]   height of frame 0
    [7]   zero on 99.7% of entries
    [8]   zero on 99.7% of entries
    [9]   max width  across frames
    [10]  max height across frames
    [11]  low u16 = frame count; high u16 = a flag

The reason this table is worth reading is that it answers "how big is this
texture, how many frames, how many mips" **without decoding the texture**.
:mod:`titan.u9.texture` has to walk an entry's frame directory and per-frame
headers to learn the same things, and refuses entries whose pixel format it
cannot handle. This table answers for every entry regardless.

Everything above was established by correlation against the partner archive
rather than from documentation. Six fields reproduce exactly:

===============================================  ===========
check                                            agreement
===============================================  ===========
``[5]``/``[6]`` == frame 0's decoded dimensions  6,599/6,599 (and 100% in the other two archives)
``[9]``/``[10]`` == the entry header's max dims  6,599/6,599
``[11]`` low u16 == the header's frame count      6,599/6,599
``[2]`` low u16 == the entry header's mip count  6,599/6,599
===============================================  ===========

The packed byte fields in ``[1]`` are near-exact rather than exact:
``1 << byte0 == [5]`` on 98.1% of entries, which is precisely the share of
textures whose width is a power of two (98.4%) -- so the field is a log2
shortcut that simply does not apply to the irregular ones. ``byte3 ==
frame_count - 1`` holds on 99.6%.

Both ``[2]`` and ``[11]`` carry a flag in their high half, and reading either
whole rather than masked is a trap: ``sdInfoC.flx`` sets ``[11]``'s high bit on
5,687 of 6,576 entries, so an unmasked read matches the frame count on only
13.5% of them while the masked read matches all 6,576.

``[0]``, ``[3]``, ``[4]``, ``[7]`` and ``[8]`` are not decoded. They were
tested against frame offsets, frame lengths, entry byte length, the
compression field and the per-frame transparency flag; none correlates.

Example::

    from titan.u9.sdinfo import U9SdInfo

    info = U9SdInfo.from_file("static/sdInfo16.flx")
    rec = info.record(1805)
    print(rec.width, rec.height, rec.frame_count, rec.mip_levels)
"""

from __future__ import annotations

__all__ = ["U9SdInfo", "U9SdInfoError", "U9SdInfoRecord"]

import os
import struct
from dataclasses import dataclass

RECORD_SIZE = 48
RECORD_STRUCT = "<12I"


class U9SdInfoError(Exception):
    """Raised on malformed ``static/sdInfo*.flx`` data."""


@dataclass(frozen=True)
class U9SdInfoRecord:
    """One 48-byte texture-metadata record."""

    index: int
    width: int
    height: int
    max_width: int
    max_height: int
    frame_count: int
    mip_levels: int
    log2_width: int
    log2_height: int
    flag: int
    frame_flag: int
    fields: tuple[int, ...]

    @property
    def is_animated(self) -> bool:
        return self.frame_count > 1

    @property
    def frames_vary_in_size(self) -> bool:
        """True when frame 0 is smaller than the largest frame in the entry."""
        return (self.width, self.height) != (self.max_width, self.max_height)

    @property
    def is_power_of_two(self) -> bool:
        """True when both dimensions are powers of two, as 98.4% of textures are."""
        return (
            self.width > 0
            and self.height > 0
            and self.width & (self.width - 1) == 0
            and self.height & (self.height - 1) == 0
        )


class U9SdInfo:
    """Reader for one ``static/sdInfo*.flx`` archive."""

    def __init__(self, archive) -> None:
        self._archive = archive

    @classmethod
    def from_file(cls, filepath: str | os.PathLike[str]) -> U9SdInfo:
        from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError

        try:
            return cls(U9FlxArchive.from_file(filepath))
        except U9FlxArchiveError as e:
            raise U9SdInfoError(f"not a readable FLX archive: {e}") from e

    @property
    def num_entries(self) -> int:
        return self._archive.num_entries

    def used_indices(self) -> list[int]:
        """Texture indices this table describes."""
        return self._archive.used_entry_indices()

    def record(self, index: int) -> U9SdInfoRecord | None:
        """One record by texture index, or ``None`` if that slot is unused."""
        if index < 0 or index >= self.num_entries:
            raise U9SdInfoError(f"index {index} out of range (0..{self.num_entries - 1})")
        blob = self._archive.read_entry(index)
        if not blob:
            return None
        if len(blob) < RECORD_SIZE:
            raise U9SdInfoError(
                f"entry {index}: {len(blob)} bytes is short of the {RECORD_SIZE}-byte record"
            )
        f = struct.unpack_from(RECORD_STRUCT, blob, 0)
        packed = f[1]
        return U9SdInfoRecord(
            index=index,
            width=f[5],
            height=f[6],
            max_width=f[9],
            max_height=f[10],
            frame_count=f[11] & 0xFFFF,
            mip_levels=f[2] & 0xFFFF,
            log2_width=packed & 0xFF,
            log2_height=(packed >> 8) & 0xFF,
            flag=f[2] >> 16,
            frame_flag=f[11] >> 16,
            fields=f,
        )

    def records(self) -> list[U9SdInfoRecord]:
        """Every used record, in index order."""
        out = []
        for index in self.used_indices():
            rec = self.record(index)
            if rec is not None:
                out.append(rec)
        return out

    def cross_check(self, textures) -> dict[str, int]:
        """Compare this table against its partner texture archive.

        ``textures`` is a :class:`titan.u9.flx_archive.U9FlxArchive` opened on
        the matching ``bitmap*.flx``. Returns counts for each agreement the
        decode rests on, so a caller can confirm the pairing rather than
        assume it.
        """
        counts = dict.fromkeys(
            ("compared", "same_index_set", "max_dims", "frame_count", "mip_levels"), 0
        )
        mine = set(self.used_indices())
        theirs = set(textures.used_entry_indices())
        counts["same_index_set"] = int(mine == theirs)
        for index in sorted(mine & theirs):
            rec = self.record(index)
            blob = textures.read_entry(index)
            if rec is None or len(blob) < 12:
                continue
            counts["compared"] += 1
            header_w, mips, header_h = struct.unpack_from("<3H", blob, 0)
            frame_count = struct.unpack_from("<I", blob, 8)[0]
            if (rec.max_width, rec.max_height) == (header_w, header_h):
                counts["max_dims"] += 1
            if rec.frame_count == frame_count:
                counts["frame_count"] += 1
            if rec.mip_levels == mips:
                counts["mip_levels"] += 1
        return counts

    def __len__(self) -> int:
        return len(self.used_indices())

    def __iter__(self):
        return iter(self.records())
