# GIMP 3 Python Batch Scripting for U8 Shapes

How to drive GIMP 3 headlessly via `gimp-console-3.exe` to load, manipulate,
and re-export Ultima 8 shape files using the `u8shp` plugin.

## Running a Batch Script

```bash
gimp-console-3.exe -i --quit --batch-interpreter python-fu-eval -b \
  "exec(open(r'C:/path/to/script.py').read())"
```

| Flag | Meaning |
|------|--------|
| `-i` | No GUI (headless) |
| `--quit` | Exit cleanly after batch completes (propagates exit code 0 = success) |
| `--batch-interpreter python-fu-eval` | Use Python 3 (required in GIMP 3; no default interpreter) |
| `-b "..."` | The Python expression to evaluate |

**Windows tip:** Wrap the command in a `.bat` file to avoid PowerShell/cmd
quoting issues:

```bat
@echo off
"C:\Program Files\GIMP 3\bin\gimp-console-3.exe" -i --quit ^
  --batch-interpreter python-fu-eval ^
  -b "exec(open(r'C:/path/to/script.py').read())"
```

**Exit code:** With `--quit`, `gimp-console` exits cleanly and returns
exit code 0 on success (non-zero on error). The message
`batch command executed successfully` confirms completion.

## API Reference

GIMP 3's Python GI bindings (`gi.repository.Gimp`) have significant differences from GIMP 2's Script-Fu and Python-Fu.

### Imports

```python
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gio, Gegl
```

### Loading a File

```python
image = Gimp.file_load(
    Gimp.RunMode.NONINTERACTIVE,
    Gio.File.new_for_path(SHP_IN)
)
```

Returns a `Gimp.Image`. Dispatches to the correct file plugin based on
the `.shp` extension.

### Saving a File

```python
success = Gimp.file_save(
    Gimp.RunMode.NONINTERACTIVE,
    image,
    Gio.File.new_for_path(SHP_OUT)
)
```

Returns `True`/`False`. Dispatches to the correct file plugin based on
the `.shp` extension and handles export options internally.

### Image Operations

| Operation | GIMP 3 API | Notes |
|-----------|-----------|-------|
| Get layers | `image.get_layers()` | NOT `list_layers()` |
| Delete image | `image.delete()` | NOT `Gimp.image_delete()` |
| Convert to RGB | `image.convert_rgb()` | For indexed → RGB |
| Get palette | `image.get_palette()` | Returns `Gimp.Palette` |
| Quit GIMP | Use `--quit` CLI flag | Don't call `Gimp.quit()` in scripts |

### Palette Manipulation

```python
pal = image.get_palette()

# Read a colour
color = pal.get_entry_color(37)     # returns Gimp.RGB

# Write a colour (swap palette entries)
green_color = pal.get_entry_color(64)
pal.set_entry_color(37, green_color)

# Count entries
n = pal.get_color_count()           # typically 256
```

**Important:** Palette changes only affect the colour lookup table, not the
pixel indices. To actually recolour pixels, you must:
1. Swap palette entries
2. Convert to RGB (`image.convert_rgb()`)
3. Export — the plugin's quantizer maps the new RGB values back to the
   correct U8 palette indices

### GEGL Buffer Access (Advanced)

```python
layer = image.get_layers()[0]
buf = gimp_drawable_get_buffer(layer)   # or: layer.get_buffer() — varies

# Read raw pixel data
rect = Gegl.Rectangle.new(0, 0, buf.props.width, buf.props.height)
data = buf.get(rect, 1.0, None, Gegl.AbyssPolicy.NONE)

# WARNING: buf.set() does NOT work reliably for indexed data.
# The format conversion corrupts palette indices.
# Use palette manipulation + convert_rgb() instead.
```

## Complete Recolour Pipeline

### Strategy: Palette Swap + RGB Convert

This is the proven approach for recolouring indexed sprites:

```
Load indexed .shp
  → Swap palette entries (red slots get green RGB values)
  → Convert to RGB (pixels become actual green RGB)
  → Export via Gimp.file_save()
    → Plugin reads RGBA, quantizes to nearest U8 palette index
    → Green RGB → green palette indices in the output .shp
```

### Example Script (Red → Green)

```python
import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gio, Gegl

LOG     = "C:/.../recolor_log.txt"
SHP_IN  = "C:/.../0001.shp"
SHP_OUT = "C:/.../0001_green.shp"

# Full red range (32-47) → green range (64-79)
REMAP = {
    32: 64, 33: 65, 34: 66, 35: 67,
    36: 68, 37: 69, 38: 70, 39: 71,
    40: 72, 41: 73, 42: 74, 43: 75,
    44: 76, 45: 77, 46: 78, 47: 79,
}

log = open(LOG, 'w')
try:
    # Load
    image = Gimp.file_load(
        Gimp.RunMode.NONINTERACTIVE,
        Gio.File.new_for_path(SHP_IN)
    )
    log.write(f"Loaded {len(image.get_layers())} layers\n")

    # Swap palette entries
    pal = image.get_palette()
    for src_idx, dst_idx in REMAP.items():
        pal.set_entry_color(src_idx, pal.get_entry_color(dst_idx))

    # Convert to RGB (locks in the new colours)
    image.convert_rgb()

    # Export
    success = Gimp.file_save(
        Gimp.RunMode.NONINTERACTIVE,
        image,
        Gio.File.new_for_path(SHP_OUT)
    )
    log.write(f"Export: {success}\n")
    image.delete()
    log.write("DONE\n")
except Exception as e:
    import traceback
    log.write(traceback.format_exc())
log.close()
```

### End-to-End Workflow

```
1. Extract .shp from FLX    →  titan flex-extract U8SHAPES.FLX -o shapes/
2. Recolour via GIMP batch  →  gimp-console -i --quit --batch-interpreter ... -b "..."
3. Verify byte counts       →  python -c "compare red vs green byte freqs"
4. Pack back into FLX       →  titan flex-update U8SHAPES.FLX --index 1 --data 0001_green.shp
```

## Pitfalls & Hard-Won Lessons

### 1. No Default Batch Interpreter

GIMP 3 does NOT default to any interpreter. You **must** specify
`--batch-interpreter python-fu-eval`. Without it, you get:
```
No batch interpreter specified.
```

### 2. `buf.set()` Corrupts Indexed Data

Writing to GEGL buffers with `buf.set(rect, format_name, data)` causes
format conversion that corrupts palette indices. For example, writing
index 255 (transparent) gets converted to 11 through Babl's colour space
conversions.

**Workaround:** Never write pixels directly. Use palette manipulation +
`convert_rgb()` to change colours.

### 3. Palette Method Names

| Wrong (doesn't exist) | Correct |
|-----------------------|---------|
| `gimp-image-get-colormap` | `image.get_palette()` |
| `pal.get_colormap()` | `pal.get_entry_color(idx)` |
| `image.list_layers()` | `image.get_layers()` |
| `Gimp.image_delete()` | `image.delete()` |

### 4. Script Exit

Use the `--quit` CLI flag when launching `gimp-console`. This tells GIMP to
exit cleanly after the batch script completes, with proper exit code
propagation (0 = success). **Do NOT** call `Gimp.quit()` in your script —
let `--quit` handle it. Without `--quit`, `gimp-console` hangs indefinitely.

### 5. Log Everything

GIMP's Python console gives no visible stdout/stderr in batch mode. Always
write to a log file and flush after every operation:

```python
log = open('log.txt', 'w')
log.write("step 1\n"); log.flush()
```

This is the only way to debug crashes — if the log stops mid-way through,
you know exactly which operation failed.
