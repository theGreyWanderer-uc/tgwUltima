"""Bundled place data: the names and outlines the finders cannot work out.

The game files say where roofs, floors, doors and signs are, but not what
most buildings are called, which dungeon is which, or where a town ends.
That comes from the printed town maps shipped with the game and from a
reviewer going over every find. The full working copy (with review notes and
rejected guesses) is kept outside the package; ``compact_place_data`` cuts it
down to what the finders read, and that is what ships in ``data/``.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
FORMAT = "titan-u7-place-data"
VERSION = 1

# Fields copied for each place and region, in this order, when set.
PLACE_FIELDS = ("id", "name", "type", "town", "number", "keeper", "anchor", "rects")
REGION_FIELDS = ("id", "name", "kind", "anchor", "rects")


class PlaceDataError(ValueError):
    """Raised when bundled place data is missing or malformed."""


def available_games() -> list[str]:
    """Games with bundled place data ("bg", ...)."""
    return sorted(p.name.split("_", 1)[0] for p in DATA_DIR.glob("*_places.json"))


def place_data_path(game: str) -> Path:
    return DATA_DIR / f"{game}_places.json"


def load_place_data(game: str) -> dict:
    """The bundled place data for ``game``."""
    path = place_data_path(game)
    if not path.is_file():
        raise PlaceDataError(
            f"No place data is bundled for {game!r} yet "
            f"(available: {', '.join(available_games()) or 'none'})."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT or not isinstance(data.get("places"), list):
        raise PlaceDataError(f"{path} is not {FORMAT} data.")
    if data.get("version", 0) > VERSION:
        raise PlaceDataError(
            f"{path} is version {data['version']}; this titan reads up to {VERSION}."
        )
    data.setdefault("regions", [])
    return data


def _pick(entry: dict, fields: tuple[str, ...]) -> dict:
    out = {k: entry[k] for k in fields if entry.get(k) not in (None, [], "")}
    if entry.get("source") == "review":
        out["source"] = "review"
    return out


def compact_place_data(profile: dict) -> dict:
    """Cut a working place profile down to the shipped place data.

    Keeps only entries that are on the map (an anchor or rects) and not
    dropped, and only the fields the finders and the export read. A reviewed
    entry keeps ``"source": "review"``, so a printed-map name still wins over
    it on the same building.
    """
    places = [
        _pick(p, PLACE_FIELDS)
        for p in profile.get("places", [])
        if p.get("anchor") and not p.get("dropped")
    ]
    regions = [
        _pick(r, REGION_FIELDS)
        for r in profile.get("regions", [])
        if (r.get("anchor") or r.get("rects")) and not r.get("dropped")
    ]
    return {
        "format": FORMAT,
        "version": VERSION,
        "game": profile.get("game"),
        "map": profile.get("map", 0),
        "description": (
            "Place names and outlines for titan u7 places-export: printed town "
            "map entries pinned to the world, reviewed names, areas, and town "
            "outlines. Coordinates are inclusive world tiles; rects are "
            "[x0, y0, x1, y1]. Generated from the working place profile."
        ),
        "places": places,
        "regions": regions,
    }


def dump_place_data(data: dict) -> str:
    """JSON text with one place or region per line, so diffs stay readable."""
    lines = ["{"]
    for key, value in data.items():
        if key in ("places", "regions"):
            rows = ",\n".join(
                "    " + json.dumps(row, ensure_ascii=False, separators=(", ", ": "))
                for row in value
            )
            lines.append(f'  "{key}": [\n{rows}\n  ],' if value else f'  "{key}": [],')
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)},")
    lines[-1] = lines[-1].rstrip(",")
    return "\n".join(lines) + "\n}\n"
