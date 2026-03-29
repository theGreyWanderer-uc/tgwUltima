# Changelog

All notable changes to **titan-ultima** are documented here.

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** (1.0, 2.0, …) — breaking API or CLI changes
- **MINOR** (0.5, 0.6, …) — new features, new commands, new format support
- **PATCH** (0.4.1, 0.4.2, …) — bug fixes, docs, internal improvements

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
