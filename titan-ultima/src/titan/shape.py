"""
Ultima 8 shape format handler (RLE compressed sprites).

Provides :class:`U8Shape` for reading, writing, and rendering Ultima 8
shape files (.shp) extracted from U8SHAPES.FLX, U8GUMPS.FLX, U8FONTS.FLX.

Example::

    from titan.shape import U8Shape
    from titan.palette import U8Palette

    pal = U8Palette.from_file("U8PAL.PAL")
    shape = U8Shape.from_file("0001.shp")
    images = shape.to_pngs(pal)
    for i, img in enumerate(images):
        img.save(f"frame_{i:04d}.png")

    # Round-trip: export → edit → import
    data = shape.to_bytes()
    shape2 = U8Shape.from_data(data)
"""

from __future__ import annotations

__all__ = ["U8Shape"]

import struct
from typing import Optional

import numpy as np
from PIL import Image

from titan.palette import U8Palette


class U8Shape:
    """
    Reader/writer for Ultima 8 shape files (.shp).

    U8 Shape binary layout::

        Offset 0, 2 bytes: uint16 – header field 0 (shape num / max width)
        Offset 2, 2 bytes: uint16 – header field 1 (max height / unknown)
        Offset 4, 2 bytes: uint16 – frame count
        Offset 6, N*6:     frame table (per frame):
            3 bytes: frame offset (from start of shape data, uint24 LE)
            1 byte:  unknown
            2 bytes: frame data size (uint16 LE)

    Each frame (at its offset within the shape data)::

        Offset  0, 2 bytes: shape number (uint16)
        Offset  2, 2 bytes: frame number (uint16)
        Offset  4, 4 bytes: unknown
        Offset  8, 2 bytes: compression flag (0=raw pixels, 1=RLE with runs)
        Offset 10, 2 bytes: width (sint16)
        Offset 12, 2 bytes: height (sint16)
        Offset 14, 2 bytes: x offset (sint16)
        Offset 16, 2 bytes: y offset (sint16)
        Offset 18, height*2: line offset table (uint16 per line, relative)
        After line table: RLE data for each line
    """

    class Frame:
        """A single frame within a shape."""

        def __init__(self) -> None:
            self.width: int = 0
            self.height: int = 0
            self.xoff: int = 0
            self.yoff: int = 0
            self.compressed: int = 0
            self.pixels: Optional[np.ndarray] = None  # height x width, uint8
            # Preserved for round-trip fidelity:
            self.frame_unknown: bytes = b'\x00' * 8   # 8 bytes at frame start
            self.table_unknown: int = 0                # 1 byte in frame table

    def __init__(self) -> None:
        self.header0: int = 0
        self.header1: int = 0
        self.frames: list[U8Shape.Frame] = []

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @classmethod
    def from_data(cls, data: bytes) -> U8Shape:
        """Parse a U8 shape from raw bytes."""
        shape = cls()
        if len(data) < 6:
            return shape

        shape.header0 = struct.unpack_from("<H", data, 0)[0]
        shape.header1 = struct.unpack_from("<H", data, 2)[0]
        frame_count = struct.unpack_from("<H", data, 4)[0]

        if frame_count == 0 or frame_count > 20000:
            return shape

        for i in range(frame_count):
            table_off = 6 + i * 6
            if table_off + 6 > len(data):
                break

            # 3-byte offset (uint24 LE)
            frame_offset = (data[table_off]
                            | (data[table_off + 1] << 8)
                            | (data[table_off + 2] << 16))
            # 1 byte unknown
            table_unk = data[table_off + 3]
            # 2-byte size
            frame_size = struct.unpack_from("<H", data, table_off + 4)[0]

            if frame_offset + 18 > len(data):
                shape.frames.append(U8Shape.Frame())  # empty stub
                continue

            frame = cls._parse_frame(data, frame_offset, frame_size)
            frame.table_unknown = table_unk
            shape.frames.append(frame)

        return shape

    @classmethod
    def from_file(cls, filepath: str) -> U8Shape:
        """Load a shape from a ``.shp`` file."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_data(data)

    @staticmethod
    def _parse_frame(data: bytes, offset: int, size: int) -> U8Shape.Frame:
        """Parse a single frame at the given offset."""
        frame = U8Shape.Frame()
        d = data[offset:]
        if len(d) < 18:
            return frame

        frame.frame_unknown = bytes(d[:8])  # preserve 8 unknown header bytes
        frame.compressed = struct.unpack_from("<H", d, 8)[0]
        frame.width = struct.unpack_from("<h", d, 10)[0]
        frame.height = struct.unpack_from("<h", d, 12)[0]
        frame.xoff = struct.unpack_from("<h", d, 14)[0]
        frame.yoff = struct.unpack_from("<h", d, 16)[0]

        if frame.width <= 0 or frame.height <= 0:
            return frame

        # Read line offset table (height entries, 2 bytes each)
        line_header_start = 18
        line_table_end = line_header_start + frame.height * 2
        if len(d) < line_table_end:
            return frame

        line_offsets: list[int] = []
        for row in range(frame.height):
            raw_off = struct.unpack_from("<H", d, line_header_start + row * 2)[0]
            # Relative offset: subtract remaining line table entries
            actual = raw_off - ((frame.height - row) * 2)
            line_offsets.append(actual)

        # RLE data starts after line offset table
        rle_base = line_table_end
        rle_data = d[rle_base:]

        # Decompress into pixel buffer (0xFF = transparent)
        pixels = np.full((frame.height, frame.width), 0xFF, dtype=np.uint8)

        for row in range(frame.height):
            if line_offsets[row] < 0 or line_offsets[row] >= len(rle_data):
                continue
            pos = line_offsets[row]
            xpos = 0

            while xpos < frame.width and pos < len(rle_data):
                # Read x skip
                xpos += rle_data[pos]
                pos += 1

                if xpos >= frame.width:
                    break

                if pos >= len(rle_data):
                    break

                # Read data length
                dlen = rle_data[pos]
                pos += 1

                if frame.compressed:
                    run_type = dlen & 1  # 1 = solid run, 0 = literal
                    dlen >>= 1
                else:
                    run_type = 0

                if dlen <= 0:
                    continue

                end_x = min(xpos + dlen, frame.width)
                actual_len = end_x - xpos

                if run_type == 0:
                    # Literal: read dlen bytes of pixel data
                    if pos + actual_len <= len(rle_data):
                        pixels[row, xpos:end_x] = np.frombuffer(
                            rle_data[pos:pos + actual_len], dtype=np.uint8
                        )
                    pos += dlen
                else:
                    # Solid run: single byte repeated
                    if pos < len(rle_data):
                        pixels[row, xpos:end_x] = rle_data[pos]
                    pos += 1

                xpos += dlen

        frame.pixels = pixels
        return frame

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def to_pngs(self, palette: U8Palette, transparent: bool = True
                ) -> list[Image.Image]:
        """
        Render all frames to PIL Images using the given palette.

        Args:
            palette: :class:`~titan.palette.U8Palette` for color mapping.
            transparent: If ``True``, transparent pixels become alpha=0.

        Returns:
            List of RGBA PIL Images, one per frame.
        """
        images: list[Image.Image] = []
        flat_rgb = palette.to_flat_rgb()

        for frame in self.frames:
            if frame.pixels is None or frame.width <= 0 or frame.height <= 0:
                # Create a 1x1 transparent placeholder
                img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
                images.append(img)
                continue

            # Create indexed image
            indexed = Image.fromarray(frame.pixels, mode="P")
            indexed.putpalette(flat_rgb)

            # Convert to RGBA for transparency
            rgba = indexed.convert("RGBA")

            if transparent:
                # Make transparent pixels (index 0xFF=255) fully transparent
                px = frame.pixels
                alpha = np.where(px == 0xFF, 0, 255).astype(np.uint8)
                rgba.putalpha(Image.fromarray(alpha, mode="L"))

            images.append(rgba)

        return images

    # ------------------------------------------------------------------
    # RGBA -> indexed palette quantiser
    # ------------------------------------------------------------------

    @staticmethod
    def quantize_to_palette(rgba_img: Image.Image,
                            palette: U8Palette) -> np.ndarray:
        """
        Convert an RGBA PIL Image to a palette-indexed uint8 pixel array.

        Args:
            rgba_img: Input RGBA image.
            palette:  :class:`~titan.palette.U8Palette` for colour mapping.

        Returns:
            numpy uint8 array (height x width).  Index 0xFF = transparent.
        """
        arr = np.asarray(rgba_img)                       # (H, W, 4) uint8
        h, w = arr.shape[:2]
        rgb = arr[:, :, :3].astype(np.int32)             # (H, W, 3)
        alpha = arr[:, :, 3]                              # (H, W)

        # Build palette lookup table (256 x 3, int32)
        pal_arr = np.array([palette.colors[i] for i in range(256)],
                           dtype=np.int32)                # (256, 3)

        # For every opaque pixel, find nearest palette entry (Euclidean RGB).
        flat_rgb = rgb.reshape(-1, 1, 3)                  # (N, 1, 3)
        diff = flat_rgb - pal_arr.reshape(1, 256, 3)      # (N, 256, 3)
        dist_sq = (diff * diff).sum(axis=2)               # (N, 256)
        nearest = dist_sq.argmin(axis=1).astype(np.uint8) # (N,)
        result = nearest.reshape(h, w)

        # Transparent pixels -> 0xFF
        result[alpha < 128] = 0xFF
        return result

    # ------------------------------------------------------------------
    # RLE compression (export / encode path)
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_rle_line(row: np.ndarray) -> bytes:
        """
        RLE-encode a single scan line of palette indices.

        Produces compressed-format (flag=1) RLE data matching the U8 format.
        Index 0xFF is treated as transparent (skip).

        Args:
            row: 1-D uint8 numpy array (width elements).

        Returns:
            Encoded bytes for this line.
        """
        out = bytearray()
        width = len(row)
        x = 0

        while x < width:
            # Count transparent pixels (skip)
            skip_start = x
            while x < width and row[x] == 0xFF:
                x += 1
            skip = x - skip_start

            if x >= width:
                # Trailing transparent — emit skip so decoder reaches width
                if skip > 0:
                    while skip > 255:
                        out.append(255)
                        out.append(0)   # dlen=0 -> zero-length run
                        skip -= 255
                    out.append(skip)
                break

            # Count non-transparent run
            run_start = x
            while x < width and row[x] != 0xFF:
                x += 1
            total_run = x - run_start

            # Emit in chunks of at most 127
            emitted = 0
            while emitted < total_run:
                chunk = min(total_run - emitted, 127)

                # Emit skip (real skip for first chunk, 0 for continuations)
                if emitted == 0:
                    while skip > 255:
                        out.append(255)
                        out.append(0)
                        skip -= 255
                    out.append(skip)
                else:
                    out.append(0)

                rp = row[run_start + emitted:run_start + emitted + chunk]

                # Check if chunk is all same value -> solid run
                if chunk > 0 and np.all(rp == rp[0]):
                    out.append((chunk << 1) | 1)
                    out.append(int(rp[0]))
                else:
                    out.append(chunk << 1)
                    out.extend(rp.tobytes())

                emitted += chunk

        return bytes(out)

    # ------------------------------------------------------------------
    # Shape binary serialiser
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """
        Serialize this shape to U8 shape binary format.

        Produces the exact binary layout consumed by :meth:`from_data`:
        6-byte header, frame table, per-frame headers + line tables + RLE data.

        Returns:
            Complete shape file bytes.
        """
        buf = bytearray()
        frame_count = len(self.frames)

        # --- Header (6 bytes) ---
        buf += struct.pack("<HHH", self.header0, self.header1, frame_count)

        # --- Placeholder frame table (frame_count x 6 bytes) ---
        table_base = len(buf)
        buf += b'\x00' * (frame_count * 6)

        # --- Frame data ---
        for f_idx, frame in enumerate(self.frames):
            frame_offset = len(buf)

            # Frame header: 8 unknown, 2 compression, 2 width, 2 height,
            #               2 xoff, 2 yoff = 18 bytes
            buf += frame.frame_unknown[:8].ljust(8, b'\x00')

            # Always write compressed = 1
            buf += struct.pack("<h", 1)
            buf += struct.pack("<h", frame.width)
            buf += struct.pack("<h", frame.height)
            buf += struct.pack("<h", frame.xoff)
            buf += struct.pack("<h", frame.yoff)

            if frame.pixels is not None and frame.height > 0 and frame.width > 0:
                # RLE-encode every line
                line_bufs: list[bytes] = []
                for row_idx in range(frame.height):
                    line_bufs.append(
                        self._encode_rle_line(frame.pixels[row_idx])
                    )

                # Compute cumulative RLE offsets within the RLE block
                rle_offsets: list[int] = []
                cum = 0
                for row_idx in range(frame.height):
                    rle_offsets.append(cum)
                    cum += len(line_bufs[row_idx])

                # Write line offset table (self-relative encoding):
                #   stored_value = rle_offset + (height - row) * 2
                for row_idx in range(frame.height):
                    stored = rle_offsets[row_idx] + (frame.height - row_idx) * 2
                    buf += struct.pack("<H", stored)

                # Write RLE data
                for lb in line_bufs:
                    buf += lb
            # else: 0x0 frame with no pixel data (placeholder)

            # Frame data size (from frame_offset to current end)
            frame_data_size = len(buf) - frame_offset

            # Patch frame table entry
            entry_off = table_base + f_idx * 6
            # 3-byte offset (uint24 LE)
            buf[entry_off] = frame_offset & 0xFF
            buf[entry_off + 1] = (frame_offset >> 8) & 0xFF
            buf[entry_off + 2] = (frame_offset >> 16) & 0xFF
            # 1-byte table unknown
            buf[entry_off + 3] = frame.table_unknown & 0xFF
            # 2-byte frame data size
            struct.pack_into("<H", buf, entry_off + 4, frame_data_size)

        return bytes(buf)
