"""Titan package version (single source of truth), and a PyPI update check.

The check never runs on import or for ordinary commands; only when something
asks (``titan --version``, a front end). It sends nothing about the user.
"""

from __future__ import annotations

__all__ = [
    "NO_UPDATE_CHECK_ENV",
    "PYPI_URL",
    "TITAN_VERSION",
    "__version__",
    "is_dev_build",
    "is_newer",
    "latest_release",
]

__version__ = "0.8.0"
TITAN_VERSION = __version__

PYPI_URL = "https://pypi.org/pypi/titan-ultima/json"
NO_UPDATE_CHECK_ENV = "TITAN_NO_UPDATE_CHECK"
"""Set to ``1`` (or ``true``/``yes``) to turn the update check off."""

_CACHE_NAME = "latest-release.json"
_RETRY_AFTER_FAILURE = 3600.0
"""Seconds before asking PyPI again after a failed check, so offline runs stay fast."""


def _check_disabled() -> bool:
    import os

    return os.getenv(NO_UPDATE_CHECK_ENV, "").strip().lower() in {"1", "true", "yes"}


def _cache_file():
    from titan._config import cache_dir

    return cache_dir() / _CACHE_NAME


def _read_cache() -> dict:
    import json

    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(data: dict) -> None:
    import json

    try:
        path = _cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _fetch_latest(timeout: float) -> str | None:
    import json
    import urllib.request

    request = urllib.request.Request(
        PYPI_URL,
        headers={"Accept": "application/json", "User-Agent": "titan-ultima"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        version = json.load(response)["info"]["version"]
    return version if isinstance(version, str) and version else None


def latest_release(*, timeout: float = 3.0, max_age: float = 86400) -> str | None:
    """Newest titan-ultima version on PyPI, or ``None`` if unknown (offline, disabled).

    The answer is cached in :func:`titan._config.cache_dir` for *max_age*
    seconds. When PyPI can't be reached, the last known answer is returned and
    PyPI isn't asked again for an hour. Never raises.
    """
    import time

    if _check_disabled():
        return None
    try:
        now = time.time()
        cached = _read_cache()
        known = (
            cached.get("version") if isinstance(cached.get("version"), str) else None
        )
        checked = cached.get("checked")
        if known and isinstance(checked, (int, float)) and 0 <= now - checked < max_age:
            return known
        failed = cached.get("failed")
        if (
            isinstance(failed, (int, float))
            and 0 <= now - failed < _RETRY_AFTER_FAILURE
        ):
            return known
        try:
            latest = _fetch_latest(timeout)
        except Exception:  # offline, timeout, HTTP error, bad JSON: all "unknown"
            latest = None
        if latest is None:
            _write_cache({**cached, "failed": now})
            return known
        _write_cache({"version": latest, "checked": now})
        return latest
    except Exception:
        return None


def _release_key(version: str) -> tuple[int, ...] | None:
    parts = version.strip().lstrip("v").split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None  # a pre-release or local version: don't compare
    key = [int(part) for part in parts]
    while len(key) > 1 and key[-1] == 0:
        key.pop()
    return tuple(key)


def is_newer(latest: str | None, current: str = __version__) -> bool:
    """Whether *latest* is a newer final release than *current*.

    Only plain ``X.Y.Z`` versions are compared; anything else gives ``False``.
    """
    if not latest:
        return False
    new, old = _release_key(latest), _release_key(current)
    return new is not None and old is not None and new > old


def is_dev_build() -> bool:
    """Running from an editable/source checkout rather than an installed wheel."""
    import json
    from importlib import metadata

    try:
        dist = metadata.distribution("titan-ultima")
    except metadata.PackageNotFoundError:
        return True  # imported straight from a source tree
    try:
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
    except ValueError:
        return False
    return bool(direct.get("dir_info", {}).get("editable"))
