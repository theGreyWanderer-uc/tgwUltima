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
    from titan.u8.shape import U8Shape

    archive = FlexArchive.from_file("U8SHAPES.FLX")
    archive.extract_all("shapes/")

    pal = U8Palette.from_file("U8PAL.PAL")
    shape = U8Shape.from_file("shapes/0001.shp")
    images = shape.to_pngs(pal)
"""

from __future__ import annotations

from importlib import import_module

from ._version import TITAN_VERSION, __version__

# The original U8 and U7 names, loaded on first use: importing any titan module
# runs this file, so eager imports here would load U8's map renderer, sound
# decoder and more for every caller (``titan._meta`` included).
_EXPORTS = {
    # Shared / game-agnostic (canonical paths shown)
    "FlexArchive": "titan.flex",
    "detect_record_type": "titan.flex",
    "get_extension_for_flex": "titan.flex",
    "XMIDIConverter": "titan.music",
    # U8 (canonical paths are titan.u8.*)
    "U8Palette": "titan.u8.palette",
    "U8Shape": "titan.u8.shape",
    "SonarcDecoder": "titan.u8.sound",
    "U8SaveArchive": "titan.u8.save",
    "U8TypeFlags": "titan.u8.typeflag",
    "U8MapRenderer": "titan.u8.map",
    "U8MapSampler": "titan.u8.map",
    "decrypt_credit_text": "titan.u8.credits",
    "U8_XFORM_PALETTE": "titan.u8.xformpal",
    # U7 (canonical paths are titan.u7.*)
    "U7Shape": "titan.u7.shape",
    "U7Palette": "titan.u7.palette",
    "VocDecoder": "titan.u7.sound",
}


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'titan' has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})


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
