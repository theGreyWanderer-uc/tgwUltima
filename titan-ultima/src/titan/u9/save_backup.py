"""Preserving U9 save backups: selected archive plus all loose working files."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def validate_u9_save_output(
    output: Path, save_directory: Path, sources: tuple[Path, ...] = ()
) -> None:
    """Reject outputs in live game data or equal to any source file."""
    target = output.resolve()
    save = save_directory.resolve()
    protected = [save]
    if save.name.casefold() == "savegame":
        protected.extend(save.parent / name for name in ("static", "runtime"))
    protected.extend(source.resolve() for source in sources if source.is_dir())
    for directory in protected:
        if target == directory or directory in target.parents:
            raise ValueError(
                "U9 save browser: write exports and backups outside game data"
            )
    if any(target == source.resolve() for source in sources):
        raise ValueError("U9 save browser: output must differ from source files")


def next_u9_save_output(output: Path, stem: str, suffix: str = "") -> Path:
    """Choose a new export name, preserving every earlier report or extraction."""
    index = 0
    while True:
        path = output / f"{stem}{'_' + str(index) if index else ''}{suffix}"
        if not path.exists() and not path.is_symlink():
            return path
        index += 1


def _file_signature(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_size, info.st_mtime_ns


def _file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        return digest.hexdigest()


def _loose_save_files(save_directory: Path) -> list[Path]:
    if not save_directory.is_dir():
        return []
    return sorted(
        (
            path
            for path in save_directory.iterdir()
            if path.is_file() and path.suffix.casefold() != ".sav"
        ),
        key=lambda path: path.name.casefold(),
    )


def backup_u9_save(
    archive: Path,
    save_directory: Path,
    output: Path,
    *,
    slot: int | None = None,
    now: datetime | None = None,
) -> Path:
    """Back up byte-exact archive/working files; completion requires stable sources."""
    validate_u9_save_output(output, save_directory, (archive,))
    if not archive.is_file():
        raise ValueError("U9 save backup: selected archive is unavailable")
    loose = _loose_save_files(save_directory)
    files = [(archive, Path("archive") / archive.name)]
    files.extend((path, Path("working") / path.name) for path in loose)
    if any(source.is_symlink() for source, _ in files):
        raise ValueError("U9 save backup: source files must not be symbolic links")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%S") + f"{moment.microsecond // 1000:03d}Z"
    stem = f"u9-save-slot-{slot if slot is not None else 'unknown'}-{stamp}"
    output.mkdir(parents=True, exist_ok=True)
    index = 0
    while True:
        folder = output / f"{stem}{'_' + str(index) if index else ''}"
        try:
            folder.mkdir()
            break
        except FileExistsError:
            index += 1
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "complete": False,
        "slot": slot,
        "created_utc": moment.isoformat(),
        "archive_source": str(archive.resolve()),
        "working_source": str(save_directory.resolve()),
        "start_dat_present": any(path.name.casefold() == "start.dat" for path in loose),
        "working_files_are_current": True,
        "files": [],
        "note": "Working files are the current folder snapshot and may belong to another slot. No installed map files or other slot archives are included.",
    }
    manifest_path = folder / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    try:
        before = {source: _file_signature(source) for source, _ in files}
        for source, relative in files:
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            digest = _file_hash(target)
            if (
                digest != _file_hash(source)
                or _file_signature(source) != before[source]
            ):
                raise ValueError(
                    "U9 save backup: source changed during backup; stop the game and try again"
                )
            manifest["files"].append(
                {
                    "path": relative.as_posix(),
                    "source": str(source.resolve()),
                    "bytes": target.stat().st_size,
                    "sha256": digest,
                }
            )
        if loose != _loose_save_files(save_directory) or any(
            _file_signature(source) != signature for source, signature in before.items()
        ):
            raise ValueError(
                "U9 save backup: working folder changed during backup; stop the game and try again"
            )
        manifest["complete"] = True
    except (OSError, ValueError) as error:
        manifest["error"] = str(error)
        raise
    finally:
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    return folder
