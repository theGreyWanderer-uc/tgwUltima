"""Library modules don't print, prompt or import terminal UI toolkits.

Terminal code belongs in the CLI layer: ``cli.py``, ``cli/`` packages,
``*_cli.py`` and ``*_ui.py`` modules (plus the shared terminal helpers listed in
``TERMINAL_MODULES``). Library code logs through ``logging.getLogger(__name__)``
instead (see :mod:`titan._log`), so a front end can run it without a terminal.

``ALLOWED`` lists the library modules that still do terminal I/O, with how many
uses each has. It may only shrink: a new use fails, and so does an entry whose
module has become clean (delete it).
"""

from __future__ import annotations

import ast
from pathlib import Path

import titan

SRC = Path(titan.__file__).parent

TERMINAL_MODULES = {
    "__main__.py",
    "_cli_aliases.py",
    "_image_preview.py",
    "_inventory_browser.py",
    "_log.py",
    "_palette_browser_ui.py",
    "_setup_config.py",
    "_terminal_image.py",
    "_windows_preview.py",
    "_wizard_ui.py",
    "u7/target_picker.py",
    "u9/cli_paths.py",  # the U9 command parser (CLI layer despite its name)
    "_meta.py",  # imports Typer only to read the command tree for front ends
}
"""Shared terminal helpers and CLI-layer modules: talking to the terminal is their job."""

TERMINAL_IMPORTS = {"typer", "click", "questionary", "rich", "prompt_toolkit"}

# Library module -> terminal I/O uses still in it. Shrink this; never grow it.
ALLOWED: dict[str, int] = {
    # dialogue pipeline steps, also runnable as scripts that print progress
    "dialogue/pipeline/lint_json.py": 14,
    "dialogue/pipeline/build_data.py": 8,
    "dialogue/pipeline/extract_ast.py": 7,
    "dialogue/pipeline/extract_books.py": 7,
    "dialogue/pipeline/extract_library.py": 5,
    "dialogue/websrc/build_data.py": 5,
    "u7/shape_properties.py": 5,
    "u7/flex.py": 4,
    "flex.py": 3,
    "u7/shape_animation_flag.py": 3,  # choose_u7_shape_animation prompts
    "u8/state_io.py": 2,
    "u9/texture_export.py": 2,
    "u7/gamedat_source.py": 1,  # raises typer.BadParameter for --save
    "u7/shape_import.py": 1,
    "uw2/map_render.py": 1,
}


def _is_cli_layer(relative: str) -> bool:
    path = Path(relative)
    return (
        relative in TERMINAL_MODULES
        or path.name == "cli.py"
        or "cli" in path.parts[:-1]
        or path.stem.endswith(("_cli", "_ui"))
        or path.parts[0] == "third_party"
    )


def _uses(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            count += node.func.id in {"print", "input"}
        elif isinstance(node, ast.Import):
            count += sum(a.name.split(".")[0] in TERMINAL_IMPORTS for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            count += node.module.split(".")[0] in TERMINAL_IMPORTS
            count += node.module == "titan" and any(
                a.name == "_wizard_ui" for a in node.names
            )
            count += node.module == "titan._wizard_ui"
    return count


def terminal_uses() -> dict[str, int]:
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        if "__pycache__" in relative or _is_cli_layer(relative):
            continue
        uses = _uses(ast.parse(path.read_text(encoding="utf-8")))
        if uses:
            found[relative] = uses
    return found


def test_library_modules_do_no_terminal_io() -> None:
    found = terminal_uses()
    new = {m: n for m, n in found.items() if n > ALLOWED.get(m, 0)}
    assert not new, (
        "library modules print, prompt or import a terminal toolkit; log instead "
        f"(titan._log) or move the code into a *_ui / cli module: {new}"
    )
    stale = {m: found.get(m, 0) for m, n in ALLOWED.items() if found.get(m, 0) < n}
    assert not stale, f"shrink ALLOWED in {__file__} to the current counts: {stale}"
