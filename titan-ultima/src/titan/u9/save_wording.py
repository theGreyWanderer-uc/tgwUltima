"""Portable player wording for U9 save findings; only plain {name} substitution."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, cast

from titan.u9.integrity import IntegrityReport, SEVERITY_RANK

RESOURCE_DIRECTORY = Path(__file__).with_name("resources")
PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z_0-9]*)\}")
LOAD_POLICIES = {"try_after_backup", "review_first", "do_not_load", "not_applicable"}


def validate_u9_save_wording(catalog: Mapping[str, Any]) -> None:
    """Validate portable keys, actions and placeholders before presenting advice."""
    if catalog.get("schema_version") != 1:
        raise ValueError("U9 save wording: unsupported schema version")
    actions = catalog["actions"]
    try_load = actions["try_load"]
    if (
        try_load.get("requires_explicit_activation") is not True
        or try_load.get("launch_on_activation_allowed") is not True
        or try_load.get("automatic_launch_allowed") is not False
        or set(try_load.get("allowed_overall_results", [])) != {"PASS", "WARN"}
    ):
        raise ValueError("U9 save wording: unsafe try_load activation contract")
    for key, entry in {
        **catalog["findings"],
        **catalog["summaries"],
        "unknown": catalog["unknown_finding"],
    }.items():
        if key in catalog["findings"] and not re.fullmatch(
            r"[A-Z]{3}\d{2}/(?:PASS|INFO|WARN|ERROR|FATAL)", key
        ):
            raise ValueError(f"U9 save wording: invalid finding key {key}")
        if entry["load_policy"] not in LOAD_POLICIES:
            raise ValueError(f"U9 save wording: invalid loading policy for {key}")
        if not isinstance(entry.get("affects_verdict", True), bool):
            raise ValueError(f"U9 save wording: invalid verdict flag for {key}")
        if entry.get("display_kind", "finding") not in {"finding", "note"}:
            raise ValueError(f"U9 save wording: invalid display kind for {key}")
        if any(action not in actions for action in entry["actions"]):
            raise ValueError(f"U9 save wording: unknown action for {key}")
        found: set[str] = set()
        for name in ("title", "meaning", "what_to_do", "load_text"):
            value = entry.get(name, "")
            found.update(PLACEHOLDER_RE.findall(value))
            remainder = PLACEHOLDER_RE.sub("", value)
            if "{" in remainder or "}" in remainder:
                raise ValueError(
                    f"U9 save wording: only plain placeholders allowed for {key}"
                )
        if found != set(entry.get("placeholders", [])):
            raise ValueError(
                f"U9 save wording: placeholder declaration mismatch for {key}"
            )
    if set(catalog["summaries"]) != {
        "PASS",
        "WARN",
        "ERROR",
        "FATAL",
        "NO_SAVE_SELECTED",
    }:
        raise ValueError("U9 save wording: incomplete overall summaries")


@lru_cache(maxsize=1)
def load_u9_save_wording() -> dict[str, Any]:
    """Load the shipped JSON wording contract, also consumable by C#."""
    catalog = json.loads(
        (RESOURCE_DIRECTORY / "save_wording.json").read_text(encoding="utf-8")
    )
    validate_u9_save_wording(catalog)
    return catalog


@lru_cache(maxsize=1)
def load_u9_region_catalogue() -> dict[str, Any]:
    """Load map names and explicitly qualified development/test classification."""
    return json.loads(
        (RESOURCE_DIRECTORY / "region_catalogue.json").read_text(encoding="utf-8")
    )


def describe_u9_browser_map(map_number: int) -> dict[str, Any]:
    """Display a known map name, retaining its numeric identity and uncertainty."""
    record = load_u9_region_catalogue()["maps"].get(str(map_number))
    if record is None:
        return {
            "map_number": map_number,
            "name": f"Map {map_number}",
            "category": "unknown",
            "development": False,
            "display_name": f"Map {map_number} (unidentified)",
        }
    suffix = (
        " (development/test)"
        if record["development"]
        else (
            " (classification uncertain)" if record["category"] == "unresolved" else ""
        )
    )
    return {
        "map_number": map_number,
        **record,
        "display_name": f"{record.get('player_name', record['name'])} [map {map_number}]{suffix}",
    }


def clean_u9_browser_text(value: object) -> str:
    """Remove terminal control characters from archive/player-supplied text."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value))


def fill_u9_save_wording(template: str, details: Mapping[str, Any]) -> str:
    """Replace named tokens only; never evaluate Python/C# format expressions."""

    def replacement(match: re.Match[str]) -> str:
        name = match[1]
        if name not in details:
            raise ValueError(f"U9 save wording: missing detail {name}")
        value = details[name]
        if name == "maps":
            return (
                ", ".join(
                    describe_u9_browser_map(number)["display_name"] for number in value
                )
                or "not specified"
            )
        return clean_u9_browser_text("unknown" if value is None else value)

    return PLACEHOLDER_RE.sub(replacement, template)


def describe_u9_save_integrity(report: IntegrityReport) -> dict[str, Any]:
    """Build plain finding cards; loading actions always respect the overall result."""
    catalog = load_u9_save_wording()
    result = "NO_SAVE_SELECTED" if report.no_save_selected else report.overall
    summary = {"result": result, **catalog["summaries"][result]}
    groups: dict[tuple[str, str], list[Any]] = {}
    if not report.no_save_selected:
        for finding in cast(list[dict[str, Any]], report.to_dict()["findings"]):
            if finding["severity"] == "PASS" or (
                report.self_reference and finding["check_id"] == "LAY01"
            ):
                continue
            groups.setdefault((finding["check_id"], finding["severity"]), []).append(
                finding
            )
    cards = []
    for (check_id, severity), findings in sorted(
        groups.items(), key=lambda item: (-SEVERITY_RANK[item[0][1]], item[0][0])
    ):
        key = f"{check_id}/{severity}"
        entry = catalog["findings"].get(key, catalog["unknown_finding"])
        contexts = [finding["details"] for finding in findings]
        meanings = list(
            dict.fromkeys(
                fill_u9_save_wording(entry["meaning"], context) for context in contexts
            )
        )
        actions = [
            action
            for action in entry["actions"]
            if action != "try_load"
            or report.overall
            in catalog["actions"]["try_load"]["allowed_overall_results"]
        ]
        blocks_loading = report.overall in ("ERROR", "FATAL")
        affects_verdict = any(finding["affects_verdict"] for finding in findings)
        cards.append(
            {
                "key": key,
                "check_id": check_id,
                "severity": severity,
                "affects_verdict": affects_verdict,
                "display_kind": "finding" if affects_verdict else "note",
                "title": entry["title"],
                "meanings": meanings,
                "what_to_do": summary["what_to_do"]
                if blocks_loading and entry["load_policy"] != "do_not_load"
                else fill_u9_save_wording(entry["what_to_do"], contexts[0]),
                "finding_load_policy": entry["load_policy"],
                "load_policy": summary["load_policy"]
                if blocks_loading
                else entry["load_policy"],
                "load_text": summary["load_text"]
                if blocks_loading
                else entry["load_text"],
                "actions": actions,
                "contexts": contexts,
                "paths": sorted(
                    {finding["path"] for finding in findings if finding["path"]}
                ),
            }
        )
    actions = list(
        dict.fromkeys(
            [
                *summary["actions"],
                *(action for card in cards for action in card["actions"]),
            ]
        )
    )
    if report.overall in ("ERROR", "FATAL"):
        actions = [action for action in actions if action != "try_load"]
    return {
        "schema_version": 1,
        "summary": summary,
        "cards": cards,
        "actions": actions,
        "action_labels": {key: catalog["actions"][key]["label"] for key in actions},
        "axes": {}
        if report.no_save_selected
        else {
            axis: report.verdict(axis)
            for axis in ("custody", "structure", "compatibility")
        },
        "notes": [catalog["self_reference_note"]] if report.self_reference else [],
    }


def render_u9_plain_integrity(plain: Mapping[str, Any]) -> str:
    """Render shared player wording with the technical report kept in Details."""
    summary = plain["summary"]
    lines = [summary["title"], summary["meaning"], summary["load_text"]]
    for note in plain["notes"]:
        lines.append(note)
    for card in plain["cards"]:
        prefix = "Note: " if card["display_kind"] == "note" else ""
        lines.extend(
            (
                "",
                f"{prefix}{card['title']} ({card['key']})",
                *(f"  What this means: {meaning}" for meaning in card["meanings"]),
                f"  What you can do: {card['what_to_do']}",
                f"  Loading: {card['load_text']}",
            )
        )
    return "\n".join(lines)
