"""Small interfaces the games' classes share, for cross-game code.

Each game keeps its own implementation; these only name the common surface, so
a front end or tool can treat any game's object the same way. They are
``runtime_checkable`` (``isinstance`` checks the methods exist, not their
signatures); ``tests/test_protocols.py`` checks every implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Sequence, runtime_checkable

if TYPE_CHECKING:
    from PIL import Image

__all__ = ["IndexedArchive", "Palette"]


@runtime_checkable
class Palette(Protocol):
    """A 256-colour palette: ``U6Palette`` (also MD's), ``U7Palette``,
    ``U8Palette``, ``U9Palette``, ``UW1Palette``, ``UW2Palette``.

    Loading stays per game (``from_file`` takes an index for UW1/UW2 and a
    slot for U7).
    """

    colors: Sequence[tuple[int, int, int]]
    """256 ``(r, g, b)`` colours, 8 bits per channel."""

    def to_flat_rgb(self) -> bytes:
        """768 bytes ``r0 g0 b0 r1 ...``, as Pillow's ``putpalette`` takes."""
        ...

    def to_pil_image(self, swatch_size: int = 16) -> Image.Image:
        """A 16x16 grid of *swatch_size*-pixel colour squares."""
        ...


@runtime_checkable
class IndexedArchive(Protocol):
    """Numbered slots of bytes, read-only: the root ``FlexArchive`` (U8 and
    U7 Flex), ``U7FlexArchive``, ``U9FlxArchive``, ``U6Library`` and UW2's
    ``ArkArchive``.

    Writing stays per format (the U7 and U8 Flex headers differ byte for byte);
    UO's hashed ``UOPArchive`` and image collections are not indexed archives.
    """

    @property
    def entry_count(self) -> int:
        """Number of slots, used or not."""
        ...

    def read(self, index: int) -> bytes | None:
        """Slot *index*'s bytes as the game uses them (decompressed where the
        format compresses, as U6 LIB and UW2 ARK do), or ``None`` for an empty
        slot. ``IndexError`` outside ``0..entry_count - 1``."""
        ...
