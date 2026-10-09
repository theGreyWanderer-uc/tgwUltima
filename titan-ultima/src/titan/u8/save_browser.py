"""Read-only U8 save browser views, named NPC state and preserving exports."""

from __future__ import annotations

import csv
import html
import io
import json
import re
from pathlib import Path
from typing import Any

from titan.u8.flags import U8FlagSymbols
from titan.u8.flags_report import format_u8_flags_report
from titan.u8.map_item_report import format_u8_map_item_report
from titan.u8.native_state_report import (
    format_u8_avatar_report,
    format_u8_gumps_report,
    format_u8_kernel_report,
)
from titan.u8.npc_names import describe_u8_npc_identity
from titan.u8.save_state import U8SaveSnapshot, describe_u8_save_snapshot
from titan.u8.state_report import format_u8_itemcach_report, format_u8_npcdata_report

U8_SAVE_BROWSER_OUTPUT = Path("titan-out/u8_save_browse_export")
U8_SAVE_BROWSER_VIEWS = {
    "entries": "Save entries",
    "avatar": "Avatar extension state",
    "npcs": "Named NPC state",
    "items": "Cached items",
    "regions": "Cache regions",
    "flags": "Global flags",
    "maps": "Stored NONFIXED maps",
    "map_items": "Stored map records",
    "gumps": "Container gumps",
    "rects": "Gump rectangles",
    "kernel": "Kernel process inventory",
    "process": "Kernel process details",
}


def describe_u8_save_browser_view(
    snapshot: U8SaveSnapshot,
    view: str,
    *,
    all_slots: bool = False,
    index: int | None = None,
    width: int = 1,
    map_id: int | None = None,
    slot: int | None = None,
    symbols: U8FlagSymbols | None = None,
    names: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Reuse verified parsers; missing or invalid state stays unavailable, except zero flags."""
    if view not in U8_SAVE_BROWSER_VIEWS:
        raise ValueError(f"U8 save browser: unknown view {view!r}")
    row_key = "rows"
    if view == "entries":
        overview = describe_u8_save_snapshot(snapshot)
        report = {"entry_count": len(snapshot.entries), "rows": overview["entries"]}
    elif view == "avatar" and snapshot.avatar is not None:
        report = json.loads(
            format_u8_avatar_report(snapshot.avatar, output_format="json")
        )
    elif view == "npcs" and snapshot.npc_data is not None:
        report = json.loads(
            format_u8_npcdata_report(
                snapshot.npc_data,
                item_cache=snapshot.item_cache,
                all_slots=all_slots,
                output_format="json",
            )
        )
        row_key = "npcs"
        for row in report[row_key]:
            row.update(
                describe_u8_npc_identity(row, labels=names, avatar=snapshot.avatar)
            )
    elif view in {"items", "regions"} and snapshot.item_cache is not None:
        report = json.loads(
            format_u8_itemcach_report(
                snapshot.item_cache,
                view=view,
                all_slots=all_slots,
                output_format="json",
            )
        )
        row_key = view
    elif view == "flags" and snapshot.global_flags is not None:
        report = json.loads(
            format_u8_flags_report(
                snapshot.global_flags,
                index=index,
                width=width,
                all_bits=all_slots if index is None and symbols is None else False,
                symbols=symbols if index is None else None,
                output_format="json",
            )
        )
        row_key = "flags"
    elif view in {"maps", "map_items"} and snapshot.nonfixed is not None:
        report = json.loads(
            format_u8_map_item_report(
                snapshot.nonfixed,
                map_id=map_id,
                view="summary" if view == "maps" else "items",
                output_format="json",
            )
        )
        row_key = "maps" if view == "maps" else "items"
        if view == "maps" and not all_slots:
            report[row_key] = [row for row in report[row_key] if row["record_count"]]
    elif view in {"gumps", "rects"} and snapshot.gumps is not None:
        report = json.loads(
            format_u8_gumps_report(
                snapshot.gumps,
                view="containers" if view == "gumps" else "rects",
                output_format="json",
            )
        )
    elif view in {"kernel", "process"} and snapshot.kernel is not None:
        report = json.loads(
            format_u8_kernel_report(
                snapshot.kernel,
                view="summary" if view == "kernel" else "processes",
                slot=slot if view == "process" else None,
                output_format="json",
            )
        )
    else:
        raise ValueError(
            f"U8 save browser: {U8_SAVE_BROWSER_VIEWS[view]} unavailable; check entry coverage"
        )
    rows = report.pop(row_key)
    return {
        "view": view,
        "source": str(snapshot.source),
        "metadata": report,
        "rows": rows,
    }


def filter_u8_save_browser_rows(
    rows: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Search display fields case-insensitively, excluding bulk raw hexadecimal payloads."""
    query = query.strip().casefold()
    if not query:
        return rows
    return [
        row
        for row in rows
        if query
        in json.dumps(
            {
                key: value
                for key, value in row.items()
                if key
                not in {"raw", "raw_hex", "object_hex", "payload_hex", "unknown_0c_1a"}
            },
            ensure_ascii=False,
        ).casefold()
    ]


def format_u8_save_browser_view(report: dict[str, Any], output_format: str) -> str:
    """Render exactly the selected rows, with nested CSV values encoded as JSON."""
    if output_format == "json":
        return json.dumps(report, indent=2) + "\n"
    if output_format == "text":
        return (
            f"U8 save browser: {report['view']} — {report['source']}\n"
            + json.dumps(report, indent=2)
            + "\n"
        )
    if output_format != "csv":
        raise ValueError("U8 save browser: format must be text, json or csv")
    rows = report["rows"]
    fields = list(dict.fromkeys(key for row in rows for key in row)) or ["index"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value)
                if isinstance(value, (dict, list, tuple))
                else value
                for key, value in row.items()
            }
        )
    return stream.getvalue()


def next_u8_save_browser_export(output: Path, stem: str, suffix: str = "") -> Path:
    """Choose a new export name; actual writers still create files exclusively."""
    path = output / f"{stem}{suffix}"
    number = 1
    while path.exists():
        number += 1
        path = output / f"{stem}_{number:03d}{suffix}"
    return path


def validate_u8_save_browser_output(
    snapshot: U8SaveSnapshot, output: Path, sources: tuple[Path, ...] = ()
) -> None:
    """Reject exports inside live GAMEDAT or onto any input, including symlink targets."""
    target = output.resolve()
    source = snapshot.source.resolve()
    if snapshot.source_kind == "gamedat_directory" and (
        target == source or source in target.parents
    ):
        raise ValueError("U8 save browser: export outside the source GAMEDAT directory")
    if target in {
        path.resolve() for path in (*snapshot.source_files, *sources, snapshot.source)
    }:
        raise ValueError("U8 save browser: output must differ from input files")


def extract_u8_save_browser_entry(
    snapshot: U8SaveSnapshot, name: str, output: Path
) -> Path:
    """Extract captured bytes under a safe generated filename; never reopen the source."""
    if name not in snapshot.entries:
        raise ValueError("U8 save browser: entry is absent")
    validate_u8_save_browser_output(snapshot, output)
    number = sorted(snapshot.entries).index(name)
    safe_name = f"entry_{number:03d}_" + re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:120]
    path = next_u8_save_browser_export(output, safe_name)
    validate_u8_save_browser_output(snapshot, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(snapshot.entries[name])
    return path


def export_u8_save_browser_bundle(
    snapshot: U8SaveSnapshot,
    output: Path,
    *,
    symbols: U8FlagSymbols | None = None,
    names: dict[int, str] | None = None,
    sources: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Write an offline overview and verified data views into a new directory only."""
    validate_u8_save_browser_output(snapshot, output, sources)
    if output.exists():
        raise ValueError("U8 save browser: bundle output must be a new directory")
    overview = describe_u8_save_snapshot(snapshot)
    reports: dict[str, str] = {"overview.json": json.dumps(overview, indent=2) + "\n"}
    for view in U8_SAVE_BROWSER_VIEWS:
        if view in {"map_items", "process"}:
            continue
        try:
            report = describe_u8_save_browser_view(
                snapshot, view, symbols=symbols, names=names
            )
        except ValueError:
            continue
        reports[f"{view}.json"] = format_u8_save_browser_view(report, "json")
        reports[f"{view}.csv"] = format_u8_save_browser_view(report, "csv")
    links = "".join(
        f'<li><a href="{html.escape(name)}">{html.escape(name)}</a></li>'
        for name in reports
    )
    summary = {key: value for key, value in overview.items() if key != "entries"}
    reports["index.html"] = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Ultima VIII save overview</title><style>body{font:16px/1.5 system-ui;max-width:1100px;margin:2rem auto;padding:1rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body><h1>Ultima VIII save overview</h1><p>'
        + html.escape(str(snapshot.source))
        + "</p><p>Native state inspection. Kernel coverage is partial; unknown entries remain opaque.</p><ul>"
        + links
        + "</ul><h2>Save state and coverage</h2><pre>"
        + html.escape(json.dumps(summary, indent=2))
        + "</pre></body></html>\n"
    )
    output.mkdir(parents=True, exist_ok=False)
    for name, content in reports.items():
        with (output / name).open("x", encoding="utf-8", newline="") as stream:
            stream.write(content)
    return {
        "source": str(snapshot.source),
        "output": str(output),
        "file_count": len(reports),
        "views": sorted(name[:-5] for name in reports if name.endswith(".json")),
    }
