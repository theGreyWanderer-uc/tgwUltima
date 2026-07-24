"""Tests for titan.u6.tile's U6AnimData (ANIMDATA frame substitution).

No real game files are used here -- the fixture is a hand-built 194-byte
buffer matching ANIMDATA's documented struct (u6data/u6tech.txt "Multiple
Animation Frames"): a u16 count followed by four fixed-size 0x20-entry
arrays. Confirmed against a real ANIMDATA and cross-checked against
Nuvie's TileManager::updateTileAnim, which implements the identical
substitution loop.

This module exists because rendering CHUNKS-referenced placeholder tiles
(e.g. water) without substitution produces wrong output: those tiles are
100%-transparent in the real data, so under render_tile_grid's opaque
mode they fall back to whatever color sits at palette index 255 (white
in the real U6PAL) -- exactly the "white squares in the middle of the
river" defect this class fixes.
"""

from __future__ import annotations

import struct
import unittest

import numpy as np

from titan.u6.tile import ANIMDATA_MAX_ENTRIES, U6AnimData


def _make_animdata_bytes(entries: list[tuple[int, int, int, int]]) -> bytes:
    """entries: list of (placeholder_tile, first_frame_tile, and_mask, shift)."""
    n = ANIMDATA_MAX_ENTRIES
    tile_to_animate = [0] * n
    first_anim_frame = [0] * n
    and_masks = [0] * n
    shift_values = [0] * n
    for i, (placeholder, first_frame, mask, shift) in enumerate(entries):
        tile_to_animate[i] = placeholder
        first_anim_frame[i] = first_frame
        and_masks[i] = mask
        shift_values[i] = shift

    data = struct.pack("<H", len(entries))
    data += struct.pack(f"<{n}H", *tile_to_animate)
    data += struct.pack(f"<{n}H", *first_anim_frame)
    data += struct.pack(f"<{n}B", *and_masks)
    data += struct.pack(f"<{n}B", *shift_values)
    return data


class ParseTests(unittest.TestCase):
    def test_parses_only_declared_entry_count(self):
        data = _make_animdata_bytes([(8, 448, 14, 1), (9, 456, 14, 1)])
        anim = U6AnimData.parse(data)
        self.assertEqual(len(anim.entries), 2)

    def test_real_file_shape(self):
        # Real ANIMDATA is 194 bytes: 2 + 32*2 + 32*2 + 32*1 + 32*1.
        data = _make_animdata_bytes([])
        self.assertEqual(len(data), 194)


class ResolveTileTests(unittest.TestCase):
    def setUp(self):
        # Matches the real water entry for placeholder tile 8: 8 frames
        # (and_mask=14=0b1110, shift=1 -> frame = (tick & 14) >> 1, i.e. 0-7).
        self.anim = U6AnimData.parse(_make_animdata_bytes([(8, 448, 14, 1)]))

    def test_non_placeholder_tile_passes_through_unchanged(self):
        self.assertEqual(self.anim.resolve_tile(100, tick=5), 100)

    def test_placeholder_resolves_to_first_frame_at_tick_zero(self):
        self.assertEqual(self.anim.resolve_tile(8, tick=0), 448)

    def test_placeholder_cycles_through_frames_with_tick(self):
        # tick=14 -> (14 & 14) >> 1 = 7 -> frame 7 -> tile 455
        self.assertEqual(self.anim.resolve_tile(8, tick=14), 455)

    def test_frame_for_tick_matches_documented_and_mask_shift_algorithm(self):
        entry = self.anim.entries[0]
        for tick in range(16):
            expected = (tick & 14) >> 1
            self.assertEqual(entry.frame_for_tick(tick), expected)


class ResolveGridTests(unittest.TestCase):
    def setUp(self):
        self.anim = U6AnimData.parse(
            _make_animdata_bytes([(8, 448, 14, 1), (9, 456, 14, 1)])
        )

    def test_grid_substitution_widens_dtype_beyond_uint8(self):
        grid = np.array([[8, 9], [100, 8]], dtype=np.uint8)
        resolved = self.anim.resolve_grid(grid, tick=0)
        self.assertEqual(resolved.dtype, np.uint16)
        # 448 would silently wrap to 192 in uint8 -- confirms it didn't.
        self.assertEqual(resolved[0, 0], 448)
        self.assertEqual(resolved[0, 1], 456)
        self.assertEqual(resolved[1, 0], 100)  # untouched
        self.assertEqual(resolved[1, 1], 448)

    def test_original_grid_is_not_mutated(self):
        grid = np.array([[8]], dtype=np.uint8)
        self.anim.resolve_grid(grid, tick=0)
        self.assertEqual(grid[0, 0], 8)

    def test_grid_substitution_respects_tick(self):
        grid = np.array([[8]], dtype=np.uint8)
        resolved = self.anim.resolve_grid(grid, tick=14)
        self.assertEqual(resolved[0, 0], 455)


if __name__ == "__main__":
    unittest.main()
