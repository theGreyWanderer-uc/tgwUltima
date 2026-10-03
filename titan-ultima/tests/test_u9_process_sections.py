from __future__ import annotations

import struct
import unittest

from titan.u9.process_sections import (
    BOOK_PAGE_COUNT,
    U9CombatState,
    U9ProcessSections,
    U9ProcessSectionsError,
    _Reader,
)

REFS = 8


def _light(ref: int) -> bytes:
    return struct.pack(
        "<I3B3f3fff3Bffif2Ii",
        1,
        255,
        200,
        100,
        *(1.0, 2.0, 3.0),
        *(0.0, 0.0, 10.0),
        2.0,
        150.0,
        255,
        200,
        100,
        5.0,
        0.5,
        1,
        0.1,
        0,
        0,
        ref,
    )


def _combatant_common(npc_type: int, version: int = 5) -> bytes:
    return struct.pack(
        "<i7ifiiih2x3ifiiBBii128siBHBH5i3f3i",
        version,
        npc_type,
        *(0, 1, 2, 0, 30, 3),
        30.0,
        0,
        *(6155, 10125, 1942),
        *(0, 0, 0),
        16.0,
        0,
        4,
        0,
        0,
        0,
        0,
        b"",
        -1,
        *(0, 0, 0, 0),
        *(-1, 0, 0, 0, 0),
        *(1.0, 2.0, 3.0),
        0,
        0,
        -1,
    )


def _humanoid() -> bytes:
    return struct.pack("<iiifiii", 3, 1, 0, 0.7854, 201, 0, -1)


def _avatar(weapon_ref: int) -> bytes:
    return struct.pack(
        "<ii3ffiiiIIffiiH2xiIIffii3fiiBiiii",
        4,
        1,
        *(1.0, 2.0, 3.0),
        0.5,
        weapon_ref,
        2,
        3,
        *(5, 9, 1.5, 2.5, 4, 0),
        *(612, 1, 10, 20, 3.0, 4.0, 0),
        15,
        *(4.0, 5.0, 6.0),
        8,
        2,
        1,
        *(35, 4, 10, 3),
    )


def _wolf() -> bytes:
    return struct.pack("<iiiiiiiBBBii", 3, 0, 1, 2, 192, 1600, 800, 1, 0, 1, 0, 0)


def _creeper() -> bytes:
    return struct.pack("<iBBiiiIIfII", 2, 1, 0, 0, 0, 0, 329, 1000, 50.0, 400, 400)


def _sections(
    *,
    common_version: int = 5,
    music_nodes: int = 2,
    refs: int = REFS,
) -> bytes:
    """A complete sections block; object references are taken modulo ``refs``."""

    def ref(value: int) -> int:
        return value % refs

    d = bytearray()
    # 1 fast area: one entry, then the 0 marker.
    # Flags 0x6B: displayed, active, water (lava, flat).
    d += struct.pack("<i", 1) + b"\x01" + struct.pack("<5i", 1, 2, 3, 4, 0x6B) + b"\x00"
    # 2 NPC manager.
    npc_records = bytearray(512 * 316)
    struct.pack_into("<i", npc_records, 494 * 316 + 0x44, 25)  # wolf: leading
    struct.pack_into("<i", npc_records, 300 * 316 + 0x44, 19)  # creeper
    d += struct.pack("<i", 2) + npc_records + bytes(512 * 16)
    d += (
        struct.pack("<512i", *range(512)) + bytes(12) + struct.pack("<352i", *[0] * 352)
    )
    d += struct.pack("<4I", 0, 0, 0, 0)
    # 3 main interface: map unavailable but visible, breath bar hidden.
    d += struct.pack("<i", 3) + b"\x01" * 10 + b"\x00" + b"\x01\x01\x00" + b"\x01" * 8
    found = bytearray(8192)
    found[17] = found[8191] = 1
    d += struct.pack("<iB", 1, 1) + found
    # 4 lights: none unlimited, one limited-range.
    d += struct.pack("<i3ii", 1, 10, 20, 30, 1) + struct.pack("<i", 0)
    d += struct.pack("<i", 1) + _light(ref(3))
    d += struct.pack("<23i", *range(23)) + struct.pack("<2I", 0, 0)
    # 5 weather: state, two sun masks, screen fade.
    d += struct.pack("<i", 2) + struct.pack(
        "<4if5i3f3f3fi3f4Ii3fi3Bi3Bi3B4hf",
        *(43200, 43190, 43500, 90000),
        0.0,
        *(0, 1, 3, 4, -5),
        *(100.0, 200.0, 0.0),
        *(1.5, -2.5, 0.0),
        *(0.5, 25000.0, 0.75),
        120,
        *(3.0, -4.0),
        0.9,
        *(10, 1000, 1050, 500),
        40,
        *(12.0, 0.1, 5.0),
        *(1, 255, 240, 200),
        *(0, 0, 0, 0),
        *(1, 176, 176, 176),
        *(1, 0, 4, 2),
        0.25,
    )
    d += struct.pack("<iii", 2, ref(1), ref(2))
    d += struct.pack("<8i2I", 0, 20, 15, -1, 6, 2, 0, 0, 0, 0)
    # 6 spell manager.
    d += struct.pack("<iii", 0, 1, 4242)
    # 7 physics: one object, one overlap with one trigger.
    d += struct.pack("<ii", 1, 9)
    d += struct.pack("<i", 1) + struct.pack(
        "<i3f4f3f3f3ffif",
        ref(4),
        *[0.0] * 3,
        1.0,
        0.0,
        0.0,
        0.0,
        *[0.0] * 9,
        0.0,
        1,
        10.0,
    )
    d += struct.pack("<i", 0)
    d += (
        struct.pack("<ii", 1, ref(5))
        + struct.pack("<iii", ref(6), 7, 0)
        + struct.pack("<i", 0)
    )
    d += struct.pack("<i", 0)
    # 8 moving platforms: a lift with one rider and an empty path, then a ship.
    d += struct.pack("<ii", 1, 0)
    d += struct.pack("<iii4I", 1, 1, ref(2), 0, 0, 0, 0)
    d += struct.pack("<i", 1) + struct.pack(
        "<i3f4ffif3f4f3f", ref(3), *[1.0] * 3, *[0.0] * 4, 0.0, 1, 0.0, *[0.0] * 10
    )
    d += struct.pack("<i", 0)
    d += struct.pack("<i4i", 0, 0, 0, 0, 0) + struct.pack(
        "<iffffiiiiii", 0, 0, 0, 1, 70, 0, 0, 0, 0, ref(1), ref(2)
    )
    d += bytes(48)
    d += (
        struct.pack("<iii4I", 1, 3, ref(1), 0, 0, 0, 0)
        + struct.pack("<i", 0)
        + bytes(209)
    )
    d += struct.pack("<i", 0)
    # 9 highway manager.
    # One mover: frozen position (flag 0x4), Location with junk in its pad.
    d += struct.pack("<ii", 2, 1)
    d += struct.pack("<iiiifiiihH", 4, 226, 14, 2, 7.5, 900, 64063, 61084, 2436, 3089)
    d += struct.pack("<i4I", 1, 0, 0, 0, 0)
    # 10 hints.
    d += struct.pack("<ii", 3, 1) + struct.pack(
        "<ii6i4I", ref(1), ref(2), *range(6), 0, 0, 0, 0
    )
    d += struct.pack("<4I", 0, 0, 0, 0)
    # 11 combat: the Avatar (humanoid and Avatar fields after the common
    # part), NPC 494 (wolf fields before it) and NPC 300 (creeper: common,
    # its fields, common again), then three words.
    d += struct.pack("<iiiii", 3, 3, 0, 494, 300)
    d += _combatant_common(0, common_version) + _humanoid() + _avatar(ref(5))
    d += _wolf() + _combatant_common(494, common_version)
    d += _combatant_common(300, common_version) + _creeper()
    d += _combatant_common(300, common_version)
    d += struct.pack("<3i", 0, -407, 0)
    # 12 books, 13 music list (count, nodes).
    d += struct.pack("<i", 1) + struct.pack(
        f"<{BOOK_PAGE_COUNT}i", *[0] * BOOK_PAGE_COUNT
    )
    d += struct.pack("<2ii", 3, 4, 0)
    d += struct.pack("<ii", 2, music_nodes)
    for i in range(music_nodes):
        d += struct.pack("<iiBiBBIIIBBB", i, 3, 1, 7, 0, 100, 1000, 3000, 2000, 1, 0, 0)
    return bytes(d)


class ProcessSectionsTests(unittest.TestCase):
    def test_reads_every_section_to_the_end_of_the_data(self) -> None:
        data = _sections()
        s = U9ProcessSections.from_bytes(data, 0, object_reference_count=REFS)

        self.assertEqual(s.end_offset, len(data))
        (chunk,) = s.fast_area.entries
        self.assertEqual(
            (chunk.chunk_x, chunk.chunk_y, chunk.wrap_x, chunk.wrap_y), (1, 2, 3, 4)
        )
        self.assertTrue(chunk.displayed and chunk.active and chunk.has_water)
        self.assertFalse(chunk.collision)
        self.assertEqual(chunk.water_kind, "lava")
        self.assertTrue(chunk.flat_water)
        self.assertFalse(chunk.underground_water)
        self.assertEqual(s.npc_manager.npc_object_offsets[5], 5)
        self.assertEqual(len(s.npc_manager.npcs()), 512)
        ui = s.main_interface
        self.assertEqual(ui.element_flags()["map"], (False, True))
        self.assertEqual(ui.element_flags()["breath_bar"], (True, False))
        self.assertEqual((ui.mode_name, ui.equipment_shown), ("minimum", True))
        self.assertEqual(ui.found_types(), (17, 8191))
        self.assertEqual(s.lights.ambient, (10, 20, 30))
        (light,) = s.lights.ranged_lights
        self.assertEqual(light.color, (255, 200, 100))
        self.assertEqual(light.position, (1.0, 2.0, 3.0))
        self.assertEqual(light.light_range, 150.0)
        self.assertEqual(light.object_reference_index, 3)
        self.assertEqual(s.lights.settings[22], 22)
        w = s.weather
        self.assertEqual((w.weather_time, w.total_seconds), (43200, 90000))
        self.assertEqual(
            (w.current_state_name, w.desired_state_name), ("raining", "storming")
        )
        self.assertEqual(w.transition_time, -5)
        self.assertEqual(w.storm_position, (100.0, 200.0, 0.0))
        self.assertEqual((w.storm_radius, w.storm_intensity_cap), (25000.0, 0.75))
        self.assertEqual((w.wind_strength, w.wind_vector), (120, (3.0, -4.0)))
        self.assertEqual(w.gust_sound_time, 500)
        self.assertEqual((w.rain_drop_count, w.lightning_time), (40, 5.0))
        self.assertEqual((w.sun.present, w.sun.color), (True, (255, 240, 200)))
        self.assertFalse(w.secondary_light.present)
        self.assertEqual(w.lightning.color, (176, 176, 176))
        self.assertEqual(
            (w.trammel_phase_name, w.felucca_phase_name), ("full", "first quarter")
        )
        self.assertEqual(w.sun_mask_scale, 0.25)
        self.assertEqual(w.sun_mask_reference_indices, (1, 2))
        self.assertEqual((w.screen_fade.edge_rate, w.screen_fade.direction), (15, -1))
        self.assertEqual(s.spell_manager.active_spell_process_ids, (4242,))
        self.assertEqual(s.physics.map_number, 9)
        self.assertEqual(s.physics.objects[0].mass, 10.0)
        (overlap,) = s.physics.overlaps
        self.assertEqual(overlap.triggers[0].trigger_object_reference_index, 6)
        lift, ship = s.moving_platforms.supports
        self.assertEqual((lift.kind, ship.kind), (1, 3))
        self.assertEqual(lift.supported_objects[0].object_reference_index, 3)
        assert lift.path is not None
        self.assertEqual(lift.path.speed, 70.0)
        self.assertEqual((len(lift.own), len(ship.own)), (48, 209))
        self.assertIsNone(ship.path)
        (mover,) = s.highway_manager.movers
        self.assertEqual((mover.npc_number, mover.highway, mover.node), (226, 14, 2))
        self.assertEqual((mover.speed, mover.milliseconds_to_next_step), (7.5, 900))
        self.assertTrue(mover.position_frozen)
        self.assertFalse(mover.walk_started)
        self.assertEqual(mover.frozen_location, (64063, 61084, 2436))
        self.assertEqual(s.highway_manager.step_phase, 1)
        self.assertEqual(s.hints.hints[0].values, (0, 1, 2, 3, 4, 5))
        self.assertEqual(s.combat.npc_types, (0, 494, 300))
        avatar, npc, creeper = s.combat.combatants
        self.assertEqual((avatar.combat_behavior, npc.combat_behavior), (0, 25))
        self.assertEqual((len(avatar.leading), len(avatar.trailing)), (0, 157))
        self.assertEqual((len(npc.leading), len(npc.trailing)), (39, 0))
        self.assertEqual(npc.common.npc_type, 494)
        self.assertEqual(avatar.common.combatant_radius, 30.0)
        self.assertEqual(avatar.common.home_location, (6155, 10125, 1942))
        self.assertEqual(avatar.common.route_tolerance, 16.0)
        self.assertEqual(avatar.common.route_failure_limit, 4)
        self.assertEqual(avatar.common.last_destination, (1.0, 2.0, 3.0))
        self.assertEqual(avatar.common.charm_source_npc_type, -1)
        self.assertEqual(npc.offset, avatar.end_offset)
        humanoid, avatar_fields = avatar.trailing_fields
        self.assertEqual((humanoid.kind, humanoid.version), ("humanoid", 3))
        turn_tolerance = humanoid["pre_combat_turn_tolerance"]
        assert isinstance(turn_tolerance, float)
        self.assertAlmostEqual(turn_tolerance, 0.7854, 5)
        self.assertEqual(humanoid["stun_effect_id"], -1)
        self.assertEqual(avatar_fields["strike_zone_position"], (1.0, 2.0, 3.0))
        self.assertEqual(avatar_fields["self_damage_weapon"], 5)
        self.assertEqual(avatar_fields.object_reference_indices, (5,))
        self.assertEqual(avatar_fields["weapon_item_type"], 612)
        self.assertEqual(avatar_fields["self_damage_position"], (4.0, 5.0, 6.0))
        self.assertEqual(avatar_fields["queued_spell_flags"], 3)
        self.assertEqual(avatar_fields["animation_end_callback"], 35)
        (wolf,) = npc.leading_fields
        self.assertEqual(npc.class_fields, (wolf,))
        self.assertEqual((wolf["current_state"], wolf["notice_distance"]), (1, 800))
        self.assertEqual(len(npc.leading), 39)
        self.assertIsNone(npc.repeated_common)
        assert creeper.repeated_common is not None
        self.assertEqual(creeper.repeated_common.npc_type, 300)
        self.assertEqual(creeper.trailing_fields[0]["enemy_distance"], 50.0)
        self.assertEqual(len(creeper.trailing), 38 + 268)
        self.assertEqual(s.combat.tail, (0, -407, 0))
        self.assertEqual(s.books.chapter_bookmarks, (3, 4))
        self.assertEqual(s.sounds.version, 2)
        first, second = s.sounds.music_nodes
        self.assertEqual((second.track, second.priority, second.piece), (1, 3, 7))
        self.assertEqual((first.start_volume, first.target_volume), (0, 100))
        self.assertEqual(
            (first.fade_start_tick, first.fade_end_tick, first.last_update_tick),
            (1000, 3000, 2000),
        )
        self.assertTrue(first.playing and first.fading_in)

    def test_music_list_may_be_empty(self) -> None:
        data = _sections(music_nodes=0)
        s = U9ProcessSections.from_bytes(data, 0, object_reference_count=REFS)
        self.assertEqual(s.sounds.music_nodes, ())
        self.assertEqual(s.end_offset, len(data))

    def test_music_list_must_end_the_file(self) -> None:
        for data, message in (
            (_sections() + bytes(30), "30 bytes follow the music list"),
            (_sections()[:-30], "truncated music node"),
        ):
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(U9ProcessSectionsError, message),
            ):
                U9ProcessSections.from_bytes(data, 0, object_reference_count=REFS)

    def test_rejects_too_many_highway_movers(self) -> None:
        data = bytearray(_sections())
        good = U9ProcessSections.from_bytes(bytes(data), 0, object_reference_count=REFS)
        struct.pack_into("<i", data, good.highway_manager.offset + 4, 65)
        with self.assertRaisesRegex(U9ProcessSectionsError, "highway mover count 65"):
            U9ProcessSections.from_bytes(bytes(data), 0, object_reference_count=REFS)

    def test_rejects_bad_versions_references_and_markers(self) -> None:
        data = _sections()
        good = U9ProcessSections.from_bytes(data, 0, object_reference_count=REFS)
        light_ref = good.lights.offset + 4 + 12 + 4 + 4 + 4 + 66
        for position, fmt, value, message in (
            (good.lights.offset, "<i", 2, "light-system version 2"),
            (good.physics.offset, "<i", 0, "physics version 0"),
            (light_ref, "<i", REFS, f"saved light object-reference index {REFS}"),
            (good.moving_platforms.offset + 8, "<i", 5, "moving platform marker 5"),
            (good.fast_area.offset + 4, "<B", 3, "fast-area marker 3"),
        ):
            bad = bytearray(data)
            struct.pack_into(fmt, bad, position, value)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(U9ProcessSectionsError, message),
            ):
                U9ProcessSections.from_bytes(bytes(bad), 0, object_reference_count=REFS)

    def test_rejects_bad_combatant_fields(self) -> None:
        data = bytearray(_sections())
        good = U9ProcessSections.from_bytes(bytes(data), 0, object_reference_count=REFS)
        avatar = good.combat.combatants[0]
        avatar_fields = avatar.offset + 268 + 28
        for position, value, message in (
            (avatar.offset + 268, 2, "unsupported humanoid combatant version 2"),
            (avatar_fields, 3, "unsupported avatar combatant version 3"),
            (
                avatar_fields + 24,
                REFS,
                f"avatar combatant object-reference index {REFS}",
            ),
        ):
            bad = bytearray(data)
            struct.pack_into("<i", bad, position, value)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(U9ProcessSectionsError, message),
            ):
                U9ProcessSections.from_bytes(bytes(bad), 0, object_reference_count=REFS)

    def test_rejects_bad_combatant_common_part(self) -> None:
        with self.assertRaisesRegex(U9ProcessSectionsError, "combatant version 3"):
            U9ProcessSections.from_bytes(
                _sections(common_version=3), 0, object_reference_count=REFS
            )
        data = bytearray(_sections())
        good = U9ProcessSections.from_bytes(bytes(data), 0, object_reference_count=REFS)
        npc = good.combat.combatants[1]
        struct.pack_into("<i", data, npc.offset + 39 + 4, 495)
        with self.assertRaisesRegex(
            U9ProcessSectionsError, "NPC type 495, expected 494"
        ):
            U9ProcessSections.from_bytes(bytes(data), 0, object_reference_count=REFS)


class CombatantReconFieldTests(unittest.TestCase):
    def _parse(
        self, behaviors: tuple[int, ...], records: tuple[bytes, ...]
    ) -> U9CombatState:
        npc_records = bytearray(512 * 316)
        for npc_type, behavior in enumerate(behaviors):
            struct.pack_into("<i", npc_records, npc_type * 316 + 0x44, behavior)
        stream = (
            struct.pack("<2i", 3, len(records))
            + struct.pack(f"<{len(records)}i", *range(len(records)))
            + b"".join(records)
            + struct.pack("<3i", 0, -407, 17)
        )
        reader = _Reader(stream, 0)
        combat = U9CombatState.read(reader, bytes(npc_records))
        self.assertEqual(combat.end_offset, len(stream))
        self.assertEqual(combat.tail, (0, -407, 17))
        for previous, following in zip(combat.combatants, combat.combatants[1:]):
            self.assertEqual(previous.end_offset, following.offset)
        return combat

    def test_slasher_float_health_and_zombie_split_flag_boundaries(self) -> None:
        # Independent packed fixtures in retail stream order, including unaligned
        # floats and nonzero following words; shield HP is separate from NPC HP.
        slasher = struct.pack(
            "<iiIiiBBIIIffBBiII",
            3,
            55,
            1200,
            2,
            54,
            1,
            0,
            300,
            400,
            500,
            1200.0,
            960.0,
            1,
            2,
            -1,
            65535,
            64000,
        )
        zombie = struct.pack("<iiBii", 2, 500, 1, 3, 4)
        combat = self._parse(
            (6, 8), (_combatant_common(0) + slasher, _combatant_common(1) + zombie)
        )
        first, second = combat.combatants
        fields = first.trailing_fields[0]
        self.assertEqual(fields["avatar_tracking_distance"], 960.0)
        self.assertIsInstance(fields["avatar_tracking_distance"], float)
        self.assertEqual(fields["saved_health_maximum"], 65535)
        self.assertEqual(fields["saved_health_current"], 64000)
        self.assertEqual(fields["shield_hit_points"], 55)
        self.assertEqual(first.trailing, slasher)
        self.assertEqual(second.trailing_fields[0]["split_complete"], 1)
        self.assertEqual(second.trailing_fields[0]["next_state"], 4)
        self.assertEqual(second.trailing, zombie)

    def test_all_shared_wolf_layouts_expose_nonzero_restore_state(self) -> None:
        behaviors = (25, 26, 27, 30, 44)
        wolf = struct.pack("<7i3B2i", 3, 0, 1, 2, 192, 1600, 3200, 1, 0, 1, 800, 20000)
        records = []
        for npc_type, behavior in enumerate(behaviors):
            prefix = (
                struct.pack("<2i", 1, 2)
                if behavior == 30
                else (struct.pack("<2i", 2, 700) if behavior == 44 else b"")
            )
            records.append(prefix + wolf + _combatant_common(npc_type))
        combat = self._parse(behaviors, tuple(records))
        for record in combat.combatants:
            fields = record.leading_fields[-1]
            self.assertEqual(fields.kind, "wolf")
            self.assertEqual(fields["baseline_notice_distance"], 800)
            self.assertEqual(fields["notice_distance_restore_ms"], 20000)
            self.assertEqual(fields["notice_distance"], 3200)
            self.assertTrue(record.leading.endswith(wolf))


if __name__ == "__main__":
    unittest.main()
