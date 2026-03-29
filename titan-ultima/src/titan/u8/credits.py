"""
Credit text decryption for Ultima 8.

Provides :func:`decrypt_credit_text` for decrypting ECREDITS.DAT and
QUOTES.DAT (position-dependent XOR cipher).

Example::

    from titan.credits import decrypt_credit_text

    with open("ECREDITS.DAT", "rb") as f:
        data = f.read()

    text = decrypt_credit_text(data)
    print(text)
"""

from __future__ import annotations

__all__ = ["decrypt_credit_text"]


def decrypt_credit_text(data: bytes) -> str:
    """
    Decrypt U8 credit / quote text files (position-dependent XOR cipher).

    Port of U8Game::getCreditText (games/U8Game.cpp).

    Files: ECREDITS.DAT (English credits), QUOTES.DAT (developer quotes).
    The CreditsGump uses special formatting::

        +  Title line (large, centred)
        &  Name line
        *  Newline / break
        }  Tab / role indent
    """
    result: list[str] = []
    for i, c in enumerate(data):
        if i <= 1:
            x = 0
        elif i == 2:
            x = 0xE1
        else:
            x = 0x20 * (i + 1) + (i >> 1)
            x += (i % 0x40) * ((i & 0xC0) >> 6) * 0x40
        d = (c ^ x) & 0xFF
        if d == 0:
            d = ord('\n')
        result.append(chr(d))
    return ''.join(result)
