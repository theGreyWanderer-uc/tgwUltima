"""Deprecated shim: import from ``titan.u8.palette`` instead.

``titan.palette`` is the U8 module's pre-split location; it warns on import
and will be removed in a later release."""

import warnings
from titan.u8.palette import U8Palette

warnings.warn(
    "titan.palette is deprecated; import from titan.u8.palette instead",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ["U8Palette"]
