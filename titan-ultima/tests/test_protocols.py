"""Every game's palette (and archive) class meets the shared interface in
``titan.protocols``."""

from __future__ import annotations

import pytest

from titan.md.palette import build_martian_palette
from titan.protocols import Palette
from titan.u6.palette import U6Palette
from titan.u7.palette import U7Palette
from titan.u8.palette import U8Palette, U8PaletteError
from titan.u9.palette import EXPECTED_SIZE, U9Palette
from titan.uw1.palette import UW1Palette
from titan.uw2.palette import UW2Palette

PALETTES = {
    "u6": lambda: U6Palette(),
    "md": lambda: build_martian_palette(U6Palette()),
    "u7": lambda: U7Palette(),
    "u8": lambda: U8Palette(),
    "u9": lambda: U9Palette.parse(bytes(EXPECTED_SIZE)),
    "uw1": lambda: UW1Palette.from_data(bytes(768)),
    "uw2": lambda: UW2Palette.from_data(bytes(768)),
}


@pytest.mark.parametrize("game", sorted(PALETTES))
def test_every_palette_meets_the_palette_protocol(game: str) -> None:
    palette = PALETTES[game]()
    assert isinstance(palette, Palette)
    assert len(palette.colors) == 256
    flat = palette.to_flat_rgb()
    assert isinstance(flat, bytes) and len(flat) == 768
    assert flat[:3] == bytes(palette.colors[0])
    assert palette.to_pil_image(swatch_size=2).size == (32, 32)


@pytest.mark.parametrize("cls", [UW1Palette, UW2Palette])
def test_underworld_palettes_keep_their_older_names(cls) -> None:
    palette = cls.from_data(bytes(range(256)) * 3)
    assert palette.flattened_rgb() == list(palette.to_flat_rgb())
    assert palette.to_swatch_image(2).tobytes() == palette.to_pil_image(2).tobytes()


def test_u8_palette_errors_are_titan_data_errors() -> None:
    with pytest.raises(U8PaletteError, match="too small"):
        U8Palette.from_raw_bytes(b"\0" * 10)
    with pytest.raises(ValueError):  # still a ValueError for existing callers
        U8Palette.from_raw_bytes(b"")


def _u9_flx(entries: list[bytes | None]) -> bytes:
    """A minimal FLX: 0x80-byte header (count at 0x50, version 2 at 0x54),
    directory, payloads."""
    import struct

    header = bytearray(0x80)
    struct.pack_into("<II", header, 0x50, len(entries), 2)
    cursor = 0x80 + 8 * len(entries)
    directory, payload = bytearray(), bytearray()
    for data in entries:
        directory += struct.pack("<II", *((cursor, len(data)) if data else (0, 0)))
        if data:
            payload += data
            cursor += len(data)
    return bytes(header + directory + payload)


def _archives():
    from pathlib import Path

    from titan.flex import FlexArchive
    from titan.u6.lib import U6Library
    from titan.u7.flex import U7FlexArchive
    from titan.u9.flx_archive import U9FlxArchive
    from titan.uw2.ark import ArkArchive, ArkBlock

    flex, u7 = FlexArchive(), U7FlexArchive()
    flex.records = [b"one", b"", b"three"]
    u7.records = [b"one", b"", b"three"]
    lib = U6Library(
        (0).to_bytes(4, "little") + (12).to_bytes(4, "little") + bytes(4) + b"one"
    )
    ark = ArkArchive(
        Path("LEV.ARK"),
        b"\0" * 6 + b"one" + b"three",
        [ArkBlock(0, 6, 0, 3, 3), ArkBlock(1, 0, 0, 0, 0), ArkBlock(2, 9, 0, 5, 5)],
        (3).to_bytes(2, "little") + bytes(4),
    )
    return {
        "flex": (flex, [b"one", None, b"three"]),
        "u7flex": (u7, [b"one", None, b"three"]),
        "u9flx": (
            U9FlxArchive(_u9_flx([b"one", None, b"three"])),
            [b"one", None, b"three"],
        ),
        "u6lib": (lib, [None, b"one", None]),
        "uw2ark": (ark, [b"one", None, b"three"]),
    }


@pytest.mark.parametrize("kind", ["flex", "u7flex", "u9flx", "u6lib", "uw2ark"])
def test_every_indexed_archive_meets_the_protocol(kind: str) -> None:
    from titan.protocols import IndexedArchive

    archive, expected = _archives()[kind]
    assert isinstance(archive, IndexedArchive)
    assert archive.entry_count == len(expected)
    assert [archive.read(index) for index in range(archive.entry_count)] == expected
    for bad in (-1, archive.entry_count):
        with pytest.raises(IndexError):
            archive.read(bad)
