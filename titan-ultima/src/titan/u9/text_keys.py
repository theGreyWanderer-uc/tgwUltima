"""Lossless reader for Ultima IX ``static/text.dat``.

The file is a bucketed lookup table from an 8-bit spoken-line key to an entry
index in ``static/text.flx``. Everything is little-endian::

    int32  bucket_count
    repeat bucket_count times:
        uint32 item_count
        repeat item_count times:
            uint32 stored_hash     -- the bucket the key hashes to
            uint32 stored_crc      -- CRC-32 of the key and its NUL
            uint32 text_index      -- entry in static/text.flx

The retail 1.19F loader (``u9.exe`` ``0x004AF030``) reads exactly that and
checks nothing. The retail lookup (``0x004AF230``) computes, over the key's
bytes without the terminator::

    h = (64 * h + byte) mod bucket_count           (bytes zero-extended)

and a non-reflected CRC-32 (polynomial ``0x04C11DB7``, register preset to
``0xFFFFFFFF``, result inverted) over the key bytes *including* the NUL. It then
walks bucket ``h`` and returns the first item whose stored hash equals ``h``
and whose stored CRC equals the key CRC. An item stored under the wrong
bucket, or behind an earlier item with the same hash and CRC, can never be
found; Titan keeps such items and reports them rather than dropping them.

The retail caller (``0x00615FC0``) looks up ``prefix + line`` with nothing in
between. Its two callers supply the prefix: the constant ``"UI : "``
(``0x0061DDE0``) or ``"%s : "`` formatted with the speaking NPC record's name
(``0x0061DE40``). The speaker is not stored in either file, so
:func:`reconstruct_keys` tries ``UI`` and the names from ``runtime/NPC.FLX``
when they are supplied, and otherwise falls back to ``text.flx`` block names
and a few observed record names. File markers are keyed as ``"C:" + marker``.
Every reconstructed key is accepted only when both the bucket and the CRC
match the stored item. Key bytes are the ``text.flx`` code points taken
one-for-one, i.e. Latin-1.
"""

from __future__ import annotations

__all__ = [
    "KEY_ENCODING",
    "KEY_SEPARATOR",
    "MARKER_KEY_PREFIX",
    "U9TextKey",
    "U9TextKeyBucket",
    "U9TextKeyItem",
    "U9TextKeyTable",
    "U9TextKeyTableError",
    "key_bucket",
    "key_crc",
    "reconstruct_keys",
    "text_reference_status",
]

import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from titan.u9.text import U9TextArchive

KEY_ENCODING = "latin-1"
KEY_SEPARATOR = " : "
MARKER_KEY_PREFIX = "C:"
# The interface prefix is a code constant; every other speaker is an NPC
# record name. Without NPC.FLX, these observed record names are tried after the
# line's own block name.
UI_SPEAKER = "UI"
FALLBACK_SPEAKERS = ("Avatar", "Gypsy", "Questions", "Hairam", "Skeleton")

_COUNT_SIZE = 4
_ITEM = struct.Struct("<III")
_CRC_POLYNOMIAL = 0x04C11DB7


def _build_crc_table() -> tuple[int, ...]:
    table = []
    for value in range(256):
        register = value << 24
        for _ in range(8):
            if register & 0x80000000:
                register = ((register << 1) ^ _CRC_POLYNOMIAL) & 0xFFFFFFFF
            else:
                register = (register << 1) & 0xFFFFFFFF
        table.append(register)
    return tuple(table)


_CRC_TABLE = _build_crc_table()


def _check_key(key: bytes) -> None:
    if b"\0" in key:
        raise ValueError("a lookup key cannot contain a NUL byte")


def key_bucket(key: bytes, bucket_count: int) -> int:
    """Return the bucket the retail lookup computes for ``key`` (no NUL)."""
    _check_key(key)
    if bucket_count <= 0:
        raise ValueError(f"bucket count must be positive; found {bucket_count}")
    value = 0
    for byte in key:
        value = (64 * value + byte) % bucket_count
    return value


def key_crc(key: bytes) -> int:
    """Return the stored-CRC value for ``key``; the NUL is appended here."""
    _check_key(key)
    register = 0xFFFFFFFF
    for byte in key + b"\0":
        register = ((register << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[(register >> 24) ^ byte]
    return register ^ 0xFFFFFFFF


class U9TextKeyTableError(Exception):
    """Raised when ``text.dat`` is truncated or has impossible framing."""


@dataclass(frozen=True)
class U9TextKeyItem:
    """One stored ``(hash, crc, text index)`` triple."""

    bucket: int
    position: int
    offset: int
    stored_hash: int
    stored_crc: int
    text_index: int

    @property
    def hash_matches_bucket(self) -> bool:
        return self.stored_hash == self.bucket


@dataclass(frozen=True)
class U9TextKeyBucket:
    """One bucket: its count word's offset and its items in file order."""

    bucket: int
    offset: int
    items: tuple[U9TextKeyItem, ...]


@dataclass(frozen=True)
class U9TextKey:
    """A reconstructed key for one stored item, verified by bucket and CRC."""

    text: str
    speaker: str | None
    method: str

    @property
    def key_bytes(self) -> bytes:
        return self.text.encode(KEY_ENCODING)


class U9TextKeyTable:
    """Lossless bucket-ordered view of ``static/text.dat``."""

    def __init__(
        self,
        bucket_count_raw: int,
        buckets: Iterable[U9TextKeyBucket],
        trailing_data: bytes = b"",
    ) -> None:
        self.bucket_count = bucket_count_raw
        self.buckets = tuple(buckets)
        self.trailing_data = bytes(trailing_data)
        if len(self.buckets) != max(bucket_count_raw, 0):
            raise U9TextKeyTableError(
                f"{len(self.buckets)} buckets given for a count of {bucket_count_raw}"
            )

    @classmethod
    def from_bytes(cls, data: bytes) -> U9TextKeyTable:
        data = bytes(data)
        if len(data) < _COUNT_SIZE:
            raise U9TextKeyTableError(
                f"text.dat needs a 4-byte bucket count; found {len(data)} bytes"
            )
        (bucket_count,) = struct.unpack_from("<i", data, 0)
        if bucket_count < 0:
            raise U9TextKeyTableError(f"negative bucket count {bucket_count}")
        # Every bucket needs at least its count word; check before allocating.
        if bucket_count > (len(data) - _COUNT_SIZE) // _COUNT_SIZE:
            raise U9TextKeyTableError(
                f"bucket count {bucket_count} cannot fit in {len(data)} bytes"
            )

        offset = _COUNT_SIZE
        buckets = []
        for bucket in range(bucket_count):
            if offset + _COUNT_SIZE > len(data):
                raise U9TextKeyTableError(
                    f"truncated at bucket {bucket}: count word at 0x{offset:x} "
                    f"passes the end of {len(data)} bytes"
                )
            bucket_offset = offset
            (item_count,) = struct.unpack_from("<I", data, offset)
            offset += _COUNT_SIZE
            if item_count > (len(data) - offset) // _ITEM.size:
                raise U9TextKeyTableError(
                    f"bucket {bucket} at 0x{bucket_offset:x} claims {item_count} "
                    f"items; only {len(data) - offset} bytes remain"
                )
            items = []
            for position in range(item_count):
                stored_hash, stored_crc, text_index = _ITEM.unpack_from(data, offset)
                items.append(
                    U9TextKeyItem(
                        bucket=bucket,
                        position=position,
                        offset=offset,
                        stored_hash=stored_hash,
                        stored_crc=stored_crc,
                        text_index=text_index,
                    )
                )
                offset += _ITEM.size
            buckets.append(
                U9TextKeyBucket(bucket=bucket, offset=bucket_offset, items=tuple(items))
            )
        return cls(bucket_count, buckets, data[offset:])

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> U9TextKeyTable:
        try:
            return cls.from_bytes(Path(path).read_bytes())
        except OSError as error:
            raise U9TextKeyTableError(str(error)) from error

    def to_bytes(self) -> bytes:
        """Serialize every bucket, item and trailing byte in stored order."""
        parts = [struct.pack("<i", self.bucket_count)]
        for bucket in self.buckets:
            parts.append(struct.pack("<I", len(bucket.items)))
            parts.extend(
                _ITEM.pack(item.stored_hash, item.stored_crc, item.text_index)
                for item in bucket.items
            )
        parts.append(self.trailing_data)
        return b"".join(parts)

    @property
    def items(self) -> tuple[U9TextKeyItem, ...]:
        """Every stored item, in file order."""
        return tuple(item for bucket in self.buckets for item in bucket.items)

    def lookup_bytes(self, key: bytes) -> U9TextKeyItem | None:
        """Return the item the retail lookup would select, or ``None``."""
        if self.bucket_count <= 0:
            return None
        bucket = key_bucket(key, self.bucket_count)
        crc = key_crc(key)
        for item in self.buckets[bucket].items:
            if item.stored_hash == bucket and item.stored_crc == crc:
                return item
        return None

    def lookup(self, key: str) -> U9TextKeyItem | None:
        """Look up a text key such as ``"Avatar : Farewell."``."""
        return self.lookup_bytes(key.encode(KEY_ENCODING))

    def reachability(self, item: U9TextKeyItem) -> str:
        """Say whether any key can select ``item`` under the retail rule."""
        if not item.hash_matches_bucket:
            return "unreachable_hash_mismatch"
        for earlier in self.buckets[item.bucket].items[: item.position]:
            if (earlier.stored_hash, earlier.stored_crc) == (
                item.stored_hash,
                item.stored_crc,
            ):
                return "shadowed_by_earlier_item"
        return "reachable"

    def text_index_counts(self) -> dict[int, int]:
        """How many stored items point at each ``text.flx`` index."""
        counts: dict[int, int] = {}
        for item in self.items:
            counts[item.text_index] = counts.get(item.text_index, 0) + 1
        return counts


def text_reference_status(item: U9TextKeyItem, text: U9TextArchive) -> str:
    """Validate ``item.text_index`` against a ``text.flx`` archive."""
    if item.text_index >= text.num_entries:
        return "out_of_range"
    if text.entry(item.text_index) is None:
        return "empty_slot"
    return "valid"


def reconstruct_keys(
    table: U9TextKeyTable,
    text: U9TextArchive,
    speakers: Iterable[str] = (),
    npc_names: Iterable[str] | None = None,
) -> dict[tuple[int, int], U9TextKey]:
    """Recover the key of every item whose line and speaker can be matched.

    ``npc_names`` are the record names from ``runtime/NPC.FLX``, the source the
    game formats the speaker from. When given, only they, ``UI`` and any extra
    ``speakers`` are tried; otherwise ``text.flx`` block names and a few
    observed record names stand in for them.

    Returns a mapping from ``(bucket, position)`` to the verified key. Items
    left out are unresolved: their target is not a valid line, or no candidate
    speaker reproduces both the stored bucket and the stored CRC.
    """
    if table.bucket_count <= 0:
        return {}
    owners: dict[int, str] = {}
    block_names: list[str] = []
    for block in text.blocks():
        block_names.append(block.name)
        for line in block.lines:
            owners[line.index] = block.name
    npc_set = frozenset(npc_names) if npc_names is not None else None
    if npc_set is not None:
        pool = [UI_SPEAKER, *sorted(npc_set), *speakers]
    else:
        pool = [*speakers, UI_SPEAKER, *FALLBACK_SPEAKERS, *block_names]
    modulus = table.bucket_count
    prefixes = _speaker_prefixes(pool, modulus)
    found: dict[tuple[int, int], U9TextKey] = {}
    for item in table.items:
        line = _key_line(item, text)
        if line is None:
            continue
        entry_text, line_bytes, is_marker = line
        if is_marker:
            key = _match_marker(item, entry_text, line_bytes, modulus)
        else:
            key = _match_speaker(
                item,
                entry_text,
                line_bytes,
                prefixes,
                owners.get(item.text_index),
                npc_set,
                modulus,
            )
        if key is not None:
            found[(item.bucket, item.position)] = key
    return found


def _speaker_prefixes(
    pool: Iterable[str], modulus: int
) -> dict[str, tuple[bytes, int]]:
    """Encode each distinct speaker's ``"<name> : "`` prefix with its hash."""
    prefixes: dict[str, tuple[bytes, int]] = {}
    for speaker in dict.fromkeys(name for name in pool if name):
        try:
            prefix = (speaker + KEY_SEPARATOR).encode(KEY_ENCODING)
        except UnicodeEncodeError:
            continue
        if b"\0" not in prefix:
            prefixes[speaker] = (prefix, key_bucket(prefix, modulus))
    return prefixes


def _key_line(
    item: U9TextKeyItem, text: U9TextArchive
) -> tuple[str, bytes, bool] | None:
    """Return the target line as text and key bytes, or ``None`` if unusable."""
    if text_reference_status(item, text) != "valid":
        return None
    entry = text.entry(item.text_index)
    assert entry is not None
    try:
        line = entry.text.encode(KEY_ENCODING)
    except UnicodeEncodeError:
        return None
    if b"\0" in line:
        return None
    return entry.text, line, entry.is_file_marker


def _match_marker(
    item: U9TextKeyItem, entry_text: str, line: bytes, modulus: int
) -> U9TextKey | None:
    key = MARKER_KEY_PREFIX.encode(KEY_ENCODING) + line
    if key_bucket(key, modulus) != item.bucket or key_crc(key) != item.stored_crc:
        return None
    return U9TextKey(
        text=MARKER_KEY_PREFIX + entry_text, speaker=None, method="file_marker"
    )


def _match_speaker(
    item: U9TextKeyItem,
    entry_text: str,
    line: bytes,
    prefixes: dict[str, tuple[bytes, int]],
    owner: str | None,
    npc_names: frozenset[str] | None,
    modulus: int,
) -> U9TextKey | None:
    # The bucket hash composes: hash(prefix + line) is
    # (hash(prefix) * 64**len(line) + hash(line)) mod count, so each speaker
    # costs one multiply; the CRC is computed only when the bucket matches.
    line_hash = key_bucket(line, modulus)
    scale = pow(64, len(line), modulus)
    order = ([owner] if owner in prefixes else []) + [
        speaker for speaker in prefixes if speaker != owner
    ]
    for speaker in order:
        prefix, prefix_hash = prefixes[speaker]
        if (prefix_hash * scale + line_hash) % modulus != item.bucket:
            continue
        if key_crc(prefix + line) != item.stored_crc:
            continue
        return U9TextKey(
            text=speaker + KEY_SEPARATOR + entry_text,
            speaker=speaker,
            method=_speaker_method(speaker, owner, npc_names),
        )
    return None


def _speaker_method(
    speaker: str, owner: str | None, npc_names: frozenset[str] | None
) -> str:
    if speaker == UI_SPEAKER:
        return "ui_prefix"
    if npc_names is not None and speaker in npc_names:
        return "npc_name"
    return "block_speaker" if speaker == owner else "other_speaker"
