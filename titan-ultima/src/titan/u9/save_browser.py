"""U9 save browser snapshots, searchable views and preserving offline reports."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from titan.u9.integrity import (
    IntegrityReport,
    check_save,
    check_save_archive,
    render_integrity_report,
    resolve_u9_save_directories,
)
from titan.u9.npc import U9Npcs, U9NpcError, RECORD_SIZE, LIVE_RECORD_COUNT
from titan.u9.savegame import U9SaveArchive, U9SaveError, U9StartDat
from titan.u9.save_backup import next_u9_save_output, validate_u9_save_output
from titan.u9.save_wording import (
    clean_u9_browser_text,
    describe_u9_browser_map,
    describe_u9_save_integrity,
    load_u9_save_wording,
    render_u9_plain_integrity,
)

U9_SAVE_BROWSER_OUTPUT = Path("titan-out/u9_save_browse_export")
U9_SAVE_BROWSER_VIEWS = {
    "members": "Archive members",
    "maps": "Saved maps",
    "npcs": "Named NPC state",
    "processes": "Saved activities",
    "references": "Object-link evidence",
}
SAVE_ARCHIVE_RE = re.compile(r"^u9game(\d+).*\.sav$", re.IGNORECASE)


@dataclass
class U9SaveBrowserSession:
    """One independently checked source; changing selection creates a new session."""

    source: Path
    save_directory: Path
    report: IntegrityReport
    archive: U9SaveArchive | None
    output: Path
    static_directory: Path | None
    fixed_reference_directory: Path | None
    requested_slot: int | None = None

    @property
    def sources(self) -> tuple[Path, ...]:
        """All paths that reports, backups and extractions must preserve."""
        return tuple(
            path
            for path in (
                self.source,
                self.static_directory,
                self.fixed_reference_directory,
            )
            if path is not None
        )


def discover_u9_save_archives(target: Path) -> list[dict[str, Any]]:
    """List this folder's archives; damaged saves remain selectable for inspection."""
    directory, _ = resolve_u9_save_directories(target)
    rows: list[dict[str, Any]] = []
    if not directory.is_dir():
        return rows
    selected = None
    try:
        selected = U9StartDat.from_file(directory / "start.dat").slot
    except (OSError, U9SaveError):
        pass
    for path in directory.iterdir():
        match = SAVE_ARCHIVE_RE.fullmatch(path.name)
        if not match or not path.is_file():
            continue
        slot = int(match[1])
        row = {
            "slot": slot,
            "path": str(path),
            "description": "Unreadable archive",
            "selected": slot == selected
            and path.name.casefold() == f"u9game{slot}.sav",
            "bytes": path.stat().st_size,
            "map_number": None,
            "map_name": "Unknown",
        }
        try:
            archive = U9SaveArchive.from_file(path)
            row.update(
                description=clean_u9_browser_text(archive.header.description),
                map_number=archive.header.header_map,
                map_name=describe_u9_browser_map(archive.header.header_map)[
                    "display_name"
                ],
                day=archive.header.day,
                time=archive.header.time,
            )
        except (OSError, U9SaveError) as error:
            row["read_error"] = str(error)
        rows.append(row)
    return sorted(rows, key=lambda row: (row["slot"], row["path"].casefold()))


def open_u9_save_browser_session(
    source: Path,
    *,
    slot: int | None = None,
    static_directory: Path | None = None,
    fixed_reference_directory: Path | None = None,
    output: Path = U9_SAVE_BROWSER_OUTPUT,
) -> U9SaveBrowserSession:
    """A file means archive-only; a folder means the selected working save."""
    archive_source = source.suffix.casefold() == ".sav" and not source.is_dir()
    directory, default_static = resolve_u9_save_directories(
        source.parent if archive_source else source
    )
    static = static_directory or default_static
    if archive_source:
        if slot is not None:
            raise ValueError(
                "U9 save browser: --slot applies to a folder, not an explicit archive"
            )
        report = check_save_archive(
            source,
            static_directory=static,
            fixed_reference_directory=fixed_reference_directory,
        )
    else:
        report = check_save(
            source,
            slot=slot,
            static_directory=static,
            fixed_reference_directory=fixed_reference_directory,
        )
    archive = None
    if report.archive:
        try:
            archive = U9SaveArchive.from_file(report.archive)
        except (OSError, U9SaveError):
            pass  # the report retains the exact parse/read failure
    return U9SaveBrowserSession(
        source,
        directory,
        report,
        archive,
        output,
        static,
        fixed_reference_directory,
        slot,
    )


def describe_u9_save_browser_view(
    session: U9SaveBrowserSession, view: str
) -> list[dict[str, Any]]:
    """Reuse Titan readers for archive members, map state, NPCs and activity evidence."""
    if view not in U9_SAVE_BROWSER_VIEWS:
        raise ValueError(f"U9 save browser: unknown view {view}")
    archive = session.archive
    if archive is None:
        return []
    if view == "members":
        return [
            {
                "name": member.name,
                "bytes": len(member.data),
                "offset": member.offset,
                "map_number": member.map_number,
                "sha256": hashlib.sha256(member.data).hexdigest(),
            }
            for member in (
                archive.screenshot,
                archive.processes,
                archive.diary,
                *archive.nonfixed,
            )
        ]
    if view == "maps":
        return [
            {
                **describe_u9_browser_map(member.map_number),
                "bytes": len(member.data),
                "findings": sorted(
                    {
                        f"{f.check_id}/{f.severity}"
                        for f in session.report.findings
                        if member.map_number in cast(list[int], f.details["maps"])
                    }
                ),
            }
            for member in archive.nonfixed
            if member.map_number is not None
        ]
    artifacts = cast(dict[str, dict[str, Any]], session.report.to_dict()["artifacts"])
    process_data = artifacts.get("archive/processes.dat", {})
    if view == "processes":
        records = list(process_data.get("decoded_following_processes", []))
        first = process_data.get("first_process")
        return ([first] if isinstance(first, dict) else []) + records
    if view == "references":
        return [
            record
            for finding in session.report.findings
            for record in cast(
                list[dict[str, Any]], finding.details.get("target_records", [])
            )
        ]
    # The version-8 prefix's 512 NPC records follow its two words and 1024-byte
    # global state block. A deterministic table boundary must have validated it.
    if "reference_table_offset" not in process_data:
        raise ValueError(
            "U9 save browser: NPC state unavailable because saved state could not be validated"
        )
    offset = 8 + 1024
    try:
        table = U9Npcs(
            archive.processes.data[offset : offset + LIVE_RECORD_COUNT * RECORD_SIZE]
        )
    except U9NpcError as error:
        raise ValueError(f"U9 save browser: NPC state unavailable: {error}") from error
    return [
        {
            "npc_id": npc.index,
            "name": clean_u9_browser_text(npc.name),
            "map_number": npc.region,
            "map_name": describe_u9_browser_map(npc.region)["display_name"],
            "position": list(npc.position),
            "health": npc.health_current,
            "scale": list(npc.scale),
            "state_flags": int(npc.state_flags),
        }
        for npc in table
        if npc.name or npc.is_slot_used
    ]


def filter_u9_save_browser_rows(
    rows: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    """Search player labels or exact numeric data without changing source order."""
    words = query.casefold().split()
    return [
        row
        for row in rows
        if all(word in json.dumps(row, ensure_ascii=False).casefold() for word in words)
    ]


def format_u9_save_browser_rows(rows: list[dict[str, Any]], output_format: str) -> str:
    """Export complete view data as JSON or CSV with nested fields retained."""
    if output_format == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if output_format != "csv":
        raise ValueError("U9 save browser: view format must be json or csv")
    stream = io.StringIO(newline="")
    columns = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list, tuple))
                else value
                for key, value in row.items()
            }
        )
    return stream.getvalue()


def extract_u9_save_browser_archive(session: U9SaveBrowserSession) -> Path:
    """Extract raw members into a new inspection folder, never the working folder."""
    if session.archive is None:
        raise ValueError("U9 save browser: archive cannot be extracted")
    validate_u9_save_output(session.output, session.save_directory, session.sources)
    folder = next_u9_save_output(session.output, "extracted_save")
    folder.mkdir(parents=True)
    for member in (
        session.archive.processes,
        session.archive.diary,
        *session.archive.nonfixed,
    ):
        (folder / member.name).write_bytes(member.data)
    (folder / "screenshot.bin").write_bytes(session.archive.screenshot.data)
    return folder


def build_u9_save_browser_report(session: U9SaveBrowserSession) -> dict[str, Any]:
    """Combine the complete technical report and portable player presentation."""
    views, errors = {}, {}
    for view in U9_SAVE_BROWSER_VIEWS:
        try:
            views[view] = describe_u9_save_browser_view(session, view)
        except ValueError as error:
            errors[view] = str(error)
    return {
        "schema_version": 1,
        "source": str(session.source),
        "integrity": session.report.to_dict(),
        "presentation": describe_u9_save_integrity(session.report),
        "views": views,
        "view_errors": errors,
    }


def _u9_save_browser_html(report: dict[str, Any], technical_text: str) -> str:
    plain = report["presentation"]
    summary = plain["summary"]

    def escaped(value: object) -> str:
        return html.escape(str(value), quote=True)

    cards = []
    for card in plain["cards"]:
        findings = [
            finding
            for finding in report["integrity"]["findings"]
            if (finding["check_id"], finding["severity"])
            == (card["check_id"], card["severity"])
        ]
        prefix = "Note: " if card["display_kind"] == "note" else ""
        cards.append(
            f"<article class='finding'><h2>{prefix}{escaped(card['title'])} <small>{escaped(card['key'])}</small></h2>"
            + "".join(
                f"<p><b>What this means:</b> {escaped(meaning)}</p>"
                for meaning in card["meanings"]
            )
            + f"<p><b>What you can do:</b> {escaped(card['what_to_do'])}</p>"
            + f"<p><b>Loading:</b> {escaped(card['load_text'])}</p>"
            + f"<details><summary>Details</summary><pre>{escaped(json.dumps(findings, indent=2, ensure_ascii=False))}</pre></details></article>"
        )
    actions = []
    catalog = load_u9_save_wording()
    for action in plain["actions"]:
        record = catalog["actions"][action]
        actions.append(
            f"<details class='action' data-action='{escaped(action)}'><summary>{escaped(record['label'])}</summary>"
            f"<p>{escaped(record['description'])}</p><p>Use this action in the Titan save browser.</p></details>"
        )
    views = "".join(
        f"<details><summary>{escaped(U9_SAVE_BROWSER_VIEWS[view])}</summary>"
        f"<pre>{escaped(json.dumps(rows, indent=2, ensure_ascii=False))}</pre></details>"
        for view, rows in report["views"].items()
    )
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Titan U9 Save Browser</title>
<style>body{font-family:system-ui,sans-serif;max-width:64rem;margin:2rem auto;padding:0 1rem;background:#f6f4ef;color:#24282b}
article,section{background:white;border:1px solid #d1cec5;border-radius:.5rem;padding:1rem;margin:1rem 0}h2{font-size:1.15rem}
small{font-weight:normal;color:#606060}summary,button{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.85rem}
input{width:95%;padding:.7rem}button,a{margin:.3rem}details{margin:.8rem 0}.action{display:inline-block;border:1px solid #aaa;padding:.5rem}</style>
<h1>Titan U9 Save Browser</h1>"""
        + f"<p>{escaped(report['source'])}</p><section><h2>{escaped(summary['title'])}</h2><p>{escaped(summary['meaning'])}</p><p>{escaped(summary['load_text'])}</p>"
        + "".join(f"<p>{escaped(note)}</p>" for note in plain["notes"])
        + "</section><button id='copy-report'>Copy report</button><span id='copy-status' role='status'></span><a href='integrity.txt' download>Download report</a><a href='browser.json' download>Complete JSON</a>"
        + "".join(actions)
        + "<p><input id='search' aria-label='Filter findings' placeholder='Filter findings by name or check ID'></p>"
        + "".join(cards)
        + views
        + f"<details><summary>Complete technical report</summary><pre id='technical'>{escaped(technical_text)}</pre></details>"
        + """<script>
document.getElementById('search').addEventListener('input', function(){
const query=this.value.toLowerCase();document.querySelectorAll('.finding').forEach(card=>{card.hidden=!card.textContent.toLowerCase().includes(query);});});
document.getElementById('copy-report').addEventListener('click',async function(){
const text=document.getElementById('technical').textContent;const status=document.getElementById('copy-status');
try{await navigator.clipboard.writeText(text);status.textContent='Report copied.';}catch(error){status.textContent='Clipboard unavailable. Use Download report.';}});
</script></html>"""
    )


def export_u9_save_browser_bundle(session: U9SaveBrowserSession) -> Path:
    """Write a new offline HTML/JSON/CSV report bundle, preserving earlier exports."""
    validate_u9_save_output(session.output, session.save_directory, session.sources)
    report = build_u9_save_browser_report(session)
    technical = render_integrity_report(session.report)
    folder = next_u9_save_output(session.output, "save_report")
    folder.mkdir(parents=True)
    (folder / "browser.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    session.report.write_json(folder / "integrity.json")
    (folder / "integrity.txt").write_text(technical + "\n", encoding="utf-8")
    (folder / "summary.txt").write_text(
        render_u9_plain_integrity(report["presentation"]) + "\n", encoding="utf-8"
    )
    for view, rows in report["views"].items():
        for kind in ("json", "csv"):
            (folder / f"{view}.{kind}").write_text(
                format_u9_save_browser_rows(rows, kind), encoding="utf-8"
            )
    (folder / "index.html").write_text(
        _u9_save_browser_html(report, technical), encoding="utf-8"
    )
    return folder
