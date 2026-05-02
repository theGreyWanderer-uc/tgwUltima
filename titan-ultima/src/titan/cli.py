"""
TITAN command-line interface.

Root commands (game-agnostic):
    flex-info, flex-list, flex-extract, flex-create, flex-update,
    music-export, music-batch, setup, config.

Sub-apps:
    u8  — Ultima 8: Pagan commands (shape, map, sound, save, etc.)
    u7  — Ultima 7 commands (placeholder — coming soon)

Old root-level U8 commands (e.g. ``titan shape-export``) are still
accepted as hidden deprecated aliases that forward to ``titan u8 …``.

Entry point (pyproject.toml)::

    [project.scripts]
    titan = "titan.cli:main"
"""

from __future__ import annotations

__all__ = ["app", "main"]

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan._version import TITAN_VERSION
from titan._config import (
    find_config,
    load_config,
    cfg as _cfg,
    get_config,
)
from titan.flex import (
    FlexArchive,
    FLEX_HEADER_SIZE,
    get_extension_for_flex,
)
from titan.music import XMIDIConverter


# ============================================================================
# Typer App
# ============================================================================

app = typer.Typer(
    name="titan",
    help=(
        "TITAN \u2013 Tool for Interpreting and Transforming Archival Nodes.\n"
        "Work with Ultima file formats (U8, U7)."
    ),
    no_args_is_help=True,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)


def _version_callback(value: bool) -> None:
    if value:
        print(f"TITAN v{TITAN_VERSION}")
        raise typer.Exit()


@app.callback()
def _global_options(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Print version and exit.",
        ),
    ] = False,
    config: Annotated[
        Optional[str],
        typer.Option("--config", "-c", help="Path to titan.toml config file."),
    ] = None,
) -> None:
    """TITAN \u2013 Tool for Interpreting and Transforming Archival Nodes."""
    import titan._config as _config_mod
    _config_mod.explicit_config_path = config
    _config_mod.load_config(config)


# ============================================================================
# CLI COMMANDS — FLEX
# ============================================================================

def cmd_flex_info(args: SimpleNamespace) -> int:
    """Show detailed information about a Flex archive."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    if not FlexArchive.is_flex(filepath):
        print(f"ERROR: Not a valid Flex archive: {filepath}", file=sys.stderr)
        return 1

    archive = FlexArchive.from_file(filepath)
    print(archive.summary())
    print()

    # Show raw header bytes for inspection
    with open(filepath, "rb") as f:
        raw_header = f.read(FLEX_HEADER_SIZE)

    print("Raw header (first 128 bytes):")
    for row_start in range(0, FLEX_HEADER_SIZE, 16):
        row = raw_header[row_start:row_start + 16]
        hex_part = " ".join(f"{b:02X}" for b in row)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        print(f"  {row_start:04X}: {hex_part:<48s}  {ascii_part}")

    return 0


def cmd_flex_list(args: SimpleNamespace) -> int:
    """List contents of a Flex archive."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    if not FlexArchive.is_flex(filepath):
        print(f"ERROR: Not a valid Flex archive: {filepath}", file=sys.stderr)
        return 1

    archive = FlexArchive.from_file(filepath)
    print(archive.summary())
    print()
    print(archive.record_table())
    return 0


def cmd_flex_extract(args: SimpleNamespace) -> int:
    """Extract all objects from a Flex archive into a directory."""
    filepath = args.file
    outdir = args.output

    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    if not FlexArchive.is_flex(filepath):
        print(f"ERROR: Not a valid Flex archive: {filepath}", file=sys.stderr)
        return 1

    archive = FlexArchive.from_file(filepath)

    # Determine output directory
    if outdir is None:
        # Default: create a subfolder named after the flex file (minus extension)
        base_name = Path(filepath).stem
        outdir = os.path.join(".", base_name)

    os.makedirs(outdir, exist_ok=True)

    flex_name = os.path.basename(filepath)
    extracted = 0
    skipped = 0

    for i, record in enumerate(archive.records):
        if not record:
            skipped += 1
            continue

        ext = get_extension_for_flex(flex_name, record)
        name = archive.get_record_name(i)
        safe = FlexArchive._safe_filename(name) if name else ""

        if safe:
            stem = f"{i:04d}_{safe}"
        else:
            stem = f"{i:04d}"

        out_path = os.path.join(outdir, f"{stem}{ext}")
        with open(out_path, "wb") as f:
            f.write(record)

        # Write companion metadata file
        archive._write_record_metadata(outdir, stem, i, name, record, flex_name)

        extracted += 1

    outdir_display = outdir.rstrip("/\\") + "/"
    print(f"Extracted {extracted} records from {flex_name} -> {outdir_display}")
    if skipped > 0:
        print(f"  ({skipped} empty records skipped)")
    named_count = sum(1 for n in archive.record_names if n)
    if named_count > 0:
        print(f"  ({named_count} records have names from embedded name table)")

    # Write a manifest file for reconstruction
    manifest_path = os.path.join(outdir, "_manifest.txt")
    with open(manifest_path, "w") as mf:
        mf.write("# TITAN Flex Manifest\n")
        mf.write(f"# Source: {os.path.abspath(filepath)}\n")
        mf.write(f"# Records: {len(archive.records)}\n")
        mf.write(f"# Comment: {archive.comment}\n")
        mf.write(f"# Unknown field: 0x{archive.unknown_field:08X}\n")
        mf.write("#\n")
        mf.write("# Index | Size | Filename | Name\n")
        for i, record in enumerate(archive.records):
            rec_name = archive.get_record_name(i)
            if record:
                ext = get_extension_for_flex(flex_name, record)
                safe = FlexArchive._safe_filename(rec_name) if rec_name else ""
                stem = f"{i:04d}_{safe}" if safe else f"{i:04d}"
                mf.write(f"{i}|{len(record)}|{stem}{ext}|{rec_name}\n")
            else:
                mf.write(f"{i}|0||{rec_name}\n")

    print(f"  Manifest written: {manifest_path}")
    return 0


def cmd_flex_create(args: SimpleNamespace) -> int:
    """Create a Flex archive from files in a directory."""
    source_dir = args.directory
    output_file = args.output
    comment = args.comment

    if not os.path.isdir(source_dir):
        print(f"ERROR: Directory not found: {source_dir}", file=sys.stderr)
        return 1

    # Check if a manifest exists for guided reconstruction
    manifest_path = os.path.join(source_dir, "_manifest.txt")
    if os.path.isfile(manifest_path):
        archive = _create_from_manifest(source_dir, manifest_path, comment)
    else:
        archive = FlexArchive.from_directory(source_dir, comment)

    if output_file is None:
        # Default output name: directory name + .flx
        output_file = Path(source_dir).stem + ".flx"

    archive.save(output_file)
    return 0


def _create_from_manifest(source_dir: str, manifest_path: str,
                          comment_override: str = "") -> FlexArchive:
    """Reconstruct a Flex archive guided by a _manifest.txt file."""
    archive = FlexArchive()

    original_comment = ""
    unknown_field = 1
    entries: list[tuple[int, int, str]] = []  # (index, size, filename)

    with open(manifest_path, "r") as mf:
        for line in mf:
            line = line.strip()
            if line.startswith("# Comment:"):
                original_comment = line[len("# Comment:"):].strip()
            elif line.startswith("# Unknown field:"):
                try:
                    unknown_field = int(line.split(":")[-1].strip(), 0)
                except ValueError:
                    pass
            elif line.startswith("#") or not line:
                continue
            else:
                parts = line.split("|")
                if len(parts) >= 3:
                    idx = int(parts[0])
                    size = int(parts[1])
                    fname = parts[2].strip()
                    entries.append((idx, size, fname))

    archive.comment = (comment_override or original_comment
                       or f"Rebuilt by TITAN v{TITAN_VERSION}")
    archive.unknown_field = unknown_field

    if not entries:
        return archive

    max_index = max(e[0] for e in entries)
    archive.records = [b""] * (max_index + 1)

    for idx, expected_size, fname in entries:
        if not fname:
            continue  # Empty record
        fpath = os.path.join(source_dir, fname)
        if not os.path.isfile(fpath):
            print(f"  WARNING: Missing file for record {idx}: {fpath}",
                  file=sys.stderr)
            continue
        data = Path(fpath).read_bytes()
        if len(data) != expected_size:
            print(f"  WARNING: Record {idx} size mismatch "
                  f"(expected {expected_size}, got {len(data)})",
                  file=sys.stderr)
        archive.records[idx] = data

    return archive


def cmd_flex_update(args: SimpleNamespace) -> int:
    """Replace a single record inside a Flex archive."""
    flex_path = args.file
    if not os.path.isfile(flex_path):
        print(f"ERROR: File not found: {flex_path}", file=sys.stderr)
        return 1

    data_path = args.data
    if not os.path.isfile(data_path):
        print(f"ERROR: Replacement data file not found: {data_path}",
              file=sys.stderr)
        return 1

    index = args.index
    if index < 0:
        print(f"ERROR: Invalid index: {index}", file=sys.stderr)
        return 1

    archive = FlexArchive.from_file(flex_path)

    if index >= len(archive.records):
        print(f"ERROR: Index {index} out of range "
              f"(archive has {len(archive.records)} records)",
              file=sys.stderr)
        return 1

    old_size = len(archive.records[index]) if archive.records[index] else 0
    new_data = Path(data_path).read_bytes()
    archive.records[index] = new_data

    output_path = args.output or flex_path
    archive.save(output_path)

    print(f"Flex updated: record {index} replaced "
          f"({old_size:,} -> {len(new_data):,} bytes) -> {output_path}")
    return 0


# ============================================================================
# CLI COMMANDS — MUSIC (XMIDI)
# ============================================================================

def cmd_music_export(args: SimpleNamespace) -> int:
    """Convert a single XMIDI file to standard MIDI."""
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return 1

    with open(filepath, "rb") as f:
        data = f.read()

    midi_data = XMIDIConverter.convert(data)
    if midi_data is None:
        print(f"ERROR: Failed to convert XMIDI: {filepath}", file=sys.stderr)
        return 1

    outdir = args.output or "."
    os.makedirs(outdir, exist_ok=True)

    base = Path(filepath).stem
    out_path = os.path.join(outdir, f"{base}.mid")
    with open(out_path, "wb") as f:
        f.write(midi_data)

    print(f"Converted: {out_path}  ({len(data)} -> {len(midi_data)} bytes)")
    return 0


def cmd_music_batch(args: SimpleNamespace) -> int:
    """Batch-convert all XMIDI .xmi files in a directory to standard MIDI."""
    srcdir = args.directory
    if not os.path.isdir(srcdir):
        print(f"ERROR: Directory not found: {srcdir}", file=sys.stderr)
        return 1

    outdir = args.output or os.path.join(srcdir, "midi")
    os.makedirs(outdir, exist_ok=True)

    xmi_files = sorted(f for f in os.listdir(srcdir)
                       if f.lower().endswith(".xmi"))
    if not xmi_files:
        print(f"No .xmi files found in {srcdir}")
        return 0

    converted = 0
    failed = 0

    for xmi_file in xmi_files:
        xmi_path = os.path.join(srcdir, xmi_file)
        try:
            with open(xmi_path, "rb") as f:
                data = f.read()

            midi_data = XMIDIConverter.convert(data)
            if midi_data is None:
                print(f"  SKIP: {xmi_file} (conversion failed)")
                failed += 1
                continue

            base = Path(xmi_file).stem
            out_path = os.path.join(outdir, f"{base}.mid")
            with open(out_path, "wb") as f:
                f.write(midi_data)
            converted += 1
        except Exception as e:
            print(f"  WARNING: Failed {xmi_file}: {e}", file=sys.stderr)
            failed += 1

    print(f"Batch convert complete: {converted} MIDIs created, "
          f"{failed} skipped -> {outdir.rstrip('/\\')}/")
    return 0


# ============================================================================
# CONFIG COMMANDS — setup wizard + inspector
# ============================================================================

def cmd_config(args: SimpleNamespace) -> int:
    """Show the active titan.toml configuration (or open it for editing)."""
    import titan._config as _config_mod

    explicit = getattr(args, "config", None) or _config_mod.explicit_config_path
    path = Path(explicit) if explicit else find_config()

    if getattr(args, "edit", False):
        if path is None:
            print("No titan.toml found. Run `titan setup` to create one.")
            return 1
        editor = (
            os.getenv("VISUAL") or os.getenv("EDITOR")
            or ("notepad" if sys.platform == "win32" else "nano")
        )
        os.system(f'{editor} "{path}"')
        return 0

    if path is None or not path.exists():
        if explicit:
            print(f"ERROR: Config file not found: {explicit}", file=sys.stderr)
            return 1
        print("No titan.toml found.")
        print("  Locations checked:")
        print(f"    {Path.cwd() / 'titan.toml'}")
        print(f"    {Path.home() / '.config' / 'titan' / 'config.toml'}")
        appdata = os.getenv("APPDATA")
        if appdata:
            print(f"    {Path(appdata) / 'titan' / 'config.toml'}")
        print("\nRun `titan setup` to create one.")
        return 0

    config = load_config(str(path))

    def _print_kv_section(title: str, section: dict, check_exists: bool = False) -> None:
        if not section:
            return
        print()
        print(title)
        for k, v in section.items():
            if check_exists:
                exists = Path(str(v)).exists() if v else False
                flag = "OK" if exists else "NOT FOUND"
                print(f"  {k:<12} = {v!r}  [{flag}]")
            else:
                print(f"  {k:<12} = {v!r}")

    print(f"Active config: {path.absolute()}")

    u8 = config.get("u8", {})
    u7bg = config.get("u7bg", {})
    u7si = config.get("u7si", {})
    if any((u8, u7bg, u7si)):
        _print_kv_section("[u8.game]", u8.get("game", {}))
        _print_kv_section("[u8.paths]", u8.get("paths", {}), check_exists=True)
        _print_kv_section("[u7bg.game]", u7bg.get("game", {}))
        _print_kv_section("[u7bg.paths]", u7bg.get("paths", {}), check_exists=True)
        _print_kv_section("[u7si.game]", u7si.get("game", {}))
        _print_kv_section("[u7si.paths]", u7si.get("paths", {}), check_exists=True)
    else:
        game = config.get("game", {})
        paths = config.get("paths", {})
        _print_kv_section("[game]", game)
        _print_kv_section("[paths]  (after base expansion)", paths, check_exists=True)
    return 0


def cmd_setup(args: SimpleNamespace) -> int:
    """Interactive first-time setup wizard \u2014 creates titan.toml."""
    print("TITAN Setup Wizard")
    print("=" * 55)
    print("This will create titan.toml for Ultima 8 and Ultima 7 installs.\n")

    # -- Auto-detect standard install locations --------------------
    candidates: list[Path] = []

    def _add_candidate(path: Path) -> None:
        if path not in candidates:
            candidates.append(path)

    def _is_u8_folder_name(name: str) -> bool:
        lowered = name.lower()
        if "ultima" not in lowered:
            return False
        # Avoid nearby U7/SI installs when dynamically scanning launcher roots.
        if "serpent" in lowered:
            return False
        if "ultima 7" in lowered or "ultima7" in lowered:
            return False
        return any(token in lowered for token in ("ultima 8", "ultima8", "viii", "pagan"))

    def _is_u7_folder_name(name: str) -> bool:
        lowered = name.lower()
        if "ultima" not in lowered:
            return False
        return any(token in lowered for token in ("ultima 7", "ultima7", "black gate", "serpent"))

    def _looks_like_u7_root(path: Path) -> bool:
        static_candidates = [
            path / "STATIC",
            path / "ULTIMA7" / "STATIC",
            path / "SERPENT" / "STATIC",
        ]
        return any(static.is_dir() for static in static_candidates)
    # Windows: GOG Galaxy client (most common current install)
    for drive in "CDEFG":
        _add_candidate(Path(f"{drive}:\\Program Files (x86)\\GOG Galaxy\\Games\\Ultima 8"))
    # Windows: GOG Offline Installer + common manual redirects
    for drive in "CDEFG":
        for path in [
            Path(f"{drive}:\\GOG Games\\Ultima 8"),
            Path(f"{drive}:\\ULTIMA8"),
            Path(f"{drive}:\\ultima8"),
        ]:
            _add_candidate(path)
    # Windows: Legacy EA/Origin disc installs
    for path in [
        Path(r"C:\Program Files\EA Games\Ultima 8 Gold Edition"),
        Path(r"C:\Program Files (x86)\Origin Games\Ultima 8 Gold Edition"),
    ]:
        _add_candidate(path)

    # Linux: direct known paths
    _add_candidate(Path.home() / "GOG Games" / "Ultima 8")
    _add_candidate(Path.home() / "Games" / "Heroic" / "Ultima 8")

    # Linux: dynamic launcher roots (discover all Ultima-* folders)
    linux_roots = [
        Path.home() / "GOG Games",
        Path.home() / "Games" / "Heroic",
    ]
    for root in linux_roots:
        if not root.is_dir():
            continue
        try:
            for item in root.iterdir():
                if item.is_dir() and _is_u8_folder_name(item.name):
                    _add_candidate(item)
        except PermissionError:
            continue

    # U7 auto-detection candidates.
    u7_candidates: list[Path] = []

    def _add_u7_candidate(path: Path) -> None:
        if path not in u7_candidates:
            u7_candidates.append(path)

    for drive in "CDEFG":
        for path in [
            Path(f"{drive}:\\GOG Games\\Ultima VII"),
            Path(f"{drive}:\\GOG Games\\Ultima VII - Complete"),
            Path(f"{drive}:\\ULTIMA7"),
            Path(f"{drive}:\\SERPENT"),
        ]:
            _add_u7_candidate(path)

    for path in [
        Path.home() / "GOG Games" / "Ultima VII",
        Path.home() / "Games" / "Heroic" / "Ultima 7",
        Path.home() / "Games" / "Heroic" / "Ultima 7 - Serpent Isle",
    ]:
        _add_u7_candidate(path)

    for root in linux_roots:
        if not root.is_dir():
            continue
        try:
            for item in root.iterdir():
                if item.is_dir() and _is_u7_folder_name(item.name):
                    _add_u7_candidate(item)
        except PermissionError:
            continue

    detected_base: Optional[Path] = None
    detected_lang = "ENGLISH"
    detected_u8: list[tuple[Path, str]] = []

    print("Searching for Ultima 8 installation...")
    for base in candidates:
        if not base.exists():
            continue
        try:
            for item in base.iterdir():
                if not item.is_dir():
                    continue
                static = item / "STATIC"
                if static.exists() and (static / "FIXED.DAT").exists():
                    detected_u8.append((base, item.name))
                    break
        except PermissionError:
            continue

    if detected_u8:
        detected_base, detected_lang = detected_u8[0]
        for base, lang_name in detected_u8:
            print(f"  Found: {base}  (language: {lang_name})")

    if not detected_base:
        print("  No standard installation found.")

    default_base = str(detected_base) if detected_base else str(Path.cwd())
    base_input = input(f"\nGame base path [{default_base}]: ").strip()
    base = base_input or default_base

    default_lang = detected_lang if detected_base else ""
    lang_prompt = (
        f"Language folder (ENGLISH/FRENCH/GERMAN) "
        f"[{default_lang or 'leave empty for flat mode'}]: "
    )
    lang = input(lang_prompt).strip()
    if lang == "":
        lang = default_lang  # keep detected; empty string IS flat mode only if nothing detected

    # -- U7 install detection (BG + SI) ---------------------------
    detected_u7bg: Optional[Path] = None
    detected_u7si: Optional[Path] = None
    print("\nSearching for Ultima 7 installations...")
    for u7_base in u7_candidates:
        if not u7_base.exists() or not _looks_like_u7_root(u7_base):
            continue
        lowered = u7_base.name.lower()
        if "serpent" in lowered:
            if detected_u7si is None:
                detected_u7si = u7_base
                print(f"  Found Serpent Isle: {u7_base}")
        else:
            if detected_u7bg is None:
                detected_u7bg = u7_base
                print(f"  Found Black Gate:   {u7_base}")

    bg_default = str(detected_u7bg) if detected_u7bg else ""
    si_default = str(detected_u7si) if detected_u7si else ""

    u7bg_input = input(f"Ultima VII Black Gate base [{bg_default or 'optional'}]: ").strip()
    u7si_input = input(f"Ultima VII Serpent Isle base [{si_default or 'optional'}]: ").strip()

    u7bg_base = (u7bg_input or bg_default).replace("\\", "/")
    u7si_base = (u7si_input or si_default).replace("\\", "/")

    # -- Third-party engine save detection -------------------------
    appdata = os.getenv("APPDATA")
    engine_save_file: Optional[Path] = None
    # Windows: %APPDATA%\Pentagram\u8-save
    if appdata:
        pent_save = Path(appdata) / "Pentagram" / "u8-save"
        if (pent_save / "U8SAVE.000").exists():
            engine_save_file = pent_save / "U8SAVE.000"
    # macOS: ~/Library/Application Support/Pentagram/u8-save
    if engine_save_file is None:
        mac_save = Path.home() / "Library" / "Application Support" / "Pentagram" / "u8-save"
        if (mac_save / "U8SAVE.000").exists():
            engine_save_file = mac_save / "U8SAVE.000"

    nonfixed_value = "U8SAVE.000"
    if engine_save_file:
        print(f"\nThird-party engine save detected: {engine_save_file}")
        ans = input("Use this save instead of game-folder saves? [Y/n] ").strip().lower()
        if ans not in ("n", "no"):
            nonfixed_value = str(engine_save_file).replace("\\", "/")

    # -- Detection summary + confirmation -------------------------
    u8_static_detected = (Path(base) / lang / "STATIC") if lang else Path(base)
    u8_usecode_detected = (
        (Path(base) / lang / "USECODE" / "EUSECODE.FLX")
        if lang else (Path(base) / "USECODE" / "EUSECODE.FLX")
    )
    u7bg_static_detected = (Path(u7bg_base) / "STATIC") if u7bg_base else None
    u7si_static_detected = (Path(u7si_base) / "STATIC") if u7si_base else None

    print("\nDetected folders to write to titan.toml:")
    print(f"  U8 base:      {base}")
    print(f"  U8 language:  {lang or '(flat mode)'}")
    print(f"  U8 STATIC:    {u8_static_detected}")
    print(f"  U8 USECODE:   {u8_usecode_detected}")
    print(f"  U7 BG base:   {u7bg_base or '(empty)'}")
    print(f"  U7 BG STATIC: {u7bg_static_detected or '(empty)'}")
    print(f"  U7 SI base:   {u7si_base or '(empty)'}")
    print(f"  U7 SI STATIC: {u7si_static_detected or '(empty)'}")

    confirm = input("Are these paths correct? [Y/n] ").strip().lower()

    manual_u8_static = ""
    manual_u8_usecode = ""
    manual_u7bg_static = ""
    manual_u7si_static = ""

    if confirm in ("n", "no"):
        print("\nClearing detected values and switching to manual STATIC path entry.")
        base = ""
        lang = ""
        u7bg_base = ""
        u7si_base = ""

        manual_u8_static = input("U8 STATIC path [optional]: ").strip().replace("\\", "/")
        manual_u8_usecode = input("U8 EUSECODE.FLX path [optional]: ").strip().replace("\\", "/")
        manual_u7bg_static = input("U7 BG STATIC path [optional]: ").strip().replace("\\", "/")
        manual_u7si_static = input("U7 SI STATIC path [optional]: ").strip().replace("\\", "/")

    # -- Build and write titan.toml --------------------------------
    base_toml = base.replace("\\", "/")
    nonfixed_is_abs = Path(nonfixed_value).is_absolute()

    u8_static_manual_path = Path(manual_u8_static) if manual_u8_static else None
    if manual_u8_usecode:
        u8_usecode_path = manual_u8_usecode
    elif u8_static_manual_path is not None:
        u8_usecode_path = str(u8_static_manual_path.parent / "USECODE" / "EUSECODE.FLX").replace("\\", "/")
    else:
        u8_usecode_path = str(u8_usecode_detected).replace("\\", "/")

    if u8_static_manual_path is not None:
        u8_paths_fixed = str(u8_static_manual_path / "FIXED.DAT").replace("\\", "/")
        u8_paths_palette = str(u8_static_manual_path / "U8PAL.PAL").replace("\\", "/")
        u8_paths_typeflag = str(u8_static_manual_path / "TYPEFLAG.DAT").replace("\\", "/")
        u8_paths_gumpage = str(u8_static_manual_path / "GUMPAGE.DAT").replace("\\", "/")
        u8_paths_xformpal = str(u8_static_manual_path / "XFORMPAL.DAT").replace("\\", "/")
        u8_paths_ecredits = str(u8_static_manual_path / "ECREDITS.DAT").replace("\\", "/")
        u8_paths_quotes = str(u8_static_manual_path / "QUOTES.DAT").replace("\\", "/")
        u8_paths_shapes_flx = str(u8_static_manual_path / "U8SHAPES.FLX").replace("\\", "/")
        u8_paths_fonts_flx = str(u8_static_manual_path / "U8FONTS.FLX").replace("\\", "/")
        u8_paths_gumps_flx = str(u8_static_manual_path / "U8GUMPS.FLX").replace("\\", "/")
    else:
        u8_paths_fixed = "FIXED.DAT"
        u8_paths_palette = "U8PAL.PAL"
        u8_paths_typeflag = "TYPEFLAG.DAT"
        u8_paths_gumpage = "GUMPAGE.DAT"
        u8_paths_xformpal = "XFORMPAL.DAT"
        u8_paths_ecredits = "ECREDITS.DAT"
        u8_paths_quotes = "QUOTES.DAT"
        u8_paths_shapes_flx = "U8SHAPES.FLX"
        u8_paths_fonts_flx = "U8FONTS.FLX"
        u8_paths_gumps_flx = "U8GUMPS.FLX"

    def _u7_section_from_manual(static_path: str, variant: str) -> list[str]:
        static_norm = static_path.replace("\\", "/")
        static_p = Path(static_norm)
        base_guess = ""
        if static_p.name.upper() == "STATIC" and static_p.parent != static_p:
            base_guess = str(static_p.parent).replace("\\", "/")
        section_name = "u7bg" if variant == "blackgate" else "u7si"
        return [
            "",
            f"[{section_name}.game]",
            f'base     = "{base_guess}"',
            f'variant  = "{variant}"',
            "",
            f"[{section_name}.paths]",
            f'static   = "{static_norm}"',
            f'shapes   = "{static_norm}/SHAPES.VGA"',
            f'palette  = "{static_norm}/PALETTES.FLX"',
        ]

    lines = [
        "# titan.toml \u2014 created by `titan setup`",
        "[u8.game]",
        f'base     = "{base_toml}"',
        f'language = "{lang}"',
        "",
        "[u8.paths]",
        f'fixed     = "{u8_paths_fixed}"',
        f'palette   = "{u8_paths_palette}"',
        f'typeflag  = "{u8_paths_typeflag}"',
        f'gumpage   = "{u8_paths_gumpage}"',
        f'xformpal  = "{u8_paths_xformpal}"',
        f'ecredits  = "{u8_paths_ecredits}"',
        f'quotes    = "{u8_paths_quotes}"',
        "",
        f'u8shapes  = "{u8_paths_shapes_flx}"',
        f'u8fonts   = "{u8_paths_fonts_flx}"',
        f'u8gumps   = "{u8_paths_gumps_flx}"',
        f'usecode   = "{u8_usecode_path}"',
        "",
        "# Pre-extracted directories (relative to where you run titan)",
        'shapes    = "shapes/"',
        'globs     = "globs/"',
        "",
        "# Live/dynamic objects \u2014 U8SAVE.000 from game or third-party engine",
    ]
    if nonfixed_is_abs:
        lines.append(f'nonfixed  = "{nonfixed_value}"  # absolute (third-party engine)')
    else:
        lines.append(f'nonfixed  = "{nonfixed_value}"')

    if manual_u7bg_static:
        lines += _u7_section_from_manual(manual_u7bg_static, "blackgate")
    elif u7bg_base:
        lines += [
            "",
            "[u7bg.game]",
            f'base     = "{u7bg_base}"',
            'variant  = "blackgate"',
            "",
            "[u7bg.paths]",
            'static   = "STATIC/"',
            'shapes   = "STATIC/SHAPES.VGA"',
            'palette  = "STATIC/PALETTES.FLX"',
        ]

    if manual_u7si_static:
        lines += _u7_section_from_manual(manual_u7si_static, "serpentisle")
    elif u7si_base:
        lines += [
            "",
            "[u7si.game]",
            f'base     = "{u7si_base}"',
            'variant  = "serpentisle"',
            "",
            "[u7si.paths]",
            'static   = "STATIC/"',
            'shapes   = "STATIC/SHAPES.VGA"',
            'palette  = "STATIC/PALETTES.FLX"',
        ]

    toml_path = Path.cwd() / "titan.toml"
    toml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n  Created: {toml_path.absolute()}")

    # -- Optional extraction ---------------------------------------
    ans = input("\nExtract shapes/ and globs/ now? [Y/n] ").strip().lower()
    if ans not in ("n", "no"):
        if manual_u8_static:
            static_dir = Path(manual_u8_static)
        else:
            static_dir = (
                (Path(base) / lang / "STATIC") if lang else Path(base)
            )
        for flx, out in [("U8SHAPES.FLX", "shapes/"), ("GLOB.FLX", "globs/")]:
            src = static_dir / flx
            if src.exists():
                print(f"\nExtracting {flx} -> {out}")
                os.system(f'titan flex-extract "{src}" -o {out}')
            else:
                print(f"  WARNING: {src} not found \u2014 skipping")
        print("\n  Extraction complete.")

    print("\nAll done! Try:")
    print("   titan u8 map-render -m 5")
    print("   titan config")
    return 0


# ============================================================================
# Typer command wrappers — shared / game-agnostic
# ============================================================================


@app.command("flex-info")
def flex_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to the .flx file")],
) -> None:
    """Show detailed header info of a Flex archive."""
    raise SystemExit(cmd_flex_info(SimpleNamespace(file=file)))


@app.command("flex-list")
def flex_list_cmd(
    file: Annotated[str, typer.Argument(help="Path to the .flx file")],
) -> None:
    """List contents of a Flex archive."""
    raise SystemExit(cmd_flex_list(SimpleNamespace(file=file)))


@app.command("flex-extract")
def flex_extract_cmd(
    file: Annotated[str, typer.Argument(help="Path to the .flx file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: ./<flexname>/)"),
    ] = None,
) -> None:
    """Extract all objects from a Flex archive."""
    raise SystemExit(cmd_flex_extract(SimpleNamespace(file=file, output=output)))


@app.command("flex-create")
def flex_create_cmd(
    directory: Annotated[
        str,
        typer.Argument(help="Source directory with numbered files (e.g., 0000.bin, 0001.shp)"),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output .flx file path (default: <dirname>.flx)"),
    ] = None,
    comment: Annotated[
        str,
        typer.Option("-C", "--comment", help="Comment string to embed in the Flex header"),
    ] = "",
) -> None:
    """Create a Flex archive from files in a directory."""
    raise SystemExit(cmd_flex_create(SimpleNamespace(
        directory=directory, output=output, comment=comment,
    )))


@app.command("flex-update")
def flex_update_cmd(
    file: Annotated[str, typer.Argument(help="Path to .flx archive")],
    index: Annotated[int, typer.Option("--index", help="Record index to replace (0-based)")],
    data: Annotated[str, typer.Option("--data", help="Path to the replacement file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output .flx path (default: overwrite input)"),
    ] = None,
) -> None:
    """Replace a single record inside a Flex archive."""
    raise SystemExit(cmd_flex_update(SimpleNamespace(
        file=file, index=index, data=data, output=output,
    )))


@app.command("music-export")
def music_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to .xmi XMIDI file")],
    output: Annotated[
        Optional[str], typer.Option("-o", "--output", help="Output directory"),
    ] = None,
) -> None:
    """Convert an XMIDI (.xmi) file to standard MIDI."""
    raise SystemExit(cmd_music_export(SimpleNamespace(file=file, output=output)))


@app.command("music-batch")
def music_batch_cmd(
    directory: Annotated[str, typer.Argument(help="Directory containing .xmi files")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory (default: <dir>/midi/)"),
    ] = None,
) -> None:
    """Batch-convert all XMIDI .xmi files to standard MIDI."""
    raise SystemExit(cmd_music_batch(SimpleNamespace(
        directory=directory, output=output,
    )))


@app.command("setup")
def setup_cmd() -> None:
    """Interactive first-time setup wizard \u2014 creates titan.toml."""
    raise SystemExit(cmd_setup(SimpleNamespace(config=None)))


@app.command("config")
def config_cmd(
    edit: Annotated[
        bool, typer.Option("--edit", help="Open titan.toml in the system default editor"),
    ] = False,
) -> None:
    """Show or edit the active titan.toml settings."""
    import titan._config as _config_mod
    raise SystemExit(cmd_config(SimpleNamespace(
        config=_config_mod.explicit_config_path, edit=edit,
    )))


# ============================================================================
# Sub-app registration
# ============================================================================

from titan.u8.cli import u8_app  # noqa: E402
from titan.u7.cli import u7_app  # noqa: E402
from titan.dialogue.cli import dialogue_app  # noqa: E402

app.add_typer(u8_app)
app.add_typer(u7_app)
app.add_typer(dialogue_app)


# ============================================================================
# Deprecated backward-compat aliases for old root-level U8 commands
#
# These are hidden (not shown in ``titan --help``) and marked deprecated.
# When invoked, Typer prints a deprecation warning automatically.
# They reuse the *exact same* Typer-annotated wrapper functions from
# titan.u8.cli so no parameter definitions are duplicated.
# ============================================================================

from titan.u8 import cli as _u8_cli  # noqa: E402

_U8_COMPAT_COMMANDS: list[tuple[str, object]] = [
    ("palette-export",  _u8_cli.palette_export_cmd),
    ("shape-export",    _u8_cli.shape_export_cmd),
    ("shape-batch",     _u8_cli.shape_batch_cmd),
    ("shape-import",    _u8_cli.shape_import_cmd),
    ("sound-export",    _u8_cli.sound_export_cmd),
    ("sound-batch",     _u8_cli.sound_batch_cmd),
    ("credits-decrypt", _u8_cli.credits_decrypt_cmd),
    ("xformpal-export", _u8_cli.xformpal_export_cmd),
    ("typeflag-dump",   _u8_cli.typeflag_dump_cmd),
    ("gumpinfo-dump",   _u8_cli.gumpinfo_dump_cmd),
    ("save-list",       _u8_cli.save_list_cmd),
    ("save-extract",    _u8_cli.save_extract_cmd),
    ("unkcoff-dump",    _u8_cli.unkcoff_dump_cmd),
    ("map-render",      _u8_cli.map_render_cmd),
    ("map-render-all",  _u8_cli.map_render_all_cmd),
    ("map-sample",      _u8_cli.map_sample_cmd),
    ("map-sample-all",  _u8_cli.map_sample_all_cmd),
]

for _compat_name, _compat_fn in _U8_COMPAT_COMMANDS:
    app.command(_compat_name, hidden=True, deprecated=True)(_compat_fn)


# ============================================================================
# CLI ENTRY POINT
# ============================================================================


def main() -> int:
    """CLI entry point."""
    app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
