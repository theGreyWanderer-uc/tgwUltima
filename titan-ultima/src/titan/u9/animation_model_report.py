"""Build cross-file animation-to-model candidate reports for Ultima IX.

The report intentionally distinguishes structural compatibility from a real
runtime binding. ``registry.txt`` proves how animation part IDs match model
limb IDs, while the source LightWave path provides useful human-readable
family/action hints. Neither source says which object state selects a clip.
"""

from __future__ import annotations

__all__ = [
    "ANIMATION_MODEL_REPORT_COLUMNS",
    "U9AnimationModelReportError",
    "build_animation_model_report",
]

import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from titan.u9.animation import U9Animation, U9AnimationError, U9Animations
from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.model import U9Model, U9ModelError
from titan.u9.node_registry import U9NodeRegistry, U9NodeRegistryError
from titan.u9.typename import U9TypeNames
from titan.u9.types_dat import U9TypeRecord, U9TypesDat, U9TypesDatError


class U9AnimationModelReportError(Exception):
    """Raised when animation/model report inputs cannot be read or validated."""


ANIMATION_MODEL_REPORT_COLUMNS = [
    "animation_archive",
    "animation_id",
    "animation_label",
    "source_path",
    "source_asset_group",
    "source_family",
    "source_category",
    "source_stem",
    "source_actor_hint",
    "source_actor_hint_basis",
    "action_hint",
    "start_frame",
    "end_frame",
    "frame_count",
    "source_fps",
    "frame_interval_ms",
    "duration_ms",
    "part_count",
    "part_ids",
    "part_names",
    "suffix_count",
    "suffix_values",
    "registry_status",
    "registry_name_match_count",
    "registry_name_mismatches",
    "registry_unknown_part_ids",
    "model_track_count",
    "model_track_ids",
    "authoring_only_track_count",
    "authoring_only_track_ids",
    "authoring_only_track_names",
    "candidate_status",
    "candidate_basis",
    "candidate_ambiguity",
    "full_structural_candidate_count",
    "candidate_model_count",
    "candidate_model_ids",
    "candidate_named_models",
    "candidate_models",
    "best_match_part_count",
    "best_match_ratio",
    "source_name_candidate_count",
    "source_name_candidate_models",
    "runtime_binding_status",
    "runtime_binding_evidence",
    "ghidra_priority",
    "ghidra_question",
]


@dataclass(frozen=True)
class _SourceHints:
    asset_group: str
    family: str
    category: str
    stem: str
    actor: str
    actor_basis: str
    action: str

    @property
    def label(self) -> str:
        return "/".join(
            value for value in (self.family, self.category, self.stem) if value
        )


@dataclass(frozen=True)
class _ModelMetadata:
    model_id: int
    record_format: str
    limb_ids: frozenset[int]
    geometry_limb_count: int
    names: tuple[str, ...]
    type_records: tuple[U9TypeRecord, ...]
    type_names: tuple[str | None, ...]
    clean_flags_06: tuple[int, ...]


_GENERIC_ACTOR_HINTS = {"", "humanoid", "npc", "magic", "ui"}
_NAME_STOP_WORDS = {"a", "an", "of", "the"}


def _case_insensitive_child(directory: Path, filename: str) -> Path | None:
    wanted = filename.casefold()
    try:
        return next(
            (child for child in directory.iterdir() if child.name.casefold() == wanted),
            None,
        )
    except OSError:
        return None


def _required_file(value: str | Path, description: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise U9AnimationModelReportError(f"{description} not found: {path}")
    return path


def _optional_companion(
    directory: Path,
    explicit: str | Path | None,
    filename: str,
) -> Path | None:
    if explicit is not None:
        return _required_file(explicit, filename)
    return _case_insensitive_child(directory, filename)


def _parse_source_hints(source_name: str) -> _SourceHints:
    parts = list(PureWindowsPath(source_name).parts)
    lowered = [part.casefold() for part in parts]
    filename = parts[-1] if parts else source_name
    stem = PureWindowsPath(filename).stem.casefold()

    asset_group = "other"
    relative: list[str] = []
    for marker in ("motions", "objects"):
        if marker in lowered:
            marker_index = lowered.index(marker)
            asset_group = marker
            relative = [part.casefold() for part in parts[marker_index + 1 :]]
            break

    directories = relative[:-1]
    family = directories[0] if directories else ""
    category_parts = [part for part in directories[1:] if part != "lws"]
    category = "/".join(category_parts)

    actor = family
    actor_basis = "family-directory" if family else "none"
    if "avatar" in stem:
        actor = "avatar"
        actor_basis = "filename-token"
    elif "npc" in stem:
        actor = "npc"
        actor_basis = "filename-token"
    elif asset_group == "objects" and "_" in stem:
        actor = stem.split("_", 1)[0]
        actor_basis = "object-filename"

    action = stem
    family_prefix = f"{family}_"
    if family and action.startswith(family_prefix):
        action = action[len(family_prefix) :]
    for marker in ("_avatar", "_npc"):
        if marker in action:
            action = action.split(marker, 1)[0]
            break

    return _SourceHints(
        asset_group=asset_group,
        family=family,
        category=category,
        stem=stem,
        actor=actor,
        actor_basis=actor_basis,
        action=action,
    )


def _load_type_helpers(
    directory: Path,
    types_path: str | Path | None,
    typenames_path: str | Path | None,
) -> tuple[U9TypesDat | None, U9TypeNames | None, list[str]]:
    warnings: list[str] = []
    types_file = _optional_companion(directory, types_path, "TYPES.DAT")
    names_file = _optional_companion(directory, typenames_path, "TYPENAME.FLX")
    if types_file is None or names_file is None:
        warnings.append(
            "model type/name evidence requires both TYPES.DAT and TYPENAME.FLX"
        )
        return None, None, warnings
    try:
        return (
            U9TypesDat.from_file(types_file),
            U9TypeNames.from_file(names_file),
            warnings,
        )
    except (OSError, U9TypesDatError, U9FlxArchiveError) as error:
        warnings.append(f"could not load model type/name evidence: {error}")
        return None, None, warnings


def _model_material_flags_06(model: U9Model) -> tuple[int, ...]:
    values = {
        material.flags_06
        for limb in model.limbs
        for lod in limb.lods
        if lod is not None
        for material in lod.materials
        if 0x80 <= material.flags_06 <= 0x9F
    }
    return tuple(sorted(values))


def _read_model_metadata(
    model_path: Path,
    types: U9TypesDat | None,
    typenames: U9TypeNames | None,
) -> tuple[list[_ModelMetadata], list[str]]:
    warnings: list[str] = []
    try:
        archive = U9FlxArchive.from_file(model_path)
    except (OSError, U9FlxArchiveError) as error:
        raise U9AnimationModelReportError(
            f"could not read sappear.flx at {model_path}: {error}"
        ) from error

    models: list[_ModelMetadata] = []
    parse_errors = 0
    for model_id in archive.used_entry_indices():
        try:
            model = U9Model.parse(archive.read_entry(model_id), model_id)
        except (U9ModelError, OSError):
            parse_errors += 1
            continue
        type_records = (
            tuple(
                types.records[type_id] for type_id in types.type_ids_for_model(model_id)
            )
            if types is not None
            else ()
        )
        type_names = tuple(
            typenames.name_for(record.type_id) if typenames is not None else None
            for record in type_records
        )
        names = tuple(dict.fromkeys(name for name in type_names if name))
        models.append(
            _ModelMetadata(
                model_id=model_id,
                record_format=model.record_format,
                limb_ids=frozenset(limb.limb_id for limb in model.limbs),
                geometry_limb_count=sum(
                    1
                    for limb in model.limbs
                    if any(lod is not None and bool(lod.triangles) for lod in limb.lods)
                ),
                names=names,
                type_records=type_records,
                type_names=type_names,
                clean_flags_06=_model_material_flags_06(model),
            )
        )
    if parse_errors:
        warnings.append(
            f"{parse_errors} sappear.flx model entries could not be parsed and were skipped"
        )
    return models, warnings


def _canonical_name(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _name_matches_actor_hint(name: str, actor_hint: str) -> bool:
    if actor_hint in _GENERIC_ACTOR_HINTS:
        return False
    hint = _canonical_name(actor_hint)
    canonical = _canonical_name(name)
    if not hint or not canonical:
        return False
    if hint in canonical or canonical in hint:
        return True
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", name.casefold())
        if word not in _NAME_STOP_WORDS and len(word) >= 3
    ]
    return bool(words) and all(word in hint for word in words)


def _named_model_strings(models: list[_ModelMetadata]) -> list[str]:
    return [
        f"{model.model_id}:{'|'.join(model.names)}" for model in models if model.names
    ]


def _candidate_model_record(
    model: _ModelMetadata,
    model_track_ids: frozenset[int],
    part_names: dict[int, str],
) -> dict[str, Any]:
    matched_ids = sorted(model_track_ids & model.limb_ids)
    missing_ids = sorted(model_track_ids - model.limb_ids)
    return {
        "model_id": model.model_id,
        "model_names": list(model.names),
        "record_format": model.record_format,
        "limb_count": len(model.limb_ids),
        "geometry_limb_count": model.geometry_limb_count,
        "matched_track_count": len(matched_ids),
        "matched_track_ids": matched_ids,
        "missing_track_count": len(missing_ids),
        "missing_track_ids": missing_ids,
        "missing_track_names": [part_names[node_id] for node_id in missing_ids],
        "clean_material_flags_06": [f"0x{value:02x}" for value in model.clean_flags_06],
        "type_ids": [record.type_id for record in model.type_records],
        "type_names": list(model.type_names),
        "usecode_ids": sorted({record.usecode_id for record in model.type_records}),
        "type_flags": sorted(
            {f"0x{record.type_flags:04x}" for record in model.type_records}
        ),
    }


def _registry_fields(
    animation: U9Animation,
    registry: U9NodeRegistry | None,
) -> dict[str, Any]:
    if registry is None:
        return {"registry_status": "unavailable"}
    mismatches = [
        {
            "part_id": part.part_id,
            "animation_name": part.name,
            "registry_name": registry.name_for(part.part_id),
        }
        for part in animation.parts
        if registry.name_for(part.part_id) is not None
        and registry.name_for(part.part_id) != part.name
    ]
    unknown = [
        part.part_id
        for part in animation.parts
        if registry.name_for(part.part_id) is None
    ]
    return {
        "registry_status": "complete" if not mismatches and not unknown else "mismatch",
        "registry_name_match_count": len(animation.parts)
        - len(mismatches)
        - len(unknown),
        "registry_name_mismatches": mismatches,
        "registry_unknown_part_ids": unknown,
    }


def _ghidra_fields(candidate_status: str, candidate_count: int) -> dict[str, Any]:
    if candidate_status == "partial-best":
        priority = "high-part-mismatch"
        question = (
            "Why does no shipped model contain every model-used part ID? Trace "
            "part filtering, alternate model assembly, and clip application."
        )
    elif candidate_count > 10:
        priority = "high-selection-ambiguity"
        question = (
            "Which object type, activity, equipment, AI, or movement state narrows "
            "this broad compatible-model set and selects this animation ID?"
        )
    elif candidate_count > 1:
        priority = "medium-selection-ambiguity"
        question = (
            "Which runtime class/state selects this animation ID from the small "
            "compatible-model set?"
        )
    elif candidate_count == 1:
        priority = "confirm-unique-candidate"
        question = (
            "Confirm the runtime class/state binding and local-transform playback "
            "for this unique structural candidate."
        )
    else:
        priority = "high-no-candidate"
        question = (
            "Trace how this clip is consumed; no model candidate could be established "
            "from the available model-part namespace."
        )
    return {
        "runtime_binding_status": "unresolved",
        "runtime_binding_evidence": (
            "source-path naming and registry-backed structural compatibility only"
        ),
        "ghidra_priority": priority,
        "ghidra_question": question,
    }


def _animation_report_row(
    animation_path: Path,
    animation: U9Animation,
    registry: U9NodeRegistry | None,
    models: list[_ModelMetadata],
    all_model_limb_ids: frozenset[int],
) -> dict[str, Any]:
    hints = _parse_source_hints(animation.source_name)
    part_ids = frozenset(animation.part_ids)
    model_track_ids = part_ids & all_model_limb_ids
    authoring_only_ids = part_ids - all_model_limb_ids
    part_names = {part.part_id: part.name for part in animation.parts}

    full_candidates = [
        model
        for model in models
        if model_track_ids and model_track_ids.issubset(model.limb_ids)
    ]
    best_match_count = len(model_track_ids) if full_candidates else 0
    candidates = full_candidates
    candidate_status = "full-structural" if full_candidates else "none"
    if not full_candidates and model_track_ids and models:
        scores = [(len(model_track_ids & model.limb_ids), model) for model in models]
        best_match_count = max(score for score, _model in scores)
        candidates = [
            model for score, model in scores if score == best_match_count and score > 0
        ]
        candidate_status = "partial-best" if candidates else "none"

    candidate_count = len(candidates)
    if candidate_count == 0:
        ambiguity = "none"
    elif candidate_count == 1:
        ambiguity = "unique"
    elif candidate_count <= 10:
        ambiguity = "limited"
    else:
        ambiguity = "broad"

    source_name_candidates = [
        model
        for model in candidates
        if any(_name_matches_actor_hint(name, hints.actor) for name in model.names)
    ]
    if candidate_status == "full-structural":
        candidate_basis = "all clip tracks known to occur in shipped models are present"
    elif candidate_status == "partial-best":
        candidate_basis = (
            "maximum part-ID overlap; no shipped model contains every model-used track"
        )
    else:
        candidate_basis = "no registry-backed structural model candidate"

    candidate_records = [
        _candidate_model_record(model, model_track_ids, part_names)
        for model in candidates
    ]
    source_name_ids = {model.model_id for model in source_name_candidates}
    row: dict[str, Any] = {
        "animation_archive": str(animation_path),
        "animation_id": animation.animation_id,
        "animation_label": hints.label,
        "source_path": animation.source_name,
        "source_asset_group": hints.asset_group,
        "source_family": hints.family,
        "source_category": hints.category,
        "source_stem": hints.stem,
        "source_actor_hint": hints.actor,
        "source_actor_hint_basis": hints.actor_basis,
        "action_hint": hints.action,
        "start_frame": animation.start_frame,
        "end_frame": animation.end_frame,
        "frame_count": animation.frame_count,
        "source_fps": animation.source_fps,
        "frame_interval_ms": animation.frame_interval_ms,
        "duration_ms": animation.duration_ms,
        "part_count": len(animation.parts),
        "part_ids": list(animation.part_ids),
        "part_names": [part.name for part in animation.parts],
        "suffix_count": len(animation.suffixes),
        "suffix_values": [suffix.values for suffix in animation.suffixes],
        "model_track_count": len(model_track_ids),
        "model_track_ids": sorted(model_track_ids),
        "authoring_only_track_count": len(authoring_only_ids),
        "authoring_only_track_ids": sorted(authoring_only_ids),
        "authoring_only_track_names": [
            part_names[node_id] for node_id in sorted(authoring_only_ids)
        ],
        "candidate_status": candidate_status,
        "candidate_basis": candidate_basis,
        "candidate_ambiguity": ambiguity,
        "full_structural_candidate_count": len(full_candidates),
        "candidate_model_count": candidate_count,
        "candidate_model_ids": [model.model_id for model in candidates],
        "candidate_named_models": _named_model_strings(candidates),
        "candidate_models": candidate_records,
        "best_match_part_count": best_match_count,
        "best_match_ratio": (
            round(best_match_count / len(model_track_ids), 6)
            if model_track_ids
            else 0.0
        ),
        "source_name_candidate_count": len(source_name_candidates),
        "source_name_candidate_models": [
            record
            for record in candidate_records
            if record["model_id"] in source_name_ids
        ],
    }
    row.update(_registry_fields(animation, registry))
    row.update(_ghidra_fields(candidate_status, candidate_count))
    return row


def build_animation_model_report(
    animation_file: str | Path,
    *,
    animation_id: int | None = None,
    sappear_path: str | Path | None = None,
    registry_path: str | Path | None = None,
    types_path: str | Path | None = None,
    typenames_path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Join animation names/tracks to registry-backed structural model candidates."""
    animation_path = _required_file(animation_file, "anim.flx")
    directory = animation_path.parent
    warnings: list[str] = []
    try:
        animations = U9Animations.from_file(animation_path)
        if animation_id is None:
            clips = animations.animations()
        else:
            clip = animations.animation(animation_id)
            if clip is None:
                raise U9AnimationModelReportError(
                    f"animation ID {animation_id} is an unused anim.flx slot"
                )
            clips = [clip]
    except (OSError, U9AnimationError) as error:
        raise U9AnimationModelReportError(
            f"could not read anim.flx at {animation_path}: {error}"
        ) from error

    registry: U9NodeRegistry | None = None
    registry_file = _optional_companion(directory, registry_path, "registry.txt")
    if registry_file is None:
        warnings.append("registry.txt not found; node-name validation is unavailable")
    else:
        try:
            registry = U9NodeRegistry.from_file(registry_file)
        except U9NodeRegistryError as error:
            warnings.append(str(error))

    types, typenames, helper_warnings = _load_type_helpers(
        directory, types_path, typenames_path
    )
    warnings.extend(helper_warnings)

    model_file = _optional_companion(directory, sappear_path, "sappear.flx")
    models: list[_ModelMetadata] = []
    if model_file is None:
        warnings.append(
            "sappear.flx not found; structural model candidates are unavailable"
        )
    else:
        model_rows, model_warnings = _read_model_metadata(model_file, types, typenames)
        models.extend(model_rows)
        warnings.extend(model_warnings)

    all_model_limb_ids = frozenset(
        node_id for model in models for node_id in model.limb_ids
    )
    rows = [
        _animation_report_row(
            animation_path,
            animation,
            registry,
            models,
            all_model_limb_ids,
        )
        for animation in clips
    ]
    return rows, warnings
