"""Native Pagan palette inspection, DOS palette effects and exclusive exports.

Effects reproduce FadeProcess::initPal in the decoded U8 source (U8/PAL.C),
using stored six-bit components before scaling to display RGB. They are target
palettes, not an emulation of fade timing or Pentagram's approximate matrices.
"""

from __future__ import annotations

import csv
import html
import io
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from titan.palette import U8Palette
from titan.u8.shape_browser import configured_u8_browser_file, find_u8_browser_file
from titan.u8.xformpal import U8_XFORM_PALETTE

U8_PALETTE_BROWSER_OUTPUT = Path("titan-out/u8_palette_browse_export")
U8_PALETTE_EFFECTS = (
    "Normal",
    "Greyscale",
    "No red",
    "Rain storm",
    "Fire storm",
    "Saturate",
    "GBR shift",
    "BRG shift",
)


def resolve_u8_palette_source(static: Path) -> Path:
    """Resolve only the selected owner's palette, never a different language."""
    path = configured_u8_browser_file(static, "palette") or find_u8_browser_file(
        static, "U8PAL.PAL"
    )
    if path is None:
        raise FileNotFoundError(f"No U8PAL.PAL in {static}")
    return path


def u8_palette_role(index: int) -> str:
    """Sprite transparency and Pentagram blend slots are separate semantics."""
    if not 0 <= index <= 255:
        raise ValueError("Palette index must be within 0-255")
    if index == 255:
        return "transparent in decoded U8 sprites; stored RGB shown"
    if 8 <= index <= 14:
        return "colour; Pentagram blend slot when translucent painting is enabled"
    return "colour"


def _effect_rgb(rgb: tuple[int, int, int], effect: int) -> tuple[int, int, int]:
    red, green, blue = rgb
    grey = min(63, (red * 3 + green * 4 + blue * 2 + 4) >> 3)
    if effect == 1:
        return grey, grey, grey
    if effect == 2:
        return 0, green, blue
    if effect == 3:
        return (
            ((red + grey) >> 2) + 12,
            ((green + grey) >> 2) + 12,
            ((blue + grey) >> 2) + 12,
        )
    if effect == 4:
        return min(63, ((red + grey) >> 1) + 12), (green + (grey >> 1)) >> 1, blue >> 1
    if effect == 5:
        return (
            max(0, min(63, red * 2 - grey)),
            max(0, min(63, green * 2 - grey)),
            max(0, min(63, blue * 2 - grey)),
        )
    if effect == 6:
        return green, blue, red
    if effect == 7:
        return blue, red, green
    return rgb


@dataclass(frozen=True)
class U8PaletteSource:
    path: Path
    raw: bytes
    components: tuple[tuple[int, int, int], ...]
    encoding: str
    protected: tuple[Path, ...]

    @classmethod
    def load(cls, path: Path, *, protected: tuple[Path, ...] = ()) -> U8PaletteSource:
        """Read both file layouts accepted by native FilePalette::read."""
        path = path.expanduser().resolve()
        raw = path.read_bytes()
        if len(raw) == 772:
            values = tuple(raw[4:])
            encoding = "6-bit byte RGB with 4-byte header"
        elif len(raw) == 1536:
            values = struct.unpack("<768H", raw)
            encoding = "6-bit little-endian word RGB"
        else:
            raise ValueError(
                f"Native U8 palette must be 772 or 1536 bytes; got {len(raw)}"
            )
        if any(value > 63 for value in values):
            raise ValueError("Native U8 palette components must be within 0-63")
        components = tuple(
            (values[index], values[index + 1], values[index + 2])
            for index in range(0, 768, 3)
        )
        roots = [path.parent, *protected]
        if path.parent.name.casefold() == "static":
            roots.append(path.parent.parent)
            if path.parent.parent.name.casefold() in {"english", "french", "german"}:
                roots.append(path.parent.parent.parent)
        return cls(
            path, raw, components, encoding, tuple(root.resolve() for root in roots)
        )

    def palette(self, effect: int = 0) -> U8Palette:
        if not 0 <= effect < len(U8_PALETTE_EFFECTS):
            raise ValueError("U8 palette effect must be within 0-7")
        palette = U8Palette()
        palette.transparent_index = 255
        palette.colors = []
        for rgb in self.components:
            red, green, blue = _effect_rgb(rgb, effect)
            palette.colors.append(
                (red * 255 // 63, green * 255 // 63, blue * 255 // 63)
            )
        return palette

    def rows(self, effect: int = 0) -> list[dict[str, object]]:
        palette = self.palette(effect)
        return [
            {
                "index": index,
                "index_hex": f"0x{index:02x}",
                "effect": U8_PALETTE_EFFECTS[effect],
                "raw_r": raw[0],
                "raw_g": raw[1],
                "raw_b": raw[2],
                "r": rgb[0],
                "g": rgb[1],
                "b": rgb[2],
                "hex": "#{:02x}{:02x}{:02x}".format(*rgb),
                "role": u8_palette_role(index),
                "pentagram_blend_rgba": (
                    ",".join(map(str, U8_XFORM_PALETTE[index]))
                    if 8 <= index <= 14
                    else ""
                ),
            }
            for index, (raw, rgb) in enumerate(zip(self.components, palette.colors))
        ]


def nearest_u8_palette_indices(
    palette: U8Palette, rgb: tuple[int, int, int], count: int = 5
) -> list[int]:
    """Squared RGB distance, excluding the sprite transparency sentinel."""
    if len(rgb) != 3 or any(not 0 <= value <= 255 for value in rgb):
        raise ValueError("RGB components must be within 0-255")
    if not 1 <= count <= 255:
        raise ValueError("Match count must be within 1-255")
    return sorted(
        range(255),
        key=lambda index: (
            sum((a - b) ** 2 for a, b in zip(rgb, palette.colors[index])),
            index,
        ),
    )[:count]


def u8_palette_sheet(palette: U8Palette) -> Image.Image:
    """Numbered swatches at integer pixel dimensions, with stored index 255 RGB."""
    image = Image.new("RGB", (768, 512))
    draw = ImageDraw.Draw(image)
    for index, rgb in enumerate(palette.colors):
        row, column = divmod(index, 16)
        x, y = column * 48, row * 32
        draw.rectangle((x, y, x + 47, y + 31), fill=rgb)
        ink = (
            "black"
            if sum(a * b for a, b in zip(rgb, (299, 587, 114))) >= 128000
            else "white"
        )
        draw.text((x + 8, y + 10), f"{index:03d}", fill=ink)
    return image


def validate_u8_palette_output(source: U8PaletteSource, output: Path) -> None:
    resolved = output.resolve()
    if any(resolved == root or root in resolved.parents for root in source.protected):
        raise ValueError("Choose an output outside the palette's game/source folders")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")


def next_u8_palette_export(source: U8PaletteSource, output: Path, effect: int) -> Path:
    """Use a fresh numbered folder for every export, preserving older reports."""
    stem = f"{source.path.stem.lower()}_effect_{effect}"
    number = 1
    while (output / f"{stem}_{number:03d}").exists():
        number += 1
    target = output / f"{stem}_{number:03d}"
    validate_u8_palette_output(source, target)
    return target


def export_u8_palette_bundle(
    source: U8PaletteSource, output: Path, effect: int = 0
) -> Path:
    """Write a fresh HTML/CSV/JSON/PNG/original-PAL bundle with all eight effects."""
    validate_u8_palette_output(source, output)
    rows = source.rows(effect)
    metadata: dict[str, object] = {
        "source": str(source.path),
        "encoding": source.encoding,
        "header_hex": source.raw[:4].hex(" ") if len(source.raw) == 772 else None,
        "byte_count": len(source.raw),
        "selected_effect": effect,
        "effects": U8_PALETTE_EFFECTS,
        "colours": rows,
        "all_effects": [source.rows(index) for index in range(8)],
        "effect_provenance": "Decoded U8_SRC/source/U8/PAL.C FadeProcess::initPal; 6-bit target palettes",
        "blend_provenance": "Pentagram graphics/XFormBlend.cpp; not XFORMPAL.DAT lookup tables",
    }
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    report = _palette_html(metadata)
    output.mkdir(parents=True, exist_ok=False)
    (output / "effects").mkdir()
    for index in range(8):
        u8_palette_sheet(source.palette(index)).save(
            output / "effects" / f"effect_{index}.png"
        )
    u8_palette_sheet(source.palette(effect)).save(output / "palette.png")
    (output / "original.pal").write_bytes(source.raw)
    (output / "palette.csv").write_text(buffer.getvalue(), encoding="utf-8")
    (output / "palette.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    (output / "index.html").write_text(report, encoding="utf-8")
    return output / "index.html"


def _palette_html(metadata: dict[str, object]) -> str:
    data = json.dumps(metadata).replace("<", "\\u003c")
    source = html.escape(str(metadata["source"]))
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<title>U8 palette browser</title><style>
body{font:16px system-ui;background:#17191b;color:#eee;margin:2em;max-width:1200px}
a{color:#9bd3ff}select,input{font:inherit;margin:.5em;padding:.3em}
#grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.swatch{border:1px solid #555;padding:8px}.colour{height:36px;margin-bottom:6px}
small{display:block}img{max-width:100%;image-rendering:pixelated}
</style><h1>Ultima VIII palette</h1><p>"""
        + source
        + """</p>
<p>Effects reproduce the DOS target palettes. Fade timing is not simulated.
Index 255 is transparent in decoded sprites; this report shows its stored RGB.
Blend values at 8–14 describe Pentagram's optional translucent painting.</p>
<p><a href="palette.csv">CSV (exported effect)</a> · <a href="palette.json">JSON (all effects)</a> ·
<a href="original.pal">Original palette bytes</a> · <a href="palette.png">Exported sheet</a></p>
<label>Effect <select id="effect"></select></label>
<label>Find index, hex or role <input id="search" type="search"></label>
<p id="count"></p><div id="grid"></div><details><summary>Numbered PNG sheet</summary>
<img id="sheet" alt="256 numbered palette swatches"></details>
<script id="data" type="application/json">"""
        + data
        + """</script><script>
const data=JSON.parse(document.getElementById('data').textContent);
const effect=document.getElementById('effect'), search=document.getElementById('search');
data.effects.forEach((name,i)=>{const o=document.createElement('option');o.value=i;o.textContent=i+': '+name;effect.append(o)});
effect.value=data.selected_effect;
function render(){const grid=document.getElementById('grid');grid.replaceChildren();
const rows=data.all_effects[Number(effect.value)].filter(r=>[r.index,r.index_hex,r.hex,r.role].join(' ').toLowerCase().includes(search.value.toLowerCase()));
rows.forEach(r=>{const card=document.createElement('div');card.className='swatch';
const colour=document.createElement('div');colour.className='colour';colour.style.backgroundColor=r.hex;card.append(colour);
const label=document.createElement('b');label.textContent=r.index+' / '+r.index_hex+' '+r.hex;card.append(label);
['RGB '+r.r+', '+r.g+', '+r.b,'Stored '+r.raw_r+', '+r.raw_g+', '+r.raw_b,r.role,
r.pentagram_blend_rgba?'Pentagram RGBA '+r.pentagram_blend_rgba:''].filter(Boolean).forEach(t=>{const s=document.createElement('small');s.textContent=t;card.append(s)});grid.append(card)});
document.getElementById('count').textContent=rows.length+' / 256 colours';
document.getElementById('sheet').src='effects/effect_'+effect.value+'.png'}
effect.addEventListener('change',render);search.addEventListener('input',render);render();
</script></html>"""
    )
