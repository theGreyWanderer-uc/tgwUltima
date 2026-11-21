"""Helpers and option types shared by the ``titan u6`` command modules."""

from __future__ import annotations

import os
import sys
from typing import Optional

from titan.errors import InstallNotFoundError


def _require_gamedir(gamedir: Optional[str]) -> str:
    """The ``--game-dir`` value; when omitted, the CLI fills it from the configured install (titan._input_fill)."""
    if not gamedir or not os.path.isdir(gamedir):
        raise InstallNotFoundError(
            "No U6 game directory found. Pass --game-dir, or set "
            '[u6.game] base = "..." in titan.toml.'
        )
    return gamedir


def _resolve_palette(gamedir: str, explicit: Optional[str]) -> str:
    path = explicit or os.path.join(gamedir, "U6PAL")
    if not os.path.isfile(path):
        print(f"ERROR: Palette not found: {path}", file=sys.stderr)
        raise SystemExit(1)
    return path
