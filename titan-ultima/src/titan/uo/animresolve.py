"""Ultima Online animation resolution metadata."""

from __future__ import annotations

__all__ = [
    "UOAnimationResolution",
    "UOAnimationResolver",
    "UOAnimationSequence",
    "UOAnimationSequenceEntry",
    "animation_entry_index",
]

from dataclasses import dataclass
from pathlib import Path
import struct

from titan.uo.definfo import UODefFile
from titan.uo.uop import UOPArchive, hash_uop_path

_MAX_SEQUENCE_BODY = 2048
_MAX_ACTIONS = 68
_SET_BY_FILE_TYPE = {
    1: "anim",
    2: "anim2",
    3: "anim3",
    4: "anim4",
    5: "anim5",
    6: "anim6",
}


@dataclass(frozen=True)
class UOAnimationSequenceEntry:
    """One parsed AnimationSequence.uop body action-replacement table."""

    body: int
    replacements: tuple[int, ...]

    def resolve_action(self, action: int) -> int:
        if 0 <= action < len(self.replacements):
            return self.replacements[action]
        return action


class UOAnimationSequence:
    """Parsed AnimationSequence.uop replacement metadata."""

    def __init__(self, entries: dict[int, UOAnimationSequenceEntry]) -> None:
        self.entries = entries

    @classmethod
    def from_file(cls, path: str | Path) -> UOAnimationSequence:
        archive = UOPArchive(path)
        entries: dict[int, UOAnimationSequenceEntry] = {}
        for body in range(_MAX_SEQUENCE_BODY):
            virtual_path = f"build/animationsequence/{body:08d}.bin"
            entry = archive.entries_by_hash.get(hash_uop_path(virtual_path))
            if entry is None:
                continue
            sequence = _parse_sequence_entry(body, archive.read_entry(entry))
            if sequence is not None:
                entries[body] = sequence
        return cls(entries)


@dataclass(frozen=True)
class UOAnimationResolution:
    """Resolved effective animation lookup for a requested body/action/direction."""

    requested_body: int
    requested_action: int
    requested_direction: int
    bodydef_body: int
    bodydef_hue: int | None
    final_body: int
    final_file_type: int
    final_set: str
    final_action: int
    final_direction: int
    raw_entry: int
    uop_frame_path: str
    bodydef_applied: bool
    bodyconv_applied: bool
    sequence_applied: bool
    is_uop_sequence_body: bool


class UOAnimationResolver:
    """Resolve requested animation IDs through body.def/bodyconv/sequence metadata."""

    def __init__(
        self,
        *,
        defs: dict[str, UODefFile],
        sequence: UOAnimationSequence | None,
        mobtype_flags: dict[int, int],
    ) -> None:
        self.defs = defs
        self.sequence = sequence
        self.mobtype_flags = mobtype_flags

    def resolve(
        self,
        *,
        body: int,
        action: int,
        direction: int,
        preserve_hue: bool = False,
    ) -> UOAnimationResolution:
        bodydef_body = body
        bodydef_hue: int | None = None
        bodydef_applied = False
        if not preserve_hue:
            bodydef = self.defs.get("body.def")
            redirect = bodydef.redirects.get(body) if bodydef is not None else None
            if redirect is not None:
                bodydef_body = _def_target_body(redirect.targets)
                bodydef_hue = redirect.hue
                bodydef_applied = True

        final_body = bodydef_body
        file_type = 1
        bodyconv_applied = False
        bodyconv = self.defs.get("bodyconv.def")
        conversion = bodyconv.bodyconv.get(final_body) if bodyconv is not None else None
        if conversion is not None:
            for candidate_file_type, candidate_body in (
                (2, conversion.anim2),
                (3, conversion.anim3),
                (4, conversion.anim4),
                (5, conversion.anim5),
                (6, conversion.anim6),
            ):
                if candidate_body >= 0:
                    file_type = candidate_file_type
                    final_body = (
                        122
                        if candidate_file_type == 2 and candidate_body == 68
                        else candidate_body
                    )
                    bodyconv_applied = True
                    break

        sequence_entry = (
            self.sequence.entries.get(body) if self.sequence is not None else None
        )
        final_action = (
            sequence_entry.resolve_action(action)
            if sequence_entry is not None
            else action
        )
        sequence_applied = final_action != action
        raw_entry = animation_entry_index(
            body=final_body,
            action=final_action,
            direction=direction,
            file_type=file_type,
        )
        return UOAnimationResolution(
            requested_body=body,
            requested_action=action,
            requested_direction=direction,
            bodydef_body=bodydef_body,
            bodydef_hue=bodydef_hue,
            final_body=final_body,
            final_file_type=file_type,
            final_set=_SET_BY_FILE_TYPE[file_type],
            final_action=final_action,
            final_direction=direction,
            raw_entry=raw_entry,
            uop_frame_path=(
                f"build/animationlegacyframe/{body:06d}/{final_action:02d}.bin"
            ),
            bodydef_applied=bodydef_applied,
            bodyconv_applied=bodyconv_applied,
            sequence_applied=sequence_applied,
            is_uop_sequence_body=(self.mobtype_flags.get(body, 0) & 0x10000) != 0,
        )


def animation_entry_index(
    *, body: int, action: int, direction: int, file_type: int
) -> int:
    """Return the legacy anim*.idx entry for a body/action/direction."""
    if file_type == 3:
        if body < 300:
            base = body * 65
        elif body < 400:
            base = 33000 + (body - 300) * 110
        else:
            base = 35000 + (body - 400) * 175
    elif file_type == 2:
        if body < 200:
            base = body * 110
        else:
            base = 22000 + (body - 200) * 65
    elif file_type == 5 and body == 34:
        base = 22000 + (body - 200) * 65
    else:
        if body < 200:
            base = body * 110
        elif body < 400:
            base = 22000 + (body - 200) * 65
        else:
            base = 35000 + (body - 400) * 175
    return base + action * 5 + direction


def _def_target_body(targets: tuple[int, ...]) -> int:
    if len(targets) >= 3:
        return targets[2]
    if targets:
        return targets[0]
    return 0


def _parse_sequence_entry(
    fallback_body: int, data: bytes
) -> UOAnimationSequenceEntry | None:
    if len(data) < 56:
        return None
    body = struct.unpack_from("<I", data, 0)[0]
    pos = 4 + 48
    replaces = struct.unpack_from("<i", data, pos)[0]
    pos += 4

    replacements = list(range(_MAX_ACTIONS))
    if replaces in (48, 68):
        return UOAnimationSequenceEntry(body or fallback_body, tuple(replacements))

    if replaces < 0 or replaces > 10000:
        return None
    for _ in range(replaces):
        if pos + 72 > len(data):
            break
        old_group = struct.unpack_from("<i", data, pos)[0]
        frame_count = struct.unpack_from("<I", data, pos + 4)[0]
        new_group = struct.unpack_from("<i", data, pos + 8)[0]
        if frame_count == 0 and 0 <= old_group < _MAX_ACTIONS and new_group >= 0:
            replacements[old_group] = new_group
        pos += 72

    return UOAnimationSequenceEntry(body or fallback_body, tuple(replacements))
