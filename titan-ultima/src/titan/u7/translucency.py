"""
Ultima 7 translucency compositing.

Joins :class:`~titan.u7.shapeinfo.U7Xforms` (``XFORM.TBL``) and
:class:`~titan.u7.shapeinfo.U7Blends` (``BLENDS.DAT``/Exult-bundle/
hardcoded fallback) -- previously two independent, unlinked readers -- into
one class that reproduces Exult's actual translucent-pixel compositing:
mapping the existing *destination* palette index through a real 256-byte
xform table, not merely replacing it with a fixed preview colour.

Sourced from Exult (``D:/_Repos/exult``):

* ``shapeid.cc:290-370`` -- loading ``xforms``/``blends`` and computing
  ``xfstart = 0xFF - nblends`` (first translucent palette index).
* ``shapeid.cc:328-339`` -- when real ``XFORM.TBL`` records exist (both
  Black Gate and Serpent Isle ship one), they are loaded in
  **file-order-reversed** fashion: file record ``i`` becomes
  ``xforms[nxforms - 1 - i]``.  This module reproduces that reversal in
  :meth:`U7Translucency.table_by_slot` -- getting it backwards would
  silently pair pixels with the wrong remap table.
* ``shapes/vgafile.cc:540-556`` (``Shape_frame::paint_rle_translucent``)
  -- the actual per-pixel operation: ``xforms[pix - xfstart][dest_pixel]``.
* ``shapeid.cc:625-626`` -- ``PT_xForm`` palette transforms reuse this
  same ``xforms[]`` array directly by slot number (see
  :mod:`titan.u7.palette_transform`).
"""

from __future__ import annotations

__all__ = ["U7Translucency"]

from typing import Optional, Tuple

from titan.u7.shapeinfo import U7Blends, U7BlendRecord, U7Xforms


class U7Translucency:
    """Real (indexed) and approximate (RGBA preview) translucency
    compositing for a single game's static data."""

    def __init__(self, xforms: U7Xforms, blends: U7Blends) -> None:
        self.xforms = xforms
        self.blends = blends
        self._blend_by_index = {b.translucent_palette_index: b for b in blends.records}

    @classmethod
    def from_dir(
        cls,
        static_dir: str,
        game: str = "bg",
        exult_flx_path: Optional[str] = None,
    ) -> "U7Translucency":
        xforms = U7Xforms.from_dir(static_dir)
        blends = U7Blends.from_dir(static_dir, game=game, exult_flx_path=exult_flx_path)
        return cls(xforms, blends)

    @property
    def xfstart(self) -> int:
        """First translucent palette index (Exult: ``0xFF - nblends``)."""
        n = len(self.blends.records)
        return 0xFF - n if n else 0xFF

    @property
    def num_slots(self) -> int:
        return len(self.blends.records)

    # ------------------------------------------------------------------
    # Real (indexed) compositing
    # ------------------------------------------------------------------

    def table_by_slot(self, slot: int) -> Optional[bytes]:
        """Return the 256-byte xform remap table at raw 0-based *slot*
        (Exult's ``xforms[slot]``), applying the file-order reversal
        documented in ``shapeid.cc:328-339``: file record ``i`` maps to
        slot ``nxforms - 1 - i``.  Returns an identity table for any slot
        within range but beyond how many records ``XFORM.TBL`` actually
        provided (Exult's ``ds.good() == False`` fallback), or ``None``
        if *slot* is outside ``[0, num_slots)`` entirely.
        """
        n = self.num_slots
        if slot < 0 or slot >= n:
            return None
        file_index = n - 1 - slot
        tables = self.xforms.tables
        if file_index < len(tables):
            return tables[file_index]
        return bytes(range(256))

    def remap_table_for_index(self, pixel_index: int) -> Optional[bytes]:
        """Return the real xform table for translucent palette
        *pixel_index* (in ``[xfstart, 0xFE]``), or ``None`` if
        *pixel_index* is not a translucent index for this game's data."""
        return self.table_by_slot(pixel_index - self.xfstart)

    def composite_index(self, dest_index: int, translucent_index: int) -> int:
        """The actual Exult operation (``vgafile.cc:540-556``): map the
        existing *destination* palette index through *translucent_index*'s
        real xform table.  Falls back to ``dest_index`` unchanged if
        *translucent_index* isn't a known translucent slot."""
        table = self.remap_table_for_index(translucent_index)
        return dest_index if table is None else table[dest_index]

    # ------------------------------------------------------------------
    # Approximate RGBA preview
    # ------------------------------------------------------------------

    def blend_for_index(self, pixel_index: int) -> Optional[U7BlendRecord]:
        """The flat blend colour for a translucent palette index, as
        used for the RGBA preview path -- not the real per-destination-
        pixel operation (see :meth:`composite_index` for that)."""
        return self._blend_by_index.get(pixel_index)

    def composite_rgba_preview(
        self, translucent_index: int
    ) -> Optional[Tuple[int, int, int, int]]:
        """Approximate ``(r, g, b, alpha)`` preview colour for a
        translucent pixel: the raw ``BLENDS.DAT`` bytes, used directly as
        straight-alpha RGBA -- matching Exult's own ``translucency_argb``
        table (``shapeid.cc:350-368``, "the ARGB translucency table used
        by overlay layers... so a layer can reproduce it with real
        texture alpha"). Explicitly an approximation of the real indexed
        compositing in :meth:`composite_index`, not the exact operation.

        Note: this is *not* the same scaling Exult uses when it builds
        the indexed remap table via ``create_trans_table`` (``blends[i]
        / 4``, ``shapeid.cc:343-344``) -- that division only exists
        because ``create_trans_table`` expects 6-bit VGA-range input for
        the palette's native colour space; the ARGB overlay path (this
        one) uses the full undivided 0-255 bytes.
        """
        blend = self.blend_for_index(translucent_index)
        if blend is None:
            return None
        return (blend.r, blend.g, blend.b, blend.alpha)
