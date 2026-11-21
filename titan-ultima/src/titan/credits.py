"""Deprecated shim: import from ``titan.u8.credits`` instead.

``titan.credits`` is the U8 module's pre-split location; it warns on import
and will be removed in a later release."""

import warnings
from titan.u8.credits import decrypt_credit_text

warnings.warn(
    "titan.credits is deprecated; import from titan.u8.credits instead",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ["decrypt_credit_text"]
