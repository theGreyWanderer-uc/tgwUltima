"""
Ultima 7 shape format handler.

Provides :class:`U7Shape` for reading and rendering shapes from
standalone ``.shp`` files and VGA Flex archives (``SHAPES.VGA``,
``FACES.VGA``, ``GUMPS.VGA``, ``SPRITES.VGA``).

U7 shapes come in two flavours:

* **Ground tiles** (shapes 0–149 in ``SHAPES.VGA``): raw 8×8 pixel data,
  64 bytes per frame, no RLE header.
* **RLE sprites** (all others): an 8-byte extent header followed by
  span-encoded pixel data.

Example::

    from titan.u7.shape import U7Shape
    from titan.u7.palette import U7Palette

    pal = U7Palette.from_file("PALETTES.FLX")
    shape = U7Shape.from_file("POINTERS.SHP")
    images = shape.to_pngs(pal)
    for i, img in enumerate(images):
        img.save(f"pointer_{i:04d}.png")

    # Load from a VGA Flex archive
    from titan.u7.flex import U7FlexArchive
    vga = U7FlexArchive.from_file("SHAPES.VGA")
    shape = U7Shape.from_data(vga.get_record(150))
    images = shape.to_pngs(pal)
"""

from __future__ import annotations

__all__ = ["U7Shape"]

import struct
from typing import Optional

import numpy as np
from PIL import Image

# Shapes 0..149 in SHAPES.VGA are 8×8 raw ground tiles (no RLE).
FIRST_OBJ_SHAPE = 0x96  # 150 — matches Exult's c_first_obj_shape
TILE_SIZE = 8
NUM_TILE_BYTES = TILE_SIZE * TILE_SIZE  # 64


# ---------------------------------------------------------------------------
# RLE encoding helpers (used by Frame.to_rle_bytes)
# ---------------------------------------------------------------------------

def _find_opaque_spans(row: np.ndarray) -> list[tuple[int, int]]:
    """Return (start, end) pairs of contiguous non-transparent pixel runs.

    Transparent pixels have index 0xFF.
    """
    spans: list[tuple[int, int]] = []
    w = len(row)
    i = 0
    while i < w:
        if row[i] != 0xFF:
            start = i
            while i < w and row[i] != 0xFF:
                i += 1
            spans.append((start, i))
        else:
            i += 1
    return spans


def _encode_rle_segment(segment: np.ndarray) -> bytes:
    """Encode a span of opaque pixels using U7 RLE blocks.

    Each block: 1 byte header (bit 0 = repeat flag, bits 1-7 = count),
    followed by either 1 byte (repeat) or *count* bytes (literal).
    """
    parts: list[bytes] = []
    n = len(segment)
    i = 0
    while i < n:
        # Check for a repeat run (≥3 identical consecutive pixels)
        run_len = 1
        while i + run_len < n and segment[i + run_len] == segment[i] and run_len < 127:
            run_len += 1

        if run_len >= 3:
            # Emit repeat block: header bit0=1, pixel value
            parts.append(bytes([(run_len << 1) | 1, segment[i]]))
            i += run_len
        else:
            # Collect a literal run (non-repeating pixels)
            lit_start = i
            while i < n:
                # Check if a repeat of ≥3 starts here
                if i + 2 < n and segment[i] == segment[i + 1] == segment[i + 2]:
                    break
                i += 1
                if i - lit_start >= 127:
                    break
            lit_len = i - lit_start
            # Emit literal block: header bit0=0, then pixel bytes
            parts.append(bytes([lit_len << 1]))
            parts.append(bytes(segment[lit_start:lit_start + lit_len]))

    return b"".join(parts)


class U7Shape:
    """
    Reader for Ultima 7 shape data.

    A shape contains one or more frames.  Each frame is either a raw 8×8
    ground tile or an RLE-compressed sprite with an extent header.

    Binary layout (per shape record in a VGA Flex)::

        Offset 0:  uint32 — total size of shape data
        Offset 4:  uint32[] — frame offset table (N entries)
                   N = (first_offset − 4) / 4

    For standalone ``.shp`` files (e.g. ``POINTERS.SHP``) the layout is
    identical.

    Each RLE frame (at offset within shape data)::

        Bytes 0-1:  uint16 LE — xright  (extent to right of hot-spot)
        Bytes 2-3:  uint16 LE — xleft   (extent to left)
        Bytes 4-5:  uint16 LE — yabove  (extent above)
        Bytes 6-7:  uint16 LE — ybelow  (extent below)
        Bytes 8+:   span data (see _decode_rle_spans)
    """

    class Frame:
        """A single frame within a shape."""

        __slots__ = ("width", "height", "xoff", "yoff", "pixels", "is_tile")

        def __init__(self) -> None:
            self.width: int = 0
            self.height: int = 0
            self.xoff: int = 0
            self.yoff: int = 0
            self.pixels: Optional[np.ndarray] = None  # height×width uint8
            self.is_tile: bool = False

        def to_rle_bytes(self) -> bytes:
            """Encode this frame as U7 RLE binary data.

            Returns the 8-byte extent header followed by span-encoded
            pixel data and a ``0x0000`` end-of-frame marker.  Transparent
            pixels (index 0xFF) are omitted from the output spans.

            For raw 8×8 tile frames, returns 64 bytes of raw pixel data
            (no extent header).
            """
            if self.pixels is None:
                return b""

            if self.is_tile:
                return self.pixels.astype(np.uint8).tobytes()

            pix = self.pixels
            xleft = self.xoff
            yabove = self.yoff
            xright = self.width - xleft - 1
            ybelow = self.height - yabove - 1

            parts: list[bytes] = []
            # 8-byte extent header
            parts.append(struct.pack("<hhhh", xright, xleft, yabove, ybelow))

            # Encode each scanline row by row
            for row_idx in range(self.height):
                row = pix[row_idx]
                scany = row_idx - yabove  # relative to hotspot

                # Find contiguous runs of non-transparent pixels
                spans = _find_opaque_spans(row)

                for start_col, end_col in spans:
                    segment = row[start_col:end_col]
                    scanx = start_col - xleft  # relative to hotspot
                    npixels = len(segment)

                    # Decide: raw vs RLE encoded
                    rle_data = _encode_rle_segment(segment)
                    raw_data = bytes(segment)

                    if len(rle_data) < len(raw_data):
                        # Use RLE-encoded span (bit 0 = 1)
                        scanlen = (npixels << 1) | 1
                        parts.append(struct.pack("<Hhh", scanlen, scanx, scany))
                        parts.append(rle_data)
                    else:
                        # Use raw span (bit 0 = 0)
                        scanlen = npixels << 1
                        parts.append(struct.pack("<Hhh", scanlen, scanx, scany))
                        parts.append(raw_data)

            # End-of-frame marker
            parts.append(struct.pack("<H", 0))
            return b"".join(parts)

    def __init__(self) -> None:
        self.frames: list[U7Shape.Frame] = []

    # ------------------------------------------------------------------
    # Encoding — shape record builder
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Pack all frames into a complete U7 shape record.

        Returns bytes suitable for writing as a standalone ``.shp`` file
        or inserting into a VGA Flex archive via :class:`FlexArchive`.

        Layout::

            uint32   total_size (includes this field)
            uint32[] frame_offset_table (N entries, offsets from byte 0)
            bytes[]  frame data blocks (RLE or raw tile)
        """
        if not self.frames:
            return b""

        # For tile-only shapes, just concatenate raw tile data.
        if all(f.is_tile for f in self.frames):
            return b"".join(f.to_rle_bytes() for f in self.frames)

        # Encode each frame
        frame_blobs: list[bytes] = []
        for f in self.frames:
            frame_blobs.append(f.to_rle_bytes())

        # Build offset table: offsets are relative to byte 0 of the record.
        # Layout: [total_size(4)] [offset_table(N*4)] [frame_data...]
        num_frames = len(frame_blobs)
        table_start = 4  # after the total_size field
        data_start = table_start + num_frames * 4

        offsets: list[int] = []
        current = data_start
        for blob in frame_blobs:
            offsets.append(current)
            current += len(blob)

        total_size = current

        parts: list[bytes] = [struct.pack("<I", total_size)]
        for off in offsets:
            parts.append(struct.pack("<I", off))
        parts.extend(frame_blobs)
        return b"".join(parts)

    def save(self, filepath: str) -> None:
        """Write the shape to a standalone ``.shp`` file."""
        data = self.to_bytes()
        with open(filepath, "wb") as f:
            f.write(data)

    # ------------------------------------------------------------------
    # Parsing — standalone .shp / VGA Flex record
    # ------------------------------------------------------------------

    @classmethod
    def from_data(cls, data: bytes, *, is_tile: bool = False) -> U7Shape:
        """Parse a U7 shape from raw bytes.

        Parameters
        ----------
        data:
            Raw shape record (from a VGA Flex or standalone .shp file).
        is_tile:
            If ``True``, treat the data as raw 8×8 ground-tile frames
            (no size/offset header, just N*64 bytes of pixel data).
        """
        shape = cls()
        if not data:
            return shape

        if is_tile:
            return cls._parse_tile(data)

        # Detect tile vs RLE automatically.
        # Tiles: total length is a multiple of 64 and there is no valid
        # offset table (first uint32 would need to be > 4 and == 4 + N*4).
        if cls._looks_like_tile(data):
            return cls._parse_tile(data)

        return cls._parse_rle(data)

    @classmethod
    def from_file(cls, filepath: str) -> U7Shape:
        """Load a shape from a standalone ``.shp`` file."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_data(data)

    # ------------------------------------------------------------------
    # Internal: tile detection
    # ------------------------------------------------------------------

    @staticmethod
    def _looks_like_tile(data: bytes) -> bool:
        """Heuristic: is *data* raw 8×8 tile frames (not RLE)?"""
        n = len(data)
        if n == 0 or n % NUM_TILE_BYTES != 0:
            return False
        # If first uint32 equals the total data length, it is an RLE shape
        # (the "size" header of the shape).
        if n >= 4:
            first = struct.unpack_from("<I", data, 0)[0]
            if first == n:
                return False
            # A valid RLE shape has first_offset in [8, len) and
            # (first_offset - 4) % 4 == 0.
            if 8 <= first < n and (first - 4) % 4 == 0:
                return False
        return True

    @classmethod
    def _parse_tile(cls, data: bytes) -> U7Shape:
        """Parse ground-tile data: N frames of raw 8×8 pixel bytes."""
        shape = cls()
        num_frames = len(data) // NUM_TILE_BYTES
        for i in range(num_frames):
            frame = cls.Frame()
            frame.is_tile = True
            frame.width = TILE_SIZE
            frame.height = TILE_SIZE
            frame.xoff = TILE_SIZE
            frame.yoff = TILE_SIZE
            start = i * NUM_TILE_BYTES
            frame.pixels = np.frombuffer(
                data[start:start + NUM_TILE_BYTES], dtype=np.uint8
            ).reshape((TILE_SIZE, TILE_SIZE)).copy()
            shape.frames.append(frame)
        return shape

    # ------------------------------------------------------------------
    # Internal: RLE shape parsing
    # ------------------------------------------------------------------

    @classmethod
    def _parse_rle(cls, data: bytes) -> U7Shape:
        """Parse an RLE shape with size header + frame offsets."""
        shape = cls()
        if len(data) < 4:
            return shape

        shape_size = struct.unpack_from("<I", data, 0)[0]
        if shape_size <= 4 or shape_size > len(data):
            # Fall back: might be a single-frame with no size prefix —
            # try decoding directly as a single RLE frame.
            frame = cls._decode_rle_frame(data, 0, len(data))
            if frame.pixels is not None:
                shape.frames.append(frame)
            return shape

        # Offset table starts at byte 4; first entry tells us the end.
        first_offset = struct.unpack_from("<I", data, 4)[0]
        if first_offset <= 4 or (first_offset - 4) % 4 != 0:
            return shape

        num_frames = (first_offset - 4) // 4
        offsets: list[int] = []
        for i in range(num_frames):
            off = struct.unpack_from("<I", data, 4 + i * 4)[0]
            offsets.append(off)

        for i, off in enumerate(offsets):
            # Frame length = next offset − this offset (or end of shape).
            if i + 1 < len(offsets):
                flen = offsets[i + 1] - off
            else:
                flen = shape_size - off
            if off >= len(data):
                shape.frames.append(cls.Frame())  # empty stub
                continue
            frame = cls._decode_rle_frame(data, off, flen)
            shape.frames.append(frame)

        return shape

    @classmethod
    def _decode_rle_frame(cls, data: bytes, offset: int, length: int
                          ) -> U7Shape.Frame:
        """Decode one RLE frame at *offset* with *length* bytes."""
        frame = cls.Frame()
        d = data[offset:]
        if len(d) < 8:
            return frame

        xright = struct.unpack_from("<h", d, 0)[0]   # signed!
        xleft = struct.unpack_from("<h", d, 2)[0]
        yabove = struct.unpack_from("<h", d, 4)[0]
        ybelow = struct.unpack_from("<h", d, 6)[0]

        frame.width = xleft + xright + 1
        frame.height = yabove + ybelow + 1
        frame.xoff = xleft
        frame.yoff = yabove

        if frame.width <= 0 or frame.height <= 0:
            return frame
        if frame.width > 4096 or frame.height > 4096:
            return frame

        # 0xFF = transparent
        pixels = np.full((frame.height, frame.width), 0xFF, dtype=np.uint8)

        # Decode spans starting after the 8-byte header.
        pos = 8
        dv = memoryview(d)
        dlen = len(d)

        while pos + 2 <= dlen:
            scanlen = struct.unpack_from("<H", d, pos)[0]
            pos += 2
            if scanlen == 0:
                break  # end-of-frame marker

            encoded = scanlen & 1
            npixels = scanlen >> 1

            if pos + 4 > dlen:
                break
            scanx = struct.unpack_from("<h", d, pos)[0]
            pos += 2
            scany = struct.unpack_from("<h", d, pos)[0]
            pos += 2

            # Convert to pixel coordinates relative to top-left.
            px = scanx + xleft
            py = scany + yabove

            if not encoded:
                # Raw span: next npixels bytes are literal pixel indices.
                end = min(pos + npixels, dlen)
                count = end - pos
                if 0 <= py < frame.height and 0 <= px < frame.width:
                    put = min(count, frame.width - px)
                    pixels[py, px:px + put] = np.frombuffer(
                        d[pos:pos + put], dtype=np.uint8
                    )
                pos += npixels
            else:
                # RLE span
                b = 0
                while b < npixels and pos < dlen:
                    bcnt_raw = d[pos]
                    pos += 1
                    repeat = bcnt_raw & 1
                    bcnt = bcnt_raw >> 1
                    if bcnt == 0:
                        break

                    cx = px + b
                    if repeat:
                        if pos >= dlen:
                            break
                        pix = d[pos]
                        pos += 1
                        if 0 <= py < frame.height and 0 <= cx < frame.width:
                            put = min(bcnt, frame.width - cx)
                            pixels[py, cx:cx + put] = pix
                    else:
                        end = min(pos + bcnt, dlen)
                        count = end - pos
                        if 0 <= py < frame.height and 0 <= cx < frame.width:
                            put = min(count, frame.width - cx)
                            pixels[py, cx:cx + put] = np.frombuffer(
                                d[pos:pos + put], dtype=np.uint8
                            )
                        pos += bcnt
                    b += bcnt

        frame.pixels = pixels
        return frame

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def to_pngs(self, palette, *, transparent: bool = True
                ) -> list[Image.Image]:
        """Render all frames to PIL Images using the given palette.

        Parameters
        ----------
        palette:
            A palette object with a ``to_flat_rgb()`` method (returns
            768 bytes of R,G,B triples) and a ``transparent_index``
            attribute.  Both :class:`~titan.palette.U8Palette` and
            :class:`~titan.u7.palette.U7Palette` satisfy this.
        transparent:
            If True, transparent pixels become alpha=0.
        """
        images: list[Image.Image] = []
        flat_rgb = palette.to_flat_rgb()
        tidx = getattr(palette, "transparent_index", 255)

        for frame in self.frames:
            if frame.pixels is None or frame.width <= 0 or frame.height <= 0:
                images.append(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
                continue

            indexed = Image.fromarray(frame.pixels, mode="P")
            indexed.putpalette(flat_rgb)
            rgba = indexed.convert("RGBA")

            if transparent:
                alpha = np.where(frame.pixels == tidx, 0, 255).astype(np.uint8)
                rgba.putalpha(Image.fromarray(alpha, mode="L"))

            images.append(rgba)

        return images
