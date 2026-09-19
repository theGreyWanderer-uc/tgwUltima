from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from titan.u9.integrity import check_save, render_integrity_report
from titan.u9.process_data import HANDLE_DATA_OFFSET


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
            next_offset = 0x60 + free_slots[index + 1] * 24 if index + 1 < len(free_slots) else 0
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


def _processes(*, fixed_offset: int | None = None) -> bytes:
    count = 3 if fixed_offset is not None else 2
    end = HANDLE_DATA_OFFSET + 12 + count * 12
    data = bytearray(end + 4)
    struct.pack_into("<II", data, 0, 8, 2)
    struct.pack_into("<III", data, HANDLE_DATA_OFFSET, 1, count, 1)
    struct.pack_into("<iii", data, HANDLE_DATA_OFFSET + 12, 0, -1, 0)
    struct.pack_into("<iii", data, HANDLE_DATA_OFFSET + 24, 0, -1, 0)
    if fixed_offset is not None:
        struct.pack_into(
            "<iii", data, HANDLE_DATA_OFFSET + 36, 1, 9, -fixed_offset
        )
    struct.pack_into("<I", data, end, 2)
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
        rendered = render_integrity_report(report)
        self.assertIn("Assessment: PASS - no integrity problems detected", rendered)
        self.assertIn("Custody       PASS", rendered)
        self.assertIn("Problems (0)\n  None", rendered)
        self.assertIn("Confirmations (1)", rendered)
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
            len([finding for finding in report.to_dict()["findings"] if finding["check_id"] == "NFS07"]),
            2,
        )

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

    def test_fixed_handle_resolves_live_slot_and_rejects_free_slot(self) -> None:
        fixed = _fixed(live_slot=0)
        (self.static / "fixed.9").write_bytes(fixed)
        (self.reference / "fixed.9").write_bytes(fixed)
        for offset, expected in ((0x60, None), (0x78, "REF03")):
            processes = _processes(fixed_offset=offset)
            (self.save / "processes.dat").write_bytes(processes)
            (self.save / "u9game4.sav").write_bytes(
                _archive(processes, _nonfixed())
            )
            report = check_save(self.root, fixed_reference_directory=self.reference)
            ids = {finding.check_id for finding in report.findings}
            if expected is None:
                self.assertNotIn("REF03", ids)
            else:
                self.assertIn(expected, ids)
                finding = next(
                    finding for finding in report.findings if finding.check_id == "REF03"
                )
                records = finding.details["target_records"]
                self.assertEqual(records[0]["handles"], [2])
                self.assertEqual(records[0]["page"], [0, 0])
                self.assertEqual(records[0]["xyz"], [0, 0, 0])
                self.assertEqual(records[0]["status_hex"], "00000")
                rendered = render_integrity_report(report)
                self.assertIn(
                    "Evidence: handle(2) fixed.9 offset 0x78 slot 1 "
                    "page(0,0) xyz(0,0,0) type 0",
                    rendered,
                )


if __name__ == "__main__":
    unittest.main()