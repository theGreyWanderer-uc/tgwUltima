from __future__ import annotations

import struct
import unittest

from titan.u9.process_data import (
    HANDLE_DATA_OFFSET,
    OBJECT_REFERENCE_DATA_OFFSET,
    U9CameraEffectState,
    U9CameraState,
    U9CameraControlState,
    U9AnimationControllerProcessState,
    U9HangingObjectProcessState,
    U9ItemHandleEntry,
    U9ItemHandleTable,
    U9ObjectReferenceEntry,
    U9ObjectReferenceTable,
    U9ParticleForcePresetState,
    U9ParticleForceState,
    U9ParticleGenerationState,
    U9ParticleInstanceState,
    U9ParticlePresetState,
    U9ParticleRecordCollection,
    U9ParticleRecordCollections,
    U9ParticleProcessState,
    U9PlayerProximityProcessState,
    U9PortableLightProcessState,
    U9ProcessDataPrefix,
    U9ProcessDataError,
    U9ProcessHeaderState,
    U9ProcessRecordPrefix,
    U9ProcessWorldState,
    U9ScriptedProcessState,
    U9ScriptTimerProcessState,
    U9TargetingState,
)


def _process_data(count: int = 4) -> bytes:
    table_end = OBJECT_REFERENCE_DATA_OFFSET + 12 + count * 12
    data = bytearray(table_end + 4)
    struct.pack_into("<II", data, 0, 8, 2)
    struct.pack_into("<III", data, OBJECT_REFERENCE_DATA_OFFSET, 1, count, 1)
    records = [
        (0, -1, 0),
        (2, -1, 0),
        (0, -1, 0),
        (1, 9, -0x1068),
    ]
    for index, record in enumerate(records[:count]):
        struct.pack_into(
            "<iii",
            data,
            OBJECT_REFERENCE_DATA_OFFSET + 12 + index * 12,
            *record,
        )
    struct.pack_into("<I", data, table_end, 2)
    return bytes(data)


def _process_prefix(
    *,
    effect_version: float = 1.1,
    effect_count: int = 8,
    has_temporary_camera: bool = False,
    process_type: int = 104,
    process_name: bytes = b"Poof",
    object_reference_indices: tuple[int, ...] = (),
    particle_version: int = 5,
    particle_counts: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
) -> bytes:
    data = bytearray(_process_data()[:-4])
    data += struct.pack(
        "<I3f3fiiB4fi",
        2,
        100.0,
        200.0,
        300.0,
        0.25,
        -0.5,
        0.75,
        323,
        2,
        1,
        60.0,
        1.0,
        8000.0,
        4000.0,
        effect_count,
    )
    effect_size = {1.0: 302, 1.1: 310}.get(effect_version, 310)
    for index in range(effect_count):
        effect = bytearray(effect_size)
        struct.pack_into("<f", effect, 0, effect_version)
        effect[-1] = index
        data += effect

    control = bytearray(180)
    struct.pack_into("<I", control, 0, 2)
    struct.pack_into("<3f", control, 4, 110.0, 210.0, 310.0)
    struct.pack_into("<2f", control, 16, 0.5, -0.25)
    struct.pack_into("<I", control, 24, 1)
    struct.pack_into("<5f", control, 28, 70.0, 450.0, 500.0, 1000.0, 1.6)
    struct.pack_into("<4I", control, 48, 0, 1, 0, 1)
    struct.pack_into("<I", control, 176, int(has_temporary_camera))
    data += control

    if not has_temporary_camera:
        data += struct.pack(
            "<Iiii3f3fii",
            0,
            1,
            2,
            1,
            250.0,
            500.0,
            1500.0,
            110.0,
            210.0,
            310.0,
            640,
            480,
        )
        data += struct.pack("<i", process_type)
        if process_type != -1:
            data += struct.pack(
                "<9i100s",
                2,
                1,
                0,
                0,
                30103,
                -1,
                -1,
                -1,
                0,
                process_name,
            )
            if process_type == 104:
                data += struct.pack("<ii", 0, len(object_reference_indices))
                data += struct.pack(
                    f"<{len(object_reference_indices)}i", *object_reference_indices
                )
                data += struct.pack("<i", -1)
                data += struct.pack(
                    "<iIBi5i", particle_version, 49, 0, 527, *particle_counts
                )
                collection_layouts = (
                    (
                        "particle_presets",
                        particle_counts[0],
                        1484 if particle_version == 3 else 1490,
                    ),
                    ("force_presets", particle_counts[3], 97),
                    ("forces", particle_counts[4], 24),
                    ("generations", particle_counts[1], 124),
                    ("particles", particle_counts[2], 196),
                )
                for name, count, record_size in collection_layouts:
                    for record_id in range(1, count + 1):
                        record = bytearray(record_size)
                        struct.pack_into("<i", record, 0, record_id)
                        if name == "force_presets":
                            record[:] = struct.pack(
                                "<iBiii3ffii3fi3f3fiiii",
                                record_id,
                                43,
                                100,
                                5,
                                9,
                                1.0,
                                2.0,
                                3.0,
                                0.75,
                                50,
                                -1,
                                1.0,
                                1.5,
                                2.0,
                                9999,
                                0.1,
                                0.2,
                                0.3,
                                4.0,
                                5.0,
                                6.0,
                                24,
                                -1,
                                12,
                                3,
                            )
                        elif name == "forces":
                            struct.pack_into(
                                "<i3fi",
                                record,
                                4,
                                100 + record_id,
                                float(record_id),
                                float(record_id + 1),
                                float(record_id + 2),
                                1,
                            )
                        elif name == "generations":
                            force_id = 1 if particle_counts[4] else -1
                            values = [1, -1, -1, -1]
                            values.extend([force_id] * 16)
                            values.extend([-1] * 10)
                            struct.pack_into("<30i", record, 4, *values)
                        elif name == "particles":
                            record[:] = struct.pack(
                                "<3i10i2i3f3f3f3f4f4f2iBHI4iIB5i",
                                record_id,
                                1,
                                -1,
                                *([-1] * 10),
                                120,
                                7,
                                10.0,
                                20.0,
                                30.0,
                                1.0,
                                2.0,
                                3.0,
                                0.0,
                                0.0,
                                0.0,
                                1.0,
                                1.0,
                                1.0,
                                0.0,
                                0.0,
                                0.0,
                                1.0,
                                0.0,
                                0.0,
                                0.0,
                                1.0,
                                5,
                                2,
                                2,
                                557,
                                0x200,
                                0,
                                0,
                                1,
                                -1,
                                0,
                                0,
                                0,
                                0,
                                0,
                                0,
                                3,
                            )
                        data += record
                data += struct.pack(
                    "<i9i100s", 70, 10, 1, 0, 0, 464, -1, -1, -1, 0, b"Torch"
                )
                data += struct.pack("<iiii", 0, 1, 3, 9)
                data += struct.pack("<iiHfIIII", 0, 3, 65535, 65535.0, 24, 0, 0, 0x09)
                data += struct.pack("<i", -1)
    return bytes(data)


def _hanging_object_process() -> bytes:
    data = bytearray(
        struct.pack("<i9i100s", 61, 7, 1, 0, 0, 10809, -1, -1, 0x3F, 0, b"Hanging")
    )
    data += struct.pack("<iiii", 0, 1, 3, 14)
    data += struct.pack("<iiiii128si", 0, 3, 0, 1, 0, b"motion", 0)
    values: list[int | float] = [
        2,
        1,
        22,
        45,
        4.0,
        3,
        17,
        45,
        4.0,
        0x02686032,
    ]
    values.extend(
        [
            1.0,
            0.0,
            0.0,
            0.0,
            0.999,
            0.01,
            0.02,
            0.03,
            0.998,
            0.02,
            0.03,
            0.04,
            0.997,
            0.03,
            0.0,
            0.0,
            0.996,
            0.0,
            0.0,
            0.04,
        ]
    )
    values.extend(
        [
            0.25,
            -0.5,
            1,
            0.75,
            525,
            19420,
            1.5,
            1,
            -1,
            1,
            0.5,
            759,
            8337,
            1.5,
            1,
            0,
            0,
            0.25,
            0.5,
            5,
            38573,
            308875,
            0,
            0.0,
            -1.0,
            0.0,
            0,
            0,
            0,
            0,
        ]
    )
    data += struct.pack("<iiiifiiifI20f2fifiifiiifiifiiiffiIIi3f4I", *values)
    return bytes(data)


def _script_timer_process() -> bytes:
    data = bytearray(
        struct.pack("<i9i100s", 62, 14, 1, 0, 0, 10809, -1, -1, 0x3F, 0, b"Timer")
    )
    data += struct.pack("<iiii", 0, 1, 3, 14)
    data += struct.pack("<iiiii128si", 0, 3, 0, 0x8000, 0, b"", 0)
    timer_flags = (100 << 16) | (3 << 8) | (4 << 4) | 0x0F
    data += struct.pack("<i12I", 1, timer_flags, 600, 4, 3, 400, 125, 1, 1, 0, 0, 0, 0)
    return bytes(data)


def _animation_controller_process() -> bytes:
    data = bytearray(struct.pack("<if", 98, 1.2))
    data += struct.pack(
        "<9i100s", 30, 1, 0, 0, 125, -1, -1, 0x3F, 0, b"LayeredAnimation"
    )
    data += struct.pack("<iiii", 0, 1, 3, 14)
    data += struct.pack(
        "<i3f2Bi3f3fB", 3, 1.0, 2.0, 3.0, 1, 0, 807, 4.0, 5.0, 6.0, 1.0, 1.0, 1.0, 1
    )
    data += struct.pack("<i32i", 3, 1, 2, 3, *([0] * 29))
    data += struct.pack("<i32i", 2, 4, 5, *([0] * 30))
    data += struct.pack("<3f2BIii", 0.25, 0.5, 0.75, 1, 0, 19, -1, 44)
    data += struct.pack("<i2i", 2, 1, 7)
    data += struct.pack("<ii", 1, 9)
    data += struct.pack("<fi", 1.0, 810)
    data += struct.pack(
        "<fiiiififiiB", 1.25, 100, 90, 80, 1000, 0.5, 100, 0.75, 120, 30, 1
    )
    data += struct.pack("<i", 15)
    data += b"".join(
        struct.pack("<iII", callback_id, callback_id + 1, callback_id + 2)
        for callback_id in range(4)
    )
    data += struct.pack("<fi", 1.0, -1) * 4
    data += struct.pack("<i", 1)
    data += struct.pack(
        "<fi3B10f3f3f12fB",
        1.0,
        20,
        1,
        0,
        1,
        -0.5,
        0.5,
        -1.0,
        1.0,
        -1.5,
        1.5,
        0.1,
        0.2,
        0.3,
        2.0,
        10.0,
        20.0,
        30.0,
        0.01,
        0.02,
        0.03,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0,
    )
    return bytes(data)


class ObjectReferenceTableTests(unittest.TestCase):
    def test_generalized_names_preserve_legacy_imports(self) -> None:
        self.assertIs(U9ItemHandleTable, U9ObjectReferenceTable)
        self.assertIs(U9ItemHandleEntry, U9ObjectReferenceEntry)
        self.assertEqual(HANDLE_DATA_OFFSET, OBJECT_REFERENCE_DATA_OFFSET)

        legacy_entry = U9ItemHandleEntry(
            index=7,
            usage_count=2,
            map_number=9,
            encoded_item_offset=-0x1068,
        )
        self.assertEqual(legacy_entry.reference_count, 2)
        self.assertEqual(legacy_entry.encoded_object_offset, -0x1068)

    def test_parses_dynamic_table_and_free_chain(self) -> None:
        table = U9ObjectReferenceTable.from_bytes(_process_data())
        self.assertEqual(table.count, 4)
        self.assertEqual(table.walk_free_chain(), (1, 2))
        self.assertEqual(table.fixed_entries[0].object_offset, 0x1068)
        self.assertEqual(table.end_offset, OBJECT_REFERENCE_DATA_OFFSET + 60)

    def test_preserves_serialized_reference_entry_semantics(self) -> None:
        table = U9ObjectReferenceTable.from_bytes(_process_data())

        free_entry = table.entries[1]
        self.assertTrue(free_entry.is_free)
        self.assertFalse(free_entry.is_live)
        self.assertEqual(free_entry.next_free_index, 2)

        fixed_entry = table.entries[3]
        self.assertTrue(fixed_entry.is_live)
        self.assertTrue(fixed_entry.is_fixed)
        self.assertEqual(fixed_entry.map_number, 9)
        self.assertEqual(fixed_entry.encoded_object_offset, -0x1068)
        self.assertEqual(fixed_entry.object_offset, 0x1068)

    def test_requires_following_camera_boundary(self) -> None:
        data = bytearray(_process_data())
        struct.pack_into("<I", data, len(data) - 4, 99)
        with self.assertRaisesRegex(U9ProcessDataError, "camera version"):
            U9ObjectReferenceTable.from_bytes(bytes(data))

    def test_rejects_broken_free_chain(self) -> None:
        data = bytearray(_process_data())
        struct.pack_into("<i", data, OBJECT_REFERENCE_DATA_OFFSET + 12 + 2 * 12, 1)
        with self.assertRaisesRegex(U9ProcessDataError, "cycles"):
            U9ObjectReferenceTable.from_bytes(bytes(data)).walk_free_chain()

    def test_rejects_negative_free_link(self) -> None:
        # A negative link must not index the tuple from its end.
        data = bytearray(_process_data())
        struct.pack_into("<i", data, OBJECT_REFERENCE_DATA_OFFSET + 12 + 2 * 12, -1)
        with self.assertRaisesRegex(U9ProcessDataError, "leaves table at entry -1"):
            U9ObjectReferenceTable.from_bytes(bytes(data)).walk_free_chain()


class ProcessDataPrefixTests(unittest.TestCase):
    def test_decodes_retail_particle_preset_fields_and_extensions(self) -> None:
        data = bytearray(1490)
        struct.pack_into("<iiBiiiBB", data, 0, 7, 81, 1, 120, 15, 3, 2, 1)
        struct.pack_into("<3f", data, 0x17, 10.0, 20.0, 30.0)
        struct.pack_into("<i", data, 0xDC, 1)
        data[0xF4:0xF6] = b"\xaa\x55"
        data[0xF6] = 1
        struct.pack_into("<Hi", data, 0xF7, 557, 12)
        data[0x133] = 1
        data[0x134:0x137] = bytes((10, 20, 30))
        struct.pack_into("<ii", data, 0x137, 100, 1200)
        struct.pack_into("<I", data, 0x141, 9999)
        data[0x145:0x148] = bytes((47, 1, 1))
        struct.pack_into("<H", data, 0x148, 60000)
        data[0x157:0x162] = bytes((1, 2, 3, 4, 5, 6, 7, 1, 8, 9, 10))
        struct.pack_into(
            "<4H8BI", data, 0x166, 42, 3, 0, 1, 255, 128, 0, 4, 2, 12, 1, 0, 33
        )
        data[0x183:0x187] = b"\x11\x22\x33\x44"
        struct.pack_into("<ii", data, 0x187, 7, 9)
        data[0x187 + 48] = 128
        struct.pack_into("<i", data, 0x187 + 49, 20)
        data[0x5BF] = 1
        struct.pack_into("<H4i", data, 0x5C0, 1141, 24, 5, 2, 3)

        record = U9ParticlePresetState.from_bytes(bytes(data), 0, version=5)

        self.assertEqual(record.record_id, 7)
        self.assertEqual(record.particle_id, 81)
        self.assertEqual(record.location, (10.0, 20.0, 30.0))
        self.assertEqual(record.version_5_item_extension, b"\xaa\x55")
        self.assertEqual(record.item_variants[0].object_type_id, 557)
        self.assertEqual(record.item_variants[0].swap_time_frames, 12)
        self.assertEqual(record.light_color, (10, 20, 30))
        self.assertEqual(record.sound_category_id, 47)
        self.assertEqual(record.spawn_mean_ramp_count, 1)
        self.assertEqual(record.light_diffusion_ramp_count, 10)
        self.assertEqual(record.camera_filter_texture.texture_id, 42)
        self.assertEqual(record.camera_filter_texture.animation_time, 33)
        self.assertEqual(record.version_5_ramp_extension, b"\x11\x22\x33\x44")
        self.assertEqual(record.ramp_slots[0].spawn_mean_value, 7)
        self.assertEqual(record.ramp_slots[0].object_translucency, 128)
        self.assertEqual(record.ramp_slots[0].object_translucency_frame, 20)
        self.assertEqual(record.skeleton_appearance_id, 1141)
        self.assertEqual(record.source_object_reference_index, 2)
        self.assertEqual(record.skeleton_object_reference_index, 3)
        self.assertEqual(record.end_offset, 1490)

    def test_decodes_known_older_particle_preset_without_extensions(self) -> None:
        data = bytearray(1484)
        struct.pack_into("<i", data, 0, 7)

        record = U9ParticlePresetState.from_bytes(bytes(data), 0, version=3)

        self.assertEqual(record.record_id, 7)
        self.assertEqual(record.version_5_item_extension, b"")
        self.assertEqual(record.version_5_ramp_extension, b"")
        self.assertEqual(record.end_offset, 1484)

    def test_rejects_particle_preset_counts_above_stored_capacity(self) -> None:
        invalid_items = bytearray(1490)
        struct.pack_into("<ii", invalid_items, 0, 1, 0)
        struct.pack_into("<i", invalid_items, 0xDC, 11)
        with self.assertRaisesRegex(U9ProcessDataError, "object-type count 11"):
            U9ParticlePresetState.from_bytes(bytes(invalid_items), 0, version=5)

        invalid_ramp = bytearray(1490)
        struct.pack_into("<ii", invalid_ramp, 0, 1, 0)
        invalid_ramp[0x157] = 11
        with self.assertRaisesRegex(U9ProcessDataError, "ramp count above 10"):
            U9ParticlePresetState.from_bytes(bytes(invalid_ramp), 0, version=5)

    def test_decodes_particle_force_preset_fields(self) -> None:
        data = struct.pack(
            "<iBiii3ffii3fi3f3fiiii",
            7,
            43,
            100,
            5,
            9,
            1.0,
            2.0,
            3.0,
            0.75,
            50,
            -1,
            1.0,
            1.5,
            2.0,
            9999,
            0.1,
            0.2,
            0.3,
            4.0,
            5.0,
            6.0,
            24,
            -1,
            12,
            3,
        )

        record = U9ParticleForcePresetState.from_bytes(data, 0)

        self.assertEqual(record.record_id, 7)
        self.assertEqual(record.force_type, 43)
        self.assertEqual(record.lifetime, 100)
        self.assertEqual(record.initial_age, 5)
        self.assertEqual(record.trigger_age, 9)
        self.assertEqual(record.location, (1.0, 2.0, 3.0))
        self.assertEqual(record.strength, 0.75)
        self.assertEqual(record.influence_distance, 50)
        self.assertEqual(record.inner_radius, -1)
        self.assertEqual(record.scale, (1.0, 1.5, 2.0))
        self.assertEqual(record.speed_limit, 9999)
        self.assertAlmostEqual(record.twist_velocity[0], 0.1)
        self.assertEqual(record.offset_vector, (4.0, 5.0, 6.0))
        self.assertEqual(record.element_id, 24)
        self.assertEqual(record.hard_point_id, -1)
        self.assertEqual(record.numeric_type, 12)
        self.assertEqual(record.object_reference_index, 3)
        self.assertEqual(record.end_offset, 97)

    def test_rejects_truncated_particle_force_preset(self) -> None:
        with self.assertRaisesRegex(
            U9ProcessDataError, "truncated particle force preset"
        ):
            U9ParticleForcePresetState.from_bytes(bytes(96), 0)

    def test_decodes_particle_force_record_fields(self) -> None:
        data = struct.pack("<ii3fi", 7, 42, 1.25, -2.5, 3.75, 4)

        record = U9ParticleForceState.from_bytes(data, 0)

        self.assertEqual(record.record_id, 7)
        self.assertEqual(record.age, 42)
        self.assertEqual(record.location, (1.25, -2.5, 3.75))
        self.assertEqual(record.preset_id, 4)
        self.assertEqual(record.end_offset, 24)

    def test_rejects_truncated_particle_force_record(self) -> None:
        with self.assertRaisesRegex(U9ProcessDataError, "truncated particle force"):
            U9ParticleForceState.from_bytes(bytes(23), 0)

    def test_decodes_particle_generation_record_fields(self) -> None:
        force_slots = (
            10,
            20,
            30,
            40,
            11,
            21,
            31,
            41,
            12,
            22,
            32,
            42,
            13,
            23,
            33,
            43,
        )
        data = struct.pack(
            "<31i",
            7,
            3,
            8,
            9,
            10,
            *force_slots,
            50,
            51,
            52,
            53,
            54,
            55,
            56,
            57,
            58,
            59,
        )

        record = U9ParticleGenerationState.from_bytes(data, 0)

        self.assertEqual(record.record_id, 7)
        self.assertEqual(record.particle_preset_id, 3)
        self.assertEqual(record.birth_generation_id, 8)
        self.assertEqual(record.lifetime_generation_id, 9)
        self.assertEqual(record.death_generation_id, 10)
        self.assertEqual(record.birth_force_ids, (10, 11, 12, 13))
        self.assertEqual(record.lifetime_force_ids, (20, 21, 22, 23))
        self.assertEqual(record.death_force_ids, (30, 31, 32, 33))
        self.assertEqual(record.slave_force_ids, (40, 41, 42, 43))
        self.assertEqual(record.slave_generation_ids, tuple(range(50, 60)))
        self.assertEqual(record.end_offset, 124)

    def test_rejects_truncated_particle_generation_record(self) -> None:
        with self.assertRaisesRegex(
            U9ProcessDataError, "truncated particle generation"
        ):
            U9ParticleGenerationState.from_bytes(bytes(123), 0)

    def test_decodes_particle_instance_fields(self) -> None:
        data = struct.pack(
            "<3i10i2i3f3f3f3f4f4f2iBHI4iIB5i",
            7,
            3,
            12,
            *range(20, 30),
            120,
            7,
            10.0,
            20.0,
            30.0,
            1.0,
            2.0,
            3.0,
            0.25,
            0.5,
            0.75,
            1.0,
            1.5,
            2.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.1,
            0.2,
            0.3,
            0.9,
            5,
            0x102,
            2,
            557,
            0x80000200,
            4,
            8,
            13,
            -1,
            2585,
            1,
            30,
            101,
            2,
            31,
            32,
        )

        record = U9ParticleInstanceState.from_bytes(data, 0)

        self.assertEqual(record.record_id, 7)
        self.assertEqual(record.generation_id, 3)
        self.assertEqual(record.parent_particle_id, 12)
        self.assertEqual(record.child_particle_ids, tuple(range(20, 30)))
        self.assertEqual(record.lifetime, 120)
        self.assertEqual(record.age, 7)
        self.assertEqual(record.location, (10.0, 20.0, 30.0))
        self.assertEqual(record.velocity, (1.0, 2.0, 3.0))
        self.assertEqual(record.snap_velocity, (0.25, 0.5, 0.75))
        self.assertEqual(record.scale, (1.0, 1.5, 2.0))
        self.assertEqual(record.orientation_quaternion, (0.0, 0.0, 0.0, 1.0))
        self.assertAlmostEqual(record.rotation_quaternion[0], 0.1)
        self.assertEqual(record.spawn_mean_lifetime, 5)
        self.assertEqual(record.spawn_pulse_count, 0x102)
        self.assertEqual(record.spawn_pulse_count_byte, 2)
        self.assertTrue(record.pulse_count_byte_matches)
        self.assertEqual(record.object_type_id, 557)
        self.assertEqual(record.object_status_flags, 0x80000200)
        self.assertEqual(record.swap_sequence, 4)
        self.assertEqual(record.sequence_index, 8)
        self.assertEqual(record.swap_elapsed_frames, 13)
        self.assertEqual(record.attached_element_id, -1)
        self.assertEqual(record.sound_id, 2585)
        self.assertEqual(record.light_source_flag, 1)
        self.assertTrue(record.has_light_source)
        self.assertEqual(record.callback_id, 30)
        self.assertEqual(record.callback_effect_id, 101)
        self.assertEqual(record.callback_magic_type, 2)
        self.assertEqual(record.callback_caster_reference_index, 31)
        self.assertEqual(record.object_reference_index, 32)
        self.assertEqual(record.end_offset, 196)

    def test_rejects_truncated_particle_instance(self) -> None:
        with self.assertRaisesRegex(U9ProcessDataError, "truncated particle instance"):
            U9ParticleInstanceState.from_bytes(bytes(195), 0)

    def test_parses_camera_control_and_typed_process_boundary(self) -> None:
        prefix = U9ProcessDataPrefix.from_bytes(_process_prefix())

        self.assertIsInstance(prefix.camera, U9CameraState)
        self.assertEqual(prefix.camera.focus_position, (100.0, 200.0, 300.0))
        self.assertEqual(prefix.camera.focus_distance, 323)
        self.assertEqual(prefix.camera.mode, 2)
        self.assertTrue(prefix.camera.exclusive_interface)
        self.assertEqual(len(prefix.camera.effects), 8)
        self.assertIsInstance(prefix.camera.effects[0], U9CameraEffectState)
        self.assertAlmostEqual(prefix.camera.effects[0].version, 1.1)
        self.assertEqual(prefix.camera.effects[0].size, 310)

        self.assertIsInstance(prefix.camera_control, U9CameraControlState)
        self.assertEqual(prefix.camera_control.target_position, (110.0, 210.0, 310.0))
        self.assertEqual(prefix.camera_control.current_distance, 450.0)
        self.assertTrue(prefix.camera_control.underwater)
        self.assertFalse(prefix.camera_control.has_temporary_camera)
        self.assertIsInstance(prefix.camera_control.targeting, U9TargetingState)
        self.assertEqual(prefix.camera_control.targeting.ranges, (250.0, 500.0, 1500.0))
        self.assertEqual(prefix.process_list_offset, prefix.camera_control.end_offset)
        self.assertEqual(prefix.first_process_type, 104)
        self.assertIsInstance(prefix.first_process, U9ProcessRecordPrefix)
        assert prefix.first_process is not None
        self.assertIsInstance(prefix.first_process.header, U9ProcessHeaderState)
        self.assertEqual(prefix.first_process.header.process_id, 2)
        self.assertEqual(prefix.first_process.header.category, 1)
        self.assertEqual(prefix.first_process.header.run_count, 30103)
        self.assertEqual(prefix.first_process.header.name, "Poof")
        self.assertEqual(prefix.first_process.header.execution_mask, -1)
        self.assertIsInstance(prefix.first_process.world_state, U9ProcessWorldState)
        assert prefix.first_process.world_state is not None
        self.assertEqual(prefix.first_process.world_state.version, 0)
        self.assertEqual(prefix.first_process.world_state.object_reference_indices, ())
        self.assertEqual(prefix.first_process.world_state.map_number, -1)
        self.assertEqual(
            prefix.first_process.payload_offset,
            prefix.first_process.world_state.end_offset,
        )
        self.assertIsInstance(
            prefix.first_process.particle_state, U9ParticleProcessState
        )
        assert prefix.first_process.particle_state is not None
        self.assertEqual(prefix.first_process.particle_state.version, 5)
        self.assertEqual(prefix.first_process.particle_state.animation_time, 49)
        self.assertEqual(prefix.first_process.particle_state.next_particle_id, 527)
        self.assertEqual(prefix.first_process.particle_state.particle_preset_count, 0)
        self.assertEqual(prefix.first_process.particle_state.particle_count, 0)
        self.assertEqual(prefix.first_process.particle_state.force_count, 0)
        self.assertEqual(
            prefix.first_process.decoded_prefix_end_offset,
            prefix.first_process.particle_state.records.end_offset,
        )
        self.assertEqual(prefix.next_process_type, 70)

        assert prefix.next_process_header is not None
        self.assertEqual(prefix.next_process_header.name, "Torch")
        self.assertEqual(len(prefix.following_processes), 1)
        light = prefix.following_processes[0]
        self.assertIsInstance(light, U9PortableLightProcessState)
        assert isinstance(light, U9PortableLightProcessState)
        self.assertEqual(light.light_object_reference_index, 3)
        self.assertEqual(light.maximum_fuel, 65535)
        self.assertEqual(light.current_fuel, 65535.0)
        self.assertEqual(light.update_elapsed, 24)
        self.assertTrue(light.is_on)
        self.assertTrue(light.is_automatic)
        self.assertFalse(light.uses_skeletal_flame)
        self.assertEqual(prefix.terminator_offset, light.end_offset)
        self.assertIsNone(prefix.blocked_process_type)

    def test_traverses_player_proximity_then_portable_light_processes(self) -> None:
        original = _process_prefix()
        original_prefix = U9ProcessDataPrefix.from_bytes(original)
        assert original_prefix.next_process_offset is not None
        data = bytearray(original[: original_prefix.next_process_offset])
        data += struct.pack(
            "<i9i100s", 80, 4, 1, 0, 0, 120, -1, -1, 0x3F, 0, b"Proximity"
        )
        data += struct.pack("<iiii", 0, 1, 3, 14)
        data += struct.pack("<iiiii128si", 0, 3, 0, 1, 0, b"temp", 7)
        data += struct.pack(
            "<iffI3fiiii4I",
            1,
            90000.0,
            122500.0,
            1,
            4645.0,
            10042.0,
            1753.0,
            4645,
            10042,
            200,
            1,
            0,
            0,
            0,
            0,
        )
        data += struct.pack("<i9i100s", 70, 5, 1, 0, 0, 121, -1, -1, -1, 0, b"Light")
        data += struct.pack("<iiii", 0, 1, 3, 14)
        data += struct.pack("<iiHfIIII", 0, 3, 1000, 750.5, 12, 4, 8, 0x12)
        data += struct.pack("<i", -1)

        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))

        self.assertEqual(len(prefix.following_processes), 2)
        proximity, light = prefix.following_processes
        self.assertIsInstance(proximity, U9PlayerProximityProcessState)
        assert isinstance(proximity, U9PlayerProximityProcessState)
        self.assertIsInstance(proximity.scripted_state, U9ScriptedProcessState)
        self.assertEqual(proximity.scripted_state.primary_object_reference_index, 3)
        self.assertEqual(proximity.scripted_state.user_object_reference_index, 0)
        self.assertEqual(proximity.scripted_state.temporary_buffer[:4], b"temp")
        self.assertEqual(proximity.location, (4645.0, 10042.0, 1753.0))
        self.assertTrue(proximity.uses_double_threshold)
        self.assertTrue(proximity.enabled)
        self.assertEqual(proximity.reserved, (0, 0, 0, 0))
        self.assertIsInstance(light, U9PortableLightProcessState)
        assert isinstance(light, U9PortableLightProcessState)
        self.assertEqual(light.current_fuel, 750.5)
        self.assertTrue(light.uses_skeletal_flame)
        self.assertTrue(light.has_manual_override)
        self.assertEqual(prefix.terminator_offset, light.end_offset)

    def test_traverses_hanging_object_motion_and_decodes_configuration(self) -> None:
        original = _process_prefix()
        original_prefix = U9ProcessDataPrefix.from_bytes(original)
        assert original_prefix.next_process_offset is not None
        data = (
            original[: original_prefix.next_process_offset]
            + _hanging_object_process()
            + original[original_prefix.next_process_offset :]
        )

        prefix = U9ProcessDataPrefix.from_bytes(data)

        self.assertEqual(len(prefix.following_processes), 2)
        hanging, light = prefix.following_processes
        self.assertIsInstance(hanging, U9HangingObjectProcessState)
        assert isinstance(hanging, U9HangingObjectProcessState)
        self.assertEqual(hanging.version, 2)
        self.assertEqual(hanging.world_state.object_reference_indices, (3,))
        self.assertEqual(hanging.scripted_state.primary_object_reference_index, 3)
        self.assertEqual(hanging.swing_period, 22)
        self.assertEqual(hanging.maximum_swing_angle, 45)
        self.assertEqual(hanging.turn_period, 17)
        self.assertEqual(hanging.maximum_turn_angle, 45)
        self.assertEqual(hanging.initial_orientation, (1.0, 0.0, 0.0, 0.0))
        self.assertEqual(hanging.facing, (0.0, -1.0, 0.0))
        self.assertTrue(hanging.is_swinging)
        self.assertTrue(hanging.is_turning)
        self.assertEqual(hanging.swing_time_ms, 525)
        self.assertEqual(hanging.turn_time_ms, 759)
        self.assertTrue(hanging.configured_swingable)
        self.assertEqual(hanging.configured_swing_period, 22)
        self.assertEqual(hanging.configured_maximum_swing_angle, 45)
        self.assertEqual(hanging.configured_swing_half_life, 4)
        self.assertEqual(hanging.configured_turning_type, 3)
        self.assertEqual(hanging.configured_turn_period, 17)
        self.assertTrue(hanging.configured_turn_limit_is_degrees)
        self.assertEqual(hanging.configured_turn_limit, 45)
        self.assertEqual(hanging.configured_turn_half_life, 4)
        self.assertEqual(hanging.reserved, (0, 0, 0, 0))
        self.assertEqual(hanging.end_offset, light.offset)
        self.assertIsInstance(light, U9PortableLightProcessState)

    def test_rejects_bad_hanging_object_version_and_nonfinite_motion(self) -> None:
        original = _process_prefix()
        original_prefix = U9ProcessDataPrefix.from_bytes(original)
        assert original_prefix.next_process_offset is not None
        data = bytearray(
            original[: original_prefix.next_process_offset]
            + _hanging_object_process()
            + original[original_prefix.next_process_offset :]
        )
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        hanging = prefix.following_processes[0]
        assert isinstance(hanging, U9HangingObjectProcessState)
        payload_offset = hanging.scripted_state.end_offset

        bad_version = bytearray(data)
        struct.pack_into("<i", bad_version, payload_offset, 3)
        with self.assertRaisesRegex(U9ProcessDataError, "hanging-object version 3"):
            U9ProcessDataPrefix.from_bytes(bytes(bad_version))

        nonfinite = bytearray(data)
        struct.pack_into("<f", nonfinite, payload_offset + 16, float("inf"))
        with self.assertRaisesRegex(U9ProcessDataError, "non-finite"):
            U9ProcessDataPrefix.from_bytes(bytes(nonfinite))

    def test_traverses_script_timer_and_decodes_configuration(self) -> None:
        original = _process_prefix()
        original_prefix = U9ProcessDataPrefix.from_bytes(original)
        assert original_prefix.next_process_offset is not None
        data = (
            original[: original_prefix.next_process_offset]
            + _script_timer_process()
            + original[original_prefix.next_process_offset :]
        )

        prefix = U9ProcessDataPrefix.from_bytes(data)

        self.assertEqual(len(prefix.following_processes), 2)
        timer, light = prefix.following_processes
        self.assertIsInstance(timer, U9ScriptTimerProcessState)
        assert isinstance(timer, U9ScriptTimerProcessState)
        self.assertEqual(timer.version, 1)
        self.assertEqual(timer.world_state.object_reference_indices, (3,))
        self.assertEqual(timer.scripted_state.primary_object_reference_index, 3)
        self.assertEqual(timer.phase_1_duration, 600)
        self.assertEqual(timer.phase_2_duration, 400)
        self.assertEqual(timer.accumulated_time, 125)
        self.assertTrue(timer.has_started)
        self.assertEqual(timer.phase, 1)
        self.assertTrue(timer.runs_continuously)
        self.assertTrue(timer.starts_in_fast_area)
        self.assertTrue(timer.fast_area_stop_flag)
        self.assertTrue(timer.is_quiet_outside_fast_area)
        self.assertEqual(timer.configured_dual_percentage, 40)
        self.assertEqual(timer.configured_time_system, 3)
        self.assertEqual(timer.configured_duration, 100)
        self.assertEqual(timer.reserved, (0, 0, 0, 0))
        self.assertEqual(timer.end_offset, light.offset)
        self.assertIsInstance(light, U9PortableLightProcessState)

    def test_rejects_bad_script_timer_version(self) -> None:
        original = _process_prefix()
        original_prefix = U9ProcessDataPrefix.from_bytes(original)
        assert original_prefix.next_process_offset is not None
        data = bytearray(
            original[: original_prefix.next_process_offset]
            + _script_timer_process()
            + original[original_prefix.next_process_offset :]
        )
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        timer = prefix.following_processes[0]
        assert isinstance(timer, U9ScriptTimerProcessState)

        struct.pack_into("<i", data, timer.scripted_state.end_offset, 2)
        with self.assertRaisesRegex(U9ProcessDataError, "script-timer version 2"):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_traverses_layered_animation_controller(self) -> None:
        original = _process_prefix()
        original_prefix = U9ProcessDataPrefix.from_bytes(original)
        assert original_prefix.next_process_offset is not None
        data = (
            original[: original_prefix.next_process_offset]
            + _animation_controller_process()
            + original[original_prefix.next_process_offset :]
        )

        prefix = U9ProcessDataPrefix.from_bytes(data)

        self.assertEqual(len(prefix.following_processes), 2)
        controller, light = prefix.following_processes
        self.assertIsInstance(controller, U9AnimationControllerProcessState)
        assert isinstance(controller, U9AnimationControllerProcessState)
        self.assertAlmostEqual(controller.version, 1.2)
        self.assertEqual(controller.header.serialized_prefix_size, 8)
        self.assertEqual(controller.world_state.object_reference_indices, (3,))
        self.assertEqual(controller.object_reference_index, 3)
        self.assertEqual(controller.initial_position, (1.0, 2.0, 3.0))
        self.assertTrue(controller.calculates_transforms)
        self.assertEqual(controller.last_animation_id, 807)
        self.assertTrue(controller.scales_translation)
        self.assertEqual(controller.upper_limb_ids, (1, 2, 3))
        self.assertEqual(controller.lower_limb_ids, (4, 5))
        self.assertEqual(controller.included_limb_ids, (1, 7))
        self.assertEqual(controller.excluded_limb_ids, (9,))
        self.assertEqual(len(controller.animation_tracks), 5)
        active = controller.animation_tracks[0]
        self.assertTrue(active.active)
        self.assertEqual(active.animation_id, 810)
        self.assertEqual(active.current_time_ms, 100)
        self.assertEqual(active.rotation_blend_amount, 0.5)
        self.assertTrue(active.reverse)
        self.assertEqual(active.callbacks[3].callback_id, 3)
        self.assertFalse(controller.animation_tracks[1].active)
        self.assertEqual(len(controller.kinematic_tracks), 1)
        kinematic = controller.kinematic_tracks[0]
        self.assertEqual(kinematic.limb_id, 20)
        self.assertTrue(kinematic.constrain_pitch)
        self.assertFalse(kinematic.constrain_roll)
        self.assertEqual(kinematic.look_point, (10.0, 20.0, 30.0))
        self.assertEqual(len(kinematic.reference_transform), 12)
        self.assertEqual(controller.end_offset, light.offset)

    def test_rejects_bad_animation_controller_versions_and_reference(self) -> None:
        original = _process_prefix()
        original_prefix = U9ProcessDataPrefix.from_bytes(original)
        assert original_prefix.next_process_offset is not None
        record = _animation_controller_process()
        data = bytearray(
            original[: original_prefix.next_process_offset]
            + record
            + original[original_prefix.next_process_offset :]
        )
        process_offset = original_prefix.next_process_offset

        bad_version = bytearray(data)
        struct.pack_into("<f", bad_version, process_offset + 4, 1.1)
        with self.assertRaisesRegex(U9ProcessDataError, "animation-controller version"):
            U9ProcessDataPrefix.from_bytes(bytes(bad_version))

        parsed = U9ProcessDataPrefix.from_bytes(bytes(data))
        controller = parsed.following_processes[0]
        assert isinstance(controller, U9AnimationControllerProcessState)
        bad_reference = bytearray(data)
        struct.pack_into(
            "<i",
            bad_reference,
            process_offset + (controller.world_state.end_offset - controller.offset),
            4,
        )
        with self.assertRaisesRegex(U9ProcessDataError, "object-reference index 4"):
            U9ProcessDataPrefix.from_bytes(bytes(bad_reference))

        bad_track_version = bytearray(data)
        first_track_offset = controller.animation_tracks[0].offset
        struct.pack_into("<f", bad_track_version, first_track_offset, 1.1)
        with self.assertRaisesRegex(U9ProcessDataError, "animation-track version"):
            U9ProcessDataPrefix.from_bytes(bytes(bad_track_version))

    def test_stops_before_unknown_process_without_parsing_a_false_header(self) -> None:
        original = _process_prefix()
        original_prefix = U9ProcessDataPrefix.from_bytes(original)
        assert original_prefix.next_process_offset is not None
        data = original[: original_prefix.next_process_offset] + struct.pack(
            "<if", 213, 1.2
        )

        prefix = U9ProcessDataPrefix.from_bytes(data)

        self.assertEqual(prefix.next_process_type, 213)
        self.assertEqual(prefix.blocked_process_type, 213)
        self.assertEqual(prefix.blocked_process_offset, prefix.next_process_offset)
        self.assertIsNone(prefix.next_process_header)
        self.assertEqual(prefix.following_processes, ())
        self.assertIsNone(prefix.terminator_offset)

    def test_rejects_bad_supported_process_version_and_reference(self) -> None:
        original = bytearray(_process_prefix())
        prefix = U9ProcessDataPrefix.from_bytes(bytes(original))
        light = prefix.following_processes[0]
        assert isinstance(light, U9PortableLightProcessState)
        payload_offset = light.world_state.end_offset

        bad_version = bytearray(original)
        struct.pack_into("<i", bad_version, payload_offset, 1)
        with self.assertRaisesRegex(U9ProcessDataError, "portable-light version 1"):
            U9ProcessDataPrefix.from_bytes(bytes(bad_version))

        bad_reference = bytearray(original)
        struct.pack_into("<i", bad_reference, payload_offset + 4, 4)
        with self.assertRaisesRegex(U9ProcessDataError, "object-reference index 4"):
            U9ProcessDataPrefix.from_bytes(bytes(bad_reference))

    def test_accepts_older_camera_effect_records(self) -> None:
        prefix = U9ProcessDataPrefix.from_bytes(
            _process_prefix(effect_version=1.0, effect_count=6)
        )
        self.assertEqual(len(prefix.camera.effects), 6)
        self.assertEqual({effect.size for effect in prefix.camera.effects}, {302})
        self.assertEqual(prefix.first_process_type, 104)

    def test_parses_older_camera_control_versions(self) -> None:
        version_zero = U9CameraControlState.from_bytes(
            struct.pack("<I3f2fI", 0, 1.0, 2.0, 3.0, 0.25, -0.5, 0), 0
        )
        self.assertEqual(version_zero.target_position, (1.0, 2.0, 3.0))
        self.assertIsNone(version_zero.current_distance)
        self.assertEqual(version_zero.end_offset, 28)

        version_one_data = bytearray(180)
        struct.pack_into("<I", version_one_data, 0, 1)
        version_one = U9CameraControlState.from_bytes(bytes(version_one_data), 0)
        self.assertEqual(version_one.version, 1)
        self.assertIsNone(version_one.targeting)
        self.assertEqual(version_one.end_offset, 180)

    def test_stops_at_undecoded_temporary_camera_state(self) -> None:
        prefix = U9ProcessDataPrefix.from_bytes(
            _process_prefix(has_temporary_camera=True)
        )
        self.assertTrue(prefix.camera_control.has_temporary_camera)
        self.assertIsNone(prefix.camera_control.targeting)
        self.assertIsNone(prefix.process_list_offset)
        self.assertIsNone(prefix.first_process_type)

    def test_rejects_unknown_camera_effect_version(self) -> None:
        with self.assertRaisesRegex(U9ProcessDataError, "camera-effect version"):
            U9ProcessDataPrefix.from_bytes(_process_prefix(effect_version=9.0))

    def test_rejects_truncated_camera_effect(self) -> None:
        data = _process_prefix()[
            : U9ObjectReferenceTable.from_bytes(_process_prefix()).end_offset + 100
        ]
        with self.assertRaisesRegex(U9ProcessDataError, "truncated camera-effect"):
            U9ProcessDataPrefix.from_bytes(data)

    def test_rejects_invalid_first_process_type(self) -> None:
        data = bytearray(_process_prefix())
        process_offset = U9ProcessDataPrefix.from_bytes(bytes(data)).process_list_offset
        assert process_offset is not None
        struct.pack_into("<i", data, process_offset, 0xE5)
        with self.assertRaisesRegex(U9ProcessDataError, "invalid first process type"):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_parses_first_process_object_associations(self) -> None:
        prefix = U9ProcessDataPrefix.from_bytes(
            _process_prefix(object_reference_indices=(0, 3))
        )
        assert prefix.first_process is not None
        assert prefix.first_process.world_state is not None
        self.assertEqual(
            prefix.first_process.world_state.object_reference_indices, (0, 3)
        )

    def test_preserves_full_fixed_process_name_without_nul(self) -> None:
        prefix = U9ProcessDataPrefix.from_bytes(
            _process_prefix(process_name=b"x" * 100)
        )
        assert prefix.first_process is not None
        self.assertEqual(prefix.first_process.header.name, "x" * 100)
        self.assertEqual(prefix.first_process.header.raw_name, b"x" * 100)

    def test_rejects_truncated_first_process_header(self) -> None:
        data = _process_prefix()
        prefix = U9ProcessDataPrefix.from_bytes(data)
        assert prefix.process_list_offset is not None
        with self.assertRaisesRegex(U9ProcessDataError, "truncated process header"):
            U9ProcessDataPrefix.from_bytes(data[: prefix.process_list_offset + 20])

    def test_rejects_too_many_first_process_object_associations(self) -> None:
        data = bytearray(_process_prefix())
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        extension_offset = prefix.first_process.header.end_offset
        struct.pack_into("<i", data, extension_offset + 4, 11)
        with self.assertRaisesRegex(U9ProcessDataError, "association count 11"):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_rejects_out_of_range_first_process_object_reference(self) -> None:
        with self.assertRaisesRegex(U9ProcessDataError, "object-reference index 4"):
            U9ProcessDataPrefix.from_bytes(
                _process_prefix(object_reference_indices=(4,))
            )

    def test_preserves_nonzero_particle_translation_flag(self) -> None:
        data = bytearray(_process_prefix())
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        particle_offset = prefix.first_process.payload_offset
        data[particle_offset + 8] = 0xFF

        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        self.assertEqual(prefix.first_process.particle_state.translation_flag, 0xFF)
        self.assertTrue(prefix.first_process.particle_state.translation_pending)

    def test_accepts_known_older_particle_state_prefix(self) -> None:
        data = bytearray(_process_prefix())
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        struct.pack_into("<i", data, prefix.first_process.payload_offset, 3)

        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        self.assertEqual(prefix.first_process.particle_state.version, 3)

    def test_rejects_unsupported_particle_state_version(self) -> None:
        data = bytearray(_process_prefix())
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        struct.pack_into("<i", data, prefix.first_process.payload_offset, 4)
        with self.assertRaisesRegex(U9ProcessDataError, "particle-state version 4"):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_parses_all_particle_record_collection_boundaries(self) -> None:
        prefix = U9ProcessDataPrefix.from_bytes(
            _process_prefix(particle_counts=(2, 2, 3, 1, 1))
        )
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        collections = prefix.first_process.particle_state.records
        self.assertIsInstance(collections, U9ParticleRecordCollections)

        expected = (
            (collections.particle_presets, 2, 1490),
            (collections.force_presets, 1, 97),
            (collections.forces, 1, 24),
            (collections.generations, 2, 124),
            (collections.particles, 3, 196),
        )
        for collection, count, size in expected:
            self.assertIsInstance(collection, U9ParticleRecordCollection)
            self.assertEqual(collection.count, count)
            self.assertEqual(collection.record_size, size)
            self.assertEqual(collection.record_ids, tuple(range(1, count + 1)))

        self.assertEqual(
            collections.force_presets.offset, collections.particle_presets.end_offset
        )
        self.assertEqual(
            collections.forces.offset, collections.force_presets.end_offset
        )
        self.assertEqual(collections.generations.offset, collections.forces.end_offset)
        self.assertEqual(
            collections.particles.offset, collections.generations.end_offset
        )
        self.assertEqual(prefix.next_process_offset, collections.end_offset)
        self.assertEqual(prefix.next_process_type, 70)

        self.assertEqual(len(collections.force_preset_records), 1)
        self.assertEqual(len(collections.particle_preset_records), 2)
        self.assertEqual(collections.particle_preset_records[0].record_id, 1)
        self.assertEqual(collections.force_preset_records[0].force_type, 43)
        self.assertEqual(collections.force_preset_records[0].object_reference_index, 3)
        self.assertEqual(len(collections.force_records), 1)
        self.assertEqual(collections.force_records[0].age, 101)
        self.assertEqual(collections.force_records[0].location, (1.0, 2.0, 3.0))
        self.assertEqual(collections.force_records[0].preset_id, 1)
        self.assertEqual(len(collections.generation_records), 2)
        self.assertEqual(collections.generation_records[0].particle_preset_id, 1)
        self.assertEqual(collections.generation_records[0].birth_force_ids, (1,) * 4)
        self.assertEqual(
            collections.generation_records[0].slave_generation_ids, (-1,) * 10
        )
        self.assertEqual(len(collections.particle_records), 3)
        self.assertEqual(collections.particle_records[0].generation_id, 1)
        self.assertEqual(collections.particle_records[0].object_type_id, 557)
        self.assertEqual(collections.particle_records[0].object_reference_index, 3)

    def test_uses_known_version_three_particle_preset_size(self) -> None:
        prefix = U9ProcessDataPrefix.from_bytes(
            _process_prefix(particle_version=3, particle_counts=(1, 0, 0, 0, 0))
        )
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        collection = prefix.first_process.particle_state.records.particle_presets
        self.assertEqual(collection.record_size, 1484)
        self.assertEqual(prefix.next_process_type, 70)

    def test_rejects_nonsequential_particle_record_id(self) -> None:
        data = bytearray(_process_prefix(particle_counts=(1, 0, 0, 0, 0)))
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        record_offset = prefix.first_process.particle_state.records.offset
        struct.pack_into("<i", data, record_offset, 7)
        with self.assertRaisesRegex(U9ProcessDataError, "record 1 has ID 7"):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_rejects_truncated_particle_record_collection(self) -> None:
        data = _process_prefix(particle_counts=(1, 0, 0, 0, 0))
        prefix = U9ProcessDataPrefix.from_bytes(data)
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        records_offset = prefix.first_process.particle_state.records.offset
        with self.assertRaisesRegex(U9ProcessDataError, "truncated particle presets"):
            U9ProcessDataPrefix.from_bytes(data[: records_offset + 100])

    def test_rejects_out_of_range_particle_force_preset_reference(self) -> None:
        data = bytearray(_process_prefix(particle_counts=(1, 0, 0, 1, 1)))
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        force_offset = prefix.first_process.particle_state.records.forces.offset
        struct.pack_into("<i", data, force_offset + 20, 2)

        with self.assertRaisesRegex(U9ProcessDataError, "force preset reference 2"):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_rejects_out_of_range_force_preset_object_reference(self) -> None:
        data = bytearray(_process_prefix(particle_counts=(1, 0, 0, 1, 0)))
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        preset_offset = prefix.first_process.particle_state.records.force_presets.offset
        struct.pack_into("<i", data, preset_offset + 93, 4)

        with self.assertRaisesRegex(
            U9ProcessDataError, "force preset 1 object reference 4"
        ):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_rejects_out_of_range_particle_preset_object_reference(self) -> None:
        data = bytearray(_process_prefix(particle_counts=(1, 0, 0, 0, 0)))
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        preset_offset = (
            prefix.first_process.particle_state.records.particle_presets.offset
        )
        struct.pack_into("<i", data, preset_offset + 0x5CA, 4)

        with self.assertRaisesRegex(
            U9ProcessDataError, "particle preset 1 source object reference 4"
        ):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_rejects_out_of_range_generation_force_reference(self) -> None:
        data = bytearray(_process_prefix(particle_counts=(1, 1, 0, 1, 1)))
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        generation_offset = (
            prefix.first_process.particle_state.records.generations.offset
        )
        struct.pack_into("<i", data, generation_offset + 20, 2)

        with self.assertRaisesRegex(U9ProcessDataError, "birth force reference 2"):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_rejects_out_of_range_particle_generation_reference(self) -> None:
        data = bytearray(_process_prefix(particle_counts=(1, 1, 1, 1, 1)))
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        particle_offset = prefix.first_process.particle_state.records.particles.offset
        struct.pack_into("<i", data, particle_offset + 4, 2)

        with self.assertRaisesRegex(U9ProcessDataError, "generation reference 2"):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_rejects_out_of_range_particle_object_reference(self) -> None:
        data = bytearray(_process_prefix(particle_counts=(1, 1, 1, 1, 1)))
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.first_process is not None
        assert prefix.first_process.particle_state is not None
        particle_offset = prefix.first_process.particle_state.records.particles.offset
        struct.pack_into("<i", data, particle_offset + 192, 4)

        with self.assertRaisesRegex(U9ProcessDataError, "object reference 4"):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_rejects_invalid_process_type_after_particle_collections(self) -> None:
        data = bytearray(_process_prefix())
        prefix = U9ProcessDataPrefix.from_bytes(bytes(data))
        assert prefix.next_process_offset is not None
        struct.pack_into("<i", data, prefix.next_process_offset, 0xE5)
        with self.assertRaisesRegex(U9ProcessDataError, "invalid next process type"):
            U9ProcessDataPrefix.from_bytes(bytes(data))

    def test_rejects_truncated_process_header_after_particle_collections(self) -> None:
        data = _process_prefix()
        prefix = U9ProcessDataPrefix.from_bytes(data)
        assert prefix.next_process_offset is not None
        with self.assertRaisesRegex(U9ProcessDataError, "truncated process header"):
            U9ProcessDataPrefix.from_bytes(data[: prefix.next_process_offset + 12])


if __name__ == "__main__":
    unittest.main()
