"""Deprecated shim: import from ``titan.u8.shape`` instead.

``titan.shape`` is the U8 module's pre-split location; it warns on import
and will be removed in a later release."""

import warnings
from titan.u8.shape import U8Shape

warnings.warn(
    "titan.shape is deprecated; import from titan.u8.shape instead",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ["U8Shape"]
