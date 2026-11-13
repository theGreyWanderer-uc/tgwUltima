"""Keep Avatar schedule sentinels and monster reporting ordinals semantically separate."""

from __future__ import annotations

import struct

import pytest

from titan.u7.save import U7NPCData, U7Schedules


def _schedule_stream(marker: int, offsets: list[int], entry: bytes = b"") -> bytes:
    header = struct.pack("<i", len(offsets))
    if marker < 0:
        header = struct.pack("<iI", marker, len(offsets))
        if marker == -2:
            header += struct.pack("<H", 0)
    return header + struct.pack(f"<{len(offsets)}H", *offsets) + entry


@pytest.mark.parametrize("marker", [0, -1, -2])
def test_schedule_rejects_nonzero_avatar_sentinel(marker: int) -> None:
    entry = (
        bytes.fromhex("32 2D 92 0D")
        if marker == 0
        else struct.pack("<HHBBBB", 301, 402, 3, 2, 6, 0x7F)
    )
    with pytest.raises(ValueError, match="(?i)avatar.*sentinel.*zero"):
        U7Schedules.from_bytes(_schedule_stream(marker, [1, 1], entry))


@pytest.mark.parametrize("marker", [0, -1, -2])
def test_schedule_zero_sentinel_preserves_npc_one_index(marker: int) -> None:
    entry = (
        bytes.fromhex("32 2D 92 0D")
        if marker == 0
        else struct.pack("<HHBBBB", 301, 402, 3, 2, 6, 0x7F)
    )
    schedules = U7Schedules.from_bytes(_schedule_stream(marker, [0, 1], entry))
    assert set(schedules.entries) == {1}
    schedule = schedules.entries[1][0]
    assert (schedule.tx, schedule.ty, schedule.time, schedule.type) == (301, 402, 2, 6)


@pytest.mark.parametrize("marker", [0, -1, -2])
@pytest.mark.parametrize("offsets", [[], [0]])
def test_schedule_accepts_empty_and_avatar_only_tables(
    marker: int, offsets: list[int]
) -> None:
    schedules = U7Schedules.from_bytes(_schedule_stream(marker, offsets))
    assert schedules.entries == {}
    assert schedules.num_npcs == len(offsets)


def _actor_record(*, used: bool = True, modern_magic: bool = False) -> bytes:
    record = bytearray(117)
    struct.pack_into("<H", record, 2, 150)
    struct.pack_into("<H", record, 14, int(used))
    # Legacy NPC 0 owns these spell stats; legacy non-NPC actors do not.
    record[27:29] = bytes([27, 21])
    if modern_magic:
        record[25:27] = bytes([0x80 | 23, 17])
    return bytes(record)


def test_first_legacy_monster_does_not_receive_avatar_spell_stats() -> None:
    records = _actor_record() * 2
    monsters = U7NPCData.from_monsnpcs_bytes(struct.pack("<H", 2) + records)
    assert [(actor.magic, actor.mana) for actor in monsters.npcs] == [(0, 0), (0, 0)]
    assert [actor.npc_num for actor in monsters.npcs] == [0, 1]

    npcs = U7NPCData.from_bytes(struct.pack("<HH", 2, 0) + records)
    assert [(actor.magic, actor.mana) for actor in npcs.npcs] == [(27, 21), (0, 0)]


def test_monsters_do_not_use_the_npc_unused_slot_rule() -> None:
    records = _actor_record(used=False) * 2
    monsters = U7NPCData.from_monsnpcs_bytes(struct.pack("<H", 2) + records)
    assert len(monsters.npcs) == 2
    assert not any(actor.unused for actor in monsters.npcs)

    # A modern Avatar word keeps the later NPC's zero marker authoritative.
    # A zero Avatar word instead activates the stream-wide legacy repair.
    npcs = U7NPCData.from_bytes(
        struct.pack("<HH", 2, 0) + _actor_record(used=True) + _actor_record(used=False)
    )
    assert [actor.unused for actor in npcs.npcs] == [False, True]


def test_all_monster_ordinals_keep_explicit_runtime_spell_stats() -> None:
    records = _actor_record(modern_magic=True) * 2
    monsters = U7NPCData.from_monsnpcs_bytes(struct.pack("<H", 2) + records)
    assert [(actor.magic, actor.mana) for actor in monsters.npcs] == [
        (23, 17),
        (23, 17),
    ]


def test_monster_context_keeps_variable_actor_tails() -> None:
    first = bytearray(_actor_record())
    struct.pack_into("<H", first, 4, 1 | 2 | 8)
    inventory = bytes([6, 1, 2, 150, 0, 0, 1, 1])
    first_record = (
        bytes(first[:78]) + b"\x03foo" + bytes(first[78:]) + inventory + b"\xff\x02"
    )
    second = bytearray(_actor_record(modern_magic=True))
    struct.pack_into("<H", second, 4, 2)
    data = struct.pack("<H", 2) + first_record + bytes(second) + b"\xff\x02"

    monsters = U7NPCData.from_monsnpcs_bytes(data)
    assert len(monsters.npcs) == 2
    assert [actor.npc_num for actor in monsters.npcs] == [0, 1]
    assert [(item.shape, item.x, item.y) for item in monsters.npcs[0].inventory] == [
        (150, 1, 2)
    ]
    assert (monsters.npcs[0].magic, monsters.npcs[1].magic) == (0, 23)
    assert monsters._parsed_bytes == len(data) + 2
