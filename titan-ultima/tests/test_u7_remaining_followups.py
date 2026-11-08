"""Regression coverage for shared world resolution and schedule framing follow-ups."""

import struct

import pytest

from titan.u7.combat_metadata import U7CombatLayer, U7CombatMetadata
from titan.u7.save import U7Schedules
from titan.u7.shapeinfo import U7Weapons, U7Ammos, U7Armors
from titan.u7.save import U7NPCData
from titan.u7.actor_metadata import U7ActorMetadata


def combat_record(kind, shape, value=0, *, deleted=False):
    size = {"weapon": 21, "ammo": 13, "armor": 10}[kind]
    data = bytearray(size)
    data[:2] = shape.to_bytes(2, "little")
    data[2] = value
    data[-1] = 255 if deleted else 0
    return bytes(data)


@pytest.mark.parametrize(
    "kind,reader,name",
    [
        ("weapon", U7Weapons, "WEAPONS.DAT"),
        ("ammo", U7Ammos, "AMMO.DAT"),
        ("armor", U7Armors, "ARMOR.DAT"),
    ],
)
def test_shared_combat_world_resolves_sparse_replacements_and_removals(
    tmp_path, kind, reader, name
):
    static, patch = tmp_path / "STATIC", tmp_path / "patch"
    static.mkdir()
    patch.mkdir()
    assert reader.from_dir(str(static)).declared_count is None
    base = bytes([2]) + combat_record(kind, 100, 1) + combat_record(kind, 101, 2)
    mod = (
        bytes([3])
        + combat_record(kind, 100, deleted=True)
        + combat_record(kind, 102, 3)
        + combat_record(kind, 102, 4)
    )
    (static / name).write_bytes(base)
    (patch / name.lower()).write_bytes(mod)
    parsed = reader.from_dir(str(static), patch_dir=patch)
    assert {row.shape for row in parsed.records} == {101, 102}
    assert [layer.to_bytes() for layer in parsed.world_metadata.layers] == [base, mod]
    assert parsed.world_metadata.records[102].raw[2] == 4
    assert parsed.world_metadata.records[102].source.endswith(name.lower())


@pytest.mark.parametrize("kind", ["weapon", "ammo", "armor"])
def test_combat_copy_edits_preserve_headers_unknown_bytes_and_tail(kind):
    row = combat_record(kind, 100, 9)
    raw = b"\xff\x01\x00" + row + b"unknown-tail"
    layer = U7CombatLayer.from_bytes(kind, raw, strict=True)
    edited = layer.replace_record(0, combat_record(kind, 101, 8))
    assert layer.to_bytes() == raw and edited.to_bytes()[:3] == raw[:3]
    assert edited.table.trailing_data == b"unknown-tail"
    removed = edited.append_record(edited.removal_record(101))
    assert U7CombatMetadata(kind, (removed,)).records == {}
    assert removed.table.header_size == 3 and removed.table.declared_count == 2
    with pytest.raises(ValueError):
        layer.replace_record(0, b"short")


def test_combat_append_crosses_255_without_losing_unknown_data():
    row = combat_record("armor", 100)
    source = U7CombatLayer.from_bytes("armor", bytes([254]) + row * 254 + b"tail")
    appended = source.append_record(combat_record("armor", 101))
    assert appended.to_bytes()[:3] == b"\xff\xff\x00"
    assert appended.table.trailing_data == b"tail" and source.table.header_size == 1
    with pytest.raises(ValueError, match="incomplete"):
        U7CombatLayer.from_bytes("armor", b"\x01short").append_record(row)


def schedules(names=(b"walk_to_market", b"night_watch"), *, trailing=b""):
    block = b"".join(struct.pack("<H", len(name)) + name for name in names)
    data = struct.pack("<iIH2H", -2, 2, len(names), 0, 1)
    if names:
        data += struct.pack("<H", len(block)) + block
    return data + struct.pack("<HHBBBB", 300, 400, 2, 3, 0x80, 0x7F) + trailing


def test_scripted_schedule_names_raw_bytes_and_trailing_diagnostics():
    raw = schedules(trailing=b"tail")
    parsed = U7Schedules.from_bytes(raw, strict=True)
    assert parsed.script_names == ("walk_to_market", "night_watch")
    assert parsed.name_for_type(0x80) == "walk_to_market"
    assert (
        "walk_to_market" in parsed.dump_csv()
        and "walk_to_market" in parsed.dump_detail()
    )
    assert parsed.raw == raw and parsed.trailing_data == b"tail" and parsed.warnings


def test_shared_schedule_parser_rejects_every_truncated_prefix_strictly():
    raw = schedules()
    for length in range(len(raw)):
        with pytest.raises(ValueError):
            U7Schedules.from_bytes(raw[:length], strict=True)
    partial = U7Schedules.from_bytes(raw[:-1])
    assert not partial.complete and partial.warnings and not partial.entries


def test_script_block_lengths_and_cumulative_counts_are_validated():
    raw = bytearray(schedules())
    struct.pack_into("<H", raw, 16, 65535)
    with pytest.raises(ValueError, match="script-name"):
        U7Schedules.from_bytes(raw, strict=True)
    with pytest.raises(ValueError, match="not cumulative"):
        U7Schedules.from_bytes(struct.pack("<i3H", 3, 0, 2, 1), strict=True)
    with pytest.raises(ValueError, match="Unsupported"):
        U7Schedules.from_bytes(struct.pack("<i", -3))


def actor_record(*, flags=0, flags2=0, iflag=0, poly=0, intel=10, health=20):
    raw = bytearray(117)
    raw[10], raw[18], raw[20] = health & 255, 30, intel
    struct.pack_into("<HH", raw, 2, 100, iflag)
    struct.pack_into("<H", raw, 14, 1)
    struct.pack_into("<HhI", raw, 64, 100, poly, flags)
    struct.pack_into("<I", raw, 74, flags2)
    return bytes(raw)


def test_npc_extended_death_health_correction_and_original_boundary():
    raw = actor_record(flags=16)
    runtime = U7NPCData.from_bytes(
        struct.pack("<HH", 2, 0) + raw * 2, npc_flavor="runtime"
    )
    original = U7NPCData.from_bytes(
        struct.pack("<HH", 2, 0) + raw * 2, npc_flavor="original"
    )
    assert all(n.is_dead for n in runtime.npcs) and all(
        not n.is_dead for n in original.npcs
    )
    dying = U7NPCData.from_bytes(
        struct.pack("<HH", 2, 0) + actor_record(health=-11) * 2
    )
    assert not dying.npcs[0].is_dead and dying.npcs[1].is_dead
    assert dying.npcs[1].metadata.health_death_correction


def test_named_usecode_and_extended_skin_remain_explicit_and_json_safe():
    raw = actor_record(iflag=8 | 16)
    raw = raw[:78] + bytes([4]) + b"test" + bytes([9]) + raw[79:]
    parsed = U7NPCData.from_bytes(struct.pack("<HH", 1, 0) + raw).npcs[0]
    assert parsed.metadata.usecode_name == "test" and parsed.metadata.skin == 9
    assert parsed.metadata.resolve_usecode() is None
    assert parsed.metadata.resolve_usecode({"test": 0x12345}) == 0x12345
    assert "test" in U7NPCData([parsed]).dump_csv()


def test_polymorph_flag_correction_and_avatar_appearance_context():
    raw = actor_record(flags2=1)
    extension = U7ActorMetadata.from_bytes(
        raw, game="si", original_new_game=False, npc_num=1, health=20, strength=30
    )
    assert not extension.effective_flags & (1 << 32)
    raw = actor_record(intel=128 | 10, poly=900)
    extension = U7ActorMetadata.from_bytes(
        raw, game="si", original_new_game=False, npc_num=1, health=20, strength=30
    )
    assert extension.appearance(100)["shape"] == 900
    avatar = U7ActorMetadata.from_bytes(
        actor_record(),
        game="bg",
        original_new_game=False,
        npc_num=0,
        health=20,
        strength=30,
    )
    assert avatar.appearance(100)["avatar_context_required"]
    assert avatar.appearance(100, avatar_shape=721)["shape"] == 721
