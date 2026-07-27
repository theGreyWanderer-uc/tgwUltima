"""
Best-effort human-readable labels for ``static/sappear.flx`` model IDs.

There is no file anywhere in this game (or in the reference tools this
project ported from) that names a ``sappear.flx`` model directly. The
only real path is indirect, through two other files this project
already reads:

    TYPES.DAT (titan.u9.types_dat)      : type_id -> default_model_id
    TYPENAME.FLX (titan.u9.typename)    : type_id -> display name (only ~25% of type_ids have one)

Joining them (real data, this project's test copy of the game): 2,029
type IDs have both a nonzero ``default_model_id`` and a display name,
resolving to 1,706 distinct model IDs -- **about 45% of the ~3,764 used
models** get at least one name this way; the rest have none and simply
keep their bare numeric ID.

This mapping is also **not unique**: ``TYPENAME.FLX`` was built for
NPC/unique-object tooltips, not as a 1:1 model catalog, so several
distinct named types commonly share one generic body mesh. Real
example: model 3448's ``default_model_id`` is claimed by type IDs named
"Valkadesh", "Wislem", "Winged Gargoyle", "Guard", "Voresh", and
"Statue" all at once -- :func:`names_for_model` returns every one of
them; :func:`label_for_model` joins them all into one slug rather than
arbitrarily picking a "winner", since the model ID itself (always
included alongside the label by callers) is the actual unique key.

Example::

    from titan.u9.types_dat import U9TypesDat
    from titan.u9.typename import U9TypeNames
    from titan.u9.model_naming import label_for_model

    types = U9TypesDat.from_file("static/TYPES.DAT")
    names = U9TypeNames.from_file("static/TYPENAME.FLX")
    label_for_model(1805, types, names)  # "lord-british"
    label_for_model(9999, types, names)  # None -- no named type claims this model
"""

from __future__ import annotations

__all__ = ["names_for_model", "label_for_model", "slugify"]

import re

from titan.u9.typename import U9TypeNames
from titan.u9.types_dat import U9TypesDat


def names_for_model(model_id: int, types: U9TypesDat, typenames: U9TypeNames) -> list[str]:
    """Every distinct display name claimed by a type whose ``default_model_id`` is ``model_id``."""
    seen: dict[str, None] = {}
    for type_id in types.type_ids_for_model(model_id):
        name = typenames.name_for(type_id)
        if name:
            seen.setdefault(name, None)
    return list(seen)


def slugify(text: str) -> str:
    """Lowercase, filesystem-safe slug: non-alphanumeric runs become a single hyphen."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug or "unnamed"


def label_for_model(model_id: int, types: U9TypesDat, typenames: U9TypeNames) -> str | None:
    """A single filesystem-safe slug joining every name claimed for ``model_id``, or ``None`` if none."""
    names = names_for_model(model_id, types, typenames)
    if not names:
        return None
    return "-".join(slugify(name) for name in names)
