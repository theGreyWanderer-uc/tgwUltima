# Changelog

All notable changes to **titan-ultima** are documented here.

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** (1.0, 2.0, …) — breaking API or CLI changes
- **MINOR** (0.5, 0.6, …) — new features, new commands, new format support
- **PATCH** (0.4.1, 0.4.2, …) — bug fixes, docs, internal improvements

---

## [0.6.5]

### Added

- Added three new U7 data-inspection commands:
  - `titan u7 world-query` for IFIX and IREG placement filtering by shape,
    class, flags, and area.
  - `titan u7 egg-query` for decoded egg trigger inspection with table or CSV
    output.
  - `titan u7 container-browse` for nested container traversal with tree or
    CSV output.
- Expanded U7 naming resolution with layered sources:
  - Base shape names from `TEXT.FLX`.
  - Per-frame names from Exult FLX data.
  - Optional mod overrides from `textmsg.txt` and `shape_info.txt`.
- Added stronger Exult-aware setup and config discovery:
  - Detects runtime `gamedat` paths in `%LOCALAPPDATA%` profile folders.
  - Discovers mod roots, saves, and archive/initgame sources.
  - Writes Exult paths into config when available.
- Added multi-map mod support for `world-query` and `map-render` via
  `--map-num`.
- Improved dialogue web branch reporting:
  - Random branch roll/chance reporting.
  - Flag-branch ending hints to suggest alternate outcomes.

### Fixed

- Corrected dialogue web condition handling for mixed random and
  `strcmp`-driven branch flow.

---

## [0.6.4]

### Added

- **U7 loose NPC schedule exports** — added `titan u7 npc-dump` for loose
  `npc.dat` / `GAMEDAT` data and `titan u7 schedule-dump` for loose
  `schedule.dat`, including automatic sibling `npc.dat` name resolution.
- **U7 TFA reference output and notes** — added
  `u7 typeflag-dump --format detail` output plus source-checked parser notes
  for `TFA.DAT`, `SHPDIMS.DAT`, `WGTVOL.DAT`, `OCCLUDE.DAT`, shape classes,
  and BG/SI animation nibbles.
- **U7 Exult runtime source discovery** — `titan setup` now records live
  Exult profile `GAMEDAT` paths when initialized, detects mod
  `patch/initgame.dat` archives, and `u7 gamedat-info --mod NAME` can inspect
  configured/AppData mod sources.

### Fixed

- Replaced CSV serialisation in `typeflag.py`, `save.py`,
  and `cli.py` with Python's standard `csv.writer` module for robust export
  output.
- Corrected U7 NPC and inventory parsing edge cases in runtime data paths,
  including IREG special-entry skipping so `npc.dat` parsing continues past
  Avatar inventory and exports all declared NPC records.
- Removed duplicate raw type-flag columns from U7 NPC CSV exports.
- Corrected U7 TFA parsing so BG/SI animation bytes at offset `3 * 1024` are
  decoded as packed animation nibbles instead of extra shape records.
- Corrected U7 SHPDIMS decoding/export labels to expose raw `dimY, dimX`
  bytes, X/Y obstacle bits, and decoded dimension payloads.
- Corrected the U8 dialogue web engine loop safety guard so long valid
  conversations that pause at an `Ask` no longer force-end after ten topic
  choices, while no-pause runaway loops are still capped.
- Corrected loose Exult `GAMEDAT/npc.dat` sex export to decode runtime
  `type_flags` bit 9 directly, while `INITGAME.DAT` still uses Exult's
  original new-game inversion path.
- Added raw ZIP archive support for Exult mod `initgame.dat` containers and
  initgame parsing in Exult mod data paths.

### Correction

- The U7 Exult runtime source discovery note above was incomplete: Exult
  stores initialized base-game and mod runtime files under its profile data
  folders, not only under the installed game or mod directories. The expanded
  setup/path handling is tracked in `0.6.5`.

---

## [0.6.3]

### Added

- **Expanded `titan setup` wizard** — setup now detects and configures
  Ultima 8 plus Ultima 7 (Black Gate and Serpent Isle) in one pass,
  prints a consolidated path summary, supports confirmation before write,
  and writes multi-game config sections (`[u8.*]`, `[u7bg.*]`, `[u7si.*]`).
- **New `titan dialogue` command group** — added end-to-end U8 dialogue web
  workflow commands:
  - `titan dialogue prepare` to generate runtime dialogue artifacts
  - `titan dialogue validate` to verify required outputs
  - `titan dialogue launch` to start the local dialogue web viewer
- **Dialogue web theme system updates** — added runtime theme switching with
  Palettes, preview swatches, tokenized CSS theme
  contract improvements (`--bg-main`, `--font-heading`, `--text-soft`), and
  readability/UX polish for Look/Book surfaces (including clearer book-first
  discoverability for `BASEBOOK` in the Objects list).

---

## [0.6.2]

### Added

- **`u7 map-render` tile-rectangle highlights** — new repeatable
  `--highlight-tile-rect tx0,ty0,tx1,ty1,#RRGGBB[AA]` option overlays
  world-tile rectangle bounds on rendered maps. Each rectangle can have
  its own colour code, with optional alpha channel (`#RRGGBBAA`).
- **Highlight stroke control** — new `--highlight-width` option controls
  rectangle outline thickness in pixels.
- **Highlight visibility controls** — `--highlight-fill-alpha` adds a
  configurable semi-transparent fill, `--highlight-lift` applies projected
  lift to overlays, and `--highlight-labels` draws per-rectangle coordinate
  labels (`tx0,ty0,tx1,ty1`) for easier map annotation.
- **Custom highlight labels** — `--highlight-tile-rect` now accepts optional
  custom label text (`...,#RRGGBB,label`). Highlight text is centered in each
  rectangle both horizontally and vertically.
- **Default highlight fill** — fill defaults to `128` (50% opacity), so
  underlying terrain and objects remain visible.
- **RGBA composited highlight fill** — rectangle fill is rendered through an
  overlay layer and composited onto the map for proper translucent blending.
- **Larger overlay text** — highlight coordinate/custom label text size is
  now tripled for readability on full-world renders.
- **Zone profiles for `u7 map-render`** — new `--zone-profile` option loads
  canonical rectangle sets from packaged JSON data (`si_zones`,
  `bg_zones`) and renders them through the existing highlight path.
- **Zone ID filtering** — new repeatable `--zone-id` option selects specific
  zones from a profile; `--all-zones` includes every zone.
- **Overlay composition retained** — profile-based zones and manual
  `--highlight-tile-rect` overlays can be used together in the same render.

### Fixed

- **U7 music export sound compatibility** — added a dedicated General MIDI
  conversion mode to `u7 music-export` (`--target gm`) to address SC-55/
  SC-88 playback issues from MT-32-oriented track data. The conversion path
  now applies GM-friendly patch remapping while preserving MIDI timing.

---

## [0.6.1]

### Fixed

- **`map-sample` RLE terrain** — colour-sampled minimap now uses nearby-flat
  fill for RLE terrain shapes, matching the classic renderer. Eliminates
  misleading centre-pixel colours from large sprites.
- **`map-sample` IFIX overlay removed** — fixed stray coloured specs and
  lavender/purple dots caused by sampling single pixels from mountain wall
  and small IFIX object sprites.
- **`map-sample` void tile halo** — shape 12 frame 0 (palette-cycling void)
  no longer bleeds bright blue around mountains and buildings; also fixed
  `_find_nearby_flat()` whole-chunk fallback to skip the void tile.
- **`map-sample` fortress floor** — remap shape 18 frame 16 (near-black
  indoor floor) to frame 0 (stone grey) so castle interiors are visible.
- **`map-sample` grid overlay** — dual-tier grid: blue chunk grid (scale ≤ 2)
  with coordinate labels + red superchunk grid with SC number labels.
- **CLI help** — `--grid` descriptions for `map-render` and `map-sample` now
  correctly describe chunk vs superchunk grid behaviour.

---

## [0.6.0]

### Added — Ultima 7 support

- **Multi-game architecture** — game-specific commands live under `titan u8`
  and `titan u7` sub-apps; shared commands remain at root.
- **U7 shapes** — read/write U7 RLE shapes and VGA Flex archives
  (`SHAPES.VGA`, `FACES.VGA`, etc.). `U7Shape.to_bytes()` / `.save()` for
  round-trip encoding. New commands: `shape-export`, `shape-batch`.
- **U7 palettes** — 12-palette `PALETTES.FLX` support. New: `palette-export`.
- **U7 music** — Flex-based XMIDI extraction (`ADLIBMUS.DAT`, `MT32MUS.DAT`,
  etc.) and standalone `.xmi` conversion. Multi-track XMIDI now produces
  MIDI Format 1. New: `u7 music-export`, `u8 music-export`.
- **U7 sound** — Creative Voice (.voc) decoder with ADPCM support; batch
  speech export from `U7SPEECH.SPC`. New: `voc-export`, `speech-export`,
  `u8 sound-export-all`.
- **U7 map rendering** — parallel oblique projection (classic / flat / steep),
  IFIX + optional IREG objects, dependency-DAG depth sorting, TFA flag
  filtering, `--full` world render, colour-sampled minimap.
  New: `map-render`, `map-sample`.
- **U7 type flags** — `TFA.DAT`, `SHPDIMS.DAT`, `WGTVOL.DAT`, `OCCLUDE.DAT`
  parser with animation nibbles, shape class enum, and `build_exclude_set()`.
  New: `typeflag-dump` (summary / detail / csv).
- **U7 savegame reader** — Exult `.sav` (ZIP & FLEX), global flags, save
  metadata, NPC stats, schedules. New: `save-list`, `save-extract`,
  `gflag-dump`, `save-info`, `save-npcs`, `save-schedules`.
- **Multi-game config** — `titan.toml` now supports `[u7bg.*]` / `[u7si.*]`
  sections alongside the existing `[u8.*]` / legacy `[game]` format.
- **Enhanced grid overlays** — chunk coordinate labels and superchunk
  boundary lines for both U7 and U8 map commands.

### Added — U7 font creation

- **Font wizard** — new `titan u7 font-create` interactive wizard builds
  Exult-compatible font shapes from TrueType sources. Steps: game/archive
  selection, slot picking (11 BG/SI stock presets), TTF source, render
  method, dimensions, palette, preview, and output (`.shp` or Flex patch).
  Non-interactive batch mode via `--config recipe.toml`.
- **Font rendering pipeline** — `titan.fonts` package: FreeType mono/grayscale
  renderer, palette LUT mapper (7 built-in LUTs), glyph-to-shape encoder.
- **Hollow gradient rendering** — stroke outline + vertical gradient fill with
  morphological erosion; 30 built-in gradient presets (from U7 palette and
  [uiGradients](https://uigradients.com)) with ANSI colour swatch display.
  Hex-to-palette resolver maps any CSS gradient to nearest game indices.
- **Bundled TTFs** — six fonts: dosVga437-win, Ophidean Runes, Britannian
  Runes I/II/II Sans Serif, and Gargish. See [FONTS_CREDITS.md](FONTS_CREDITS.md).
- **Exult integration** — parses `exult.cfg` for game paths and font config;
  scans game directories for `*font*.vga` archives; shows live slot tables
  from actual Flex data; resolves mod patch directories for archive patching.
- **Exult Studio preview** — auto-fills frame 65 (the hardcoded thumbnail
  frame) with a representative glyph for non-standard layouts (Gargish,
  Runic, Serpentine).

### Changed

- **CLI restructure** — U8 commands moved under `titan u8 <cmd>` with
  deprecated root-level aliases. Modules relocated to `titan.u8.*` with
  backward-compatible shims.

### Fixed

- U7 palette 6-bit→8-bit scaling no longer fooled by garbage at index 255.
- `map-render` hex superchunk input (`--sc 0x55`) now accepted.
- RLE terrain tiles promoted to depth-sorted objects with correct anchoring;
  eliminates black strips between multi-tile terrain.
- Dependency-DAG uses actual pixel bounds for overlap (fixes tall sprites
  rendering on top of roofs).
- Cross-superchunk depth ordering uses a single global pass (fixes
  furniture visible through rooftops at boundaries).

### Known issues

- U7 MIDI export doesn't sound 100% yet — some tracks may have timing or
  instrument mapping differences compared to the original game playback.

---

## [0.5.3] — 2026-03-22

### Added

- **FLX name tables** — auto-detect and parse embedded name tables
  (`SOUND.FLX`, `MUSIC.FLX`); named file extraction (`NNNN_NAME.<ext>`);
  metadata sidecars (`.meta.txt`); `flex-list` Name column; library
  `summary()` / `record_table()` methods.
- **Speech FLX** — per-NPC speech archives (`E44.FLX`, etc.) with dialogue
  transcript extraction and Sonarc audio at 11,111 Hz.
- **Text content detection** — `detect_record_type()` returns `"text"` for
  plain-ASCII records.

### Changed

- Manifest format expanded to four columns for round-trip rebuilds.

### Fixed

- Name-table heuristic rejects space characters (prevents speech transcript
  false positives).
- Sidecar extension changed `.txt` → `.meta.txt` to avoid overwriting data.
- `from_directory()` rebuild updated for `.meta.txt` sidecars.
- Build: fix duplicate `.npy` LUT files in wheel (hatchling config).
- CI: Trusted Publishers (OIDC) for PyPI; remove duplicate trigger.

---

## [0.4.0] — 2026-03-20

First public release.

### Added

- **CLI** — 26 Typer-based commands covering Flex archives, shapes, palette,
  Sonarc audio, XMIDI music, world maps, saves, credits, type-flag data,
  gump layout, colour transforms.
- **U8 map renderer** — isometric and bird's-eye views with dependency-graph
  depth sorting, 16 TYPEFLAG filter flags, live-object merge from saves.
- **Shape round-trip** — export RLE frames to PNG, edit, re-import.
- **Configuration** — `titan.toml` with auto-path resolution; `titan setup`
  wizard; `titan config` inspector.
- **Library API** — all CLI capabilities as importable Python modules.
- **PEP 561** — `py.typed` marker for type checking.

---

_Versioning note: this project started at 0.4.0 to reflect the amount of
functionality present at first release._
