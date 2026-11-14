"""``titan uo animation-*`` — animation frame, resolution and body-name commands."""

from __future__ import annotations

__all__ = [
    "animation_export_cmd",
    "animation_resolution_export_cmd",
    "animation_body_names_export_cmd",
]

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan.uo.animation import (
    UOAnimationDecoder,
    animation_naming,
    legacy_animation_slot,
    load_mobtype_flags,
    load_mobtypes,
)
from titan.uo.animresolve import (
    UOAnimationResolution,
    UOAnimationResolver,
    UOAnimationSequence,
    animation_entry_index,
)
from titan.uo.animnames import UOAnimationBodyNames
from titan.uo.definfo import UOBodyConvDefEntry, UODefFile, UOEquipConvDefEntry
from titan.uo.indexed import UOIndexedFile
from titan.uo.cli import _common


def _load_animations(client: Path, set_name: str) -> UOIndexedFile:
    allowed = {"anim", "anim2", "anim3", "anim4", "anim5", "anim6"}
    if set_name not in allowed:
        raise ValueError(f"unsupported animation set: {set_name}")

    mul = client / f"{set_name}.mul"
    idx = client / f"{set_name}.idx"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError(f"{set_name}.mul/{set_name}.idx not found")


def _try_load_animation_sequence(client: Path) -> UOAnimationSequence | None:
    path = client / "AnimationSequence.uop"
    if not path.is_file():
        return None
    try:
        return UOAnimationSequence.from_file(path)
    except Exception:
        return None


def _animation_resolver(
    client: Path,
    defs: dict[str, UODefFile],
) -> UOAnimationResolver:
    return UOAnimationResolver(
        defs=defs,
        sequence=_try_load_animation_sequence(client),
        mobtype_flags=load_mobtype_flags(client / "mobtypes.txt"),
    )


def _bodyconv_metadata(entry: UOBodyConvDefEntry | None) -> dict[str, object]:
    if entry is None:
        return {
            "bodyconv": "",
            "bodyconv_anim2": "",
            "bodyconv_anim3": "",
            "bodyconv_anim4": "",
            "bodyconv_anim5": "",
            "bodyconv_anim6": "",
            "bodyconv_line": "",
        }
    return {
        "bodyconv": 1,
        "bodyconv_anim2": entry.anim2,
        "bodyconv_anim3": entry.anim3,
        "bodyconv_anim4": entry.anim4,
        "bodyconv_anim5": entry.anim5,
        "bodyconv_anim6": entry.anim6,
        "bodyconv_line": entry.line_number,
    }


def _equipconv_metadata(entries: list[UOEquipConvDefEntry]) -> dict[str, object]:
    if not entries:
        return {
            "equipconv": "",
            "equipconv_bodies": "",
            "equipconv_convert_to": "",
            "equipconv_gumps": "",
            "equipconv_hues": "",
            "equipconv_comments": "",
        }
    return {
        "equipconv": 1,
        "equipconv_bodies": "|".join(str(entry.body) for entry in entries),
        "equipconv_convert_to": "|".join(str(entry.convert_to) for entry in entries),
        "equipconv_gumps": "|".join(str(entry.gump) for entry in entries),
        "equipconv_hues": "|".join(str(entry.hue) for entry in entries),
        "equipconv_comments": "|".join(
            entry.comment for entry in entries if entry.comment
        ),
    }


def _animation_def_metadata(
    defs: dict[str, UODefFile],
    *,
    set_name: str,
    body: int,
) -> dict[str, object]:
    bodydef = defs.get("body.def")
    corpse = defs.get("corpse.def")
    anim1 = defs.get("anim1.def")
    anim2 = defs.get("anim2.def")
    bodyconv = defs.get("bodyconv.def")
    equipconv = defs.get("equipconv.def")

    bodyconv_entry = bodyconv.bodyconv.get(body) if bodyconv is not None else None
    equip_matches = (
        [entry for entry in equipconv.equipconv if entry.equipment == body]
        if equipconv is not None
        else []
    )
    return {
        **_common._redirect_metadata(
            "bodydef", bodydef.redirects.get(body) if bodydef is not None else None
        ),
        **_common._redirect_metadata(
            "corpse", corpse.redirects.get(body) if corpse is not None else None
        ),
        **_common._redirect_metadata(
            "anim1def", anim1.redirects.get(body) if anim1 is not None else None
        ),
        **_common._redirect_metadata(
            "anim2def", anim2.redirects.get(body) if anim2 is not None else None
        ),
        **_bodyconv_metadata(bodyconv_entry),
        "bodyconv_effective_archive": (
            ""
            if bodyconv_entry is None
            else bodyconv_entry.archive_for_set(set_name) or ""
        ),
        **_equipconv_metadata(equip_matches),
    }


def _animation_resolution_metadata(
    resolution: UOAnimationResolution | None,
) -> dict[str, object]:
    if resolution is None:
        return {
            "requested_body": "",
            "requested_action": "",
            "requested_direction": "",
            "resolved_bodydef_body": "",
            "resolved_bodydef_hue": "",
            "resolved_final_body": "",
            "resolved_final_set": "",
            "resolved_file_type": "",
            "resolved_action": "",
            "resolved_direction": "",
            "resolved_raw_entry": "",
            "resolved_uop_frame_path": "",
            "resolved_bodydef_applied": "",
            "resolved_bodyconv_applied": "",
            "resolved_sequence_applied": "",
            "resolved_uop_sequence_body": "",
        }
    return {
        "requested_body": resolution.requested_body,
        "requested_action": resolution.requested_action,
        "requested_direction": resolution.requested_direction,
        "resolved_bodydef_body": resolution.bodydef_body,
        "resolved_bodydef_hue": (
            "" if resolution.bodydef_hue is None else resolution.bodydef_hue
        ),
        "resolved_final_body": resolution.final_body,
        "resolved_final_set": resolution.final_set,
        "resolved_file_type": resolution.final_file_type,
        "resolved_action": resolution.final_action,
        "resolved_direction": resolution.final_direction,
        "resolved_raw_entry": resolution.raw_entry,
        "resolved_uop_frame_path": (
            resolution.uop_frame_path if resolution.is_uop_sequence_body else ""
        ),
        "resolved_bodydef_applied": 1 if resolution.bodydef_applied else 0,
        "resolved_bodyconv_applied": 1 if resolution.bodyconv_applied else 0,
        "resolved_sequence_applied": 1 if resolution.sequence_applied else 0,
        "resolved_uop_sequence_body": 1 if resolution.is_uop_sequence_body else 0,
    }


def _animation_body_name_metadata(
    *,
    body_names: UOAnimationBodyNames | None,
    prefix: str,
    body: int,
) -> dict[str, object]:
    if body_names is None:
        return {
            f"{prefix}_body_name": "",
            f"{prefix}_body_name_source": "",
            f"{prefix}_body_name_alternates": "",
        }

    preferred = body_names.preferred(body)
    return {
        f"{prefix}_body_name": "" if preferred is None else preferred.name,
        f"{prefix}_body_name_source": "" if preferred is None else preferred.source,
        f"{prefix}_body_name_alternates": "|".join(body_names.names_for(body)),
    }


def _animation_body_dir(
    *,
    body: int,
    category: str,
    body_names: UOAnimationBodyNames | None,
) -> str:
    preferred = body_names.preferred(body) if body_names is not None else None
    if preferred is None:
        return f"body_{body:04d}_{_safe_path_part(category)}"
    return (
        f"body_{body:04d}_{_safe_path_part(preferred.name)}_{_safe_path_part(category)}"
    )


def _safe_path_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return cleaned or "unknown"


def cmd_animation_export(args: SimpleNamespace) -> int:
    """Export legacy UO animation frames to PNG."""
    try:
        client = _common._client_path(args.client)
        indexed = _load_animations(client, args.set_name)
        defs = _common._try_load_defs(client)
        resolver = _animation_resolver(client, defs)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Temporarily disable body-name-based naming for animation exports.
    body_names: UOAnimationBodyNames | None = None

    entries = _common._entry_iter(indexed, args.range_start, args.range_end)
    mobtypes = load_mobtypes(client / "mobtypes.txt")
    outdir = _common._out(args) / "animations" / args.set_name
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    saved_entries = 0
    saved_frames = 0
    failed = 0

    for entry in entries:
        if args.limit is not None and saved_entries >= args.limit:
            break
        frames = UOAnimationDecoder.decode(entry)
        if not frames:
            failed += 1
            continue

        slot = legacy_animation_slot(entry.index, args.set_name)
        naming = animation_naming(
            slot,
            set_name=args.set_name,
            mobtypes=mobtypes,
        )
        def_metadata = _animation_def_metadata(
            defs,
            set_name=args.set_name,
            body=slot.body,
        )
        resolution = (
            resolver.resolve(
                body=slot.body,
                action=slot.action,
                direction=slot.direction,
            )
            if args.set_name == "anim"
            else None
        )
        if args.layout == "named":
            body_dir = _animation_body_dir(
                body=slot.body,
                category=naming.category,
                body_names=body_names,
            )
            relative_dir = (
                f"{naming.kind}/{body_dir}/{naming.action_dir}/{naming.direction_dir}"
            )
        elif args.layout == "grouped":
            relative_dir = (
                f"body_{slot.body:04d}"
                f"/action_{slot.action:02d}"
                f"/direction_{slot.direction:02d}"
            )
        else:
            relative_dir = f"{entry.index:05d}"

        entry_dir = outdir / relative_dir
        entry_dir.mkdir(parents=True, exist_ok=True)
        for frame in frames:
            filename = f"frame_{frame.index:03d}.png"
            frame.image.save(entry_dir / filename)
            row: dict[str, object] = {
                "set": args.set_name,
                "raw_entry": entry.index,
                "body": slot.body,
                "action": slot.action,
                "action_name": naming.action_name,
                "direction": slot.direction,
                "direction_name": naming.direction_name,
                "stride": slot.stride,
                "group": slot.group,
                "kind": naming.kind,
                "category": naming.category,
                "category_source": naming.category_source,
                "frame": frame.index,
                "file": f"{relative_dir}/{filename}",
                "width": frame.width,
                "height": frame.height,
                "center_x": frame.center_x,
                "center_y": frame.center_y,
            }
            row.update(
                _animation_body_name_metadata(
                    body_names=body_names,
                    prefix="body",
                    body=slot.body,
                )
            )
            row.update(def_metadata)
            row.update(_animation_resolution_metadata(resolution))
            rows.append(row)
            saved_frames += 1
        saved_entries += 1

    _common._write_manifest(outdir / "manifest.csv", rows)
    print(
        f"Exported {saved_frames} animation frame(s) from {saved_entries} entrie(s) -> {outdir}"
    )
    if failed:
        print(f"  ({failed} animation entrie(s) failed or decoded empty)")
    return 0


def cmd_animation_resolution_export(args: SimpleNamespace) -> int:
    """Export effective UO animation body/action resolution metadata."""
    try:
        client = _common._client_path(args.client)
        defs = _common._try_load_defs(client)
        resolver = _animation_resolver(client, defs)
        mobtypes = load_mobtypes(client / "mobtypes.txt")
        sequence = _try_load_animation_sequence(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Temporarily disable body-name-based naming/metadata for resolution export.
    body_names: UOAnimationBodyNames | None = None

    outdir = _common._out(args) / "animation_resolution"
    outdir.mkdir(parents=True, exist_ok=True)
    start = 0 if args.body_start is None else args.body_start
    end = 2048 if args.body_end is None else args.body_end
    bodies = [body for body in sorted(mobtypes) if start <= body < end]
    if not bodies:
        bodies = list(range(start, end))

    rows: list[dict[str, object]] = []
    saved_bodies = 0
    for body in bodies:
        if args.limit_bodies is not None and saved_bodies >= args.limit_bodies:
            break
        saved_bodies += 1
        for action in range(args.actions):
            for direction in range(args.directions):
                resolution = resolver.resolve(
                    body=body,
                    action=action,
                    direction=direction,
                )
                requested_slot = legacy_animation_slot(
                    animation_entry_index(
                        body=body,
                        action=action,
                        direction=direction,
                        file_type=1,
                    ),
                    "anim",
                )
                requested_naming = animation_naming(
                    requested_slot,
                    set_name="anim",
                    mobtypes=mobtypes,
                )
                resolved_slot = legacy_animation_slot(
                    resolution.raw_entry,
                    resolution.final_set,
                )
                resolved_naming = animation_naming(
                    resolved_slot,
                    set_name=resolution.final_set,
                    mobtypes=mobtypes,
                )
                row: dict[str, object] = {
                    "requested_kind": requested_naming.kind,
                    "requested_category": requested_naming.category,
                    "requested_action_name": requested_naming.action_name,
                    "requested_direction_name": requested_naming.direction_name,
                    "resolved_kind": resolved_naming.kind,
                    "resolved_category": resolved_naming.category,
                    "resolved_action_name": resolved_naming.action_name,
                    "resolved_direction_name": resolved_naming.direction_name,
                    "requested_body_dir": _animation_body_dir(
                        body=body,
                        category=requested_naming.category,
                        body_names=body_names,
                    ),
                    "resolved_body_dir": _animation_body_dir(
                        body=resolution.final_body,
                        category=resolved_naming.category,
                        body_names=body_names,
                    ),
                    "resolved_action_dir": resolved_naming.action_dir,
                    "resolved_direction_dir": resolved_naming.direction_dir,
                }
                row.update(
                    _animation_body_name_metadata(
                        body_names=body_names,
                        prefix="requested",
                        body=body,
                    )
                )
                row.update(
                    _animation_body_name_metadata(
                        body_names=body_names,
                        prefix="resolved",
                        body=resolution.final_body,
                    )
                )
                row.update(_animation_resolution_metadata(resolution))
                rows.append(row)

    sequence_rows: list[dict[str, object]] = []
    if sequence is not None:
        for entry in sorted(sequence.entries.values(), key=lambda item: item.body):
            changed = [
                f"{index}->{value}"
                for index, value in enumerate(entry.replacements)
                if index != value
            ]
            sequence_rows.append(
                {
                    "body": entry.body,
                    "changed_count": len(changed),
                    "changes": "|".join(changed),
                }
            )

    _common._write_manifest(outdir / "manifest.csv", rows)
    _common._write_manifest(outdir / "sequence_replacements.csv", sequence_rows)
    print(
        f"Exported {len(rows)} animation resolution row(s), {len(sequence_rows)} sequence row(s) -> {outdir}"
    )
    return 0


def cmd_animation_body_names_export(args: SimpleNamespace) -> int:
    """Export best-effort UO animation body-name clues."""
    _ = args
    print(
        "ERROR: animation body-name export is temporarily disabled while body-name sources are disabled.",
        file=sys.stderr,
    )
    return 1


def animation_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    set_name: Annotated[
        Literal["anim", "anim2", "anim3", "anim4", "anim5", "anim6"],
        typer.Option("--set", help="Legacy animation file set."),
    ] = "anim",
    layout: Annotated[
        Literal["named", "grouped", "raw"],
        typer.Option("--layout", help="Output folder layout."),
    ] = "named",
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum decoded animation entries to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First animation entry, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last animation entry, exclusive."),
    ] = None,
) -> None:
    """Export legacy UO animation frames to PNG."""
    raise SystemExit(cmd_animation_export(SimpleNamespace(**locals())))


def animation_resolution_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    body_start: Annotated[
        Optional[int],
        typer.Option("--body-start", help="First requested body ID, inclusive."),
    ] = None,
    body_end: Annotated[
        Optional[int],
        typer.Option("--body-end", help="Last requested body ID, exclusive."),
    ] = None,
    limit_bodies: Annotated[
        Optional[int],
        typer.Option("--limit-bodies", help="Maximum requested bodies to export."),
    ] = None,
    actions: Annotated[
        int,
        typer.Option("--actions", help="Number of requested actions per body."),
    ] = 68,
    directions: Annotated[
        int,
        typer.Option("--directions", help="Number of requested directions per action."),
    ] = 5,
) -> None:
    """Export effective UO animation body/action resolution metadata."""
    raise SystemExit(cmd_animation_resolution_export(SimpleNamespace(**locals())))


def animation_body_names_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
) -> None:
    """Export best-effort UO animation body-name clues."""
    raise SystemExit(cmd_animation_body_names_export(SimpleNamespace(**locals())))
