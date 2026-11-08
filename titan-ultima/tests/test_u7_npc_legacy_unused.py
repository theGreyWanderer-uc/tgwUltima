"""Exult's Avatar-triggered unused compatibility state spans both NPC groups, not monsters."""

import csv
import io
import struct

import pytest

from titan.u7.save import U7NPCData, U7Save
from tests.test_u7_remaining_followups import actor_record


def actor(name, used, *, inventory=b""):
    raw = bytearray(actor_record(iflag=bool(inventory)))
    struct.pack_into("<H", raw, 14, used)
    raw[101:117] = name.encode().ljust(16, b"\0")
    return bytes(raw) + inventory


@pytest.mark.parametrize("game", ["bg", "si"])
@pytest.mark.parametrize("flavor", ["runtime", "original"])
def test_avatar_zero_enables_stream_compatibility_and_preserves_inventory_alignment(
    game, flavor
):
    item = b"\6" + bytes([0, 0, 101, 0, 0, 0]) + b"\0"
    raw = (
        struct.pack("<HH", 1, 2)
        + actor("Avatar", 0)
        + actor("Iolo", 0, inventory=item)
        + actor("Third", 1)
    )
    parsed = U7NPCData.from_bytes(raw, game=game, npc_flavor=flavor)
    assert (
        parsed.fix_unused and len(parsed.npcs) == 3 and parsed._parsed_bytes == len(raw)
    )
    assert all(not npc.unused and npc.unused_compatibility for npc in parsed.npcs)
    assert [npc.used_in_game_raw for npc in parsed.npcs] == [0, 0, 1]
    assert parsed.npcs[1].inventory[0].shape == 101 and parsed.npcs[2].name == "Third"
    assert parsed.warnings and "legacy unused compatibility" in parsed.dump_summary()
    rows = list(csv.DictReader(io.StringIO(parsed.dump_csv())))
    assert rows[1]["unused"] == "False" and rows[1]["unused_compatibility"] == "True"


def test_later_zero_word_does_not_activate_repair_and_state_does_not_leak_between_files():
    old = struct.pack("<HH", 1, 1) + actor("Avatar", 0) + actor("Active", 0)
    assert U7NPCData.from_bytes(old).fix_unused
    modern = (
        struct.pack("<HH", 1, 2)
        + actor("Avatar", 1)
        + actor("Unused", 0)
        + actor("Active", 1)
    )
    parsed = U7NPCData.from_bytes(modern)
    assert not parsed.fix_unused and not parsed.warnings
    assert [npc.unused for npc in parsed.npcs] == [False, True, False]
    assert all(not npc.unused_compatibility for npc in parsed.npcs)


def test_auto_detection_runs_with_independent_compatibility_state():
    raw = struct.pack("<HH", 1, 1) + actor("Avatar", 0) + actor("Active", 0)
    parsed = U7NPCData.from_bytes(raw, npc_flavor="auto")
    assert parsed.fix_unused and all(not npc.unused for npc in parsed.npcs)
    assert parsed.npcs[1].used_in_game_raw == 0


def test_monster_ordinals_never_trigger_avatar_unused_repair():
    raw = struct.pack("<H", 2) + actor("Monster", 0) * 2
    parsed = U7NPCData.from_monsnpcs_bytes(raw, game="si")
    assert not parsed.fix_unused and not parsed.warnings
    assert all(not npc.unused and not npc.unused_compatibility for npc in parsed.npcs)


def test_from_save_preserves_container_diagnostics_alongside_repair():
    raw = struct.pack("<HH", 1, 1) + actor("Avatar", 0) + actor("Active", 0)
    save = U7Save("Old", {"NPC.DAT": raw}, "flex")
    save.warnings.append("Container observation")
    parsed = U7NPCData.from_save(save)
    assert parsed.fix_unused and parsed.warnings[0] == "Container observation"
