"""
Ultima 9 2D UI icon discovery.

Real discovery: the texture archives ``bitmap16.flx``/``bitmapC.flx``/
``bitmapsh.flx`` -- already used by :mod:`titan.u9.mesh_export` for 3D
model surface textures -- also hold a large set of standalone 2D UI
icons mixed into that same index space, with no format-level flag
distinguishing them from material textures. Confirmed by exporting and
individually inspecting real entries (each verified one index at a
time, not by eyeballing a contact-sheet grid -- see the "known
limitation" note below for why that distinction matters here):
entries 568-641 are a set of colorful circular spell-rune sigils, and
scattered individual entries in the roughly 6900-7450 range are
clearly UI-style icon art too (e.g. 7047 a rune/seal pattern, 7050 an
apple, 7066 a book with a red cross, 7070 a parchment scroll) --
though that broad range is a mix of real icons and ordinary material
textures (faces, cloth, metal, wheat fields, ...), not a clean,
uniformly-icon cluster the way 568-641 is.

**The one reliable signal found**: every 3D model's material
``texture_id`` in ``sappear.flx`` is either a real surface material,
or a 2D-only UI icon that no material ever references at all.
:func:`used_texture_ids` computes the "claimed by a mesh" set by
parsing every model in ``sappear.flx``; :func:`icon_entry_indices`
returns a texture archive's used entries with that set subtracted --
the "unclaimed" 2D icon candidates. Real data: 5,044 distinct
texture_ids are claimed this way (matching the count already recorded
in ``mesh_export``'s own module docstring), leaving 1,553 of
``bitmapsh.flx``'s 6,597 used entries as icon candidates -- including
the full spell-rune cluster (568-641) confirmed by direct visual
inspection.

**Known limitation, confirmed not just theorized**: this is a "claimed
vs. unclaimed" split, not a true icon/material classifier -- an entry
that's unmistakably icon-style flat art can still be *excluded* here if
some low-poly world prop happens to reuse that same flat image as its
surface texture instead of a tileable material. Confirmed on real data:
texture 7047 (a decorative rune/seal-pattern icon, visually similar in
style to the 568-641 cluster) is used by model 2385 (an 8-triangle
prop, 2 materials) -- so :func:`icon_entry_indices` correctly excludes
it even though it reads as UI-style art. (An earlier pass at this
investigation misidentified *which* image several other texture_ids
pointed to, from a debug script that mislabeled cells with a search
range's start index instead of the actual rendered entry -- re-checked
each one here via direct single-entry export, one index at a time, to
avoid repeating that mistake. Moral: verify by exact index, never by
eyeballing a label next to a grid cell.) So :func:`icon_entry_indices`
is a solid, honest *subset* of the real icon art (verified matches the
568-641 spell-rune cluster exactly), not a provably exhaustive one.

Example::

    from titan.u9.flx_archive import U9FlxArchive
    from titan.u9.icon import icon_entry_indices

    sappear = U9FlxArchive.from_file("static/sappear.flx")
    textures = U9FlxArchive.from_file("static/bitmap16.flx")
    icon_ids = icon_entry_indices(sappear, textures)
"""

from __future__ import annotations

__all__ = ["used_texture_ids", "icon_entry_indices"]

from titan.u9.flx_archive import U9FlxArchive
from titan.u9.model import U9Model, U9ModelError


def _texture_ids_for_model(model: U9Model) -> set[int]:
    """Every non-invisible material's ``texture_id`` across all of a model's limbs/LODs."""
    ids: set[int] = set()
    for limb in model.limbs:
        for lod in limb.lods:
            if lod is None:
                continue
            ids.update(m.texture_id for m in lod.materials if not m.is_invisible)
    return ids


def used_texture_ids(sappear: U9FlxArchive) -> set[int]:
    """Every ``texture_id`` referenced by a non-invisible material in any parseable ``sappear.flx`` model."""
    ids: set[int] = set()
    for model_id in sappear.used_entry_indices():
        blob = sappear.read_entry(model_id)
        try:
            model = U9Model.parse(blob, model_id=model_id)
        except U9ModelError:
            continue
        ids.update(_texture_ids_for_model(model))
    return ids


def icon_entry_indices(sappear: U9FlxArchive, textures: U9FlxArchive) -> list[int]:
    """``textures`` entries not referenced by any 3D model material -- candidate 2D UI icons."""
    claimed = used_texture_ids(sappear)
    return sorted(i for i in textures.used_entry_indices() if i not in claimed)
