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

Class dispatch needs TFA and the supplemental body/jawbone flags. Without
those inputs, legacy length-based decoding is explicitly marked inferred.
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

from dataclasses import dataclass, field
from enum import IntFlag
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from titan.u7.ireg_metadata import U7IregContext

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
    kind: str = "unknown"
    class_data: dict[str, object] = field(default_factory=dict)
    context_warnings: list[str] = field(default_factory=list)
    raw_hex: str = ""


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
    payload: bytes,
    adj: int,
    testlen: int,
    extended_lift: bool,
    oflags: U7ObjectFlags,
    shape_class: int | None,
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
    payload: bytes,
    adj: int,
    testlen: int,
    extended_lift: bool,
) -> _EntryFields | None:
    extbody = 1 if testlen == 13 else 0  # 12 (container) has no extbody variant
    if len(payload) <= 11 + adj + extbody:
        return None
    type_val = payload[4 + adj] + payload[5 + adj] * 256
    lift = read_lift(payload[9 + adj + extbody], extended_lift)
    raw_quality = payload[7 + adj]
    raw_flag_byte = payload[11 + adj + extbody]
    oflags = get_quality_flags(raw_flag_byte)
    return _EntryFields(
        lift, raw_quality, raw_quality, raw_flag_byte, oflags, type_val != 0
    )


def _decode_spellbook(
    payload: bytes, adj: int, extended_lift: bool
) -> _EntryFields | None:
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
    is_body: bool | None = None,
    is_jawbone: bool | None = None,
    game: str = "bg",
    context: U7IregContext | None = None,
) -> IregDecodedEntry | None:
    """
    Decode one IREG entry, retaining class-specific state and unknown bytes.

    ``payload`` is the raw ``entlen``-byte entry body (before any pointer
    shift). ``extended`` is True for 2-byte shape numbers (``IREG_EXTENDED``,
    wire marker 254); ``extended_lift`` is True whenever the entry was
    prefixed by either extended-marker byte (254 or 253), since both widen
    the lift field the same way. ``shape_class`` is the shape's TFA
    ``shape_class`` -- pass ``None`` when TFA is unavailable; simple entries
    then get plain, unreinterpreted quality. ``context`` supplies TFA and
    supplemental flags and overrides the individual class/game arguments.

    Returns ``None`` if ``payload`` is too short or ``entlen`` doesn't match
    a known non-egg record length (6, 10, 12, 13, 14, 18).
    """
    adj = 1 if extended else 0
    testlen = entlen - adj
    if len(payload) < entlen or testlen not in (6, 10, 12, 13, 14, 18):
        return None

    shape_frame = _decode_shape_frame(payload, extended)
    if shape_frame is None:
        return None
    shape, frame = shape_frame
    if context is not None:
        entry = context.tfa.get(shape) if context.tfa is not None else None
        shape_class = entry.shape_class if entry is not None else None
        is_body = context.bodies.get(shape, False if context.bodies_complete else None)
        is_jawbone = context.jawbones.get(
            shape, False if context.jawbones_complete else None
        )
        game = context.game
    if game.lower() not in ("bg", "si"):
        raise ValueError("IREG game must be bg or si")
    warnings: list[str] = []
    details: dict[str, object] = {}
    if shape_class is None:
        warnings.append(
            "TFA class unavailable; dispatch and quality interpretation may be incomplete"
        )
        if shape == 275 and testlen in (12, 14):
            shape_class = 7
            warnings.append("Egg class inferred from conventional shape 275")
    kind = "simple"

    # Exult recomputes oflags fresh for every entry: gamemap.cc:940
    # `oflags = flags & ~(1 << Obj_flags::is_temporary)`.
    base_oflags = inherited_flags & ~U7ObjectFlags.TEMPORARY
    fields: _EntryFields | None

    if shape_class == 7:
        if testlen not in (12, 14):
            return None

        def word(offset: int) -> int:
            return int.from_bytes(payload[offset + adj : offset + adj + 2], "little")

        kind = "egg"
        details = {
            "type_word": word(4),
            "probability": payload[6 + adj],
            "data1": word(7),
            "data2": word(10),
            "data3": word(12) if testlen == 14 else None,
        }
        fields = _EntryFields(
            read_lift(payload[9 + adj], extended_lift),
            0,
            0,
            None,
            U7ObjectFlags.NONE,
            False,
        )
    elif testlen in (6, 10):
        fields = _decode_simple(
            payload, adj, testlen, extended_lift, base_oflags, shape_class
        )
    elif is_body is True or (is_body is None and testlen in (13, 14)):
        kind = "body"
        if is_body is None:
            warnings.append("Body flag unavailable; body layout inferred from length")
        fields = _decode_container_or_body(payload, adj, testlen, extended_lift)
        if fields is not None:
            extbody = testlen == 13
            npc = -1
            if fields.quality == 1 and (
                extbody or payload[8 + adj] >= 128 or game.lower() == "si"
            ):
                npc = (
                    int.from_bytes(payload[8 + adj : 10 + adj], "little")
                    if extbody
                    else ((payload[8 + adj] - 128) & 255)
                )
            details = {
                "npc_number": npc if npc != 0 else -1,
                "type_word": int.from_bytes(payload[4 + adj : 6 + adj], "little"),
                "extended_body": extbody,
            }
    elif testlen == 12:
        fields = _decode_container_or_body(payload, adj, testlen, extended_lift)
        kind = "container"
        details = {
            "type_word": int.from_bytes(payload[4 + adj : 6 + adj], "little"),
            "resistance": payload[10 + adj],
        }
        if is_body is None:
            warnings.append(
                "Body flag unavailable; 12-byte body/container dispatch unresolved"
            )
        if shape_class == 11:
            kind = "virtue_stone"
            details = {
                "target_x": (payload[6 + adj] % 12) * 256 + payload[4 + adj],
                "target_y": (payload[6 + adj] // 12) * 256 + payload[5 + adj],
                "target_lift": payload[7 + adj],
                "target_map": payload[10 + adj],
            }
            if fields is not None:
                fields.has_children_marker = False
        elif shape_class == 9:
            kind = "barge"
            details = {
                "width": payload[4 + adj],
                "height": payload[5 + adj],
                "direction": (payload[7 + adj] >> 1) & 3,
                "moving": bool(payload[7 + adj] & 8),
            }
        elif is_jawbone is True:
            kind = "jawbone"
        elif is_jawbone is None:
            warnings.append("Jawbone flag unavailable; container subtype unresolved")
    elif testlen == 18 and shape_class in (8, None):
        kind = "spellbook"
        fields = _decode_spellbook(payload, adj, extended_lift)
        if fields is not None:
            fields.oflags = base_oflags
        details = {
            "circles": list(payload[4 + adj : 9 + adj] + payload[10 + adj : 14 + adj]),
            "bookmark": payload[17 + adj],
            "unknown_hex": payload[14 + adj : 17 + adj].hex(),
        }
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
        kind=kind,
        class_data=details,
        context_warnings=warnings,
        raw_hex=payload[:entlen].hex(),
    )
