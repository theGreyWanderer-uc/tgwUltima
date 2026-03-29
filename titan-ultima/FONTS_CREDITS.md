# Bundled Font Credits

TITAN bundles six TrueType font files for creating U7-compatible font
shapes. These fonts are **not** covered by TITAN's MIT license — each
retains its own licensing terms as described below.

The font files live in `src/titan/fonts/bundled/`.

---

## Ultima Fan Fonts — thealmightyguru.com

The following five fonts are fan-made TTF recreations of bitmap writing
systems from the classic Ultima series, hosted at Dean Tersigni's
**Game Font Database**:

> <https://www.thealmightyguru.com/GameFonts/Series-Ultima.html>

Per the site's stated policy, these fonts may be **copied, used, edited,
and redistributed without permission or attribution** (credit is
appreciated but not required), including for commercial projects.
The original font creators include the note *"To be distributed freely"*
in the TTF metadata.

| File | Creator | Script | Used for |
|------|---------|--------|----------|
| `Gargish.ttf` | Jim Sorenson | Gargish language | SI Gargish dialogue font |
| `Ophidean Runes.ttf` | Jim Sorenson | Ophidean / Serpentine | SI book & sign text |
| `Britannian Runes I.ttf` | Fan recreation | Britannian runes (signs) | BG/SI runic sign lettering |
| `Britannian Runes II.ttf` | Fan recreation | Britannian runes (serif) | BG/SI large runic plaques |
| `Britannian Runes II Sans Serif.ttf` | Fan recreation | Britannian runes (sans) | BG/SI compact runic text |

**Thank you** to Dean Tersigni (thealmightyguru.com) for maintaining the
Game Font Database, and to Jim Sorenson for creating the Gargish and
Ophidean Runes fonts.

---

## Oldschool PC Font — int10h.org

The following font is from the **Ultimate Oldschool PC Font Pack** by
VileR:

> <https://int10h.org/oldschool-pc-fonts/>

| File | Description | Used for |
|------|-------------|----------|
| `dosVga437-win.ttf` | IBM VGA 9×16, codepage 437 | English text (slots 0, 2, 4, 5, 7) |

### License: Creative Commons Attribution-ShareAlike 4.0 International

The TTF remakes and enhancements are licensed under
**CC BY-SA 4.0** by VileR. The original DOS-era bitmap data is
in the public domain (credit to the original hardware/firmware
designers).

The full CC BY-SA 4.0 license text is included alongside this file as
[`LICENSE-CC-BY-SA-4.0.txt`](LICENSE-CC-BY-SA-4.0.txt).

**Summary of terms:**

- You may freely share and adapt/transform/enhance for any purpose,
  including commercial use.
- You **must** give appropriate credit (VileR + link to int10h.org).
- If you distribute your own adaptations, they must be under a
  compatible license.
- No warranties.

**Thank you** to VileR for the meticulous pixel-accurate TTF remakes of
classic PC fonts.

---

## Note on derivative works

These fonts are derivative works of Ultima's in-game writing systems
(historically owned by Origin Systems / Electronic Arts). The
fan/modding community has distributed these recreations for decades
without enforcement, and TITAN's use case — converting TTF glyphs to
bitmap font shapes for the original games — is exactly the kind of
personal/fan use the fonts were intended for.

The generated bitmap output (`.shp` files) inherits the licensing terms
of the source font used to create it. For the Ultima fan fonts this is
unrestricted; for the int10h font the CC BY-SA 4.0 terms apply to
distributed derivatives.
