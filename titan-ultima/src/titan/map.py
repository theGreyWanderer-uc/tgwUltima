"""Deprecated shim: import from ``titan.u8.map`` instead.

``titan.map`` is the U8 module's pre-split location; it warns on import
and will be removed in a later release."""

import warnings
from titan.u8.map import U8MapRenderer, U8MapSampler

warnings.warn(
    "titan.map is deprecated; import from titan.u8.map instead",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ["U8MapRenderer", "U8MapSampler"]
