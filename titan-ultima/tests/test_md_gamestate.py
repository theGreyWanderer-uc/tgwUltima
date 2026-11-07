"""MD save-state and animation tests with distinct U6/MD offsets."""

import struct

import pytest

from tests.md_fixtures import initial_martian_objlist
from titan.md.actor import MD_ACTOR_LAYOUT
from titan.md.gamestate import MartianGameState
from titan.md.map_animation import build_martian_animation
from titan.u6.tile import U6AnimData, U6AnimEntry


def test_md_clock_party_dream_and_berry_timers() -> None:
    data = initial_martian_objlist()
    data[0x1D27] = 1
    struct.pack_into("<H", data, 0x1D29, 0x10)
    struct.pack_into("<H", data, 0x1D53, 0x1234)
    data[0x1D2F:0x1D31] = b"\xa3\xf5"
    data[0x1D05] = 9
    state = MartianGameState.parse(bytes(data))
    assert state.clock.iso_string() == "1895-01-06T08:00"
    assert [(m.actor_id, m.name) for m in state.party] == [
        (1, "Avatar"),
        (2, "Spector"),
        (3, "Nellie_Bly"),
    ]
    assert state.gender == 1 and state.in_dream_mode and state.dream_stage == 0x1234
    assert (
        state.berry_timers[0].purple,
        state.berry_timers[0].green,
        state.berry_timers[0].brown,
    ) == (3, 10, 5)
    assert state.blue_berry_counter == 9


@pytest.mark.parametrize("mutation", ["short", "party", "clock"])
def test_md_state_rejects_invalid_data(mutation: str) -> None:
    data = initial_martian_objlist()
    if mutation == "short":
        data = data[:-1]
    elif mutation == "party":
        data[0xFF0] = 17
    else:
        data[0x1CF4] = 25
    with pytest.raises(ValueError, match="Martian Dreams"):
        MartianGameState.parse(bytes(data))


def test_md_saved_flags_drive_canals_power_and_watch_without_mutating_resolver() -> (
    None
):
    raw = U6AnimData(
        [
            U6AnimEntry(16, 368, 1, 0),
            U6AnimEntry(1992, 408, 6, 1),
            U6AnimEntry(616, 416, 14, 1),
            U6AnimEntry(111, 384, 6, 1),
        ]
    )
    data = initial_martian_objlist()
    off = build_martian_animation(raw, MartianGameState.parse(bytes(data)))
    assert off.resolve_tile(16, 3) == 368
    assert off.resolve_tile(1992, 3) == 408
    assert off.resolve_tile(616, 3) == 424
    assert off.resolve_tile(111, 3) == 385
    data[MD_ACTOR_LAYOUT.talk_flags + 118] = (1 << 5) | (1 << 6)
    data[MD_ACTOR_LAYOUT.talk_flags + 115] = 1 << 2
    state = MartianGameState.parse(bytes(data))
    assert state.canals_filled and state.power_active
    on = build_martian_animation(raw, state)
    assert on.resolve_tile(16, 3) == 369
    assert on.resolve_tile(1992, 3) == 409
    assert off.resolve_tile(16, 3) == 368
    assert raw.resolve_tile(616, 3) == 417


@pytest.mark.parametrize("flags", [0, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0])
@pytest.mark.parametrize("tick", [0, 1, 7, 65535])
def test_md_water_matches_dos_load_reconstruction(flags: int, tick: int) -> None:
    # GAME.EXE 2238:0919 zeroes masks; 222c:0008 classifies both canal ranges.
    cistern = [U6AnimEntry(i, 344 + (i - 1) * 2, 1, 0) for i in range(1, 5)]
    canals = [U6AnimEntry(i, 368 + (i - 16) * 2, 1, 0) for i in range(16, 24)]
    canals += [U6AnimEntry(i, 500 + (i - 192) * 2, 1, 0) for i in range(192, 196)]
    raw = U6AnimData(cistern + canals)
    data = initial_martian_objlist()
    data[MD_ACTOR_LAYOUT.talk_flags + 118] = flags
    state = MartianGameState.parse(bytes(data))
    animation = build_martian_animation(raw, state)
    assert (state.cistern_filled, state.canal_valves_open, state.canals_filled) == (
        bool(flags & 0x20),
        bool(flags & 0x40),
        flags & 0x60 == 0x60,
    )
    for entry in cistern:
        assert animation.resolve_tile(entry.placeholder_tile, tick) == (
            entry.first_frame_tile + (1 if flags & 0x20 else 0)
        )
    for entry in canals:
        assert animation.resolve_tile(entry.placeholder_tile, tick) == (
            entry.first_frame_tile + (1 if flags & 0x60 == 0x60 else 0)
        )
    assert raw.entries == cistern + canals
    assert build_martian_animation(raw).resolve_tile(1, tick) == 344
    assert build_martian_animation(raw).resolve_tile(16, tick) == 368
