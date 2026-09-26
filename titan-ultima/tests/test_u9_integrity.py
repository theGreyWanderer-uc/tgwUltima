from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from titan.u9.integrity import check_save, render_integrity_report
from titan.u9.process_data import OBJECT_REFERENCE_DATA_OFFSET


def _nonfixed() -> bytes:
    data = bytearray(40)
    struct.pack_into("<5I", data, 0, 0, 0, 0, 0, 0x00C00000)
    struct.pack_into("<III", data, 0x14, 1, 1, 1)
    return bytes(data)


def _fixed(*, live_slot: int | None = None) -> bytes:
    payload_size = 4096 if live_slot is not None else 0
    data = bytearray(36 + payload_size)
    struct.pack_into("<I", data, 0x08, payload_size)
    struct.pack_into("<II", data, 0x10, 1, 1)
    if live_slot is not None:
        struct.pack_into("<I", data, 0x1C, 1)
        free_slots = [slot for slot in range(166) if slot != live_slot]
        struct.pack_into("<6I", data, 36, 0, 0x60 + free_slots[0] * 24, 0, 0, 0, 1)
        for index, slot in enumerate(free_slots):
            next_offset = (
                0x60 + free_slots[index + 1] * 24 if index + 1 < len(free_slots) else 0
            )
            struct.pack_into("<I", data, 36 + 0x60 + slot * 24, next_offset)
    return bytes(data)


def _archive(processes: bytes, nonfixed: bytes) -> bytes:
    data = bytearray(b"U9:008")
    for text in (b"", b"Integrity fixture\x00"):
        data += struct.pack("<i", len(text)) + text
    data += struct.pack("<3f4f3f3i", 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 9, 0, 0)
    for payload in (b"", processes, b""):
        data += struct.pack("<i", len(payload)) + payload
    data += struct.pack("<ii", 9, len(nonfixed)) + nonfixed
    data += struct.pack("<i", -1)
    return bytes(data)


def _hanging_object_process() -> bytes:
    data = bytearray(
        struct.pack("<i9i100s", 61, 7, 1, 0, 0, 10809, -1, -1, 0x3F, 0, b"Hanging")
    )
    data += struct.pack("<iii", 0, 0, 9)
    data += struct.pack("<iiiii128si", 0, 0, 0, 1, 0, b"motion", 0)
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
        *([0.0] * 20),
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
    data += struct.pack("<iiiifiiifI20f2fifiifiiifiifiiiffiIIi3f4I", *values)
    return bytes(data)


def _script_timer_process() -> bytes:
    data = bytearray(
        struct.pack("<i9i100s", 62, 14, 1, 0, 0, 10809, -1, -1, 0x3F, 0, b"Timer")
    )
    data += struct.pack("<iii", 0, 0, 9)
    data += struct.pack("<iiiii128si", 0, 0, 0, 0x8000, 0, b"", 0)
    timer_flags = (100 << 16) | (3 << 8) | (4 << 4) | 0x0F
    data += struct.pack("<i12I", 1, timer_flags, 600, 4, 3, 400, 125, 1, 1, 0, 0, 0, 0)
    return bytes(data)


def _animation_controller_process() -> bytes:
    data = bytearray(struct.pack("<if", 98, 1.2))
    data += struct.pack(
        "<9i100s", 30, 1, 0, 0, 125, -1, -1, 0x3F, 0, b"LayeredAnimation"
    )
    data += struct.pack("<iii", 0, 0, -1)
    data += struct.pack(
        "<i3f2Bi3f3fB", 0, 0.0, 0.0, 0.0, 0, 0, -1, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0
    )
    data += struct.pack("<i32i", 0, *([0] * 32))
    data += struct.pack("<i32i", 0, *([0] * 32))
    data += struct.pack("<3f2BIii", 0.0, 0.0, 0.0, 1, 0, 0, -1, -1)
    data += struct.pack("<ii", 0, 0)
    data += struct.pack("<fi", 1.0, -1) * 5
    data += struct.pack("<i", 0)
    return bytes(data)


def _processes(
    *, fixed_offset: int | None = None, first_process: bool = False
) -> bytes:
    count = 3 if fixed_offset is not None else 2
    end = OBJECT_REFERENCE_DATA_OFFSET + 12 + count * 12
    data = bytearray(end)
    struct.pack_into("<II", data, 0, 8, 2)
    struct.pack_into("<III", data, OBJECT_REFERENCE_DATA_OFFSET, 1, count, 1)
    struct.pack_into("<iii", data, OBJECT_REFERENCE_DATA_OFFSET + 12, 0, -1, 0)
    struct.pack_into("<iii", data, OBJECT_REFERENCE_DATA_OFFSET + 24, 0, -1, 0)
    if fixed_offset is not None:
        struct.pack_into(
            "<iii",
            data,
            OBJECT_REFERENCE_DATA_OFFSET + 36,
            1,
            9,
            -fixed_offset,
        )
    data += struct.pack(
        "<I3f3fiiB4fi",
        2,
        0,
        0,
        0,
        0,
        0,
        0,
        320,
        2,
        0,
        60,
        1,
        8000,
        4000,
        0,
    )
    camera_control = bytearray(180)
    struct.pack_into("<I", camera_control, 0, 2)
    data += camera_control
    data += struct.pack("<Iiii3f3fii", 0, 0, 0, 0, 250, 500, 1500, 0, 0, 0, 0, 0)
    if first_process:
        data += struct.pack(
            "<i9i100siii",
            104,
            2,
            1,
            0,
            0,
            30103,
            -1,
            -1,
            -1,
            0,
            b"Poof",
            0,
            0,
            -1,
        )
        particle_counts = (2, 2, 3, 1, 1)
        data += struct.pack("<iIBi5i", 5, 49, 0, 527, *particle_counts)
        layouts = (
            ("particle_presets", 2, 1490),
            ("force_presets", 1, 97),
            ("forces", 1, 24),
            ("generations", 2, 124),
            ("particles", 3, 196),
        )
        for name, count, record_size in layouts:
            for record_id in range(1, count + 1):
                record = bytearray(record_size)
                struct.pack_into("<i", record, 0, record_id)
                if name == "force_presets":
                    struct.pack_into(
                        "<Biii3ffii3fi3f3fiiii",
                        record,
                        4,
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
                        0,
                    )
                elif name == "forces":
                    struct.pack_into("<i3fi", record, 4, 17, 1.0, 2.0, 3.0, 1)
                elif name == "generations":
                    struct.pack_into(
                        "<30i", record, 4, 1, -1, -1, -1, *([1] * 16), *([-1] * 10)
                    )
                elif name == "particles":
                    struct.pack_into(
                        "<2i10i2i3f3f3f3f4f4f2iBHI4iIB5i",
                        record,
                        4,
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
                        0,
                    )
                data += record
        data += _hanging_object_process()
        data += _script_timer_process()
        data += _animation_controller_process()
        data += struct.pack("<i9i100s", 70, 10, 1, 0, 0, 464, -1, -1, -1, 0, b"Torch")
        data += struct.pack("<iii", 0, 0, 9)
        data += struct.pack("<iiHfIIII", 0, 0, 65535, 65535.0, 24, 0, 0, 0x09)
        data += struct.pack("<i", -1)
    else:
        data += struct.pack("<i", -1)
    return bytes(data)


class IntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.save = self.root / "savegame"
        self.static = self.root / "static"
        self.reference = self.root / "reference"
        self.save.mkdir()
        self.static.mkdir()
        self.reference.mkdir()
        processes = _processes()
        nonfixed = _nonfixed()
        (self.save / "start.dat").write_bytes(b"U9.008" + struct.pack("<i", 4))
        (self.save / "u9game4.sav").write_bytes(_archive(processes, nonfixed))
        (self.save / "processes.dat").write_bytes(processes)
        (self.save / "nonfixed.9").write_bytes(nonfixed)
        (self.static / "fixed.9").write_bytes(_fixed())
        (self.reference / "fixed.9").write_bytes(_fixed())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_clean_fixture_has_three_pass_verdicts(self) -> None:
        report = check_save(self.root, fixed_reference_directory=self.reference)
        self.assertEqual(report.verdict("custody"), "PASS")
        self.assertEqual(report.verdict("structure"), "PASS")
        self.assertEqual(report.verdict("compatibility"), "PASS")
        self.assertIn("LAY01", {finding.check_id for finding in report.findings})
        process_evidence = report.artifacts["archive/processes.dat"]
        self.assertEqual(process_evidence["camera"]["version"], 2)
        self.assertEqual(process_evidence["camera_control"]["version"], 2)
        self.assertEqual(process_evidence["first_process_type"], -1)
        rendered = render_integrity_report(report)
        self.assertIn("Assessment: PASS - no integrity problems detected", rendered)
        self.assertIn("Custody       PASS", rendered)
        self.assertIn("Problems (0)\n  None", rendered)
        self.assertIn("Confirmations (1)", rendered)
        self.assertIn("camera=v2/effects0", rendered)
        self.assertIn("camera_control=v2", rendered)
        self.assertIn("first_process_type=-1", rendered)
        self.assertLess(rendered.index("Problems"), rendered.index("Evidence"))
        json.dumps(report.to_dict())

    def test_member_mismatch_is_a_custody_failure(self) -> None:
        (self.save / "processes.dat").write_bytes(b"different")
        report = check_save(self.root, fixed_reference_directory=self.reference)
        self.assertEqual(report.verdict("custody"), "FATAL")
        self.assertIn("CUS01", {finding.check_id for finding in report.findings})
        rendered = render_integrity_report(report)
        self.assertIn("Assessment: UNSAFE TO LOAD", rendered)
        self.assertIn("CUS: Re-extract the selected archive", rendered)
        self.assertIn("Source:", rendered)

    def test_reports_first_process_shared_prefix(self) -> None:
        processes = _processes(first_process=True)
        nonfixed = _nonfixed()
        (self.save / "u9game4.sav").write_bytes(_archive(processes, nonfixed))
        (self.save / "processes.dat").write_bytes(processes)

        report = check_save(self.root, fixed_reference_directory=self.reference)
        evidence = report.artifacts["archive/processes.dat"]
        first_process = evidence["first_process"]
        self.assertEqual(first_process["type"], 104)
        self.assertEqual(first_process["name"], "Poof")
        self.assertEqual(first_process["process_id"], 2)
        self.assertEqual(first_process["payload_offset"], first_process["offset"] + 152)
        self.assertEqual(
            first_process["world_state"],
            {"version": 0, "object_reference_indices": [], "map_number": -1},
        )
        self.assertEqual(
            first_process["particle_state"]["record_counts"],
            {
                "particle_presets": 2,
                "generations": 2,
                "particles": 3,
                "force_presets": 1,
                "forces": 1,
            },
        )
        self.assertEqual(
            first_process["particle_state"]["end_offset"],
            first_process["next_process_offset"],
        )
        self.assertEqual(first_process["next_process_type"], 61)
        self.assertEqual(first_process["next_process_name"], "Hanging")
        self.assertEqual(
            first_process["particle_state"]["collections"]["particle_presets"][
                "record_size"
            ],
            1490,
        )
        particle_presets = first_process["particle_state"]["particle_preset_records"]
        self.assertEqual(len(particle_presets), 2)
        self.assertEqual(particle_presets[0]["record_id"], 1)
        self.assertEqual(particle_presets[0]["version_5_item_extension"], "0000")
        self.assertEqual(particle_presets[0]["version_5_ramp_extension"], "00000000")
        self.assertEqual(len(particle_presets[0]["item_variants"]), 10)
        self.assertEqual(len(particle_presets[0]["ramp_slots"]), 10)
        self.assertEqual(
            first_process["particle_state"]["force_records"],
            [
                {
                    "record_id": 1,
                    "age": 17,
                    "location": [1.0, 2.0, 3.0],
                    "preset_id": 1,
                    "offset": first_process["particle_state"]["collections"]["forces"][
                        "offset"
                    ],
                    "end_offset": first_process["particle_state"]["collections"][
                        "forces"
                    ]["end_offset"],
                }
            ],
        )
        generation_records = first_process["particle_state"]["generation_records"]
        self.assertEqual(len(generation_records), 2)
        self.assertEqual(generation_records[0]["particle_preset_id"], 1)
        self.assertEqual(generation_records[0]["birth_force_ids"], [1, 1, 1, 1])
        self.assertEqual(generation_records[0]["slave_generation_ids"], [-1] * 10)
        force_presets = first_process["particle_state"]["force_preset_records"]
        self.assertEqual(len(force_presets), 1)
        self.assertEqual(force_presets[0]["force_type"], 43)
        self.assertEqual(force_presets[0]["location"], [1.0, 2.0, 3.0])
        self.assertEqual(force_presets[0]["speed_limit"], 9999)
        self.assertEqual(force_presets[0]["object_reference_index"], 0)
        particle_records = first_process["particle_state"]["particle_records"]
        self.assertEqual(len(particle_records), 3)
        self.assertEqual(particle_records[0]["generation_id"], 1)
        self.assertEqual(particle_records[0]["child_particle_ids"], [-1] * 10)
        self.assertEqual(particle_records[0]["object_type_id"], 557)
        self.assertTrue(particle_records[0]["pulse_count_byte_matches"])
        self.assertEqual(particle_records[0]["object_reference_index"], 0)
        self.assertEqual(evidence["decoded_following_process_count"], 4)
        hanging, timer, controller, light = evidence["decoded_following_processes"]
        self.assertEqual(hanging["type"], 61)
        self.assertEqual(hanging["name"], "Hanging")
        self.assertEqual(hanging["scripted_state"]["primary_object_reference_index"], 0)
        self.assertEqual(hanging["hanging_object"]["version"], 2)
        self.assertEqual(hanging["hanging_object"]["swing_period"], 22)
        self.assertEqual(hanging["hanging_object"]["turn_period"], 17)
        self.assertEqual(
            hanging["hanging_object"]["configured_maximum_swing_angle"], 45
        )
        self.assertEqual(hanging["hanging_object"]["facing"], [0.0, -1.0, 0.0])
        self.assertEqual(timer["type"], 62)
        self.assertEqual(timer["name"], "Timer")
        self.assertEqual(timer["script_timer"]["version"], 1)
        self.assertEqual(timer["script_timer"]["phase_1_duration"], 600)
        self.assertEqual(timer["script_timer"]["configured_dual_percentage"], 40)
        self.assertTrue(timer["script_timer"]["runs_continuously"])
        self.assertEqual(controller["type"], 98)
        self.assertEqual(controller["name"], "LayeredAnimation")
        animation = controller["animation_controller"]
        self.assertAlmostEqual(animation["version"], 1.2)
        self.assertEqual(animation["object_reference_index"], 0)
        self.assertEqual(animation["upper_limb_ids"], [])
        self.assertEqual(len(animation["animation_tracks"]), 5)
        self.assertFalse(animation["animation_tracks"][0]["active"])
        self.assertEqual(animation["kinematic_tracks"], [])
        self.assertEqual(light["type"], 70)
        self.assertEqual(light["name"], "Torch")
        self.assertEqual(light["world_state"]["map_number"], 9)
        self.assertEqual(light["portable_light"]["maximum_fuel"], 65535)
        self.assertTrue(light["portable_light"]["is_on"])
        self.assertTrue(light["portable_light"]["is_automatic"])
        self.assertIsNone(evidence["blocked_process_type"])
        self.assertEqual(evidence["process_terminator_offset"], light["end_offset"])
        rendered = render_integrity_report(report)
        self.assertIn("first_process=104/Poof", rendered)
        self.assertIn("decoded_following_processes=4", rendered)
        json.dumps(report.to_dict())

    def test_renderer_collapses_duplicate_problems_but_json_keeps_them(self) -> None:
        report = check_save(self.root, fixed_reference_directory=self.reference)
        report.add("NFS07", "structure", "WARN", "same issue", path="archive")
        report.add("NFS07", "structure", "WARN", "same issue", path="working")

        rendered = render_integrity_report(report)
        self.assertIn("Problems (1 distinct, 2 findings)", rendered)
        self.assertEqual(rendered.count("NFS07 structure: same issue"), 1)
        self.assertIn("Source: archive", rendered)
        self.assertIn("Source: working", rendered)
        self.assertEqual(
            len(
                [
                    finding
                    for finding in report.to_dict()["findings"]
                    if finding["check_id"] == "NFS07"
                ]
            ),
            2,
        )

    def test_map_member_above_the_shipped_range_warns_instead_of_failing(self) -> None:
        # The game archives and restores nonfixed.0-255, so a member numbered
        # 240-255 is legal; no shipped map has that number, so it is worth a warning.
        nonfixed = _nonfixed()
        archive = bytearray(_archive(_processes(), nonfixed))
        del archive[-4:]
        archive += struct.pack("<ii", 240, len(nonfixed)) + nonfixed
        archive += struct.pack("<i", -1)
        (self.save / "u9game4.sav").write_bytes(bytes(archive))
        (self.save / "nonfixed.240").write_bytes(nonfixed)

        report = check_save(self.root, fixed_reference_directory=self.reference)
        ids = {finding.check_id for finding in report.findings}
        self.assertIn("ARC10", ids)
        self.assertNotIn("ARC01", ids)
        # No handle points at map 240, so it needs no fixed.240.
        self.assertNotIn("REF01", ids)
        self.assertEqual(report.verdict("custody"), "WARN")
        self.assertEqual(report.verdict("structure"), "PASS")
        self.assertEqual(report.verdict("compatibility"), "PASS")

    def test_missing_fixed_map_is_a_compatibility_failure(self) -> None:
        (self.static / "fixed.9").unlink()
        report = check_save(self.root, fixed_reference_directory=self.reference)
        self.assertEqual(report.verdict("compatibility"), "FATAL")
        self.assertIn("REF01", {finding.check_id for finding in report.findings})

    def test_partial_bundle_records_omissions_without_failing_custody(self) -> None:
        (self.save / "nonfixed.9").unlink()
        (self.static / "fixed.9").unlink()
        report = check_save(
            self.root,
            fixed_reference_directory=self.reference,
            allow_partial=True,
        )
        self.assertEqual(report.verdict("custody"), "PASS")
        self.assertEqual(report.verdict("compatibility"), "PASS")
        self.assertIn("CUS07", {finding.check_id for finding in report.findings})
        self.assertIn("REF08", {finding.check_id for finding in report.findings})

    def test_fixed_reference_resolves_live_slot_and_rejects_free_slot(self) -> None:
        fixed = _fixed(live_slot=0)
        (self.static / "fixed.9").write_bytes(fixed)
        (self.reference / "fixed.9").write_bytes(fixed)
        for offset, expected in ((0x60, None), (0x78, "REF03")):
            processes = _processes(fixed_offset=offset)
            (self.save / "processes.dat").write_bytes(processes)
            (self.save / "u9game4.sav").write_bytes(_archive(processes, _nonfixed()))
            report = check_save(self.root, fixed_reference_directory=self.reference)
            process_evidence = report.artifacts["archive/processes.dat"]
            self.assertEqual(process_evidence["reference_count"], 3)
            self.assertEqual(
                process_evidence["reference_count"],
                process_evidence["handle_count"],
            )
            self.assertEqual(
                process_evidence["live_references"],
                process_evidence["live_handles"],
            )
            ids = {finding.check_id for finding in report.findings}
            if expected is None:
                self.assertNotIn("REF03", ids)
            else:
                self.assertIn(expected, ids)
                finding = next(
                    finding
                    for finding in report.findings
                    if finding.check_id == "REF03"
                )
                self.assertEqual(finding.details["reference_indices"], [2])
                self.assertEqual(
                    finding.details["reference_indices"],
                    finding.details["handle_indices"],
                )
                records = finding.details["target_records"]
                self.assertEqual(records[0]["reference_indices"], [2])
                self.assertEqual(records[0]["handles"], [2])
                self.assertEqual(records[0]["page"], [0, 0])
                self.assertEqual(records[0]["xyz"], [0, 0, 0])
                self.assertEqual(records[0]["status_hex"], "00000")
                rendered = render_integrity_report(report)
                self.assertIn(
                    "Evidence: reference(2) fixed.9 offset 0x78 slot 1 "
                    "page(0,0) xyz(0,0,0) type 0",
                    rendered,
                )


if __name__ == "__main__":
    unittest.main()
