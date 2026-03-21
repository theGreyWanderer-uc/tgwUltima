# Changelog

All notable changes to **titan-ultima** are documented here.

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** (1.0, 2.0, …) — breaking API or CLI changes
- **MINOR** (0.5, 0.6, …) — new features, new commands, new format support
- **PATCH** (0.4.1, 0.4.2, …) — bug fixes, docs, internal improvements

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
