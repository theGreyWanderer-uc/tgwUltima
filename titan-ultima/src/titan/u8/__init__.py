"""
Ultima 8: Pagan — game-specific modules.

Re-exports all U8 public symbols for convenient access::

    from titan.u8 import U8Shape, U8Palette, U8MapRenderer
"""

from __future__ import annotations

from titan.u8.shape import U8Shape
from titan.u8.map import U8MapRenderer, U8MapSampler
from titan.u8.sound import SonarcDecoder
from titan.u8.save import U8SaveArchive
from titan.u8.typeflag import U8TypeFlags
from titan.u8.credits import decrypt_credit_text
from titan.u8.xformpal import U8_XFORM_PALETTE

__all__ = [
    "U8Shape",
    "U8MapRenderer",
    "U8MapSampler",
    "SonarcDecoder",
    "U8SaveArchive",
    "U8TypeFlags",
    "decrypt_credit_text",
    "U8_XFORM_PALETTE",
]
