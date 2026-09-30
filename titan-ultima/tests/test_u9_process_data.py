from __future__ import annotations

import math
import struct
import unittest

from titan.u9.process_data import (
    HANDLE_DATA_OFFSET,
    MOVEMENT_CONTROLLER_STATE_SIZE,
    OBJECT_REFERENCE_DATA_OFFSET,
    SIMPLE_PROCESS_LAYOUTS,
    U9CameraEffectState,
    U9CameraState,
    U9CameraControlState,
    U9AnimationControllerProcessState,
    U9AvatarMovementFields,
    U9AvatarMovementTailFields,
    U9BruteMovementFields,
    U9ClockAnimationProcessState,
    U9PathfinderProcessState,
    U9DoorTimerProcessState,
    U9FloatingLanternProcessState,
    U9HangingObjectProcessState,
    U9HumanoidMovementFields,
    U9ItemHandleEntry,
    U9ItemHandleTable,
    U9MovementControllerProcessState,
    U9NpcActionProcessState,
    U9NpcActivityProcessState,
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
    U9ScriptedObjectProcessState,
    U9SimpleProcessState,
    U9SkeletonReformProcessState,
    U9ScriptedProcessState,
    U9ScriptTimerProcessState,
    U9SpiderMovementFields,
    U9SwimmingMovementFields,
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


def _movement_controller_process(
    process_type: int,
    *,
    leading: bytes = b"",
    trailing: bytes = b"",
    name: bytes = b"MoveCon",
) -> bytes:
    data = bytearray(struct.pack("<i", process_type))
    data += leading
    data += struct.pack("<9i100s", 40, 1, 0, 0, 125, -1, -1, 0x3F, 0, name)
    data += struct.pack("<iiii", 0, 1, 2, -1)
    movement = bytearray(MOVEMENT_CONTROLLER_STATE_SIZE)
    struct.pack_into("<i", movement, 0, 1)
    struct.pack_into("<i", movement, 40, 1)
    struct.pack_into("<i", movement, 48, 3)
    data += movement
    data += trailing
    return bytes(data)


def _world_process_header(process_type: int, name: bytes) -> bytes:
    data = bytearray(
        struct.pack("<i9i100s", process_type, 50, 1, 0, 0, 7, -1, -1, 0x3F, 0, name)
    )
    data += struct.pack("<iiii", 0, 1, 2, 9)
    return bytes(data)


def _npc_activity_process(process_type: int = 30) -> bytes:
    variables = [0] * 64
    variables[1] = 734
    variables[5] = 735
    data = bytearray(_world_process_header(process_type, b"NpcActivity"))
    data += struct.pack("<7i64i4I", 2, 275, 2, 3, -1, 1, 0, *variables, 0, 0, 0, 0)
    return bytes(data)


def _npc_action_process(process_type: int = 23) -> bytes:
    variables = [0] * 64
    variables[0] = 734
    data = bytearray(_world_process_header(process_type, b"NpcAction"))
    data += struct.pack("<6ifi", 4, 275, 2, 1, 120, 340, 50.0, 3)
    data += struct.pack("<8if3i", 0, 2, 0, 0, 125, 350, 0, -1, 1.5, 120, 340, 900)
    data += struct.pack("<2ifi", 44, 43, 1.0, 0)
    data += struct.pack("<64i", *variables)
    data += struct.pack("<fi5i4I", 50.0, 1, 1, 30, 172, 1, 0, 0, 0, 0, 0)
    return bytes(data)


_SIMPLE_SAMPLE_VALUES: dict[str, object] = {
    "int": -7,
    "uint": 9,
    "float": 1.5,
    "flag": True,
    "byte_flag": True,
    "byte": 200,
    "ushort": 40000,
    "reference": 1,
    "vector": (1.5, 1.5, 1.5),
    "quaternion": (1.0, 0.0, 0.0, 0.0),
    "location": (1, 2, 3),
    "rgb": (255, 240, 90),
}
_SIMPLE_SAMPLE_PACKING: dict[str, tuple[str, tuple[object, ...]]] = {
    "int": ("i", (-7,)),
    "uint": ("I", (9,)),
    "float": ("f", (1.5,)),
    "flag": ("i", (1,)),
    "byte_flag": ("B", (1,)),
    "byte": ("B", (200,)),
    "ushort": ("H", (40000,)),
    "reference": ("i", (1,)),
    "vector": ("3f", (1.5, 1.5, 1.5)),
    "quaternion": ("4f", (1.0, 0.0, 0.0, 0.0)),
    "location": ("iih2x", (1, 2, 3)),
    "rgb": ("3B", (255, 240, 90)),
    "reserved": ("I", (0,)),
}


def _simple_process(process_type: int) -> bytes:
    layout = SIMPLE_PROCESS_LAYOUTS[process_type]
    version_format = "<f" if isinstance(layout.version, float) else "<i"
    data = bytearray(struct.pack("<i", process_type))
    if layout.version_before_header:
        data += struct.pack(version_format, layout.version)
    data += struct.pack(
        "<9i100s", 50, 1, 0, 0, 7, -1, -1, 0x3F, 0, layout.kind.encode()
    )
    if layout.parent != "header":
        data += struct.pack("<iiii", 0, 1, 2, 9)
    if layout.parent == "scripted":
        data += struct.pack("<iiiii128si", 0, 1, 3, 5, 0, b"", 2)
    if layout.parent == "spell":
        data += struct.pack(
            "<iiIiiiiiIii4I", 4, 1, 24, 2, 422, 7, 30, 0, 0, 3, 16, 0, 0, 0, 0
        )
    if layout.version is not None and not layout.version_before_header:
        data += struct.pack(version_format, layout.version)
    for _, kind in layout.fields:
        fmt, values = _SIMPLE_SAMPLE_PACKING[kind]
        data += struct.pack("<" + fmt, *values)
    return bytes(data)


def _skeleton_reform_process(*, moving: int = 1) -> bytes:
    data = bytearray(_world_process_header(55, b"SkeletonReform"))
    data += struct.pack("<i", 2)
    for bone in range(11):
        data += struct.pack(
            "<i3f3f4f4f3ff3fB",
            bone % 4,
            *(float(bone), 1.0, 2.0),
            *(0.0, 0.0, 0.0),
            *(1.0, 0.0, 0.0, 0.0),
            *(1.0, 0.0, 0.0, 0.0),
            *(0.0, 0.0, 1.0),
            0.5,
            *(3.0, 4.0, 5.0),
            moving if bone == 0 else 0,
        )
    data += struct.pack("<iBBii3ff", 3743, 0, 1, 2, 3, 10.0, 20.0, 30.0, 1.25)
    return bytes(data)


def _floating_lantern_process(*, spline_count: int = 2) -> bytes:
    data = bytearray(_world_process_header(13, b"FloatingLantern"))
    data += struct.pack("<ii", 1, 3)
    data += struct.pack("<ii", 0, spline_count)
    data += b"".join(
        struct.pack("<3f", float(i), 0.0, 0.0) for i in range(spline_count)
    )
    data += struct.pack("<i2f", 2, 0.0, 10.0)
    data += struct.pack("<i4f", 1, 1.0, 0.0, 0.0, 0.0)
    data += struct.pack("<i", 0)
    data += struct.pack("<iffffiiiiii", 5, 2.5, 2.0, 1.0, 70.0, 1, 2, 0, 0, 1, 2)
    data += struct.pack(
        "<fi3i3ii4I", 3.831, 0, 1, 43151, 44162, 82717, 83728, 0, 1, 0, 0, 0, 0
    )
    return bytes(data)


_GRID_BASE = 0x0A000000


def _pathfinder_process(*, grid: bool, blocked_x: float = 0.0) -> bytes:
    data = bytearray(_world_process_header(1, b"Pathfinder"))
    vectors = [(float(i), 2.0, 3.0) for i in range(7)]
    vectors[5] = (blocked_x, 0.0, 0.0)
    data += struct.pack("<iiiff", 6, 275, -1, 40.0, 0.5)
    for vector in vectors:
        data += struct.pack("<3f", *vector)
    data += struct.pack("<iiiiif", 0, 1, 1264, -1, 0, 1.25)
    data += struct.pack("<3f", 0.0, 1.0, 0.0)
    data += struct.pack("<fiiiifff", 16.0, 33, 0, 10, 12345, 20.0, 18.0, 0.3)
    data += struct.pack("<3fB", 7.0, 8.0, 9.0, 1 if grid else 0)
    if grid:
        data += struct.pack("<15f", *([1.0] * 15))
        data += struct.pack(
            "<4f4i2f2iiI", 30, 0.7, 20, 0.9, 0, 0, 1, 1, 9.0, 60, 2, 2, 1, _GRID_BASE
        )
        for index in range(4):
            touched = index in (0, 1, 3)
            data += struct.pack(
                "<6i3fI",
                index % 2 if touched else 0x1234,
                index // 2 if touched else 0x5678,
                194 if touched else 0,
                index,
                index + 1,
                3 - index,
                0.0,
                0.0,
                0.0,
                _GRID_BASE + 40 * (index + 1) if index < 3 else 0,
            )
        data += struct.pack(
            "<IIfiI", _GRID_BASE + 40, _GRID_BASE, 22.5, 0, _GRID_BASE + 120
        )
    data += struct.pack("<7i", 0, 0, 1, 11, 1, 30, 0)
    return bytes(data)


def _door_timer_process() -> bytes:
    data = bytearray(_world_process_header(197, b"DoorTimer"))
    data += struct.pack("<iif", 0, 3, 28177.0)
    return bytes(data)


def _scripted_object_process(process_type: int = 53) -> bytes:
    data = bytearray(_world_process_header(process_type, b"Door"))
    data += struct.pack("<iiiii128si", 0, 1, 3, 5, 0, b"", 2)
    return bytes(data)


def _clock_animation_process() -> bytes:
    data = bytearray(_scripted_object_process(57))
    data += struct.pack("<if", 0, 11685.0)
    return bytes(data)


def _flying_extension() -> bytes:
    return struct.pack(
        "<2f5ii5ii2I", 900.0, 10.0, 1, 2, 0, 0, 0, 2, 7, 0, 0, 0, 0, 1, 0, 0
    )


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

    def test_accepts_unset_camera_filter_ramp_counts(self) -> None:
        # A retail save stores 255 in both camera-filter counts of an unused
        # filter; the record size does not depend on them.
        preset = bytearray(1490)
        struct.pack_into("<ii", preset, 0, 1, 0)
        preset[0x181] = preset[0x182] = 255
        state = U9ParticlePresetState.from_bytes(bytes(preset), 0, version=5)
        self.assertEqual(
            (
                state.camera_filter_color_ramp_count,
                state.camera_filter_translucency_ramp_count,
            ),
            (255, 255),
        )

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

    def test_routes_avatar_animation_controller_type(self) -> None:
        original = _process_prefix()
        original_prefix = U9ProcessDataPrefix.from_bytes(original)
        assert original_prefix.next_process_offset is not None
        record = bytearray(_animation_controller_process())
        struct.pack_into("<i", record, 0, 213)
        data = (
            original[: original_prefix.next_process_offset]
            + bytes(record)
            + original[original_prefix.next_process_offset :]
        )

        controller, light = U9ProcessDataPrefix.from_bytes(data).following_processes

        assert isinstance(controller, U9AnimationControllerProcessState)
        self.assertEqual(controller.header.process_type, 213)
        self.assertEqual(controller.end_offset, light.offset)

    def _insert_movement(self, *records: bytes) -> tuple[U9ProcessDataPrefix, bytes]:
        original = _process_prefix()
        original_prefix = U9ProcessDataPrefix.from_bytes(original)
        assert original_prefix.next_process_offset is not None
        data = (
            original[: original_prefix.next_process_offset]
            + b"".join(records)
            + original[original_prefix.next_process_offset :]
        )
        return U9ProcessDataPrefix.from_bytes(data), data

    def test_traverses_base_and_flying_movement_controllers(self) -> None:
        prefix, _ = self._insert_movement(
            _movement_controller_process(88),
            _movement_controller_process(93, trailing=_flying_extension()),
        )

        walker, flyer, light = prefix.following_processes
        assert isinstance(walker, U9MovementControllerProcessState)
        assert isinstance(flyer, U9MovementControllerProcessState)
        self.assertIsInstance(light, U9PortableLightProcessState)
        self.assertEqual(walker.header.name, "MoveCon")
        self.assertEqual(walker.world_state.object_reference_indices, (2,))
        self.assertEqual(walker.movement.version, 1)
        self.assertEqual(walker.movement.object_reference_indices, (1, 3))
        self.assertEqual(len(walker.movement.raw), MOVEMENT_CONTROLLER_STATE_SIZE)
        self.assertIsNone(walker.flying)
        self.assertEqual(walker.end_offset, flyer.offset)
        assert flyer.flying is not None
        self.assertEqual(flyer.flying.ceiling_altitude, 900.0)
        self.assertEqual(flyer.flying.fall_animation_ids, (1, 2, 0, 0, 0))
        self.assertEqual(flyer.flying.fall_animation_count, 2)
        self.assertEqual(flyer.flying.death_animation_count, 1)
        self.assertEqual(flyer.end_offset, light.offset)

    def test_humanoid_blocks_precede_the_common_header(self) -> None:
        avatar_fields = struct.pack("<iiiiBBBiiii", 3, 33, 7, 0, 0, 1, 0, 172, 0, -1, 1)
        humanoid_fields = struct.pack("<iiBB", 2, 0, 0, 1)
        prefix, _ = self._insert_movement(
            _movement_controller_process(
                166,
                leading=avatar_fields + humanoid_fields,
                trailing=b"\x01",
                name=b"AvatarMoveCon",
            ),
            _movement_controller_process(
                95, leading=struct.pack("<ii", 1, -1) + humanoid_fields
            ),
        )

        avatar, brute, light = prefix.following_processes
        assert isinstance(avatar, U9MovementControllerProcessState)
        assert isinstance(brute, U9MovementControllerProcessState)
        self.assertEqual(avatar.header.name, "AvatarMoveCon")
        self.assertEqual(avatar.header.serialized_prefix_size, 4 + 35 + 10)
        self.assertEqual(
            [(block.kind, block.raw) for block in avatar.leading],
            [("avatar", avatar_fields), ("humanoid", humanoid_fields)],
        )
        self.assertEqual(avatar.leading[0].offset, avatar.offset + 4)
        self.assertEqual(
            [(block.kind, block.raw) for block in avatar.extensions],
            [("avatar_tail", b"\x01")],
        )
        self.assertEqual(avatar.end_offset, brute.offset)
        self.assertEqual([block.kind for block in brute.leading], ["brute", "humanoid"])
        self.assertEqual(brute.extensions, ())
        self.assertEqual(brute.end_offset, light.offset)

        self.assertEqual(
            avatar.leading[0].fields,
            U9AvatarMovementFields(
                version=3,
                breath_timer=33,
                health_timer=7,
                swamp_timer=0,
                breath_override=False,
                levitation_allowed=True,
                levitating=False,
                previous_idle_animation_id=172,
                posing=0,
                last_idle_animation_id=-1,
                combat_mode=1,
            ),
        )
        self.assertEqual(
            avatar.leading[1].fields,
            U9HumanoidMovementFields(
                version=2,
                lava_timer=0,
                wearing_infernal_armor=False,
                leaves_footprints=True,
            ),
        )
        self.assertEqual(
            avatar.extensions[0].fields, U9AvatarMovementTailFields(swamp_immunity=True)
        )
        self.assertEqual(
            brute.leading[0].fields,
            U9BruteMovementFields(version=1, idle_animation_id=-1),
        )

    def test_rejects_bad_movement_extension_versions_and_flags(self) -> None:
        humanoid_fields = struct.pack("<iiBB", 2, 0, 0, 1)
        prefix, data = self._insert_movement(
            _movement_controller_process(85, leading=humanoid_fields)
        )
        walker = prefix.following_processes[0]
        assert isinstance(walker, U9MovementControllerProcessState)
        block = walker.leading[0]

        bad_version = bytearray(data)
        struct.pack_into("<i", bad_version, block.offset, 3)
        with self.assertRaisesRegex(U9ProcessDataError, "humanoid movement version 3"):
            U9ProcessDataPrefix.from_bytes(bytes(bad_version))

        bad_flag = bytearray(data)
        bad_flag[block.offset + 9] = 2
        with self.assertRaisesRegex(U9ProcessDataError, "footprints boolean byte 2"):
            U9ProcessDataPrefix.from_bytes(bytes(bad_flag))

    def test_spider_swimming_and_zombie_blocks_follow_the_base_block(self) -> None:
        spider_fields = struct.pack("<iII", -1, 5621, 0)
        swimming_fields = struct.pack(
            "<3f5ii5ii2I",
            25.0,
            300.0,
            0.0,
            *(0x3F7E6B52, 0x3F7E6B52, 78, -4909232, 0),
            0,
            *(939, 0, 0, 0, 0),
            1,
            0,
            0x3F800000,
        )
        prefix, _ = self._insert_movement(
            _movement_controller_process(155, trailing=spider_fields),
            _movement_controller_process(168, trailing=swimming_fields),
            _movement_controller_process(211),
        )

        spider, fish, zombie, light = prefix.following_processes
        assert isinstance(spider, U9MovementControllerProcessState)
        assert isinstance(fish, U9MovementControllerProcessState)
        assert isinstance(zombie, U9MovementControllerProcessState)
        self.assertEqual(
            [(block.kind, block.raw) for block in spider.extensions],
            [("spider", spider_fields)],
        )
        self.assertEqual(
            [(block.kind, block.raw) for block in fish.extensions],
            [("swimming", swimming_fields)],
        )
        self.assertIsNone(fish.flying)
        self.assertEqual((zombie.leading, zombie.extensions), ((), ()))
        self.assertEqual(spider.end_offset, fish.offset)
        self.assertEqual(fish.end_offset, zombie.offset)
        self.assertEqual(zombie.end_offset, light.offset)

        self.assertEqual(
            spider.extensions[0].fields,
            U9SpiderMovementFields(speed=-1, reserved=(5621, 0)),
        )
        swimming = fish.extensions[0].fields
        assert isinstance(swimming, U9SwimmingMovementFields)
        self.assertEqual(
            (swimming.floor_altitude, swimming.floor_depth, swimming.jump_depth),
            (25.0, 300.0, 0.0),
        )
        self.assertEqual(swimming.fall_animation_count, 0)
        self.assertEqual(swimming.fall_animation_ids[2], 78)
        self.assertEqual(swimming.death_animation_ids[0], 939)
        self.assertEqual(swimming.death_animation_count, 1)
        self.assertEqual(swimming.reserved, (0, 0x3F800000))

    def test_rejects_swimming_animation_count_above_capacity(self) -> None:
        swimming_fields = struct.pack(
            "<3f5ii5ii2I", 25.0, 300.0, 0.0, *([0] * 5), 6, *([0] * 5), 0, 0, 0
        )
        record = _movement_controller_process(87, trailing=swimming_fields)
        with self.assertRaisesRegex(
            U9ProcessDataError, "invalid swimming fall-animation count 6"
        ):
            self._insert_movement(record)

    def test_npc_movement_extension_follows_the_base_block(self) -> None:
        extension = struct.pack("<iii", 3, 3266, 2)
        prefix, data = self._insert_movement(
            _movement_controller_process(86, trailing=extension)
        )

        npc, light = prefix.following_processes
        assert isinstance(npc, U9MovementControllerProcessState)
        self.assertEqual(npc.leading, ())
        (block,) = npc.extensions
        self.assertEqual(block.kind, "npc")
        self.assertEqual(block.object_reference_index, 3)
        self.assertEqual(block.offset, npc.movement.end_offset)
        self.assertEqual(npc.end_offset, light.offset)

        bad_reference = bytearray(data)
        struct.pack_into("<i", bad_reference, block.offset, 4)
        with self.assertRaisesRegex(
            U9ProcessDataError, "npc movement object-reference"
        ):
            U9ProcessDataPrefix.from_bytes(bytes(bad_reference))

    def test_rejects_bad_movement_controller_version_and_reference(self) -> None:
        prefix, data = self._insert_movement(_movement_controller_process(88))
        walker = prefix.following_processes[0]
        assert isinstance(walker, U9MovementControllerProcessState)

        bad_version = bytearray(data)
        struct.pack_into("<i", bad_version, walker.movement.offset, 2)
        with self.assertRaisesRegex(
            U9ProcessDataError, "movement-controller version 2"
        ):
            U9ProcessDataPrefix.from_bytes(bytes(bad_version))

        bad_reference = bytearray(data)
        struct.pack_into("<i", bad_reference, walker.movement.offset + 48, 4)
        with self.assertRaisesRegex(
            U9ProcessDataError, "movement-controller object-reference index 4"
        ):
            U9ProcessDataPrefix.from_bytes(bytes(bad_reference))

    def test_traverses_npc_activity_process(self) -> None:
        prefix, _ = self._insert_movement(
            _npc_activity_process(30), _npc_activity_process(160)
        )

        loiter, idle, light = prefix.following_processes
        assert isinstance(loiter, U9NpcActivityProcessState)
        self.assertIsInstance(idle, U9NpcActivityProcessState)
        self.assertIsInstance(light, U9PortableLightProcessState)
        self.assertEqual(loiter.header.name, "NpcActivity")
        self.assertEqual(loiter.world_state.map_number, 9)
        self.assertEqual(
            (
                loiter.version,
                loiter.npc_number,
                loiter.action_kind,
                loiter.npc_object_reference_index,
                loiter.state,
                loiter.activity_started,
                loiter.clears_hands_on_exit,
            ),
            (2, 275, 2, 3, -1, True, False),
        )
        self.assertEqual(len(loiter.activity_variables), 64)
        self.assertEqual(loiter.activity_variables[:6], (0, 734, 0, 0, 0, 735))
        self.assertEqual(loiter.reserved, (0, 0, 0, 0))
        self.assertEqual(loiter.end_offset, idle.offset)
        self.assertEqual(idle.end_offset, light.offset)

    def test_traverses_npc_action_and_door_timer_processes(self) -> None:
        prefix, _ = self._insert_movement(
            _npc_activity_process(30), _npc_action_process(23), _door_timer_process()
        )

        activity, action, door, light = prefix.following_processes
        assert isinstance(activity, U9NpcActivityProcessState)
        assert isinstance(action, U9NpcActionProcessState)
        assert isinstance(door, U9DoorTimerProcessState)
        self.assertIsInstance(light, U9PortableLightProcessState)
        self.assertEqual(activity.action.name, "loiter")
        self.assertEqual(action.action.name, "loiter")
        self.assertEqual(
            (action.version, action.npc_number, action.action_kind, action.pathfinding),
            (4, 275, 2, True),
        )
        self.assertEqual((action.pathfind_x, action.pathfind_y), (120, 340))
        self.assertEqual(action.error_tolerance, 50.0)
        self.assertEqual(action.npc_object_reference_index, 3)
        self.assertEqual(
            (action.state, action.target_x, action.target_y), (2, 125, 350)
        )
        self.assertEqual((action.current_link, action.target_angle), (-1, 1.5))
        self.assertEqual(
            (action.origin_x, action.origin_y, action.stand_time), (120, 340, 900)
        )
        self.assertEqual(
            (action.animation_to_play, action.last_animation_played), (44, 43)
        )
        self.assertEqual(action.activity_variables[0], 734)
        self.assertEqual(action.maximum_step_height, 50.0)
        self.assertEqual(action.extra_object_reference_index, 1)
        self.assertEqual(
            (action.collision_checks_per_frame, action.maximum_collision_checks),
            (1, 30),
        )
        self.assertEqual(action.idle_animation_id, 172)
        self.assertTrue(action.needs_idle_animation)
        self.assertFalse(action.exits_next_frame)
        self.assertEqual(action.reserved, (0, 0, 0, 0))
        self.assertEqual(action.end_offset, door.offset)
        self.assertEqual(
            (door.version, door.door_object_reference_index, door.elapsed_time),
            (0, 3, 28177.0),
        )
        self.assertEqual(door.end_offset, light.offset)

    def test_rejects_bad_npc_action_and_door_timer_fields(self) -> None:
        prefix, data = self._insert_movement(
            _npc_action_process(), _door_timer_process()
        )
        action, door, _ = prefix.following_processes
        assert isinstance(action, U9NpcActionProcessState)
        assert isinstance(door, U9DoorTimerProcessState)
        action_payload = action.world_state.end_offset
        door_payload = door.world_state.end_offset

        for position, value, message in (
            (action_payload, 3, "NPC-action version 3"),
            (action_payload + 12, 2, "pathfinding flag 2"),
            (action_payload + 28, 4, "NPC-action object-reference index 4"),
            (action_payload + 356, 4, "NPC-action extra object-reference index 4"),
            (door_payload, 1, "door-timer version 1"),
            (door_payload + 4, 4, "door-timer object-reference index 4"),
        ):
            bad = bytearray(data)
            struct.pack_into("<i", bad, position, value)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(U9ProcessDataError, message),
            ):
                U9ProcessDataPrefix.from_bytes(bytes(bad))

    def test_traverses_pathfinders_with_and_without_grid(self) -> None:
        prefix, _ = self._insert_movement(
            _pathfinder_process(grid=False, blocked_x=math.nan),
            _pathfinder_process(grid=True),
        )

        plain, gridded, light = prefix.following_processes
        assert isinstance(plain, U9PathfinderProcessState)
        assert isinstance(gridded, U9PathfinderProcessState)
        self.assertIsInstance(light, U9PortableLightProcessState)
        self.assertIsNone(plain.grid)
        self.assertTrue(math.isnan(plain.blocked_position[0]))
        self.assertEqual(
            (plain.version, plain.npc_number, plain.target_npc_number),
            (6, 275, -1),
        )
        self.assertEqual(plain.goal, (2.0, 2.0, 3.0))
        self.assertEqual(plain.leg_goal, (3.0, 2.0, 3.0))
        self.assertEqual(
            (plain.duration_npc_offset, plain.termination_npc_offset), (1264, -1)
        )
        self.assertEqual((plain.flags, plain.walk_state), (33, 10))
        self.assertEqual(plain.previous_walk_state, 12345)
        self.assertEqual(plain.last_seen_position, (7.0, 8.0, 9.0))
        self.assertEqual(
            (
                plain.status_code,
                plain.grid_move_succeeded,
                plain.maximum_collision_checks,
            ),
            (1, 11, 30),
        )
        self.assertEqual(plain.end_offset, gridded.offset)
        self.assertEqual(gridded.end_offset, light.offset)

        grid = gridded.grid
        assert grid is not None
        self.assertEqual((grid.x_cells, grid.y_cells), (2, 2))
        self.assertEqual((grid.from_cell, grid.to_cell), ((0, 0), (1, 1)))
        self.assertTrue(grid.path_found)
        self.assertEqual(len(grid.cells), 4)
        self.assertEqual(
            (grid.cells[3].x, grid.cells[3].y, grid.cells[3].flags), (1, 1, 194)
        )
        self.assertEqual(grid.cells[2].flags, 0)
        self.assertEqual(grid.cell_index(grid.cells[0].next_address), 1)
        self.assertIsNone(grid.cell_index(0))
        self.assertIsNone(grid.cell_index(_GRID_BASE + 2))
        self.assertIsNone(grid.cell_index(_GRID_BASE + 160))
        self.assertEqual(
            (grid.queue_cell_index, grid.path_cell_index, grid.best_cell_index),
            (1, 0, 3),
        )
        self.assertEqual(grid.cell_spacing, 22.5)

    def test_traverses_skeleton_reform_and_floating_lantern(self) -> None:
        prefix, _ = self._insert_movement(
            _skeleton_reform_process(), _floating_lantern_process()
        )

        skeleton, lantern, light = prefix.following_processes
        assert isinstance(skeleton, U9SkeletonReformProcessState)
        assert isinstance(lantern, U9FloatingLanternProcessState)
        self.assertIsInstance(light, U9PortableLightProcessState)
        self.assertEqual(skeleton.version, 2)
        self.assertEqual(len(skeleton.bones), 11)
        bone = skeleton.bones[1]
        self.assertEqual(bone.bone_object_reference_index, 1)
        self.assertEqual(bone.final_position, (1.0, 1.0, 2.0))
        self.assertEqual(bone.final_orientation, (1.0, 0.0, 0.0, 0.0))
        self.assertEqual(bone.move_orientation_rate, 0.5)
        self.assertEqual(bone.current_destination, (3.0, 4.0, 5.0))
        self.assertTrue(skeleton.bones[0].moving_to_final)
        self.assertFalse(bone.moving_to_final)
        self.assertEqual(
            (skeleton.find_delay, skeleton.found_all_bones, skeleton.bones_ready),
            (3743, False, True),
        )
        self.assertEqual(
            (
                skeleton.bone_key_object_reference_index,
                skeleton.skeleton_object_reference_index,
            ),
            (2, 3),
        )
        self.assertEqual(skeleton.skeleton_position, (10.0, 20.0, 30.0))
        self.assertEqual(skeleton.end_offset, lantern.offset)

        self.assertEqual(
            (lantern.version, lantern.lantern_object_reference_index), (1, 3)
        )
        path = lantern.path
        self.assertEqual(path.spline_points, ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
        self.assertEqual(path.spline_distances, (0.0, 10.0))
        self.assertEqual(path.orientations, ((1.0, 0.0, 0.0, 0.0),))
        self.assertEqual(path.orientation_distances, ())
        self.assertEqual((path.link, path.speed, path.output_node_count), (5, 70.0, 2))
        self.assertEqual(
            (
                path.last_path_marker_object_reference_index,
                path.first_path_marker_object_reference_index,
            ),
            (1, 2),
        )
        self.assertAlmostEqual(lantern.accumulated_time, 3.831, places=5)
        self.assertEqual(lantern.target_position_words, (1, 43151, 44162))
        self.assertEqual(lantern.accumulated_offset_words, (82717, 83728, 0))
        self.assertEqual(lantern.end_condition_flags, 1)
        self.assertEqual(lantern.reserved, (0, 0, 0, 0))
        self.assertEqual(lantern.end_offset, light.offset)

    def test_rejects_bad_skeleton_reform_and_lantern_fields(self) -> None:
        records = (
            (_skeleton_reform_process(moving=2), "moving-to-final boolean byte 2"),
            (_floating_lantern_process(spline_count=-1), "path-manager array count -1"),
        )
        for record, message in records:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(U9ProcessDataError, message),
            ):
                self._insert_movement(record)

    def test_accepts_unset_pathfinder_floats(self) -> None:
        # Retail saves hold NaN in positions the walker never set.
        prefix, data = self._insert_movement(_pathfinder_process(grid=True))
        pathfinder = prefix.following_processes[0]
        assert isinstance(pathfinder, U9PathfinderProcessState)
        payload = pathfinder.world_state.end_offset
        unset = bytearray(data)
        struct.pack_into("<f3f", unset, payload + 168, *([math.nan] * 4))

        reread = U9ProcessDataPrefix.from_bytes(bytes(unset)).following_processes[0]

        assert isinstance(reread, U9PathfinderProcessState)
        self.assertTrue(math.isnan(reread.obstacle_avoid_angle))
        self.assertTrue(all(math.isnan(v) for v in reread.last_seen_position))
        self.assertEqual(reread.end_offset, pathfinder.end_offset)

    def test_rejects_bad_pathfinder_fields(self) -> None:
        prefix, data = self._insert_movement(_pathfinder_process(grid=True))
        pathfinder = prefix.following_processes[0]
        assert isinstance(pathfinder, U9PathfinderProcessState)
        payload = pathfinder.world_state.end_offset
        grid_offset = payload + 185

        for position, fmt, value, message in (
            (payload, "<i", 5, "pathfinder version 5"),
            (payload + 184, "<B", 2, "pathfinder grid flag 2"),
            (grid_offset + 100, "<i", 0, "path-grid size 0x2"),
            (grid_offset + 108, "<i", 3, "path-grid path-found flag 3"),
        ):
            bad = bytearray(data)
            struct.pack_into(fmt, bad, position, value)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(U9ProcessDataError, message),
            ):
                U9ProcessDataPrefix.from_bytes(bytes(bad))

    def test_traverses_every_table_driven_layout(self) -> None:
        records = [_simple_process(t) for t in sorted(SIMPLE_PROCESS_LAYOUTS)]
        prefix, _ = self._insert_movement(*records)

        *simple, light = prefix.following_processes
        self.assertIsInstance(light, U9PortableLightProcessState)
        self.assertEqual(len(simple), len(SIMPLE_PROCESS_LAYOUTS))
        for record, following in zip(simple, [*simple[1:], light]):
            assert isinstance(record, U9SimpleProcessState)
            layout = SIMPLE_PROCESS_LAYOUTS[record.header.process_type]
            with self.subTest(kind=layout.kind):
                self.assertEqual(record.kind, layout.kind)
                self.assertEqual(record.version, layout.version)
                self.assertEqual(
                    record.scripted_state is not None, layout.parent == "scripted"
                )
                self.assertEqual(
                    record.spell_state is not None, layout.parent == "spell"
                )
                self.assertEqual(record.world_state is None, layout.parent == "header")
                if record.spell_state is not None:
                    self.assertEqual(
                        (
                            record.spell_state.spell_number,
                            record.spell_state.target_object_reference_index,
                        ),
                        (30, 3),
                    )
                self.assertEqual(record.end_offset, following.offset)
                for name, kind in layout.fields:
                    if kind != "reserved":
                        self.assertEqual(record[name], _SIMPLE_SAMPLE_VALUES[kind])
                self.assertEqual(
                    record.reserved,
                    (0,) * sum(k == "reserved" for _, k in layout.fields),
                )

    def test_rejects_bad_spell_state(self) -> None:
        prefix, data = self._insert_movement(_simple_process(136))
        spell = prefix.following_processes[0]
        assert isinstance(spell, U9SimpleProcessState)
        assert spell.spell_state is not None
        self.assertEqual(spell.kind, "teleport_spell")
        base = spell.spell_state.offset

        for relative, value, message in (
            (0, 3, "spell-state version 3"),
            (36, 4, "spell target object-reference index 4"),
            (60, 2, "teleport-spell process version 2"),
        ):
            bad = bytearray(data)
            struct.pack_into("<i", bad, base + relative, value)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(U9ProcessDataError, message),
            ):
                U9ProcessDataPrefix.from_bytes(bytes(bad))

    def test_path_follower_fields_and_rejections(self) -> None:
        prefix, data = self._insert_movement(_simple_process(73))
        follower = prefix.following_processes[0]
        assert isinstance(follower, U9SimpleProcessState)
        self.assertEqual(follower.kind, "path_follower")
        self.assertEqual(follower["starting_location"], (1, 2, 3))
        self.assertEqual(follower["delta"], (1.5, 1.5, 1.5))
        self.assertTrue(follower["skips_first_frame"])
        self.assertEqual(follower.fields["source_object"], 1)
        with self.assertRaises(KeyError):
            follower["missing"]
        payload = follower.world_state.end_offset

        for relative, value, message in (
            (0, 2, "path-follower process version 2"),
            (4, 4, "path-follower process source_object object-reference index 4"),
            (56, 2, "path-follower process skips_first_frame flag 2"),
        ):
            bad = bytearray(data)
            struct.pack_into("<i", bad, payload + relative, value)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(U9ProcessDataError, message),
            ):
                U9ProcessDataPrefix.from_bytes(bytes(bad))

    def test_rejects_bad_npc_activity_version_reference_and_flag(self) -> None:
        prefix, data = self._insert_movement(_npc_activity_process())
        activity = prefix.following_processes[0]
        assert isinstance(activity, U9NpcActivityProcessState)
        payload = activity.world_state.end_offset

        for relative, value, message in (
            (0, 1, "NPC-activity version 1"),
            (12, 4, "NPC-activity object-reference index 4"),
            (20, 2, "activity-started flag 2"),
        ):
            bad = bytearray(data)
            struct.pack_into("<i", bad, payload + relative, value)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(U9ProcessDataError, message),
            ):
                U9ProcessDataPrefix.from_bytes(bytes(bad))

    def test_traverses_scripted_object_and_clock_animation_processes(self) -> None:
        prefix, data = self._insert_movement(
            _scripted_object_process(53), _clock_animation_process()
        )

        door, clock, light = prefix.following_processes
        assert isinstance(door, U9ScriptedObjectProcessState)
        assert isinstance(clock, U9ClockAnimationProcessState)
        self.assertIsInstance(light, U9PortableLightProcessState)
        self.assertEqual(door.header.process_type, 53)
        self.assertEqual(door.scripted_state.user_object_reference_index, 3)
        self.assertEqual(door.scripted_state.state, 2)
        self.assertEqual(door.end_offset, clock.offset)
        self.assertEqual(clock.header.process_type, 57)
        self.assertEqual((clock.version, clock.loop_time_ms), (0, 11685.0))
        self.assertEqual(clock.end_offset, light.offset)

        bad_version = bytearray(data)
        struct.pack_into("<i", bad_version, clock.scripted_state.end_offset, 1)
        with self.assertRaisesRegex(U9ProcessDataError, "clock-animation version 1"):
            U9ProcessDataPrefix.from_bytes(bytes(bad_version))

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
            "<if", 131, 1.2
        )

        prefix = U9ProcessDataPrefix.from_bytes(data)

        self.assertEqual(prefix.next_process_type, 131)
        self.assertEqual(prefix.blocked_process_type, 131)
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
