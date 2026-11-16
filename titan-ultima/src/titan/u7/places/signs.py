"""Text of U7 signs and plaques, read from their usecode functions."""

from __future__ import annotations

# Shapes whose usecode holds one text per quality, as sign_texts() reads it:
# {game: {shape: kind}}. A building is named from a sign before a plaque,
# because plaques also label rooms and puzzles.
SIGN_SHAPES = {
    "bg": {379: "sign", 820: "plaque"},
    "si": {379: "sign", 820: "plaque", 709: "plaque"},
}
# Hanging picture signs: no usecode and no text, the frame is the picture.
PICTURE_SIGN_SHAPES = (360, 361)
RUNE_PAIRS = {"(": "th", ")": "ee", "*": "ng", "+": "ea", ",": "st"}
# A sign ending in one of these names a street, not a building.
STREET_WORDS = {
    "road", "street", "avenue", "lane", "way", "walk", "north", "south",
    "east", "west", "hallway", "strand", "cove", "coves", "paws",
}  # fmt: skip
# A sign longer than this is an announcement and only names a building when
# nothing shorter does.
NAME_MAX_WORDS = 4
# How far (in tiles) a sign may hang from the place it names.
SIGN_REACH = 3


def decode_sign_line(line: str) -> tuple[str, bool]:
    """One sign line as plain text, and whether it was written in runes.

    Lower-case lines are drawn in the runic font, where five characters stand
    for the two-letter runes and | is a space.
    """
    runic = line != line.upper()
    if runic:
        for code, letters in RUNE_PAIRS.items():
            line = line.replace(code, letters)
        line = " ".join(w.capitalize() for w in line.replace("~", "").split("|"))
        line = " ".join(w[:1].upper() + w[1:] for w in line.split(" "))
    return line.replace("|", " ").replace("@", '"').strip(), runic


def sign_texts(usecode, shape: int) -> dict[int, tuple[str, bool]]:
    """{quality: (text, runic)} read from a sign shape's usecode function.

    The function is a chain of `quality == N` tests, each pushing the sign's
    lines (last line first) and calling the display intrinsic.
    """
    fn = usecode.get_function(shape) if usecode else None
    if fn is None:
        return {}
    data = usecode.data

    def string_at(offset):
        start = fn.data_offset + offset
        return data[start : data.index(b"\0", start)].decode("cp437")

    table: dict[int, tuple[str, bool]] = {}
    lines: list[str] = []
    quality = last_pushi = None
    for ins in fn.iter_instructions(data):
        if ins.mnemonic == "pushi":
            last_pushi = ins.operands[0]
        elif ins.mnemonic == "cmpeq":
            quality, lines = last_pushi, []
        elif ins.mnemonic.startswith("cmp"):
            quality, lines = None, []
        elif ins.mnemonic == "pushs":
            lines.append(string_at(ins.operands[0]))
        elif ins.mnemonic == "arrc" and lines:
            # The lines are gathered into one array, which signs hand
            # straight to the display intrinsic and plaques keep in a local.
            if quality is not None and quality not in table:
                decoded = [decode_sign_line(s) for s in reversed(lines)]
                text = " ".join(t for t, _ in decoded if t)
                table[quality] = (text, any(r for _, r in decoded))
            lines = []
    return table


def sign_tables(usecode, game: str) -> tuple[dict[int, str], dict[int, dict]]:
    """(kind per sign shape, texts per sign shape) for one game."""
    kinds = dict(SIGN_SHAPES[game])
    kinds.update({shape: "picture" for shape in PICTURE_SIGN_SHAPES})
    texts = {shape: sign_texts(usecode, shape) for shape in SIGN_SHAPES[game]}
    return kinds, texts
