"""Game-specific storage rules for the shared Ultima VI format readers."""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path

from titan.u6.lib import U6Library
from titan.u6.lzw import U6Lzw

__all__ = ["U6GameProfile", "U6_PROFILE"]


@dataclass(frozen=True)
class U6GameProfile:
    """Describe resource storage and static animation defaults for one U6-engine game."""

    game_id: str
    palette_filename: str
    compressed_resources: frozenset[str] = frozenset()
    library_resources: frozenset[str] = frozenset()
    inactive_animation_tiles: frozenset[int] = frozenset()
    hidden_marker_tiles: frozenset[int] = frozenset()

    def read_resource(self, directory: str | PathLike[str], filename: str) -> bytes:
        """Read a resource, removing its game's LZW or single-item library wrapper."""
        path = Path(directory) / filename
        data = path.read_bytes()
        if filename in self.library_resources:
            if len(data) < 8 or int.from_bytes(data[:4], "little") != len(data):
                raise ValueError(f"Invalid {self.game_id} resource size header: {path}")
            library = U6Library(data, has_size_header=True)
            if library.num_items != 1:
                raise ValueError(
                    f"Expected a single-item {self.game_id} resource: {path}"
                )
            result = library.get_item(0)
            if not result:
                raise ValueError(f"Empty {self.game_id} map resource: {path}")
            return result
        if filename in self.compressed_resources:
            return U6Lzw.decompress(data)
        return data


U6_PROFILE = U6GameProfile(
    game_id="u6",
    palette_filename="U6PAL",
    compressed_resources=frozenset(
        {"MASKTYPE.VGA", "MAPTILES.VGA", "LZOBJBLK", "LZDNGBLK", "LOOK.LZD"}
    ),
)
