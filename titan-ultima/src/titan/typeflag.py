"""Deprecated shim: import from ``titan.u8.typeflag`` instead.

``titan.typeflag`` is the U8 module's pre-split location; it warns on import
and will be removed in a later release."""

import warnings
from titan.u8.typeflag import U8TypeFlags

warnings.warn(
    "titan.typeflag is deprecated; import from titan.u8.typeflag instead",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ["U8TypeFlags"]
