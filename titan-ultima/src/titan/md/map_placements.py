"""Project MD object and actor footprints across wrapped world seams into a bounded crop."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import TypeVar

from titan.u6.actor import U6Actor
from titan.u6.object import U6Object

__all__ = ["project_martian_placements"]

_Placement = TypeVar("_Placement", bound=U6Object | U6Actor)


def project_martian_placements(
    placements: Iterable[_Placement],
    region: tuple[int, int, int, int],
    side: int,
) -> list[_Placement]:
    """Return detached seam aliases that can reach the crop, retaining anchor layer order.

    MD footprints extend at most one cell north/west of their anchor. A full
    atlas can need both an anchor's original position and its alias at +side;
    projecting whole anchors preserves overlap order at each end of the map.
    Lighting keeps original coordinates and performs its own context wrapping.
    """
    left, top, width, height = region
    result = []
    for obj in placements:
        for y in (obj.y - side, obj.y, obj.y + side):
            if not top <= y <= top + height:
                continue
            for x in (obj.x - side, obj.x, obj.x + side):
                if left <= x <= left + width:
                    result.append(
                        obj if (x, y) == (obj.x, obj.y) else replace(obj, x=x, y=y)
                    )
    return result
