"""Show titan's progress and warnings on the terminal when titan runs as a CLI.

Library code never prints: it logs to ``logging.getLogger(__name__)``, under
the ``titan`` logger. A front end attaches its own handler (or reads
``caplog``-style records) to show them however it likes. The CLI and the
terminal wizards call :func:`install_cli_logging`, which prints:

* INFO as plain lines on stdout, exactly as the message reads;
* WARNING as ``Warning: ...`` and ERROR as ``ERROR: ...`` on stderr.

Streams are looked up when each message is written, so redirected or
captured output (``CliRunner``, pytest) receives it.
"""

from __future__ import annotations

__all__ = ["install_cli_logging"]

import logging
import sys

_LOGGER = "titan"


class _TerminalHandler(logging.Handler):
    """Write titan's log records the way the CLI used to print them."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.levelno >= logging.ERROR:
                stream, text = sys.stderr, f"ERROR: {message}"
            elif record.levelno >= logging.WARNING:
                stream, text = sys.stderr, f"Warning: {message}"
            else:
                stream, text = sys.stdout, message
            stream.write(text + "\n")
            stream.flush()
        except Exception:  # pragma: no cover - logging must never raise
            self.handleError(record)


def install_cli_logging(level: int = logging.INFO) -> None:
    """Print ``titan.*`` log records on the terminal (once per process)."""
    logger = logging.getLogger(_LOGGER)
    if not any(isinstance(handler, _TerminalHandler) for handler in logger.handlers):
        logger.addHandler(_TerminalHandler())
    if logger.level == logging.NOTSET or logger.level > level:
        logger.setLevel(level)
