"""Write setup configuration while retaining existing settings and a backup."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import tomli_w

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


def _merge_missing_config(existing: dict[str, Any], generated: dict[str, Any]) -> None:
    """Add missing setup entries without replacing custom settings."""
    for key, value in generated.items():
        if key not in existing:
            existing[key] = value
        elif isinstance(existing[key], dict) and isinstance(value, dict):
            _merge_missing_config(existing[key], value)


def write_setup_config(path: Path, generated_text: str) -> Optional[Path]:
    """Add missing config values; back up the original before rewriting TOML."""
    generated = tomllib.loads(generated_text)
    backup = None
    if path.exists():
        original = path.read_bytes()
        existing = tomllib.loads(original.decode("utf-8"))
        # Legacy U8 settings remain authoritative until explicitly migrated.
        if "u8" not in existing and ("game" in existing or "paths" in existing):
            generated.pop("u8", None)
        _merge_missing_config(existing, generated)
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
