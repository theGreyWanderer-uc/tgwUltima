"""UU2 block decompression."""

from __future__ import annotations


def decode_uw2_block(data: bytes) -> bytes:
    """Decode a UU2 LZ-style compressed block.

    UU2 compressed archive blocks carry a four-byte prefix that the known
    readers skip before processing control bytes.
    """

    if len(data) <= 4:
        return b""

    out = bytearray()
    pos = 4

    while pos < len(data):
        control = data[pos]
        pos += 1

        for _ in range(8):
            if pos >= len(data):
                break

            if control & 1:
                out.append(data[pos])
                pos += 1
            else:
                if pos + 1 >= len(data):
                    break

                m1 = data[pos]
                m2 = data[pos + 1]
                pos += 2

                rel = m1 | ((m2 & 0xF0) << 4)
                if rel & 0x800:
                    rel -= 0x1000
                count = (m2 & 0x0F) + 3
                rel += 18

                if rel > len(out):
                    raise ValueError(
                        f"UU2 back-reference points beyond output: rel={rel}, out={len(out)}"
                    )

                while rel < len(out) - 0x1000:
                    rel += 0x1000

                for _ in range(count):
                    if rel < 0 or rel >= len(out):
                        raise ValueError(
                            f"UU2 back-reference index out of range: rel={rel}, out={len(out)}"
                        )
                    out.append(out[rel])
                    rel += 1

            control >>= 1

    return bytes(out)
