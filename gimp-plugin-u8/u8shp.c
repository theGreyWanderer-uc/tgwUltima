/*
 * Ultima 8 Shape (.shp) file filter for GIMP 3.x
 *
 * Loads and exports Ultima 8 shape files as multi-layer indexed images.
 * Each layer represents one animation frame.  Guides mark the hot-spot.
 *
 * Format reference: Pentagram engine (The Pentagram Team, 2002-2005)
 * Plugin structure: modelled after the Exult U7 shape plugin (u7shp.cc)
 *
 * (C) 2025 – built with knowledge from titan.py and the Pentagram source.
 *
 * Self-contained: no external libraries beyond GIMP 3 / GLib / GEGL.
 * Build:  gimptool-3.0 --build u8shp.c
 * Install: gimptool-3.0 --install u8shp.c
 */

#ifdef __GNUC__
#   pragma GCC diagnostic push
#   pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#   if !defined(__llvm__) && !defined(__clang__)
#       pragma GCC diagnostic ignored "-Wpedantic"
#   else
#       pragma GCC diagnostic ignored "-Wc99-extensions"
#   endif
#endif
#define GDK_DISABLE_DEPRECATION_WARNINGS
#define GLIB_DISABLE_DEPRECATION_WARNINGS
#include <glib/gstdio.h>
#include <gtk/gtk.h>
#include <libgimp/gimp.h>
#include <libgimp/gimpui.h>
#ifdef __GNUC__
#   pragma GCC diagnostic pop
#endif

#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* ================================================================
 * Constants
 * ================================================================ */

#define LOAD_PROC      "file-u8shp-load"
#define EXPORT_PROC    "file-u8shp-export"
#define PLUG_IN_BINARY "file-u8shp"
#define PLUG_IN_ROLE   "gimp-file-u8shp"

#define U8_TRANSPARENT 0xFF   /* palette index used for transparency  */

/* ================================================================
 * Little-endian helpers
 * ================================================================ */

static inline guint16 read_u16(const guchar *p) {
    return (guint16)(p[0] | (p[1] << 8));
}
static inline gint16 read_s16(const guchar *p) {
    return (gint16)read_u16(p);
}
static inline guint32 read_u24(const guchar *p) {
    return (guint32)(p[0] | (p[1] << 8) | (p[2] << 16));
}
static inline void write_u16(guchar *p, guint16 v) {
    p[0] = v & 0xFF;  p[1] = (v >> 8) & 0xFF;
}
static inline void write_s16(guchar *p, gint16 v) {
    write_u16(p, (guint16)v);
}
static inline void write_u24(guchar *p, guint32 v) {
    p[0] = v & 0xFF;  p[1] = (v >> 8) & 0xFF;  p[2] = (v >> 16) & 0xFF;
}

/* ================================================================
 * Default Ultima 8 palette  (256 × RGB, 8-bit, from U8PAL.PAL)
 * Index 0 is black; index 255 is used as the transparent key.
 * ================================================================ */

static guchar u8_cmap[768] = {
    0x00, 0x00, 0x00, 0xFA, 0xFA, 0xFF, 0xEA, 0xEA, 0xFF, 0xDE, 0xDE, 0xFF,
    0xD2, 0xD2, 0xFF, 0xC2, 0xC2, 0xFF, 0xB6, 0xB6, 0xFF, 0xAA, 0xAA, 0xFF,
    0x4C, 0xFF, 0x48, 0x30, 0x30, 0x30, 0xFF, 0xFF, 0x00, 0xFF, 0xFF, 0xFF,
    0xFF, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x69, 0xFF, 0xFF, 0xFF,
    0xEE, 0xEE, 0xEE, 0xDE, 0xDE, 0xDE, 0xCE, 0xCE, 0xCE, 0xBE, 0xBE, 0xBE,
    0xAE, 0xAE, 0xAE, 0x9D, 0x9D, 0x9D, 0x8D, 0x8D, 0x8D, 0x81, 0x81, 0x81,
    0x71, 0x71, 0x71, 0x61, 0x61, 0x61, 0x50, 0x50, 0x50, 0x40, 0x40, 0x40,
    0x30, 0x30, 0x30, 0x20, 0x20, 0x20, 0x10, 0x10, 0x10, 0x04, 0x04, 0x04,
    0xFF, 0xEE, 0xEE, 0xF6, 0xC2, 0xC2, 0xEE, 0x99, 0x99, 0xE6, 0x75, 0x75,
    0xDE, 0x50, 0x50, 0xD6, 0x30, 0x30, 0xD2, 0x10, 0x10, 0xBE, 0x0C, 0x0C,
    0xAA, 0x08, 0x08, 0x99, 0x04, 0x04, 0x85, 0x04, 0x04, 0x71, 0x00, 0x00,
    0x61, 0x00, 0x00, 0x4C, 0x00, 0x00, 0x38, 0x00, 0x00, 0x28, 0x00, 0x00,
    0xFF, 0xFF, 0xFA, 0xFF, 0xFF, 0xA5, 0xFF, 0xFF, 0x50, 0xFF, 0xFF, 0x00,
    0xEA, 0xDE, 0x0C, 0xD6, 0xC2, 0x1C, 0xC2, 0xAA, 0x28, 0xAE, 0x95, 0x34,
    0xFF, 0xCA, 0x99, 0xFF, 0xAA, 0x65, 0xFF, 0x85, 0x30, 0xFF, 0x5D, 0x00,
    0xDE, 0x59, 0x0C, 0xBE, 0x55, 0x1C, 0x9D, 0x4C, 0x24, 0x81, 0x44, 0x28,
    0xC6, 0xFF, 0xCE, 0xAA, 0xEE, 0xB6, 0x95, 0xDE, 0x9D, 0x7D, 0xCE, 0x89,
    0x69, 0xBE, 0x71, 0x59, 0xAE, 0x61, 0x48, 0x9D, 0x4C, 0x38, 0x8D, 0x40,
    0x28, 0x7D, 0x30, 0x20, 0x6D, 0x24, 0x14, 0x5D, 0x18, 0x0C, 0x4C, 0x10,
    0x04, 0x3C, 0x08, 0x00, 0x2C, 0x04, 0x00, 0x20, 0x00, 0x00, 0x10, 0x00,
    0xD2, 0xFF, 0xFF, 0xB6, 0xEE, 0xEA, 0x9D, 0xDE, 0xDA, 0x89, 0xD2, 0xCA,
    0x71, 0xC2, 0xBA, 0x61, 0xB2, 0xA5, 0x4C, 0xA5, 0x95, 0x40, 0x95, 0x81,
    0x30, 0x85, 0x71, 0x24, 0x79, 0x61, 0x18, 0x69, 0x50, 0x10, 0x59, 0x40,
    0x08, 0x4C, 0x34, 0x04, 0x3C, 0x24, 0x00, 0x2C, 0x18, 0x00, 0x20, 0x10,
    0xFF, 0xFF, 0xAA, 0xEE, 0xEE, 0x95, 0xDE, 0xDE, 0x81, 0xCE, 0xD2, 0x6D,
    0xBE, 0xC2, 0x5D, 0xAE, 0xB6, 0x4C, 0x9D, 0xA5, 0x40, 0x8D, 0x95, 0x34,
    0x7D, 0x89, 0x28, 0x6D, 0x79, 0x1C, 0x61, 0x6D, 0x14, 0x50, 0x5D, 0x0C,
    0x40, 0x4C, 0x04, 0x34, 0x40, 0x04, 0x28, 0x30, 0x00, 0x1C, 0x24, 0x00,
    0xD6, 0xFF, 0xD6, 0x9D, 0xFF, 0x9D, 0x69, 0xFF, 0x69, 0x30, 0xFF, 0x30,
    0x00, 0xFF, 0x00, 0x18, 0xD2, 0x1C, 0x2C, 0xA5, 0x30, 0x34, 0x7D, 0x38,
    0xFF, 0xDA, 0xFF, 0xE2, 0xA5, 0xE2, 0xC6, 0x79, 0xC6, 0xAA, 0x50, 0xAA,
    0x91, 0x30, 0x91, 0x75, 0x18, 0x75, 0x59, 0x08, 0x59, 0x40, 0x00, 0x40,
    0xC2, 0xFF, 0xFF, 0xA5, 0xFF, 0xFF, 0x6D, 0xFF, 0xFF, 0x00, 0xFF, 0xFF,
    0x04, 0xDE, 0xDE, 0x10, 0xC2, 0xC2, 0x14, 0xA1, 0xA1, 0x18, 0x85, 0x85,
    0x89, 0x9D, 0xFF, 0x65, 0x79, 0xFF, 0x40, 0x50, 0xFF, 0x1C, 0x28, 0xFF,
    0x00, 0x00, 0xFF, 0x0C, 0x0C, 0xCE, 0x14, 0x14, 0x9D, 0x18, 0x18, 0x6D,
    0xEA, 0xEA, 0xFF, 0xCA, 0xCA, 0xEE, 0xB2, 0xB2, 0xDE, 0x99, 0x99, 0xCE,
    0x81, 0x81, 0xC2, 0x69, 0x69, 0xB2, 0x59, 0x59, 0xA1, 0x44, 0x44, 0x91,
    0x34, 0x34, 0x85, 0x28, 0x28, 0x75, 0x1C, 0x1C, 0x65, 0x10, 0x10, 0x59,
    0x08, 0x08, 0x48, 0x04, 0x04, 0x38, 0x00, 0x00, 0x28, 0x00, 0x00, 0x1C,
    0xFA, 0xDA, 0xAA, 0xEA, 0xC6, 0x91, 0xDA, 0xB6, 0x81, 0xCA, 0xA5, 0x6D,
    0xBE, 0x95, 0x5D, 0xAE, 0x85, 0x4C, 0x9D, 0x75, 0x3C, 0x8D, 0x69, 0x30,
    0x81, 0x5D, 0x24, 0x71, 0x4C, 0x1C, 0x61, 0x40, 0x10, 0x55, 0x34, 0x0C,
    0x44, 0x28, 0x04, 0x34, 0x20, 0x00, 0x24, 0x14, 0x00, 0x18, 0x0C, 0x00,
    0xFF, 0xE6, 0xBA, 0xEE, 0xD2, 0xA1, 0xE2, 0xBE, 0x8D, 0xD6, 0xAA, 0x79,
    0xCA, 0x95, 0x69, 0xBA, 0x85, 0x59, 0xAE, 0x71, 0x48, 0xA1, 0x5D, 0x3C,
    0x91, 0x4C, 0x30, 0x85, 0x3C, 0x24, 0x79, 0x2C, 0x18, 0x6D, 0x20, 0x10,
    0x5D, 0x14, 0x08, 0x50, 0x08, 0x04, 0x44, 0x04, 0x00, 0x38, 0x00, 0x00,
    0xDA, 0xDA, 0xC6, 0xC2, 0xC2, 0xAA, 0xAA, 0xAA, 0x91, 0x91, 0x91, 0x79,
    0x7D, 0x7D, 0x65, 0x65, 0x65, 0x4C, 0x4C, 0x4C, 0x38, 0x38, 0x38, 0x28,
    0xF6, 0xDE, 0xCE, 0xEA, 0xCE, 0xBE, 0xE2, 0xC2, 0xAA, 0xD6, 0xB2, 0x99,
    0xCE, 0xA5, 0x8D, 0xC2, 0x99, 0x7D, 0xBA, 0x8D, 0x71, 0xAE, 0x81, 0x65,
    0xA5, 0x75, 0x59, 0x99, 0x6D, 0x4C, 0x91, 0x61, 0x40, 0x85, 0x59, 0x38,
    0x7D, 0x4C, 0x30, 0x71, 0x44, 0x24, 0x69, 0x3C, 0x20, 0x5D, 0x34, 0x18,
    0x55, 0x2C, 0x10, 0x48, 0x24, 0x0C, 0x40, 0x20, 0x08, 0x38, 0x18, 0x04,
    0x2C, 0x10, 0x00, 0x24, 0x0C, 0x00, 0x18, 0x08, 0x00, 0x10, 0x04, 0x00,
    0xFF, 0xFF, 0xEA, 0xFF, 0xFA, 0xC6, 0xFF, 0xF2, 0xA5, 0xFF, 0xEA, 0x81,
    0xFF, 0xDA, 0x61, 0xFF, 0xCA, 0x3C, 0xFF, 0xB6, 0x1C, 0xFF, 0x9D, 0x00,
    0xE2, 0x79, 0x00, 0xC6, 0x59, 0x00, 0xAE, 0x40, 0x00, 0x91, 0x28, 0x00,
    0x79, 0x18, 0x00, 0x5D, 0x08, 0x00, 0x40, 0x04, 0x00, 0x28, 0x00, 0x00,
    0xDE, 0xDE, 0xEA, 0xCA, 0xCA, 0xDA, 0xB6, 0xB6, 0xCA, 0xA5, 0xA5, 0xBA,
    0x95, 0x95, 0xAA, 0x85, 0x85, 0x9D, 0x75, 0x75, 0x8D, 0x65, 0x65, 0x7D,
    0x55, 0x55, 0x6D, 0x48, 0x48, 0x61, 0x3C, 0x3C, 0x50, 0x2C, 0x2C, 0x40,
    0x20, 0x20, 0x30, 0x14, 0x14, 0x20, 0x0C, 0x0C, 0x18, 0x18, 0x7D, 0x7D
};

/* ================================================================
 * Palette loading  (U8 .pal and GIMP .gpl files)
 * ================================================================ */

/* Load GIMP text palette (.gpl) into u8_cmap[]. Returns colour count. */
static gint load_gpl_palette(const gchar *path) {
    FILE *fp = g_fopen(path, "r");
    if (!fp) return 0;

    char line[512];
    /* Must start with "GIMP Palette" */
    if (!fgets(line, sizeof(line), fp) || !strstr(line, "GIMP Palette")) {
        fclose(fp);
        return 0;
    }

    unsigned idx = 0;
    while (fgets(line, sizeof(line), fp) && idx < 256) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') continue;
        if (strncmp(line, "Name:", 5) == 0 || strncmp(line, "Columns:", 8) == 0) continue;
        int r, g, b;
        if (sscanf(line, "%d %d %d", &r, &g, &b) == 3) {
            u8_cmap[idx * 3 + 0] = (guchar)r;
            u8_cmap[idx * 3 + 1] = (guchar)g;
            u8_cmap[idx * 3 + 2] = (guchar)b;
            idx++;
        }
    }
    fclose(fp);
    return (gint)idx;
}

/* Load Ultima 8 binary palette (.pal): 4-byte header + 768 bytes of
 * 6-bit VGA values (0-63).  Scaled to 8-bit via (v * 255) / 63.     */
static gint load_u8pal(const gchar *path) {
    FILE *fp = g_fopen(path, "rb");
    if (!fp) return 0;
    fseek(fp, 0, SEEK_END);
    long sz = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    if (sz < 772) { fclose(fp); return 0; }

    guchar hdr[4];
    if (fread(hdr, 1, 4, fp) != 4) { fclose(fp); return 0; }

    guchar raw[768];
    if (fread(raw, 1, 768, fp) != 768) { fclose(fp); return 0; }
    fclose(fp);

    for (unsigned i = 0; i < 256; i++) {
        u8_cmap[i * 3 + 0] = (guchar)((raw[i * 3 + 0] * 255) / 63);
        u8_cmap[i * 3 + 1] = (guchar)((raw[i * 3 + 1] * 255) / 63);
        u8_cmap[i * 3 + 2] = (guchar)((raw[i * 3 + 2] * 255) / 63);
    }
    return 256;
}

/* Try to load palette from a file (auto-detect format). */
static gint load_palette_file(GFile *file) {
    if (!file) return 0;
    const gchar *path = gimp_file_get_utf8_name(file);
    if (!path) return 0;

    /* Try .gpl by extension first */
    if (g_str_has_suffix(path, ".gpl"))
        return load_gpl_palette(path);

    /* Sniff content for "GIMP Palette" header */
    FILE *fp = g_fopen(path, "r");
    if (fp) {
        char buf[64];
        if (fgets(buf, sizeof(buf), fp) && strstr(buf, "GIMP Palette")) {
            fclose(fp);
            return load_gpl_palette(path);
        }
        fclose(fp);
    }

    /* Default: try as U8 binary .pal */
    return load_u8pal(path);
}

/* ================================================================
 * U8 Shape binary format – in-memory frame representation
 * ================================================================ */

typedef struct {
    gint16  width;
    gint16  height;
    gint16  xoff;       /* pixels left of hot-spot   */
    gint16  yoff;       /* pixels above hot-spot      */
    guint16 compressed; /* 0 = raw literals, 1 = RLE  */
    guchar *pixels;     /* height × width, 0xFF = transparent */
} U8Frame;

/* ================================================================
 * RLE decompression  (load path)
 *
 * Each scan-line is a sequence of (skip, data) pairs:
 *   skip byte  – number of transparent pixels to advance
 *   dlen byte  – if compressed: low bit = type (0=literal, 1=solid),
 *                count = dlen >> 1
 *                if uncompressed: count = dlen, always literal
 * Decoder exits when xpos reaches width.
 * ================================================================ */

static void decode_frame(const guchar *frame_data, gsize frame_data_len,
                         U8Frame *f)
{
    if (frame_data_len < 18) { f->width = f->height = 0; return; }

    f->compressed = read_u16(frame_data + 8);
    f->width      = read_s16(frame_data + 10);
    f->height     = read_s16(frame_data + 12);
    f->xoff       = read_s16(frame_data + 14);
    f->yoff       = read_s16(frame_data + 16);

    if (f->width <= 0 || f->height <= 0) {
        f->width = f->height = 0;
        f->pixels = NULL;
        return;
    }

    gsize line_table_start = 18;
    gsize line_table_end   = line_table_start + (gsize)f->height * 2;
    if (line_table_end > frame_data_len) {
        f->width = f->height = 0;
        f->pixels = NULL;
        return;
    }

    /* Decode line offsets (self-relative format) */
    gint *line_off = g_new(gint, f->height);
    for (gint row = 0; row < f->height; row++) {
        guint16 raw = read_u16(frame_data + line_table_start + row * 2);
        line_off[row] = (gint)raw - (f->height - row) * 2;
    }

    const guchar *rle = frame_data + line_table_end;
    gsize rle_len = frame_data_len - line_table_end;

    gsize npix = (gsize)f->width * (gsize)f->height;
    f->pixels = g_malloc(npix);
    memset(f->pixels, U8_TRANSPARENT, npix);

    for (gint row = 0; row < f->height; row++) {
        if (line_off[row] < 0 || (gsize)line_off[row] >= rle_len)
            continue;

        gsize pos = (gsize)line_off[row];
        gint  xpos = 0;

        while (xpos < f->width && pos < rle_len) {
            /* skip */
            xpos += rle[pos++];
            if (xpos >= f->width) break;
            if (pos >= rle_len)   break;

            /* dlen */
            guint8 dlen_raw = rle[pos++];
            int    run_type = 0;
            int    count    = dlen_raw;

            if (f->compressed) {
                run_type = dlen_raw & 1;
                count    = dlen_raw >> 1;
            }
            if (count <= 0) continue;

            gint end_x = xpos + count;
            if (end_x > f->width) end_x = f->width;
            gint actual = end_x - xpos;

            if (run_type == 0) {
                /* literal */
                if (pos + actual <= rle_len)
                    memcpy(f->pixels + row * f->width + xpos, rle + pos, actual);
                pos += count;
            } else {
                /* solid */
                if (pos < rle_len)
                    memset(f->pixels + row * f->width + xpos, rle[pos], actual);
                pos += 1;
            }
            xpos += count;
        }
    }
    g_free(line_off);
}

/* ================================================================
 * RLE compression  (export path)
 *
 * Produces compressed format (flag=1) RLE data for a single scan line.
 * Appends bytes to `out`.
 * ================================================================ */

/* Append skip bytes, handling skip > 255 with (255, dlen=0) pairs. */
static void emit_skip(GByteArray *out, int skip) {
    while (skip > 255) {
        guchar pair[2] = { 255, 0 };
        g_byte_array_append(out, pair, 2);
        skip -= 255;
    }
    guchar b = (guchar)skip;
    g_byte_array_append(out, &b, 1);
}

static void encode_line(const guchar *pixels, gint width, GByteArray *out)
{
    int x = 0;
    while (x < width) {
        /* Count transparent skip */
        int skip_start = x;
        while (x < width && pixels[x] == U8_TRANSPARENT) x++;
        int skip = x - skip_start;

        if (x >= width) {
            /* Trailing transparent – emit skip so decoder's xpos reaches width */
            if (skip > 0) emit_skip(out, skip);
            break;
        }

        /* Count full non-transparent run (may exceed 127, will be chunked) */
        int run_start = x;
        while (x < width && pixels[x] != U8_TRANSPARENT) x++;
        int total_run = x - run_start;

        /* Emit in chunks of at most 127 */
        int emitted = 0;
        while (emitted < total_run) {
            int chunk = total_run - emitted;
            if (chunk > 127) chunk = 127;

            /* Emit skip (real skip for first chunk, 0 for continuations) */
            if (emitted == 0)
                emit_skip(out, skip);
            else {
                guchar zero = 0;
                g_byte_array_append(out, &zero, 1);
            }

            /* Check if chunk is all the same value → solid run */
            int all_same = 1;
            const guchar *rp = pixels + run_start + emitted;
            for (int i = 1; i < chunk; i++) {
                if (rp[i] != rp[0]) { all_same = 0; break; }
            }

            if (all_same) {
                guchar dlen = (guchar)((chunk << 1) | 1);
                g_byte_array_append(out, &dlen, 1);
                g_byte_array_append(out, &rp[0], 1);
            } else {
                guchar dlen = (guchar)(chunk << 1);
                g_byte_array_append(out, &dlen, 1);
                g_byte_array_append(out, rp, chunk);
            }
            emitted += chunk;
        }
    }
}

/* ================================================================
 * Shape file reader  (load path)
 *
 * Binary layout (U8ShapeFormat from Pentagram ConvertShapeU8.cpp):
 *   Header  : 4 B unknown  +  2 B frame_count            = 6 bytes
 *   Frame table : frame_count × 6 B  (3B offset, 1B unk, 2B size)
 *   Frame data  : per frame, starting at the stored offset:
 *     8 B unknown, 2 B compression, 2 B width, 2 B height,
 *     2 B xoff, 2 B yoff                                  = 18 bytes
 *     height × 2 B  line-offset table (self-relative)
 *     RLE data
 * ================================================================ */

static U8Frame *read_shape(const guchar *data, gsize len, int *out_nframes)
{
    *out_nframes = 0;
    if (len < 6) return NULL;

    guint16 frame_count = read_u16(data + 4);
    if (frame_count == 0 || frame_count > 20000) return NULL;

    gsize table_end = 6 + (gsize)frame_count * 6;
    if (table_end > len) return NULL;

    U8Frame *frames = g_new0(U8Frame, frame_count);

    for (guint16 i = 0; i < frame_count; i++) {
        gsize te = 6 + (gsize)i * 6;
        guint32 off  = read_u24(data + te);
        /* guint8  unk  = data[te + 3]; */
        /* guint16 size = read_u16(data + te + 4); */

        if (off + 18 > len) {
            frames[i].width = frames[i].height = 0;
            frames[i].pixels = NULL;
            continue;
        }

        gsize avail = len - off;
        decode_frame(data + off, avail, &frames[i]);
    }

    *out_nframes = (int)frame_count;
    return frames;
}

static void free_frames(U8Frame *frames, int n) {
    if (!frames) return;
    for (int i = 0; i < n; i++)
        g_free(frames[i].pixels);
    g_free(frames);
}

/* ================================================================
 * Shape file writer  (export path)
 *
 * Produces a complete U8-format shape binary blob.
 * ================================================================ */

static guchar *write_shape(U8Frame *frames, int nframes,
                           const guchar *orig_header4,
                           gsize *out_len)
{
    GByteArray *buf = g_byte_array_new();

    /* ------ header (6 bytes) ------ */
    if (orig_header4)
        g_byte_array_append(buf, orig_header4, 4);
    else {
        guchar z[4] = {0, 0, 0, 0};
        g_byte_array_append(buf, z, 4);
    }
    guchar fc[2];
    write_u16(fc, (guint16)nframes);
    g_byte_array_append(buf, fc, 2);

    /* ------ placeholder frame table (nframes × 6 bytes) ------ */
    gsize table_base = buf->len;
    for (int i = 0; i < nframes; i++) {
        guchar entry[6] = {0, 0, 0, 0, 0, 0};
        g_byte_array_append(buf, entry, 6);
    }

    /* ------ frame data ------ */
    for (int f = 0; f < nframes; f++) {
        U8Frame *fr = &frames[f];
        guint32 frame_offset = (guint32)buf->len;

        /* Frame header (18 bytes):
         *   8 unknown (we store shape=0, frame=f, pad=0)
         *   2 compression  2 width  2 height  2 xoff  2 yoff  */
        guchar fh[18];
        memset(fh, 0, 18);
        write_u16(fh + 2, (guint16)f);         /* frame number */
        write_u16(fh + 8, 1);                  /* always compressed */
        write_s16(fh + 10, fr->width);
        write_s16(fh + 12, fr->height);
        write_s16(fh + 14, fr->xoff);
        write_s16(fh + 16, fr->yoff);
        g_byte_array_append(buf, fh, 18);

        /* ------ RLE-encode all lines first to know offsets ------ */
        GByteArray **line_bufs = g_new(GByteArray*, fr->height);
        for (gint row = 0; row < fr->height; row++) {
            line_bufs[row] = g_byte_array_new();
            encode_line(fr->pixels + row * fr->width, fr->width, line_bufs[row]);
        }

        /* Compute cumulative RLE offsets (within the RLE block) */
        gsize *rle_pos = g_new(gsize, fr->height);
        gsize cum = 0;
        for (gint row = 0; row < fr->height; row++) {
            rle_pos[row] = cum;
            cum += line_bufs[row]->len;
        }

        /* Write line offset table (self-relative encoding):
         * stored_value = rle_offset + (height - row) * 2                */
        for (gint row = 0; row < fr->height; row++) {
            guint16 stored = (guint16)(rle_pos[row] + (fr->height - row) * 2);
            guchar lo[2];
            write_u16(lo, stored);
            g_byte_array_append(buf, lo, 2);
        }

        /* Write RLE data */
        for (gint row = 0; row < fr->height; row++) {
            g_byte_array_append(buf, line_bufs[row]->data, line_bufs[row]->len);
            g_byte_array_free(line_bufs[row], TRUE);
        }
        g_free(line_bufs);
        g_free(rle_pos);

        /* ------ patch frame table entry ------ */
        guint32 frame_data_size = (guint32)buf->len - frame_offset;
        gsize entry_pos = table_base + (gsize)f * 6;
        write_u24(buf->data + entry_pos, frame_offset);
        buf->data[entry_pos + 3] = 0;  /* unknown */
        write_u16(buf->data + entry_pos + 4, (guint16)frame_data_size);
    }

    *out_len = buf->len;
    return g_byte_array_free(buf, FALSE);   /* caller owns the data */
}

/* ================================================================
 * GIMP load function
 * ================================================================ */

static GimpImage *load_image(GFile *file, GFile *palette_file,
                             GimpRunMode run_mode, GError **error)
{
    (void)run_mode;

    /* Read entire file */
    gchar  *contents = NULL;
    gsize   length   = 0;
    if (!g_file_load_contents(file, NULL, &contents, &length, NULL, error))
        return NULL;

    /* Load optional palette */
    if (palette_file)
        load_palette_file(palette_file);

    /* Parse shape */
    int      nframes = 0;
    U8Frame *frames  = read_shape((const guchar *)contents, length, &nframes);

    /* Preserve original 4-byte header for perfect round-trip */
    guchar header4[4] = {0};
    if (length >= 4)
        memcpy(header4, contents, 4);

    g_free(contents);

    if (!frames || nframes == 0) {
        g_set_error(error, G_FILE_ERROR, G_FILE_ERROR_FAILED,
                    "U8SHP: not a valid Ultima 8 shape (0 frames)");
        return NULL;
    }

    /* Compute canvas bounds (max extents across all frames) */
    gint max_xoff = 0, max_xright = 0, max_yoff = 0, max_ybelow = 0;
    for (int i = 0; i < nframes; i++) {
        if (frames[i].width <= 0 || frames[i].height <= 0) continue;
        if (frames[i].xoff   > max_xoff)   max_xoff   = frames[i].xoff;
        if (frames[i].yoff   > max_yoff)   max_yoff   = frames[i].yoff;
        gint xr = frames[i].width  - frames[i].xoff - 1;
        gint yb = frames[i].height - frames[i].yoff - 1;
        if (xr > max_xright) max_xright = xr;
        if (yb > max_ybelow) max_ybelow = yb;
    }

    gint canvas_w = max_xoff + max_xright + 1;
    gint canvas_h = max_yoff + max_ybelow + 1;
    if (canvas_w < 1) canvas_w = 1;
    if (canvas_h < 1) canvas_h = 1;

    /* Create GIMP image (indexed + alpha) */
    GimpImage *image = gimp_image_new(canvas_w, canvas_h, GIMP_INDEXED);
    gimp_palette_set_colormap(gimp_image_get_palette(image),
                              babl_format("R'G'B' u8"),
                              u8_cmap, 256 * 3);

    /* Create one layer per frame */
    for (int f = 0; f < nframes; f++) {
        U8Frame *fr = &frames[f];
        gint fw = (fr->width  > 0) ? fr->width  : 1;
        gint fh = (fr->height > 0) ? fr->height : 1;

        gchar name[64];
        g_snprintf(name, sizeof(name), "Frame %d", f);

        GimpLayer *layer = gimp_layer_new(
            image, name, fw, fh,
            GIMP_INDEXEDA_IMAGE, 100,
            gimp_image_get_default_new_layer_mode(image));
        gimp_image_insert_layer(image, layer, NULL, 0);

        /* Position layer relative to hot-spot */
        gimp_item_transform_translate(GIMP_ITEM(layer),
                                      max_xoff - fr->xoff,
                                      max_yoff - fr->yoff);

        /* Write pixels as (index, alpha) pairs */
        GeglBuffer *gegl = gimp_drawable_get_buffer(GIMP_DRAWABLE(layer));
        GeglRectangle rect = { 0, 0,
                               gegl_buffer_get_width(gegl),
                               gegl_buffer_get_height(gegl) };

        gsize npix = (gsize)fw * (gsize)fh;
        guchar *px = g_malloc(npix * 2);
        if (fr->pixels) {
            for (gsize p = 0; p < npix; p++) {
                guchar idx = fr->pixels[p];
                px[p * 2 + 0] = idx;
                px[p * 2 + 1] = (idx == U8_TRANSPARENT) ? 0 : 255;
            }
        } else {
            memset(px, 0, npix * 2);   /* fully transparent placeholder */
        }

        gegl_buffer_set(gegl, &rect, 0, NULL, px, GEGL_AUTO_ROWSTRIDE);
        g_object_unref(gegl);
        g_free(px);
    }

    /* Add guides to mark the hot-spot origin */
    gimp_image_add_hguide(image, max_yoff);
    gimp_image_add_vguide(image, max_xoff);

    free_frames(frames, nframes);

    /* Attach header as parasite for round-trip fidelity */
    GimpParasite *parasite = gimp_parasite_new("u8shp-header4",
                                               GIMP_PARASITE_PERSISTENT,
                                               4, header4);
    gimp_image_attach_parasite(image, parasite);
    gimp_parasite_free(parasite);

    return image;
}

/* ================================================================
 * Nearest-neighbour quantiser — map any (R,G,B) to the closest
 * U8 palette index (0-254).  Index 255 is transparent, never chosen.
 * ================================================================ */

static guchar nearest_u8_index(guchar r, guchar g, guchar b)
{
    guint32 best_dist = G_MAXUINT32;
    guchar  best_idx  = 0;
    for (int i = 0; i < 255; i++) {       /* skip 255 = transparent */
        gint dr = (gint)r - u8_cmap[i * 3 + 0];
        gint dg = (gint)g - u8_cmap[i * 3 + 1];
        gint db = (gint)b - u8_cmap[i * 3 + 2];
        guint32 d = (guint32)(dr*dr + dg*dg + db*db);
        if (d == 0) return (guchar)i;     /* exact match → done */
        if (d < best_dist) { best_dist = d; best_idx = (guchar)i; }
    }
    return best_idx;
}

/* ================================================================
 * GIMP export function
 * ================================================================ */

static gboolean export_image(GFile *file, GimpImage *image,
                             GimpRunMode run_mode, GError **error)
{
    /* Progress bar */
    if (run_mode != GIMP_RUN_NONINTERACTIVE) {
        gchar msg[256];
        g_snprintf(msg, sizeof(msg), "Saving %s:",
                   gimp_file_get_utf8_name(file));
        gimp_progress_init(msg);
    }

    /* Find hot-spot from guides */
    gint hotx = 0, hoty = 0;
    gint found_h = 0, found_v = 0;
    for (gint32 gid = gimp_image_find_next_guide(image, 0);
         gid > 0;
         gid = gimp_image_find_next_guide(image, gid))
    {
        switch (gimp_image_get_guide_orientation(image, gid)) {
        case GIMP_ORIENTATION_HORIZONTAL:
            if (!found_h) { hoty = gimp_image_get_guide_position(image, gid); found_h = 1; }
            break;
        case GIMP_ORIENTATION_VERTICAL:
            if (!found_v) { hotx = gimp_image_get_guide_position(image, gid); found_v = 1; }
            break;
        default: break;
        }
    }

    /* Collect layers (reversed = original frame order) */
    GList *layers = g_list_reverse(gimp_image_list_layers(image));
    gint   nlayers = g_list_length(layers);

    if (nlayers == 0) {
        g_set_error(error, G_FILE_ERROR, G_FILE_ERROR_FAILED,
                    "U8SHP: image has no layers");
        g_list_free(layers);
        return FALSE;
    }

    /* Always read every layer as R'G'B'A u8 and re-quantise to the
     * U8 palette.  This is correct for both Indexed and RGB images
     * and avoids subtle format-detection edge cases.                    */
    const Babl *rgba_fmt = babl_format("R'G'B'A u8");
    U8Frame *frames = g_new0(U8Frame, nlayers);
    int fi = 0;

    for (GList *cur = g_list_first(layers); cur; cur = g_list_next(cur), fi++) {
        GimpDrawable *drawable = GIMP_DRAWABLE(cur->data);
        GeglBuffer   *gegl    = gimp_drawable_get_buffer(drawable);
        gint offX, offY;
        gimp_drawable_get_offsets(drawable, &offX, &offY);

        gint w = gegl_buffer_get_width(gegl);
        gint h = gegl_buffer_get_height(gegl);

        frames[fi].width      = (gint16)w;
        frames[fi].height     = (gint16)h;
        frames[fi].xoff       = (gint16)(hotx - offX);
        frames[fi].yoff       = (gint16)(hoty - offY);
        frames[fi].compressed = 1;

        gsize npix = (gsize)w * (gsize)h;
        guchar *rgba = g_malloc(npix * 4);
        GeglRectangle rect = { 0, 0, w, h };
        gegl_buffer_get(gegl, &rect, 1.0, rgba_fmt, rgba,
                        GEGL_AUTO_ROWSTRIDE, GEGL_ABYSS_NONE);
        g_object_unref(gegl);

        frames[fi].pixels = g_malloc(npix);
        for (gsize p = 0; p < npix; p++) {
            guchar a = rgba[p * 4 + 3];
            if (a < 128) {
                frames[fi].pixels[p] = U8_TRANSPARENT;
            } else {
                frames[fi].pixels[p] = nearest_u8_index(
                    rgba[p * 4], rgba[p * 4 + 1], rgba[p * 4 + 2]);
            }
        }
        g_free(rgba);
    }
    g_list_free(layers);

    /* Retrieve original header if present (for byte-perfect round-trip) */
    const guchar *orig_header4 = NULL;
    GimpParasite *p = gimp_image_get_parasite(image, "u8shp-header4");
    if (p)
        orig_header4 = gimp_parasite_get_data(p, NULL);

    /* Encode to binary */
    gsize  blob_len = 0;
    guchar *blob = write_shape(frames, nlayers, orig_header4, &blob_len);
    free_frames(frames, nlayers);
    if (p) gimp_parasite_free(p);

    if (!blob) {
        g_set_error(error, G_FILE_ERROR, G_FILE_ERROR_FAILED,
                    "U8SHP: failed to encode shape");
        return FALSE;
    }

    /* Write to disk — pure GIO, no CRT mismatch on any platform */
    if (!g_file_replace_contents(file,
                                 (const char *)blob, blob_len,
                                 NULL,                /* etag          */
                                 FALSE,               /* make_backup   */
                                 G_FILE_CREATE_NONE,
                                 NULL,                /* new_etag      */
                                 NULL,                /* cancellable   */
                                 error))
    {
        g_free(blob);
        return FALSE;
    }
    g_free(blob);

    return TRUE;
}

/* ================================================================
 * GObject boilerplate  (GIMP 3 plugin registration)
 * ================================================================ */

typedef struct _U8Shp      U8Shp;
typedef struct _U8ShpClass U8ShpClass;

struct _U8Shp      { GimpPlugIn      parent_instance; };
struct _U8ShpClass { GimpPlugInClass parent_class;    };

#define U8SHP_TYPE (u8shp_get_type())
#define U8SHP(obj) (G_TYPE_CHECK_INSTANCE_CAST((obj), U8SHP_TYPE, U8Shp))

GType u8shp_get_type(void) G_GNUC_CONST;

static GList         *u8shp_query_procedures(GimpPlugIn *plug_in);
static GimpProcedure *u8shp_create_procedure(GimpPlugIn *plug_in,
                                             const gchar *name);

static GimpValueArray *u8shp_load(
    GimpProcedure        *procedure,
    GimpRunMode           run_mode,
    GFile                *file,
    GimpMetadata         *metadata,
    GimpMetadataLoadFlags *flags,
    GimpProcedureConfig  *config,
    gpointer              run_data);

static GimpValueArray *u8shp_export(
    GimpProcedure        *procedure,
    GimpRunMode           run_mode,
    GimpImage            *image,
    GFile                *file,
    GimpExportOptions    *options,
    GimpMetadata         *metadata,
    GimpProcedureConfig  *config,
    gpointer              run_data);

static gboolean u8shp_palette_dialog(const gchar     *title,
                                     GimpProcedure   *procedure,
                                     GimpProcedureConfig *config);

/* ---- GObject type plumbing ---- */

#ifdef __GNUC__
#   pragma GCC diagnostic push
#   if defined(__llvm__) || defined(__clang__)
#       pragma GCC diagnostic ignored "-Wunused-parameter"
#       if __clang_major__ >= 16
#           pragma GCC diagnostic ignored "-Wcast-function-type-strict"
#       endif
#   endif
#endif
G_DEFINE_TYPE(U8Shp, u8shp, GIMP_TYPE_PLUG_IN)
GIMP_MAIN(U8SHP_TYPE)
#ifdef __GNUC__
#   pragma GCC diagnostic pop
#endif

static void u8shp_class_init(U8ShpClass *klass) {
    GimpPlugInClass *c = GIMP_PLUG_IN_CLASS(klass);
    c->query_procedures = u8shp_query_procedures;
    c->create_procedure = u8shp_create_procedure;
    c->set_i18n         = NULL;
}

static void u8shp_init(U8Shp *self) { (void)self; }

/* ---- Procedure registration ---- */

static GList *u8shp_query_procedures(GimpPlugIn *plug_in) {
    (void)plug_in;
    GList *list = NULL;
    list = g_list_append(list, g_strdup(LOAD_PROC));
    list = g_list_append(list, g_strdup(EXPORT_PROC));
    return list;
}

static GimpProcedure *u8shp_create_procedure(GimpPlugIn  *plug_in,
                                             const gchar *name)
{
    GimpProcedure *procedure = NULL;

    if (!strcmp(name, LOAD_PROC)) {
        procedure = gimp_load_procedure_new(
            plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN,
            u8shp_load, NULL, NULL);

        gimp_procedure_set_menu_label(procedure, "Ultima 8 Shape");
        gimp_procedure_set_documentation(
            procedure,
            "Loads files in Ultima 8 Shape format",
            "Loads individual Ultima 8 Shape files (.shp) "
            "extracted from U8SHAPES.FLX, U8GUMPS.FLX, etc.",
            name);
        gimp_procedure_set_attribution(
            procedure,
            "Pentagram GIMP Plugin Project",
            "Pentagram GIMP Plugin Project",
            "2025");
        gimp_file_procedure_set_extensions(
            GIMP_FILE_PROCEDURE(procedure), "shp");
        gimp_procedure_add_file_argument(
            procedure, "palette-file", "_Palette file",
            "U8 PAL or GIMP GPL palette file",
            GIMP_FILE_CHOOSER_ACTION_OPEN, TRUE, NULL,
            G_PARAM_READWRITE);
    }
    else if (!strcmp(name, EXPORT_PROC)) {
        procedure = gimp_export_procedure_new(
            plug_in, name, GIMP_PDB_PROC_TYPE_PLUGIN,
            FALSE, u8shp_export, NULL, NULL);

        gimp_procedure_set_image_types(procedure, "RGB*, INDEXED*");
        gimp_procedure_set_menu_label(procedure, "Ultima 8 Shape");
        gimp_procedure_set_documentation(
            procedure,
            "Exports files in Ultima 8 Shape format",
            "Exports a multi-layer indexed image as an Ultima 8 Shape file.",
            name);
        gimp_procedure_set_attribution(
            procedure,
            "Pentagram GIMP Plugin Project",
            "Pentagram GIMP Plugin Project",
            "2025");
        gimp_file_procedure_set_extensions(
            GIMP_FILE_PROCEDURE(procedure), "shp");
        gimp_export_procedure_set_capabilities(
            GIMP_EXPORT_PROCEDURE(procedure),
            (GimpExportCapabilities)(
                GIMP_EXPORT_CAN_HANDLE_ALPHA
                | GIMP_EXPORT_CAN_HANDLE_LAYERS
                | GIMP_EXPORT_CAN_HANDLE_INDEXED
                | GIMP_EXPORT_CAN_HANDLE_RGB),
            NULL, NULL, NULL);
    }

    return procedure;
}

/* ---- Palette dialog ---- */

static gboolean u8shp_palette_dialog(const gchar         *title,
                                     GimpProcedure       *procedure,
                                     GimpProcedureConfig *config)
{
    GtkWidget *dialog;
    gboolean   run;

    gimp_ui_init(PLUG_IN_BINARY);
    dialog = gimp_procedure_dialog_new(
        procedure, GIMP_PROCEDURE_CONFIG(config), title);
    gimp_procedure_dialog_set_ok_label(
        GIMP_PROCEDURE_DIALOG(dialog), "_Open");
    gimp_procedure_dialog_fill(GIMP_PROCEDURE_DIALOG(dialog), NULL);
    run = gimp_procedure_dialog_run(GIMP_PROCEDURE_DIALOG(dialog));
    gtk_widget_destroy(dialog);
    return run;
}

/* ---- Load entry point ---- */

static GimpValueArray *u8shp_load(
    GimpProcedure         *procedure,
    GimpRunMode            run_mode,
    GFile                 *file,
    GimpMetadata          *metadata,
    GimpMetadataLoadFlags *flags,
    GimpProcedureConfig   *config,
    gpointer               run_data)
{
    (void)metadata; (void)flags; (void)run_data;

    GimpValueArray *ret;
    GimpImage      *image        = NULL;
    GFile          *palette_file = NULL;
    GError         *error        = NULL;

    gegl_init(NULL, NULL);

    g_object_get(config, "palette-file", &palette_file, NULL);

    if (run_mode != GIMP_RUN_NONINTERACTIVE) {
        if (!u8shp_palette_dialog("Load U8 Palette", procedure, config))
            return gimp_procedure_new_return_values(procedure,
                                                    GIMP_PDB_CANCEL, NULL);
        g_clear_object(&palette_file);
        g_object_get(config, "palette-file", &palette_file, NULL);
    }

    image = load_image(file, palette_file, run_mode, &error);
    g_clear_object(&palette_file);

    if (!image)
        return gimp_procedure_new_return_values(procedure,
                                                GIMP_PDB_EXECUTION_ERROR,
                                                error);

    ret = gimp_procedure_new_return_values(procedure, GIMP_PDB_SUCCESS, NULL);
    GIMP_VALUES_SET_IMAGE(ret, 1, image);
    return ret;
}

/* ---- Export entry point ---- */

static GimpValueArray *u8shp_export(
    GimpProcedure        *procedure,
    GimpRunMode           run_mode,
    GimpImage            *image,
    GFile                *file,
    GimpExportOptions    *options,
    GimpMetadata         *metadata,
    GimpProcedureConfig  *config,
    gpointer              run_data)
{
    (void)metadata; (void)config; (void)run_data;

    GimpPDBStatusType status = GIMP_PDB_SUCCESS;
    GimpExportReturn  expret = GIMP_EXPORT_IGNORE;
    GError           *error  = NULL;

    gegl_init(NULL, NULL);

    if (options)
        expret = gimp_export_options_get_image(options, &image);

    if (!export_image(file, image, run_mode, &error))
        status = GIMP_PDB_EXECUTION_ERROR;

    if (expret == GIMP_EXPORT_EXPORT)
        gimp_image_delete(image);

    return gimp_procedure_new_return_values(procedure, status, error);
}
