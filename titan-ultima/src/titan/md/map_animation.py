"""Resolve MD map animation using confirmed clock and story-state controls.

The DOS power/load loops freeze stopped machinery at its first animation
frame. MD's watch uses scripts/md/init.lua's 416 + hour % 12. The DOS load
routine sets water animation masks to zero and selects adjacent dry/wet
frames from saved cistern/valve flags.
See reference/md/animation/md_water_animation_reference.md for the trace.
"""

from __future__ import annotations

from titan.md.game_profile import MD_PROFILE
from titan.md.gamestate import MartianGameState
from titan.md.power_state import is_martian_power_tile
from titan.u6.tile import U6AnimData, U6AnimEntry

__all__ = ["build_martian_animation"]


def build_martian_animation(
    raw: U6AnimData, state: MartianGameState | None = None
) -> U6AnimData:
    """Build a fresh resolver per snapshot so one save cannot contaminate later renders."""
    entries: list[U6AnimEntry] = []
    for entry in raw.entries:
        tile = entry.placeholder_tile
        if tile == 616:
            entries.append(
                U6AnimEntry(tile, 416 + (state.clock.hour % 12 if state else 0), 0, 0)
            )
        elif 1 <= tile <= 4:
            entries.append(
                U6AnimEntry(
                    tile,
                    entry.first_frame_tile + int(bool(state and state.cistern_filled)),
                    0,
                    0,
                )
            )
        elif 16 <= tile <= 23 or 192 <= tile <= 195:
            entries.append(
                U6AnimEntry(
                    tile,
                    entry.first_frame_tile + int(bool(state and state.canals_filled)),
                    0,
                    0,
                )
            )
        elif is_martian_power_tile(tile):
            entries.append(
                entry
                if state and state.power_active
                else U6AnimEntry(tile, entry.first_frame_tile, 0, 0)
            )
        elif tile not in MD_PROFILE.inactive_animation_tiles:
            entries.append(entry)
    return U6AnimData(entries)
