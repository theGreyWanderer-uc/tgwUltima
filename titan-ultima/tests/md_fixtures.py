"""Synthetic MD retail-layout resources shared by map and inspection tests."""

import struct
from pathlib import Path

import pytest

from titan.md.gamestate import MD_STATE_REQUIRED_SIZE
from titan.u6.object import pack_position


def resource_library(data: bytes) -> bytes:
    return martian_library([data])


def martian_library(items: list[bytes | None]) -> bytes:
    """Build MD lib_32 offsets with a total-size header and explicit null slots."""
    position = 4 + len(items) * 4
    offsets = []
    payload = bytearray()
    for item in items:
        offsets.append(0xFF000000 if item is None else 0xE0000000 | position)
        if item is not None:
            payload.extend(item)
            position += len(item)
    return (
        struct.pack("<I", position) + struct.pack(f"<{len(items)}I", *offsets) + payload
    )


def object_block(x: int, y: int, z: int = 0) -> bytes:
    b0, b1, b2 = pack_position(x, y, z)
    return struct.pack("<H8B", 1, 0, b0, b1, b2, 10, 0, 1, 0)


def initial_martian_objlist() -> bytearray:
    """Three party slots and a valid 1895 clock, without any U6 clock bytes."""
    state = bytearray(MD_STATE_REQUIRED_SIZE)
    struct.pack_into("<4BH", state, 0x1CF3, 0, 8, 6, 1, 1895)
    state[0xFF0] = 3
    for index, name in enumerate((b"Avatar", b"Spector", b"Nellie_Bly")):
        state[0xF00 + index * 14 : 0xF00 + index * 14 + len(name)] = name
        state[0xFE0 + index] = index + 1
        state[0x100 + (index + 1) * 3 : 0x103 + (index + 1) * 3] = bytes(
            pack_position(index, 0, 0)
        )
        struct.pack_into("<H", state, 0x400 + (index + 1) * 2, 10)
        struct.pack_into("<H", state, 0x16F1 + (index + 1) * 2, 10)
        state[0x800 + index + 1] = 0x80
    return state


@pytest.fixture
def md_game(tmp_path: Path) -> Path:
    game = tmp_path / "MARTIAN"
    game.mkdir()
    tiles = b"".join(bytes([i % 64]) * 256 for i in range(2048))
    (game / "MASKTYPE.VGA").write_bytes(resource_library(bytes(2048)))
    (game / "MAPTILES.VGA").write_bytes(resource_library(tiles[: 512 * 256]))
    (game / "OBJTILES.VGA").write_bytes(tiles[512 * 256 :])
    (game / "MDPAL").write_bytes(b"".join(bytes([i % 64, 0, 0]) for i in range(512)))
    (game / "MAP").write_bytes(bytes(32256))
    (game / "CHUNKS").write_bytes(bytes([16]) * 64)
    anim = bytearray(194)
    struct.pack_into("<H", anim, 0, 1)
    struct.pack_into("<H", anim, 2, 16)
    struct.pack_into("<H", anim, 66, 32)
    anim[130] = 1
    (game / "ANIMDATA").write_bytes(anim)
    basetile = bytearray(2048)
    struct.pack_into("<H", basetile, 20, 600)
    (game / "BASETILE").write_bytes(basetile)
    (game / "TILEFLAG").write_bytes(bytes(7168))
    (game / "LZOBJBLK").write_bytes(resource_library(object_block(1, 1) + bytes(126)))
    (game / "LZDNGBLK").write_bytes(
        resource_library(object_block(1, 1, 1) + bytes(8) + initial_martian_objlist())
    )
    (game / "TALK.LZC").write_bytes(
        martian_library(
            [
                b"make build\n",
                None,
                b"\xff\x02Spector\xf2\xdf\xd3\x02\xa7\xce\xb6",
            ]
        )
    )
    (game / "LOOK.LZC").write_bytes(
        resource_library(
            struct.pack("<H", 0) + b"Nothing\0" + struct.pack("<H", 4) + b"canal\0"
        )
    )
    (game / "MDTEXT.LZC").write_bytes(
        martian_library([b"Book One\r\n*Page Two\0", b"Sign\0"])
    )
    return game
