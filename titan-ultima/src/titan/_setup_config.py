"""Write setup configuration while retaining existing settings and a backup."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import tomli_w

from titan._config import migrate_legacy_u8

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


def section_lines(config: dict[str, Any]) -> list[str]:
    """Render ``{section: {...}}`` (see :func:`titan._meta.install_config`) as
    TOML lines, preceded by a blank line, for setup to append."""
    return ["", *tomli_w.dumps(config).splitlines()]


def _merge_missing_config(existing: dict[str, Any], generated: dict[str, Any]) -> None:
    """Add missing setup entries without replacing custom settings."""
    for key, value in generated.items():
        if key not in existing:
            existing[key] = value
        elif isinstance(existing[key], dict) and isinstance(value, dict):
            _merge_missing_config(existing[key], value)


def _apply_updates(existing: dict[str, Any], updates: dict[str, Any]) -> None:
    """Apply only the corrections explicitly included in setup's confirmation."""
    for key, value in updates.items():
        if isinstance(value, dict):
            _apply_updates(existing.setdefault(key, {}), value)
        else:
            existing[key] = value


def write_setup_config(
    path: Path,
    generated_text: str,
    *,
    updates: Optional[dict[str, Any]] = None,
    cleanup: Optional[Callable[[dict[str, Any]], object]] = None,
) -> Optional[Path]:
    """Add missing config values; back up the original before rewriting TOML.

    *cleanup* runs on the merged existing config, to drop values only an
    older setup wrote (never ones a user set on purpose).
    """
    generated = tomllib.loads(generated_text)
    backup = None
    if path.exists():
        original = path.read_bytes()
        existing = tomllib.loads(original.decode("utf-8"))
        # titan's original U8-only [game]/[paths] move under [u8] (the .bak
        # keeps the old file). They are the user's U8 settings: detected U8
        # defaults are not added to them (an empty language, say, would move
        # STATIC from <base>/ENGLISH/STATIC to <base>).
        had_u8 = "u8" in existing
        if migrate_legacy_u8(existing) and not had_u8:
            generated.pop("u8", None)
        _merge_missing_config(existing, generated)
        _apply_updates(existing, updates or {})
        if cleanup is not None:
            cleanup(existing)
        text = tomli_w.dumps(existing)
        backup = path.with_name(path.name + ".bak")
        suffix = 1
        while backup.exists():
            backup = path.with_name(f"{path.name}.bak.{suffix}")
            suffix += 1
        backup.write_bytes(original)
    else:
        text = generated_text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return backup
