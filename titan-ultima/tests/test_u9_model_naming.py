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
from titan.u9.model_naming import label_for_model, names_for_model, slugify
from titan.u9.typename import U9TypeNames
from titan.u9.types_dat import U9TypesDat

TYPENAME_DIR_OFFSET = 0x80
TYPENAME_MARKER = 0x1B81
TYPES_DAT_HEADER_SIZE = 8
TYPES_DAT_RECORD_STRUCT = "<IHHHBBBBH"


def _typename_entry(name: str | None) -> bytes:
    header = struct.pack("<IH", 0, TYPENAME_MARKER)
    return header if name is None else header + name.encode("ascii") + b"\x00"


def _build_typenames(entries_data: list[bytes]) -> U9TypeNames:
    count = len(entries_data)
    dir_size = count * 8
    header = bytearray(TYPENAME_DIR_OFFSET)
    struct.pack_into("<I", header, 0x50, count)

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
    data = b"\x00" * TYPES_DAT_HEADER_SIZE + b"".join(_types_record(m) for m in default_model_ids)
    return U9TypesDat(data)


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


if __name__ == "__main__":
    unittest.main()
