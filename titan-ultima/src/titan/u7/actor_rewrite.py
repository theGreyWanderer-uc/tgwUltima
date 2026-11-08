"""Lossless, flavor-explicit actor header writing with bounded inventory/special framing."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

from titan.u7.actor_metadata import U7ActorMetadata
from titan.u7.ireg import decode_ireg_payload
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_specials import read_ireg_special
from titan.u7.ireg_tree import ireg_context_sha256
from titan.u7.save_repack import U7SaveReplacement, check_u7_save_hash, repack_u7_save
from titan.u7.save_container import read_u7_save_container

ActorFileKind = Literal["npc", "monsters"]
ActorSourceFlavor = Literal["runtime", "original-new-game"]


@dataclass(frozen=True)
class U7ActorWireRecord:
    """One complete actor record; the header, inventory and actor specials retain raw byte boundaries."""

    index: int
    offset: int
    header: bytes = field(repr=False)
    inventory: bytes = field(repr=False)
    specials: bytes = field(repr=False)

    @property
    def raw(self) -> bytes:
        return self.header + self.inventory + self.specials

    def as_row(self) -> dict[str, object]:
        return {
            "index": self.index,
            "offset": self.offset,
            "size": len(self.raw),
            "sha256": hashlib.sha256(self.raw).hexdigest(),
            "header_sha256": hashlib.sha256(self.header).hexdigest(),
            "header_hex": self.header.hex(),
            "inventory_bytes": len(self.inventory),
            "special_bytes": len(self.specials),
        }


@dataclass(frozen=True)
class U7ActorWireFile:
    """An explicit NPC or monster wrapper, complete actor records and retained trailing bytes."""

    prefix: bytes
    actors: tuple[U7ActorWireRecord, ...]
    trailing: bytes

    def to_bytes(self) -> bytes:
        return (
            self.prefix + b"".join(actor.raw for actor in self.actors) + self.trailing
        )


@dataclass(frozen=True)
class U7ActorHeaderEdit:
    """Edit one original actor ordinal using its complete-record hash; raw replacement covers all header bytes."""

    index: int
    expected_sha256: str
    fields: Mapping[str, int | str] = field(default_factory=dict)
    replacement_header: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class U7ActorRewriteResult:
    """Validated actor bytes, unchanged tails and source/output identity evidence."""

    data: bytes = field(repr=False)
    changes: tuple[dict[str, object], ...]
    source_sha256: str
    context_sha256: str

    def as_row(self) -> dict[str, object]:
        return {
            "source_sha256": self.source_sha256,
            "context_sha256": self.context_sha256,
            "output_sha256": hashlib.sha256(self.data).hexdigest(),
            "output_bytes": len(self.data),
            "changes": list(self.changes),
        }


def _number(value: object, name: str, low: int, high: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not low <= value <= high
    ):
        raise ValueError(f"Actor rewrite: {name} must be an integer in {low}..{high}")
    return value


def _inventory_end(
    data: bytes, start: int, context: U7IregContext, depth: int = 0
) -> int:
    if depth > 128:
        raise ValueError("Actor rewrite: inventory nesting exceeds 128")
    pos = start
    while pos < len(data):
        marker = data[pos]
        pos += 1
        if marker in (0, 1):
            return pos
        if marker == 2:
            pos += 2
        elif marker == 255:
            special, pos = read_ireg_special(data, pos - 1)
            if not special.complete or special.type_id == 2:
                raise ValueError(
                    "Actor rewrite: incomplete special or actor endmark inside inventory"
                )
        else:
            extended = marker == 254
            extended_lift = marker in (253, 254)
            if extended_lift:
                if pos == len(data):
                    raise ValueError(
                        "Actor rewrite: truncated extended inventory record"
                    )
                marker = data[pos]
                pos += 1
            end = pos + marker
            if end > len(data):
                raise ValueError("Actor rewrite: truncated inventory payload")
            length = marker - int(extended)
            if length in (6, 10, 12, 13, 14, 18):
                decoded = decode_ireg_payload(
                    data[pos:end],
                    entlen=marker,
                    extended=extended,
                    extended_lift=extended_lift,
                    context=context,
                )
                if decoded is None or decoded.context_warnings or decoded.kind == "egg":
                    raise ValueError(
                        "Actor rewrite: unresolved or unsupported inventory class"
                    )
                pos = (
                    _inventory_end(data, end, context, depth + 1)
                    if decoded.has_children_marker
                    else end
                )
            else:
                if extended_lift and marker < 4 + int(extended):
                    raise ValueError("Actor rewrite: invalid extended inventory length")
                pos = end
        if pos > len(data):
            raise ValueError("Actor rewrite: truncated inventory index")
    raise ValueError("Actor rewrite: missing inventory terminator")


def _header_end(data: bytes, start: int, flavor: ActorSourceFlavor) -> int:
    if len(data) - start < 117:
        raise ValueError("Actor rewrite: truncated actor header")
    delta = (
        1 + data[start + 78]
        if flavor == "runtime" and struct.unpack_from("<H", data, start + 4)[0] & 8
        else 0
    )
    end = start + 117 + delta
    if end > len(data):
        raise ValueError("Actor rewrite: truncated named function insertion")
    return end


def read_actor_wire_file(
    data: bytes,
    *,
    context: U7IregContext,
    kind: ActorFileKind = "npc",
    flavor: ActorSourceFlavor = "runtime",
) -> U7ActorWireFile:
    """Read exact actor boundaries with explicit BG/SI flavor; no heuristic source auto-detection."""
    if (
        context.game not in ("bg", "si")
        or kind not in ("npc", "monsters")
        or flavor not in ("runtime", "original-new-game")
    ):
        raise ValueError("Actor rewrite: invalid game, file kind or source flavor")
    if kind == "monsters" and flavor != "runtime":
        raise ValueError("Actor rewrite: monster streams require runtime flavor")
    size = 4 if kind == "npc" else 2
    if len(data) < size:
        raise ValueError("Actor rewrite: truncated actor count wrapper")
    count = (
        sum(struct.unpack_from("<HH", data))
        if kind == "npc"
        else struct.unpack_from("<H", data)[0]
    )
    pos = size
    actors = []
    compatibility = False
    for index in range(count):
        start = pos
        end = _header_end(data, start, flavor)
        header = data[start:end]
        iflag, used = (
            struct.unpack_from("<H", header, 4)[0],
            struct.unpack_from("<H", header, 14)[0],
        )
        if kind == "npc" and index == 0 and used == 0:
            compatibility = True
        unused = kind == "npc" and index > 0 and used == 0 and not compatibility
        has_contents = (
            bool(iflag & 1) if flavor == "runtime" else bool(iflag and not unused)
        )
        inventory_end = _inventory_end(data, end, context) if has_contents else end
        pos = inventory_end
        if flavor == "runtime" and iflag & 2:
            while pos < len(data) and data[pos] == 255:
                special, pos = read_ireg_special(data, pos)
                if not special.complete:
                    raise ValueError("Actor rewrite: truncated actor special")
                if special.type_id == 2:
                    break
        actors.append(
            U7ActorWireRecord(
                index, start, header, data[end:inventory_end], data[inventory_end:pos]
            )
        )
    result = U7ActorWireFile(data[:size], tuple(actors), data[pos:])
    if result.to_bytes() != data:
        raise ValueError("Actor rewrite: lossless reconstruction mismatch")
    return result


# Offset, byte width, signedness; raw wire names avoid inventing runtime side effects.
_HEADER_FIELDS: dict[str, tuple[int, int, bool]] = {
    "x_byte": (0, 1, False),
    "y_byte": (1, 1, False),
    "shape_word": (2, 2, False),
    "iflag1": (4, 2, False),
    "superchunk": (6, 1, False),
    "map_num": (7, 1, False),
    "usecode_lift_word": (8, 2, False),
    "health": (10, 1, True),
    "used_in_game": (14, 2, False),
    "rflags": (16, 2, False),
    "strength_byte": (18, 1, False),
    "dexterity": (19, 1, False),
    "intelligence_byte": (20, 1, False),
    "combat_byte": (21, 1, False),
    "schedule_type": (22, 1, False),
    "attack_byte": (23, 1, False),
    "effective_alignment": (24, 1, False),
    "magic_marker": (25, 1, False),
    "mana_byte": (26, 1, False),
    "magic_temperature_byte": (27, 1, False),
    "flags3": (28, 1, False),
    "face_num": (29, 2, False),
    "experience": (32, 4, False),
    "training": (36, 1, False),
    "oppressor": (41, 2, True),
    "schedule_x": (47, 2, False),
    "schedule_y": (49, 2, False),
    "type_flags": (51, 2, False),
    "next_schedule": (58, 1, False),
    "shape16": (64, 2, False),
    "polymorph_shape": (66, 2, True),
    "flags": (68, 4, False),
    "schedule_z": (72, 1, False),
    "flags2": (74, 4, False),
}
_RUNTIME_FIELDS = {
    "map_num",
    "effective_alignment",
    "magic_marker",
    "mana_byte",
    "face_num",
    "oppressor",
    "schedule_z",
    "shape16",
    "polymorph_shape",
    "flags",
    "flags2",
    "next_schedule",
}


def rewrite_actor_header(
    header: bytes,
    fields: Mapping[str, int | str],
    *,
    context: U7IregContext,
    flavor: ActorSourceFlavor = "runtime",
    npc_num: int = 0,
) -> bytes:
    """Patch all documented header fields while preserving unknown bytes and disjoint packed bits."""
    if _header_end(header, 0, flavor) != len(header):
        raise ValueError("Actor rewrite: replacement must contain exactly one header")
    raw = bytearray(header)
    original_iflag = struct.unpack_from("<H", raw, 4)[0]
    delta = len(header) - 117
    touched: dict[int, int] = {}

    def write(offset: int, width: int, value: int, mask: int | None = None) -> None:
        mask = (1 << (8 * width)) - 1 if mask is None else mask
        for index in range(width):
            bits = mask >> (index * 8) & 255
            if touched.get(offset + index, 0) & bits:
                raise ValueError("Actor rewrite: overlapping header field edits")
            touched[offset + index] = touched.get(offset + index, 0) | bits
        current = int.from_bytes(raw[offset : offset + width], "little")
        raw[offset : offset + width] = ((current & ~mask) | (value & mask)).to_bytes(
            width, "little"
        )

    for name, value in fields.items():
        if name in ("usecode_name_hex", "name_hex", "name"):
            continue
        if flavor != "runtime" and name in _RUNTIME_FIELDS | {"extended_skin"}:
            raise ValueError(
                "Actor rewrite: runtime extension edit requested for original-new-game flavor"
            )
        if name in _HEADER_FIELDS:
            offset, width, signed = _HEADER_FIELDS[name]
            number = _number(
                value,
                name,
                -(1 << (8 * width - 1)) if signed else 0,
                (1 << (8 * width - int(signed))) - 1,
            )
            write(offset, width, number & ((1 << (width * 8)) - 1))
        elif name in (
            "strength",
            "intelligence",
            "combat",
            "frame",
            "shape",
            "lift",
            "usecode",
            "alignment",
            "attack_mode",
        ):
            offset, width, mask, shift = {
                "strength": (18, 1, 31 if context.game == "si" else 63, 0),
                "intelligence": (20, 1, 31, 0),
                "combat": (21, 1, 127, 0),
                "frame": (2, 2, 0xFC00, 10),
                "shape": (2, 2, 1023, 0),
                "lift": (8, 2, 0xF000, 12),
                "usecode": (8, 2, 4095, 0),
                "alignment": (16, 2, 24, 3),
                "attack_mode": (23, 1, 15, 0),
            }[name]
            write(offset, width, _number(value, name, 0, mask >> shift) << shift, mask)
        elif name in ("food", "extended_skin"):
            offset = (93 if name == "food" else 78) + delta
            number = _number(
                value,
                name,
                -128 if name == "food" else 0,
                127 if name == "food" else 255,
            )
            write(offset, 1, number & 255)
        else:
            raise ValueError(f"Actor rewrite: unsupported header field {name}")
    if "name" in fields and "name_hex" in fields:
        raise ValueError("Actor rewrite: name and name_hex conflict")
    if "name" in fields or "name_hex" in fields:
        value = fields["name"] if "name" in fields else fields["name_hex"]
        if not isinstance(value, str):
            raise ValueError("Actor rewrite: name must be text or hex text")
        try:
            actor_name = (
                value.encode("latin-1") if "name" in fields else bytes.fromhex(value)
            )
        except (ValueError, UnicodeError) as error:
            raise ValueError("Actor rewrite: name encoding is invalid") from error
        if len(actor_name) > 16 or "name_hex" in fields and len(actor_name) != 16:
            raise ValueError(
                "Actor rewrite: name needs at most 16 bytes; name_hex needs exactly 16"
            )
        raw[101 + delta : 117 + delta] = actor_name.ljust(16, b"\0")
    if "usecode_name_hex" in fields:
        value = fields["usecode_name_hex"]
        if flavor != "runtime" or not isinstance(value, str):
            raise ValueError("Actor rewrite: named functions require runtime hex text")
        try:
            function_name = bytes.fromhex(value)
        except ValueError as error:
            raise ValueError("Actor rewrite: invalid named function hex") from error
        if len(function_name) > 255 or b"\0" in function_name:
            raise ValueError(
                "Actor rewrite: function name must be 0..255 non-NUL bytes"
            )
        if "iflag1" in fields:
            raise ValueError(
                "Actor rewrite: named function and raw iflag1 edit conflict"
            )
        raw[78 : 78 + delta] = (
            bytes([len(function_name)]) + function_name if function_name else b""
        )
        iflag = struct.unpack_from("<H", raw, 4)[0]
        struct.pack_into(
            "<H", raw, 4, (iflag | 8) & ~4 if function_name else iflag & ~8
        )
    result = bytes(raw)
    new_iflag = struct.unpack_from("<H", result, 4)[0]
    if (
        flavor == "runtime"
        and new_iflag & 3 != original_iflag & 3
        or flavor != "runtime"
        and bool(new_iflag) != bool(original_iflag)
    ):
        raise ValueError(
            "Actor rewrite: header edits cannot change inventory/special framing"
        )
    if (
        flavor == "runtime"
        and bool(new_iflag & 8) != bool(original_iflag & 8)
        and "usecode_name_hex" not in fields
    ):
        raise ValueError(
            "Actor rewrite: named-function flag changes require usecode_name_hex"
        )
    if _header_end(result, 0, flavor) != len(result):
        raise ValueError("Actor rewrite: header size does not match insertion flags")
    U7ActorMetadata.from_bytes(
        result,
        game=context.game,
        original_new_game=flavor != "runtime",
        npc_num=npc_num,
        health=struct.unpack_from("<b", result, 10)[0],
        strength=result[18] & (31 if context.game == "si" else 63),
    )
    return result


def rewrite_actor_file(
    data: bytes,
    edits: Iterable[U7ActorHeaderEdit],
    *,
    context: U7IregContext,
    kind: ActorFileKind = "npc",
    flavor: ActorSourceFlavor = "runtime",
    expected_sha256: str,
    expected_context_sha256: str,
) -> U7ActorRewriteResult:
    """Write guarded actor headers; preserve count groups, all inventory/special bytes and trailing data."""
    check_u7_save_hash(expected_sha256, data, "actor source")
    digest = ireg_context_sha256(context)
    if (
        not isinstance(expected_context_sha256, str)
        or expected_context_sha256.lower() != digest
    ):
        raise ValueError("Actor rewrite: dispatch context SHA-256 does not match")
    parsed = read_actor_wire_file(data, context=context, kind=kind, flavor=flavor)
    replacements: dict[int, bytes] = {}
    changes: list[dict[str, object]] = []
    for edit in edits:
        index = _number(edit.index, "actor index", 0, len(parsed.actors) - 1)
        if (
            index in replacements
            or bool(edit.fields) + (edit.replacement_header is not None) != 1
        ):
            raise ValueError(
                "Actor rewrite: duplicate actor or expected exactly one header operation"
            )
        actor = parsed.actors[index]
        check_u7_save_hash(edit.expected_sha256, actor.raw, "actor record")
        header = rewrite_actor_header(
            edit.replacement_header
            if edit.replacement_header is not None
            else actor.header,
            edit.fields,
            context=context,
            flavor=flavor,
            npc_num=index if kind == "npc" else -1,
        )
        old_flag, new_flag = (
            struct.unpack_from("<H", actor.header, 4)[0],
            struct.unpack_from("<H", header, 4)[0],
        )
        if (
            flavor == "runtime"
            and old_flag & 3 != new_flag & 3
            or flavor != "runtime"
            and bool(old_flag) != bool(new_flag)
        ):
            raise ValueError(
                "Actor rewrite: replacement header changes actor-tail framing"
            )
        replacements[index] = header
        changes.append(
            {
                "index": index,
                "offset": actor.offset,
                "before_header_hex": actor.header.hex(),
                "after_header_hex": header.hex(),
            }
        )
    output = (
        parsed.prefix
        + b"".join(
            replacements.get(actor.index, actor.header)
            + actor.inventory
            + actor.specials
            for actor in parsed.actors
        )
        + parsed.trailing
    )
    reread = read_actor_wire_file(output, context=context, kind=kind, flavor=flavor)
    if (
        reread.prefix != parsed.prefix
        or reread.trailing != parsed.trailing
        or len(reread.actors) != len(parsed.actors)
    ):
        raise ValueError("Actor rewrite: output actor wrapper changed")
    for before, after in zip(parsed.actors, reread.actors, strict=True):
        if (
            after.header != replacements.get(before.index, before.header)
            or after.inventory != before.inventory
            or after.specials != before.specials
        ):
            raise ValueError(
                "Actor rewrite: output header/inventory/special validation failed"
            )
    for change in changes:
        change["output_offset"] = reread.actors[cast(int, change["index"])].offset
    return U7ActorRewriteResult(
        output, tuple(changes), hashlib.sha256(data).hexdigest(), digest
    )


def read_actor_save_member(
    data: bytes, path: tuple[int, ...], *, kind: ActorFileKind
) -> bytes:
    """Select a named NPC.DAT/MONSNPCS.DAT occurrence without collapsing duplicate names."""
    if not isinstance(path, tuple) or not 1 <= len(path) <= 16:
        raise ValueError("Actor rewrite: member path must contain 1..16 indices")
    for index in path:
        archive = read_u7_save_container(data, strict=True)
        _number(index, "member index", 0, len(archive.members) - 1)
        member = archive.members[index]
        if member.is_directory:
            raise ValueError("Actor rewrite: directory is not an actor member")
        data = member.data
    if member.name.replace("\\", "/").split("/")[-1].casefold() != (
        "npc.dat" if kind == "npc" else "monsnpcs.dat"
    ):
        raise ValueError("Actor rewrite: save leaf name does not match actor file kind")
    return data


def rewrite_actor_save(
    data: bytes,
    path: tuple[int, ...],
    edits: Iterable[U7ActorHeaderEdit],
    *,
    context: U7IregContext,
    kind: ActorFileKind,
    flavor: ActorSourceFlavor,
    expected_save_sha256: str,
    expected_sha256: str,
    expected_context_sha256: str,
) -> tuple[bytes, dict[str, object]]:
    """Validate actor headers before embedding their exact occurrence in a new save archive."""
    check_u7_save_hash(expected_save_sha256, data, "save source")
    member = read_actor_save_member(data, path, kind=kind)
    result = rewrite_actor_file(
        member,
        edits,
        context=context,
        kind=kind,
        flavor=flavor,
        expected_sha256=expected_sha256,
        expected_context_sha256=expected_context_sha256,
    )
    packed = repack_u7_save(
        data,
        [U7SaveReplacement(path, result.data, expected_sha256)],
        expected_sha256=expected_save_sha256,
    )
    return packed.data, {"actor_edit": result.as_row(), "save_repack": packed.as_row()}
