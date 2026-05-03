#!/usr/bin/env python3
"""Extract all Ultima VIII book texts from BASEBOOK fold source and its
referenced book classes (BOOK1, BOOKMARK, SGBOOK, STEVBOOK, MELBOOK,
EARTHMAG, BRIBOOKx).

Outputs dialogue/web/public/data/books.json mapping each quality value to
a title and the full in-game book text with formatting markers decoded.
"""

import argparse
import json
import os
import re
import sys


def read_fold(fold_dir: str, name: str) -> str:
    path = os.path.join(fold_dir, f'U8P_{name}.txt')
    if not os.path.exists(path):
        return ''
    with open(path, 'r', encoding='latin-1') as f:
        return f.read()


def parse_look_titles(src: str) -> dict[int, str]:
    """Parse BASEBOOK::look() to map quality -> title."""
    titles: dict[int, str] = {}
    for m in re.finditer(
        r'Item::getQuality\(this\)\s*==\s*(0x[\dA-Fa-f]+h)\)\s*\{'
        r'\s*temp\s*=\s*pid\s*<=>\s*process\s+Item::bark\(str_to_ptr\("([^"]+)"\)',
        src,
    ):
        q = int(m.group(1).replace('h', ''), 16)
        titles[q] = m.group(2).strip()
    return titles


def parse_use_dispatch(src: str) -> dict[int, tuple[str, str]]:
    """Parse BASEBOOK::use() to map quality -> (CLASS, funcName)."""
    dispatch: dict[int, tuple[str, str]] = {}
    for m in re.finditer(
        r'Item::getQuality\(this\)\s*==\s*(0x[\dA-Fa-f]+h)\).*?->(\w+)::(\w+)\(',
        src,
        re.DOTALL,
    ):
        q = int(m.group(1).replace('h', ''), 16)
        if q not in dispatch:
            dispatch[q] = (m.group(2), m.group(3))
    return dispatch


def extract_book_texts(fold_dir: str, class_names: set[str]) -> dict[str, str]:
    """Read each book class fold file and extract Book::read() strings."""
    func_text: dict[str, str] = {}
    for cls in sorted(class_names):
        content = read_fold(fold_dir, cls)
        if not content:
            print(f'  WARNING: Missing fold file for {cls}', file=sys.stderr)
            continue
        # Match function definitions and their Book::read calls
        for fm in re.finditer(
            r'(\w+)::(\w+)\(\)\s*\{(.*?)\n\}',
            content,
            re.DOTALL,
        ):
            body = fm.group(3)
            rm = re.search(r'Book::read\(str_to_ptr\("(.*?)"\)', body, re.DOTALL)
            if rm:
                func_text[f'{fm.group(1)}::{fm.group(2)}'] = rm.group(1)
    return func_text


def format_book_text(raw: str) -> list[str]:
    """Convert raw book text into formatted paragraphs.

    Game formatting markers:
      ~  = line break
      *  = page break
      %  = paragraph indent / new paragraph
    """
    # Normalize: replace * (page break) with double newline
    text = raw.replace('*', '\n\n')
    # Replace ~ (line break) with newline
    text = text.replace('~', '\n')
    # Replace % (paragraph marker) with newline + indent
    text = text.replace('%', '\n')
    # Split into paragraphs (runs of blank lines)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    return paragraphs


# ── Title improvement heuristics ──────────────────────────────────────────

# Manual overrides for books whose text has no embedded title header.
TITLE_OVERRIDES: dict[int, str] = {
    0x01: 'Song of Fred',           # "diary"    – well-known poem
    0x47: 'Slayer Quest Book I',    # "Read me." – BRIBOOK2
    0x48: 'Slayer Quest Book II',   # "Read me." – BRIBOOK3
    0x49: 'Slayer Quest Book III',  # "Read me." – BRIBOOK4
    0x4A: 'Slayer Quest Book IV',   # "Read me." – BRIBOOK5
}

_GENERIC_TITLE_RE = re.compile(
    r'^(Book|book|diary|journal|Journal|Read me\.)( \(quality .+\))?$'
)
_ROMAN_RE = re.compile(r'^[IVXLCDM]+\.?$')


def _is_generic_title(title: str) -> bool:
    """Return True if the title is generic / unhelpful."""
    return bool(_GENERIC_TITLE_RE.match(title.strip()))


def _title_case_smart(s: str) -> str:
    """Convert mostly-uppercase text to Title Case, preserving Roman numerals."""
    alpha = [c for c in s if c.isalpha()]
    if not alpha:
        return s
    upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    if upper_ratio < 0.6:
        return s  # already mixed/lower case
    small = {'a', 'an', 'the', 'of', 'in', 'on', 'at', 'to',
             'for', 'and', 'but', 'or', 'nor', 'by', 'as'}
    words = s.split()
    out: list[str] = []
    for i, w in enumerate(words):
        bare = w.rstrip(':,;.!?\'"')
        if _ROMAN_RE.match(bare):
            out.append(w)                     # keep Roman numerals
        elif i == 0 or bare.lower() not in small:
            out.append(w.capitalize())
        else:
            out.append(w.lower())
    return ' '.join(out)


def _infer_title_from_text(raw: str | None) -> str | None:
    """Extract a display title from the opening of book text.

    Many BOOKMARK-class books embed their title in ALL CAPS as the first
    ``~``-delimited segment, e.g.::

        EAR OF ARRICORN: VOL. III~by Kram ~~...
        %KILLER JOKES~%by Trixter ~~...
        ADVENTURE QUARTERLY~VOL. IX~ ~...
    """
    if not raw:
        return None
    text = raw.lstrip('%')
    segs = text.split('~')
    first = segs[0].strip().rstrip(':').strip()
    if not first or len(first) < 4 or len(first) > 80:
        return None
    # Reject body-text starts (lowercase first char)
    if first[0].islower():
        return None
    title = first
    # If second segment is a volume number, combine
    if len(segs) > 1:
        second = segs[1].strip().lstrip('%').strip()
        if re.match(r'VOL\.?\s', second, re.IGNORECASE):
            title = f'{title}, {second}'
    return _title_case_smart(title)


def _improve_title(quality: int, title: str, raw_text: str | None) -> str:
    """Return a better display title when the look() bark is generic."""
    if quality in TITLE_OVERRIDES:
        return TITLE_OVERRIDES[quality]
    if _is_generic_title(title):
        inferred = _infer_title_from_text(raw_text)
        if inferred:
            return inferred
    return title


def categorize_book(title: str, quality: int) -> str:
    """Assign a category based on the book title/quality."""
    tl = title.lower()
    if 'spellbook' in tl or quality in range(0x0A, 0x16):
        return 'Sorcery Spellbooks'
    if quality in range(0x51, 0x57):
        return 'Thaumaturgy Spellbooks'
    if quality in range(0x5D, 0x67):
        return 'Theurgy Spellbooks'
    if 'guard log' in tl:
        return 'Guard Logs'
    if 'journal' in tl or 'diary' in tl or 'expedition' in tl or 'captain' in tl or 'logbook' in tl:
        return 'Journals & Logs'
    if 'letter' in tl or 'acolyte' in tl:
        return 'Letters'
    if 'saga' in tl or 'chronicle' in tl or 'history' in tl or 'moriens' in tl:
        return 'History & Lore'
    if 'mystery' in tl or 'mythology' in tl or 'destruction' in tl or 'objective history' in tl:
        return 'History & Lore'
    if 'earthen' in tl:
        return 'Necromancy'
    if 'art of flame' in tl or 'tongue of flame' in tl or 'sorcerous' in tl:
        return 'Sorcery'
    if 'reagent' in tl:
        return 'Thaumaturgy'
    if 'stratos' in tl or 'parables' in tl or 'raising' in tl:
        return 'Theurgy'
    if 'slayer' in tl or 'read me' in tl:
        return 'Quest Books'
    if 'adventure' in tl or 'mushroom' in tl or 'killer' in tl or 'arricorn' in tl:
        return 'Miscellaneous'
    return 'Books'


def _default_paths() -> tuple[str, str]:
    dialogue_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return (
        os.path.join(dialogue_root, 'foldExtract'),
        os.path.join(dialogue_root, 'json', 'books.json'),
    )


def main(argv: list[str] | None = None) -> int:
    default_fold_dir, default_out_path = _default_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument('--fold-dir', default=default_fold_dir, help='Directory containing U8P_*.txt fold output')
    parser.add_argument('--out', default=default_out_path, help='Output path for books.json')
    args = parser.parse_args(argv)

    fold_dir = os.path.abspath(args.fold_dir)
    out_path = os.path.abspath(args.out)

    basebook_src = read_fold(fold_dir, 'BASEBOOK')
    if not basebook_src:
        print('ERROR: Cannot find U8P_BASEBOOK.txt', file=sys.stderr)
        return 1

    titles = parse_look_titles(basebook_src)
    dispatch = parse_use_dispatch(basebook_src)

    # Collect all referenced classes
    class_names = set(cls for cls, _ in dispatch.values())
    func_text = extract_book_texts(fold_dir, class_names)

    # Build the books list
    all_qualities = sorted(set(list(titles.keys()) + list(dispatch.keys())))
    books = []
    text_found = 0
    text_missing = 0

    for q in all_qualities:
        raw_title = titles.get(q, f'Book (quality 0x{q:02X})')

        # Resolve raw book text (needed for title inference)
        raw_text: str | None = None
        if q in dispatch:
            cls, func = dispatch[q]
            raw_text = func_text.get(f'{cls}::{func}')

        title = _improve_title(q, raw_title, raw_text)

        entry: dict = {
            'quality': q,
            'qualityHex': f'0x{q:02X}',
            'title': title,
            'category': categorize_book(title, q),
        }

        if q in dispatch:
            cls, func = dispatch[q]
            key = f'{cls}::{func}'
            entry['source'] = key
            if key in func_text:
                raw = func_text[key]
                entry['text'] = raw
                entry['paragraphs'] = format_book_text(raw)
                text_found += 1
            else:
                # Function exists but has no Book::read (empty body, e.g. diary/journal)
                entry['text'] = None
                text_missing += 1
        else:
            entry['text'] = None
            text_missing += 1

        books.append(entry)

    output = {
        'itemClass': 'BASEBOOK',
        'description': 'All books in Ultima VIII: Pagan indexed by quality value',
        'totalBooks': len(books),
        'booksWithText': text_found,
        'books': books,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f'Wrote {out_path}')
    print(f'  Total books: {len(books)}')
    print(f'  With text: {text_found}')
    print(f'  Without text: {text_missing}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
