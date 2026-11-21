"""Tell a front end which files a command wrote, without it scanning folders.

A front end sets ``TITAN_RESULTS_FILE`` to a path before running a command.
When the command finishes (successfully or not), titan writes a JSON document
there::

    {"outputs": ["C:/.../exports/map-browse", "C:/.../exports/map-browse/map.png"],
     "exit_code": 0}

``outputs`` lists the files and folders the run wrote, in the order found, each
once, and only those that exist when it ends. Every command whose ``@meta``
tags an ``output-file`` or ``output-dir`` parameter reports it automatically
(:func:`wrap_outputs`): the file, or the folder followed by the files written
into it during the run (at most :data:`MAX_LISTED_FILES`). A default output
folder chosen in a command's body comes from ``titan._config.export_output``,
which reports it too. Commands may also call :func:`record_output` for other
paths. Without the variable nothing is recorded or written.
"""

from __future__ import annotations

__all__ = [
    "MAX_LISTED_FILES",
    "RESULTS_ENV",
    "record_output",
    "record_output_folder",
    "recorded_outputs",
    "wrap_outputs",
    "write_results",
]

import functools
import json
import os
import time
from pathlib import Path
from typing import Any

RESULTS_ENV = "TITAN_RESULTS_FILE"
MAX_LISTED_FILES = 2000
"""Files listed per output folder; a larger export lists only the folder."""

_OUTPUT_KINDS = ("output-file", "output-dir")
_WRAPPED = "__titan_outputs_wrapped__"

_outputs: list[str] = []
_folders: list[tuple[str, float]] = []


def _absolute(path: str | os.PathLike[str]) -> str:
    return Path(path).expanduser().absolute().as_posix()


def record_output(path: str | os.PathLike[str]) -> None:
    """Note that this run wrote *path* (a file, or a folder of results); a no-op
    unless ``TITAN_RESULTS_FILE`` is set."""
    if not os.getenv(RESULTS_ENV):
        return
    resolved = _absolute(path)
    if resolved not in _outputs:
        _outputs.append(resolved)


def record_output_folder(path: str | os.PathLike[str], since: float) -> None:
    """Note an output folder (as :func:`record_output`); the files written into it
    after *since* (a ``time.time()``) are listed too when the results are written."""
    if not os.getenv(RESULTS_ENV):
        return
    record_output(path)
    _folders.append((_absolute(path), since))


def recorded_outputs() -> list[str]:
    """The paths recorded so far in this process."""
    return list(_outputs)


def _new_files(folder: Path, since: float) -> list[str]:
    found: list[str] = []
    stack = [folder]
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                stack.append(Path(entry.path))
            elif entry.stat().st_mtime >= since:
                found.append(Path(entry.path).as_posix())
                if len(found) > MAX_LISTED_FILES:
                    return []
    return sorted(found)


def write_results(exit_code: int) -> None:
    """Write the results document if ``TITAN_RESULTS_FILE`` is set; then reset."""
    target = os.getenv(RESULTS_ENV)
    folders = list(_folders)
    _folders.clear()
    if target:
        for folder, since in folders:
            if Path(folder).is_dir():
                for path in _new_files(Path(folder), since):
                    record_output(path)
    outputs = [path for path in recorded_outputs() if Path(path).exists()]
    _outputs.clear()
    if not target:
        return
    document = {"outputs": outputs, "exit_code": exit_code}
    path = Path(target).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def wrap_outputs(command: Any) -> Any:
    """Make *command* report its tagged output parameters (once)."""
    callback = getattr(command, "callback", None)
    info = getattr(callback, "__titan_meta__", None)
    if callback is None or info is None or getattr(callback, _WRAPPED, False):
        return command
    outputs = {
        name: kind for name, kind in info.params.items() if kind in _OUTPUT_KINDS
    }
    if not outputs:
        return command

    @functools.wraps(callback)
    def reporting(**kwargs: Any) -> Any:
        if not os.getenv(RESULTS_ENV):
            return callback(**kwargs)
        # Filesystem timestamps can trail the clock slightly.
        started = time.time() - 2
        try:
            return callback(**kwargs)
        finally:
            for name, kind in outputs.items():
                value = kwargs.get(name)
                if not value:
                    continue
                if kind == "output-dir" or Path(str(value)).is_dir():
                    record_output_folder(str(value), started)
                else:
                    record_output(str(value))

    setattr(reporting, _WRAPPED, True)
    command.callback = reporting
    return command
