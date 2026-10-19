"""Ultima Online facet terrain (mapN) and static object (staidxN/staticsN) support."""

from __future__ import annotations

__all__ = [
    "FACET_DIMENSIONS",
    "UOLandCell",
    "UOMap",
    "UOMapSource",
    "UOStaticItem",
]

from dataclasses import dataclass
import mmap
from pathlib import Path
import struct

import numpy as np
from PIL import Image

from titan.uo.radar import UORadarColors
from titan.uo.uop import UOPArchive, hash_uop_path

BLOCK_BYTES = 196
STATIC_INDEX_BYTES = 12
STATIC_RECORD_BYTES = 7
_NO_DATA = 0xFFFFFFFF

# Facet tile dimensions for the current client layout. Facets 0/1 were
# 6144 wide before Mondain's Legacy; that size is recognised from block count.
FACET_DIMENSIONS: dict[int, tuple[int, int]] = {
    0: (7168, 4096),
    1: (7168, 4096),
    2: (2304, 1600),
    3: (2560, 2048),
    4: (1448, 1448),
    5: (1280, 4096),
}
_LEGACY_FELUCCA_TRAMMEL = (6144, 4096)

_STATIC_DTYPE = np.dtype(
    [("tile_id", "<u2"), ("x", "u1"), ("y", "u1"), ("z", "i1"), ("hue", "<u2")]
)


@dataclass(frozen=True)
class UOLandCell:
    """One terrain cell: land tile ID and altitude."""

    tile_id: int
    z: int


@dataclass(frozen=True)
class UOStaticItem:
    """One static object placed at absolute world coordinates."""

    tile_id: int
    x: int
    y: int
    z: int
    hue: int


@dataclass(frozen=True)
class UOMapSource:
    """Where a facet's data was read from, for manifests and reports."""

    land_path: str
    land_container: str
    staidx_path: str
    statics_path: str
    trailing_land_blocks: int
    land_patch_blocks: int
    static_patch_blocks: int


def _read_file(path: Path, mapped: bool):
    if not mapped or path.stat().st_size == 0:
        return path.read_bytes()
    with path.open("rb") as stream:
        return mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)


def _trim(buffer, length: int):
    """Limit a buffer to ``length`` bytes without copying mapped data."""
    if len(buffer) == length:
        return buffer
    if isinstance(buffer, bytes):
        return buffer[:length]
    return memoryview(buffer)[:length]


def _blocks_for(width: int, height: int) -> int:
    return ((width + 7) // 8) * ((height + 7) // 8)


def _read_uop_land(path: Path, stem: str) -> bytes:
    """Concatenate build/<stem>legacymul/NNNNNNNN.dat entries in index order."""
    archive = UOPArchive(path)
    chunks: list[bytes] = []
    index = 0
    while True:
        entry = archive.entries_by_hash.get(
            hash_uop_path(f"build/{stem}legacymul/{index:08d}.dat")
        )
        if entry is None:
            break
        chunks.append(archive.read_entry(entry))
        index += 1
    if not chunks:
        raise ValueError(f"no build/{stem}legacymul entries in {path}")
    if index != len(archive.entries):
        raise ValueError(
            f"{path.name}: {len(archive.entries) - index} entr(ies) outside the "
            f"build/{stem}legacymul sequence"
        )
    return b"".join(chunks)


class UOMap:
    """A facet's terrain and statics, held as flat MUL-layout buffers.

    Blocks are 8x8 tiles in column-major order: ``block = bx * blocks_high + by``.
    Inside a land block, cells are row-major: ``cell = ty * 8 + tx``.
    """

    def __init__(
        self,
        land: bytes,
        staidx: bytes,
        statics: bytes,
        width: int,
        height: int,
        *,
        facet: int | None = None,
        source: UOMapSource | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.blocks_wide = (width + 7) // 8
        self.blocks_high = (height + 7) // 8
        self.block_count = self.blocks_wide * self.blocks_high
        self.facet = facet
        self.source = source

        if len(land) < self.block_count * BLOCK_BYTES:
            raise ValueError(
                f"land data holds {len(land) // BLOCK_BYTES} block(s); "
                f"{width}x{height} needs {self.block_count}"
            )
        if len(staidx) < self.block_count * STATIC_INDEX_BYTES:
            raise ValueError(
                f"static index holds {len(staidx) // STATIC_INDEX_BYTES} block(s); "
                f"{width}x{height} needs {self.block_count}"
            )
        self.land = _trim(land, self.block_count * BLOCK_BYTES)
        self.staidx = _trim(staidx, self.block_count * STATIC_INDEX_BYTES)
        self.statics = statics

    # -- loading ---------------------------------------------------------

    @classmethod
    def from_client(
        cls,
        client: str | Path,
        facet: int,
        *,
        container: str = "auto",
        suffix: str = "",
        width: int | None = None,
        height: int | None = None,
        patches: bool = False,
        mapped: bool = False,
    ) -> UOMap:
        """Load facet ``facet`` from a client directory.

        ``container`` is ``auto`` (UOP when present, else MUL), ``uop`` or ``mul``.
        ``suffix`` selects alternate file sets such as ``map0x``/``staidx0x``;
        their UOP entries keep the unsuffixed ``build/map0legacymul`` name.
        ``patches`` applies mapdif/stadif difference files when present.
        ``mapped`` memory-maps the MUL files instead of reading them, so
        several processes share one copy through the OS page cache.
        """
        client = Path(client)
        name = f"map{facet}{suffix}"
        uop_path = client / f"{name}LegacyMUL.uop"
        mul_path = client / f"{name}.mul"

        if container not in ("auto", "uop", "mul"):
            raise ValueError(f"unknown map container: {container}")
        use_uop = container == "uop" or (container == "auto" and uop_path.is_file())
        if use_uop:
            if not uop_path.is_file():
                raise FileNotFoundError(f"{uop_path.name} not found")
            land = _read_uop_land(uop_path, f"map{facet}")
            land_path, land_container = uop_path, "uop"
        else:
            if not mul_path.is_file():
                raise FileNotFoundError(f"{mul_path.name} not found")
            land = _read_file(mul_path, mapped)
            land_path, land_container = mul_path, "mul"

        staidx_path = client / f"staidx{facet}{suffix}.mul"
        statics_path = client / f"statics{facet}{suffix}.mul"
        for path in (staidx_path, statics_path):
            if not path.is_file():
                raise FileNotFoundError(f"{path.name} not found")
        staidx = _read_file(staidx_path, mapped)
        statics = _read_file(statics_path, mapped)

        if width is None or height is None:
            width, height = cls._infer_dimensions(
                facet, len(staidx) // STATIC_INDEX_BYTES
            )
        blocks = _blocks_for(width, height)
        trailing = max(0, len(land) // BLOCK_BYTES - blocks)

        land_patched = static_patched = 0
        if patches:
            land, land_patched = cls._apply_land_patches(client, facet, land, blocks)
            staidx, statics, static_patched = cls._apply_static_patches(
                client, facet, staidx, statics, blocks
            )

        source = UOMapSource(
            land_path=str(land_path),
            land_container=land_container,
            staidx_path=str(staidx_path),
            statics_path=str(statics_path),
            trailing_land_blocks=trailing,
            land_patch_blocks=land_patched,
            static_patch_blocks=static_patched,
        )
        return cls(land, staidx, statics, width, height, facet=facet, source=source)

    @staticmethod
    def _infer_dimensions(facet: int, block_count: int) -> tuple[int, int]:
        known = FACET_DIMENSIONS.get(facet)
        if known is not None and _blocks_for(*known) == block_count:
            return known
        if facet in (0, 1) and _blocks_for(*_LEGACY_FELUCCA_TRAMMEL) == block_count:
            return _LEGACY_FELUCCA_TRAMMEL
        raise ValueError(
            f"cannot infer facet {facet} size from {block_count} static index "
            "block(s); pass width and height"
        )

    @staticmethod
    def _apply_land_patches(
        client: Path, facet: int, land: bytes, blocks: int
    ) -> tuple[bytes, int]:
        lookup_path = client / f"mapdifl{facet}.mul"
        data_path = client / f"mapdif{facet}.mul"
        if not (lookup_path.is_file() and data_path.is_file()):
            return land, 0
        lookup = lookup_path.read_bytes()
        data = data_path.read_bytes()
        count = min(len(lookup) // 4, len(data) // BLOCK_BYTES)
        out = bytearray(land)
        applied = 0
        for index in range(count):
            block = struct.unpack_from("<I", lookup, index * 4)[0]
            if block >= blocks:
                continue
            start = index * BLOCK_BYTES
            out[block * BLOCK_BYTES : (block + 1) * BLOCK_BYTES] = data[
                start : start + BLOCK_BYTES
            ]
            applied += 1
        return bytes(out), applied

    @staticmethod
    def _apply_static_patches(
        client: Path, facet: int, staidx: bytes, statics: bytes, blocks: int
    ) -> tuple[bytes, bytes, int]:
        lookup_path = client / f"stadifl{facet}.mul"
        index_path = client / f"stadifi{facet}.mul"
        data_path = client / f"stadif{facet}.mul"
        if not (lookup_path.is_file() and index_path.is_file() and data_path.is_file()):
            return staidx, statics, 0
        lookup = lookup_path.read_bytes()
        patch_index = index_path.read_bytes()
        base = len(statics)
        count = min(len(lookup) // 4, len(patch_index) // STATIC_INDEX_BYTES)
        out = bytearray(staidx)
        applied = 0
        for index in range(count):
            block = struct.unpack_from("<I", lookup, index * 4)[0]
            if block >= blocks:
                continue
            offset, length, extra = struct.unpack_from(
                "<III", patch_index, index * STATIC_INDEX_BYTES
            )
            if offset != _NO_DATA:
                offset += base
            struct.pack_into(
                "<III", out, block * STATIC_INDEX_BYTES, offset, length, extra
            )
            applied += 1
        return bytes(out), bytes(statics) + data_path.read_bytes(), applied

    # -- point access ----------------------------------------------------

    def block_index(self, block_x: int, block_y: int) -> int:
        if not (0 <= block_x < self.blocks_wide and 0 <= block_y < self.blocks_high):
            raise IndexError(f"block ({block_x}, {block_y}) outside facet")
        return block_x * self.blocks_high + block_y

    def land_block(self, block_x: int, block_y: int) -> list[UOLandCell]:
        """Return the 64 land cells of a block in row-major (y, x) order."""
        start = self.block_index(block_x, block_y) * BLOCK_BYTES + 4
        return [
            UOLandCell(*struct.unpack_from("<Hb", self.land, start + cell * 3))
            for cell in range(64)
        ]

    def block_header(self, block_x: int, block_y: int) -> int:
        start = self.block_index(block_x, block_y) * BLOCK_BYTES
        return struct.unpack_from("<I", self.land, start)[0]

    def land_tile(self, x: int, y: int) -> UOLandCell:
        start = (
            self.block_index(x // 8, y // 8) * BLOCK_BYTES
            + 4
            + ((y % 8) * 8 + (x % 8)) * 3
        )
        return UOLandCell(*struct.unpack_from("<Hb", self.land, start))

    def statics_block(self, block_x: int, block_y: int) -> list[UOStaticItem]:
        """Return a block's statics in stored order, at world coordinates."""
        offset, length, _extra = struct.unpack_from(
            "<III",
            self.staidx,
            self.block_index(block_x, block_y) * STATIC_INDEX_BYTES,
        )
        if offset == _NO_DATA or length == 0:
            return []
        items: list[UOStaticItem] = []
        for record in range(length // STATIC_RECORD_BYTES):
            tile_id, x, y, z, hue = struct.unpack_from(
                "<HBBbH", self.statics, offset + record * STATIC_RECORD_BYTES
            )
            items.append(
                UOStaticItem(tile_id, block_x * 8 + x, block_y * 8 + y, z, hue)
            )
        return items

    def statics_at(self, x: int, y: int) -> list[UOStaticItem]:
        return [
            item
            for item in self.statics_block(x // 8, y // 8)
            if item.x == x and item.y == y
        ]

    # -- whole-facet arrays ----------------------------------------------

    def land_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(tile_id, z)`` arrays shaped ``(height, width)``."""
        cells = (
            np.frombuffer(self.land, dtype=np.uint8)
            .reshape(self.block_count, BLOCK_BYTES)[:, 4:]
            .reshape(self.block_count, 64, 3)
        )
        ids = cells[:, :, 0].astype(np.uint16) | (cells[:, :, 1].astype(np.uint16) << 8)
        z = cells[:, :, 2].view(np.int8)
        return self._blocks_to_grid(ids), self._blocks_to_grid(z)

    def _blocks_to_grid(self, cells: np.ndarray) -> np.ndarray:
        grid = (
            cells.reshape(self.blocks_wide, self.blocks_high, 8, 8)
            .transpose(1, 2, 0, 3)
            .reshape(self.blocks_high * 8, self.blocks_wide * 8)
        )
        return grid[: self.height, : self.width]

    def static_records(self) -> np.ndarray:
        """Return every static as a structured array with world ``x``/``y``.

        Fields: ``tile_id``, ``x``, ``y``, ``z``, ``hue``, ``block``; rows keep
        block order, then stored order within each block.
        """
        index = np.frombuffer(self.staidx, dtype="<u4").reshape(self.block_count, 3)
        offsets = index[:, 0].astype(np.int64)
        counts = (index[:, 1] // STATIC_RECORD_BYTES).astype(np.int64)
        counts[index[:, 0] == _NO_DATA] = 0
        total = int(counts.sum())

        blocks = np.repeat(np.arange(self.block_count, dtype=np.int64), counts)
        firsts = np.cumsum(counts) - counts
        within = np.arange(total, dtype=np.int64) - np.repeat(firsts, counts)
        starts = np.repeat(offsets, counts) + within * STATIC_RECORD_BYTES
        if total and int(starts.max()) + STATIC_RECORD_BYTES > len(self.statics):
            raise ValueError("static index points past end of statics data")

        raw = np.frombuffer(self.statics, dtype=np.uint8)
        gathered = raw[starts[:, None] + np.arange(STATIC_RECORD_BYTES)]
        parsed = np.ascontiguousarray(gathered).view(_STATIC_DTYPE).reshape(total)

        out = np.empty(
            total,
            dtype=[
                ("tile_id", "<u2"),
                ("x", "<i4"),
                ("y", "<i4"),
                ("z", "i1"),
                ("hue", "<u2"),
                ("block", "<i4"),
            ],
        )
        out["tile_id"] = parsed["tile_id"]
        out["x"] = (blocks // self.blocks_high) * 8 + parsed["x"]
        out["y"] = (blocks % self.blocks_high) * 8 + parsed["y"]
        out["z"] = parsed["z"]
        out["hue"] = parsed["hue"]
        out["block"] = blocks
        return out

    def static_index_summary(self) -> dict[str, int]:
        index = np.frombuffer(self.staidx, dtype="<u4").reshape(self.block_count, 3)
        no_data = index[:, 0] == _NO_DATA
        zero_length = ~no_data & (index[:, 1] == 0)
        return {
            "blocks": self.block_count,
            "blocks_no_data": int(no_data.sum()),
            "blocks_zero_length": int(zero_length.sum()),
            "blocks_with_statics": int((~no_data & (index[:, 1] > 0)).sum()),
            "length_not_multiple_of_7": int(
                (~no_data & (index[:, 1] % STATIC_RECORD_BYTES != 0)).sum()
            ),
            "static_count": int(
                (index[~no_data, 1] // STATIC_RECORD_BYTES).sum()
            ),
        }

    # -- rendering -------------------------------------------------------

    def render_radar(
        self, radar: UORadarColors, *, statics: bool = True
    ) -> Image.Image:
        """Render one pixel per tile using radarcol colours.

        Each cell shows the highest of its land tile and statics by ``z``;
        statics win ties with land, and the later stored static wins ties
        between statics. Land uses ``radarcol[id]``, statics ``radarcol[0x4000 + id]``.
        """
        lut = np.zeros((max(len(radar.colors), 1), 3), dtype=np.uint8)
        for color in radar.colors:
            lut[color.index] = color.rgb

        land_ids, land_z = self.land_arrays()
        color_index = land_ids.astype(np.int64)

        if statics:
            records = self.static_records()
            if len(records):
                cell = records["y"].astype(np.int64) * self.width + records["x"]
                order = np.lexsort(
                    (np.arange(len(records)), records["z"].astype(np.int16), cell)
                )
                ordered_cell = cell[order]
                last = np.r_[ordered_cell[1:] != ordered_cell[:-1], True]
                top = order[last]
                top_cell = cell[top]
                top_y, top_x = top_cell // self.width, top_cell % self.width
                inside = (top_x < self.width) & (top_y < self.height)
                top, top_x, top_y = top[inside], top_x[inside], top_y[inside]
                above = records["z"][top].astype(np.int16) >= land_z[top_y, top_x]
                color_index[top_y[above], top_x[above]] = (
                    0x4000 + records["tile_id"][top[above]].astype(np.int64)
                )

        color_index[color_index >= len(lut)] = 0
        return Image.fromarray(lut[color_index])

    def render_heightmap(self) -> Image.Image:
        """Render land altitude as greyscale: z -128 maps to 0, z 127 to 255."""
        _ids, land_z = self.land_arrays()
        return Image.fromarray(
            (land_z.astype(np.int16) + 128).astype(np.uint8)
        )
