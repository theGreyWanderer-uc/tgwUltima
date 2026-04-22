# titan-ultima

**TITAN** – Tool for Interpreting and Transforming Archival Nodes.

A Python CLI and library for working with Ultima file formats —
currently supporting *Ultima 8: Pagan* and *Ultima 7: The Black Gate /
Serpent Isle*. TITAN reads, converts, extracts, and reconstructs the
games' proprietary archive and data formats — from sprite sheets and
sound effects to full isometric world maps.

> Run `titan --help` for a full list of commands, or
> `titan u8 --help` / `titan u7 --help` for game-specific options.

---

## What TITAN can do

| Category | Capability |
|----------|-----------|
| **Archives** | Read, list, extract, create, and patch Flex (`.flx`) archives; auto-detect embedded name tables (SOUND.FLX, MUSIC.FLX) for human-readable filenames and per-record `.meta.txt` metadata sidecars |
| **Shapes** | Decode RLE-compressed sprite frames to PNG; re-import edited PNGs; create new shapes from scratch |
| **Fonts** | Interactive wizard (`font-create`) builds U7 FONTS.VGA-compatible shapes from TrueType fonts — mono, multi-shade, or hollow gradient rendering (stroke outline + vertical colour fill) with 30 gradient presets (with colour swatches), 11 stock presets (BG & SI), 6 bundled TTFs, palette LUT mapping, hex-to-palette colour resolution, ASCII art preview. Scans game directories for font archives, shows live slot tables from actual Flex data, auto-generates Exult Studio preview placeholder for non-standard glyph layouts (Gargish, Runic). Parses `exult.cfg` to auto-resolve the correct font archive path (including mod patch directories). Non-interactive batch mode via TOML config |
| **Palette** | Export the VGA 6-bit palette as a colour swatch |
| **Sound** | One-step Sonarc audio export from `SOUND.FLX` to WAV (`u8 sound-export-all`); single-file decode (`u8 sound-export`); speech FLX archives (`E44.FLX`, `E80.FLX`, …) extract dialogue transcripts + Sonarc audio; Creative Voice (.voc) decoder for U7 speech (`INTROSND.DAT`, `U7SPEECH.SPC`) |
| **Music** | One-step XMIDI→MIDI export from Flex archives (`u8 music-export`, `u7 music-export`); multi-track XMIDI support (MIDI Format 1) |
| **Maps** | **U8:** Render full isometric or top-down world maps from `FIXED.DAT` + GLOBs with engine-accurate dependency-graph depth sorting; merge live NPCs and items from save files; filter by all 16 TYPEFLAG bits; chunk coordinate grid overlay. **U7:** Render parallel-oblique world maps from `U7MAP` + `U7CHUNKS` + `SHAPES.VGA` with IFIX fixed objects and optional IREG dynamic objects; classic/flat/steep projection views; sprite-accurate dependency-DAG depth sorting; RLE terrain promotion with nearby-flat fill; colour-sampled world minimap (`map-sample`); `--full` world render; filter by TFA flags; chunk + superchunk grid overlay with coordinate labels; world-tile rectangle highlights with per-rectangle hex colours |
| **Type data** | **U8:** Decode `TYPEFLAG.DAT` shape physics/flag metadata. **U7:** Parse `TFA.DAT` flag array + `SHPDIMS.DAT` + `WGTVOL.DAT` |
| **Gumps** | Dump `GUMPAGE.DAT` container UI layout |
| **Credits** | Decrypt XOR-encoded `ECREDITS.DAT` / `QUOTES.DAT` |
| **Saves** | **U8:** List and extract entries from U8 save archives. **U7:** Read Exult `.sav` files (ZIP & FLEX formats), list/extract entries, dump global flags (`flaginit`), inspect save metadata & party (`save-info`), dump full NPC stats (`save-npcs`), dump NPC schedules (`save-schedules`) |

---

## Installation

```bash
pip install titan-ultima
```

Requires Python 3.9+, NumPy ≥ 1.24, Pillow ≥ 10.0, Typer ≥ 0.15.

---

## Getting started

### Option A — first-time wizard (recommended)

Run the interactive setup wizard once. It auto-detects your Ultima 8
installation, handles Pentagram/ScummVM save paths, writes `titan.toml`, and
optionally extracts the shape and glob archives for you.

```bash
titan setup
```

After setup, U8 map commands need no path arguments at all:

```bash
titan u8 map-render -m 5               # renders map_005_iso_classic.png
titan u8 map-render -m 0 --no-roof     # roof tiles removed
titan u8 map-render -m 39 --no-editor --no-ignore   # player-accurate
titan u8 map-render-all --maps 0 5 39 --views iso_classic iso_high
```

### Option B — manual setup (no config file)

```bash
# One-time: extract the shape and glob archives
titan flex-extract U8SHAPES.FLX -o shapes/
titan flex-extract GLOB.FLX     -o globs/

# Render an Ultima 8 map
titan u8 map-render \
  --fixed FIXED.DAT --shapes shapes/ --globs globs/ \
  --palette U8PAL.PAL --typeflag TYPEFLAG.DAT \
  --map 5 -o map_005.png
```

### Quick Ultima 7 examples

```bash
# Export a U7 shape from SHAPES.VGA
titan u7 shape-export SHAPES.VGA --shape 150 -p PALETTES.FLX -o shape_150/

# Batch-export all faces
titan u7 shape-batch FACES.VGA -p PALETTES.FLX -o faces/

# Export all 12 palettes
titan u7 palette-export PALETTES.FLX -o palettes/

# Extract U7 music to MIDI
titan u7 music-export MT32MUS.DAT -o music/
titan u7 music-export ENDSCORE.XMI -o music/

# Export U7 music rewritten for General MIDI devices (SC-55/SC-88)
# Writes .MID files, strips MT-32 SysEx, and injects GM reset
titan u7 music-export MT32MUS.DAT --target gm -o music_gm/

# Decode the Guardian's intro speech (VOC → WAV)
titan u7 voc-export INTROSND.DAT -o speech/

# Extract all speech samples from U7SPEECH.SPC
titan u7 speech-export U7SPEECH.SPC -o speech_wav/

# Render a U7 map region (superchunk 85 / 0x55 = Britain; hex and decimal both accepted)
titan u7 map-render STATIC/ --sc 0x55 -o britain.png

# Render the entire world map
titan u7 map-render STATIC/ --full -o u7_world.png

# Highlight world-tile rectangles with per-rectangle hex colours
titan u7 map-render STATIC/ --full \
  --highlight-tile-rect "2054,1698,2589,2386,#00BFFF,Moonshade" \
  --highlight-tile-rect "895,1604,1172,1959,#FF6B35,Fawn" \
  --highlight-tile-rect "670,2430,1134,2799,#7CFC00,Monitor" \
  --highlight-width 4 \
  --highlight-fill-alpha 128 \
  --highlight-lift 8 \
  --highlight-labels \
  -o u7_world_marked.png

# Use built-in zone profiles (can be combined with manual highlights)
titan u7 map-render STATIC/ --full \
  --zone-profile si_zones \
  --zone-id 3 --zone-id 13 --zone-id 14 \
  --highlight-tile-rect "2054,1698,2589,2386,#FFFFFF,Check" \
  -o u7_si_zones_subset.png

# Render all zones from a profile
titan u7 map-render STATIC/ --full --zone-profile bg_zones --all-zones -o u7_bg_regions.png

# Remove building-class shapes (roofs, windows, mountain tops)
titan u7 map-render STATIC/ --sc 85 --exclude no_building -o britain_no_roofs.png

# Remove only transparent shapes (narrower filter — mostly interior rooftops)
titan u7 map-render STATIC/ --sc 85 --exclude no_transparent -o britain_open.png

# World minimap (768×768) with superchunk grid
titan u7 map-sample STATIC/ --scale 4 --grid -o minimap.png

# Dump U7 type flag summary
titan u7 typeflag-dump STATIC/

# Export detailed per-shape reference
titan u7 typeflag-dump STATIC/ -f detail -o tfa_reference.txt

# Export as CSV for analysis
titan u7 typeflag-dump STATIC/ -f csv -o tfa_data.csv

# List entries in an Exult savegame
titan u7 save-list exult00bg.sav

# Extract all files from a save
titan u7 save-extract exult00bg.sav -o save_bg/

# Dump global flags from a save (detail format)
titan u7 gflag-dump exult00bg.sav -f detail

# Export global flags as CSV
titan u7 gflag-dump exult00bg.sav -f csv -o bg_gflags.csv

# Show save metadata: identity, party, game clock, state
titan u7 save-info exult00bg.sav

# Dump all NPC stats (use --static for reliable container detection)
titan u7 save-npcs exult00bg.sav --static STATIC/ -f detail

# Dump NPC schedules
titan u7 save-schedules exult00bg.sav -f detail

# Create a font shape interactively
titan u7 font-create

# Create a font shape from a TOML recipe (non-interactive)
titan u7 font-create --config my_font_recipe.toml -o my_font.shp
```

### Other useful commands (no config needed)

```bash
# U8 music — one step: MUSIC.FLX → MIDI (68 tracks)
titan u8 music-export MUSIC.FLX -o music_midi/

# U8 sound effects — one step: SOUND.FLX → WAV (133 effects)
titan u8 sound-export-all SOUND.FLX -o sound_wav/

# Extract speech audio (one FLX per NPC — E=English, G=German, etc.)
# record 0 = dialogue transcript (.txt), records 1+ = Sonarc audio (.raw)
titan flex-extract E44.FLX  -o speech_e44/
titan flex-extract E80.FLX  -o speech_e80/
titan u8 sound-batch speech_e44/ -o speech_e44_wav/

# Export all U8 shapes to PNG
titan u8 shape-batch shapes/ -p U8PAL.PAL -o shapes_png/
```

Run `titan <command> --help` for per-command options, or see the full
[CLI reference](cli_reference.md).

---

## Configuration (titan.toml)

`titan.toml` stores default paths so map and other commands work without
repeating long paths on every invocation. CLI flags always override config
values.

### File location

TITAN looks for the config in this order:

1. `./titan.toml` — current working directory **(recommended)**
2. `~/.config/titan/config.toml` — Linux / macOS
3. `%APPDATA%\titan\config.toml` — Windows

Use `titan --config /other/path.toml <command>` to override.

### Format

```toml
[game]
base     = "C:/ultima8"   # root of your Ultima 8 install
language = "ENGLISH"      # ENGLISH, FRENCH, GERMAN, etc.
                          # leave "" for flat mode (files directly in base/)

[paths]
# Relative paths are auto-expanded to <base>/<language>/STATIC/<name>
fixed     = "FIXED.DAT"
palette   = "U8PAL.PAL"
typeflag  = "TYPEFLAG.DAT"

# Pre-extracted directories (relative to your working directory)
shapes    = "shapes/"
globs     = "globs/"

# Live objects — relative expands to <base>/<language>/SAVEGAME/<name>
# Absolute paths (e.g. Pentagram/ScummVM) are used unchanged
nonfixed  = "U8SAVE.000"
```

A fully annotated template is available in
[`titan.toml.example`](titan.toml.example).

**Rules:**
- `language = ""` enables **flat mode** — all files expected directly in
  `base/`; useful when you copy game files to your working directory.
- `nonfixed` with an absolute path (e.g. a Pentagram save) is used as-is.
- `shapes` and `globs` are always relative to the working directory, not the
  game install.

### Inspecting the active config

```bash
titan config           # show all resolved paths with OK / NOT FOUND status
titan config --edit    # open titan.toml in your system editor
```

---

## Library quick start

TITAN is also a Python library. Every CLI command has a corresponding module.
U8-specific modules live under `titan.u8`, U7-specific under `titan.u7`.
Backward-compatible imports (e.g. `from titan.shape import U8Shape`) still work.

```python
# Flex archives (shared)
from titan.flex import FlexArchive

archive = FlexArchive.from_file("U8SHAPES.FLX")
archive.extract_all("shapes/")

# U8 shapes + palette
from titan.u8.shape import U8Shape
from titan.palette import U8Palette

pal    = U8Palette.from_file("U8PAL.PAL")
shape  = U8Shape.from_file("shapes/0001.shp")
frames = shape.to_pngs(pal)
frames[0].save("frame0.png")

# U7 shapes + palette
from titan.u7.shape import U7Shape
from titan.u7.palette import U7Palette

pal7   = U7Palette.from_file("PALETTES.FLX")
shape7 = U7Shape.from_file("POINTERS.SHP")
frames = shape7.to_pngs(pal7)
frames[0].save("pointer0.png")

# U7 music + speech
from titan.u7.music import extract_music
from titan.u7.sound import VocDecoder

extract_music("MT32MUS.DAT", "music/")           # MIDI tracks
pcm, rate = VocDecoder.decode_file("INTROSND.DAT")  # VOC → raw PCM
VocDecoder.to_wav("INTROSND.DAT", "speech/guardian.wav")

# U8 map rendering
from titan.u8.map import U8MapRenderer

renderer = U8MapRenderer(
    fixed_path    = "FIXED.DAT",
    shapes_dir    = "shapes/",
    globs_dir     = "globs/",
    palette_path  = "U8PAL.PAL",
    typeflag_path = "TYPEFLAG.DAT",
)
img = renderer.render_map(map_num=5, view="iso_classic")
img.save("map_005.png")

# U7 map rendering
from titan.u7.map import U7MapRenderer, U7MapSampler
from titan.u7.palette import U7Palette

pal7     = U7Palette.from_file("STATIC/PALETTES.FLX")
renderer = U7MapRenderer("STATIC/")
img      = renderer.render_superchunk(85, pal7)
img.save("superchunk_85.png")

minimap  = U7MapSampler.sample_map(renderer, pal7, scale=4)
minimap.save("minimap.png")

# U8 save archives
from titan.u8.save import U8SaveArchive

save = U8SaveArchive.from_file("U8SAVE.000")
for name, size in save.list_entries():
    print(f"{name}  {size:,} bytes")
```

---

## Supported formats

### Shared

| Format | Module | Game file(s) |
|--------|--------|--------------|
| Flex archive | `titan.flex` | `*.FLX` |
| XMIDI music | `titan.music` | `MUSIC.FLX`, `ENDSCORE.XMI` — single- and multi-track |

### Ultima 8

| Format | Module | Game file(s) |
|--------|--------|--------------|
| Shape sprites | `titan.u8.shape` | `U8SHAPES.FLX` → `.shp` |
| VGA palette | `titan.palette` | `U8PAL.PAL` |
| Sonarc audio | `titan.u8.sound` | `SOUND.FLX` (one-step via `u8 sound-export-all`); `E*.FLX` / `G*.FLX` → speech |
| World map (static) | `titan.u8.map` | `FIXED.DAT`, `GLOB.FLX` |
| World map (dynamic) | `titan.u8.map` | `NONFIXED.DAT` / `U8SAVE.000` |
| Type flags | `titan.u8.typeflag` | `TYPEFLAG.DAT` |
| Gump layout | (cli only) | `GUMPAGE.DAT` |
| XOR credits | `titan.u8.credits` | `ECREDITS.DAT`, `QUOTES.DAT` |
| Colour transforms | `titan.u8.xformpal` | `XFORMPAL.DAT` |
| Save archives | `titan.u8.save` | `U8SAVE.000`–`.005` |

### Ultima 7

| Format | Module | Game file(s) |
|--------|--------|--------------|
| Shape sprites | `titan.u7.shape` | `SHAPES.VGA`, `FACES.VGA`, `GUMPS.VGA`, `SPRITES.VGA`, `POINTERS.SHP` |
| Palettes | `titan.u7.palette` | `PALETTES.FLX` (12 palettes) |
| Music (MIDI) | `titan.u7.music` | `ADLIBMUS.DAT`, `MT32MUS.DAT`, `INTROADM.DAT`, `INTRORDM.DAT`, `ENDSCORE.XMI` |
| Voice / speech | `titan.u7.sound` | `INTROSND.DAT` (VOC), `U7SPEECH.SPC` (Flex of VOC) |
| World map | `titan.u7.map` | `U7MAP`, `U7CHUNKS`, `U7IFIX*`, `SHAPES.VGA`; `gamedat/u7ireg*` (optional) |
| Type flags | `titan.u7.typeflag` | `TFA.DAT`, `SHPDIMS.DAT`, `WGTVOL.DAT` |
| Save archives | `titan.u7.save` | Exult `.sav` (ZIP & FLEX): `identity`, `saveinfo.dat`, `gamewin.dat`, `schedule.dat`, `npc.dat`, `flaginit` |

---

## Game files

TITAN requires the original game files. If you own the games through GOG,
the default install locations are:

| Platform | Game | Default path |
|----------|------|--------------|
| Windows | Ultima 8 (GOG Galaxy) | `C:\Program Files (x86)\GOG Galaxy\Games\Ultima 8` |
| Windows | Ultima 8 (GOG Offline) | `C:\GOG Games\Ultima 8` |
| Windows | Ultima 7 (GOG) | `C:\GOG Games\Ultima VII\ULTIMA7` (BG), `C:\GOG Games\Ultima VII\SERPENT` (SI) |
| Linux | GOG | `~/GOG Games/Ultima 8`, `~/GOG Games/Ultima VII` |

`titan setup` auto-detects these paths and others (legacy EA/Origin disc
installs, common manual redirects such as `C:\ULTIMA8`).

### Typical GOG directory layout

```
<install root>\
├── ENGLISH\                ← language folder (FRENCH / GERMAN for other editions)
│   ├── STATIC\             ← core game data
│   │   ├── FIXED.DAT           world map static objects
│   │   ├── GLOB.FLX            reusable object groups  (extract → globs/)
│   │   ├── U8SHAPES.FLX        all sprites             (extract → shapes/)
│   │   ├── U8PAL.PAL           VGA colour palette
│   │   ├── TYPEFLAG.DAT        shape physics / flag metadata
│   │   ├── GUMPAGE.DAT         container gump UI layout
│   │   ├── XFORMPAL.DAT        colour-transform palette
│   │   ├── ECREDITS.DAT        encrypted credits text
│   │   ├── QUOTES.DAT          encrypted quote text
│   │   ├── U8FONTS.FLX         font shapes
│   │   ├── U8GUMPS.FLX         UI gump shapes
│   │   └── EINTRO.SKF / ENDGAME.SKF
│   ├── SOUND\              ← audio
│   │   ├── SOUND.FLX           sound effects  (extract → sound_raw/)
│   │   ├── MUSIC.FLX           music tracks   (extract → music_xmi/)
│   │   └── E*.FLX              language-specific voice/effects
│   └── USECODE\            ← game bytecode
│       └── EUSECODE.FLX
│
└── cloud_saves\            ← all GOG saves live here (not in the language folder)
    └── SAVEGAME\
        ├── SGHEADER.DAT        save slot names
        └── U8SAVE.000–005      save archives
```

> **Note:** GOG does not write saves into `ENGLISH\SAVEGAME\`; all save files
> go to `cloud_saves\SAVEGAME\`. `titan setup` configures the `nonfixed` path
> accordingly.

### Pentagram save locations

| Platform | Settings folder | Save file |
|----------|----------------|-----------|
| Windows | `%APPDATA%\Pentagram\` | `%APPDATA%\Pentagram\u8-save\U8SAVE.000` |
| macOS | `~/Library/Application Support/Pentagram/` | `~/Library/Application Support/Pentagram/u8-save/U8SAVE.000` |

`titan setup` detects Pentagram saves on both Windows and macOS automatically.

### Module → file reference

| TITAN module | Files needed | Location |
|---|---|---|
| `titan.flex` | Any `.flx` archive | `STATIC/` or `SOUND/` |
| `titan.palette` | `U8PAL.PAL` | `STATIC/` |
| `titan.music` | `.xmi` files (extracted) or `MUSIC.FLX` directly | `STATIC/` or output of `flex-extract` |
| `titan.u8.shape` | `.shp` files (extracted) | Output of `flex-extract U8SHAPES.FLX` |
| `titan.u8.sound` | `SOUND.FLX` directly or `.raw` files (extracted) | `STATIC/` or output of `flex-extract` |
| `titan.u8.map` | `FIXED.DAT`, `TYPEFLAG.DAT`, extracted `shapes/` + `globs/`; `U8SAVE.000` (optional) | `STATIC/`, `SAVEGAME/` |
| `titan.u8.typeflag` | `TYPEFLAG.DAT` | `STATIC/` |
| `titan.u8.credits` | `ECREDITS.DAT`, `QUOTES.DAT` | `STATIC/` |
| `titan.u8.save` | `U8SAVE.000`–`.005` | `SAVEGAME/` or `cloud_saves/SAVEGAME/` |
| `titan.u7.shape` | `SHAPES.VGA`, `FACES.VGA`, `GUMPS.VGA`, `POINTERS.SHP` | `STATIC/` |
| `titan.u7.palette` | `PALETTES.FLX` | `STATIC/` |
| `titan.u7.music` | `ADLIBMUS.DAT`, `MT32MUS.DAT`, `ENDSCORE.XMI` | `STATIC/` |
| `titan.u7.sound` | `INTROSND.DAT`, `U7SPEECH.SPC` | `STATIC/` |
| `titan.u7.map` | `U7MAP`, `U7CHUNKS`, `U7IFIX*`, `SHAPES.VGA`, `TFA.DAT`; `gamedat/u7ireg*` (optional) | `STATIC/`, `gamedat/` |
| `titan.u7.typeflag` | `TFA.DAT`, `SHPDIMS.DAT`, `WGTVOL.DAT` | `STATIC/` |

---

## Requirements

- Python 3.9+
- NumPy ≥ 1.24
- Pillow ≥ 10.0
- Typer ≥ 0.15
- tomli ≥ 2.0 *(Python < 3.11 only — for `titan.toml` support)*

---

## Credits

TITAN uses the following excellent open-source tools:

- **[LeRF](https://github.com/ddlee-cn/LeRF-PyTorch)** (Jiacheng Li, Chang Chen, et al.)  
  - *Learning Steerable Function for Efficient Image Resampling* (CVPR 2023)  
  - *LeRF: Learning Resampling Function for Adaptive and Efficient Image Interpolation* (IEEE T-PAMI 2025)  
  Adaptive downscaling and geometric transforms (rotation/skew for birdseye view) are powered by LeRF's official LUTs and NumPy implementation.

### Bundled fonts

The `font-create` wizard ships six TrueType fonts for Ultima script
systems. See [FONTS_CREDITS.md](FONTS_CREDITS.md) for full attribution
and licensing details. One font (`dosVga437-win.ttf` by VileR / int10h.org)
is distributed under [CC BY-SA 4.0](LICENSE-CC-BY-SA-4.0.txt); the
remaining five are fan recreations released under permissive terms.

---

## License

MIT

### Important note

**Ultima** (Copyright 1981–1999, Electronic Arts)

To use this fan-made tool you **must own** a legitimate copy of the
original games ([Ultima 8](https://www.gog.com/en/game/ultima_8_pagan),
[Ultima 7](https://www.gog.com/en/game/ultima_7_complete)).
This project is not affiliated with Electronic Arts. All rights to Ultima
remain with Electronic Arts.
