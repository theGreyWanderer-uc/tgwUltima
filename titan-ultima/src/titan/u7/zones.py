"""U7 zone profile loading for map highlight overlays."""

from __future__ import annotations

import json
from pathlib import Path


__all__ = [
    "U7ZoneProfileError",
    "available_zone_profiles",
    "build_zone_highlight_rects",
]


class U7ZoneProfileError(ValueError):
    """Raised when zone profile data or selection is invalid."""


_PROFILE_FILES: dict[str, str] = {
    "si_zones": "si_zones.json",
    "bg_zones": "bg_zones.json",
}


def available_zone_profiles() -> list[str]:
    """Return supported U7 zone profile names."""
    return sorted(_PROFILE_FILES.keys())


def _profiles_dir() -> Path:
    return Path(__file__).with_name("zone_profiles")


def _parse_hex_rgba(color: str) -> tuple[int, int, int, int]:
    txt = color.strip()
    if txt.startswith("#"):
        txt = txt[1:]
    if len(txt) not in (6, 8):
        raise U7ZoneProfileError(
            f"Invalid color '{color}' in zone profile; expected #RRGGBB or #RRGGBBAA.")
    try:
        r = int(txt[0:2], 16)
        g = int(txt[2:4], 16)
        b = int(txt[4:6], 16)
        a = int(txt[6:8], 16) if len(txt) == 8 else 255
    except ValueError as exc:
        raise U7ZoneProfileError(
            f"Invalid color '{color}' in zone profile.") from exc
    return (r, g, b, a)


def _load_profile(profile: str) -> dict:
    filename = _PROFILE_FILES.get(profile)
    if not filename:
        raise U7ZoneProfileError(
            f"Unknown zone profile '{profile}'. "
            f"Available: {', '.join(available_zone_profiles())}")

    path = _profiles_dir() / filename
    if not path.is_file():
        raise U7ZoneProfileError(f"Zone profile file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise U7ZoneProfileError(
            f"Zone profile '{profile}' is invalid JSON: {exc}") from exc

    zones = data.get("zones")
    if not isinstance(zones, list):
        raise U7ZoneProfileError(
            f"Zone profile '{profile}' is missing a valid 'zones' list.")

    return data


def _normalize_zone_ids(zone_ids: list[str] | None) -> set[str] | None:
    if not zone_ids:
        return None
    out = {str(z).strip().lower() for z in zone_ids if str(z).strip()}
    return out or None


def _available_ids(zones: list[dict]) -> set[str]:
    ids = {str(z.get("id", "")).strip().lower() for z in zones}
    ids.discard("")
    return ids


def _validate_selected_ids(
    profile: str,
    selected_ids: set[str] | None,
    available_ids: set[str],
) -> None:
    if not selected_ids:
        return
    missing = sorted(selected_ids - available_ids)
    if not missing:
        return
    avail = ", ".join(sorted(available_ids, key=lambda v: (len(v), v)))
    raise U7ZoneProfileError(
        f"Unknown zone ID(s) for profile '{profile}': {', '.join(missing)}. "
        f"Available IDs: {avail}")


def _zone_is_selected(
    zone: dict,
    *,
    include_all: bool,
    selected_ids: set[str] | None,
) -> bool:
    zid = str(zone.get("id", "")).strip().lower()
    if not zid:
        return False
    if include_all:
        return True
    return bool(selected_ids and zid in selected_ids)


def _rect_tuple(profile: str, zone: dict, rect: dict) -> tuple[int, int, int, int, tuple[int, int, int, int], str]:
    try:
        tx0 = int(rect["tx0"])
        ty0 = int(rect["ty0"])
        tx1 = int(rect["tx1"])
        ty1 = int(rect["ty1"])
        color = _parse_hex_rgba(str(rect.get("color", "#FFFFFF")))
        label = str(rect.get("label") or f"ID{zone.get('id')} {zone.get('name', '')}").strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise U7ZoneProfileError(
            f"Invalid rectangle entry in zone '{zone.get('id')}' "
            f"for profile '{profile}'.") from exc
    return (tx0, ty0, tx1, ty1, color, label)


def build_zone_highlight_rects(
    profile: str,
    *,
    zone_ids: list[str] | None = None,
    include_all: bool = False,
) -> list[tuple[int, int, int, int, tuple[int, int, int, int], str]]:
    """Build highlight rectangle tuples from a named zone profile.

    Returns a list of tuples compatible with the existing U7 CLI highlight
    pipeline: ``(tx0, ty0, tx1, ty1, rgba, label)``.
    """
    if include_all and zone_ids:
        raise U7ZoneProfileError(
            "Use either --all-zones or --zone-id (not both).")

    data = _load_profile(profile)
    zones = data["zones"]

    selected_ids = _normalize_zone_ids(zone_ids)

    if selected_ids is None and not include_all:
        include_all = True

    available_ids = _available_ids(zones)
    _validate_selected_ids(profile, selected_ids, available_ids)

    out: list[tuple[int, int, int, int, tuple[int, int, int, int], str]] = []

    for zone in zones:
        if not _zone_is_selected(zone, include_all=include_all, selected_ids=selected_ids):
            continue

        rects = zone.get("rects", [])
        if not isinstance(rects, list):
            raise U7ZoneProfileError(
                f"Zone '{zone.get('id')}' in profile '{profile}' has invalid 'rects'.")

        for rect in rects:
            out.append(_rect_tuple(profile, zone, rect))

    return out
