"""Deprecated shim: import from ``titan.u8.xformpal`` instead.

``titan.xformpal`` is the U8 module's pre-split location; it warns on import
and will be removed in a later release."""

import warnings
from titan.u8.xformpal import U8_XFORM_PALETTE

warnings.warn(
    "titan.xformpal is deprecated; import from titan.u8.xformpal instead",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ["U8_XFORM_PALETTE"]
