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

## CLI layout

TITAN organises commands into **game-specific sub-apps** and **shared
(game-agnostic) root commands**:

```
titan <shared-command>          # Flex archives, XMIDI music, config/setup
titan u8 <command>              # Ultima 8: Pagan
titan u7 <command>              # Ultima 7: The Black Gate / Serpent Isle
```

> **Backward compatibility:** The old root-level U8 commands (e.g.
> `titan shape-export`) still work as hidden, deprecated aliases that
> forward to `titan u8 shape-export`. They are not shown in `--help`
> but remain functional.

---

## Config-aware commands

The four U8 map commands (`u8 map-render`, `u8 map-render-all`, `u8 map-sample`,
`u8 map-sample-all`) accept path arguments that are **optional on the command
line** — they fall back to values from `titan.toml` if present.

Config-aware arguments: `--fixed`, `--shapes`, `--globs`, `--palette`,
`--typeflag`, `--nonfixed`.

CLI flags always win over config values. If a required path is missing from
both the command line and the config, TITAN prints an error pointing to
`titan setup`.

See [Configuration (titan.toml)](#configuration-titantoml) below.

---

## Shared commands (root level)

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

Records are written as `NNNN_NAME.<ext>` when the archive contains an
embedded name table (SOUND.FLX, MUSIC.FLX), or `NNNN.<ext>` otherwise.
`NNNN` is the zero-padded record index, `NAME` is the sanitised name
(up to 32 characters), and `<ext>` is inferred from the archive name
or detected per-record (`.shp`, `.dat`, `.raw`, `.xmi`, `.txt`, etc.).
Speech FLX archives (`E44.FLX`, `G289.FLX`, etc.) contain a text
transcript in record 0 (`.txt`) and Sonarc audio in remaining records (`.raw`).

A companion `NNNN_NAME.meta.txt` metadata sidecar is written alongside each
record with the source archive, record index, name, byte size, content
type, hex header preview, and format-specific details (Sonarc sample rate,
XMIDI FORM size, shape frame count).

A `_manifest.txt` is written alongside for round-trip reconstruction
with `flex-create`.

Empty records are skipped and counted separately.

**Examples**
```bash
titan flex-extract U8SHAPES.FLX -o shapes/
titan flex-extract GLOB.FLX     -o globs/
titan flex-extract MUSIC.FLX    -o music_xmi/   # → 0001_intro.xmi, 0001_intro.meta.txt, ...
titan flex-extract SOUND.FLX    -o sound_raw/   # → 0001_ARMHIT1A.raw, 0001_ARMHIT1A.meta.txt, ...
titan flex-extract E44.FLX      -o e44/         # → 0000.txt (transcript), 0001.raw, ...
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

---

## Ultima 8 commands (`titan u8`)

All commands below are invoked as `titan u8 <command>`. The old root-level
forms (e.g. `titan shape-export`) still work as deprecated aliases.

### Shape commands

---

#### `u8 shape-export`

Export all frames from a single U8 Shape (`.shp`) file to PNG images.

```
titan u8 shape-export <file> [-p PAL] [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to the `.shp` shape file |
| `-p FILE`, `--palette FILE` | Path to `.pal` palette (default: greyscale) |
| `-o DIR`, `--output DIR` | Output directory (default: `./<shapename>/`) |

Frames are saved as `<shapename>_fNNNN.png`.

**Example**
```bash
titan u8 shape-export shapes/0001.shp -p U8PAL.PAL -o out/
```

---

#### `u8 shape-batch`

Batch-export all `.shp` files in a directory to PNG.

```
titan u8 shape-batch <directory> [-p PAL] [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `directory` | Directory containing `.shp` files |
| `-p FILE`, `--palette FILE` | Path to `.pal` palette (default: greyscale) |
| `-o DIR`, `--output DIR` | Output directory (default: `<dir>/png/`) |

**Example**
```bash
titan u8 shape-batch shapes/ -p U8PAL.PAL -o shapes_png/
```

---

#### `u8 shape-import`

Import edited PNG frames back into a U8 shape file.

```
titan u8 shape-import <directory> --original FILE [-p PAL] [-o FILE]
```

| Argument | Description |
|----------|-------------|
| `directory` | Directory containing `*_fNNNN.png` frame images |
| `--original FILE` | Original `.shp` file (provides metadata reference) |
| `-p FILE`, `--palette FILE` | Path to `.pal` palette for colour quantisation |
| `-o FILE`, `--output FILE` | Output `.shp` path (default: `<base>_imported.shp`) |

**Example**
```bash
titan u8 shape-import edited_frames/ --original shapes/0001.shp -p U8PAL.PAL -o 0001_new.shp
```

---

### Palette commands

---

#### `u8 palette-export`

Export a U8 palette (`.pal`) as a PNG colour swatch and text dump.

```
titan u8 palette-export <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `.pal` file |
| `-o DIR`, `--output DIR` | Output directory (default: `./<palname>/`) |

Outputs a 256-colour swatch PNG and a plain-text index listing.

**Example**
```bash
titan u8 palette-export U8PAL.PAL -o palette/
```

---

### Music commands

---

#### `u8 music-export`

Extract and convert music from `MUSIC.FLX` (Flex archive of XMIDI tracks)
to standard MIDI files in a single step.  Also handles standalone `.xmi`
files.

```
titan u8 music-export <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `MUSIC.FLX` or a standalone `.xmi` file |
| `-o DIR`, `--output DIR` | Output directory (default: `<name>_midi/`) |

Multi-track XMIDI files (e.g. records 258, 260) are converted to MIDI
Format 1 with all tracks preserved.  Single-track records produce Format 0.

**Examples**
```bash
# One-step: Flex archive → MIDI
titan u8 music-export MUSIC.FLX -o music_midi/

# Standalone XMIDI file
titan u8 music-export some_track.xmi -o midi/
```

---

### Sound commands

---

#### `u8 sound-export-all`

Extract and decode all Sonarc audio from `SOUND.FLX` to WAV in a single
step.

```
titan u8 sound-export-all <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `SOUND.FLX` (Flex archive of Sonarc audio) |
| `-o DIR`, `--output DIR` | Output directory (default: `<name>_wav/`) |

**Example**
```bash
titan u8 sound-export-all SOUND.FLX -o sound_wav/
```

---

#### `u8 sound-export`

Decode a single Sonarc-compressed audio file (`.raw`) to WAV.

```
titan u8 sound-export <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `.raw` Sonarc audio file |
| `-o DIR`, `--output DIR` | Output directory (default: `./<name>/`) |

**Example**
```bash
titan u8 sound-export sound_raw/0001.raw -o sound_wav/
```

---

#### `u8 sound-batch`

Batch-decode all Sonarc `.raw` files in a directory to WAV.

```
titan u8 sound-batch <directory> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `directory` | Directory containing `.raw` files |
| `-o DIR`, `--output DIR` | Output directory (default: `<dir>/wav/`) |

**Example**
```bash
titan u8 sound-batch sound_raw/ -o sound_wav/
```

---

### Low-level music commands (shared / root)

These root-level commands operate on individual pre-extracted `.xmi` files.
For most workflows, prefer the game-specific one-step commands above.

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
titan music-batch music_xmi/ -o music_midi/
```

---

### U8 map commands

All four U8 map commands share a common set of **config-aware path flags** and
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
| `--grid` | off | Overlay chunk grid lines at 512-world-unit spacing with coordinate labels |
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

#### `u8 map-render`

Render a single U8 map to a PNG image.

```
titan u8 map-render [path flags] --map N [--view VIEW] [-o FILE] [filter flags] [display flags]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `--map N`, `-m N` | **yes** | Map number (0–255) |
| `--view VIEW`, `-V VIEW` | no | Projection view (default: `iso_classic`) |
| `-o FILE`, `--output FILE` | no | Output PNG path (default: `map_<N>_<view>.png`) |

**Examples**

Without config (all paths explicit):
```bash
titan u8 map-render \
  --fixed FIXED.DAT --shapes shapes/ --globs globs/ -p U8PAL.PAL \
  --typeflag TYPEFLAG.DAT --map 5 -o map_005.png
```

With `titan.toml` (paths from config):
```bash
titan u8 map-render -m 5
titan u8 map-render -m 5 --view iso_high -o map_005_high.png
titan u8 map-render -m 39 --nonfixed U8SAVE.000   # override nonfixed only
titan u8 map-render -m 0  --no-roof               # remove roof tiles
```

---

#### `u8 map-render-all`

Render every non-empty U8 map (or a selection) in one or more projection views.

```
titan u8 map-render-all [path flags] [-o DIR] [--views VIEW ...] [--maps N ...] [filter flags] [display flags]
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
titan u8 map-render-all

# Render specific maps in two views
titan u8 map-render-all --maps 0 5 39 --views iso_classic iso_high -o renders/

# No-config form
titan u8 map-render-all \
  --fixed FIXED.DAT --shapes shapes/ --globs globs/ -p U8PAL.PAL \
  --typeflag TYPEFLAG.DAT --maps 5 39 --views iso_classic
```

---

#### `u8 map-sample`

Render a top-down colour-sampled minimap of a single U8 map.

```
titan u8 map-sample [path flags] --map N [-s N] [-o FILE] [filter flags]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--map N`, `-m N` | **required** | Map number (0–255) |
| `--scale N`, `-s N` | `64` | World units per output pixel. Lower = higher resolution (32 → 1024 px, 16 → 2048 px for a U8 map) |
| `-o FILE`, `--output FILE` | `map_<N>_sample_<scale>.png` | Output PNG path |

**Examples**
```bash
titan u8 map-sample -m 5 -s 32 -o maps/map_005_mini.png
titan u8 map-sample -m 0 -s 16           # high-res minimap
```

---

#### `u8 map-sample-all`

Colour-sample all (or selected) U8 maps at one or more scales.

```
titan u8 map-sample-all [path flags] [-o DIR] [-s N] [--scales N ...] [--maps N ...] [filter flags]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `-o DIR`, `--output DIR` | `map_samples/` | Output directory |
| `--scale N`, `-s N` | `64` | Scale to use when `--scales` is not given |
| `--scales N ...` | | One or more scales (overrides `--scale`) |
| `--maps N ...` | all non-empty | Specific map numbers to sample |

**Examples**
```bash
titan u8 map-sample-all --scales 64 32 16 -o minimaps/
titan u8 map-sample-all --maps 0 5 --scales 32
```

---

### U8 data inspection commands

---

#### `u8 typeflag-dump`

Parse U8 `TYPEFLAG.DAT` and dump all shape physics / flag metadata.

```
titan u8 typeflag-dump <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `TYPEFLAG.DAT` |
| `-o DIR`, `--output DIR` | Output directory (default: stdout) |

Outputs one line per shape entry with footprint dimensions and all SI_ flag bits.

**Example**
```bash
titan u8 typeflag-dump TYPEFLAG.DAT -o typeflag/
```

---

#### `u8 gumpinfo-dump`

Dump U8 `GUMPAGE.DAT` container gump UI layout data.

```
titan u8 gumpinfo-dump <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `GUMPAGE.DAT` |
| `-o DIR`, `--output DIR` | Output directory (default: stdout) |

**Example**
```bash
titan u8 gumpinfo-dump GUMPAGE.DAT -o gumpinfo/
```

---

#### `u8 credits-decrypt`

Decrypt U8 `ECREDITS.DAT` or `QUOTES.DAT` to plain text (XOR cipher).

```
titan u8 credits-decrypt <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `ECREDITS.DAT` or `QUOTES.DAT` |
| `-o DIR`, `--output DIR` | Output directory (default: `./<name>/`) |

**Example**
```bash
titan u8 credits-decrypt ECREDITS.DAT -o credits/
titan u8 credits-decrypt QUOTES.DAT   -o credits/
```

---

#### `u8 xformpal-export`

Export the U8 colour-transform palette as a PNG swatch and text dump.

```
titan u8 xformpal-export [file] [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `XFORMPAL.DAT` (optional — the hardcoded internal palette is always exported too) |
| `-o DIR`, `--output DIR` | Output directory |

**Example**
```bash
titan u8 xformpal-export XFORMPAL.DAT -o xformpal/
```

---

### U8 save archive commands

---

#### `u8 save-list`

List all entries inside a U8 save archive with their sizes.

```
titan u8 save-list <file>
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `U8SAVE.000` (or `.001`–`.005`) |

**Example**
```bash
titan u8 save-list U8SAVE.000
```

---

#### `u8 save-extract`

Extract all (or a single named) entry from a U8 save archive.

```
titan u8 save-extract <file> [-o DIR] [--entry NAME]
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
titan u8 save-extract U8SAVE.000 -o save_all/
titan u8 save-extract U8SAVE.000 --entry NONFIXED.DAT -o save_single/
```

---

#### `u8 unkcoff-dump`

Dump the `UNKCOFF.DAT` code-offset table (a developer leftover in the game data).

```
titan u8 unkcoff-dump <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `UNKCOFF.DAT` |
| `-o DIR`, `--output DIR` | Output directory (default: stdout) |

**Example**
```bash
titan u8 unkcoff-dump UNKCOFF.DAT -o unkcoff/
```

---

## Ultima 7 commands (`titan u7`)

> Ultima 7 support is under active development. Commands listed below are
> available now; more will be added in future releases.

### U7 shape commands

---

#### `u7 shape-export`

Export frames from a U7 shape file (individual `.shp` or a record inside
`SHAPES.VGA`) to PNG. Handles both 8×8 ground tiles (shapes 0–149) and
RLE-compressed sprites.

```
titan u7 shape-export <file> [-p PAL] [-o DIR] [--shape N] [--frame N]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `.shp` file **or** `SHAPES.VGA` Flex archive |
| `-p FILE`, `--palette FILE` | Path to `PALETTES.FLX` or raw `.pal` (default: greyscale) |
| `-o DIR`, `--output DIR` | Output directory (default: `./<name>/`) |
| `--shape N` | Shape index to export when `file` is a VGA Flex (e.g. `SHAPES.VGA`). Required for Flex input |
| `--frame N` | Single frame number to export (default: all frames) |

**Examples**
```bash
# Export from a standalone .shp
titan u7 shape-export POINTERS.SHP -p PALETTES.FLX -o pointers/

# Export shape 150 (first non-ground object) from SHAPES.VGA
titan u7 shape-export SHAPES.VGA --shape 150 -p PALETTES.FLX -o shape_150/
```

---

#### `u7 shape-batch`

Batch-export shapes from a VGA Flex archive to PNG.

```
titan u7 shape-batch <file> [-p PAL] [-o DIR] [--range START END]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to a VGA Flex archive (e.g. `SHAPES.VGA`, `FACES.VGA`) |
| `-p FILE`, `--palette FILE` | Path to `PALETTES.FLX` or raw `.pal` (default: greyscale) |
| `-o DIR`, `--output DIR` | Output directory (default: `<name>_png/`) |
| `--range START END` | Shape index range to export (default: all) |

**Examples**
```bash
titan u7 shape-batch SHAPES.VGA -p PALETTES.FLX -o shapes_png/
titan u7 shape-batch FACES.VGA -p PALETTES.FLX -o faces_png/ --range 0 50
```

---

### U7 palette commands

---

#### `u7 palette-export`

Export palettes from `PALETTES.FLX` as PNG colour swatches and text dumps.

```
titan u7 palette-export <file> [-o DIR] [--index N]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `PALETTES.FLX` or a standalone `.pal` file |
| `-o DIR`, `--output DIR` | Output directory (default: `./palettes/`) |
| `--index N` | Export only palette N (default: all palettes in the archive) |

`PALETTES.FLX` typically contains 12 palettes. Palette 0 is the main
daytime palette used by most graphics.

**Examples**
```bash
# Export all 12 palettes
titan u7 palette-export PALETTES.FLX -o palettes/

# Export only the main daytime palette
titan u7 palette-export PALETTES.FLX --index 0 -o palettes/
```

---

### U7 music commands

---

#### `u7 music-export`

Extract music tracks from a U7 music Flex archive as standard MIDI files.
Handles both archives of standard MIDI (`ADLIBMUS.DAT`, `MT32MUS.DAT`,
`INTROADM.DAT`, `INTRORDM.DAT`) and standalone XMIDI files (`ENDSCORE.XMI`).

```
titan u7 music-export <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to a U7 music archive or XMIDI file |
| `-o DIR`, `--output DIR` | Output directory (default: `<name>_midi/`) |

U7 music archives contain standard MIDI (`.mid`) tracks — no XMIDI
conversion is needed for the bulk of the soundtrack. `ENDSCORE.XMI` is
the sole XMIDI file, which is automatically converted.

**Examples**
```bash
# Extract MT-32 music (54 tracks)
titan u7 music-export MT32MUS.DAT -o music_mt32/

# Extract AdLib music
titan u7 music-export ADLIBMUS.DAT -o music_adlib/

# Convert the endgame XMIDI score to MIDI
titan u7 music-export ENDSCORE.XMI -o endscore/

# Extract intro music
titan u7 music-export INTRORDM.DAT -o intro_mt32/
```

---

### U7 voice / speech commands

---

#### `u7 voc-export`

Decode a standalone Creative Voice File (`.voc`) to WAV.

```
titan u7 voc-export <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to a `.voc` file (e.g. `INTROSND.DAT`) |
| `-o DIR`, `--output DIR` | Output directory (default: `./<name>/`) |

Supports uncompressed 8-bit PCM and 4-bit ADPCM compression, multi-block
VOC files with continuation and silence blocks.

**Example**
```bash
# Decode the Guardian's intro speech
titan u7 voc-export INTROSND.DAT -o speech/
```

---

#### `u7 speech-export`

Extract and decode all Creative Voice records from a U7 speech Flex
archive to WAV. Also handles a single VOC file.

```
titan u7 speech-export <file> [-o DIR]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to `U7SPEECH.SPC` (Flex of VOC records) or a single VOC file |
| `-o DIR`, `--output DIR` | Output directory (default: `<name>_wav/`) |

`U7SPEECH.SPC` is a Flex archive containing ~25 VOC speech samples.
Non-VOC records (e.g. text) are saved alongside in their original format.

**Examples**
```bash
# Extract all speech samples
titan u7 speech-export U7SPEECH.SPC -o speech_wav/

# Also works on a single VOC file
titan u7 speech-export INTROSND.DAT -o speech/
```

---

### U7 map commands

---

#### `u7 map-render`

Render a U7 map region (single superchunk, arbitrary chunk range, or
the entire world) to PNG. Uses game-accurate parallel oblique projection
(not isometric — X/Y axes are screen-aligned, lift shifts diagonally at
45°). IFIX fixed objects are depth-sorted using an Exult-style
dependency DAG with sprite-accurate overlap detection.  RLE terrain
tiles (mountains, etc.) are promoted to depth-sorted objects with a
nearby-flat fill for seamless ground coverage.

```
titan u7 map-render <static> [--superchunk N | --cx0 X0 --cy0 Y0 --cx1 X1 --cy1 Y1 | --full]
                              [-p PAL] [-o FILE] [--view VIEW]
                              [--gamedat DIR] [--grid] [--exclude FLAG ...]
```

| Argument | Description |
|----------|-------------|
| `static` | Path to `STATIC/` directory containing `U7MAP`, `U7CHUNKS`, `U7IFIX*`, `SHAPES.VGA`, `TFA.DAT` |
| `--superchunk N`, `--sc N` | Superchunk number 0–143 (hex ok, e.g. `0x55`). Renders a 16×16 chunk region |
| `--cx0`, `--cy0`, `--cx1`, `--cy1` | Chunk-level bounding box (0–191). Alternative to `--superchunk` |
| `--full` | Render the entire world map (shorthand for `--cx0 0 --cy0 0 --cx1 191 --cy1 191`) |
| `-p FILE`, `--palette FILE` | Path to `PALETTES.FLX` (default: `STATIC/PALETTES.FLX`) |
| `-o FILE`, `--output FILE` | Output PNG path (default: auto-named) |
| `--view VIEW` | Projection view: `classic` (45° lift, default), `flat` (no lift), `steep` (exaggerated lift) |
| `--gamedat DIR` | Path to `gamedat/` directory to include IREG dynamic objects |
| `--grid / --no-grid` | Overlay chunk grid lines (default: off). Blue chunk grid with coordinate labels; red superchunk boundaries with SC number labels |
| `--grid-size N` | Grid line width in pixels (default: 1) |
| `--exclude FLAG` | Exclude shapes by TFA flag. Repeatable. Choices: `no_solid`, `no_water`, `no_animated`, `no_sfx`, `no_transparent`, `no_translucent`, `no_door`, `no_barge`, `no_light`, `no_poisonous`, `no_strange_movement`, `no_building` |

> **U7 and roof tiles:** U7's `TFA.DAT` does not have a dedicated roof flag
> (unlike U8's `TYPEFLAG.DAT`).  Use `--exclude no_building` to remove all
> shapes with shape class 14 (roofs, windows, mountain tops).  For a
> narrower filter, `--exclude no_transparent` removes only the 8 shapes
> marked as transparent (mostly interior rooftops and windows).  Extended
> roof metadata is only present in Exult's supplementary `shapeinf.dat`.

**Examples**
```bash
# Render superchunk 85 / 0x55 (Britain area) — decimal and hex both work
titan u7 map-render STATIC/ --superchunk 0x55 -o britain.png
titan u7 map-render STATIC/ --sc 85 -o britain.png

# Render a chunk range with grid overlay
titan u7 map-render STATIC/ --cx0 56 --cy0 80 --cx1 63 --cy1 87 --grid

# Flat (pure top-down) view, excluding water shapes
titan u7 map-render STATIC/ --sc 85 --view flat --exclude no_water

# Remove building-class shapes (roofs, windows, mountain tops)
titan u7 map-render STATIC/ --sc 85 --exclude no_building -o britain_no_roofs.png

# Remove only transparent shapes (narrower than no_building)
titan u7 map-render STATIC/ --sc 85 --exclude no_transparent

# Include dynamic objects from a savegame's gamedat/
titan u7 map-render STATIC/ --sc 85 --gamedat gamedat/ --view classic

# Render the entire world map
titan u7 map-render STATIC/ --full -o u7_world.png
```

---

#### `u7 map-sample`

Render a colour-sampled U7 world minimap. Samples the centre pixel of
each tile (or group of tiles at the given scale) and paints IFIX objects
on top sorted by Z order. Much faster than full rendering.

```
titan u7 map-sample <static> [-p PAL] [-o FILE] [--scale N]
                              [--grid] [--sc N ...] [--exclude FLAG ...]
```

| Argument | Description |
|----------|-------------|
| `static` | Path to `STATIC/` directory |
| `-p FILE`, `--palette FILE` | Path to `PALETTES.FLX` (default: `STATIC/PALETTES.FLX`) |
| `-o FILE`, `--output FILE` | Output PNG path (default: auto-named) |
| `--scale N` | Tiles per output pixel: `1` = full 3072×3072, `4` = 768×768, `8` = 384×384 (default: 4) |
| `--grid / --no-grid` | Overlay superchunk grid lines (default: off) |
| `--grid-size N` | Grid line width (default: 1) |
| `--sc N` | Only sample these superchunks (repeatable) |
| `--exclude FLAG` | Exclude shapes by TFA flag (repeatable) |

**Examples**
```bash
# Default 768×768 minimap of the whole world
titan u7 map-sample STATIC/ -o minimap.png

# Smaller 384×384 thumbnail with superchunk grid
titan u7 map-sample STATIC/ --scale 8 --grid -o minimap_grid.png

# Full resolution (3072×3072) minimap
titan u7 map-sample STATIC/ --scale 1 -o minimap_full.png
```

---

### U7 type flag commands

---

#### `u7 typeflag-dump`

Dump U7 shape flag data from `TFA.DAT`, `SHPDIMS.DAT`, `WGTVOL.DAT`,
and `OCCLUDE.DAT`.  Includes all per-shape flags, 3D dimensions, shape
class, pixel dimensions, weight, volume, occlusion, and animation type
(decoded from the TFA animation nibbles at offset 3072).

Three output formats:
- **summary** (default) — per-shape table with dimensions, weight, volume, and flag names
- **detail** — comprehensive reference with raw TFA hex, shape class names, animation types, statistics
- **csv** — machine-readable CSV with every decoded field as a column

> **BG vs SI:** Black Gate and Serpent Isle use the same TFA.DAT binary
> format (3 bytes × 1024 shapes + 512 animation nibbles).  The structure
> is identical — only the per-shape flag values differ between games.
> Run `typeflag-dump` on each game's `STATIC/` to compare.

```
titan u7 typeflag-dump <static> [-o FILE] [-f FORMAT]
```

| Argument | Description |
|----------|-------------|
| `static` | Path to `STATIC/` directory containing `TFA.DAT` |
| `-o FILE`, `--output FILE` | Write dump to this file |
| `-f FORMAT`, `--format FORMAT` | Output format: `summary` (default), `detail`, `csv` |

**Examples**
```bash
# Print statistics summary to terminal
titan u7 typeflag-dump STATIC/

# Save detailed per-shape reference to file
titan u7 typeflag-dump STATIC/ -f detail -o tfa_reference.txt

# Export as CSV for spreadsheet analysis
titan u7 typeflag-dump STATIC/ -f csv -o tfa_data.csv

# Compare Black Gate vs Serpent Isle
titan u7 typeflag-dump "C:/GOG Games/Ultima VII/ULTIMA7/STATIC" -f csv -o tfa_bg.csv
titan u7 typeflag-dump "C:/GOG Games/Ultima VII/SERPENT/STATIC" -f csv -o tfa_si.csv
```

---

### U7 save commands

---

#### `u7 save-list`

List all entries inside an Exult U7 savegame with their sizes.
Supports both ZIP (modern) and FLEX (legacy) container formats.

```
titan u7 save-list <file>
```

| Argument | Description |
|----------|-------------|
| `file` | Path to an Exult `.sav` file (e.g. `exult00bg.sav`) |

**Example**
```bash
titan u7 save-list exult00bg.sav
```

---

#### `u7 save-extract`

Extract all (or a single named) entry from an Exult U7 savegame.

```
titan u7 save-extract <file> [-o DIR] [-e NAME]
```

| Argument | Description |
|----------|-------------|
| `file` | Path to Exult `.sav` file |
| `-o DIR`, `--output DIR` | Output directory (default: `./<savename>/`) |
| `-e NAME`, `--entry NAME` | Extract only this named entry, e.g. `flaginit` |

Common entries inside a U7 save: `npc.dat`, `monsnpcs.dat`, `usecode.dat`,
`usecode.var`, `flaginit`, `gamewin.dat`, `schedule.dat`, `identity`,
`scrnshot.shp`, `saveinfo.dat`, `notebook.xml`, `u7ireg00`–`u7ireg8f`.
Serpent Isle saves also include `keyring.dat`.

**Examples**
```bash
titan u7 save-extract exult00bg.sav -o save_bg/
titan u7 save-extract exult00bg.sav -e flaginit -o flags/
```

---

#### `u7 gflag-dump`

Dump global flags from an Exult savegame or a loose `flaginit` file.
Flags are stored as one byte per flag index (0 = unset, nonzero = set).
The file is truncated at the last nonzero flag by Exult's
`compact_global_flags()` before save.

Three output formats:
- **summary** (default) — total/set counts
- **detail** — lists every nonzero flag with decimal & hex addresses and values
- **csv** — machine-readable CSV (`index,index_hex,value,value_hex`)

```
titan u7 gflag-dump <file> [-o FILE] [-f FORMAT]
```

| Argument | Description |
|----------|-------------|
| `file` | Exult `.sav` file **or** loose `flaginit` file |
| `-o FILE`, `--output FILE` | Write dump to this file |
| `-f FORMAT`, `--format FORMAT` | Output format: `summary` (default), `detail`, `csv` |

> Accepts either a `.sav` archive (flaginit is extracted automatically) or
> a loose `flaginit` file (e.g. extracted with `save-extract` or found in
> the `gamedat/` directory).

**Examples**
```bash
# Quick summary from a save
titan u7 gflag-dump exult00bg.sav

# Detailed flag listing
titan u7 gflag-dump exult00bg.sav -f detail

# Export as CSV
titan u7 gflag-dump exult00bg.sav -f csv -o bg_gflags.csv

# From a loose flaginit file
titan u7 gflag-dump gamedat/flaginit -f detail -o gflags.txt
```

---

#### `u7 save-info`

Show consolidated save metadata: game identity, real-world save timestamp,
in-game clock, party roster with stats, game state (camera position, music,
combat flags), and schedule summary.

```
titan u7 save-info <file> [-o FILE]
```

| Argument | Description |
|----------|-------------|
| `file` | Exult `.sav` file |
| `-o FILE`, `--output FILE` | Write output to this file |

> Reads `identity`, `saveinfo.dat`, `gamewin.dat`, and `schedule.dat` from
> the save archive.  Any missing entry is skipped gracefully.

**Examples**
```bash
titan u7 save-info exult00bg.sav
titan u7 save-info exult01si.sav -o save_report.txt
```

---

#### `u7 save-npcs`

Dump NPC data from `npc.dat` inside an Exult savegame.  Parses each NPC's
fixed-header fields: name, shape, position, health, strength, dexterity,
intelligence, combat, magic, mana, experience, food, schedule type,
alignment, attack mode, and status flags.

IREG inventory sections are skipped.  For reliable container nesting
detection, pass `--static` pointing to the game's STATIC directory so
TFA.DAT can identify container shapes (class 6).  Without `--static`,
a heuristic treats all 12-byte IREG entries with type ≠ 0 as containers.

Three output formats:
- **summary** (default) — counts: total, named, in-party, alive
- **detail** — one line per NPC with key stats and flags
- **csv** — full machine-readable CSV

```
titan u7 save-npcs <file> [--static DIR] [-o FILE] [-f FORMAT]
```

| Argument | Description |
|----------|-------------|
| `file` | Exult `.sav` file |
| `--static DIR` | Path to STATIC directory (for TFA container detection) |
| `-o FILE`, `--output FILE` | Write dump to this file |
| `-f FORMAT`, `--format FORMAT` | Output format: `summary` (default), `detail`, `csv` |

**Examples**
```bash
titan u7 save-npcs exult00bg.sav
titan u7 save-npcs exult00bg.sav --static "C:/U7BG/STATIC" -f detail
titan u7 save-npcs exult00bg.sav -f csv -o bg_npcs.csv
```

---

#### `u7 save-schedules`

Dump NPC daily schedules from `schedule.dat` inside an Exult savegame.
Auto-detects the schedule format: original U7 4-byte entries, Exult 8-byte
entries, or Exult 8-byte with script names.

Each schedule entry specifies a 3-hour time period (0 = midnight–2am …
7 = 9pm–11pm), an activity type (e.g. `sleep`, `eat`, `tend_shop`,
`patrol`), and a target tile position.

Three output formats:
- **summary** (default) — NPC count and total entry count
- **detail** — per-NPC schedule listing with activity names and positions
- **csv** — machine-readable CSV

```
titan u7 save-schedules <file> [-o FILE] [-f FORMAT]
```

| Argument | Description |
|----------|-------------|
| `file` | Exult `.sav` file |
| `-o FILE`, `--output FILE` | Write dump to this file |
| `-f FORMAT`, `--format FORMAT` | Output format: `summary` (default), `detail`, `csv` |

**Examples**
```bash
titan u7 save-schedules exult00bg.sav
titan u7 save-schedules exult00bg.sav -f detail -o schedules.txt
titan u7 save-schedules exult00bg.sav -f csv -o schedules.csv
```

---

#### `u7 font-create`

Interactive wizard for creating U7 FONTS.VGA-compatible shape files from
TrueType font sources. Walks through game selection (BG/SI) — immediately
displays the resolved Exult font archive path from `exult.cfg` — then
scans the game directory for all `*font*.vga` archives (including mod
patch directories) and presents a numbered pick-list. Selecting an
archive shows a live slot table with real frame counts and cell heights
read from the actual Flex records. Continues through font slot selection,
shape naming (descriptive label + `.shp` filename), TTF source (6 built-in
or custom path), rendering method (mono, LUT downscale, grayscale
threshold, hollow gradient), dimension overrides, palette / gradient
preset selection (with ANSI colour swatches), ASCII art preview, and
output format.

For fonts that map glyphs to non-standard positions (e.g. Gargish), the
encoder automatically copies a representative glyph into frame 65 (‘A’)
as an Exult Studio preview placeholder, since Exult Studio hardcodes
frame 65 as the font thumbnail.

With `--config`, reads all parameters from a TOML recipe file and generates
the shape non-interactively.

```
titan u7 font-create [--config FILE] [-o FILE]
```

| Argument | Description |
|----------|-------------|
| `--config FILE`, `-c FILE` | TOML config file (skip interactive prompts) |
| `-o FILE`, `--output FILE` | Output file path |

**Interactive mode** (no arguments):
```bash
titan u7 font-create
```

**Non-interactive mode** (TOML recipe):
```bash
titan u7 font-create --config recipe.toml
titan u7 font-create --config recipe.toml -o my_font.shp
```

**Recipe TOML schema:**
```toml
[target]
game = "BG"           # "BG" or "SI"
slot = 2              # FONTS.VGA shape index (0-7 BG, 0-10 SI)
cell_height = 8       # Override (optional if slot pre-fills)
ink_height = 7        # Override (optional)
h_lead = 0            # Override (optional)

[source]
font = "dosVga437"    # Built-in key or path: "./MyFont.ttf"

[rendering]
method = "mono"       # "mono", "lut", "threshold", "hollow_gradient"
# lut = "black_ink"   # Required if method=lut

# --- Hollow gradient options (method = "hollow_gradient" only) ---
# gradient_preset = "warm_flame"   # Use a named preset (see list below)
# gradient_indices = [36, 181, 182, 183, 184, 185]  # OR manual palette indices
# stroke_width = 1                 # Outline width in pixels
# stroke_index = 0                 # Palette index for stroke (overridden by preset)
# gradient_steps = 6               # Number of colour stops when resolving a preset

[palette]
ink = 0               # Palette index for ink pixels (mono/threshold)
transparent = 255
# file = "PALETTES.FLX"  # Explicit palette file (auto-discovered if omitted)

[output]
format = "shp"        # "shp", "flex", "both"
path = "./my_font.shp"
# flex_source = "./fonts_original.vga"  # Auto-resolved from exult.cfg if omitted
```

**Flex output & Exult config resolution:**

When `format = "flex"` or `"both"`, the wizard resolves the target font
archive by parsing Exult's `exult.cfg`:

1. Auto-discovers `exult.cfg` at `%LOCALAPPDATA%\Exult\exult.cfg` (Windows)
   or `~/.exult.cfg` (Linux/macOS)
2. Reads the game base path (`config/disk/game/{blackgate,serpentisle}/path`)
3. Reads the font config (`config/gameplay/fonts`) — defaults to `"original"`
4. Maps to the correct filename:
   - `"disabled"` → `<PATCH>/fonts.vga`
   - `"original"` → `<PATCH>/fonts_original.vga`
   - `"serif"` → `<PATCH>/fonts_serif.vga`
5. Displays the resolved path and offers to accept, use a mod's patch
   directory instead, or enter a custom path

For mods, enter the mod's patch directory (e.g.
`C:\Ultima\ultima7si\SERPENT\mods\PaganExulted\patch`) and the wizard
appends the correct font filename automatically.

The archive is auto-extended if the target slot exceeds the current record
count, so new slots (11+) work without manual scripting.

**Hollow gradient** renders each glyph with a black stroke outline and
a vertical colour gradient fill. You can specify colours in two ways:

1. **Preset name** (`gradient_preset`) — hex CSS colours from the preset
   are interpolated into `gradient_steps` stops and matched to the nearest
   game palette entries at generation time.
2. **Manual indices** (`gradient_indices`) — raw palette index array used
   as-is. Overrides any preset.

**Built-in gradient presets:**

| Key | Name | Colours | Source |
|-----|------|---------|--------|
| `warm_flame` | Warm Flame | `#ff9d3c` → `#7d2c00` | U7 SI palette |
| `sunrise` | Sunrise | `#FF512F` → `#F09819` | uiGradients |
| `juicy_orange` | Juicy Orange | `#FF8008` → `#FFC837` | uiGradients |
| `citrus_peel` | Citrus Peel | `#FDC830` → `#F37335` | uiGradients |
| `koko_caramel` | Koko Caramel | `#D1913C` → `#FFD194` | uiGradients |
| `blood_red` | Blood Red | `#f85032` → `#e73827` | uiGradients |
| `sin_city_red` | Sin City Red | `#ED213A` → `#93291E` | uiGradients |
| `firewatch` | Firewatch | `#cb2d3e` → `#ef473a` | uiGradients |
| `master_card` | Master Card | `#f46b45` → `#eea849` | uiGradients |
| `sun_horizon` | Sun on the Horizon | `#fceabb` → `#f8b500` | uiGradients |
| `learning_leading` | Learning and Leading | `#F7971E` → `#FFD200` | uiGradients |
| `electric_violet` | Electric Violet | `#4776E6` → `#8E54E9` | uiGradients |
| `purple_love` | Purple Love | `#cc2b5e` → `#753a88` | uiGradients |
| `deep_purple` | Deep Purple | `#673AB7` → `#512DA8` | uiGradients |
| `reef` | Reef | `#00d2ff` → `#3a7bd5` | uiGradients |
| `royal` | Royal | `#141E30` → `#243B55` | uiGradients |
| `midnight_city` | Midnight City | `#232526` → `#414345` | uiGradients |
| `frost` | Frost | `#000428` → `#004e92` | uiGradients |
| `cool_sky` | Cool Sky | `#2980B9` → `#6DD5FA` | uiGradients |
| `sexy_blue` | Sexy Blue | `#2193b0` → `#6dd5ed` | uiGradients |
| `cold_shivers` | Cold Shivers | `#83a4d4` → `#b6fbff` | uiGradients |
| `lush` | Lush | `#56ab2f` → `#a8e063` | uiGradients |
| `mojito` | Mojito | `#1D976C` → `#93F9B9` | uiGradients |
| `quepal` | Quepal | `#11998e` → `#38ef7d` | uiGradients |
| `kyoto` | Kyoto | `#c21500` → `#ffc500` | uiGradients |
| `witching_hour` | Witching Hour | `#c31432` → `#240b36` | uiGradients |
| `stellar` | Stellar | `#7474BF` → `#348AC7` | uiGradients |
| `flare` | Flare | `#f12711` → `#f5af19` | uiGradients |
| `crimson_tide` | Crimson Tide | `#642B73` → `#C6426E` | uiGradients |
| `steel_gray` | Steel Gray | `#1F1C2C` → `#928DAB` | uiGradients |

**Built-in TTF keys:** `dosVga437`, `ophidean`, `brit_plaques`,
`brit_plaquesSmall`, `brit_signs`, `gargish`

**Built-in LUT keys:** `black_ink`, `white_glow`, `yellow_text`,
`red_text`, `runic_multicolor`, `serpentine_metal`, `serpentine_gold`

---

### Configuration commands (shared)

---

#### `setup`

Interactive first-time setup wizard. Detects your Ultima 8 (and optionally
Ultima 7) installation, detects third-party engine saves, and writes
`titan.toml` in the current directory. Optionally extracts `shapes/` and
`globs/` immediately.

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

After setup, U8 map commands require no path flags:
```bash
titan setup
titan u8 map-render -m 5
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

The legacy flat format is still supported (treated as Ultima 8 config).
The new multi-game format uses `[u8.*]`, `[u7bg.*]`, `[u7si.*]` sections.

#### Legacy format (Ultima 8 only)

```toml
[game]
base     = "C:/Program Files (x86)/GOG Galaxy/Games/Ultima 8"  # GOG Galaxy default
language = "ENGLISH"      # language sub-folder; "" for flat mode

[paths]
fixed     = "FIXED.DAT"
palette   = "U8PAL.PAL"
typeflag  = "TYPEFLAG.DAT"
shapes    = "shapes/"
globs     = "globs/"
nonfixed  = "U8SAVE.000"
```

#### Multi-game format

```toml
[u8.game]
base     = "C:/Program Files (x86)/GOG Galaxy/Games/Ultima 8"
language = "ENGLISH"

[u8.paths]
fixed     = "FIXED.DAT"
palette   = "U8PAL.PAL"
typeflag  = "TYPEFLAG.DAT"
shapes    = "shapes/"
globs     = "globs/"
nonfixed  = "U8SAVE.000"

[u7bg.game]
base     = "C:/GOG Games/Ultima VII/ULTIMA7"

[u7bg.paths]
shapes   = "STATIC/SHAPES.VGA"
palette  = "STATIC/PALETTES.FLX"

[u7si.game]
base     = "C:/GOG Games/Ultima VII/SERPENT"

[u7si.paths]
shapes   = "STATIC/SHAPES.VGA"
palette  = "STATIC/PALETTES.FLX"
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
| `u7 save-list` | List entries in an Exult U7 savegame |
| `u7 save-extract` | Extract entries from an Exult U7 savegame |
| `u7 gflag-dump` | Dump global flags from a U7 save or `flaginit` file |
| `u7 save-info` | Show save metadata: identity, timestamp, party, game state |
| `u7 save-npcs` | Dump NPC data from an Exult U7 savegame |
| `u7 save-schedules` | Dump NPC schedules from an Exult U7 savegame |
| `u7 font-create` | Interactive wizard for creating U7 font shapes from TTF |
| `setup` | First-time setup wizard — creates `titan.toml` |
| `config` | Show or edit active `titan.toml` |
