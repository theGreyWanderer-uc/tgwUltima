"""Carry U7 frame-animation choices and update owner-scoped TFA object flags.

Standalone SHP files have no object flags. Their hash-bound animation sidecar
keeps the choice until insertion into a world shape archive assigns a shape ID.

Nothing here prompts: the CLI asks through :mod:`titan.u7.shape_animation_ui`
and passes the answer (or a ``choose`` callback) in.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Callable

from titan.u7.shape import U7Shape
from titan.u7.shape_archive import find_archive

log = logging.getLogger(__name__)

AnimationChooser = Callable[[int, U7Shape, "bool | None"], "bool | None"]
"""``choose(record_number, shape, default)`` -> animate?, for records with no explicit choice."""

ANIMATED_OBJECT_FLAG = 0x04
ANIMATION_SIDECAR_SUFFIX = ".animation.json"


def u7_animation_sidecar(path: Path) -> Path:
    """Use a suffix that cannot be mistaken for a numbered Flex input record."""
    return path.with_name(path.name + ANIMATION_SIDECAR_SUFFIX)


def u7_shape_animation_payload(data: bytes, animated: bool) -> bytes:
    """Bind a standalone animation choice to the exact shape bytes, preventing stale reuse."""
    return (
        json.dumps(
            {
                "format": "titan-u7-shape-animation-1",
                "sha256": hashlib.sha256(data).hexdigest(),
                "animated": animated,
            },
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def read_u7_shape_animation(path: Path, data: bytes) -> bool | None:
    """Read a matching standalone choice; ignore stale sidecars after external edits."""
    sidecar = u7_animation_sidecar(path)
    if not sidecar.is_file():
        return None
    report = json.loads(sidecar.read_text(encoding="utf-8"))
    if (
        not isinstance(report, dict)
        or report.get("format") != "titan-u7-shape-animation-1"
    ):
        raise ValueError(f"Invalid U7 animation sidecar: {sidecar}")
    if report.get("sha256") != hashlib.sha256(data).hexdigest():
        return None
    if type(report.get("animated")) is not bool:
        raise ValueError(f"Invalid U7 animation choice: {sidecar}")
    return report["animated"]


def can_animate(shape: U7Shape) -> bool:
    """Only multi-frame RLE artwork animates; flats and single frames never do."""
    return len(shape.frames) > 1 and not any(frame.is_tile for frame in shape.frames)


def resolve_u7_shape_animation(
    shape: U7Shape,
    *,
    animated: bool | None = None,
    default: bool | None = None,
) -> bool | None:
    """The animation choice without asking: *animated* if given, else *default*.

    ``None`` means "no animation metadata" (always so for shapes that can't
    animate). Asking ``animated=True`` of such a shape is a ``ValueError``.
    """
    if not can_animate(shape):
        if animated:
            raise ValueError(
                "U7 frame animation requires more than one RLE object frame"
            )
        return None
    return animated if animated is not None else default


def prepare_u7_archive_animation(
    output: Path,
    updates: dict[int, tuple[bytes, bool]],
    *,
    world_shapes: bool,
    sources: tuple[Path, ...] = (),
) -> list[tuple[Path, bytes]]:
    """Preserve other TFA bits/entries; generic libraries carry choices without world flags."""
    if not updates:
        return []
    sidecar = u7_animation_sidecar(output)
    choices: dict[str, object] = {}
    if sidecar.exists():
        old = json.loads(sidecar.read_text(encoding="utf-8"))
        if (
            not isinstance(old, dict)
            or old.get("format") != "titan-u7-archive-animation-1"
            or not isinstance(old.get("shapes"), dict)
        ):
            raise ValueError(f"Invalid U7 archive animation sidecar: {sidecar}")
        choices.update(old["shapes"])
    for number, (data, animated) in updates.items():
        choices[str(number)] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "animated": animated,
        }
    result = [
        (
            sidecar,
            (
                json.dumps(
                    {"format": "titan-u7-archive-animation-1", "shapes": choices},
                    indent=2,
                )
                + "\n"
            ).encode("utf-8"),
        )
    ]
    if not world_shapes:
        return result
    table_path = find_archive(output.parent, "TFA.DAT") or output.parent / "TFA.DAT"
    candidates = [table_path] + [
        find_archive(path if path.is_dir() else path.parent, "TFA.DAT")
        for path in sources
    ]
    original = next(
        (path for path in candidates if path is not None and path.is_file()), None
    )
    raw = original.read_bytes() if original else b""
    if raw and len(raw) != 3584 and len(raw) % 3:
        raise ValueError(f"U7 animation: incomplete TFA records in {original}")
    highest = max(updates)
    if not 150 <= min(updates) <= highest <= 65535:
        raise ValueError("U7 animated object flags require world shape IDs 150-65535")
    # Retail animation nibbles are not shape records. Exult reads them from the
    # original STATIC TFA independently; extended patch tables contain 3-byte entries.
    if len(raw) == 3584 and highest >= 1024:
        if original is not None and table_path.resolve() == original.resolve():
            raise ValueError(
                "U7 animation: extended shapes require a separate patch/output TFA.DAT"
            )
        raw = raw[:3072]
    table = bytearray(raw)
    table.extend(bytes(max(0, (highest + 1) * 3 - len(table))))
    for number, (_, animated) in updates.items():
        position = number * 3
        table[position] = (
            (table[position] | ANIMATED_OBJECT_FLAG)
            if animated
            else (table[position] & ~ANIMATED_OBJECT_FLAG)
        )
    result.append((table_path, bytes(table)))
    return result


def write_u7_animation_payloads(payloads: list[tuple[Path, bytes]]) -> None:
    """Atomically replace each prepared metadata file after validation, alongside its output."""
    for path, data in payloads:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        log.info("  Animation metadata written: %s", path)


def prepare_u7_flex_animation_import(
    records: dict[int, bytes],
    output: Path,
    *,
    sources: tuple[Path, ...] = (),
    input_paths: dict[int, Path] | None = None,
    animated: bool | None = None,
    choose: AnimationChooser | None = None,
) -> list[tuple[Path, bytes]]:
    """Recognize validated U7 RLE data in generic Flex imports; leave unrelated records alone.

    Each multi-frame record takes *animated* when given. Otherwise *choose*
    decides (the CLI passes a prompt), with the record's sidecar choice as its
    default; without *choose*, the sidecar choice is kept.
    """
    from titan.u7.shape_validation import validate_u7_shape_data

    updates = {}
    for number, raw in records.items():
        try:
            validate_u7_shape_data(raw)
        except ValueError:
            continue
        shape = U7Shape.from_data(raw, strict=True)
        if len(shape.frames) <= 1:
            continue
        path = (input_paths or {}).get(number)
        default = read_u7_shape_animation(path, raw) if path else None
        log.info("  U7 shape record %d: %d frames", number, len(shape.frames))
        if animated is None and choose is not None and can_animate(shape):
            choice = choose(number, shape, default)
        else:
            choice = resolve_u7_shape_animation(
                shape, animated=animated, default=default
            )
        if choice is not None:
            updates[number] = (raw, choice)
    nonworld_names = {
        "gumps.vga",
        "faces.vga",
        "fonts.vga",
        "sprites.vga",
        "paperdol.vga",
        "mainshp.flx",
        "endshape.flx",
        "exult.flx",
        "exult_bg.flx",
        "exult_si.flx",
    }
    generic_library = any(
        path.name.lower() in nonworld_names for path in (output, *sources)
    )
    world_updates = {
        number: value
        for number, value in updates.items()
        if number >= 150 and not generic_library
    }
    if world_updates:
        # Keep the archive sidecar for every selected record; only world slots get TFA flags.
        payloads = prepare_u7_archive_animation(
            output, updates, world_shapes=False, sources=sources
        )
        payloads.extend(
            prepare_u7_archive_animation(
                output, world_updates, world_shapes=True, sources=sources
            )[1:]
        )
        return payloads
    return prepare_u7_archive_animation(
        output, updates, world_shapes=False, sources=sources
    )
