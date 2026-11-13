"""Distinct sentinel bytes prove MD actor tables never fall back to U6 offsets."""

import struct

import pytest

from titan.md.actor import MD_ACTOR_LAYOUT, parse_martian_actors
from titan.u6.actor import U6ActorError, U6Actors
from titan.u6.object import pack_position


def test_martian_actor_layout_and_status_semantics() -> None:
    data = bytearray(MD_ACTOR_LAYOUT.required_size)
    data[0x103:0x106] = bytes(pack_position(417, 628, 0))
    struct.pack_into("<H", data, 0x402, 343 | (7 << 10))
    struct.pack_into("<H", data, 0x15F3, 100 | (2 << 10))
    struct.pack_into("<H", data, 0x16F3, 344 | (9 << 10))
    for offset, value in (
        (0x17F2, 1),
        (0x18F2, 0x81),
        (0x19F2, 2),
        (0x1AF2, 3),
        (0x12F2, 4),
        (0x13F2, 5),
        (0x15F2, 6),
        (0x11F2, 7),
        (0x801, 0x81),
        (1, 0xC0),
    ):
        data[offset] = value
    actor = parse_martian_actors(bytes(data))[1]
    assert (actor.x, actor.y, actor.z, actor.obj_n, actor.frame_n) == (
        417,
        628,
        0,
        343,
        7,
    )
    assert (actor.base_obj_n, actor.old_frame_n) == (344, 9)
    assert (actor.talk_flags, actor.movement_flags) == (0x81, 3)
    assert (actor.magic, actor.combat_mode, actor.movement_points, actor.worktype) == (
        4,
        5,
        6,
        7,
    )
    assert actor.is_cold and actor.is_in_party and actor.is_met
    assert actor.is_hypoxic and actor.is_frenzied
    assert not actor.is_protected
    u6_actor = U6Actors.parse(bytes(data))[1]
    assert u6_actor.talk_flags == 1
    assert u6_actor.magic == 5 and u6_actor.combat_mode == 4


def test_martian_actor_requires_the_later_movement_table() -> None:
    with pytest.raises(U6ActorError, match="too short"):
        parse_martian_actors(bytes(MD_ACTOR_LAYOUT.required_size - 1))
