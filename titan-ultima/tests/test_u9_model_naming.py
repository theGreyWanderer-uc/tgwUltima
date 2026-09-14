"""Tests for titan.u9.model_naming's best-effort model-ID -> label lookup.

Reproduces the two real, verified scenarios this module exists for
(see its module docstring): a model claimed by exactly one named type
(model 1805 -> "Lord British" in the real game), and a model claimed by
several named types at once (model 3448 -> six different named types
in the real game) -- using small hand-built fixtures rather than the
real archives.
"""

from __future__ import annotations

import struct
import unittest

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.model_naming import (
    MAX_LABEL_LENGTH,
    label_for_model,
    names_for_model,
    slugify,
)
from titan.u9.typename import U9TypeNames
from titan.u9.types_dat import U9TypesDat

TYPENAME_DIR_OFFSET = 0x80
TYPENAME_MARKER = 0x1B81
TYPES_DAT_HEADER_SIZE = 8
TYPES_DAT_RECORD_STRUCT = "<IHHHBBBBH"
TYPES_DAT_MAX_RECORDS = 8192


def _typename_entry(name: str | None) -> bytes:
    header = struct.pack("<IH", 0, TYPENAME_MARKER)
    return header if name is None else header + name.encode("ascii") + b"\x00"


def _build_typenames(entries_data: list[bytes]) -> U9TypeNames:
    count = len(entries_data)
    dir_size = count * 8
    header = bytearray(TYPENAME_DIR_OFFSET)
    struct.pack_into("<I", header, 0x50, count)
    struct.pack_into("<I", header, 0x54, 2)  # FLX format-version word

    payload = bytearray()
    dir_entries = []
    cursor = TYPENAME_DIR_OFFSET + dir_size
    for data in entries_data:
        dir_entries.append((cursor, len(data)))
        payload += data
        cursor += len(data)

    directory = bytearray()
    for offset, length in dir_entries:
        directory += struct.pack("<II", offset, length)

    archive = U9FlxArchive(bytes(header) + bytes(directory) + bytes(payload))
    return U9TypeNames(archive)


def _types_record(default_model_id: int) -> bytes:
    return struct.pack(TYPES_DAT_RECORD_STRUCT, 0, 0, default_model_id, 0, 0, 0, 0, 0, 0)


def _build_types(default_model_ids: list[int]) -> U9TypesDat:
    """A complete 131,080-byte TYPES.DAT: the given types, then empty ones.

    U9TypesDat requires the exact 8 + 16*8192 layout, since that size is
    the only thing distinguishing a TYPES.DAT from any other file.
    """
    records = [_types_record(m) for m in default_model_ids]
    records += [_types_record(0)] * (TYPES_DAT_MAX_RECORDS - len(records))
    return U9TypesDat(b"\x00" * TYPES_DAT_HEADER_SIZE + b"".join(records))


class SlugifyTests(unittest.TestCase):
    def test_lowercases_and_hyphenates(self) -> None:
        self.assertEqual(slugify("Lord British"), "lord-british")

    def test_collapses_punctuation_runs(self) -> None:
        self.assertEqual(slugify("Winged Gargoyle!!"), "winged-gargoyle")

    def test_empty_input_is_unnamed(self) -> None:
        self.assertEqual(slugify(""), "unnamed")


class NamesForModelTests(unittest.TestCase):
    def test_single_named_type_claims_model(self) -> None:
        # type_id 1 -> model 1805, named "Lord British" (real-data scenario).
        types = _build_types([0, 1805])
        typenames = _build_typenames([_typename_entry(None), _typename_entry("Lord British")])

        self.assertEqual(names_for_model(1805, types, typenames), ["Lord British"])
        self.assertEqual(label_for_model(1805, types, typenames), "lord-british")

    def test_multiple_named_types_share_one_model(self) -> None:
        # type_ids 1,2,3 all -> model 3448 (real-data scenario: 6 named types share one model).
        types = _build_types([3448, 3448, 3448])
        typenames = _build_typenames([
            _typename_entry("Valkadesh"),
            _typename_entry("Wislem"),
            _typename_entry("Winged Gargoyle"),
        ])

        self.assertEqual(names_for_model(3448, types, typenames), ["Valkadesh", "Wislem", "Winged Gargoyle"])
        self.assertEqual(label_for_model(3448, types, typenames), "valkadesh-wislem-winged-gargoyle")

    def test_unnamed_type_contributes_nothing(self) -> None:
        types = _build_types([42])
        typenames = _build_typenames([_typename_entry(None)])

        self.assertEqual(names_for_model(42, types, typenames), [])
        self.assertIsNone(label_for_model(42, types, typenames))

    def test_model_with_no_claiming_type_has_no_name(self) -> None:
        types = _build_types([1805])
        typenames = _build_typenames([_typename_entry("Lord British")])

        self.assertEqual(names_for_model(9999, types, typenames), [])
        self.assertIsNone(label_for_model(9999, types, typenames))


class LabelLengthRegressionTests(unittest.TestCase):
    """Labels are capped so nested export paths stay inside Windows' MAX_PATH.

    Model 766 is claimed by ten map types and produced a 155-character label.
    ``model-export-all`` writes ``<outdir>/<stem>/<stem>.obj``, putting the
    stem in the path twice, which cleared the 260-character limit on its own.
    """

    MODEL_ID = 99

    def _crowded_model(self, count: int = 20):
        """One model claimed by ``count`` named types -- the shape that got long."""
        types = _build_types([self.MODEL_ID] * count)
        typenames = _build_typenames(
            [_typename_entry(f"map of somewhere number {i}") for i in range(count)]
        )
        return types, typenames

    def test_long_label_is_capped(self) -> None:
        types, typenames = self._crowded_model()
        label = label_for_model(self.MODEL_ID, types, typenames)
        self.assertLessEqual(len(label), MAX_LABEL_LENGTH)

    def test_cap_falls_on_a_hyphen_not_mid_word(self) -> None:
        types, typenames = self._crowded_model()
        label = label_for_model(self.MODEL_ID, types, typenames)
        self.assertFalse(label.endswith("-"))
        full = label_for_model(self.MODEL_ID, types, typenames, max_length=10_000)
        self.assertGreater(len(full), MAX_LABEL_LENGTH)
        self.assertTrue(full.startswith(label))

    def test_short_label_is_untouched(self) -> None:
        types = _build_types([0, 1805])
        typenames = _build_typenames([_typename_entry(None), _typename_entry("Lord British")])
        self.assertEqual(label_for_model(1805, types, typenames), "lord-british")

    def test_max_length_is_overridable(self) -> None:
        types, typenames = self._crowded_model()
        label = label_for_model(self.MODEL_ID, types, typenames, max_length=20)
        self.assertLessEqual(len(label), 20)
        self.assertFalse(label.endswith("-"))

    def test_truncation_cannot_collide_two_models(self) -> None:
        # Callers pair the label with the zero-padded model id, which is what
        # keeps stems unique once the label itself is clipped.
        types = _build_types([1] * 20 + [2] * 20)
        typenames = _build_typenames(
            [_typename_entry(f"map of somewhere number {i}") for i in range(40)]
        )
        stems = {
            f"model_{model_id:05d}_{label_for_model(model_id, types, typenames)}"
            for model_id in (1, 2)
        }
        self.assertEqual(len(stems), 2)

    def test_exported_path_stays_within_max_path(self) -> None:
        # model-export-all nests the stem: <outdir>/<stem>/<stem>.obj
        types, typenames = self._crowded_model()
        stem = f"model_{self.MODEL_ID:05d}_{label_for_model(self.MODEL_ID, types, typenames)}"
        self.assertLess(len(stem) * 2 + len("/.obj"), 200)


if __name__ == "__main__":
    unittest.main()
