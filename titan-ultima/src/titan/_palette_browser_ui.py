"""Shared numbered colour swatches for U7 and U8 palette browsers."""

from __future__ import annotations

import shutil
from collections.abc import Sequence

from titan import _wizard_ui as ui


def show_palette_colour_grid(
    colours: Sequence[tuple[int, int, int]], start: int = 0, count: int = 64
) -> None:
    """Readable index cells with the same terminal sizing in both games."""
    columns = max(1, min(16, (shutil.get_terminal_size((80, 30)).columns - 2) // 4))
    end = min(len(colours), start + count)
    for row in range(start, end, columns):
        fragments = [("", "  ")]
        for index in range(row, min(row + columns, end)):
            rgb = colours[index]
            colour = "#{:02x}{:02x}{:02x}".format(*rgb)
            ink = (
                "#000000"
                if sum(a * b for a, b in zip(rgb, (299, 587, 114))) >= 128000
                else "#ffffff"
            )
            fragments.extend([(f"bg:{colour} fg:{ink}", f"{index:03d}"), ("", " ")])
        ui.print_coloured(fragments)
