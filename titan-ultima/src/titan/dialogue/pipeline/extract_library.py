#!/usr/bin/env python3
"""Extract readable Ultima VIII library records from dialogue AST JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from titan.dialogue.pipeline.extract_books import build_books, format_book_text


QUALITY_RE = re.compile(r"\b(?:Item::getQuality\(this\)|local\d+)\s*==\s*(0x[\dA-Fa-f]+)h")
DISPATCH_RE = re.compile(r"->(\w+)::(\w+)\(")
SCROLL_READ_RE = re.compile(r'Scroll::read\((?:str_to_ptr|strptr)\("(.*?)"\)', re.DOTALL)
GRAVE_READ_RE = re.compile(r'Grave::read\((?:str_to_ptr|strptr)\("(.*?)"\)', re.DOTALL)
PLAQUE_READ_RE = re.compile(
    r'Plaque::read\((?:str_to_ptr|strptr)\("(.*?)"\),\s*(0x[\dA-Fa-f]+)h',
    re.DOTALL,
)


NECROMANCY = [
    ("Death Speak", "Kal Wis Corp", "Blood, Bone", "EARTHMAG::func0080"),
    ("Mask of Death", "Quas Corp", "Wood, Executioner's Hood", "NEC1::use"),
    ("Rock Flesh", "Rel Sanct Ylem", "Wood, Dirt", "NEC1::use"),
    ("Summon Undead", "Kal Corp Xen", "Blood, Bone, Wood", "NEC1::use"),
    ("Open Ground", "Des Por Ylem", "Blood, Blackmoor", "EARTHMAG::func0080"),
    ("Create Golem", "In Ort Ylem Xen", "Blood, Bone, Wood, Dirt, Blackmoor", "NEC1::use"),
    ("Withstand Death", "Vas An Corp", "Wood, Dirt, Blackmoor", "NEC1::use"),
    ("Grant Peace", "In Vas Corp", "Executioner's Hood, Blackmoor", "NEC1::use"),
    ("Call Quake", "Kal Vas Ylem Por", "Bone, Wood, Dirt, Blackmoor", "SCROLL1::func156D"),
]

SORCERY = [
    ("Ignite", "In Flam", "Ash, Pumice", "symbol, wand, rod, staff"),
    ("Extinguish", "An Flam", "Pumice", "symbol, wand, rod, staff"),
    ("Flash", "Flam Por", "Ash, Pumice", "symbol, wand, rod, staff"),
    ("Flame Bolt", "In Ort Flam", "Ash, Pumice, Pig Iron", "symbol, wand, rod, staff"),
    ("Endure Heat", "Sanct Flam", "Obsidian, Pig Iron", "symbol, rod, staff"),
    ("Fire Shield", "In Flam An Por", "Ash, Obsidian, Pig Iron", "symbol, rod, staff"),
    ("Armor of Flames", "Vas Sanct Flam", "Ash, Obsidian, Pig Iron, Brimstone", "symbol, rod, staff"),
    ("Create Fire", "In Flam Ylem", "Ash, Pumice, Obsidian", "symbol, staff"),
    ("Explosion", "Vas Ort Flam", "Ash, Pumice, Pig Iron, Brimstone", "symbol, staff"),
    ("Summon Daemon", "Kal Flam Corp Xen", "Ash, Pumice, Obsidian, Daemon Bone", "symbol, talisman"),
    ("Banish Daemon", "An Flam Corp Xen", "Ash, Pumice, Pig Iron, Daemon Bone", "symbol, talisman"),
    (
        "Conflagration",
        "Kal Vas Flam Corp Xen",
        "Ash, Pumice, Obsidian, Pig Iron, Brimstone, Daemon Bone",
        "symbol, talisman",
    ),
]

THAUMATURGY = [
    ("Confusion Blast", "In Quas Wis", "Eye of Newt, Bat Wing, Serpent Scale, Obsidian, Brimstone"),
    ("Meteor Shower", "Kal Des Flam Ylem", "Ash, Dirt, Serpent Scale, Brimstone, Blackmoor"),
    ("Summon Creature", "Kal Xen", "Bat Wing, Pumice, Obsidian, Bone"),
    ("Call Destruction", "Kal Vas Grav Corp", "Serpent Scale, Dragon Blood, Ash, Pig Iron, Executioner's Hood"),
    (
        "Devastation",
        "In Vas Ort Corp",
        "Bat Wing, Serpent Scale, Dragon Blood, Pig Iron, Executioner's Hood, Blackmoor, Brimstone",
    ),
    ("Ethereal Travel", "Ort Grav Por", "5 pieces of broken Blackrock from the Obelisk of Pagan"),
]

THEURGY = [
    ("Divination", "In Wis", "Sextant"),
    ("Healing Touch", "In Mani", "Pointing Hand"),
    ("Aerial Servant", "Kal Ort Xen", "Arm Band"),
    ("Reveal", "Ort Lor", "Open Eye"),
    ("Restoration", "Vas In Mani", "Open Hand"),
    ("Fade from Sight", "Quas An Lor", "Closed Eye"),
    ("Air Walk", "Vas Hur Por", "Wings"),
    ("Hear Truth", "An Quas Lor", "Chain"),
    ("Intervention", "In Sanct An Jux", "Fist"),
]


def _json_load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _load_class(json_dir: Path, name: str) -> dict[str, Any] | None:
    path = json_dir / f"U8P_{name}.json"
    if not path.is_file():
        return None
    return _json_load(path)


def _iter_nodes(nodes: list[Any]) -> Any:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        yield node
        for key in ("then", "else", "body"):
            child = node.get(key)
            if isinstance(child, list):
                yield from _iter_nodes(child)
        else_ifs = node.get("else_ifs")
        if isinstance(else_ifs, list):
            for branch in else_ifs:
                if isinstance(branch, dict) and isinstance(branch.get("body"), list):
                    yield from _iter_nodes(branch["body"])


def _quality_from_condition(condition: Any) -> int | None:
    if not isinstance(condition, dict):
        return None
    raw = condition.get("raw")
    if not isinstance(raw, str):
        return None
    match = QUALITY_RE.search(raw)
    return int(match.group(1), 16) if match else None


def _quality_branches(function: dict[str, Any]) -> list[tuple[int, list[Any]]]:
    branches: list[tuple[int, list[Any]]] = []
    for node in function.get("nodes", []):
        if not isinstance(node, dict) or node.get("type") != "IfStatement":
            continue
        q = _quality_from_condition(node.get("condition"))
        if q is not None and isinstance(node.get("then"), list):
            branches.append((q, node["then"]))
        for branch in node.get("else_ifs", []):
            if not isinstance(branch, dict):
                continue
            q = _quality_from_condition(branch.get("condition"))
            if q is not None and isinstance(branch.get("body"), list):
                branches.append((q, branch["body"]))
    return branches


def _first_bark(nodes: list[Any]) -> str | None:
    for node in _iter_nodes(nodes):
        if node.get("type") == "Bark" and isinstance(node.get("text"), str):
            return node["text"].strip()
    return None


def _first_dispatch(nodes: list[Any]) -> tuple[str, str] | None:
    for node in _iter_nodes(nodes):
        raw = node.get("raw")
        if not isinstance(raw, str):
            continue
        match = DISPATCH_RE.search(raw)
        if match:
            return match.group(1), match.group(2)
    return None


def _first_match(nodes: list[Any], regex: re.Pattern[str]) -> re.Match[str] | None:
    for node in _iter_nodes(nodes):
        raw = node.get("raw")
        if not isinstance(raw, str):
            continue
        match = regex.search(raw)
        if match:
            return match
    return None


def _format_simple_text(raw: str) -> list[str]:
    text = raw.replace("*", "\n").replace("~", "\n").replace("%", "\n")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _title_from_text(raw: str, fallback: str) -> str:
    for line in _format_simple_text(raw):
        clean = line.strip().strip(".")
        if clean:
            return clean.title() if clean.isupper() else clean
    return fallback


def _common_item(
    *,
    kind: str,
    quality: int | None,
    title: str,
    category: str,
    text: str | None = None,
    source: str | None = None,
    details: dict[str, Any] | None = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    quality_hex = f"0x{quality:02X}" if quality is not None else "default"
    entry: dict[str, Any] = {
        "id": item_id or f"{kind}-{quality_hex}",
        "kind": kind,
        "quality": quality,
        "qualityHex": quality_hex,
        "title": title,
        "category": category,
        "text": text,
    }
    if text:
        entry["paragraphs"] = _format_simple_text(text)
    if source:
        entry["source"] = source
    if details:
        entry["details"] = details
    return entry


def _section(
    section_id: str,
    title: str,
    description: str,
    icon: str,
    item_class: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": title,
        "description": description,
        "icon": icon,
        "itemClass": item_class,
        "totalItems": len(items),
        "itemsWithText": sum(1 for item in items if isinstance(item.get("text"), str) and item["text"]),
        "items": items,
    }


def build_book_section(json_dir: Path) -> dict[str, Any]:
    books_data = build_books(json_dir)
    items = []
    for book in books_data["books"]:
        item = dict(book)
        item["id"] = f"book-{book['qualityHex']}"
        item["kind"] = "book"
        items.append(item)
    return _section(
        "books",
        "Books",
        "Readable books indexed from BASEBOOK quality branches.",
        "book",
        "BASEBOOK",
        items,
    )


def build_scroll_section(json_dir: Path) -> dict[str, Any]:
    base = _load_class(json_dir, "BASESCRL")
    if base is None:
        raise FileNotFoundError(f"Cannot find {json_dir / 'U8P_BASESCRL.json'}")
    functions = base.get("functions") or {}
    look = functions.get("look") if isinstance(functions.get("look"), dict) else {}
    use = functions.get("use") if isinstance(functions.get("use"), dict) else {}

    titles: dict[int, str] = {}
    for quality, body in _quality_branches(look):
        bark = _first_bark(body)
        if bark:
            titles[quality] = bark.strip()

    dispatch: dict[int, tuple[str, str]] = {}
    for quality, body in _quality_branches(use):
        target = _first_dispatch(body)
        if target:
            dispatch[quality] = target

    class_names = {cls for cls, _ in dispatch.values()}
    func_text: dict[str, str] = {}
    for cls in sorted(class_names):
        payload = _load_class(json_dir, cls)
        if payload is None:
            print(f"  WARNING: Missing JSON class file for {cls}", file=sys.stderr)
            continue
        for func_name, function in (payload.get("functions") or {}).items():
            if not isinstance(function, dict):
                continue
            match = _first_match(function.get("nodes", []), SCROLL_READ_RE)
            if match:
                func_text[f"{cls}::{func_name}"] = match.group(1)

    items: list[dict[str, Any]] = []
    for quality in sorted(dispatch):
        cls, func = dispatch[quality]
        source = f"{cls}::{func}"
        raw = func_text.get(source)
        title = titles.get(quality) or (_title_from_text(raw, "Scroll") if raw else f"Scroll {quality:02X}")
        category = "Magic Scrolls" if quality >= 0x32 or "scroll of" in title.lower() else "Scrolls & Notes"
        items.append(
            _common_item(
                kind="scroll",
                quality=quality,
                title=title,
                category=category,
                text=raw,
                source=source,
            )
        )
    return _section("scrolls", "Scrolls", "Readable scrolls dispatched by BASESCRL.", "scroll", "BASESCRL", items)


def build_direct_read_section(
    json_dir: Path,
    *,
    class_name: str,
    function_name: str,
    kind: str,
    title: str,
    description: str,
    icon: str,
    category: str,
    regex: re.Pattern[str],
) -> dict[str, Any]:
    payload = _load_class(json_dir, class_name)
    if payload is None:
        raise FileNotFoundError(f"Cannot find {json_dir / f'U8P_{class_name}.json'}")
    function = (payload.get("functions") or {}).get(function_name)
    if not isinstance(function, dict):
        raise ValueError(f"Cannot find {class_name}::{function_name}")

    items: list[dict[str, Any]] = []
    seen_reads: set[str] = set()
    for quality, body in _quality_branches(function):
        match = _first_match(body, regex)
        if not match:
            continue
        raw = match.group(1)
        seen_reads.add(match.group(0))
        details: dict[str, Any] = {}
        if kind == "plaque" and len(match.groups()) > 1:
            details["width"] = match.group(2)
        items.append(
            _common_item(
                kind=kind,
                quality=quality,
                title=_title_from_text(raw, title),
                category=category,
                text=raw,
                source=f"{class_name}::{function_name}",
                details=details or None,
            )
        )
    extra_index = 1
    for node in _iter_nodes(function.get("nodes", [])):
        raw_line = node.get("raw")
        if not isinstance(raw_line, str):
            continue
        match = regex.search(raw_line)
        if not match or match.group(0) in seen_reads:
            continue
        raw = match.group(1)
        details = {"qualityNote": "default/fallback"}
        if kind == "plaque" and len(match.groups()) > 1:
            details["width"] = match.group(2)
        items.append(
            _common_item(
                kind=kind,
                quality=None,
                title=_title_from_text(raw, title),
                category=category,
                text=raw,
                source=f"{class_name}::{function_name}",
                details=details,
                item_id=f"{kind}-default-{extra_index}",
            )
        )
        extra_index += 1
    return _section(kind + "s", title, description, icon, class_name, items)


def build_spell_section() -> dict[str, Any]:
    items: list[dict[str, Any]] = []

    def add_spell(school: str, slot: int, name: str, incantation: str, details: dict[str, Any]) -> None:
        payload = {
            "id": f"spell-{school.lower()}-{slot:02d}",
            "kind": "spell",
            "quality": slot,
            "qualityHex": f"slot {slot}",
            "title": name,
            "category": school,
            "school": school,
            "text": None,
            "details": {"incantation": incantation, **details},
        }
        items.append(payload)

    for slot, (name, words, reagents, source) in enumerate(NECROMANCY):
        add_spell("Necromancy", slot, name, words, {"reagents": reagents, "source": source})
    for slot, (name, words, reagents, foci) in enumerate(SORCERY):
        add_spell("Sorcery", slot, name, words, {"reagents": reagents, "foci": foci, "source": "PENT"})
    for slot, (name, words, reagents) in enumerate(THAUMATURGY):
        add_spell("Thaumaturgy", slot, name, words, {"reagents": reagents, "focus": "spellbook", "source": "BOOK1"})
    for slot, (name, words, focus) in enumerate(THEURGY):
        add_spell("Theurgy", slot, name, words, {"focus": focus, "source": "AIRSPEL/SGBOOK"})

    return _section(
        "spells",
        "Spell Catalog",
        "Spell reference distilled from the spell exporter scripts and source annotations.",
        "spell",
        "SPELLS",
        items,
    )


def build_library(json_dir: Path) -> dict[str, Any]:
    sections = [
        build_book_section(json_dir),
        build_scroll_section(json_dir),
        build_direct_read_section(
            json_dir,
            class_name="GRAVE_NS",
            function_name="func00CB",
            kind="grave",
            title="Graves",
            description="Readable gravestone inscriptions indexed by quality.",
            icon="grave",
            category="Epitaphs",
            regex=GRAVE_READ_RE,
        ),
        build_direct_read_section(
            json_dir,
            class_name="PLAQUENS",
            function_name="func00C2",
            kind="plaque",
            title="Plaques",
            description="Readable plaques and signs indexed by quality.",
            icon="plaque",
            category="Plaques & Signs",
            regex=PLAQUE_READ_RE,
        ),
        build_spell_section(),
    ]
    return {
        "schemaVersion": "1.0",
        "description": "Readable library records for the Ultima VIII dialogue web viewer.",
        "totalSections": len(sections),
        "totalItems": sum(section["totalItems"] for section in sections),
        "sections": sections,
    }


def _default_paths() -> tuple[str, str]:
    dialogue_root = Path(__file__).resolve().parent.parent
    return (
        str(dialogue_root / "json"),
        str(dialogue_root / "json" / "library.json"),
    )


def main(argv: list[str] | None = None) -> int:
    default_json_dir, default_out_path = _default_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-dir",
        default=default_json_dir,
        help="Directory containing extracted U8P_*.json AST files",
    )
    parser.add_argument("--out", default=default_out_path, help="Output path for library.json")
    args = parser.parse_args(argv)

    json_dir = Path(args.json_dir).resolve()
    out_path = Path(args.out).resolve()
    if not json_dir.is_dir():
        print(f"ERROR: JSON directory not found: {json_dir}", file=sys.stderr)
        return 1

    try:
        output = build_library(json_dir)
    except Exception as exc:
        print(f"ERROR: Library extraction failed: {exc}", file=sys.stderr)
        return 1

    os.makedirs(out_path.parent, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {out_path}")
    for section in output["sections"]:
        print(f"  {section['title']}: {section['totalItems']} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
