"""
LZW decompression for Ultima 6 data files.

Most U6 files that are loaded into memory as a whole (driver files,
MAPTILES.VGA, individual library items, etc.) use a variable-width LZW
codec: a 4-byte little-endian uncompressed-size header, followed by
9..12-bit codewords. Code 0x100 resets the dictionary (and the codeword
immediately after it is always a raw literal byte, not a dictionary
lookup); code 0x101 marks end of stream. This is the same "compress"-style
growing-codeword LZW used by GIF, except the clear/end codes are pinned to
0x100/0x101 regardless of the current codeword width (rather than derived
from it), and the dictionary starts filling at 0x102.

Ported from the algorithm in Nuvie's ``files/U6Lzw.cpp`` (itself credited
there to a decompression writeup on nodling's now-defunct Ultima 6 site),
cross-checked against ``u6data/u6tech.txt``'s "Files and Compression"
section and pu6e's independent ``u6decode/lzw.c``. Read for byte-layout
reference only -- this is a fresh implementation, not a translation of
GPL or unlicensed source.

Example::

    from titan.u6.lzw import U6Lzw

    raw = U6Lzw.decompress_file("MAPTILES.VGA")
"""

from __future__ import annotations

__all__ = ["U6Lzw", "U6LzwError"]

import os
from dataclasses import dataclass

CLEAR_CODE = 0x100
END_CODE = 0x101
FIRST_FREE_CODE = 0x102
INITIAL_CODE_SIZE = 9
MAX_CODE_SIZE = 12
HEADER_SIZE = 4


class U6LzwError(Exception):
    """Raised when data is not a well-formed U6 LZW stream."""


@dataclass
class _DictEntry:
    """One dictionary entry: the byte appended to ``prefix``'s string."""

    root: int
    prefix: int


class U6Lzw:
    """Decoder for Ultima 6's variable-width LZW file format."""

    @classmethod
    def is_valid(cls, data: bytes) -> bool:
        """
        Whether ``data`` looks like a compressed U6 file.

        Requires at least 6 bytes, a zero top byte on the 4-byte size
        header (no U6 file decompresses to >16 MB), and the first 9-bit
        codeword after the header equal to CLEAR_CODE (0x100).
        """
        if len(data) < 6:
            return False
        if data[3] != 0:
            return False
        return data[4] == 0 and (data[5] & 1) == 1

    @classmethod
    def uncompressed_size(cls, data: bytes) -> int:
        """Decoded size in bytes, from the 4-byte little-endian header."""
        if not cls.is_valid(data):
            raise U6LzwError("not a valid U6 LZW buffer")
        return int.from_bytes(data[0:4], "little")

    @classmethod
    def decompress_file(cls, filepath: str | os.PathLike[str]) -> bytes:
        """Read and decompress a U6 file from disk."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.decompress(data)

    @classmethod
    def decompress(cls, data: bytes) -> bytes:
        """
        Decompress ``data``, or return it unchanged if it isn't LZW data.

        Not every U6 file is compressed (e.g. ``ANIMDATA``, ``OBJTILES.VGA``
        are stored as raw fixed-layout structs with no wrapper at all).
        Nuvie's ``U6Lzw::decompress_file`` has an analogous fallback that
        instead strips a presumed 8-byte header, but that does not hold up
        against real game data -- checked directly against ``ANIMDATA``
        from a real GOG-style install, which is 194 raw bytes matching its
        documented struct exactly, with no header of any kind. That
        fallback was not ported.
        """
        if cls.is_valid(data):
            return cls.decompress_buffer(data)
        return data

    @classmethod
    def decompress_buffer(cls, data: bytes) -> bytes:
        """Decompress a buffer known to be LZW-compressed, header included."""
        out_size = cls.uncompressed_size(data)
        payload = data[HEADER_SIZE:]
        out = bytearray()

        bit_pos = 0
        code_size = INITIAL_CODE_SIZE
        dict_limit = 1 << code_size
        next_code = FIRST_FREE_CODE
        table: dict[int, _DictEntry] = {}
        prev_code = 0

        def read_code(size: int) -> int:
            nonlocal bit_pos
            byte_off = bit_pos // 8
            b0 = payload[byte_off] if byte_off < len(payload) else 0
            b1 = payload[byte_off + 1] if byte_off + 1 < len(payload) else 0
            if size + (bit_pos % 8) > 16:
                b2 = payload[byte_off + 2] if byte_off + 2 < len(payload) else 0
            else:
                b2 = 0
            word = (b2 << 16) | (b1 << 8) | b0
            word >>= bit_pos % 8
            bit_pos += size
            return word & ((1 << size) - 1)

        def code_to_bytes(code: int) -> bytes:
            chain = bytearray()
            while code > 0xFF:
                entry = table[code]
                chain.append(entry.root)
                code = entry.prefix
            chain.append(code)
            chain.reverse()
            return bytes(chain)

        while len(out) < out_size:
            code = read_code(code_size)

            if code == CLEAR_CODE:
                code_size = INITIAL_CODE_SIZE
                dict_limit = 1 << code_size
                next_code = FIRST_FREE_CODE
                table.clear()
                code = read_code(code_size)
                out.append(code)
                prev_code = code
                continue

            if code == END_CODE:
                break

            if code < next_code:
                entry_bytes = code_to_bytes(code)
            else:
                if code != next_code:
                    raise U6LzwError(
                        f"corrupt LZW stream: codeword {code:#x} != next free {next_code:#x}"
                    )
                prev_bytes = code_to_bytes(prev_code)
                entry_bytes = prev_bytes + bytes([prev_bytes[0]])

            out.extend(entry_bytes)
            table[next_code] = _DictEntry(root=entry_bytes[0], prefix=prev_code)
            next_code += 1
            if next_code >= dict_limit and code_size < MAX_CODE_SIZE:
                code_size += 1
                dict_limit = 1 << code_size

            prev_code = code

        return bytes(out[:out_size])
