"""Errors titan raises on purpose, grouped by what the user can do about them.

Every error titan raises deliberately derives from :class:`TitanError`. The
three branches tell a user (or a front end) what kind of problem it is:

* :class:`ConfigError`: titan isn't set up for this. No install is
  configured, a configured or given path doesn't exist, or ``titan.toml`` is
  invalid. The fix is in setup or the command's path options.
* :class:`InvalidDataError`: an input file isn't what titan expected (wrong
  format, truncated, damaged). Also a :class:`ValueError`, so code that
  catches ``ValueError`` keeps working.
* :class:`UnsupportedError`: titan can't do this here: a format variant it
  doesn't handle, or an optional library that isn't installed.

Anything else that escapes a command is a bug in titan.

The CLI prints a :class:`TitanError` as one ``ERROR:`` line and exits with
its :attr:`~TitanError.exit_code`; see :data:`EXIT_CODES`. This module
imports nothing else from titan, so any module can raise these.
"""

from __future__ import annotations

__all__ = [
    "EXIT_CODES",
    "ConfigError",
    "ConfigFileError",
    "InstallNotFoundError",
    "InvalidDataError",
    "TitanError",
    "UnsupportedError",
    "exit_code",
]


class TitanError(Exception):
    """A problem titan reports to the user rather than a bug."""

    exit_code = 1


class ConfigError(TitanError):
    """titan isn't set up for this: fix the config or pass the path."""

    exit_code = 78  # EX_CONFIG


class InstallNotFoundError(ConfigError, FileNotFoundError):
    """No install is configured, or the configured or given folder is missing.

    Also a :class:`FileNotFoundError`, which several commands already catch.
    """


class ConfigFileError(ConfigError, ValueError):
    """``titan.toml`` can't be read (invalid TOML or a bad value)."""


class InvalidDataError(TitanError, ValueError):
    """An input file isn't in the format titan expected, or is damaged."""

    exit_code = 65  # EX_DATAERR


class UnsupportedError(TitanError):
    """titan can't do this here: unsupported variant or missing optional library."""

    exit_code = 69  # EX_UNAVAILABLE


EXIT_CODES = {
    "ok": 0,
    "error": 1,  # a reported problem (including errors a command handled itself)
    "usage": 2,  # bad command-line arguments
    "invalid-data": InvalidDataError.exit_code,
    "file-not-found": 66,  # EX_NOINPUT: a file that isn't there
    "unsupported": UnsupportedError.exit_code,
    "internal": 70,  # EX_SOFTWARE: a bug in titan (a traceback is printed)
    "io": 74,  # EX_IOERR: the system couldn't read or write a file
    "config": ConfigError.exit_code,
}
"""What each titan exit status means. Front ends can map a status back to its key."""


def exit_code(error: BaseException) -> int:
    """The exit status for *error* (see :data:`EXIT_CODES`)."""
    if isinstance(error, TitanError):
        return error.exit_code
    if isinstance(error, FileNotFoundError):
        return EXIT_CODES["file-not-found"]
    if isinstance(error, OSError):
        return EXIT_CODES["io"]
    return EXIT_CODES["error"]
