"""
TITAN -- Tool for Interpreting and Transforming Archival Nodes.

A Python toolkit for working with Ultima 8: Pagan file formats.

Library usage::

    from titan.flex import FlexArchive
    from titan.palette import U8Palette
    from titan.shape import U8Shape

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

from .flex import FlexArchive, detect_record_type, get_extension_for_flex
from .palette import U8Palette
from .shape import U8Shape
from .sound import SonarcDecoder
from .music import XMIDIConverter
from .save import U8SaveArchive
from .typeflag import U8TypeFlags
from .map import U8MapRenderer, U8MapSampler
from .credits import decrypt_credit_text
from .xformpal import U8_XFORM_PALETTE

__all__ = [
    "TITAN_VERSION",
    "__version__",
    # Core classes
    "FlexArchive",
    "U8Palette",
    "U8Shape",
    "SonarcDecoder",
    "XMIDIConverter",
    "U8SaveArchive",
    "U8TypeFlags",
    "U8MapRenderer",
    "U8MapSampler",
    # Helpers
    "detect_record_type",
    "get_extension_for_flex",
    "decrypt_credit_text",
    "U8_XFORM_PALETTE",
]
