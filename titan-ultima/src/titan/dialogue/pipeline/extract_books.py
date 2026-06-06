#!/usr/bin/env python3
"""Extract Ultima VIII book texts from generated dialogue AST JSON.

The dialogue prepare pipeline runs this after ``extract_ast``.  The output is
``books.json`` in the shape consumed by the dialogue web viewer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


QUALITY_RE = re.compile(r"Item::getQuality\(this\)\s*==\s*(0x[\dA-Fa-f]+)h")
DISPATCH_RE = re.compile(r"->(\w+)::(\w+)\(")
BOOK_READ_RE = re.compile(r'Book::read\((?:str_to_ptr|strptr)\("(.*?)"\)', re.DOTALL)


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
    if not match:
        return None
    return int(match.group(1), 16)


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


def _quality_branches(function: dict[str, Any]) -> list[tuple[int, list[Any]]]:
    branches: list[tuple[int, list[Any]]] = []
    for node in function.get("nodes", []):
        if not isinstance(node, dict) or node.get("type") != "IfStatement":
            continue
        q = _quality_from_condition(node.get("condition"))
        if q is not None:
            body = node.get("then")
            if isinstance(body, list):
                branches.append((q, body))
        for branch in node.get("else_ifs", []):
            if not isinstance(branch, dict):
                continue
            q = _quality_from_condition(branch.get("condition"))
            body = branch.get("body")
            if q is not None and isinstance(body, list):
                branches.append((q, body))
    return branches


def parse_look_titles(basebook: dict[str, Any]) -> dict[int, str]:
    """Parse BASEBOOK::look() to map quality -> title."""
    look = (basebook.get("functions") or {}).get("look")
    if not isinstance(look, dict):
        return {}

    titles: dict[int, str] = {}
    for quality, body in _quality_branches(look):
        bark = _first_bark(body)
        if bark is not None:
            titles[quality] = bark
    return titles


def parse_use_dispatch(basebook: dict[str, Any]) -> dict[int, tuple[str, str]]:
    """Parse BASEBOOK::use() to map quality -> (CLASS, funcName)."""
    use = (basebook.get("functions") or {}).get("use")
    if not isinstance(use, dict):
        return {}

    dispatch: dict[int, tuple[str, str]] = {}
    for quality, body in _quality_branches(use):
        target = _first_dispatch(body)
        if target and quality not in dispatch:
            dispatch[quality] = target
    return dispatch


def extract_book_texts(json_dir: Path, class_names: set[str]) -> dict[str, str]:
    """Read each referenced book class JSON and extract Book::read strings."""
    func_text: dict[str, str] = {}
    for cls in sorted(class_names):
        payload = _load_class(json_dir, cls)
        if payload is None:
            print(f"  WARNING: Missing JSON class file for {cls}", file=sys.stderr)
            continue
        functions = payload.get("functions")
        if not isinstance(functions, dict):
            continue
        for func_name, function in functions.items():
            if not isinstance(function, dict):
                continue
            for node in _iter_nodes(function.get("nodes", [])):
                raw = node.get("raw")
                if not isinstance(raw, str):
                    continue
                match = BOOK_READ_RE.search(raw)
                if match:
                    func_text[f"{cls}::{func_name}"] = match.group(1)
                    break
    return func_text


def format_book_text(raw: str) -> list[str]:
    """Convert raw book text into formatted paragraphs.

    Game formatting markers:
      ~  = line break
      *  = page break
      %  = paragraph indent / new paragraph
    """
    text = raw.replace("*", "\n\n")
    text = text.replace("~", "\n")
    text = text.replace("%", "\n")
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


# -- Title improvement heuristics -----------------------------------------

TITLE_OVERRIDES: dict[int, str] = {
    0x01: "Song of Fred",
    0x47: "Slayer Quest Book I",
    0x48: "Slayer Quest Book II",
    0x49: "Slayer Quest Book III",
    0x4A: "Slayer Quest Book IV",
}

_GENERIC_TITLE_RE = re.compile(
    r"^(Book|book|diary|journal|Journal|Read me\.)( \(quality .+\))?$"
)
_ROMAN_RE = re.compile(r"^[IVXLCDM]+\.?$")


def _is_generic_title(title: str) -> bool:
    return bool(_GENERIC_TITLE_RE.match(title.strip()))


def _title_case_smart(s: str) -> str:
    alpha = [c for c in s if c.isalpha()]
    if not alpha:
        return s
    upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    if upper_ratio < 0.6:
        return s
    small = {
        "a", "an", "the", "of", "in", "on", "at", "to",
        "for", "and", "but", "or", "nor", "by", "as",
    }
    words = s.split()
    out: list[str] = []
    for i, word in enumerate(words):
        bare = word.rstrip(":,;.!?'\"")
        if _ROMAN_RE.match(bare):
            out.append(word)
        elif i == 0 or bare.lower() not in small:
            out.append(word.capitalize())
        else:
            out.append(word.lower())
    return " ".join(out)


def _infer_title_from_text(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.lstrip("%")
    segs = text.split("~")
    first = segs[0].strip().rstrip(":").strip()
    if not first or len(first) < 4 or len(first) > 80:
        return None
    if first[0].islower():
        return None
    title = first
    if len(segs) > 1:
        second = segs[1].strip().lstrip("%").strip()
        if re.match(r"VOL\.?\s", second, re.IGNORECASE):
            title = f"{title}, {second}"
    return _title_case_smart(title)


def _improve_title(quality: int, title: str, raw_text: str | None) -> str:
    if quality in TITLE_OVERRIDES:
        return TITLE_OVERRIDES[quality]
    if _is_generic_title(title):
        inferred = _infer_title_from_text(raw_text)
        if inferred:
            return inferred
    return title


def categorize_book(title: str, quality: int) -> str:
    tl = title.lower()
    if "spellbook" in tl or quality in range(0x0A, 0x16):
        return "Sorcery Spellbooks"
    if quality in range(0x51, 0x57):
        return "Thaumaturgy Spellbooks"
    if quality in range(0x5D, 0x67):
        return "Theurgy Spellbooks"
    if "guard log" in tl:
        return "Guard Logs"
    if "journal" in tl or "diary" in tl or "expedition" in tl or "captain" in tl or "logbook" in tl:
        return "Journals & Logs"
    if "letter" in tl or "acolyte" in tl:
        return "Letters"
    if "saga" in tl or "chronicle" in tl or "history" in tl or "moriens" in tl:
        return "History & Lore"
    if "mystery" in tl or "mythology" in tl or "destruction" in tl or "objective history" in tl:
        return "History & Lore"
    if "earthen" in tl:
        return "Necromancy"
    if "art of flame" in tl or "tongue of flame" in tl or "sorcerous" in tl:
        return "Sorcery"
    if "reagent" in tl:
        return "Thaumaturgy"
    if "stratos" in tl or "parables" in tl or "raising" in tl:
        return "Theurgy"
    if "slayer" in tl or "read me" in tl:
        return "Quest Books"
    if "adventure" in tl or "mushroom" in tl or "killer" in tl or "arricorn" in tl:
        return "Miscellaneous"
    return "Books"


def build_books(json_dir: Path) -> dict[str, Any]:
    basebook = _load_class(json_dir, "BASEBOOK")
    if basebook is None:
        raise FileNotFoundError(f"Cannot find {json_dir / 'U8P_BASEBOOK.json'}")

    titles = parse_look_titles(basebook)
    dispatch = parse_use_dispatch(basebook)
    class_names = {cls for cls, _ in dispatch.values()}
    func_text = extract_book_texts(json_dir, class_names)

    all_qualities = sorted(set(titles) | set(dispatch))
    books: list[dict[str, Any]] = []
    text_found = 0

    for quality in all_qualities:
        raw_title = titles.get(quality, f"Book (quality 0x{quality:02X})")
        raw_text: str | None = None
        if quality in dispatch:
            cls, func = dispatch[quality]
            raw_text = func_text.get(f"{cls}::{func}")

        title = _improve_title(quality, raw_title, raw_text)
        entry: dict[str, Any] = {
            "quality": quality,
            "qualityHex": f"0x{quality:02X}",
            "title": title,
            "category": categorize_book(title, quality),
        }

        if quality in dispatch:
            cls, func = dispatch[quality]
            key = f"{cls}::{func}"
            entry["source"] = key
            if key in func_text:
                raw = func_text[key]
                entry["text"] = raw
                entry["paragraphs"] = format_book_text(raw)
                text_found += 1
            else:
                entry["text"] = None
        else:
            entry["text"] = None

        books.append(entry)

    return {
        "itemClass": "BASEBOOK",
        "description": "All books in Ultima VIII: Pagan indexed by quality value",
        "totalBooks": len(books),
        "booksWithText": text_found,
        "books": books,
    }


def _default_paths() -> tuple[str, str]:
    dialogue_root = Path(__file__).resolve().parent.parent
    return (
        str(dialogue_root / "json"),
        str(dialogue_root / "json" / "books.json"),
    )


def main(argv: list[str] | None = None) -> int:
    default_json_dir, default_out_path = _default_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-dir",
        default=default_json_dir,
        help="Directory containing extracted U8P_*.json AST files",
    )
    parser.add_argument(
        "--fold-dir",
        default=None,
        help="Deprecated compatibility option; ignored. Books are extracted from --json-dir.",
    )
    parser.add_argument("--out", default=default_out_path, help="Output path for books.json")
    args = parser.parse_args(argv)

    json_dir = Path(args.json_dir).resolve()
    out_path = Path(args.out).resolve()

    if not json_dir.is_dir():
        print(f"ERROR: JSON directory not found: {json_dir}", file=sys.stderr)
        return 1

    try:
        output = build_books(json_dir)
    except Exception as exc:
        print(f"ERROR: Book extraction failed: {exc}", file=sys.stderr)
        return 1

    os.makedirs(out_path.parent, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    text_missing = output["totalBooks"] - output["booksWithText"]
    print(f"Wrote {out_path}")
    print(f"  Total books: {output['totalBooks']}")
    print(f"  With text: {output['booksWithText']}")
    print(f"  Without text: {text_missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
