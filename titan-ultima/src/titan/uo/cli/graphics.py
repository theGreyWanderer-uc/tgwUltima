"""``titan uo art-export`` / ``gump-`` / ``texture-`` / ``light-`` / ``hue-`` / ``font-export`` — image asset commands."""

from __future__ import annotations

__all__ = [
    "art_export_cmd",
    "gump_export_cmd",
    "texture_export_cmd",
    "light_export_cmd",
    "hue_export_cmd",
    "font_export_cmd",
]

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan.uo.animdata import UOAnimData
from titan.uo.art import UOArtDecoder
from titan.uo.artdef import UOArtDef, UOArtDefEntry
from titan.uo.definfo import UODefFile
from titan.uo.font import UOAsciiFonts
from titan.uo.gump import UOGumpDecoder
from titan.uo.hue import UOHuesFile
from titan.uo.indexed import UOIndexedFile, UOIndexEntry
from titan.uo.light import UOLightDecoder
from titan.uo.tiledata import UOTileData
from titan.uo.texture import UOTextureDecoder
from titan.uo.cli import _common


def _load_art(
    client: Path,
    *,
    range_start: Optional[int] = None,
    range_end: Optional[int] = None,
    limit: Optional[int] = None,
    kind: Literal["all", "land", "static"] = "all",
) -> UOIndexedFile:
    if kind == "static" and range_start is None:
        range_start = 0x4000
    elif kind == "land" and range_end is None:
        range_end = 0x4000

    uop = client / "artLegacyMUL.uop"
    if uop.is_file():
        return UOIndexedFile.from_uop(
            uop,
            entry_count=0x14000,
            range_start=range_start,
            range_end=range_end,
            max_entries=limit,
        )

    mul = client / "art.mul"
    idx = client / "artidx.mul"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError("artLegacyMUL.uop or art.mul/artidx.mul not found")


def _load_gumps(
    client: Path,
    *,
    range_start: Optional[int] = None,
    range_end: Optional[int] = None,
    limit: Optional[int] = None,
) -> UOIndexedFile:
    uop = client / "gumpartLegacyMUL.uop"
    if uop.is_file():
        return UOIndexedFile.from_uop(
            uop,
            entry_count=0x10000,
            has_extra_header=True,
            range_start=range_start,
            range_end=range_end,
            max_entries=limit,
        )

    mul = client / "gumpart.mul"
    idx = client / "gumpidx.mul"
    if not mul.is_file():
        mul = client / "Gumpart.mul"
    if not idx.is_file():
        idx = client / "Gumpidx.mul"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError("gumpartLegacyMUL.uop or gumpart.mul/gumpidx.mul not found")


def _load_textures(client: Path) -> UOIndexedFile:
    mul = client / "texmaps.mul"
    idx = client / "texidx.mul"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError("texmaps.mul/texidx.mul not found")


def _load_lights(client: Path) -> UOIndexedFile:
    mul = client / "light.mul"
    idx = client / "lightidx.mul"
    if mul.is_file() and idx.is_file():
        return UOIndexedFile.from_mul_idx(mul, idx)

    raise FileNotFoundError("light.mul/lightidx.mul not found")


def _load_hues(client: Path) -> UOHuesFile:
    path = client / "hues.mul"
    if path.is_file():
        return UOHuesFile.from_file(path)

    raise FileNotFoundError("hues.mul not found")


def _load_fonts(client: Path, *, max_fonts: int) -> UOAsciiFonts:
    path = client / "fonts.mul"
    if path.is_file():
        return UOAsciiFonts.from_file(path, max_fonts=max_fonts)

    raise FileNotFoundError("fonts.mul not found")


def _try_load_artdef(client: Path) -> UOArtDef | None:
    try:
        return _common._load_artdef(client)
    except FileNotFoundError:
        return None


def _artdef_metadata(entry: UOArtDefEntry | None) -> dict[str, object]:
    if entry is None:
        return {
            "artdef_redirect": "",
            "artdef_targets": "",
            "artdef_first_target": "",
            "artdef_hue": "",
        }
    return {
        "artdef_redirect": 1,
        "artdef_targets": "|".join(str(value) for value in entry.targets),
        "artdef_first_target": "" if entry.first_target is None else entry.first_target,
        "artdef_hue": entry.hue,
    }


def _art_metadata(
    tiledata: UOTileData | None,
    animdata: UOAnimData | None,
    artdef: UOArtDef | None,
    defs: dict[str, UODefFile] | None = None,
    tilehelp: dict[int, str] | None = None,
):
    texterr = None if defs is None else defs.get("texterr.def")

    def metadata(entry: UOIndexEntry) -> dict[str, object]:
        artdef_entry = artdef.entries.get(entry.index) if artdef is not None else None
        if entry.index < 0x4000:
            texterr_entry = (
                texterr.redirects.get(entry.index) if texterr is not None else None
            )
            land_tile = (
                tiledata.land[entry.index]
                if tiledata is not None and entry.index < len(tiledata.land)
                else None
            )
            return {
                "tile_kind": "land",
                "tile_id": entry.index,
                **_common._land_metadata(land_tile),
                **_artdef_metadata(artdef_entry),
                **_common._redirect_metadata("texterr", texterr_entry),
            }

        tile_id = entry.index - 0x4000
        static_tile = (
            tiledata.statics[tile_id]
            if tiledata is not None and tile_id < len(tiledata.statics)
            else None
        )
        anim_entry = animdata.entries.get(tile_id) if animdata is not None else None
        return {
            "tile_kind": "static",
            "tile_id": tile_id,
            **_common._static_metadata(static_tile, anim_entry, tilehelp),
            **_artdef_metadata(artdef_entry),
            **_common._redirect_metadata("texterr", None),
        }

    return metadata


def _gump_metadata(defs: dict[str, UODefFile]):
    gumpdef = defs.get("gump.def")

    def metadata(entry: UOIndexEntry) -> dict[str, object]:
        redirect = gumpdef.redirects.get(entry.index) if gumpdef is not None else None
        return _common._redirect_metadata("gumpdef", redirect)

    return metadata


def _texture_metadata(
    tiledata: UOTileData | None,
    defs: dict[str, UODefFile] | None = None,
):
    texterr = None if defs is None else defs.get("texterr.def")

    def metadata(entry: UOIndexEntry) -> dict[str, object]:
        if tiledata is None:
            return {
                "land_tile_count": "",
                "land_tile_ids": "",
                "land_tile_names": "",
                "texterr_redirect_count": "",
                "texterr_land_tile_ids": "",
                "texterr_targets": "",
                "texterr_hues": "",
            }

        tiles = tiledata.land_by_texture.get(entry.index, [])
        redirects = [
            redirect
            for tile in tiles
            if texterr is not None
            for redirect in [texterr.redirects.get(tile.tile_id)]
            if redirect is not None
        ]
        return {
            "land_tile_count": len(tiles),
            "land_tile_ids": "|".join(str(tile.tile_id) for tile in tiles[:32]),
            "land_tile_names": "|".join(tile.name for tile in tiles[:16] if tile.name),
            "texterr_redirect_count": len(redirects),
            "texterr_land_tile_ids": "|".join(
                str(redirect.source) for redirect in redirects[:32]
            ),
            "texterr_targets": "|".join(
                str(redirect.first_target)
                for redirect in redirects[:32]
                if redirect.first_target is not None
            ),
            "texterr_hues": "|".join(
                str(redirect.hue)
                for redirect in redirects[:32]
                if redirect.hue is not None
            ),
        }

    return metadata


def _export_entries(
    *,
    entries: list[UOIndexEntry],
    outdir: Path,
    group: str,
    decode,
    limit: Optional[int],
    metadata=None,
) -> tuple[int, int, int]:
    target = outdir / group
    target.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    saved = 0
    failed = 0

    for entry in entries:
        if limit is not None and saved >= limit:
            break

        try:
            image = decode(entry)
        except Exception as exc:
            print(f"  WARNING: failed {group} {entry.index}: {exc}", file=sys.stderr)
            failed += 1
            continue

        if image is None:
            failed += 1
            continue

        filename = f"{entry.index:05d}.png"
        image.save(target / filename)
        row: dict[str, object] = {
            "id": entry.index,
            "file": filename,
            "width": image.width,
            "height": image.height,
            "payload_bytes": len(entry.data),
            "extra": f"0x{entry.extra:08X}",
        }
        if metadata is not None:
            row.update(metadata(entry))
        rows.append(row)
        saved += 1

    _common._write_manifest(target / "manifest.csv", rows)
    return saved, failed, len(entries)


def cmd_art_export(args: SimpleNamespace) -> int:
    """Export UO art land tiles and static/item sprites to PNG."""
    try:
        client = _common._client_path(args.client)
        indexed = _load_art(
            client,
            range_start=args.range_start,
            range_end=args.range_end,
            limit=args.limit,
            kind=args.kind,
        )
        tiledata = _common._try_load_tiledata(client)
        animdata = _common._try_load_animdata(client)
        artdef = _try_load_artdef(client)
        defs = _common._try_load_defs(client)
        tilehelp = _common._try_load_tilehelp(client, "enu")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = _common._entry_iter(indexed, args.range_start, args.range_end)
    if args.kind == "land":
        entries = [entry for entry in entries if entry.index < 0x4000]
    elif args.kind == "static":
        entries = [entry for entry in entries if entry.index >= 0x4000]

    outdir = _common._out(args)
    saved, failed, total = _export_entries(
        entries=entries,
        outdir=outdir,
        group="art",
        decode=UOArtDecoder.decode,
        limit=args.limit,
        metadata=_art_metadata(tiledata, animdata, artdef, defs, tilehelp),
    )
    print(
        f"Exported {saved} art image(s) from {total} indexed entrie(s) -> {outdir / 'art'}"
    )
    if failed:
        print(f"  ({failed} art entrie(s) failed or decoded empty)")
    return 0


def cmd_gump_export(args: SimpleNamespace) -> int:
    """Export UO gump images to PNG."""
    try:
        client = _common._client_path(args.client)
        indexed = _load_gumps(
            client,
            range_start=args.range_start,
            range_end=args.range_end,
            limit=args.limit,
        )
        defs = _common._try_load_defs(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = _common._entry_iter(indexed, args.range_start, args.range_end)
    outdir = _common._out(args)
    saved, failed, total = _export_entries(
        entries=entries,
        outdir=outdir,
        group="gumps",
        decode=UOGumpDecoder.decode,
        limit=args.limit,
        metadata=_gump_metadata(defs),
    )
    print(
        f"Exported {saved} gump image(s) from {total} indexed entrie(s) -> {outdir / 'gumps'}"
    )
    if failed:
        print(f"  ({failed} gump entrie(s) failed or decoded empty)")
    return 0


def cmd_texture_export(args: SimpleNamespace) -> int:
    """Export UO land textures to PNG."""
    try:
        client = _common._client_path(args.client)
        indexed = _load_textures(client)
        tiledata = _common._try_load_tiledata(client)
        defs = _common._try_load_defs(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = _common._entry_iter(indexed, args.range_start, args.range_end)
    outdir = _common._out(args)
    saved, failed, total = _export_entries(
        entries=entries,
        outdir=outdir,
        group="textures",
        decode=UOTextureDecoder.decode,
        limit=args.limit,
        metadata=_texture_metadata(tiledata, defs),
    )
    print(
        f"Exported {saved} texture image(s) from {total} indexed entrie(s) -> {outdir / 'textures'}"
    )
    if failed:
        print(f"  ({failed} texture entrie(s) failed or decoded empty)")
    return 0


def cmd_light_export(args: SimpleNamespace) -> int:
    """Export UO light masks to PNG."""
    try:
        client = _common._client_path(args.client)
        indexed = _load_lights(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    entries = _common._entry_iter(indexed, args.range_start, args.range_end)
    outdir = _common._out(args)
    saved, failed, total = _export_entries(
        entries=entries,
        outdir=outdir,
        group="lights",
        decode=UOLightDecoder.decode,
        limit=args.limit,
    )
    print(
        f"Exported {saved} light image(s) from {total} indexed entrie(s) -> {outdir / 'lights'}"
    )
    if failed:
        print(f"  ({failed} light entrie(s) failed or decoded empty)")
    return 0


def cmd_hue_export(args: SimpleNamespace) -> int:
    """Export UO hue ramps to PNG."""
    try:
        client = _common._client_path(args.client)
        hues = _load_hues(client)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    start = 0 if args.range_start is None else args.range_start
    end = (
        len(hues.hues)
        if args.range_end is None
        else min(args.range_end, len(hues.hues))
    )
    selected = [hue for hue in hues.hues if start <= hue.index < end]

    outdir = _common._out(args) / "hues"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    saved = 0

    for hue in selected:
        if args.limit is not None and saved >= args.limit:
            break
        filename = f"{hue.index:05d}.png"
        hue.to_image(swatch_size=args.swatch_size).save(outdir / filename)
        rows.append(
            {
                "index": hue.index,
                "client_id": hue.client_id,
                "file": filename,
                "group": hue.group,
                "entry": hue.entry,
                "table_start": hue.table_start,
                "table_end": hue.table_end,
                "name": hue.name,
            }
        )
        saved += 1

    _common._write_manifest(outdir / "manifest.csv", rows)
    print(
        f"Exported {saved} hue ramp image(s) from {len(selected)} hue entrie(s) -> {outdir}"
    )
    return 0


def cmd_font_export(args: SimpleNamespace) -> int:
    """Export UO ASCII font atlases and glyph metadata."""
    try:
        client = _common._client_path(args.client)
        fonts = _load_fonts(client, max_fonts=args.limit_fonts)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    outdir = _common._out(args) / "fonts"
    outdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    for font in fonts.fonts:
        font_dir = outdir / f"font_{font.index:03d}"
        font_dir.mkdir(parents=True, exist_ok=True)
        atlas_file = "atlas.png"
        font.atlas(columns=args.columns).save(font_dir / atlas_file)

        if args.glyphs:
            glyph_dir = font_dir / "glyphs"
            glyph_dir.mkdir(parents=True, exist_ok=True)
        else:
            glyph_dir = None

        for glyph in font.glyphs:
            glyph_file = ""
            if glyph_dir is not None and glyph.image is not None:
                glyph_file = f"{glyph.char_code:03d}.png"
                glyph.image.save(glyph_dir / glyph_file)
            rows.append(
                {
                    "font": font.index,
                    "font_header": f"0x{font.header:02X}",
                    "glyph": glyph.index,
                    "char_code": glyph.char_code,
                    "char": glyph.char if 32 <= glyph.char_code < 127 else "",
                    "width": glyph.width,
                    "height": glyph.height,
                    "unknown": f"0x{glyph.unknown:02X}",
                    "atlas": f"font_{font.index:03d}/{atlas_file}",
                    "glyph_file": (
                        f"font_{font.index:03d}/glyphs/{glyph_file}"
                        if glyph_file
                        else ""
                    ),
                }
            )

    _common._write_manifest(outdir / "manifest.csv", rows)
    print(f"Exported {len(fonts.fonts)} font atlas(es) -> {outdir}")
    return 0


def art_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    kind: Annotated[
        Literal["all", "land", "static"],
        typer.Option("--kind", help="Subset to export."),
    ] = "all",
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum successfully decoded images to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First resource ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last resource ID, exclusive."),
    ] = None,
) -> None:
    """Export UO art land tiles and static/item sprites to PNG."""
    raise SystemExit(cmd_art_export(SimpleNamespace(**locals())))


def gump_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum successfully decoded images to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First resource ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last resource ID, exclusive."),
    ] = None,
) -> None:
    """Export UO gump images to PNG."""
    raise SystemExit(cmd_gump_export(SimpleNamespace(**locals())))


def texture_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum successfully decoded images to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First resource ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last resource ID, exclusive."),
    ] = None,
) -> None:
    """Export UO land textures to PNG."""
    raise SystemExit(cmd_texture_export(SimpleNamespace(**locals())))


def light_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum successfully decoded images to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First resource ID, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last resource ID, exclusive."),
    ] = None,
) -> None:
    """Export UO light masks to PNG."""
    raise SystemExit(cmd_light_export(SimpleNamespace(**locals())))


def hue_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", help="Maximum hue ramps to export."),
    ] = None,
    range_start: Annotated[
        Optional[int],
        typer.Option("--range-start", help="First zero-based hue index, inclusive."),
    ] = None,
    range_end: Annotated[
        Optional[int],
        typer.Option("--range-end", help="Last zero-based hue index, exclusive."),
    ] = None,
    swatch_size: Annotated[
        int,
        typer.Option(
            "--swatch-size", help="Pixel size for each of the 32 hue colours."
        ),
    ] = 8,
) -> None:
    """Export UO hue ramps to PNG."""
    raise SystemExit(cmd_hue_export(SimpleNamespace(**locals())))


def font_export_cmd(
    client: Annotated[
        Optional[str],
        typer.Argument(
            help="Client directory or [uo.installs] name; optional if [uo.game] install/base is configured."
        ),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory. Default: the install's configured output, else uodata.",
        ),
    ] = None,
    limit_fonts: Annotated[
        int,
        typer.Option("--limit-fonts", help="Maximum fonts to parse/export."),
    ] = 10,
    columns: Annotated[
        int,
        typer.Option("--columns", help="Atlas columns."),
    ] = 16,
    glyphs: Annotated[
        bool,
        typer.Option("--glyphs", help="Also export individual glyph PNGs."),
    ] = False,
) -> None:
    """Export UO ASCII font atlases and glyph metadata."""
    raise SystemExit(cmd_font_export(SimpleNamespace(**locals())))
