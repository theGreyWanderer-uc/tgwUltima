"""Open generated image previews through the local viewer or browser."""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path


def open_preview(path: Path) -> bool:
    """Open artwork and restore/foreground its Windows viewer on every request."""
    try:
        if sys.platform == "win32":
            from titan._windows_preview import foreground_preview_window

            path = path.resolve()
            os.startfile(str(path), show_cmd=9)  # nosec B606
            try:
                focused = foreground_preview_window(path)
            except (OSError, AttributeError):
                focused = False
            if not focused:
                print(
                    "  Preview opened, but Windows did not confirm viewer focus; "
                    f"select its taskbar window or open {path} manually."
                )
            return True
        return webbrowser.open(path.resolve().as_uri())
    except (OSError, webbrowser.Error):
        return False
