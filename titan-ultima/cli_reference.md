# TITAN CLI Reference

**TITAN** – Tool for Interpreting and Transforming Archival Nodes  
Command-line reference for all `titan` subcommands.

---

## Global options

These flags apply before any subcommand:

| Flag | Short | Description |
|------|-------|-------------|
| `--version` | | Print version and exit |
| `--config FILE` | `-c` | Path to a `titan.toml` config file. Auto-detected from `./titan.toml` → `~/.config/titan/` → `%APPDATA%\titan\` if not given |
| `--help` | `-h` | Show help and exit |

```
titan [--config FILE] <command> [options]
```

---

## Config-aware commands

The four map commands (`map-render`, `map-render-all`, `map-sample`,
`map-sample-all`) accept path arguments that are **optional on the command
line** — they fall back to values from `titan.toml` if present.

Config-aware arguments: `--fixed`, `--shapes`, `--globs`, `--palette`,
`--typeflag`, `--nonfixed`.

CLI flags always win over config values. If a required path is missing from
both the command line and the config, TITAN prints an error pointing to
`titan setup`.

See [Configuration (titan.toml)](#configuration-titantoml) below.

---

## Command reference

### Flex archive commands

---

#### `flex-info`

Show detailed header information for a Flex archive.

```
titan flex-info <file>
```

| Argument | Description |
|----------|-------------|
| `file` | Path to the `.flx` archive |

Prints the Flex header comment, record count, unknown field, and a hex dump
of the raw 128-byte header.

**Example**
```bash
titan flex-info U8SHAPES.FLX
```

---

#### `flex-list`

List all records in a Flex archive with their indices and sizes.

```
titan flex-list <file>
```

| Argument | Description |
|----------|-------------|
| `file` | Path to the `.flx` archive |

**Example**
```bash
titan flex-list GLOB.FLX
```

---

#### `flex-extract`

Extract all records from a Flex archive into a directory.

```
titan flex-extract <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to the `.flx` archive |
| `-o DIR`, `--output DIR` | Output directory (default: `./<flexname>/`) |

Records are written as `NNNN.<ext>` where `NNNN` is the zero-padded index and
`<ext>` is inferred from the archive name (`.shp`, `.dat`, `.raw`, `.xmi`,
etc.). A `_manifest.txt` is written alongside for round-trip reconstruction
with `flex-create`.

Empty records are skipped and counted separately.

**Examples**
```bash
titan flex-extract U8SHAPES.FLX -o shapes/
titan flex-extract GLOB.FLX     -o globs/
titan flex-extract MUSIC.FLX    -o music_xmi/
titan flex-extract SOUND.FLX    -o sound_raw/
```

---

#### `flex-create`

Create a Flex archive from a directory of numbered files.

```
titan flex-create <directory> [-o FILE] [-c COMMENT]
```

| Argument | Description |
|----------|-------------|
| `directory` | Source directory containing `NNNN.*` files |
| `-o FILE`, `--output FILE` | Output `.flx` path (default: `<dirname>.flx`) |
| `-c TEXT`, `--comment TEXT` | Comment string to embed in the Flex header |

If a `_manifest.txt` is present (produced by `flex-extract`), it is used to
reconstruct the exact original record layout including empty slots. Without a
manifest, all files in the directory are packed in alphabetical order.

**Example**
```bash
titan flex-create shapes/ -o MY_SHAPES.FLX -c "Rebuilt by TITAN"
```

---

#### `flex-update`

Replace a single record inside an existing Flex archive.

```
titan flex-update <file> --index N --data FILE [-o FILE]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to the `.flx` archive |
| `--index N` | Record index to replace (0-based) |
| `--data FILE` | Path to the replacement data file |
| `-o FILE`, `--output FILE` | Output path (default: overwrites input) |

**Example**
```bash
titan flex-update U8SHAPES.FLX --index 42 --data my_shape.shp -o U8SHAPES_PATCHED.FLX
```

---

### Shape commands

---

#### `shape-export`

Export all frames from a single Shape (`.shp`) file to PNG images.

```
titan shape-export <file> [-p PAL] [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to the `.shp` shape file |
| `-p FILE`, `--palette FILE` | Path to `.pal` palette (default: greyscale) |
| `-o DIR`, `--output DIR` | Output directory (default: `./<shapename>/`) |

Frames are saved as `<shapename>_fNNNN.png`.

**Example**
```bash
titan shape-export shapes/0001.shp -p U8PAL.PAL -o out/
```

---

#### `shape-batch`

Batch-export all `.shp` files in a directory to PNG.

```
titan shape-batch <directory> [-p PAL] [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `directory` | Directory containing `.shp` files |
| `-p FILE`, `--palette FILE` | Path to `.pal` palette (default: greyscale) |
| `-o DIR`, `--output DIR` | Output directory (default: `<dir>/png/`) |

**Example**
```bash
titan shape-batch shapes/ -p U8PAL.PAL -o shapes_png/
```

---

#### `shape-import`

Import edited PNG frames back into a U8 shape file.

```
titan shape-import <directory> --original FILE [-p PAL] [-o FILE]
```

| Argument | Description |
|----------|-------------|
| `directory` | Directory containing `*_fNNNN.png` frame images |
| `--original FILE` | Original `.shp` file (provides metadata reference) |
| `-p FILE`, `--palette FILE` | Path to `.pal` palette for colour quantisation |
| `-o FILE`, `--output FILE` | Output `.shp` path (default: `<base>_imported.shp`) |

**Example**
```bash
titan shape-import edited_frames/ --original shapes/0001.shp -p U8PAL.PAL -o 0001_new.shp
```

---

### Palette commands

---

#### `palette-export`

Export a U8 palette (`.pal`) as a PNG colour swatch and text dump.

```
titan palette-export <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `.pal` file |
| `-o DIR`, `--output DIR` | Output directory (default: `./<palname>/`) |

Outputs a 256-colour swatch PNG and a plain-text index listing.

**Example**
```bash
titan palette-export U8PAL.PAL -o palette/
```

---

### Sound commands

---

#### `sound-export`

Decode a single Sonarc-compressed audio file (`.raw`) to WAV.

```
titan sound-export <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `.raw` Sonarc audio file |
| `-o DIR`, `--output DIR` | Output directory (default: `./<name>/`) |

**Example**
```bash
titan sound-export sound_raw/0001.raw -o sound_wav/
```

---

#### `sound-batch`

Batch-decode all Sonarc `.raw` files in a directory to WAV.

```
titan sound-batch <directory> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `directory` | Directory containing `.raw` files |
| `-o DIR`, `--output DIR` | Output directory (default: `<dir>/wav/`) |

**Example**
```bash
# First extract SOUND.FLX, then batch-convert
titan flex-extract SOUND.FLX -o sound_raw/
titan sound-batch sound_raw/ -o sound_wav/
```

---

### Music commands

---

#### `music-export`

Convert a single XMIDI (`.xmi`) file to standard MIDI.

```
titan music-export <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `.xmi` XMIDI file |
| `-o DIR`, `--output DIR` | Output directory (default: `./<name>/`) |

**Example**
```bash
titan music-export music_xmi/0044.xmi -o midi/
```

---

#### `music-batch`

Batch-convert all XMIDI `.xmi` files in a directory to standard MIDI.

```
titan music-batch <directory> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `directory` | Directory containing `.xmi` files |
| `-o DIR`, `--output DIR` | Output directory (default: `<dir>/midi/`) |

**Example**
```bash
titan flex-extract MUSIC.FLX -o music_xmi/
titan music-batch music_xmi/ -o music_midi/
```

---

### Map commands

All four map commands share a common set of **config-aware path flags** and
**filtering / display flags** documented below.

#### Common path flags (config-aware)

These are optional when a `titan.toml` config is active that provides them.
CLI values always override config values.

| Flag | Description |
|------|-------------|
| `--fixed PATH` | Path to `FIXED.DAT` (static world object data) |
| `--shapes DIR` | Directory of pre-extracted `.shp` shape files (from `flex-extract U8SHAPES.FLX`) |
| `--globs DIR` | Directory of pre-extracted GLOB `.dat` files (from `flex-extract GLOB.FLX`) |
| `--palette PATH`, `-p PATH` | Path to `U8PAL.PAL` colour palette |
| `--typeflag PATH` | Path to `TYPEFLAG.DAT`. Enables engine-accurate pairwise depth sorting for correct building/wall rendering. Highly recommended |
| `--nonfixed PATH` | Path to `U8SAVE.000` or a raw `NONFIXED.DAT` Flex archive. Merges live/dynamic objects (NPCs, moved items) into the render |

#### Common filter flags

All map commands accept these typeflag-based exclusion switches.
`--typeflag` must be provided (or configured) to use them.

| Flag | Excludes |
|------|----------|
| `--no-fixed` | `SI_FIXED` — immovable/static objects |
| `--no-solid` | `SI_SOLID` — collision geometry |
| `--no-sea` | `SI_SEA` — water tiles |
| `--no-land` | `SI_LAND` — ground / floor tiles |
| `--no-occl` | `SI_OCCL` — occluders |
| `--no-bag` | `SI_BAG` — containers |
| `--no-damaging` | `SI_DAMAGING` — damage-dealing tiles |
| `--no-noisy` | `SI_NOISY` — ambient sound triggers |
| `--no-draw` | `SI_DRAW` — non-drawable objects |
| `--no-ignore` | `SI_IGNORE` — ignored objects |
| `--no-roof` | `SI_ROOF` — roof tiles (useful for interior views) |
| `--no-transl` | `SI_TRANSL` — translucent objects |
| `--no-editor` | `SI_EDITOR` — editor-only objects (usecode eggs, monster eggs, teleport eggs, collision volumes, debug markers). **Recommended** for player-accurate renders |
| `--no-explode` | `SI_EXPLODE` — explosive objects (1 shape in vanilla U8) |
| `--no-unk46` | `SI_UNKNOWN46` — reserved flag bit 14 (39 shapes in vanilla U8) |
| `--no-unk47` | `SI_UNKNOWN47` — reserved flag bit 15 (1 shape in vanilla U8) |

> **Tip — player-accurate renders:** For renders closest to what the original
> engine displays, use `--no-editor --no-ignore` together with
> `--nonfixed U8SAVE.000`. Editor shapes (eggs, debug markers, translucent
> collision volumes) and ignored shapes are never drawn by the game engine.

#### Common display flags

| Flag | Default | Description |
|------|---------|-------------|
| `--grid` | off | Overlay chunk grid lines at 512-world-unit spacing |
| `--grid-size PX` | `2` | Grid line thickness in pixels |

#### Depth sorting

When `--typeflag` is provided (or configured via `titan.toml`), the map
renderer uses an **engine-accurate dependency-graph depth sort**:

1. **Initial ordering** by `(z, x, y)` matching the engine's `ListLessThan`.
2. **Screen-space bounding boxes** computed per-object using the `iso_classic`
   projection formulas.
3. **Sweep-line overlap detection** across screen-X, building pairwise
   dependency edges via the full `SortItem::operator<` comparator
   (including animtype, translucency, draw-flag, solidity, and occlusion
   tie-breaking for flat objects).
4. **Iterative topological DFS** paint order with silent cycle handling.

Without `--typeflag`, objects are sorted by a simple `(z, x, y)` key which
may produce incorrect layering in buildings with overlapping walls and roofs.

#### View projections

| View | Description |
|------|-------------|
| `iso_classic` | **(default)** U8 native 2:1 isometric |
| `iso_high` | Steeper isometric — more top-down angle |
| `iso_low` | Shallower isometric — emphasises wall faces |
| `iso_north` | North facade faces the camera |
| `iso_south` | South facade faces the camera |
| `birdseye` | Pure top-down orthographic |

---

#### `map-render`

Render a single map to a PNG image.

```
titan map-render [path flags] --map N [--view VIEW] [-o FILE] [filter flags] [display flags]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--map N`, `-m N` | **yes** | Map number (0–255) |
| `--view VIEW`, `-V VIEW` | no | Projection view (default: `iso_classic`) |
| `-o FILE`, `--output FILE` | no | Output PNG path (default: `map_<N>_<view>.png`) |

**Examples**

Without config (all paths explicit):
```bash
titan map-render \
  --fixed FIXED.DAT --shapes shapes/ --globs globs/ -p U8PAL.PAL \
  --typeflag TYPEFLAG.DAT --map 5 -o map_005.png
```

With `titan.toml` (paths from config):
```bash
titan map-render -m 5
titan map-render -m 5 --view iso_high -o map_005_high.png
titan map-render -m 39 --nonfixed U8SAVE.000   # override nonfixed only
titan map-render -m 0  --no-roof               # remove roof tiles
```

---

#### `map-render-all`

Render every non-empty map (or a selection) in one or more projection views.

```
titan map-render-all [path flags] [-o DIR] [--views VIEW ...] [--maps N ...] [filter flags] [display flags]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `-o DIR`, `--output DIR` | `map_renders/` | Output directory |
| `--views VIEW ...` | all views | One or more projection views to render |
| `--maps N ...` | all non-empty | Specific map numbers to render |

Output files are named `map_<NNN>_<view>.png`.

**Examples**
```bash
# Render all maps, all views (with config)
titan map-render-all

# Render specific maps in two views
titan map-render-all --maps 0 5 39 --views iso_classic iso_high -o renders/

# No-config form
titan map-render-all \
  --fixed FIXED.DAT --shapes shapes/ --globs globs/ -p U8PAL.PAL \
  --typeflag TYPEFLAG.DAT --maps 5 39 --views iso_classic
```

---

#### `map-sample`

Render a top-down colour-sampled minimap of a single map.

```
titan map-sample [path flags] --map N [-s N] [-o FILE] [filter flags]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--map N`, `-m N` | **required** | Map number (0–255) |
| `--scale N`, `-s N` | `64` | World units per output pixel. Lower = higher resolution (32 → 1024 px, 16 → 2048 px for a U8 map) |
| `-o FILE`, `--output FILE` | `map_<N>_sample_<scale>.png` | Output PNG path |

**Examples**
```bash
titan map-sample -m 5 -s 32 -o maps/map_005_mini.png
titan map-sample -m 0 -s 16           # high-res minimap
```

---

#### `map-sample-all`

Colour-sample all (or selected) maps at one or more scales.

```
titan map-sample-all [path flags] [-o DIR] [-s N] [--scales N ...] [--maps N ...] [filter flags]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `-o DIR`, `--output DIR` | `map_samples/` | Output directory |
| `--scale N`, `-s N` | `64` | Scale to use when `--scales` is not given |
| `--scales N ...` | | One or more scales (overrides `--scale`) |
| `--maps N ...` | all non-empty | Specific map numbers to sample |

**Examples**
```bash
titan map-sample-all --scales 64 32 16 -o minimaps/
titan map-sample-all --maps 0 5 --scales 32
```

---

### Data inspection commands

---

#### `typeflag-dump`

Parse `TYPEFLAG.DAT` and dump all shape physics / flag metadata.

```
titan typeflag-dump <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `TYPEFLAG.DAT` |
| `-o DIR`, `--output DIR` | Output directory (default: stdout) |

Outputs one line per shape entry with footprint dimensions and all SI_ flag bits.

**Example**
```bash
titan typeflag-dump TYPEFLAG.DAT -o typeflag/
```

---

#### `gumpinfo-dump`

Dump `GUMPAGE.DAT` container gump UI layout data.

```
titan gumpinfo-dump <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `GUMPAGE.DAT` |
| `-o DIR`, `--output DIR` | Output directory (default: stdout) |

**Example**
```bash
titan gumpinfo-dump GUMPAGE.DAT -o gumpinfo/
```

---

#### `credits-decrypt`

Decrypt `ECREDITS.DAT` or `QUOTES.DAT` to plain text (XOR cipher).

```
titan credits-decrypt <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `ECREDITS.DAT` or `QUOTES.DAT` |
| `-o DIR`, `--output DIR` | Output directory (default: `./<name>/`) |

**Example**
```bash
titan credits-decrypt ECREDITS.DAT -o credits/
titan credits-decrypt QUOTES.DAT   -o credits/
```

---

#### `xformpal-export`

Export the U8 colour-transform palette as a PNG swatch and text dump.

```
titan xformpal-export [file] [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `XFORMPAL.DAT` (optional — the hardcoded internal palette is always exported too) |
| `-o DIR`, `--output DIR` | Output directory |

**Example**
```bash
titan xformpal-export XFORMPAL.DAT -o xformpal/
```

---

### Save archive commands

---

#### `save-list`

List all entries inside a U8 save archive with their sizes.

```
titan save-list <file>
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `U8SAVE.000` (or `.001`–`.005`) |

**Example**
```bash
titan save-list U8SAVE.000
```

---

#### `save-extract`

Extract all (or a single named) entry from a U8 save archive.

```
titan save-extract <file> [-o DIR] [--entry NAME]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `U8SAVE.000` (or `.001`–`.005`) |
| `-o DIR`, `--output DIR` | Output directory (default: `./<savename>/`) |
| `--entry NAME` | Extract only this named entry, e.g. `NONFIXED.DAT` |

Common entries inside U8SAVE.000: `FIXED.DAT`, `NONFIXED.DAT`, `NPCDATA.DAT`,
`OBJLIST.DAT`, `CHUNKS.DAT`, `GAMEDAT.DAT`.

**Examples**
```bash
titan save-extract U8SAVE.000 -o save_all/
titan save-extract U8SAVE.000 --entry NONFIXED.DAT -o save_single/
```

---

#### `unkcoff-dump`

Dump the `UNKCOFF.DAT` code-offset table (a developer leftover in the game data).

```
titan unkcoff-dump <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `UNKCOFF.DAT` |
| `-o DIR`, `--output DIR` | Output directory (default: stdout) |

**Example**
```bash
titan unkcoff-dump UNKCOFF.DAT -o unkcoff/
```

---

### Configuration commands

---

#### `setup`

Interactive first-time setup wizard. Detects your Ultima 8 installation,
detects third-party engine saves, and writes `titan.toml` in the current
directory. Optionally extracts `shapes/` and `globs/` immediately.

```
titan setup
```

No arguments. Prompts:
1. **Game base path** — auto-detected from common GOG/Origin/disc locations;
   defaults to current directory if nothing found.
2. **Language folder** — `ENGLISH`, `FRENCH`, `GERMAN`, etc. Leave empty for
   flat mode (files directly in `base/`).
3. **Third-party engine saves** — if a save is found at a known engine location
   (e.g. `%APPDATA%\Pentagram\u8-save\U8SAVE.000` on Windows or
   `~/Library/Application Support/Pentagram/u8-save/U8SAVE.000` on macOS),
   offers to use it as the `nonfixed` source.
4. **Extract now?** — runs `titan flex-extract` for `U8SHAPES.FLX` and
   `GLOB.FLX` if `Y`.

After setup, map commands require no path flags:
```bash
titan setup
titan map-render -m 5
```

---

#### `config`

Show or edit the active `titan.toml` configuration.

```
titan config [--edit]
titan --config FILE config
```

| Flag | Description |
|------|-------------|
| `--edit` | Open `titan.toml` in the system editor (`$VISUAL`, `$EDITOR`, `notepad`, or `nano`) |

Without `--edit`, prints:
- Config file path
- `[game]` section values
- `[paths]` section with all relative paths expanded and each marked `[OK]` or
  `[NOT FOUND]`

**Examples**
```bash
titan config                        # show resolved paths
titan config --edit                 # open in editor
titan --config /other/titan.toml config  # inspect a specific config
```

---

## Configuration (titan.toml)

### File format

```toml
[game]
base     = "C:/Program Files (x86)/GOG Galaxy/Games/Ultima 8"  # GOG Galaxy default
language = "ENGLISH"      # language sub-folder; "" for flat mode

[paths]
# Relative → expanded to <base>/<language>/STATIC/<name>
fixed     = "FIXED.DAT"
palette   = "U8PAL.PAL"
typeflag  = "TYPEFLAG.DAT"
gumpage   = "GUMPAGE.DAT"
xformpal  = "XFORMPAL.DAT"
ecredits  = "ECREDITS.DAT"
quotes    = "QUOTES.DAT"
u8shapes  = "U8SHAPES.FLX"
u8fonts   = "U8FONTS.FLX"
u8gumps   = "U8GUMPS.FLX"

# Relative to working directory (not game install)
shapes    = "shapes/"
globs     = "globs/"

# Relative → expanded to <base>/cloud_saves/SAVEGAME/<name>  (GOG layout)
# Absolute path (third-party engine) is used as-is
nonfixed  = "U8SAVE.000"
```

### Search order

TITAN looks for a config file in this order, using the first one found:

1. `./titan.toml` (current working directory)
2. `~/.config/titan/config.toml` (Linux / macOS)
3. `%APPDATA%\titan\config.toml` (Windows)

Override with `titan --config /path/to/other.toml <command>`.

### Path expansion rules

| Key type | Expansion |
|----------|-----------|
| STATIC file (relative) | `<base>/<language>/STATIC/<name>` |
| SAVEGAME file (relative) | `<base>/cloud_saves/SAVEGAME/<name>` |
| Any absolute path | Used unchanged |
| `shapes`, `globs` | Relative to current working directory |
| Flat mode (`language = ""`) | STATIC and SAVEGAME expand directly to `<base>/` |

### Priority

`CLI flag > titan.toml > built-in default`

A value on the command line always wins.

---

## Quick reference table

| Command | Summary |
|---------|---------|
| `flex-info` | Flex archive header details |
| `flex-list` | List Flex archive records |
| `flex-extract` | Extract all Flex records to a directory |
| `flex-create` | Build a Flex archive from a directory |
| `flex-update` | Replace one record in a Flex archive |
| `palette-export` | Export `.pal` as PNG swatch |
| `shape-export` | Export `.shp` frames to PNG |
| `shape-batch` | Batch export all shapes to PNG |
| `shape-import` | Import PNGs back into a shape file |
| `sound-export` | Decode one Sonarc `.raw` to WAV |
| `sound-batch` | Batch decode Sonarc `.raw` files to WAV |
| `music-export` | Convert one XMIDI `.xmi` to MIDI |
| `music-batch` | Batch convert XMIDI `.xmi` files to MIDI |
| `map-render` | Render one map to PNG (isometric or top-down) |
| `map-render-all` | Render all (or selected) maps in all (or selected) views |
| `map-sample` | Top-down colour-sampled minimap for one map |
| `map-sample-all` | Batch minimap render for all (or selected) maps |
| `typeflag-dump` | Dump `TYPEFLAG.DAT` shape physics data |
| `gumpinfo-dump` | Dump `GUMPAGE.DAT` container UI layout |
| `credits-decrypt` | Decrypt `ECREDITS.DAT` / `QUOTES.DAT` |
| `xformpal-export` | Export colour-transform palette |
| `save-list` | List entries in a U8 save archive |
| `save-extract` | Extract entries from a U8 save archive |
| `unkcoff-dump` | Dump `UNKCOFF.DAT` code-offset table |
| `setup` | First-time setup wizard — creates `titan.toml` |
| `config` | Show or edit active `titan.toml` |
