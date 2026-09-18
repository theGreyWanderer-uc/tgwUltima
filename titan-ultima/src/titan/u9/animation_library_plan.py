"""Plan non-overlapping U9 actor animation libraries from one discovery pass."""

from __future__ import annotations

__all__ = [
    "ANIMATION_LIBRARY_PLAN_SCHEMA",
    "ANIMATION_LIBRARY_PLAN_SCHEMA_VERSION",
    "U9AnimationLibraryPlan",
    "U9AnimationLibraryPlanError",
    "build_animation_library_plan",
    "write_animation_library_plan",
]

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from titan.u9.animation_model_report import (
    U9AnimationModelReportError,
    build_animation_model_report,
)

ANIMATION_LIBRARY_PLAN_SCHEMA = "titan.u9.animation-library-plan"
ANIMATION_LIBRARY_PLAN_SCHEMA_VERSION = 1

_GENERIC_ACTOR_HINTS = {"", "humanoid", "npc", "magic", "ui"}


class U9AnimationLibraryPlanError(Exception):
    """Raised when animation discovery cannot produce a usable library plan."""


@dataclass(frozen=True)
class U9AnimationLibraryPlan:
    """Compact library plan plus optional detailed diagnostics held in memory."""

    document: dict[str, Any]
    diagnostics: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]

    @property
    def library_count(self) -> int:
        """Number of actor/track-signature libraries in the compact plan."""
        return len(self.document["libraries"])


def _safe_library_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return cleaned or "unassigned"


def _track_signature(track_ids: tuple[int, ...]) -> str:
    encoded = ",".join(str(track_id) for track_id in track_ids).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()[:8]


def _animation_category(row: dict[str, Any]) -> str:
    category = str(row.get("source_category") or "").split("/", 1)[0]
    if category:
        return category.casefold()
    motion_name = str(row.get("motion_name") or "")
    tokens = motion_name.split("_")
    return tokens[1].casefold() if len(tokens) > 1 else "other"


def _actor_hint(row: dict[str, Any]) -> str:
    return str(
        row.get("source_actor_hint")
        or row.get("motion_family")
        or row.get("source_family")
        or "unassigned"
    ).casefold()


def _preferred_model_record(
    records: list[dict[str, Any]], actor_hint: str
) -> dict[str, Any]:
    def score(record: dict[str, Any]) -> tuple[int, int]:
        names = [str(name).casefold() for name in record.get("model_names", [])]
        if names and all(name == actor_hint for name in names):
            rank = 0
        elif actor_hint in names:
            rank = 1
        elif any(actor_hint in name for name in names):
            rank = 2
        else:
            rank = 3
        return rank, int(record["model_id"])

    return min(records, key=score)


def _planned_library(
    actor_hint: str,
    track_ids: tuple[int, ...],
    rows: list[dict[str, Any]],
    *,
    actor_group_count: int,
) -> dict[str, Any]:
    signature = _track_signature(track_ids)
    library_id = _safe_library_name(actor_hint)
    if actor_group_count > 1:
        library_id = f"{library_id}-{signature}"

    candidate_statuses = {str(row.get("candidate_status")) for row in rows}
    has_partial_candidates = "partial-best" in candidate_statuses
    candidate_sets = [set(row.get("candidate_model_ids", [])) for row in rows]
    common_candidate_ids = (
        set.intersection(*candidate_sets) if candidate_sets else set()
    )
    candidate_records: dict[int, dict[str, Any]] = {}
    name_matched_ids: set[int] = set()
    for row in rows:
        for record in row.get("candidate_models", []):
            model_id = int(record["model_id"])
            if model_id in common_candidate_ids:
                candidate_records.setdefault(model_id, record)
        name_matched_ids.update(
            int(record["model_id"])
            for record in row.get("source_name_candidate_models", [])
            if int(record["model_id"]) in common_candidate_ids
        )

    if has_partial_candidates:
        recommended_ids = set(common_candidate_ids)
        variant_basis = "best partial structural candidate set; review required"
    elif name_matched_ids:
        anchored_fingerprints = {
            str(candidate_records[model_id]["skeleton_fingerprint"])
            for model_id in name_matched_ids
            if model_id in candidate_records
        }
        recommended_ids = {
            model_id
            for model_id, record in candidate_records.items()
            if str(record["skeleton_fingerprint"]) in anchored_fingerprints
        }
        variant_basis = "actor-name anchors and their exact skeleton variants"
    elif len(common_candidate_ids) == 1:
        recommended_ids = set(common_candidate_ids)
        variant_basis = "single complete structural candidate"
    else:
        recommended_ids = set()
        variant_basis = "no named skeleton anchor or unique structural candidate"

    selected_by_fingerprint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for model_id in sorted(recommended_ids):
        record = candidate_records.get(model_id)
        if record is not None:
            selected_by_fingerprint[str(record["skeleton_fingerprint"])].append(record)

    skeleton_groups = []
    representative_model_ids = []
    for fingerprint, records in sorted(selected_by_fingerprint.items()):
        anchor_records = [
            record for record in records if int(record["model_id"]) in name_matched_ids
        ]
        representative = _preferred_model_record(anchor_records or records, actor_hint)
        representative_model_ids.append(int(representative["model_id"]))
        skeleton_groups.append(
            {
                "skeleton_fingerprint": fingerprint,
                "representative_model_id": int(representative["model_id"]),
                "actor_anchor_model_ids": sorted(
                    int(record["model_id"]) for record in anchor_records
                ),
                "model_variant_ids": sorted(
                    int(record["model_id"]) for record in records
                ),
                "named_models": [
                    {
                        "model_id": int(record["model_id"]),
                        "names": list(record.get("model_names", [])),
                    }
                    for record in sorted(
                        records, key=lambda item: int(item["model_id"])
                    )
                ],
            }
        )

    if has_partial_candidates:
        confidence = "partial"
    elif (
        name_matched_ids and recommended_ids and actor_hint not in _GENERIC_ACTOR_HINTS
    ):
        confidence = "strong"
    elif recommended_ids:
        confidence = "limited"
    else:
        confidence = "structural"

    categories = Counter(_animation_category(row) for row in rows)
    animations = [
        {
            "animation_id": int(row["animation_id"]),
            "motion_name": row.get("motion_name"),
            "animation_label": row.get("animation_label"),
            "category": _animation_category(row),
            "action": row.get("action_hint"),
            "duration_ms": int(row.get("duration_ms") or 0),
            "track_count": int(row.get("part_count") or 0),
            "model_track_count": int(row.get("model_track_count") or 0),
            "authoring_only_track_count": int(
                row.get("authoring_only_track_count") or 0
            ),
            "event_count": int(row.get("event_count") or 0),
            "actor_hint_basis": row.get("source_actor_hint_basis"),
        }
        for row in sorted(rows, key=lambda item: int(item["animation_id"]))
    ]
    return {
        "library_id": library_id,
        "actor_hint": actor_hint,
        "confidence": confidence,
        "runtime_binding_status": "unresolved",
        "track_signature": signature,
        "model_track_ids": list(track_ids),
        "animation_count": len(animations),
        "animations": animations,
        "category_counts": dict(sorted(categories.items())),
        "candidate_statuses": sorted(candidate_statuses),
        "common_structural_candidate_count": len(common_candidate_ids),
        "recommended_model_ids": sorted(recommended_ids),
        "representative_model_ids": sorted(representative_model_ids),
        "model_selection_basis": variant_basis,
        "skeleton_groups": skeleton_groups,
        "requires_model_review": has_partial_candidates or not bool(recommended_ids),
    }


def build_animation_library_plan(
    animation_file: str | Path,
    *,
    sappear_path: str | Path | None = None,
    registry_path: str | Path | None = None,
    types_path: str | Path | None = None,
    typenames_path: str | Path | None = None,
    motion_ids_path: str | Path | None = None,
) -> U9AnimationLibraryPlan:
    """Discover animation families once and return compact and diagnostic views."""
    try:
        rows, warnings = build_animation_model_report(
            animation_file,
            sappear_path=sappear_path,
            registry_path=registry_path,
            types_path=types_path,
            typenames_path=typenames_path,
            motion_ids_path=motion_ids_path,
        )
    except U9AnimationModelReportError as error:
        raise U9AnimationLibraryPlanError(str(error)) from error
    if not rows:
        raise U9AnimationLibraryPlanError(
            "animation library discovery returned no clips"
        )

    grouped: dict[tuple[str, tuple[int, ...]], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        actor_hint = _actor_hint(row)
        track_ids = tuple(int(value) for value in row.get("model_track_ids", []))
        grouped[(actor_hint, track_ids)].append(row)

    actor_group_counts = Counter(actor_hint for actor_hint, _track_ids in grouped)
    libraries = [
        _planned_library(
            actor_hint,
            track_ids,
            group_rows,
            actor_group_count=actor_group_counts[actor_hint],
        )
        for (actor_hint, track_ids), group_rows in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1])
        )
    ]
    confidence_counts = Counter(str(library["confidence"]) for library in libraries)
    document: dict[str, Any] = {
        "schema": ANIMATION_LIBRARY_PLAN_SCHEMA,
        "schema_version": ANIMATION_LIBRARY_PLAN_SCHEMA_VERSION,
        "selection_policy": {
            "library_grouping": "actor hint plus exact model-used track ID signature",
            "model_grouping": "ordered limb hierarchy and rest-transform fingerprint",
            "model_approval_policy": (
                "require an actor-name skeleton anchor or one unique complete candidate"
            ),
            "runtime_binding_is_not_inferred": True,
        },
        "summary": {
            "animation_count": len(rows),
            "library_count": len(libraries),
            "actor_hint_count": len(actor_group_counts),
            "track_signature_count": len({key[1] for key in grouped}),
            "confidence_counts": dict(sorted(confidence_counts.items())),
            "auto_export_library_count": sum(
                not bool(library["requires_model_review"]) for library in libraries
            ),
            "review_library_count": sum(
                bool(library["requires_model_review"]) for library in libraries
            ),
        },
        "libraries": libraries,
    }
    return U9AnimationLibraryPlan(
        document=document,
        diagnostics=tuple(rows),
        warnings=tuple(warnings),
    )


def write_animation_library_plan(
    plan: U9AnimationLibraryPlan, output_path: str | Path
) -> Path:
    """Write the compact versioned animation library plan as JSON."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(plan.document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output
