"""Saved actor extensions and source-derived load-time status/appearance inspection."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, cast

if TYPE_CHECKING:
    from titan.u7.avatar_metadata import U7AvatarMetadata


@dataclass(frozen=True)
class U7ActorMetadata:
    """Retain raw actor extension fields; runtime lookups and appearance overrides stay explicit."""

    raw_hex: str
    game: str
    original_new_game: bool
    npc_num: int
    iflag1: int
    usecode_lift_raw: int
    flags_raw: int
    flags2_raw: int
    effective_flags: int
    shape16: int
    polymorph_shape: int
    extended_skin_raw: int
    skin: int | None
    usecode_name: str
    usecode_name_raw_hex: str
    schedule_x: int
    schedule_y: int
    schedule_z: int
    next_schedule: int
    combat_protected: bool
    user_set_attack: bool
    health_death_correction: bool
    has_usecode: bool | None = None

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        game: str,
        original_new_game: bool,
        npc_num: int,
        health: int,
        strength: int,
        has_usecode: bool | None = None,
    ) -> U7ActorMetadata:
        if len(raw) < 117:
            raise ValueError("U7 actor metadata: fixed actor prefix is incomplete")
        iflag = struct.unpack_from("<H", raw, 4)[0]
        pos = 78
        name = b""
        if not original_new_game and iflag & 8:
            size = raw[pos]
            pos += 1
            if pos + size + 39 > len(raw):
                raise ValueError(
                    "U7 actor metadata: named-function insertion is incomplete"
                )
            name = raw[pos : pos + size]
            pos += size
        skin_raw = raw[pos]
        flags, flags2 = (
            struct.unpack_from("<I", raw, 68)[0],
            struct.unpack_from("<I", raw, 74)[0],
        )
        rflags = struct.unpack_from("<H", raw, 16)[0]
        shape16 = struct.unpack_from("<H", raw, 64)[0]
        polymorph = struct.unpack_from("<h", raw, 66)[0]
        effective = 0
        for legacy, modern in (
            (7, 1),
            (8, 2),
            (9, 3),
            (10, 10),
            (11, 6),
            (12, 7),
            (13, 8),
            (14, 9),
        ):
            if rflags & (1 << legacy):
                effective |= 1 << modern
        if not original_new_game:
            if rflags & (1 << 6):
                effective |= 1 << 18
            if rflags & (1 << 15):
                effective |= 1 << 4
        if raw[20] & 32:
            effective |= 1 << 34
        if raw[20] & 64:
            effective |= 1 << 29
        poly = bool(raw[20] & 128)
        if not original_new_game and shape16 and polymorph == shape16 and npc_num != 0:
            poly = False
        if poly:
            effective |= 1 << 32
        if raw[21] & 128:
            effective |= 1 << 35
        if game == "si" and raw[18] & 128:
            effective |= 1 << 37
        flags3 = raw[28] if original_new_game or not raw[25] else raw[28] & 7
        if npc_num == 0 and (original_new_game or not raw[25]):
            flags3 = 1
        for legacy, modern in ((0, 28), (1, 31), (2, 30)):
            if flags3 & (1 << legacy):
                effective |= 1 << modern
        dying = npc_num > 0 and health < -(strength // 3)
        if dying:
            effective |= 1 << 4
        if not original_new_game:
            effective |= flags | ((flags2 & ~1) << 32)
        skin = None
        if not original_new_game and iflag & 16:
            skin = skin_raw
        elif npc_num == 0:
            skin = (((raw[18] >> 6) - 1) & 3) if game == "bg" else ((raw[18] >> 5) & 3)
        return cls(
            raw.hex(),
            game,
            original_new_game,
            npc_num,
            iflag,
            struct.unpack_from("<H", raw, 8)[0],
            flags,
            flags2,
            effective,
            shape16,
            polymorph,
            skin_raw,
            skin,
            name.split(b"\0", 1)[0].decode("latin-1"),
            name.hex(),
            struct.unpack_from("<H", raw, 47)[0],
            struct.unpack_from("<H", raw, 49)[0],
            raw[72] if not original_new_game else 0,
            raw[58],
            bool(raw[23] & 16),
            bool(raw[23] & 32),
            dying,
            has_usecode,
        )

    @property
    def is_dead(self) -> bool:
        """Apply the legacy, extended and non-Avatar health correction used during actor loading."""
        return bool(self.effective_flags & (1 << 4))

    def resolve_usecode(self, symbols: Mapping[str, int] | None = None) -> int | None:
        """Resolve stored numeric/default bindings or a named function with supplied symbols."""
        if not self.original_new_game and self.iflag1 & 8:
            return symbols.get(self.usecode_name) if symbols is not None else None
        if 0 <= self.npc_num < 256:
            return 0x400 + self.npc_num
        value = self.usecode_lift_raw & 4095
        assigned = not self.original_new_game and bool(self.iflag1 & 4)
        if value == 4095:
            return None
        return (
            value
            if assigned or self.has_usecode or value == 0x400 + self.npc_num
            else None
        )

    def appearance(
        self,
        stored_shape: int,
        *,
        avatar_shape: int | None = None,
        polymorph_shapes: Mapping[int, int] | None = None,
        avatar_metadata: U7AvatarMetadata | None = None,
        have_si_shapes: bool | None = None,
        avatar_skin: int | None = None,
        avatar_female: bool | None = None,
        avatar_sex_known: bool = True,
    ) -> dict[str, object]:
        """Resolve supplied static Avatar metadata; keep unavailable runtime inputs explicit."""
        required: list[str] = []
        avatar_resolution: dict[str, object] | None = None
        if self.npc_num == 0 and avatar_shape is None and avatar_metadata is not None:
            raw = bytes.fromhex(self.raw_hex)
            female = bool(int.from_bytes(raw[51:53], "little") & (1 << 9))
            if self.original_new_game:
                female = not female
            avatar_resolution = avatar_metadata.resolve_shape(
                skin=self.skin if avatar_skin is None else avatar_skin,
                female=(female if avatar_sex_known else None)
                if avatar_female is None
                else avatar_female,
                naked=bool(self.effective_flags & (1 << 38)),
                have_si_shapes=have_si_shapes,
            )
            value = avatar_resolution["resolved_shape"]
            avatar_shape = value if isinstance(value, int) else None
            required.extend(cast(list[str], avatar_resolution["required_context"]))
        shape = (
            avatar_shape
            if self.npc_num == 0 and avatar_shape is not None
            else stored_shape
        )
        needs_context = self.npc_num == 0 and avatar_shape is None
        if needs_context and not required:
            required.append("avatar_shape_or_metadata")
        polymorph_needs_context = bool(self.effective_flags & (1 << 32)) and (
            self.original_new_game or not self.shape16
        )
        if polymorph_needs_context:
            if self.game == "bg" or self.npc_num in (0, 28):
                if self.npc_num == 28:
                    if avatar_shape is not None:
                        shape = avatar_shape
                        needs_context = polymorph_needs_context = False
                        required.clear()
                    else:
                        required.append("main_avatar_appearance")
                else:
                    # This fallback runs before saved flags2 are ORed in actorio.cc.
                    shape = 658 if bytes.fromhex(self.raw_hex)[21] & 128 else 530
                    needs_context = polymorph_needs_context = False
                    required.clear()
            else:
                # SI set_polymorph_default is a no-op for actors other than 0 and 28.
                polymorph_needs_context = False
        if (
            self.effective_flags & (1 << 32)
            and self.shape16
            and not self.original_new_game
        ):
            target = self.polymorph_shape
            if polymorph_shapes is not None and target in polymorph_shapes:
                shape = polymorph_shapes[target]
                needs_context = False
                required.clear()
            elif (
                avatar_metadata is not None
                and target in avatar_metadata.base_shapes.values()
            ):
                if avatar_shape is not None:
                    shape = avatar_shape
                else:
                    polymorph_needs_context = True
                    required.append("main_avatar_appearance")
            else:
                shape = target
                # Without Avatar metadata a logical Avatar target cannot be excluded.
                if avatar_metadata is None:
                    polymorph_needs_context = True
                    required.append("polymorph_avatar_mapping")
                else:
                    needs_context = False
                    required.clear()
        if polymorph_needs_context and not required:
            required.append("polymorph_default_state")
        return {
            "shape": shape,
            "stored_shape": stored_shape,
            "polymorph_shape": self.polymorph_shape,
            "skin": self.skin,
            "avatar_context_required": needs_context,
            "polymorph_context_required": polymorph_needs_context,
            "required_context": required,
            "avatar_resolution": avatar_resolution,
            "interpretation": "exult_load",
            "resolved_shape": None
            if needs_context or polymorph_needs_context
            else shape,
        }

    def as_row(self) -> dict[str, object]:
        """Export raw extensions alongside resolved status and the unresolved named-binding distinction."""
        return {
            "flags_raw": self.flags_raw,
            "flags2_raw": self.flags2_raw,
            "effective_flags": self.effective_flags,
            "polymorph_shape": self.polymorph_shape,
            "extended_skin_raw": self.extended_skin_raw,
            "skin": self.skin,
            "usecode_name": self.usecode_name,
            "usecode_name_raw_hex": self.usecode_name_raw_hex,
            "resolved_usecode": self.resolve_usecode(),
            "schedule_x": self.schedule_x,
            "schedule_y": self.schedule_y,
            "schedule_z": self.schedule_z,
            "next_schedule": self.next_schedule,
            "health_death_correction": self.health_death_correction,
        }
