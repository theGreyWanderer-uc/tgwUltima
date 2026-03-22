# Changelog

All notable changes to **titan-ultima** are documented here.

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** (1.0, 2.0, …) — breaking API or CLI changes
- **MINOR** (0.5, 0.6, …) — new features, new commands, new format support
- **PATCH** (0.4.1, 0.4.2, …) — bug fixes, docs, internal improvements

---

## [0.5.3] — 2026-03-22

### Added

- **Speech FLX support** — `FlexArchive` now correctly handles per-NPC
  digital speech archives (`E44.FLX`, `E80.FLX`, `G289.FLX`, etc.). Record 0
  contains a dialogue transcript extracted as `.txt`; remaining records are
  Sonarc-compressed audio at 11,111 Hz extracted as `.raw`.  
  File naming: `[A-Z]\d+.FLX` — language letter + NPC ID.  Nine English
  speech files ship with the Speech Pack add-on disks (NPCs 44, 80, 109,
  129, 289, 385, 433, 597, 666).
- **Text content detection** — `detect_record_type()` now returns `"text"`
  for plain-ASCII records, with `.txt` extension mapping.

### Fixed

- **Name-table false positive** — the fixed 8-byte name-table heuristic now
  rejects data containing space characters, preventing dialogue transcripts
  (speech FLX record 0) from being mis-detected as name tables.
- **Sidecar filename collision** — metadata sidecars renamed from `.txt` to
  `.meta.txt` to avoid overwriting records whose data is also `.txt`
  (speech transcripts).
- **`from_directory()` rebuild** — sidecar skip logic updated for
  `.meta.txt`; real `.txt` data files are no longer excluded.

---

## [0.5.2] — 2026-03-22

### Fixed

- **Build** — fix duplicate `.npy` LUT files in wheel (hatchling was
  double-including `adaptive_resample/luts/` via both package auto-discovery
  and shared-data inclusion; resolved with explicit `exclude` + `force-include`
  in `pyproject.toml`). PyPI rejected the wheel due to duplicate ZIP entries.

---

## [0.5.1] — 2026-03-22

### Fixed

- **CI** — fix GitHub Actions workflow: remove duplicate push-to-main trigger,
  switch PyPI publishing from API token to Trusted Publishers (OIDC), add
  verbose logging for upload diagnostics.

---

## [0.5.0] — 2026-03-22

### Added

- **FLX name tables** — `FlexArchive` auto-detects and parses embedded name
  tables in record 0 of Flex archives.  SOUND.FLX (fixed 8-byte ASCII entries)
  and MUSIC.FLX (text playlist) are recognised; other archives fall back to
  index-only naming.
- **Named file extraction** — `flex-extract` now writes files as
  `NNNN_NAME.<ext>` (e.g. `0007_TELEPORT.raw`, `0001_intro.xmi`) when a name
  table is present, instead of plain `NNNN.<ext>`.
- **Metadata sidecars** — each extracted record gets a companion `.txt` file
  with the source archive, record index, name, byte size, content type, hex
  header preview, and format-specific details (Sonarc sample rate / length,
  XMIDI FORM size, shape frame count).
- **`flex-list` names** — `flex-list` output now includes a Name column for
  archives with embedded name tables.
- **`summary()` / `record_table()`** — library methods report named record
  counts and display names alongside indices.

### Changed

- **Manifest format** — `_manifest.txt` now has four columns
  (`Index | Size | Filename | Name`) for round-trip rebuilds.
- **`from_directory()` rebuild** — `flex-create` / `from_directory` correctly
  parses `NNNN_NAME.<ext>` stems and skips `.txt` sidecars.

---

## [0.4.0] — 2026-03-20

First public release.

### Added

- **CLI** — 26 Typer-based commands (`titan <command>`) covering Flex archives,
  shapes, palette, Sonarc audio, XMIDI music, world maps, saves, credits,
  type-flag data, gump layout, colour transforms, and unknown code offsets.
- **Map renderer** — full isometric and bird's-eye map rendering with
  engine-accurate dependency-graph depth sorting; six projection views
  (`iso_classic`, `iso_high`, `iso_low`, `iso_north`, `iso_south`,
  `birdseye`).
- **16 TYPEFLAG filter flags** — `--no-fixed`, `--no-solid`, `--no-sea`,
  `--no-land`, `--no-occl`, `--no-bag`, `--no-damaging`, `--no-noisy`,
  `--no-draw`, `--no-ignore`, `--no-roof`, `--no-transl`, `--no-editor`,
  `--no-explode`, `--no-unk46`, `--no-unk47`.
- **Live-object merge** — overlay NPCs and items from `U8SAVE.000` /
  `NONFIXED.DAT` onto the static map.
- **Shape round-trip** — export RLE sprite frames to PNG, edit externally,
  re-import to `.shp`.
- **Configuration** — `titan.toml` config file with auto-path resolution;
  `titan setup` interactive wizard; `titan config` inspector.
- **Library API** — every CLI capability exposed as importable Python modules
  (`titan.flex`, `titan.shape`, `titan.map`, `titan.palette`, `titan.sound`,
  `titan.music`, `titan.save`, `titan.credits`, `titan.typeflag`,
  `titan.xformpal`).
- **PEP 561** — `py.typed` marker for downstream type checking.

---

_Versioning note: this project started at 0.4.0 to reflect the amount of
functionality present at first release. Future releases will increment
normally from here (0.4.1 for patches, 0.5.0 for features, 1.0.0 when the
API is considered stable)._
