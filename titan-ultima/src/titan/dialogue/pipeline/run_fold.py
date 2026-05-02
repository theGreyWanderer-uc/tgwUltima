"""Run the bundled fold binary to extract U8 pseudo text files."""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional


class FoldRunError(RuntimeError):
    """Raised when fold execution fails."""


def _bundled_fold_subdir() -> str:
    if os.name == "nt":
        return "windows-x64"
    if sys.platform.startswith("linux"):
        return "linux-x64"
    raise FoldRunError(f"Unsupported platform for bundled fold binary: {sys.platform}")


def _platform_local_fold_names() -> tuple[str, ...]:
    if os.name == "nt":
        return ("fold.exe", "fold")
    return ("fold", "fold.exe")


def get_bundled_fold_path() -> Path:
    """Return the bundled fold executable path for the current platform."""
    binary_name = "fold.exe" if os.name == "nt" else "fold"
    return Path(__file__).resolve().parents[1] / "tools" / "fold" / _bundled_fold_subdir() / binary_name


def get_bundled_fold_dll_path() -> Path | None:
    """Return the bundled Windows DLL dependency path, or None on non-Windows."""
    if os.name != "nt":
        return None
    return Path(__file__).resolve().parents[1] / "tools" / "fold" / "windows-x64" / "libwinpthread-1.dll"


def _resolve_fold_exe(usecode_path: Path) -> Path:
    """Prefer colocated fold near EUSECODE, then fallback to bundled binary."""
    for local_name in _platform_local_fold_names():
        local_fold = usecode_path.parent / local_name
        if local_fold.is_file():
            return local_fold
    return get_bundled_fold_path()


def get_effective_fold_path(usecode_path: Path) -> Path:
    """Return the fold executable path that will be used for this EUSECODE path."""
    return _resolve_fold_exe(usecode_path)


def _resolve_optional_meta(
    usecode_path: Path,
    symbols_path: Path | None,
    classes_path: Path | None,
) -> tuple[Path | None, Path | None]:
    """Resolve symbols/classes paths from args, colocated files, then repo defaults."""
    if symbols_path and classes_path:
        return (symbols_path if symbols_path.is_file() else None, classes_path if classes_path.is_file() else None)

    base = usecode_path.parent
    symbols = symbols_path or (base / "symbols.csv")
    classes = classes_path or (base / "usecode_classes.csv")

    pipeline_resources = Path(__file__).resolve().parent / "resources"
    titan_symbols = pipeline_resources / "symbols.csv"
    titan_classes = pipeline_resources / "usecode_classes.csv"

    if not symbols.is_file():
        repo_symbols = titan_symbols if titan_symbols.is_file() else (Path.cwd() / ".github" / "reference" / "symbols.csv")
        symbols = repo_symbols if repo_symbols.is_file() else symbols
    if not classes.is_file():
        repo_classes = titan_classes if titan_classes.is_file() else (Path.cwd() / ".github" / "reference" / "usecode_classes.csv")
        classes = repo_classes if repo_classes.is_file() else classes
    return (symbols if symbols.is_file() else None, classes if classes.is_file() else None)


def _common_args(game: str, lang: str, symbols: Path | None, classes: Path | None) -> list[str]:
    args = ["--game", game, "--lang", lang, "--pseudo"]
    if symbols:
        args += ["--symbols", str(symbols)]
    if classes:
        args += ["--classes", str(classes)]
    return args


def run_fold(
    usecode_path: Path,
    output_dir: Path,
    game: str = "u8",
    lang: str = "english",
    progress_cb: Optional[Callable[[str], None]] = None,
    symbols_path: Path | None = None,
    classes_path: Path | None = None,
) -> int:
    """Run fold on the provided EUSECODE file.

    fold writes one text file per class (``U8P_*.txt``) into ``output_dir``.
    """
    fold_exe = _resolve_fold_exe(usecode_path)
    bundled_fold = get_bundled_fold_path()
    fold_dll = get_bundled_fold_dll_path()
    symbols, classes = _resolve_optional_meta(usecode_path, symbols_path, classes_path)
    common = _common_args(game, lang, symbols, classes)

    if not fold_exe.is_file():
        raise FoldRunError(f"Bundled fold executable not found: {fold_exe}")
    if fold_dll and fold_exe == bundled_fold and not fold_dll.is_file():
        raise FoldRunError(f"Bundled fold dependency not found: {fold_dll}")
    if not usecode_path.is_file():
        raise FoldRunError(f"EUSECODE file not found: {usecode_path}")
    if not symbols:
        raise FoldRunError("symbols.csv not found. Provide --symbols or place symbols.csv next to EUSECODE.FLX")
    if not classes:
        raise FoldRunError("usecode_classes.csv not found. Provide --classes or place usecode_classes.csv next to EUSECODE.FLX")

    output_dir.mkdir(parents=True, exist_ok=True)

    with classes.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    class_entries: list[tuple[str, str]] = []
    for row in rows:
        hex_id = (row.get("HexID") or row.get("hex_id") or "").strip()
        name = (row.get("Name") or row.get("name") or "").strip()
        if hex_id and name:
            class_entries.append((hex_id, name))

    if not class_entries:
        raise FoldRunError(f"No class entries found in classes CSV: {classes}")

    created = 0
    total = len(class_entries)
    for i, (hex_id, class_name) in enumerate(class_entries, start=1):
        if progress_cb:
            progress_cb(f"Folding {class_name} ({i}/{total})")

        class_cmd = [
            str(fold_exe),
            str(usecode_path),
            hex_id,
            *common,
        ]
        class_proc = subprocess.run(class_cmd, capture_output=True, text=True, timeout=30)
        if class_proc.returncode != 0:
            continue

        output_lines = class_proc.stdout.splitlines()
        filtered_lines = []
        skip_prefixes = (
            "=== PSEUDO",
            "Creating FileSystem",
            "Destroying FileSystem",
            "Game type:",
            "Language:",
        )
        for line in output_lines:
            stripped = line.strip()
            if any(stripped.startswith(prefix) for prefix in skip_prefixes):
                continue
            filtered_lines.append(line)

        while filtered_lines and not filtered_lines[0].strip():
            filtered_lines.pop(0)
        while filtered_lines and not filtered_lines[-1].strip():
            filtered_lines.pop()

        output_text = "\n".join(filtered_lines).strip()
        if not output_text:
            continue

        out_file = output_dir / f"U8P_{class_name}.txt"
        out_file.write_text(output_text + "\n", encoding="utf-8")
        created += 1

    if created == 0:
        raise FoldRunError(f"fold completed but generated no U8P_*.txt files in: {output_dir}")

    return created
