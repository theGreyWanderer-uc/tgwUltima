# titan-ultima

**TITAN** – Tool for Interpreting and Transforming Archival Nodes.

A Python CLI and library for working with *Ultima 8: Pagan* file formats.
TITAN reads, converts, extracts, and reconstructs the game's proprietary
archive and data formats — from sprite sheets and sound effects to full
isometric world maps.

> Run `titan --help` for a full list of commands, or `titan <command> --help`
> for per-command options.

---

## What TITAN can do

| Category | Capability |
|----------|-----------|
| **Archives** | Read, list, extract, create, and patch Flex (`.flx`) archives; auto-detect embedded name tables (SOUND.FLX, MUSIC.FLX) for human-readable filenames and per-record `.meta.txt` metadata sidecars |
| **Shapes** | Decode RLE-compressed sprite frames to PNG; re-import edited PNGs |
| **Palette** | Export the VGA 6-bit palette as a colour swatch |
| **Sound** | Decode Sonarc-compressed audio (`.raw`) to WAV; extracted files named from SOUND.FLX name table (e.g. `0007_TELEPORT.raw`); speech FLX archives (`E44.FLX`, `E80.FLX`, …) extract dialogue transcripts + Sonarc audio |
| **Music** | Convert XMIDI (`.xmi`) to standard MIDI |
| **Maps** | Render full isometric or top-down world maps from `FIXED.DAT` + GLOBs with engine-accurate dependency-graph depth sorting; merge live NPCs and items from save files; filter by all 16 TYPEFLAG bits (fixed, solid, sea, land, occl, bag, damaging, noisy, draw, ignore, roof, transl, editor, explode, unk46, unk47) |
| **Type data** | Decode `TYPEFLAG.DAT` shape physics/flag metadata |
| **Gumps** | Dump `GUMPAGE.DAT` container UI layout |
| **Credits** | Decrypt XOR-encoded `ECREDITS.DAT` / `QUOTES.DAT` |
| **Saves** | List and extract entries from U8 save archives |

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

The wizard will:

1. Search common GOG, Origin, and disc install paths for `FIXED.DAT`
2. Ask you to confirm (or enter) the base path and language folder
3. Detect `%APPDATA%\Pentagram\u8-save\U8SAVE.000` and offer to use it as the
   live-object source
4. Write `titan.toml` in your current directory
5. Optionally run `flex-extract` to populate `shapes/` and `globs/`

After setup, map commands need no path arguments at all:

```bash
titan map-render -m 5               # renders map_005_iso_classic.png
titan map-render -m 0 --no-roof     # roof tiles removed
titan map-render -m 39 --no-editor --no-ignore   # player-accurate (no eggs/markers)
titan map-render-all --maps 0 5 39 --views iso_classic iso_high
```

### Option B — manual setup (no config file)

If you prefer to supply explicit paths on every command, TITAN works without a
config file too:

```bash
# One-time: extract the shape and glob archives
titan flex-extract U8SHAPES.FLX -o shapes/
titan flex-extract GLOB.FLX     -o globs/

# Render a map
titan map-render \
  --fixed FIXED.DAT --shapes shapes/ --globs globs/ \
  --palette U8PAL.PAL --typeflag TYPEFLAG.DAT \
  --map 5 -o map_005.png

# Player-accurate render (excludes editor eggs/markers and ignored shapes)
titan map-render \
  --fixed FIXED.DAT --shapes shapes/ --globs globs/ \
  --palette U8PAL.PAL --typeflag TYPEFLAG.DAT \
  --nonfixed U8SAVE.000 --no-editor --no-ignore \
  --map 39 -o map_039.png
```

### Other useful commands (no config needed)

```bash
# Convert XMIDI music to standard MIDI
# (records auto-named from playlist: 0001_intro.xmi, 0002_docks.xmi, ...)
titan flex-extract MUSIC.FLX -o music_xmi/
titan music-batch music_xmi/ -o music_midi/

# Decode Sonarc sound effects to WAV
# (records auto-named from name table: 0001_ARMHIT1A.raw, 0007_TELEPORT.raw, ...)
titan flex-extract SOUND.FLX -o sound_raw/
titan sound-batch sound_raw/ -o sound_wav/

# Extract speech audio (one FLX per NPC — E=English, G=German, etc.)
# record 0 = dialogue transcript (.txt), records 1+ = Sonarc audio (.raw)
titan flex-extract E44.FLX  -o speech_e44/
titan flex-extract E80.FLX  -o speech_e80/
titan sound-batch speech_e44/ -o speech_e44_wav/

# Export all shapes to PNG
titan shape-batch shapes/ -p U8PAL.PAL -o shapes_png/
```

Run `titan <command> --help` for per-command options, or see the full
[CLI reference](reference/cli_reference.md).

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

```python
# Flex archives
from titan.flex import FlexArchive

archive = FlexArchive.from_file("U8SHAPES.FLX")
archive.extract_all("shapes/")

# Shapes + palette
from titan.shape import U8Shape
from titan.palette import U8Palette

pal    = U8Palette.from_file("U8PAL.PAL")
shape  = U8Shape.from_file("shapes/0001.shp")
frames = shape.to_pngs(pal)
frames[0].save("frame0.png")

# Map rendering
from titan.map import U8MapRenderer

renderer = U8MapRenderer(
    fixed_path    = "FIXED.DAT",
    shapes_dir    = "shapes/",
    globs_dir     = "globs/",
    palette_path  = "U8PAL.PAL",
    typeflag_path = "TYPEFLAG.DAT",
)
img = renderer.render_map(map_num=5, view="iso_classic")
img.save("map_005.png")

# Save archives
from titan.save import U8SaveArchive

save = U8SaveArchive.from_file("U8SAVE.000")
for name, size in save.list_entries():
    print(f"{name}  {size:,} bytes")
nonfixed_bytes = save.get_data("NONFIXED.DAT")
```

---

## Supported formats

| Format | Module | Game file(s) |
|--------|--------|-------------|
| Flex archive | `titan.flex` | `*.FLX` |
| Shape sprites | `titan.shape` | `U8SHAPES.FLX` → `.shp` |
| VGA palette | `titan.palette` | `U8PAL.PAL` |
| Sonarc audio | `titan.sound` | `SOUND.FLX` → `.raw`; `E*.FLX` / `G*.FLX` → speech `.raw` + `.txt` |
| XMIDI music | `titan.music` | `MUSIC.FLX` → `.xmi` |
| World map (static) | `titan.map` | `FIXED.DAT`, `GLOB.FLX` |
| World map (dynamic) | `titan.map` | `NONFIXED.DAT` / `U8SAVE.000` |
| Type flags | `titan.typeflag` | `TYPEFLAG.DAT` |
| Gump layout | (cli only) | `GUMPAGE.DAT` |
| XOR credits | `titan.credits` | `ECREDITS.DAT`, `QUOTES.DAT` |
| Colour transforms | `titan.xformpal` | `XFORMPAL.DAT` |
| Save archives | `titan.save` | `U8SAVE.000`–`.005` |

---

## Game files

TITAN requires the original Ultima 8: Pagan game files. If you own the game
through GOG, the default install locations are:

| Platform | Method | Default path |
|----------|--------|--------------|
| Windows | GOG Galaxy | `C:\Program Files (x86)\GOG Galaxy\Games\Ultima 8` |
| Windows | GOG Offline Installer | `C:\GOG Games\Ultima 8` |
| Linux | GOG Galaxy / Offline | `~/GOG Games/Ultima 8` |

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
| `titan.shape` | `.shp` files (extracted) | Output of `flex-extract U8SHAPES.FLX` |
| `titan.palette` | `U8PAL.PAL` | `STATIC/` |
| `titan.sound` | `.raw` files (extracted) | Output of `flex-extract SOUND.FLX` |
| `titan.music` | `.xmi` files (extracted) | Output of `flex-extract MUSIC.FLX` |
| `titan.map` | `FIXED.DAT`, `TYPEFLAG.DAT`, extracted `shapes/` + `globs/`; `U8SAVE.000` (optional) | `STATIC/`, `SAVEGAME/` |
| `titan.typeflag` | `TYPEFLAG.DAT` | `STATIC/` |
| `titan.credits` | `ECREDITS.DAT`, `QUOTES.DAT` | `STATIC/` |
| `titan.save` | `U8SAVE.000`–`.005` | `SAVEGAME/` or `cloud_saves/SAVEGAME/` |

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

---

## License

MIT

### Important note

**Ultima** (Copyright 1981–1999, Electronic Arts)

To use this fan-made tool you **must own** a legitimate copy of
[Ultima 8: Pagan](https://www.gog.com/en/game/ultima_8_pagan).
This project is not affiliated with Electronic Arts. All rights to Ultima
remain with Electronic Arts.
