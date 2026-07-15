#!/usr/bin/env python3
"""Extract readable Ultima VIII library records from dialogue AST JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from titan.dialogue.pipeline.extract_books import build_books


QUALITY_RE = re.compile(r"\b(?:Item::getQuality\(this\)|local\d+)\s*==\s*(0x[\dA-Fa-f]+)h")
DISPATCH_RE = re.compile(r"->(\w+)::(\w+)\(")
SCROLL_READ_RE = re.compile(r'Scroll::read\((?:str_to_ptr|strptr)\("(.*?)"\)', re.DOTALL)
NON_READABLE_SCROLL_CLASSES = frozenset({"SCROLL2"})
GRAVE_READ_RE = re.compile(r'Grave::read\((?:str_to_ptr|strptr)\("(.*?)"\)', re.DOTALL)
PLAQUE_READ_RE = re.compile(
    r'Plaque::read\((?:str_to_ptr|strptr)\("(.*?)"\),\s*(0x[\dA-Fa-f]+)h',
    re.DOTALL,
)


@dataclass(frozen=True)
class SpellDefinition:
    """Canonical spell metadata used to generate and validate library.json."""

    school: str
    slot: int
    title: str
    incantation: str
    mana_cost: int | str
    mana_cost_context: str
    source: str
    reagents: str | None = None
    focus: str | None = None
    focus_key: str = "focus"

    def details(self) -> dict[str, str | int]:
        details: dict[str, str | int] = {
            "incantation": self.incantation,
            "manaCost": self.mana_cost,
            "manaCostContext": self.mana_cost_context,
        }
        if self.reagents:
            details["reagents"] = self.reagents
        if self.focus:
            details[self.focus_key] = self.focus
        details["source"] = self.source
        return details


# Mana use occurs at cast time for Necromancy and Theurgy, while Sorcery and
# Thaumaturgy spend mana when their reusable focus or spellbook is enchanted.
# Sorcery costs are randomized by the original usecode and are shown as ranges.
SPELL_CATALOG = (
    SpellDefinition(
        "Necromancy",
        0,
        "Death Speak",
        "Kal Wis Corp",
        1,
        "Per cast",
        "EARTHMAG::func0080",
        "Blood, Bone",
    ),
    SpellDefinition(
        "Necromancy",
        1,
        "Mask of Death",
        "Quas Corp",
        1,
        "Per cast",
        "NEC1::use",
        "Wood, Executioner's Hood",
    ),
    SpellDefinition(
        "Necromancy",
        2,
        "Rock Flesh",
        "Rel Sanct Ylem",
        2,
        "Per cast",
        "NEC1::use",
        "Wood, Dirt",
    ),
    SpellDefinition(
        "Necromancy",
        3,
        "Summon Undead",
        "Kal Corp Xen",
        2,
        "Per cast",
        "NEC1::use",
        "Blood, Bone, Wood",
    ),
    SpellDefinition(
        "Necromancy",
        4,
        "Open Ground",
        "Des Por Ylem",
        3,
        "Per cast",
        "EARTHMAG::func0080",
        "Blood, Blackmoor",
    ),
    SpellDefinition(
        "Necromancy",
        5,
        "Create Golem",
        "In Ort Ylem Xen",
        3,
        "Per cast",
        "NEC1::use",
        "Blood, Bone, Wood, Dirt, Blackmoor",
    ),
    SpellDefinition(
        "Necromancy",
        6,
        "Withstand Death",
        "Vas An Corp",
        4,
        "Per cast",
        "NEC1::use",
        "Wood, Dirt, Blackmoor",
    ),
    SpellDefinition(
        "Necromancy",
        7,
        "Grant Peace",
        "In Vas Corp",
        5,
        "Per cast",
        "NEC1::use",
        "Executioner's Hood, Blackmoor",
    ),
    SpellDefinition(
        "Necromancy",
        8,
        "Call Quake",
        "Kal Vas Ylem Por",
        5,
        "Per cast",
        "SCROLL1::func156D",
        "Bone, Wood, Dirt, Blackmoor",
    ),
    SpellDefinition(
        "Sorcery",
        0,
        "Ignite",
        "In Flam",
        "3–4",
        "When enchanting a focus",
        "PENT",
        "Ash, Pumice",
        "symbol, wand, rod, staff",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        1,
        "Extinguish",
        "An Flam",
        "4–5",
        "When enchanting a focus",
        "PENT",
        "Pumice",
        "symbol, wand, rod, staff",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        2,
        "Flash",
        "Flam Por",
        "6–8",
        "When enchanting a focus",
        "PENT",
        "Ash, Pumice",
        "symbol, wand, rod, staff",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        3,
        "Flame Bolt",
        "In Ort Flam",
        "8–10",
        "When enchanting a focus",
        "PENT",
        "Ash, Pumice, Pig Iron",
        "symbol, wand, rod, staff",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        4,
        "Endure Heat",
        "Sanct Flam",
        "8–10",
        "When enchanting a focus",
        "PENT",
        "Obsidian, Pig Iron",
        "symbol, rod, staff",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        5,
        "Fire Shield",
        "In Flam An Por",
        "10–12",
        "When enchanting a focus",
        "PENT",
        "Ash, Obsidian, Pig Iron",
        "symbol, rod, staff",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        6,
        "Armor of Flames",
        "Vas Sanct Flam",
        "12–15",
        "When enchanting a focus",
        "PENT",
        "Ash, Obsidian, Pig Iron, Brimstone",
        "symbol, rod, staff",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        7,
        "Create Fire",
        "In Flam Ylem",
        "14–17",
        "When enchanting a focus",
        "PENT",
        "Ash, Pumice, Obsidian",
        "symbol, staff",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        8,
        "Explosion",
        "Vas Ort Flam",
        "16–19",
        "When enchanting a focus",
        "PENT",
        "Ash, Pumice, Pig Iron, Brimstone",
        "symbol, staff",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        9,
        "Summon Daemon",
        "Kal Flam Corp Xen",
        "18–23",
        "When enchanting a focus",
        "PENT",
        "Ash, Pumice, Obsidian, Daemon Bone",
        "symbol, talisman",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        10,
        "Banish Daemon",
        "An Flam Corp Xen",
        "19–24",
        "When enchanting a focus",
        "PENT",
        "Ash, Pumice, Pig Iron, Daemon Bone",
        "symbol, talisman",
        "foci",
    ),
    SpellDefinition(
        "Sorcery",
        11,
        "Conflagration",
        "Kal Vas Flam Corp Xen",
        "22–27",
        "When enchanting a focus",
        "PENT",
        "Ash, Pumice, Obsidian, Pig Iron, Brimstone, Daemon Bone",
        "symbol, talisman",
        "foci",
    ),
    SpellDefinition(
        "Thaumaturgy",
        0,
        "Confusion Blast",
        "In Quas Wis",
        3,
        "When enchanting the spellbook",
        "BOOK1",
        "Eye of Newt, Bat Wing, Serpent Scale, Obsidian, Brimstone",
        "spellbook",
    ),
    SpellDefinition(
        "Thaumaturgy",
        1,
        "Meteor Shower",
        "Kal Des Flam Ylem",
        3,
        "When enchanting the spellbook",
        "BOOK1",
        "Ash, Dirt, Serpent Scale, Brimstone, Blackmoor",
        "spellbook",
    ),
    SpellDefinition(
        "Thaumaturgy",
        2,
        "Summon Creature",
        "Kal Xen",
        3,
        "When enchanting the spellbook",
        "BOOK1",
        "Bat Wing, Pumice, Obsidian, Bone",
        "spellbook",
    ),
    SpellDefinition(
        "Thaumaturgy",
        3,
        "Call Destruction",
        "Kal Vas Grav Corp",
        3,
        "When enchanting the spellbook",
        "BOOK1",
        "Serpent Scale, Dragon Blood, Ash, Pig Iron, Executioner's Hood",
        "spellbook",
    ),
    SpellDefinition(
        "Thaumaturgy",
        4,
        "Devastation",
        "In Vas Ort Corp",
        3,
        "When enchanting the spellbook",
        "BOOK1",
        "Bat Wing, Serpent Scale, Dragon Blood, Pig Iron, Executioner's Hood, Blackmoor, Brimstone",
        "spellbook",
    ),
    SpellDefinition(
        "Thaumaturgy",
        5,
        "Ethereal Travel",
        "Ort Grav Por",
        3,
        "When enchanting the spellbook",
        "BOOK1",
        "5 pieces of broken Blackrock from the Obelisk of Pagan",
        "spellbook",
    ),
    SpellDefinition(
        "Theurgy",
        0,
        "Divination",
        "In Wis",
        3,
        "Per cast",
        "AIRSPEL/SGBOOK",
        focus="Sextant",
    ),
    SpellDefinition(
        "Theurgy",
        1,
        "Healing Touch",
        "In Mani",
        5,
        "Per cast",
        "AIRSPEL/SGBOOK",
        focus="Pointing Hand",
    ),
    SpellDefinition(
        "Theurgy",
        2,
        "Aerial Servant",
        "Kal Ort Xen",
        5,
        "Per cast",
        "AIRSPEL/SGBOOK",
        focus="Arm Band",
    ),
    SpellDefinition(
        "Theurgy",
        3,
        "Reveal",
        "Ort Lor",
        5,
        "Per cast",
        "AIRSPEL/SGBOOK",
        focus="Open Eye",
    ),
    SpellDefinition(
        "Theurgy",
        4,
        "Restoration",
        "Vas In Mani",
        15,
        "Per cast",
        "AIRSPEL/SGBOOK",
        focus="Open Hand",
    ),
    SpellDefinition(
        "Theurgy",
        5,
        "Fade from Sight",
        "Quas An Lor",
        5,
        "Per cast",
        "AIRSPEL/SGBOOK",
        focus="Closed Eye",
    ),
    SpellDefinition(
        "Theurgy",
        6,
        "Air Walk",
        "Vas Hur Por",
        15,
        "Per cast",
        "AIRSPEL/SGBOOK",
        focus="Wings",
    ),
    SpellDefinition(
        "Theurgy",
        7,
        "Hear Truth",
        "An Quas Lor",
        3,
        "Per cast",
        "AIRSPEL/SGBOOK",
        focus="Chain",
    ),
    SpellDefinition(
        "Theurgy",
        8,
        "Intervention",
        "In Sanct An Jux",
        15,
        "Per cast",
        "AIRSPEL/SGBOOK",
        focus="Fist",
    ),
)


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
        "itemsWithContent": sum(1 for item in items if item.get("text") or item.get("details")),
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
        if target and target[0] not in NON_READABLE_SCROLL_CLASSES:
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
    text_first_seen: dict[str, str] = {}
    for quality in sorted(dispatch):
        cls, func = dispatch[quality]
        source = f"{cls}::{func}"
        raw = func_text.get(source)
        title = titles.get(quality) or (_title_from_text(raw, "Scroll") if raw else f"Scroll {quality:02X}")
        category = "Magic Scrolls" if quality >= 0x32 or "scroll of" in title.lower() else "Scrolls & Notes"
        details: dict[str, Any] = {}
        if raw:
            first_id = text_first_seen.get(raw)
            if first_id:
                details["duplicateTextOf"] = first_id
            else:
                text_first_seen[raw] = f"scroll-0x{quality:02X}"
        items.append(
            _common_item(
                kind="scroll",
                quality=quality,
                title=title,
                category=category,
                text=raw,
                source=source,
                details=details or None,
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
    items = []
    for spell in SPELL_CATALOG:
        payload: dict[str, Any] = {
            "id": f"spell-{spell.school.lower()}-{spell.slot:02d}",
            "kind": "spell",
            "quality": spell.slot,
            "qualityHex": f"slot {spell.slot}",
            "slot": spell.slot,
            "title": spell.title,
            "category": spell.school,
            "school": spell.school,
            "text": None,
            "details": spell.details(),
        }
        items.append(payload)

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
        "schemaVersion": "1.1",
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
