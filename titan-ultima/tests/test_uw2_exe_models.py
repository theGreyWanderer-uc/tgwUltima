"""Tests for documented UW2.EXE built-in model decoding."""

import struct

import pytest

from titan.uw2.exe_models import UW2ModelArchive, UW2ModelError


def _synthetic_executable() -> bytes:
    table = 0x54CF0
    base = 0x54D8A
    info = 0x6908A
    data = bytearray(info + 32 * 5)
    struct.pack_into("<I", data, table, 0x59AA64D4)
    struct.pack_into("<H", data, table + 0x18 * 2, 0x0100)
    data[info + 0x18 * 5 : info + 0x18 * 5 + 5] = bytes((0x02, 0x8C, 0xCA, 0x00, 0x00))

    position = base + 0x0100
    struct.pack_into("<Ihhh", data, position, 0x6B, 72, 80, 120)
    position += 10
    for x, y, z, vertex_ref in ((0, 0, 0, 0), (256, 0, 0, 8), (0, 256, 0, 16)):
        struct.pack_into("<HhhhH", data, position, 0x007A, x, y, z, vertex_ref)
        position += 10
    struct.pack_into("<HHH", data, position, 0x00BC, 0x2682, 0)
    position += 6
    struct.pack_into("<HHHHH", data, position, 0x007E, 3, 0, 8, 16)
    position += 10
    struct.pack_into("<HHHH", data, position, 0x008C, 0, 0, 24)
    position += 8
    struct.pack_into("<HHHHH", data, position, 0x007E, 3, 0, 8, 24)
    position += 10
    struct.pack_into("<H", data, position, 0)
    return bytes(data)


def test_decodes_vertices_faces_and_executable_palette() -> None:
    archive = UW2ModelArchive.from_data(_synthetic_executable())

    model = archive.model(0x18)

    assert model.extents == pytest.approx((0.28125, 0.3125, 0.46875))
    assert len(model.triangles) == 2
    assert model.triangles[0].palette_index == 0xCA
    assert model.triangles[0].vertices[1].x == 1.0
    assert model.triangles[0].vertices[2].y == 1.0
    assert model.triangles[1].vertices[2].roof is True


def test_item_table_resolves_table_model() -> None:
    archive = UW2ModelArchive.from_data(_synthetic_executable())

    assert archive.model_for_item(0x0158) is archive.model(0x18)
    assert archive.model_for_item(0x0001) is None


def test_rejects_unknown_executable_build() -> None:
    with pytest.raises(UW2ModelError, match="no supported UW2 model table"):
        UW2ModelArchive.from_data(bytes(0x1000))
