"""Deprecated shim: import from ``titan.u8.sound`` instead.

``titan.sound`` is the U8 module's pre-split location; it warns on import
and will be removed in a later release."""

import warnings
from titan.u8.sound import SonarcDecoder

warnings.warn(
    "titan.sound is deprecated; import from titan.u8.sound instead",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ["SonarcDecoder"]
