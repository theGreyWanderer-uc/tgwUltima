"""Suite-wide test environment normalisation.

Typer forces Rich's terminal mode when ``GITHUB_ACTIONS``, ``FORCE_COLOR`` or
``PY_COLORS`` is set, so ``--help`` output under CI is full of ANSI escapes
that split option names (``-`` + ``-shape``) and break plain substring checks.
Pin help rendering to plain text so local and CI runs see identical output.
"""

from __future__ import annotations

import os

os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"
os.environ["NO_COLOR"] = "1"
os.environ.pop("FORCE_COLOR", None)
os.environ.pop("PY_COLORS", None)

import typer.rich_utils  # noqa: E402  (must follow the env pinning above)

typer.rich_utils.FORCE_TERMINAL = False
