"""Open generated image previews through the local viewer or browser."""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path


def open_preview(path: Path) -> bool:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # nosec B606
            return True
        return webbrowser.open(path.resolve().as_uri())
    except (OSError, webbrowser.Error):
        return False
