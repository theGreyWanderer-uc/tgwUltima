"""
TITAN -- Tool for Interpreting and Transforming Archival Nodes.

A Python toolkit for working with Ultima file formats. Each game has its own
subpackage (``titan.u6``, ``titan.u7``, ``titan.u8``, ``titan.u9``, ``titan.md``,
``titan.uw1``, ``titan.uw2``, ``titan.uo``, ``titan.u3``); import from the module
that defines a name. The names re-exported here are the original U8 and U7
set, kept for existing code.

Library usage::

    from titan.flex import FlexArchive
    from titan.u8.palette import U8Palette
    from titan.u8.shape import U8Shape    # canonical U8 import path
    from titan.shape import U8Shape       # backward-compat shim (also works)

    archive = FlexArchive.from_file("U8SHAPES.FLX")
    archive.extract_all("shapes/")

    pal = U8Palette.from_file("U8PAL.PAL")
    shape = U8Shape.from_file("shapes/0001.shp")
    images = shape.to_pngs(pal)
"""

from __future__ import annotations

# Version is defined before submodule imports to avoid circular-import issues
# (flex.py imports TITAN_VERSION from ._version, which has no cycle).
from ._version import TITAN_VERSION, __version__

# Shared / game-agnostic modules
from .flex import FlexArchive, detect_record_type, get_extension_for_flex
from .music import XMIDIConverter

# U8-specific modules (canonical paths are titan.u8.*)
from .u8.palette import U8Palette
from .u8.shape import U8Shape
from .u8.sound import SonarcDecoder
from .u8.save import U8SaveArchive
from .u8.typeflag import U8TypeFlags
from .u8.map import U8MapRenderer, U8MapSampler
from .u8.credits import decrypt_credit_text
from .u8.xformpal import U8_XFORM_PALETTE

# U7-specific modules (canonical paths are titan.u7.*)
from .u7.shape import U7Shape
from .u7.palette import U7Palette
from .u7.sound import VocDecoder

__all__ = [
    "TITAN_VERSION",
    "__version__",
    # Shared
    "FlexArchive",
    "U8Palette",
    "XMIDIConverter",
    # U8
    "U8Shape",
    "SonarcDecoder",
    "U8SaveArchive",
    "U8TypeFlags",
    "U8MapRenderer",
    "U8MapSampler",
    # U7
    "U7Shape",
    "U7Palette",
    "VocDecoder",
    # Helpers
    "detect_record_type",
    "get_extension_for_flex",
    "decrypt_credit_text",
    "U8_XFORM_PALETTE",
]
