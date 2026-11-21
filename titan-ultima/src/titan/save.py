"""Deprecated shim: import from ``titan.u8.save`` instead.

``titan.save`` is the U8 module's pre-split location; it warns on import
and will be removed in a later release."""

import warnings
from titan.u8.save import U8SaveArchive

warnings.warn(
    "titan.save is deprecated; import from titan.u8.save instead",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ["U8SaveArchive"]
