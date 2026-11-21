"""Tell a front end which files a command wrote, without it scanning folders.

A front end sets ``TITAN_RESULTS_FILE`` to a path before running a command.
When the command finishes (successfully or not), titan writes a JSON document
there::

    {"outputs": ["C:/.../palette.png", "C:/.../exports/map-browse"],
     "exit_code": 0}

``outputs`` lists the files and folders the command reported through
:func:`record_output`, in the order written, each once. Commands adopt this
one by one; an empty list means the command didn't report (or wrote nothing),
so fall back to the output parameter. Without the variable nothing is written.
"""

from __future__ import annotations

__all__ = ["RESULTS_ENV", "record_output", "recorded_outputs", "write_results"]

import json
import os
from pathlib import Path

RESULTS_ENV = "TITAN_RESULTS_FILE"

_outputs: list[str] = []


def record_output(path: str | os.PathLike[str]) -> None:
    """Note that this run wrote *path* (a file, or a folder of results)."""
    resolved = Path(path).expanduser().absolute().as_posix()
    if resolved not in _outputs:
        _outputs.append(resolved)


def recorded_outputs() -> list[str]:
    """The paths recorded so far in this process."""
    return list(_outputs)


def write_results(exit_code: int) -> None:
    """Write the results document if ``TITAN_RESULTS_FILE`` is set; then reset."""
    target = os.getenv(RESULTS_ENV)
    outputs = recorded_outputs()
    _outputs.clear()
    if not target:
        return
    document = {"outputs": outputs, "exit_code": exit_code}
    path = Path(target).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
