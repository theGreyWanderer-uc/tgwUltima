"""Offline HTML views of joined U8 NPC animation data and relative PNG assets."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from typing import Any

_STYLE = """
:root{color-scheme:dark}body{font:16px/1.5 system-ui,sans-serif;margin:0;background:#171b21;color:#e7e9ec}
main{max-width:1400px;margin:auto;padding:28px}a{color:#9fd5ff}h1{margin-bottom:4px}
.intro{color:#b9c2ce}.cards{display:flex;gap:16px;flex-wrap:wrap}.card,details{background:#232a34;padding:16px;border:1px solid #3d4654;border-radius:8px;margin:12px 0}
summary{cursor:pointer;font-weight:600}table{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0}
th,td{text-align:left;vertical-align:top;border-bottom:1px solid #3d4654;padding:8px;white-space:nowrap}
th{background:#303a48}tbody tr:hover{background:#303a48}.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}
.sheet{display:inline-block;margin:12px 12px 4px 0}.sheet img{display:block;max-width:100%;height:auto;border:1px solid #596575}
.issue{color:#ffd39c}caption{text-align:left;color:#b9c2ce}small{color:#b9c2ce}
"""


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _document(title: str, content: str) -> str:
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_escape(title)}</title><style>{_STYLE}</style></head><body><main>{content}</main></body></html>\n'


def _table(rows: list[dict[str, Any]], fields: list[tuple[str, str]]) -> str:
    headings = "".join(f'<th scope="col">{_escape(label)}</th>' for _, label in fields)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{_escape(row.get(key, ''))}</td>" for key, _ in fields)
        + "</tr>"
        for row in rows
    )
    return f'<div class="scroll"><table><thead><tr>{headings}</tr></thead><tbody>{body}</tbody></table></div>'


def render_npc_animation_page(
    state: dict[str, Any], shape: dict[str, Any], rows: list[dict[str, Any]]
) -> str:
    """Render a named NPC's state, every node/frame row and shared contact sheets."""
    title = f"NPC {state['npc_id']} — {state['npc_label']}"
    content = f'<nav><a href="../index.html">All NPCs</a> · <a href="../master.csv">Master CSV</a> · <a href="../npc_state.json">Full NPC state</a></nav><h1>{_escape(title)}</h1>'
    content += f'<p class="intro">Shape {_escape(state["item_shape"])} · shape class: {_escape(state["class_label"] or "unlabelled")}<br>NPC usecode class: {_escape(state["npc_usecode_class"])} · {_escape(state["npc_usecode_name"] or "unlabelled")} · name source: {_escape(state["label_source"])}<br>Friendly action names describe animation actions. Reused sprite frames retain their action, direction and step.</p>'
    content += (
        '<div class="cards">'
        + "".join(
            f'<div class="card"><strong>{_escape(label)}</strong><br>{_escape(state[key])}</div>'
            for key, label in (
                ("last_action", "Saved action"),
                ("direction", "Saved direction"),
                ("animation_step", "Saved step"),
                ("item_frame", "Saved sprite frame"),
                ("slot_membership", "Cache membership"),
            )
        )
        + "</div>"
    )
    content += (
        "<details><summary>Complete saved NPC and item state</summary><pre>"
        + _escape(json.dumps(state, indent=2))
        + "</pre></details>"
    )
    metadata = shape["metadata"]
    if metadata is not None:
        properties = {
            key: value
            for key, value in metadata.items()
            if key not in {"frames", "animations"}
        }
        content += (
            "<details><summary>Shape properties and source files</summary><pre>"
            + _escape(json.dumps(properties, indent=2))
            + "</pre></details>"
        )
    if shape["diagnostics"]:
        content += (
            '<div class="card issue"><strong>Data diagnostics</strong><ul>'
            + "".join(f"<li>{_escape(issue)}</li>" for issue in shape["diagnostics"])
            + "</ul></div>"
        )
    content += "<p>Expand an action and direction to inspect its frames and contact sheets. Preview artwork keeps drawing origins aligned; movement, sounds and scripts are recorded as data. Repeat is a native wait count.</p>"
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        anchor = row["npc_report"].split("#", 1)[1]
        groups[anchor].append(row)
    fields = [
        ("step", "Step"),
        ("frame", "Sprite frame"),
        ("animation_name", "Friendly action"),
        ("direction_name", "Direction"),
        ("valid_frame", "Valid frame"),
        ("width", "Width"),
        ("height", "Height"),
        ("xoff", "X origin"),
        ("yoff", "Y origin"),
        ("flipped", "Flipped"),
        ("repeat", "Repeat"),
        ("delta_z", "Delta Z"),
        ("delta_dir", "Delta dir"),
        ("movement_world_units", "World movement"),
        ("sfx", "Sound ID"),
        ("attack_range", "Attack range"),
        ("on_ground", "On ground"),
        ("special", "Special code"),
        ("call_usecode", "Usecode callback"),
        ("flags_hi", "High flags"),
        ("unknown_flag80", "Unknown flag80"),
        ("compressed", "Compression"),
        ("table_unknown", "Unknown table byte"),
        ("frame_unknown_hex", "Frame header bytes"),
        ("action_flags", "Action flags"),
        ("action_flag_names", "Action flag names"),
        ("action_unknown_4", "Unknown header4"),
        ("action_unknown_10", "Unknown header10"),
        ("action_raw_header", "Raw action header"),
        ("node_raw", "Raw node"),
        ("matches_saved_context", "Matches saved action/dir/step"),
        ("matches_saved_frame", "Matches saved frame"),
    ]
    for anchor, frames in groups.items():
        first = frames[0]
        label = (
            f"Action {first['action']}: {first['animation_name']} · {first['direction_name']} · {len(frames)} steps"
            if first["row_kind"] == "animation"
            else f"Unreferenced raw sprite frames · {len(frames)} frames"
        )
        content += (
            f'<details id="{_escape(anchor)}"><summary>{_escape(label)}</summary>'
        )
        paths = list(
            dict.fromkeys(
                row["contact_sheet"] for row in frames if row["contact_sheet"]
            )
        )
        if paths:
            for path in paths:
                url = "../" + path
                content += f'<a class="sheet" href="{_escape(url)}"><img loading="lazy" src="{_escape(url)}" alt="{_escape(label)}"><small>{_escape(path.rsplit("/", 1)[-1])}</small></a>'
        else:
            content += '<p class="issue">No contact sheet is available for this set; inspect the data diagnostics above.</p>'
        content += _table(frames, fields) + "</details>"
    if not rows:
        content += '<p class="issue">No sprite rows could be resolved for this NPC. Its stored state is retained above.</p>'
    return _document(title, content)


def render_npc_animation_index(manifest: dict[str, Any]) -> str:
    """Render an offline entry point linking every selected NPC and the master CSV."""
    content = '<h1>Ultima VIII NPC animation report</h1><p class="intro">NPC state, named animation actions and sprite frame contact sheets.</p><p><a href="master.csv">Master CSV</a> · <a href="npc_state.json">Full NPC state</a> · <a href="manifest.json">Sources and coverage</a></p>'
    content += f"<p>{manifest['npc_count']} NPCs · {manifest['shape_count']} shared shapes · {manifest['row_count']} frame rows · {manifest['contact_sheet_count']} contact sheets</p><p>Selection: {_escape(manifest['selection_basis'])}. Character names use explicit overrides, saved Avatar names or permanent NPC usecode classes. Unknown identities retain slot labels. The master CSV places the friendly action beside the sprite frame.</p>"
    if manifest["diagnostics"]:
        content += (
            '<div class="card issue"><ul>'
            + "".join(f"<li>{_escape(issue)}</li>" for issue in manifest["diagnostics"])
            + "</ul></div>"
        )
    content += '<div class="scroll"><table><thead><tr><th scope="col">NPC</th><th scope="col">Name / slot label</th><th scope="col">Shape</th><th scope="col">Frame rows</th><th scope="col">Diagnostics</th></tr></thead><tbody>'
    for npc in manifest["npcs"]:
        content += f'<tr><td>{npc["npc_id"]}</td><td><a href="{_escape(npc["page"])}">{_escape(npc["label"])}</a></td><td>{npc["shape"]}</td><td>{npc["row_count"]}</td><td>{len(npc["diagnostics"])}</td></tr>'
    return _document(
        "Ultima VIII NPC animation report", content + "</tbody></table></div>"
    )
