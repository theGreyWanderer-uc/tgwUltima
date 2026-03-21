# Ultima 8 Shape Plugin for GIMP 3 (`u8shp.c`)

A C file-filter plugin that lets GIMP 3 natively open, edit, and save
Ultima 8 `.shp` shape files.  Each animation frame becomes a GIMP layer;
guides mark the hot-spot origin.

## Quick Start

```bash
# Build (MSYS2 MinGW64 shell)
cd gimp-plugin-u8
gimptool-3.0 --build u8shp.c

# Install to user plug-in dir (Windows - will vary)
mkdir -p "$APPDATA/GIMP/3.0/plug-ins/u8shp"
cp u8shp.exe "$APPDATA/GIMP/3.0/plug-ins/u8shp/"

# Or auto-install (untested)
gimptool-3.0 --install u8shp.c
```

## Build Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| GIMP      | 3.0.x   | Provides `libgimp-3.0`, `libgimpui-3.0` |
| GLib/GIO  | 2.x     | Bundled with GIMP |
| GEGL      | 0.4.x   | Bundled with GIMP |
| Babl      | 0.1.x   | Bundled with GIMP |
| GTK       | 3.x     | For the optional palette dialog |
| gcc       | MinGW64 | On Windows, must match GIMP's toolchain |

`gimptool-3.0 --build` passes all required `-I` and `-l` flags automatically.

## Architecture

### Plugin Registration (GObject Boilerplate)

The plugin uses GIMP 3's GObject-based registration system:

```
U8Shp → GimpPlugIn (via G_DEFINE_TYPE + GIMP_MAIN)
  ├── query_procedures()  →  ["file-u8shp-load", "file-u8shp-export"]
  └── create_procedure()  →  configures load/export with image types,
                              capabilities, file extensions, and palette arg
```

Two procedures are registered:

- **`file-u8shp-load`** — Load procedure. Accepts an optional `palette-file`
  argument (U8 `.pal` or GIMP `.gpl`). When run interactively, shows a file
  chooser dialog for the palette.
- **`file-u8shp-export`** — Export procedure. Declares support for
  `RGB*, INDEXED*` image types and capabilities:
  `CAN_HANDLE_RGB | CAN_HANDLE_ALPHA | CAN_HANDLE_LAYERS | CAN_HANDLE_INDEXED`.

### Load Path

```
u8shp_load()  →  load_image()
  1. g_file_load_contents()     — read entire .shp into memory
  2. load_palette_file()        — optionally load U8PAL.PAL or .gpl
  3. read_shape()               — parse header + frame table
  4. decode_frame() per frame   — RLE decompress to flat pixel buffer
  5. Create GIMP INDEXED image  — set colormap from u8_cmap[768]
  6. One layer per frame        — indexed+alpha, positioned by offset
  7. Guides for hot-spot        — horizontal + vertical
  8. Parasite "u8shp-header4"   — preserves original 4-byte header
```

**Key detail:** The first 4 bytes of the shape file (unknown flags) are
stored as a GIMP parasite on the image. This enables byte-perfect round-trip
saving — the export path retrieves these bytes and writes them back.

### Export Path

```
u8shp_export()  →  export_image()
  1. Find hot-spot from guides
  2. Collect layers (reversed for correct frame order)
  3. Read every layer as R'G'B'A u8 via GEGL/Babl
  4. Quantize each pixel → nearest_u8_index() or U8_TRANSPARENT
  5. RLE-compress each scan line via encode_line()
  6. write_shape() → binary blob with header + frame table + RLE data
  7. g_file_replace_contents() → atomic write to disk
```

**Always-RGBA strategy:** Regardless of whether the image is indexed or RGB,
the export always reads pixel data as `R'G'B'A u8` and re-quantizes to the
U8 palette.  This eliminates an entire class of bugs where GIMP's internal
indexed palette doesn't match the U8 palette (e.g. after mode conversions,
palette edits, or importing from RGB sources).

### Nearest-Colour Quantizer

```c
static guchar nearest_u8_index(guchar r, guchar g, guchar b)
```

Brute-force Euclidean RGB distance over 255 palette entries (index 255 is
reserved for transparency).  Returns immediately on an exact match.

### RLE Format

Each scan line is a sequence of `(skip, data)` pairs:

- **skip** — number of transparent pixels
- **dlen** — compressed format: `low bit = type` (0 = literal, 1 = solid
  fill), `count = dlen >> 1`
- Literal runs copy `count` bytes; solid runs repeat one byte `count` times
- Runs > 127 pixels are split into chunks

### Palette Handling

The plugin embeds a hardcoded 256-entry palette (`u8_cmap[768]`) that matches
`U8PAL.PAL` exactly (6-bit VGA values scaled `(v * 255) / 63`).  Optional
external palette loading supports both formats:

- **U8 binary `.pal`** — 4-byte header + 768 bytes of 6-bit VGA triples
- **GIMP `.gpl`** — text format, auto-detected by `"GIMP Palette"` header

## Critical Bug Fixes & Lessons Learned

### 1. Windows CRT Mismatch Crash

**Symptom:** Plugin crashed silently during export. Output file was 0 bytes.
Debug logging showed data was `fwrite`'d successfully, but `fclose()` never
executed.

**Root cause:** `g_fopen()` uses GLib's C runtime (MSVCRT from MinGW's GLib
build), while `fclose()` uses the plugin's CRT (potentially a different
MSVCRT instance).  On Windows, `FILE*` handles are **not portable across CRT
boundaries**.

**Fix:** Replace all `g_fopen`/`fwrite`/`fclose` with pure GIO:

```c
g_file_replace_contents(file, blob, blob_len,
                        NULL, FALSE, G_FILE_CREATE_NONE,
                        NULL, NULL, error);
```

This uses the `GFile` object directly — no path extraction, no CRT, fully
cross-platform.

### 2. RGB Export Produced Wrong Colours

**Symptom:** Opening a shape, editing in RGB mode, and re-saving produced
"black/white/blue" garbage.

**Root cause:** The original export path only handled indexed images.  When
GIMP's export pipeline converted RGB → Indexed, it used GIMP's built-in
quantizer, which created a **new** 256-colour palette unrelated to the U8
palette.  The resulting indices mapped to completely wrong colours.

**Fix:** Always read as `R'G'B'A u8` and re-quantize with
`nearest_u8_index()` against the known U8 palette.

### 3. NULL Export Options from Raw PDB Calls

**Symptom:** Calling `file-u8shp-export` via raw PDB (instead of
`Gimp.file_save()`) could pass `NULL` for the `options` parameter.

**Fix:** Guard `gimp_export_options_get_image()` with a null check:

```c
if (options)
    expret = gimp_export_options_get_image(options, &image);
```

## File Locations

| File | Purpose |
|------|---------|
| `gimp-plugin-u8/u8shp.c` | Canonical source (build from here) |
| `gimp-plugin-u8/reference/` | GIMP 3 plugin creation guide and U7 example plugin |
| `C:\Users\<user>\AppData\Roaming\GIMP\3.0\plug-ins\u8shp\u8shp.exe` | Installed binary (Windows) |

## Testing

Basic round-trip test (load → save without modification):

```bash
gimp-console-3.exe -i --batch-interpreter python-fu-eval -b \
  "exec(open('gimp_roundtrip_test.py').read())"
```

Output size should match the titan CLI's `shape-import` output for the
same shape file (verifiable with `python -m titan shape-export`).
