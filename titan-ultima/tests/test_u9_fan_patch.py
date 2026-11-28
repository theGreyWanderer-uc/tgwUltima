"""FWP01/FWP02: saves that predate the Forgotten World patches' map changes."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from tests.test_u9_integrity import _archive, _fixed, _processes
from tests.test_u9_nonfixed import (
    ENTITY_SIZE,
    PAGE_HEADER_SIZE,
    _allocator_payload,
    _entity,
    _header,
)
from titan.u9.fan_patch import (
    COMPANION_MARKER_LINKS,
    COMPANION_MARKER_TYPE,
    SHRINE_OBJECTS,
    installed_state,
    save_state,
)
from titan.u9.integrity import check_save
from titan.u9.nonfixed import U9Nonfixed
from titan.u9.save_wording import describe_u9_save_integrity

# The Valor shrine's two objects; their chunk is given a base just below them.
VALOR = [item for item in SHRINE_OBJECTS if item.shrine == "Valor"]
BASE_X, BASE_Y = 33200, 26300


def _region(objects: list[tuple[int, int, int, int, int]]) -> bytes:
    """A 1x1 region of one complete page: (type, world x, world y, z, link) each."""
    entities: dict[int, bytes] = {}
    offsets = [PAGE_HEADER_SIZE + index * ENTITY_SIZE for index in range(len(objects))]
    for index, (type_index, x, y, z, link) in enumerate(objects):
        local_x, local_y = x - BASE_X, y - BASE_Y
        assert 0 <= local_x < 1024 and 0 <= local_y < 1024, "one bucket keeps it simple"
        entities[offsets[index]] = _entity(
            next_entity=offsets[index + 1] if index + 1 < len(offsets) else 0,
            x=local_x,
            y=local_y,
            z=z,
            type_index=type_index,
            link=link,
        )
    # Bucket 1 is local (0..1023, 0..1023); head 0 is reserved.
    page = bytearray(
        _allocator_payload(entities=entities, extras={}, heads=[0, offsets[0]])
    )
    struct.pack_into("<II", page, 12, BASE_X, BASE_Y)
    return _header(1, 1, [1], payload_size=len(page)) + bytes(page)


def _markers() -> list[tuple[int, int, int, int, int]]:
    return [
        (COMPANION_MARKER_TYPE, BASE_X + 500 + i, BASE_Y + 500, 2900, link)
        for i, link in enumerate(COMPANION_MARKER_LINKS)
    ]


def _valor(height: str) -> list[tuple[int, int, int, int, int]]:
    return [
        (
            item.type_index,
            item.world_x,
            item.world_y,
            item.stock_z if height == "stock" else item.patched_z,
            1330,
        )
        for item in VALOR
    ]


PATCHED_MAP = _region(_markers() + _valor("patched"))
STOCK_MAP = _region(_valor("stock"))


class FanPatchStateTests(unittest.TestCase):
    def test_a_patched_map_has_the_companions_and_lowered_runes(self) -> None:
        state = save_state({9: U9Nonfixed(PATCHED_MAP)})
        self.assertTrue(state.companions)
        self.assertEqual(set(VALOR), set(state.lowered_shrines()))
        self.assertEqual([], state.stock_shrines())

    def test_a_stock_map_has_neither(self) -> None:
        state = save_state({9: U9Nonfixed(STOCK_MAP)})
        self.assertFalse(state.companions)
        self.assertEqual(set(VALOR), set(state.stock_shrines()))

    def test_no_map_9_says_nothing_about_companions(self) -> None:
        state = save_state({0: U9Nonfixed(STOCK_MAP)})
        self.assertIsNone(state.companions)
        self.assertEqual({}, state.shrine_heights)

    def test_one_marker_is_not_the_fix(self) -> None:
        region = _region(_markers()[:1])
        self.assertFalse(save_state({9: U9Nonfixed(region)}).companions)

    def test_a_moved_rune_is_neither_stock_nor_lowered(self) -> None:
        # The game settles objects; a save's Rune can sit at a third height.
        moved = [(t, x, y, z - 27, link) for t, x, y, z, link in _valor("patched")]
        state = save_state({9: U9Nonfixed(_region(moved))})
        self.assertEqual([], state.stock_shrines())
        self.assertEqual([], state.lowered_shrines())

    def test_shrine_objects_are_matched_by_position(self) -> None:
        # A Dagger of Valor elsewhere on the map is not the shrine's.
        dagger = next(item for item in VALOR if item.type_index == 5288)
        region = _region(
            [(5288, dagger.world_x + 40, dagger.world_y, dagger.stock_z, 0)]
        )
        self.assertEqual({}, save_state({9: U9Nonfixed(region)}).shrine_heights)

    def test_installed_state_reads_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            (runtime / "NONFIXED.9").write_bytes(PATCHED_MAP)  # any case
            state = installed_state(runtime)
            self.assertTrue(state.companions)
            self.assertEqual({9}, set(state.maps))

    def test_a_missing_runtime_is_an_empty_state(self) -> None:
        state = installed_state(Path(tempfile.gettempdir()) / "no-such-u9-runtime")
        self.assertIsNone(state.companions)


class FanPatchIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("savegame", "static", "runtime"):
            (self.root / name).mkdir()
        (self.root / "static" / "fixed.9").write_bytes(_fixed())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _save(self, saved_map: bytes) -> None:
        processes = _processes()
        save = self.root / "savegame"
        (save / "start.dat").write_bytes(b"U9.008" + struct.pack("<i", 4))
        (save / "u9game4.sav").write_bytes(_archive(processes, saved_map))
        (save / "processes.dat").write_bytes(processes)
        (save / "nonfixed.9").write_bytes(saved_map)

    def _ids(self) -> dict[str, object]:
        report = check_save(self.root)
        return {f.check_id: f for f in report.findings if f.check_id.startswith("FWP")}

    def test_an_old_save_on_a_patched_install_raises_both(self) -> None:
        (self.root / "runtime" / "nonfixed.9").write_bytes(PATCHED_MAP)
        self._save(STOCK_MAP)
        report = check_save(self.root)
        found = {f.check_id: f for f in report.findings if f.check_id.startswith("FWP")}
        self.assertEqual({"FWP01", "FWP02"}, set(found))
        self.assertTrue(all(f.severity == "INFO" for f in found.values()))
        self.assertEqual("Valor", found["FWP02"].details["shrine_names"])
        self.assertEqual(
            "PASS", report.verdict("compatibility"), "information, not damage"
        )

        plain = describe_u9_save_integrity(report)
        text = repr(plain)
        self.assertIn("Started before the fan patch's companion fix", text)
        self.assertIn("Some Runes will still float", text)
        self.assertIn("Valor", text)

    def test_a_save_started_on_the_patch_raises_nothing(self) -> None:
        (self.root / "runtime" / "nonfixed.9").write_bytes(PATCHED_MAP)
        self._save(PATCHED_MAP)
        self.assertEqual({}, self._ids())

    def test_an_old_save_on_a_stock_install_raises_nothing(self) -> None:
        (self.root / "runtime" / "nonfixed.9").write_bytes(STOCK_MAP)
        self._save(STOCK_MAP)
        self.assertEqual({}, self._ids())

    def test_no_runtime_folder_raises_nothing(self) -> None:
        (self.root / "runtime").rmdir()
        self._save(STOCK_MAP)
        self.assertEqual({}, self._ids())


if __name__ == "__main__":
    unittest.main()
