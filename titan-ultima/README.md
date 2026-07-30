# titan-ultima

**TITAN** - Tool for Interpreting and Transforming Archival Nodes.

TITAN is a Python CLI and library for working with proprietary data formats
from *Ultima 8: Pagan*, *Ultima 7: The Black Gate / Serpent Isle*, and
*Ultima 6: The False Prophet*. It reads, extracts, converts, inspects, and
reconstructs archives, shapes/tiles, palettes, music, speech, maps, world
objects, saves, dialogue, and Exult runtime data. Early *Ultima 9: Ascension*
support (FLX archives, `TYPENAME.FLX`, and `sound/*.flx` decoding) is also
available under `titan u9`.

Run `titan --help`, `titan u8 --help`, `titan u7 --help`, `titan u6 --help`,
`titan u9 --help`, or see the full [CLI reference](cli_reference.md).

---

## Installation

```bash
pip install titan-ultima
```

Requirements:

- Python 3.9+
- NumPy >= 1.24
- Pillow >= 10.0
- Typer >= 0.15
- questionary >= 2.0
- tomli >= 2.0 on Python < 3.11, for `titan.toml` support

Optional:

- `pyvista` (`pip install pyvista`) — only for `titan u9 model-export`'s
  auto-generated `preview.png`/`preview_front.png` renders. Without it,
  `model-export` still works; the preview step is skipped with a
  one-line note.

---

## Quick Start

Run setup once. It detects common Ultima 8 and Ultima 7 install locations,
detects Exult runtime folders and the Exult install directory (for
`exult_bg.flx` / `exult_si.flx`), writes `titan.toml`, and can extract the
U8 shape/glob data used by map rendering.

```bash
titan setup
```

After setup, many commands can use configured paths:

```bash
# U8 map render
titan u8 map-render -m 5

# U8 dialogue web viewer
titan dialogue prepare
# Optional: export NPC JSON files and META sidecars
titan dialogue copy
titan dialogue validate
titan dialogue launch

# U7 configured commands
titan u7 map-render --game bg --sc 85 -o britain_bg.png
titan u7 typeflag-dump --game si -f csv -o tfa_si.csv
titan u7 gamedat-info --game si -f detail -o gamedat_info.txt
```

`titan setup` doesn't detect Ultima 6 installs yet — add `[u6.game]
base = "<Ultima 6 install>"` to `titan.toml` yourself, or pass
`-g`/`--gamedir` explicitly on every U6 command:

```bash
titan u6 map-render -g "C:/Ultima6" --full -o u6_world.png
```

The detailed dialogue web documentation lives in
[src/titan/dialogue/websrc/READMEd.md](src/titan/dialogue/websrc/READMEd.md).

---

## Capabilities

The table below is the compact command map. The CLI reference is the canonical
place for command options, longer examples, and format notes.

| Area | Ultima 8 | Ultima 7 / Exult | Quick example | Reference |
|---|---|---|---|---|
| Archives | Flex `.FLX` list/extract/create/update | Flex/VGA-style archive support where relevant | `titan flex-list U8SHAPES.FLX` | [Flex commands](cli_reference.md#flex-archive-commands) |
| Shapes | Export/import U8 `.shp` frames | Export U7 shapes from `SHAPES.VGA`, `FACES.VGA`, etc.; render frame-sequence or colour-cycle animation to GIF via `shape-animate`; inventory a whole archive's cycling/translucency/animation content via `shape-cycle-scan` | `titan u7 shape-export SHAPES.VGA --shape 150 -p PALETTES.FLX -o shape_150/` | [U8 commands](cli_reference.md#ultima-8-commands-titan-u8), [U7 shape commands](cli_reference.md#u7-shape-commands) |
| Shape conversion | `shape-convert-u7`/`shape-convert-u7-all`: convert one or every U8 static/scenery shape into a U7/Exult-compatible shape (resize + palette requantize + hotspot-convention shift, footprint-calibrated against real U7 game data) | (target format) | `titan u8 shape-convert-u7-all STATIC/U8SHAPES.FLX --typeflag STATIC/TYPEFLAG.DAT --u7-static /path/to/u7/STATIC` | [U8 shape-convert-u7](cli_reference.md#u8-shape-convert-u7) |
| Palettes | Export U8 VGA palette | Export 12+ U7 palettes from `PALETTES.FLX`; inspect slots, semantic names, and colour-cycling via `palette-info` | `titan u7 palette-export PALETTES.FLX -o palettes/` | [U7 palette commands](cli_reference.md#u7-palette-commands) |
| Music | XMIDI to MIDI from `MUSIC.FLX` | MIDI export from `ADLIBMUS.DAT`, `MT32MUS.DAT`, `ENDSCORE.XMI`; optional GM rewrite | `titan u7 music-export MT32MUS.DAT --target gm -o music_gm/` | [U8 music commands](cli_reference.md#music-commands), [U7 music commands](cli_reference.md#u7-music-commands) |
| Sound and speech | Sonarc sound effects and speech FLX archives | Creative Voice `.voc` decode and `U7SPEECH.SPC` export | `titan u7 speech-export U7SPEECH.SPC -o speech_wav/` | [Sound commands](cli_reference.md#sound-commands), [U7 voice commands](cli_reference.md#u7-voice--speech-commands) |
| Dialogue web | Prepare, optionally copy NPC JSON/META files, validate, and launch the U8 dialogue web machine | Not applicable | `titan dialogue launch` | [Dialogue CLI](cli_reference.md#dialogue-commands-titan-dialogue), [Dialogue README](src/titan/dialogue/websrc/READMEd.md) |
| Maps | Render U8 isometric/top-down maps from `FIXED.DAT`, GLOBs, shapes, saves | Render U7 maps from `U7MAP`, `U7CHUNKS`, `U7IFIX*`, `SHAPES.VGA`, optional `u7ireg*` | `titan u7 map-render STATIC/ --full -o u7_world.png` | [U8 map commands](cli_reference.md#u8-map-commands), [U7 map commands](cli_reference.md#u7-map-commands) |
| Type data | Decode U8 `TYPEFLAG.DAT` | Decode U7 `TFA.DAT`, `SHPDIMS.DAT`, `WGTVOL.DAT`, `OCCLUDE.DAT` | `titan u7 typeflag-dump STATIC/ -f csv -o tfa_data.csv` | [U8 data commands](cli_reference.md#u8-data-inspection-commands), [U7 type flag commands](cli_reference.md#u7-type-flag-commands) |
| Saves and runtime data | List/extract U8 save archives | Read Exult `.sav`; inspect loose `gamedat/`; dump NPCs, schedules, flags | `titan u7 save-info exult00bg.sav` | [U8 save commands](cli_reference.md#u8-save-archive-commands), [U7 save commands](cli_reference.md#u7-save-commands) |
| Fonts | U8 font archives can be extracted as Flex data | U7 `font-create` wizard for Exult-compatible font shapes | `titan u7 font-create` | [U7 font-create](cli_reference.md#u7-font-create) |
| World query | Not applicable | Interactive wizard to filter IFIX/IREG object placements by shape class, number, TFA flags, and area | `titan u7 world-query --game bg` | [U7 world-query](cli_reference.md#u7-world-query) |
| Container data | Not applicable | Browse IREG container contents with full nesting; filter by container name, item name, or tile area; optional per-frame item names via Exult FLX | `titan u7 container-browse --game bg --container-name chest` | [U7 container-browse](cli_reference.md#u7-container-browse) |
| Egg data | Not applicable | Query IREG egg trigger objects — type, usecode function, probability, location | `titan u7 egg-query --game bg --type usecode` | [U7 egg-query](cli_reference.md#u7-egg-query) |
| Text and misc data | Gump layout, XOR credits, quotes, transform palettes | Global flags and selected runtime metadata | `titan u8 credits-decrypt ECREDITS.DAT` | [U8 data commands](cli_reference.md#u8-data-inspection-commands) |

### Ultima 6

U6 support covers reading (and limited save-editing of) the full game: tiles,
world/dungeon maps, world objects and eggs, actors, party/game state, story
flags, dialogue, and text/reference data.

| Area | Coverage | Quick example |
|---|---|---|
| Archives | LZW decompression; `lib_16`/`lib_32` library files (`CONVERSE.A/B`, etc.) | `titan u6 lib-list CONVERSE.A` |
| Graphics | Tiles (plain/transparent/pixel-block), palette, `TILEFLAG` terrain/object metadata | `titan u6 tile-export-all -g "<install>" -o tiles_png/` |
| Maps | Surface world and dungeon-level rendering, animated tiles, correct multi-tile object compositing, optional world-object overlay | `titan u6 map-render -g "<install>" --full -o u6_world.png` |
| World objects | Object placement with container/inventory resolution; eggs (spawn probability/target); the 256-actor identity table | `titan u6 object-list -g "<install>" --block 5` |
| Story and saves | Party roster, player state, clock/weather; read/compare/write per-NPC talk flags and global quest state, including writing changes back to a save | `titan u6 gamestate-dump -g "<install>/SAVEGAME"` |
| Dialogue | `CONVERSE.A/B` bytecode disassembler, with known global variables annotated by name | `titan u6 converse-dump CONVERSE.A --item 5` |
| Text and reference data | Fonts (English + runic/gargoyle); object names; books/signs; NPC daily schedules | `titan u6 book-dump BOOK.DAT --book 0` |

See the [U6 commands reference](cli_reference.md#ultima-6-commands-titan-u6)
for the full command list.

### Ultima 9 (early)

U9 support is newer and narrower in scope than U8/U7 so far — FLX archives,
`TYPENAME.FLX`, `sound/*.flx` (`Speech.flx`, `sfx.flx`, `music.flx`) decoding
(EA-XA ADPCM, mono and stereo, and EA MicroTalk speech), and 3D model +
texture export from `static/sappear.flx`.

| Area | Coverage | Quick example |
|---|---|---|
| Archives | List/extract any U9 `.flx`/`.FLX` archive | `titan u9 flx-list sound/Speech.flx` |
| Metadata | Decode `TYPENAME.FLX` type-ID → name pairs | `titan u9 typename-dump static/TYPENAME.FLX` |
| Sound and speech | Decode `Speech.flx`/`sfx.flx`/`music.flx` to WAV (PCM, mono/stereo ADPCM, EA MicroTalk) | `titan u9 sound-extract sound/Speech.flx -o speech_wav/` |
| 3D models and textures | Export `sappear.flx` models (limb hierarchy, LODs, materials) to textured OBJ+MTL+PNG or geometry-only STL, with real palette colors for 8-bit textures, optional naming via `TYPES.DAT`/`TYPENAME.FLX` (e.g. `model_01805_lord-british`), and two auto-generated preview renders, front and back (needs the optional `pyvista` package) | `titan u9 model-export static/sappear.flx 2 -t static/bitmap16.flx -o model_2/` |
| 2D UI icons | List/export the standalone 2D icons (spell-rune sigils, item icons, ...) mixed into the same `bitmap16.flx`/`bitmapC.flx`/`bitmapsh.flx` archives as 3D model textures -- identified as the entries no `sappear.flx` model ever references, kept in a separate module/command group/output dir from the mesh commands above | `titan u9 icon-export-all static/sappear.flx static/bitmapsh.flx -p static/ankh.pal -o icon_export/` |

See the [U9 commands reference](cli_reference.md#ultima-9-commands-titan-u9)
for the full command list.

---

## Common Workflows

### U8 Dialogue Web

```bash
titan dialogue prepare
# Optional NPC export step
titan dialogue copy
titan dialogue validate
titan dialogue launch
```

For setup, local development, export behavior, and known dialogue-machine
limits, see the dedicated
[dialogue web README](src/titan/dialogue/websrc/READMEd.md).

### U7 Exult Runtime Inspection

```bash
# Inspect configured Serpent Isle GAMEDAT, including mod fallback sources.
titan u7 gamedat-info --game si -f detail

# Inspect a mod's packaged patch/initgame.dat archive directly.
titan u7 gamedat-info mods/<mod-name>/patch/initgame.dat --static STATIC/

# Inspect a specific Exult save archive.
titan u7 save-info exult00si.sav
titan u7 save-npcs exult00si.sav --static STATIC/ -f detail
titan u7 save-schedules exult00si.sav -f detail
```

### U7 Map Rendering

```bash
# Superchunk render.
titan u7 map-render STATIC/ --sc 0x55 -o superChunk_85.png

# Full world render.
titan u7 map-render STATIC/ --full -o u7_world.png

# Minimap sample with grid.
titan u7 map-sample STATIC/ --scale 4 --grid -o minimap.png
```

### U7 World Query

```bash
# Interactive wizard — walks through shape class, flag, and area filters.
titan u7 world-query --game bg

# With explicit paths (no titan.toml required).
titan u7 world-query STATIC/ --gamedat gamedat/

# Pre-set STATIC from config, add a runtime GAMEDAT for IREG objects.
titan u7 world-query --game si --gamedat Exult/serpentisle/gamedat
```

The wizard prompts for shape-class checkboxes, optional shape numbers, TFA flag
checkboxes, area (all or specific superchunks), and output format (summary /
full text / CSV). Output can be printed or saved to a file.

### U7 Container Browse

```bash
# Interactive wizard — configured BG paths.
titan u7 container-browse --game bg

# Show all chests with their full contents tree.
titan u7 container-browse STATIC/ --gamedat gamedat/ --container-name chest

# Find containers holding a sword.
titan u7 container-browse STATIC/ --gamedat gamedat/ --contains-name sword

# Export to CSV with per-frame item names (requires Exult installation).
titan u7 container-browse STATIC/ --gamedat gamedat/ -f csv -o containers.csv \
  --exult-flx "<Exult install>/data/exult_bg.flx"

# Configured paths with per-frame names from titan.toml [exult.paths].
titan u7 container-browse --game bg --container-name desk
```

### U7 Egg Query

```bash
# Interactive wizard — configured BG paths.
titan u7 egg-query --game bg

# All usecode eggs.
titan u7 egg-query STATIC/ --gamedat gamedat/ --type usecode

# Find every placement of a specific usecode function.
titan u7 egg-query STATIC/ --gamedat gamedat/ --fn 0x06BC

# Export usecode eggs to CSV.
titan u7 egg-query STATIC/ --gamedat gamedat/ --type usecode -f csv -o usecode_eggs.csv
```

### U8 Map Rendering

```bash
titan u8 map-render -m 5
titan u8 map-render -m 0 --no-roof
titan u8 map-render-all --maps 0 5 39 --views iso_classic iso_high
```

### U6 World Rendering

```bash
# One surface superchunk, with world objects (furniture, items, etc.) overlaid.
titan u6 map-render -g "C:/Ultima6" --region 0,0,64,64 --objects -o chunk0.png

# A dungeon level.
titan u6 map-render -g "C:/Ultima6" --dungeon 0 --objects -o dungeon0.png

# The entire surface world.
titan u6 map-render -g "C:/Ultima6" --full -o u6_world.png
```

### U9 Sound Extraction

```bash
# List an archive's decoded entry headers first.
titan u9 sound-list sound/Speech.flx

# Decode every supported entry to WAV (PCM, mono/stereo ADPCM, EA MicroTalk).
titan u9 sound-extract sound/Speech.flx -o speech_wav/
titan u9 sound-extract sound/sfx.flx -o sfx_wav/
titan u9 sound-extract sound/music.flx -o music_wav/
```

### U9 3D Model Export

```bash
# Inspect a model's limb/LOD/material/texture summary first.
titan u9 model-info static/sappear.flx 2

# Export a textured OBJ (+ MTL + PNG textures) -- bitmap16.flx covers every
# real texture referenced by any model in this project's test copy of the game.
# preview.png (back-ish) + preview_front.png (rotated 180 degrees) are rendered
# alongside it automatically (needs `pip install pyvista`).
titan u9 model-export static/sappear.flx 2 -t static/bitmap16.flx -o model_2/

# Add real palette colors for any 8-bit textures instead of flat grayscale.
titan u9 model-export static/sappear.flx 2 -t static/bitmapsh.flx -p static/ankh.pal -o model_2/

# Geometry-only STL, no textures or preview needed.
titan u9 model-export static/sappear.flx 2 -f stl --no-preview -o model_2_stl/
```

---

## Configuration

`titan.toml` stores default paths so commands can run without long path
arguments. Command-line options always override config values.

Config search order:

1. `./titan.toml`
2. `~/.config/titan/config.toml`
3. User profile folder `titan\config.toml`

Use `titan --config <other config.toml> <command>` to override.

Minimal multi-game shape:

```toml
[u8.game]
base     = "<Ultima 8 install>"
language = "ENGLISH"

[u8.paths]
fixed    = "FIXED.DAT"
palette  = "U8PAL.PAL"
typeflag = "TYPEFLAG.DAT"
shapes   = "shapes/"
globs    = "globs/"
nonfixed = "U8SAVE.000"

[u7bg.game]
base    = "<Black Gate install>/ULTIMA7"
variant = "blackgate"

[u7bg.paths]
static  = "STATIC/"
shapes  = "STATIC/SHAPES.VGA"
palette = "STATIC/PALETTES.FLX"
gamedat = "gamedat/"

[u7si.game]
base    = "<Serpent Isle install>/SERPENT"
variant = "serpentisle"

[u7si.paths]
static  = "STATIC/"
shapes  = "STATIC/SHAPES.VGA"
palette = "STATIC/PALETTES.FLX"
gamedat = "gamedat/"

[u7si.mods."<mod-name>".paths]
root    = "<User profile>/Exult/serpentisle/mods/<mod-name>"
saves   = "<User profile>/Exult/serpentisle/mods/<mod-name>/saves"
gamedat = "<User profile>/Exult/serpentisle/mods/<mod-name>/gamedat"
archive = "<Serpent Isle install>/SERPENT/mods/<mod-name>/patch/initgame.dat"

[exult.paths]
bg_flx  = "<Exult install>/data/exult_bg.flx"
si_flx  = "<Exult install>/data/exult_si.flx"
```

Notes:

- `titan setup` writes this file for you.
- U8 relative paths expand from the configured U8 install and language folder,
  except `shapes` and `globs`, which are local working directories.
- U7 `gamedat` should usually point at Exult's initialized runtime copy when
  available.
- U7 mod `saves` is discovered by scanning the mod profile root recursively for
  `.sav` files and choosing the folder with the most saves.
- A fully annotated template is available in
  [titan.toml.example](titan.toml.example).
- Full config details are in
  [cli_reference.md#configuration-titantoml](cli_reference.md#configuration-titantoml).

Inspect the active config:

```bash
titan config
titan config --edit
```

---

## Library Use

TITAN can also be imported as a Python library. U8 modules live under
`titan.u8`; U7 modules live under `titan.u7`; U6 modules live under
`titan.u6`; early U9 modules live under `titan.u9`. Backward-compatible
imports such as `from titan.shape import U8Shape` are still supported.

```python
from titan.u7.flex import U7FlexArchive
from titan.u7.palette import U7Palette
from titan.u7.shape import U7Shape

archive = U7FlexArchive.from_file("SHAPES.VGA")
shape = U7Shape.from_data(archive.get_record(150))
palette = U7Palette.from_file("PALETTES.FLX")
shape.to_pngs(palette)[0].save("shape_150_frame0.png")
```

---

## Supported File Families

| Family | Ultima 8 | Ultima 7 / Exult |
|---|---|---|
| Archives | `*.FLX`, speech FLX archives | Flex/VGA archives, Exult ZIP/FLEX saves |
| Shapes | `U8SHAPES.FLX`, `U8FONTS.FLX`, `U8GUMPS.FLX` | `SHAPES.VGA`, `FACES.VGA`, `GUMPS.VGA`, `SPRITES.VGA`, `POINTERS.SHP`, generated font shapes |
| Palettes | `U8PAL.PAL`, `XFORMPAL.DAT` | `PALETTES.FLX` |
| Audio | `SOUND.FLX`, `MUSIC.FLX`, `E*.FLX` / `G*.FLX` | `ADLIBMUS.DAT`, `MT32MUS.DAT`, `ENDSCORE.XMI`, `INTROSND.DAT`, `U7SPEECH.SPC` |
| Maps | `FIXED.DAT`, `GLOB.FLX`, `NONFIXED.DAT`, `U8SAVE.000` | `U7MAP`, `U7CHUNKS`, `U7IFIX*`, `SHAPES.VGA`, `gamedat/u7ireg*` |
| Type and object data | `TYPEFLAG.DAT`, `GUMPAGE.DAT` | `TFA.DAT`, `SHPDIMS.DAT`, `WGTVOL.DAT`, `OCCLUDE.DAT`, `npc.dat`, `schedule.dat`, `flaginit` |
| Text | `ECREDITS.DAT`, `QUOTES.DAT` | Selected Exult save/runtime metadata |

---

## Game Files

TITAN requires the original game files. You must own a legitimate copy of the
games. `titan setup` checks common GOG, EA/Origin, manual, Pentagram, ScummVM,
and Exult paths.

Typical GOG, EA/Origin, manual, ScummVM/Pentagram, and Exult folders are
auto-detected where possible. If setup cannot find a game, enter the game's
base folder manually when prompted.

---

## Documentation

- [CLI reference](cli_reference.md)
- [Dialogue web README](src/titan/dialogue/websrc/READMEd.md)
- [Annotated config template](titan.toml.example)
- [Font credits](FONTS_CREDITS.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

---

## Credits

TITAN uses the following excellent open-source tools:

- [LeRF](https://github.com/ddlee-cn/LeRF-PyTorch) by Jiacheng Li, Chang Chen,
  et al. Adaptive downscaling and geometric transforms are powered by LeRF's
  official LUTs and NumPy implementation.

The `font-create` wizard ships six TrueType fonts for Ultima script systems.
See [FONTS_CREDITS.md](FONTS_CREDITS.md) for full attribution and licensing
details.

---

## License

MIT

TITAN also distributes a modified `fold` component derived from the Pentagram
project as part of dialogue tooling. That component is licensed under
**GNU GPL v2 or later** and is **not** covered by TITAN's MIT license.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and
`src/titan/third_party/fold/` for attribution, license scope, source mapping,
build entry points, and bundled GPL license text.

**Ultima** (Copyright 1981-1999, Electronic Arts)

This fan-made tool requires a legitimate copy of the original games:
[Ultima 8](https://www.gog.com/en/game/ultima_8_pagan) and
[Ultima 7](https://www.gog.com/en/game/ultima_7_complete). This project is not
affiliated with Electronic Arts. All rights to Ultima remain with Electronic
Arts.
