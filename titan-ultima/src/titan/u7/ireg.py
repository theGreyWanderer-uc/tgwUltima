"""
Shared Ultima 7 IREG per-instance object-state decoder.

Ports Exult's ``Game_map::read_ireg_objects`` (``gamemap.cc:900-1126``) byte
layout and flag rules: ``Get_quality_flags``, ``nibble_swap``/``read_lift``,
and the simple/container/body dispatch. Used by :mod:`titan.u7.map` (world
and superchunk IREG), :mod:`titan.u7.save` (NPC/monster inventory IREG),
and :mod:`titan.u7.container` (container-browse) so all three share one
faithful implementation instead of three divergent partial ones.

These are *per-instance* object flags -- distinct from :mod:`titan.u7.typeflag`
(TFA, shared by every placement of a shape) and :mod:`titan.u7.shape_extra`
(Extra, also shared/non-per-instance metadata).

Note on dispatch: real Exult additionally gates the body-record branch on
a shape's internal ``is_body_shape()`` flag (a ``shape_flags`` bit set at
shape-table init time, unrelated to TFA's ``shape_class``) before falling
back to record length. In practice only actual NPC/monster body objects
ever produce 13/14-byte IREG records, so this module dispatches purely by
``testlen`` (record length) -- matching Titan's existing convention and
titanWork.md's own spec -- rather than requiring that additional flag.
"""

from __future__ import annotations

__all__ = [
    "U7ObjectFlags",
    "IregDecodedEntry",
    "get_quality_flags",
    "nibble_swap",
    "read_lift",
    "decode_ireg_payload",
    "object_flag_names",
]

from dataclasses import dataclass
from enum import IntFlag

from titan.u7.typeflag import U7TypeFlags


class U7ObjectFlags(IntFlag):
    """Per-instance IREG object flags (Exult's ``Obj_flags``, decoded subset)."""

    NONE = 0
    INVISIBLE = 1 << 0
    OKAY_TO_TAKE = 1 << 1
    TEMPORARY = 1 << 2


def nibble_swap(val: int) -> int:
    """Exult's ``objs/iregobjs.h`` ``nibble_swap``: rotate a byte left 4 bits."""
    return ((val << 4) | (val >> 4)) & 0xFF


def read_lift(val: int, extended_lift: bool) -> int:
    """Exult's ``read_lift`` lambda in ``Game_map::read_ireg_objects``.

    Non-extended (``IREG_EXTENDED2`` not used): masked to 4 bits.
    Extended (entry was prefixed by the 0xFD ``IREG_EXTENDED2`` marker):
    the full swapped byte is used unmasked.
    """
    lift = nibble_swap(val)
    return lift if extended_lift else (lift & 0x0F)


def get_quality_flags(qualbyte: int) -> U7ObjectFlags:
    """Exult's ``Get_quality_flags`` (``gamemap.cc``): bit0->invisible, bit3->okay_to_take."""
    flags = U7ObjectFlags.NONE
    if qualbyte & 0x01:
        flags |= U7ObjectFlags.INVISIBLE
    if qualbyte & 0x08:
        flags |= U7ObjectFlags.OKAY_TO_TAKE
    return flags


_OBJECT_FLAG_NAMES: tuple[tuple[U7ObjectFlags, str], ...] = (
    (U7ObjectFlags.INVISIBLE, "invisible"),
    (U7ObjectFlags.OKAY_TO_TAKE, "okay_to_take"),
    (U7ObjectFlags.TEMPORARY, "temporary"),
)


def object_flag_names(flags: U7ObjectFlags) -> list[str]:
    """Human-readable names of every set bit in *flags*, for CLI display."""
    return [name for bit, name in _OBJECT_FLAG_NAMES if flags & bit]


@dataclass
class IregDecodedEntry:
    """Decoded per-instance state for one IREG entry (position-independent;
    callers attach world tile or container gump coordinates separately)."""

    shape: int
    frame: int
    lift: int
    quality: int
    raw_quality: int
    object_flags: U7ObjectFlags
    raw_flag_byte: int | None
    record_length: int
    is_extended: bool
    has_children_marker: bool
    child_inherit_flags: U7ObjectFlags


@dataclass
class _EntryFields:
    lift: int
    quality: int
    raw_quality: int
    raw_flag_byte: int | None
    oflags: U7ObjectFlags
    has_children_marker: bool


def _decode_shape_frame(payload: bytes, extended: bool) -> tuple[int, int] | None:
    if extended:
        if len(payload) < 5:
            return None
        return payload[2] + payload[3] * 256, payload[4]
    if len(payload) < 4:
        return None
    return payload[2] + (payload[3] & 0x03) * 256, (payload[3] >> 2) & 0x3F


def _decode_simple(
    payload: bytes, adj: int, testlen: int, extended_lift: bool,
    oflags: U7ObjectFlags, shape_class: int | None,
) -> _EntryFields | None:
    if testlen == 10 and len(payload) > 6 + adj and (payload[6 + adj] & 0x01):
        oflags |= U7ObjectFlags.TEMPORARY

    if len(payload) <= 5 + adj:
        return None
    lift = read_lift(payload[4 + adj], extended_lift)
    raw_quality = payload[5 + adj]
    quality = raw_quality

    if shape_class == U7TypeFlags.SHAPE_CLASS_QUANTITY:
        if raw_quality & 0x80:
            oflags |= U7ObjectFlags.OKAY_TO_TAKE
            quality = raw_quality & 0x7F
        else:
            oflags &= ~U7ObjectFlags.OKAY_TO_TAKE
    elif shape_class == U7TypeFlags.SHAPE_CLASS_QUALITY_FLAGS:
        # Full replacement -- discards any temporary bit just set above.
        oflags = get_quality_flags(raw_quality)
        quality = 0

    return _EntryFields(lift, quality, raw_quality, None, oflags, False)


def _decode_container_or_body(
    payload: bytes, adj: int, testlen: int, extended_lift: bool,
) -> _EntryFields | None:
    extbody = 1 if testlen == 13 else 0  # 12 (container) has no extbody variant
    if len(payload) <= 11 + adj + extbody:
        return None
    type_val = payload[4 + adj] + payload[5 + adj] * 256
    lift = read_lift(payload[9 + adj + extbody], extended_lift)
    raw_quality = payload[7 + adj]
    raw_flag_byte = payload[11 + adj + extbody]
    oflags = get_quality_flags(raw_flag_byte)
    return _EntryFields(lift, raw_quality, raw_quality, raw_flag_byte, oflags, type_val != 0)


def _decode_spellbook(payload: bytes, adj: int, extended_lift: bool) -> _EntryFields | None:
    if len(payload) <= 9 + adj:
        return None
    lift = read_lift(payload[9 + adj], extended_lift)
    return _EntryFields(lift, 0, 0, None, U7ObjectFlags.NONE, False)


def decode_ireg_payload(
    payload: bytes,
    *,
    entlen: int,
    extended: bool,
    extended_lift: bool,
    inherited_flags: U7ObjectFlags = U7ObjectFlags.NONE,
    shape_class: int | None = None,
) -> IregDecodedEntry | None:
    """
    Decode one non-egg IREG entry's shape/frame/lift/quality/flags.

    ``payload`` is the raw ``entlen``-byte entry body (before any pointer
    shift). ``extended`` is True for 2-byte shape numbers (``IREG_EXTENDED``,
    wire marker 254); ``extended_lift`` is True whenever the entry was
    prefixed by either extended-marker byte (254 or 253), since both widen
    the lift field the same way. ``shape_class`` is the shape's TFA
    ``shape_class`` -- pass ``None`` when TFA is unavailable; simple entries
    then get plain, unreinterpreted quality (containers/bodies are
    unaffected, since their offsets depend only on record length).

    Returns ``None`` if ``payload`` is too short or ``entlen`` doesn't match
    a known non-egg record length (6, 10, 12, 13, 14, 18).
    """
    adj = 1 if extended else 0
    testlen = entlen - adj

    shape_frame = _decode_shape_frame(payload, extended)
    if shape_frame is None:
        return None
    shape, frame = shape_frame

    # Exult recomputes oflags fresh for every entry: gamemap.cc:940
    # `oflags = flags & ~(1 << Obj_flags::is_temporary)`.
    base_oflags = inherited_flags & ~U7ObjectFlags.TEMPORARY

    if testlen in (6, 10):
        fields = _decode_simple(payload, adj, testlen, extended_lift, base_oflags, shape_class)
    elif testlen in (12, 13, 14):
        fields = _decode_container_or_body(payload, adj, testlen, extended_lift)
    elif testlen == 18:
        fields = _decode_spellbook(payload, adj, extended_lift)
    else:
        fields = None

    if fields is None:
        return None

    # "Don't pass along invisibility!" -- gamemap.cc:1043, 1075.
    child_inherit_flags = fields.oflags & ~U7ObjectFlags.INVISIBLE

    return IregDecodedEntry(
        shape=shape,
        frame=frame,
        lift=fields.lift,
        quality=fields.quality,
        raw_quality=fields.raw_quality,
        object_flags=fields.oflags,
        raw_flag_byte=fields.raw_flag_byte,
        record_length=entlen,
        is_extended=extended,
        has_children_marker=fields.has_children_marker,
        child_inherit_flags=child_inherit_flags,
    )
