"""Movement controller processes and their per-creature extensions."""

from __future__ import annotations

__all__ = [
    "U9MovementControllerState",
    "U9FlyingMovementState",
    "U9HumanoidMovementFields",
    "U9AvatarMovementFields",
    "U9AvatarMovementTailFields",
    "U9BruteMovementFields",
    "U9NpcMovementFields",
    "U9SpiderMovementFields",
    "U9SwimmingMovementFields",
    "U9MovementExtensionFields",
    "U9MovementExtensionState",
    "U9MovementControllerProcessState",
]

import struct
from dataclasses import dataclass
from typing import Union

from titan.u9.process_data._base import (
    FLYING_MOVEMENT_CONTROLLER_PROCESS_TYPES,
    MOVEMENT_CONTROLLER_PROCESS_TYPES,
    U9ProcessDataError,
    U9ProcessHeaderState,
    U9ProcessWorldState,
    _require_bytes,
    _validate_byte_boolean,
    _validate_finite,
    _validate_object_reference_index,
)


# Controller-specific blocks around the base save, as (leading, trailing)
# (kind, size) lists in stream order. Leading blocks are written before the
# routine calls its parent, so they sit between the type word and the common
# header; trailing blocks follow the base block. Retail routines: humanoid
# 0x004BB900 (10 leading), NPC 0x004F53C0 (12 trailing), Avatar 0x004188E0
# (35 leading, 1 trailing, around the humanoid save), brute 0x0042FF10
# (8 leading before the humanoid save), spider 0x0053ECD0 (12 trailing),
# swimming 0x005415D0 (68 trailing); skeleton 0x00527D00, ghost 0x004A7410,
# lich 0x004D58A0 and zombie 0x005C26B0 only delegate.
_HUMANOID = ("humanoid", 10)
MOVEMENT_CONTROLLER_EXTENSIONS: dict[
    int, tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]
] = {
    85: ((_HUMANOID,), ()),
    96: ((_HUMANOID,), ()),
    97: ((_HUMANOID,), ()),
    95: ((("brute", 8), _HUMANOID), ()),
    166: ((("avatar", 35), _HUMANOID), (("avatar_tail", 1),)),
    86: ((), (("npc", 12),)),
    176: ((), (("npc", 12),)),
    155: ((), (("spider", 12),)),
    87: ((), (("swimming", 68),)),
    168: ((), (("swimming", 68),)),
    170: ((), (("swimming", 68),)),
    171: ((), (("swimming", 68),)),
    173: ((), ()),
    174: ((), ()),
    211: ((), ()),
}
MOVEMENT_CONTROLLER_VERSION = 1
MOVEMENT_CONTROLLER_STATE_SIZE = 1394
MOVEMENT_CONTROLLER_REFERENCE_OFFSETS = (40, 48)
FLYING_MOVEMENT_STATE = struct.Struct("<2f5ii5ii2I")
HUMANOID_MOVEMENT_VERSION = 2
HUMANOID_MOVEMENT_STATE = struct.Struct("<iiBB")
AVATAR_MOVEMENT_VERSION = 3
AVATAR_MOVEMENT_STATE = struct.Struct("<iiiiBBBiiii")
AVATAR_MOVEMENT_TAIL_STATE = struct.Struct("<B")
BRUTE_MOVEMENT_VERSION = 1
BRUTE_MOVEMENT_STATE = struct.Struct("<ii")
NPC_MOVEMENT_STATE = struct.Struct("<iII")
SPIDER_MOVEMENT_STATE = struct.Struct("<iII")
SWIMMING_MOVEMENT_STATE = struct.Struct("<3f5ii5ii2I")


@dataclass(frozen=True)
class U9MovementControllerState:
    """The fixed base block every movement controller saves after its world state.

    The retail base save (``0x00579B80``) writes 1,394 bytes: a version word,
    fields for movement capability, state, collision, shadow, travel, speed,
    cylinder and animation tables, and two object references at ``+40`` and
    ``+48``. Only the version and the two references are typed; ``raw``
    keeps the complete block. The two references are written only while a
    global save-mode flag is clear, which holds for every trusted save; a save
    written with it set would store a block 8 bytes shorter.
    """

    version: int
    object_reference_indices: tuple[int, int]
    raw: bytes
    offset: int

    @property
    def end_offset(self) -> int:
        return self.offset + MOVEMENT_CONTROLLER_STATE_SIZE

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9MovementControllerState:
        _require_bytes(
            data, offset, MOVEMENT_CONTROLLER_STATE_SIZE, "movement-controller state"
        )
        (version,) = struct.unpack_from("<i", data, offset)
        if version != MOVEMENT_CONTROLLER_VERSION:
            raise U9ProcessDataError(
                f"unsupported movement-controller version {version} at 0x{offset:X}"
            )
        references = tuple(
            struct.unpack_from("<i", data, offset + relative)[0]
            for relative in MOVEMENT_CONTROLLER_REFERENCE_OFFSETS
        )
        for index in references:
            _validate_object_reference_index(
                index, object_reference_count, "movement-controller"
            )
        return cls(
            version=version,
            object_reference_indices=references,  # type: ignore[arg-type]
            raw=bytes(data[offset : offset + MOVEMENT_CONTROLLER_STATE_SIZE]),
            offset=offset,
        )


@dataclass(frozen=True)
class U9FlyingMovementState:
    """The 64-byte extension the flying movement save (``0x00494290``) adds."""

    ceiling_altitude: float
    floor_altitude: float
    fall_animation_ids: tuple[int, int, int, int, int]
    fall_animation_count: int
    death_animation_ids: tuple[int, int, int, int, int]
    death_animation_count: int
    reserved: tuple[int, int]
    offset: int

    @property
    def end_offset(self) -> int:
        return self.offset + FLYING_MOVEMENT_STATE.size

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9FlyingMovementState:
        _require_bytes(
            data, offset, FLYING_MOVEMENT_STATE.size, "flying movement state"
        )
        values = FLYING_MOVEMENT_STATE.unpack_from(data, offset)
        _validate_finite(values[0:2], "flying movement altitude")
        return cls(
            ceiling_altitude=values[0],
            floor_altitude=values[1],
            fall_animation_ids=tuple(values[2:7]),  # type: ignore[arg-type]
            fall_animation_count=values[7],
            death_animation_ids=tuple(values[8:13]),  # type: ignore[arg-type]
            death_animation_count=values[13],
            reserved=tuple(values[14:16]),  # type: ignore[arg-type]
            offset=offset,
        )


@dataclass(frozen=True)
class U9HumanoidMovementFields:
    """The 10-byte humanoid block (``0x004BB900``), written before the header."""

    version: int
    lava_timer: int
    wearing_infernal_armor: bool
    leaves_footprints: bool

    @classmethod
    def from_raw(cls, raw: bytes) -> U9HumanoidMovementFields:
        values = HUMANOID_MOVEMENT_STATE.unpack(raw)
        if values[0] != HUMANOID_MOVEMENT_VERSION:
            raise U9ProcessDataError(
                f"unsupported humanoid movement version {values[0]}"
            )
        _validate_byte_boolean(values[2], "infernal-armor")
        _validate_byte_boolean(values[3], "footprints")
        return cls(values[0], values[1], bool(values[2]), bool(values[3]))


@dataclass(frozen=True)
class U9AvatarMovementFields:
    """The 35-byte Avatar block (``0x004188E0``), written before the header.

    The three timers are integer countdowns: the game subtracts elapsed time
    from them each update and re-arms them with whole values (100 for
    ``health_timer``, 200 for ``swamp_timer``). Retail saves often hold very
    large or negative values in them (``0x3EFFFFFF`` in ``health_timer``);
    these are integers, not float bit patterns.
    """

    version: int
    breath_timer: int
    health_timer: int
    swamp_timer: int
    breath_override: bool
    levitation_allowed: bool
    levitating: bool
    previous_idle_animation_id: int
    posing: int
    last_idle_animation_id: int
    combat_mode: int

    @classmethod
    def from_raw(cls, raw: bytes) -> U9AvatarMovementFields:
        values = AVATAR_MOVEMENT_STATE.unpack(raw)
        if values[0] != AVATAR_MOVEMENT_VERSION:
            raise U9ProcessDataError(f"unsupported Avatar movement version {values[0]}")
        for value, label in zip(
            values[4:7], ("breath-override", "levitation-allowed", "levitating")
        ):
            _validate_byte_boolean(value, label)
        return cls(
            version=values[0],
            breath_timer=values[1],
            health_timer=values[2],
            swamp_timer=values[3],
            breath_override=bool(values[4]),
            levitation_allowed=bool(values[5]),
            levitating=bool(values[6]),
            previous_idle_animation_id=values[7],
            posing=values[8],
            last_idle_animation_id=values[9],
            combat_mode=values[10],
        )


@dataclass(frozen=True)
class U9AvatarMovementTailFields:
    """The Avatar's one-byte trailing block: swamp immunity."""

    swamp_immunity: bool

    @classmethod
    def from_raw(cls, raw: bytes) -> U9AvatarMovementTailFields:
        (value,) = AVATAR_MOVEMENT_TAIL_STATE.unpack(raw)
        _validate_byte_boolean(value, "swamp-immunity")
        return cls(bool(value))


@dataclass(frozen=True)
class U9BruteMovementFields:
    """The 8-byte brute block (``0x0042FF10``), written before the header."""

    version: int
    idle_animation_id: int

    @classmethod
    def from_raw(cls, raw: bytes) -> U9BruteMovementFields:
        values = BRUTE_MOVEMENT_STATE.unpack(raw)
        if values[0] != BRUTE_MOVEMENT_VERSION:
            raise U9ProcessDataError(f"unsupported brute movement version {values[0]}")
        return cls(*values)


@dataclass(frozen=True)
class U9NpcMovementFields:
    """The 12-byte NPC block (``0x004F53C0``): the object the NPC sits or
    sleeps on, then two pad words.

    The pad words are not cleared before saving; retail saves hold arbitrary
    values in them.
    """

    object_reference_index: int
    reserved: tuple[int, int]

    @classmethod
    def from_raw(cls, raw: bytes) -> U9NpcMovementFields:
        values = NPC_MOVEMENT_STATE.unpack(raw)
        return cls(values[0], (values[1], values[2]))


@dataclass(frozen=True)
class U9SpiderMovementFields:
    """The 12-byte spider block (``0x0053ECD0``): speed, then two pad words.

    ``speed`` is -1 (slow), 0 (normal) or 1 (fast). The pad words are not
    cleared before saving.
    """

    speed: int
    reserved: tuple[int, int]

    @classmethod
    def from_raw(cls, raw: bytes) -> U9SpiderMovementFields:
        values = SPIDER_MOVEMENT_STATE.unpack(raw)
        return cls(values[0], (values[1], values[2]))


@dataclass(frozen=True)
class U9SwimmingMovementFields:
    """The 68-byte swimming block (``0x005415D0``).

    Only the first ``fall_animation_count`` / ``death_animation_count``
    animation slots are meaningful; the rest and the two pad words are not
    cleared before saving. A creature that never uses one of the lists may
    save its count uninitialized as well (a sea serpent was saved with a
    fall-animation count of 585), so the counts are reported as stored.
    """

    floor_altitude: float
    floor_depth: float
    jump_depth: float
    fall_animation_ids: tuple[int, int, int, int, int]
    fall_animation_count: int
    death_animation_ids: tuple[int, int, int, int, int]
    death_animation_count: int
    reserved: tuple[int, int]

    @classmethod
    def from_raw(cls, raw: bytes) -> U9SwimmingMovementFields:
        values = SWIMMING_MOVEMENT_STATE.unpack(raw)
        _validate_finite(values[0:3], "swimming movement depth")
        return cls(
            floor_altitude=values[0],
            floor_depth=values[1],
            jump_depth=values[2],
            fall_animation_ids=tuple(values[3:8]),  # type: ignore[arg-type]
            fall_animation_count=values[8],
            death_animation_ids=tuple(values[9:14]),  # type: ignore[arg-type]
            death_animation_count=values[14],
            reserved=(values[15], values[16]),
        )


U9MovementExtensionFields = Union[
    U9HumanoidMovementFields,
    U9AvatarMovementFields,
    U9AvatarMovementTailFields,
    U9BruteMovementFields,
    U9NpcMovementFields,
    U9SpiderMovementFields,
    U9SwimmingMovementFields,
]
MOVEMENT_EXTENSION_FIELD_TYPES: dict[str, type[U9MovementExtensionFields]] = {
    "humanoid": U9HumanoidMovementFields,
    "avatar": U9AvatarMovementFields,
    "avatar_tail": U9AvatarMovementTailFields,
    "brute": U9BruteMovementFields,
    "npc": U9NpcMovementFields,
    "spider": U9SpiderMovementFields,
    "swimming": U9SwimmingMovementFields,
}


@dataclass(frozen=True)
class U9MovementExtensionState:
    """A controller-specific block around the base block.

    ``kind`` names the retail save routine that writes it (``humanoid``,
    ``npc``, ``avatar``, ``avatar_tail``, ``brute``, ``spider`` or
    ``swimming``). ``fields`` holds the typed view and ``raw`` the exact
    bytes. The ``npc`` block begins with an object-reference index, also
    exposed as ``object_reference_index``.
    """

    kind: str
    raw: bytes
    offset: int
    object_reference_index: int | None = None
    fields: U9MovementExtensionFields | None = None

    @property
    def end_offset(self) -> int:
        return self.offset + len(self.raw)


@dataclass(frozen=True)
class U9MovementControllerProcessState:
    """A movement controller: header, world state, base block, and extensions.

    Humanoid-family controllers write their own fields before calling the
    parent save, so ``leading`` blocks sit between the type word and the
    common header body; ``extensions`` follow the base (or flying) block.
    """

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    movement: U9MovementControllerState
    flying: U9FlyingMovementState | None
    offset: int
    end_offset: int
    leading: tuple[U9MovementExtensionState, ...] = ()
    extensions: tuple[U9MovementExtensionState, ...] = ()

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        offset: int,
        *,
        object_reference_count: int,
    ) -> U9MovementControllerProcessState:
        _require_bytes(data, offset, 4, "process type")
        (process_type,) = struct.unpack_from("<i", data, offset)
        if process_type not in MOVEMENT_CONTROLLER_PROCESS_TYPES:
            raise U9ProcessDataError(
                f"process type {process_type} is not a supported movement controller"
            )
        flying_type = process_type in FLYING_MOVEMENT_CONTROLLER_PROCESS_TYPES
        leading_layout, trailing_layout = MOVEMENT_CONTROLLER_EXTENSIONS.get(
            process_type, ((), ())
        )
        leading = _read_movement_extensions(
            data, offset + 4, leading_layout, object_reference_count
        )
        header = U9ProcessHeaderState.from_prefixed_bytes(
            data,
            offset,
            prefix_size=4 + sum(size for _, size in leading_layout),
        )
        world_state = U9ProcessWorldState.from_bytes(
            data, header.end_offset, object_reference_count=object_reference_count
        )
        movement = U9MovementControllerState.from_bytes(
            data, world_state.end_offset, object_reference_count=object_reference_count
        )
        flying = (
            U9FlyingMovementState.from_bytes(data, movement.end_offset)
            if flying_type
            else None
        )
        cursor = flying.end_offset if flying else movement.end_offset
        extensions = _read_movement_extensions(
            data, cursor, trailing_layout, object_reference_count
        )
        return cls(
            header=header,
            world_state=world_state,
            movement=movement,
            flying=flying,
            offset=offset,
            end_offset=extensions[-1].end_offset if extensions else cursor,
            leading=leading,
            extensions=extensions,
        )


def _read_movement_extensions(
    data: bytes,
    offset: int,
    layout: tuple[tuple[str, int], ...],
    object_reference_count: int,
) -> tuple[U9MovementExtensionState, ...]:
    blocks = []
    cursor = offset
    for kind, size in layout:
        _require_bytes(data, cursor, size, f"{kind} movement extension")
        raw = bytes(data[cursor : cursor + size])
        fields = MOVEMENT_EXTENSION_FIELD_TYPES[kind].from_raw(raw)
        reference = None
        if isinstance(fields, U9NpcMovementFields):
            reference = fields.object_reference_index
            _validate_object_reference_index(
                reference, object_reference_count, "npc movement"
            )
        blocks.append(
            U9MovementExtensionState(
                kind=kind,
                raw=raw,
                offset=cursor,
                object_reference_index=reference,
                fields=fields,
            )
        )
        cursor += size
    return tuple(blocks)
