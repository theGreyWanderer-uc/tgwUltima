"""
U8 transform palette data.

Hardcoded colour-transform palette from ``graphics/XFormBlend.cpp``.
Used for translucent rendering effects (ghosts, invisibility, etc.).

Example::

    from titan.xformpal import U8_XFORM_PALETTE

    for i, (r, g, b, a) in enumerate(U8_XFORM_PALETTE):
        if a > 0:
            print(f"  [{i}] R={r} G={g} B={b} A={a}")
"""

from __future__ import annotations

__all__ = ["U8_XFORM_PALETTE"]

# 16 entries x 4 bytes (R, G, B, A).  Only indices 8–14 are non-zero.
U8_XFORM_PALETTE: list[tuple[int, int, int, int]] = [
    (0, 0, 0, 0),       # 0  unused
    (0, 0, 0, 0),       # 1  unused
    (0, 0, 0, 0),       # 2  unused
    (0, 0, 0, 0),       # 3  unused
    (0, 0, 0, 0),       # 4  unused
    (0, 0, 0, 0),       # 5  unused
    (0, 0, 0, 0),       # 6  unused
    (0, 0, 0, 0),       # 7  unused
    (48, 48, 48, 80),    # 8  green -> dark grey
    (24, 24, 24, 80),    # 9  black -> very dark grey
    (64, 64, 24, 64),    # 10 yellow tint
    (80, 80, 80, 80),    # 11 white -> grey
    (180, 90, 0, 80),    # 12 red -> orange
    (0, 0, 252, 40),     # 13 blue glow
    (0, 0, 104, 40),     # 14 dark blue glow
    (0, 0, 0, 0),       # 15 unused
]
