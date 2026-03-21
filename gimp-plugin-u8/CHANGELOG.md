# Changelog

All notable changes to the **Ultima 8 Shape Plugin for GIMP 3** are documented here.

---

## [1.0.0] — 2026-03-21

First public release.

### Features

- Native **open / edit / save** of Ultima 8 `.shp` shape files in GIMP 3.
- Each animation frame becomes a separate GIMP layer; guides mark the
  hot-spot origin.
- Optional external palette loading (U8 binary `.pal` or GIMP `.gpl`).
- Hardcoded 256-entry U8 palette for zero-config usage.
- Always-RGBA export strategy with nearest-colour quantizer — works
  correctly regardless of GIMP image mode (RGB or Indexed).
- RLE compression matching the original U8 engine format.
- Parasite-based 4-byte header preservation for byte-perfect round-trips.
- Pure GIO file I/O — no CRT mismatch issues on Windows.
