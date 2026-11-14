"""Preflight U7 save extraction and keep duplicate member payloads in distinct output files."""

from __future__ import annotations

import json
import ntpath
from pathlib import Path, PureWindowsPath
from typing import Sequence

from titan.u7.save_container import U7SaveMember


def _is_windows_reserved(windows: PureWindowsPath) -> bool:
    """Detect DOS device names such as CON or COM1 on any host platform."""
    # ntpath.isreserved replaces PureWindowsPath.is_reserved from Python 3.13.
    isreserved = getattr(ntpath, "isreserved", None)
    if isreserved is not None:
        return isreserved(windows)
    return windows.is_reserved()


def extract_u7_save_members(
    members: Sequence[U7SaveMember],
    output_dir: str | Path,
    *,
    entry: str | None = None,
) -> tuple[list[tuple[U7SaveMember, Path]], Path | None]:
    """Validate every destination before writes; duplicates receive suffixes and a name manifest."""
    selected = [
        member
        for member in members
        if entry is None or member.name.casefold() == entry.casefold()
    ]
    if entry is not None and not selected:
        raise ValueError(f"Entry {entry!r} not found in archive")
    root = Path(output_dir).expanduser().resolve()
    original: list[Path] = []
    for member in selected:
        if member.is_directory and member.data:
            raise ValueError(
                f"U7 save extraction: directory member has a payload: {member.name!r}"
            )
        windows = PureWindowsPath(member.name)
        normalized = member.name.replace("\\", "/")
        path = Path(normalized)
        if (
            not member.name
            or windows.drive
            or windows.is_absolute()
            or _is_windows_reserved(windows)
            or path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or any(
                part.endswith((" ", "."))
                or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
                for part in path.parts
            )
        ):
            raise ValueError(f"U7 save extraction: unsafe member name {member.name!r}")
        if not (root / path).resolve().is_relative_to(root):
            raise ValueError(
                f"U7 save extraction: member escapes output directory: {member.name!r}"
            )
        original.append(path)
    reserved = {path.as_posix().casefold() for path in original}
    allocated: set[str] = set()
    plan: list[tuple[U7SaveMember, Path]] = []
    duplicates = False
    for member, path in zip(selected, original):
        candidate, counter = path, 0
        if candidate.as_posix().casefold() in allocated:
            duplicates = True
            while True:
                suffix = f".duplicate-{member.index:04d}" + (
                    f"-{counter}" if counter else ""
                )
                name = (
                    path.name + suffix
                    if member.is_directory
                    else path.stem + suffix + path.suffix
                )
                candidate = path.with_name(name)
                key = candidate.as_posix().casefold()
                if key not in reserved and key not in allocated:
                    break
                counter += 1
        allocated.add(candidate.as_posix().casefold())
        target = (root / candidate).resolve()
        if not target.is_relative_to(root):
            raise ValueError(
                f"U7 save extraction: destination escapes output directory: {candidate}"
            )
        if target.exists() and (not member.is_directory or not target.is_dir()):
            raise ValueError(f"U7 save extraction: output already exists: {target}")
        plan.append((member, target))
    files = {path for member, path in plan if not member.is_directory}
    for member, path in plan:
        if (
            member.is_directory
            and path in files
            or any(parent in files or parent.is_file() for parent in path.parents)
        ):
            raise ValueError(
                f"U7 save extraction: conflicting file/directory destination: {path}"
            )
    manifest = None
    if duplicates or any(not member.complete for member in selected):
        manifest_reserved = (
            reserved
            | allocated
            | {
                parent.as_posix().casefold()
                for path in original
                for parent in path.parents
            }
        )
        counter = 0
        while True:
            name = "titan-save-members" + (f"-{counter}" if counter else "") + ".json"
            if name.casefold() not in manifest_reserved and not (root / name).exists():
                manifest = root / name
                break
            counter += 1
    if not plan:
        return [], None
    root.mkdir(parents=True, exist_ok=True)
    for member, path in plan:
        if member.is_directory:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(member.data)
    if manifest is not None:
        mapping = [
            {
                "index": member.index,
                "name": member.name,
                "source": member.source,
                "declared_size": member.declared_size,
                "size": len(member.data),
                "complete": member.complete,
                "output": path.relative_to(root).as_posix(),
            }
            for member, path in plan
        ]
        with manifest.open("x", encoding="utf-8") as stream:
            json.dump(mapping, stream, indent=2)
            stream.write("\n")
    return plan, manifest
