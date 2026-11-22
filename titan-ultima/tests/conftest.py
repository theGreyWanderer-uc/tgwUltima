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
# No test may ask PyPI for the latest release; tests of the check unset this.
os.environ["TITAN_NO_UPDATE_CHECK"] = "1"

import typer.rich_utils  # noqa: E402  (must follow the env pinning above)

typer.rich_utils.FORCE_TERMINAL = False

import pytest  # noqa: E402

from titan import _config  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_cli_config_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep loaded CLI settings from leaking between tests that invoke root commands."""
    monkeypatch.setattr(_config, "_config", {})
    monkeypatch.setattr(_config, "explicit_config_path", None)


@pytest.fixture(autouse=True)
def isolate_store_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reads this machine's launcher files or registry, and every test
    sees the same fixed drives (C-G). ``test_stores.py`` feeds the readers its
    own files and registry values."""
    from titan import _stores

    _stores.refresh()
    for reader in ("steam_roots", "heroic_config_dirs", "lutris_databases"):
        monkeypatch.setattr(_stores, reader, lambda: [])
    monkeypatch.setattr(_stores, "_registry_subkeys", lambda path: [])
    monkeypatch.setattr(_stores, "_registry_values", lambda path: [])
    monkeypatch.setattr(_stores, "drives", lambda: list("CDEFG"))
