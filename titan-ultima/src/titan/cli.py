"""
TITAN command-line interface.

Root commands (game-agnostic):
    flex-info, flex-list, flex-extract, flex-create, flex-update,
    music-export, music-batch, setup, config.

Sub-apps:
    uw1 — Ultima Underworld I commands (texture archives)
    uw2 — Ultima Underworld II commands (palette, GR shapes, object metadata)
    u8  — Ultima 8: Pagan commands (shape, map, sound, save, etc.)
    u7  — Ultima 7: The Black Gate / Serpent Isle commands
    u6  — Ultima 6: The False Prophet commands (tile, map, library, data)
    u9  — Ultima 9: Ascension commands (FLX archive, sound, model data)
    uo  — Ultima Online Classic Client commands (2D asset/data export)

Old root-level U8 commands (e.g. ``titan shape-export``) are still
accepted as hidden deprecated aliases that forward to ``titan u8 …``.

Entry point (pyproject.toml)::

    [project.scripts]
    titan = "titan.cli:main"
"""

from __future__ import annotations

__all__ = ["app", "main"]

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan._version import TITAN_VERSION
from titan import _wizard_ui as ui
from titan._config import (
    find_config,
    load_config,
    resolve_config_path,
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
        "Work with Ultima file formats (UW1, UW2, U8, U7, U6, U3 NES, U9, UO)."
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
        row = raw_header[row_start : row_start + 16]
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
        mf.write(f"# Format: {archive.archive_format}\n")
        if archive._source_header is not None:
            mf.write(f"# Header: {archive._source_header.hex()}\n")
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

    requested_format = getattr(args, "archive_format", None)
    if requested_format is None and not os.path.isfile(manifest_path):
        requested_format = (
            "u7" if output_file and Path(output_file).suffix.lower() == ".vga" else "u8"
        )
    if requested_format and requested_format != archive.archive_format:
        archive.archive_format = requested_format
        archive._source_header = None
        archive.unknown_field = 0xCC if requested_format == "u7" else 1

    if output_file is None:
        # Default output name: directory name + .flx
        output_file = Path(source_dir).stem + ".flx"

    archive.save(output_file)
    return 0


def _create_from_manifest(
    source_dir: str, manifest_path: str, comment_override: str = ""
) -> FlexArchive:
    """Reconstruct a Flex archive guided by a _manifest.txt file."""
    archive = FlexArchive()

    original_comment = ""
    unknown_field = 1
    format_recorded = False
    entries: list[tuple[int, int, str]] = []  # (index, size, filename)

    with open(manifest_path, "r") as mf:
        for line in mf:
            line = line.strip()
            if line.startswith("# Comment:"):
                original_comment = line[len("# Comment:") :].strip()
            elif line.startswith("# Unknown field:"):
                try:
                    unknown_field = int(line.split(":")[-1].strip(), 0)
                except ValueError:
                    pass
            elif line.startswith("# Format:"):
                format_recorded = True
                archive_format = line.split(":", 1)[1].strip()
                if archive_format not in {"u7", "u8"}:
                    raise ValueError(
                        f"Unsupported Flex manifest format: {archive_format}"
                    )
                archive.archive_format = "u7" if archive_format == "u7" else "u8"
            elif line.startswith("# Header:"):
                format_recorded = True
                header = bytes.fromhex(line.split(":", 1)[1].strip())
                if len(header) != FLEX_HEADER_SIZE or not FlexArchive._validate_header(
                    header
                ):
                    raise ValueError("Invalid Flex manifest header")
                archive._source_header = header
                archive.archive_format = (
                    "u7"
                    if int.from_bytes(header[0x50:0x54], "little") == 0xFFFF1A00
                    else "u8"
                )
            elif line.startswith("# Source:"):
                # Legacy manifests lacked a format field. VGA is a U7 archive;
                # new manifests also identify ambiguous .FLX inputs explicitly.
                if Path(line.split(":", 1)[1].strip()).suffix.lower() == ".vga":
                    archive.archive_format = "u7"
            elif line.startswith("#") or not line:
                continue
            else:
                parts = line.split("|")
                if len(parts) >= 3:
                    idx = int(parts[0])
                    size = int(parts[1])
                    fname = parts[2].strip()
                    entries.append((idx, size, fname))

    if not format_recorded and (
        unknown_field == 0xCC or (unknown_field & 0xFFFFFF00) == 0xCC00
    ):
        archive.archive_format = "u7"

    archive.comment = comment_override or (
        FlexArchive._decode_comment(archive._source_header)
        if archive._source_header is not None
        else original_comment or f"Rebuilt by TITAN v{TITAN_VERSION}"
    )
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
            print(f"  WARNING: Missing file for record {idx}: {fpath}", file=sys.stderr)
            continue
        data = Path(fpath).read_bytes()
        if len(data) != expected_size:
            print(
                f"  WARNING: Record {idx} size mismatch "
                f"(expected {expected_size}, got {len(data)})",
                file=sys.stderr,
            )
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
        print(f"ERROR: Replacement data file not found: {data_path}", file=sys.stderr)
        return 1

    index = args.index
    if index < 0:
        print(f"ERROR: Invalid index: {index}", file=sys.stderr)
        return 1

    try:
        archive = FlexArchive.from_file(flex_path, strict=True)
    except (OSError, ValueError) as error:
        print(f"ERROR: Cannot update Flex archive: {error}", file=sys.stderr)
        return 1

    if index >= len(archive.records):
        print(
            f"ERROR: Index {index} out of range "
            f"(archive has {len(archive.records)} records)",
            file=sys.stderr,
        )
        return 1

    old_size = len(archive.records[index]) if archive.records[index] else 0
    new_data = Path(data_path).read_bytes()
    archive.records[index] = new_data

    output_path = args.output or flex_path
    archive.save(output_path)

    print(
        f"Flex updated: record {index} replaced "
        f"({old_size:,} -> {len(new_data):,} bytes) -> {output_path}"
    )
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

    xmi_files = sorted(f for f in os.listdir(srcdir) if f.lower().endswith(".xmi"))
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

        outdir_display = outdir.rstrip("/\\") + "/"
        print(
            f"Batch convert complete: {converted} MIDIs created, "
            f"{failed} skipped -> {outdir_display}"
        )
    return 0


# ============================================================================
# CONFIG COMMANDS — setup wizard + inspector
# ============================================================================


def cmd_config(args: SimpleNamespace) -> int:
    """Show the active titan.toml configuration (or open it for editing)."""
    import titan._config as _config_mod

    explicit = getattr(args, "config", None) or _config_mod.explicit_config_path
    path = Path(explicit).expanduser() if explicit else find_config()

    if getattr(args, "edit", False):
        if path is None:
            print("No titan.toml found. Run `titan setup` to create one.")
            return 1
        editor = (
            os.getenv("VISUAL")
            or os.getenv("EDITOR")
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

    def _print_kv_section(
        title: str,
        section: dict,
        check_exists: bool = False,
        base: Optional[str] = None,
        u7_resources: bool = False,
    ) -> None:
        if not section:
            return
        print()
        print(title)
        for k, v in section.items():
            if check_exists:
                from titan.u7.install import existing_path

                value_path = resolve_config_path(v, base)
                if value_path is not None:
                    value_path = existing_path(value_path)
                exists = value_path.exists() if value_path is not None else False
                flag = "OK" if exists else "NOT FOUND"
                if (
                    u7_resources
                    and value_path is not None
                    and k in {"shapes", "palette", "text"}
                ):
                    from titan.u7.install import check_resource

                    flag = check_resource(k, value_path)
                resolved = f" -> {value_path.absolute()}" if value_path else ""
                print(f"  {k:<12} = {v!r}  [{flag}]{resolved}")
            else:
                print(f"  {k:<12} = {v!r}")

    print(f"Active config: {path.absolute()}")

    u8 = config.get("u8", {})
    uw2 = config.get("uw2", {})
    u7bg = config.get("u7bg", {})
    u7si = config.get("u7si", {})
    uo = config.get("uo", {})
    exult = config.get("exult", {})
    if any((u8, uw2, u7bg, u7si, uo, exult)):
        _print_kv_section("[u8.game]", u8.get("game", {}))
        _print_kv_section("[u8.paths]", u8.get("paths", {}), check_exists=True)
        _print_kv_section("[uw2.game]", uw2.get("game", {}), check_exists=True)
        _print_kv_section("[u7bg.game]", u7bg.get("game", {}))
        bg_base = u7bg.get("game", {}).get("base")
        _print_kv_section(
            "[u7bg.paths]",
            u7bg.get("paths", {}),
            check_exists=True,
            base=bg_base,
            u7_resources=True,
        )
        for mod_name, mod in u7bg.get("mods", {}).items():
            _print_kv_section(
                f'[u7bg.mods."{mod_name}".paths]',
                mod.get("paths", {}),
                check_exists=True,
                base=bg_base,
            )
        _print_kv_section("[u7si.game]", u7si.get("game", {}))
        si_base = u7si.get("game", {}).get("base")
        _print_kv_section(
            "[u7si.paths]",
            u7si.get("paths", {}),
            check_exists=True,
            base=si_base,
            u7_resources=True,
        )
        for mod_name, mod in u7si.get("mods", {}).items():
            _print_kv_section(
                f'[u7si.mods."{mod_name}".paths]',
                mod.get("paths", {}),
                check_exists=True,
                base=si_base,
            )
        _print_kv_section("[uo.game]", uo.get("game", {}), check_exists=True)
        _print_kv_section("[exult.paths]", exult.get("paths", {}), check_exists=True)
    else:
        game = config.get("game", {})
        paths = config.get("paths", {})
        _print_kv_section("[game]", game)
        _print_kv_section("[paths]  (after base expansion)", paths, check_exists=True)
    return 0


def cmd_setup(args: SimpleNamespace) -> int:
    """Interactive first-time setup wizard \u2014 creates titan.toml."""
    import titan._config as _config_mod
    from titan.u7.install import (
        U7Installation,
        exult_game_paths,
        inspect_install,
        install_roots,
        install_game,
    )

    explicit = getattr(args, "config", None) or _config_mod.explicit_config_path
    toml_path = Path(explicit).expanduser() if explicit else Path.cwd() / "titan.toml"
    existing_config = load_config(str(toml_path)) if toml_path.is_file() else {}
    existing_u8_game = existing_config.get("game", {})
    print("TITAN Setup Wizard")
    print("=" * 55)
    print("This will create titan.toml for Ultima 8, Ultima 7, and UO installs.\n")
    if toml_path.exists():
        print(f"Existing config: {toml_path}")
        print("Setup keeps custom settings and adds missing entries.")
        print("Verified U7 base corrections will be shown before saving.\n")

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
        return any(
            token in lowered for token in ("ultima 8", "ultima8", "viii", "pagan")
        )

    def _is_u7_folder_name(name: str) -> bool:
        lowered = name.lower()
        if "ultima" not in lowered:
            return False
        return bool(re.search(r"ultima\s*vii(?!i)", lowered)) or any(
            token in lowered
            for token in ("ultima 7", "ultima7", "black gate", "serpent")
        )

    def _looks_like_uo_root(path: Path) -> bool:
        return any(
            (path / name).is_file()
            for name in (
                "artLegacyMUL.uop",
                "gumpartLegacyMUL.uop",
                "tiledata.mul",
                "hues.mul",
            )
        )

    # Windows: GOG Galaxy client (most common current install)
    for drive in "CDEFG":
        _add_candidate(
            Path(f"{drive}:\\Program Files (x86)\\GOG Galaxy\\Games\\Ultima 8")
        )
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
            for folder in root.iterdir():
                if folder.is_dir() and _is_u8_folder_name(folder.name):
                    _add_candidate(folder)
        except PermissionError:
            continue

    # U7 auto-detection candidates.
    u7_candidates: list[Path] = []

    def _add_u7_candidate(path: Path) -> None:
        if path not in u7_candidates:
            u7_candidates.append(path)

    # Existing settings and Exult support nonstandard install locations too.
    exult_hints: dict[Path, str] = {}
    exult_statics: dict[Path, Path] = {}
    for game, section_key in (("BG", "u7bg"), ("SI", "u7si")):
        previous_base = existing_config.get(section_key, {}).get("game", {}).get("base")
        if previous_base:
            configured_base = Path(previous_base).expanduser().resolve()
            exult_hints[configured_base] = game
            _add_u7_candidate(configured_base)
        exult_paths = exult_game_paths(game)
        if "base" in exult_paths:
            exult_hints[exult_paths["base"].absolute()] = game
            if "static" in exult_paths:
                exult_statics[exult_paths["base"].absolute()] = exult_paths["static"]
            _add_u7_candidate(exult_paths["base"])

    for drive in "CDEFG":
        for path in [
            Path(f"{drive}:\\GOG Games\\Ultima VII"),
            Path(f"{drive}:\\GOG Games\\Ultima VII - Complete"),
            Path(f"{drive}:\\Ultima\\ultima7bg"),
            Path(f"{drive}:\\Ultima\\ultima7si"),
            Path(f"{drive}:\\Ultima\\ultima7bg_no_exult"),
            Path(f"{drive}:\\Ultima\\ultima7si_no_exult"),
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
            for folder in root.iterdir():
                if folder.is_dir() and _is_u7_folder_name(folder.name):
                    _add_u7_candidate(folder)
        except PermissionError:
            continue

    # UO auto-detection candidates.
    uo_candidates: list[Path] = []

    def _add_uo_candidate(path: Path) -> None:
        if path not in uo_candidates:
            uo_candidates.append(path)

    for drive in "CDEFG":
        for path in [
            Path(
                f"{drive}:\\Program Files (x86)\\Electronic Arts\\Ultima Online Classic"
            ),
            Path(f"{drive}:\\Ultima\\UltimaOnlineClassicClient"),
            Path(f"{drive}:\\Ultima Online Classic"),
        ]:
            _add_uo_candidate(path)

    detected_base: Optional[Path] = None
    detected_lang = "ENGLISH"
    detected_u8: list[tuple[Path, str]] = []

    print("Searching for Ultima 8 installation...")
    for candidate_base in candidates:
        if not candidate_base.is_dir():
            continue
        if (candidate_base / "FIXED.DAT").is_file():
            detected_u8.append((candidate_base, ""))
            continue
        try:
            for folder in candidate_base.iterdir():
                if not folder.is_dir():
                    continue
                static = folder / "STATIC"
                if static.exists() and (static / "FIXED.DAT").exists():
                    detected_u8.append((candidate_base, folder.name))
                    break
        except PermissionError:
            continue

    if detected_u8:
        detected_base, detected_lang = detected_u8[0]
        for found_base, lang_name in detected_u8:
            print(f"  Found: {found_base}  (language: {lang_name})")

    if not detected_base:
        print("  No standard installation found.")

    default_base = existing_u8_game.get("base") or (
        str(detected_base) if detected_base else str(Path.cwd())
    )
    base_input = ui.path(
        f"\nGame base path [{default_base}]: ", str(default_base)
    ).strip()
    base = base_input or default_base

    default_lang = existing_u8_game.get(
        "language", detected_lang if detected_base else ""
    )
    lang_prompt = (
        f"Language folder (ENGLISH/FRENCH/GERMAN) "
        f"[{default_lang or 'leave empty for flat mode'}]: "
    )
    lang = ui.text(lang_prompt, default_lang).strip()
    if lang == "":
        lang = default_lang  # keep detected; empty string IS flat mode only if nothing detected

    # -- U7 install detection (BG + SI) ---------------------------
    detected_u7bg: Optional[Path] = None
    detected_u7si: Optional[Path] = None
    inspected_u7: dict[Path, U7Installation] = {}
    print("\nSearching for Ultima 7 installations...")
    for u7_base in u7_candidates:
        discovered_roots = install_roots(u7_base)
        if u7_base.absolute() in exult_statics and not discovered_roots:
            discovered_roots = [u7_base]
        for root in discovered_roots:
            root = root.absolute()
            if root in inspected_u7:
                continue
            installation = inspect_install(
                root, exult_hints.get(root), static=exult_statics.get(root)
            )
            inspected_u7[root] = installation
            label = "Serpent Isle" if installation.game == "SI" else "Black Gate"
            if not installation.valid:
                print(f"  Incomplete or damaged {label} installation: {root}")
                for key, status in installation.checks.items():
                    if status != "OK":
                        print(f"    {installation.paths[key]} [{status}]")
                continue
            if installation.game == "SI" and detected_u7si is None:
                detected_u7si = root
                print(f"  Verified Serpent Isle: {root}")
            elif installation.game == "BG" and detected_u7bg is None:
                detected_u7bg = root
                print(f"  Verified Black Gate:   {root}")

    def _u7_default(section_key: str, detected: Optional[Path]) -> str:
        previous = existing_config.get(section_key, {}).get("game", {}).get("base")
        # Keep custom selections; normalize nested roots after the user's prompt.
        return str(previous or detected or "")

    bg_default = _u7_default("u7bg", detected_u7bg)
    si_default = _u7_default("u7si", detected_u7si)

    u7bg_input = ui.path(
        f"Ultima VII Black Gate base [{bg_default or 'optional'}]: ", bg_default
    ).strip()
    u7si_input = ui.path(
        f"Ultima VII Serpent Isle base [{si_default or 'optional'}]: ", si_default
    ).strip()

    u7bg_base = (u7bg_input or bg_default).replace("\\", "/")
    u7si_base = (u7si_input or si_default).replace("\\", "/")

    def _selected_u7(value: str, game: str) -> Optional[U7Installation]:
        if not value:
            return None
        candidate = Path(value).expanduser().absolute()
        roots = install_roots(candidate)
        matching = [root for root in roots if inspect_game(root) == game]
        root = next(iter(matching or roots), candidate)
        # Selecting a base explicitly chooses the game even with a custom name.
        return inspect_install(root, game, static=exult_statics.get(root))

    def inspect_game(root: Path) -> str:
        return exult_hints.get(root.absolute()) or install_game(root)

    selected_bg = _selected_u7(u7bg_base, "BG")
    selected_si = _selected_u7(u7si_base, "SI")
    if selected_bg:
        u7bg_base = selected_bg.root.as_posix()
    if selected_si:
        u7si_base = selected_si.root.as_posix()

    def _relative_u7_paths(selected: Optional[U7Installation]) -> dict[str, str]:
        if selected is None:
            return {}
        return {
            key: path.relative_to(selected.root).as_posix()
            if path.is_relative_to(selected.root)
            else path.as_posix()
            for key, path in selected.paths.items()
        }

    bg_paths = _relative_u7_paths(selected_bg)
    si_paths = _relative_u7_paths(selected_si)
    setup_updates: dict = {}
    for section_key, selected in (("u7bg", selected_bg), ("u7si", selected_si)):
        previous = existing_config.get(section_key, {}).get("game", {}).get("base")
        if (
            selected
            and previous
            and Path(str(previous)).expanduser().resolve() != selected.root.resolve()
        ):
            print(
                f"  Proposed {section_key} base correction: {previous} -> {selected.root}"
            )
            setup_updates[section_key] = {"game": {"base": selected.root.as_posix()}}
            # Preserve the meaning of custom relative paths when changing base.
            previous_section = existing_config[section_key]
            for key, value in previous_section.get("paths", {}).items():
                old_path = resolve_config_path(value, previous)
                if not value or Path(str(value)).expanduser().is_absolute():
                    continue
                standard = str(value).replace("\\", "/").upper().rstrip("/") in {
                    "STATIC",
                    "STATIC/SHAPES.VGA",
                    "STATIC/PALETTES.FLX",
                    "STATIC/TEXT.FLX",
                    "GAMEDAT",
                }
                if old_path and (old_path.exists() or not standard):
                    setup_updates[section_key].setdefault("paths", {})[key] = (
                        old_path.absolute().as_posix()
                    )
                    print(f"    Preserve custom {key}: {old_path.absolute()}")
            for mod_name, mod_config in previous_section.get("mods", {}).items():
                preserved = {}
                for key, value in mod_config.get("paths", {}).items():
                    if value and not Path(str(value)).expanduser().is_absolute():
                        preserved_path = resolve_config_path(value, previous)
                        if preserved_path is not None:
                            preserved[key] = preserved_path.absolute().as_posix()
                if preserved:
                    setup_updates[section_key].setdefault("mods", {})[mod_name] = {
                        "paths": preserved
                    }
                    print(f"    Preserve custom paths for mod: {mod_name}")

    # -- UO install detection -------------------------------------
    detected_uo: Optional[Path] = None
    print("\nSearching for Ultima Online Classic Client installation...")
    for uo_candidate in uo_candidates:
        if uo_candidate.exists() and _looks_like_uo_root(uo_candidate):
            detected_uo = uo_candidate
            print(f"  Found UO Classic Client: {uo_candidate}")
            break
    if detected_uo is None:
        print("  Not found in standard locations.")

    uo_default = str(detected_uo) if detected_uo else ""
    uo_input = ui.path(
        f"Ultima Online Classic Client base [{uo_default or 'optional'}]: ", uo_default
    ).strip()
    uo_base = (uo_input or uo_default).replace("\\", "/")

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
        mac_save = (
            Path.home() / "Library" / "Application Support" / "Pentagram" / "u8-save"
        )
        if (mac_save / "U8SAVE.000").exists():
            engine_save_file = mac_save / "U8SAVE.000"

    nonfixed_value = "U8SAVE.000"
    if engine_save_file:
        print(f"\nThird-party engine save detected: {engine_save_file}")
        ans = ui.choice(
            "Use this save instead of game-folder saves? [Y/n] ",
            ["y", "Y", "n", "N"],
            "Y",
        ).lower()
        if ans not in ("n", "no"):
            nonfixed_value = str(engine_save_file).replace("\\", "/")

    # -- Detection summary + confirmation -------------------------
    u8_static_detected = (Path(base) / lang / "STATIC") if lang else Path(base)
    u8_usecode_detected = (
        (Path(base) / lang / "USECODE" / "EUSECODE.FLX")
        if lang
        else (Path(base) / "USECODE" / "EUSECODE.FLX")
    )
    u7bg_static_detected = selected_bg.paths["static"] if selected_bg else None
    u7si_static_detected = selected_si.paths["static"] if selected_si else None
    exult_profile = (
        Path(os.getenv("LOCALAPPDATA", "")) / "Exult"
        if os.getenv("LOCALAPPDATA")
        else None
    )
    if exult_profile is not None and not exult_profile.is_dir():
        exult_profile = None

    def _has_runtime_npc(path: Path) -> bool:
        return (path / "npc.dat").is_file()

    def _preferred_u7_gamedat(base_value: str, slug: str) -> str:
        candidates: list[Path] = []
        if exult_profile is not None:
            candidates.append(exult_profile / slug / "gamedat")
        if base_value:
            candidates.append(Path(base_value) / "gamedat")
            candidates.append(Path(base_value) / "GAMEDAT")
        for candidate in candidates:
            if _has_runtime_npc(candidate):
                return str(candidate).replace("\\", "/")
        return "gamedat/"

    def _discover_u7_mod_sources(base_value: str, slug: str) -> list[dict[str, str]]:
        if not base_value:
            return []
        install_mods = Path(base_value) / "mods"
        if not install_mods.is_dir():
            return []

        def _best_saves_dir(runtime_root: Optional[Path]) -> Optional[Path]:
            if runtime_root is None or not runtime_root.is_dir():
                return None
            counts: dict[Path, int] = {}
            for save_file in runtime_root.rglob("*.sav"):
                if save_file.is_file():
                    counts[save_file.parent] = counts.get(save_file.parent, 0) + 1
            if not counts:
                return None
            return sorted(
                counts.items(),
                key=lambda item: (-item[1], len(str(item[0])), str(item[0]).lower()),
            )[0][0]

        sources: list[dict[str, str]] = []
        for mod_dir in sorted(p for p in install_mods.iterdir() if p.is_dir()):
            item: dict[str, str] = {"name": mod_dir.name}
            runtime_root = (
                exult_profile / slug / "mods" / mod_dir.name
                if exult_profile is not None
                else None
            )
            if runtime_root is not None and runtime_root.is_dir():
                item["root"] = str(runtime_root).replace("\\", "/")
            runtime_gamedat = (
                runtime_root / "gamedat" if runtime_root is not None else None
            )
            install_gamedat = mod_dir / "gamedat"
            if runtime_gamedat is not None and _has_runtime_npc(runtime_gamedat):
                item["gamedat"] = str(runtime_gamedat).replace("\\", "/")
            elif _has_runtime_npc(install_gamedat):
                item["gamedat"] = str(install_gamedat).replace("\\", "/")
            saves_dir = _best_saves_dir(runtime_root)
            if saves_dir is not None:
                item["saves"] = str(saves_dir).replace("\\", "/")
            for archive in (
                mod_dir / "patch" / "initgame.dat",
                mod_dir / "data" / "initgame.dat",
            ):
                if archive.is_file():
                    item["archive"] = str(archive).replace("\\", "/")
                    break
            if len(item) > 1:
                sources.append(item)
        return sources

    u7bg_gamedat = _preferred_u7_gamedat(u7bg_base, "blackgate") if u7bg_base else ""
    u7si_gamedat = _preferred_u7_gamedat(u7si_base, "serpentisle") if u7si_base else ""
    u7bg_mod_sources = _discover_u7_mod_sources(u7bg_base, "blackgate")
    u7si_mod_sources = _discover_u7_mod_sources(u7si_base, "serpentisle")

    # -- Exult install detection (for exult_bg.flx / exult_si.flx) --------
    def _find_exult_flx(flx_name: str) -> Optional[Path]:
        candidates: list[Path] = []
        for drive in "CD":
            for layout in (
                Path(f"{drive}:\\Program Files\\Exult\\data"),
                Path(f"{drive}:\\Program Files (x86)\\Exult\\data"),
                Path(f"{drive}:\\Program Files\\Exult"),
                Path(f"{drive}:\\Program Files (x86)\\Exult"),
            ):
                candidates.append(layout / flx_name)
        for share in (
            Path("/usr/share/exult"),
            Path("/usr/local/share/exult"),
            Path("/opt/exult"),
        ):
            candidates.append(share / flx_name)
        return next((p for p in candidates if p.exists()), None)

    detected_exult_bg_flx = _find_exult_flx("exult_bg.flx")
    detected_exult_si_flx = _find_exult_flx("exult_si.flx")

    print("\nSearching for Exult installation (exult_bg.flx / exult_si.flx)...")
    if detected_exult_bg_flx or detected_exult_si_flx:
        if detected_exult_bg_flx:
            print(f"  Found BG data: {detected_exult_bg_flx}")
        if detected_exult_si_flx:
            print(f"  Found SI data: {detected_exult_si_flx}")
    else:
        print("  Not found in standard locations.")

    exult_bg_flx_default = str(detected_exult_bg_flx) if detected_exult_bg_flx else ""
    exult_si_flx_default = str(detected_exult_si_flx) if detected_exult_si_flx else ""

    exult_bg_flx_input = ui.path(
        f"Exult BG FLX path [{exult_bg_flx_default or 'optional'}]: ",
        exult_bg_flx_default,
    ).strip()
    exult_si_flx_input = ui.path(
        f"Exult SI FLX path [{exult_si_flx_default or 'optional'}]: ",
        exult_si_flx_default,
    ).strip()

    exult_bg_flx = (exult_bg_flx_input or exult_bg_flx_default).replace("\\", "/")
    exult_si_flx = (exult_si_flx_input or exult_si_flx_default).replace("\\", "/")

    print("\nDetected folders to write to titan.toml:")
    print(f"  U8 base:      {base}")
    print(f"  U8 language:  {lang or '(flat mode)'}")
    print(f"  U8 STATIC:    {u8_static_detected}")
    print(f"  U8 USECODE:   {u8_usecode_detected}")
    print(f"  U7 BG base:   {u7bg_base or '(empty)'}")
    print(f"  U7 BG STATIC: {u7bg_static_detected or '(empty)'}")
    print(f"  U7 BG GAMEDAT:{u7bg_gamedat or '(empty)'}")
    print(f"  U7 SI base:   {u7si_base or '(empty)'}")
    print(f"  U7 SI STATIC: {u7si_static_detected or '(empty)'}")
    print(f"  U7 SI GAMEDAT:{u7si_gamedat or '(empty)'}")
    print(f"  UO base:      {uo_base or '(empty)'}")
    print(f"  Exult BG FLX: {exult_bg_flx or '(empty)'}")
    print(f"  Exult SI FLX: {exult_si_flx or '(empty)'}")
    for label, selected in (("BG", selected_bg), ("SI", selected_si)):
        if selected:
            section_key = "u7bg" if label == "BG" else "u7si"
            effective_paths = {
                **existing_config.get(section_key, {}).get("paths", {}),
                **setup_updates.get(section_key, {}).get("paths", {}),
            }
            resource_paths = {
                key: resolved_resource
                for key in ("shapes", "palette", "text")
                if (
                    resolved_resource := resolve_config_path(
                        effective_paths.get(key), selected.root
                    )
                )
                is not None
            }
            verified = inspect_install(
                selected.root,
                label,
                static=resolve_config_path(effective_paths.get("static"), selected.root)
                or selected.paths["static"],
                resources=resource_paths,
            )
            for key, status in verified.checks.items():
                print(f"  U7 {label} {key}: {verified.paths[key]} [{status}]")
    for item in u7bg_mod_sources:
        print(
            f"  U7 BG mod:    {item['name']} "
            f"root={item.get('root', '(none)')} "
            f"gamedat={item.get('gamedat', '(none)')} "
            f"saves={item.get('saves', '(none)')} "
            f"archive={item.get('archive', '(none)')}"
        )
    for item in u7si_mod_sources:
        print(
            f"  U7 SI mod:    {item['name']} "
            f"root={item.get('root', '(none)')} "
            f"gamedat={item.get('gamedat', '(none)')} "
            f"saves={item.get('saves', '(none)')} "
            f"archive={item.get('archive', '(none)')}"
        )

    confirm = ui.choice(
        "Are these paths correct? [Y/n] ", ["y", "Y", "n", "N"], "Y"
    ).lower()

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
        uo_base = ""
        u7bg_gamedat = ""
        u7si_gamedat = ""
        u7bg_mod_sources = []
        u7si_mod_sources = []
        setup_updates = {}

        manual_u8_static = (
            ui.path("U8 STATIC path [optional]: ").strip().replace("\\", "/")
        )
        manual_u8_usecode = (
            ui.path("U8 EUSECODE.FLX path [optional]: ").strip().replace("\\", "/")
        )
        manual_u7bg_static = (
            ui.path("U7 BG STATIC path [optional]: ").strip().replace("\\", "/")
        )
        manual_u7si_static = (
            ui.path("U7 SI STATIC path [optional]: ").strip().replace("\\", "/")
        )
        uo_base = (
            ui.path("UO Classic Client base [optional]: ").strip().replace("\\", "/")
        )
        exult_bg_flx = (
            ui.path("Exult BG FLX path [optional]: ").strip().replace("\\", "/")
        )
        exult_si_flx = (
            ui.path("Exult SI FLX path [optional]: ").strip().replace("\\", "/")
        )

        for section_key, game, value in (
            ("u7bg", "BG", manual_u7bg_static),
            ("u7si", "SI", manual_u7si_static),
        ):
            if not value:
                continue
            static_path = Path(value).expanduser().absolute()
            selected = inspect_install(static_path.parent, game, static=static_path)
            for key, status in selected.checks.items():
                print(f"  U7 {game} {key}: {selected.paths[key]} [{status}]")
            setup_updates[section_key] = {
                "game": {"base": selected.root.as_posix()},
                "paths": {key: path.as_posix() for key, path in selected.paths.items()},
            }
        if ui.choice(
            "Save these manually selected paths? [Y/n] ", ["y", "Y", "n", "N"], "Y"
        ).lower() in (
            "n",
            "no",
        ):
            print("Cancelled; configuration was not changed.")
            return 0

    # -- Build and write titan.toml --------------------------------
    base_toml = base.replace("\\", "/")
    nonfixed_is_abs = Path(nonfixed_value).is_absolute()

    u8_static_manual_path = Path(manual_u8_static) if manual_u8_static else None
    if manual_u8_usecode:
        u8_usecode_path = manual_u8_usecode
    elif u8_static_manual_path is not None:
        u8_usecode_path = str(
            u8_static_manual_path.parent / "USECODE" / "EUSECODE.FLX"
        ).replace("\\", "/")
    else:
        u8_usecode_path = str(u8_usecode_detected).replace("\\", "/")

    if u8_static_manual_path is not None:
        u8_paths_fixed = str(u8_static_manual_path / "FIXED.DAT").replace("\\", "/")
        u8_paths_palette = str(u8_static_manual_path / "U8PAL.PAL").replace("\\", "/")
        u8_paths_typeflag = str(u8_static_manual_path / "TYPEFLAG.DAT").replace(
            "\\", "/"
        )
        u8_paths_gumpage = str(u8_static_manual_path / "GUMPAGE.DAT").replace("\\", "/")
        u8_paths_xformpal = str(u8_static_manual_path / "XFORMPAL.DAT").replace(
            "\\", "/"
        )
        u8_paths_ecredits = str(u8_static_manual_path / "ECREDITS.DAT").replace(
            "\\", "/"
        )
        u8_paths_quotes = str(u8_static_manual_path / "QUOTES.DAT").replace("\\", "/")
        u8_paths_shapes_flx = str(u8_static_manual_path / "U8SHAPES.FLX").replace(
            "\\", "/"
        )
        u8_paths_fonts_flx = str(u8_static_manual_path / "U8FONTS.FLX").replace(
            "\\", "/"
        )
        u8_paths_gumps_flx = str(u8_static_manual_path / "U8GUMPS.FLX").replace(
            "\\", "/"
        )
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
        static_norm = Path(static_path).expanduser().absolute().as_posix()
        static_p = Path(static_norm)
        base_guess = static_p.parent.as_posix()
        gamedat_guess = str(static_p.parent / "gamedat").replace("\\", "/")
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
            f'text     = "{static_norm}/TEXT.FLX"',
            f'gamedat  = "{gamedat_guess}"',
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
            f'static   = "{bg_paths["static"]}"',
            f'shapes   = "{bg_paths["shapes"]}"',
            f'palette  = "{bg_paths["palette"]}"',
            f'text     = "{bg_paths["text"]}"',
            f'gamedat  = "{u7bg_gamedat}"',
        ]
        for item in u7bg_mod_sources:
            lines += [
                "",
                f'[u7bg.mods."{item["name"]}".paths]',
            ]
            if "gamedat" in item:
                lines.append(f'gamedat  = "{item["gamedat"]}"')
            if "saves" in item:
                lines.append(f'saves    = "{item["saves"]}"')
            if "root" in item:
                lines.append(f'root     = "{item["root"]}"')
            if "archive" in item:
                lines.append(f'archive  = "{item["archive"]}"')

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
            f'static   = "{si_paths["static"]}"',
            f'shapes   = "{si_paths["shapes"]}"',
            f'palette  = "{si_paths["palette"]}"',
            f'text     = "{si_paths["text"]}"',
            f'gamedat  = "{u7si_gamedat}"',
        ]
        for item in u7si_mod_sources:
            lines += [
                "",
                f'[u7si.mods."{item["name"]}".paths]',
            ]
            if "gamedat" in item:
                lines.append(f'gamedat  = "{item["gamedat"]}"')
            if "saves" in item:
                lines.append(f'saves    = "{item["saves"]}"')
            if "root" in item:
                lines.append(f'root     = "{item["root"]}"')
            if "archive" in item:
                lines.append(f'archive  = "{item["archive"]}"')

    if uo_base:
        lines += [
            "",
            "[uo.game]",
            f'base     = "{uo_base}"',
        ]

    if exult_bg_flx or exult_si_flx:
        lines += ["", "[exult.paths]"]
        if exult_bg_flx:
            lines.append(f'bg_flx   = "{exult_bg_flx}"')
        if exult_si_flx:
            lines.append(f'si_flx   = "{exult_si_flx}"')

    from titan._setup_config import write_setup_config

    try:
        backup = write_setup_config(
            toml_path, "\n".join(lines) + "\n", updates=setup_updates
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: Could not write setup config: {exc}", file=sys.stderr)
        return 1
    if backup is not None:
        print(f"\n  Updated: {toml_path.absolute()} (custom settings kept)")
        print(f"  Backup:  {backup.absolute()}")
    else:
        print(f"\n  Created: {toml_path.absolute()}")

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
        typer.Option(
            "-o", "--output", help="Output directory (default: ./<flexname>/)"
        ),
    ] = None,
) -> None:
    """Extract all objects from a Flex archive."""
    raise SystemExit(cmd_flex_extract(SimpleNamespace(file=file, output=output)))


@app.command("flex-create")
def flex_create_cmd(
    directory: Annotated[
        str,
        typer.Argument(
            help="Source directory with numbered files (e.g., 0000.bin, 0001.shp)"
        ),
    ],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output .flx file path (default: <dirname>.flx)"
        ),
    ] = None,
    comment: Annotated[
        str,
        typer.Option(
            "-C", "--comment", help="Comment string to embed in the Flex header"
        ),
    ] = "",
    archive_format: Annotated[
        Optional[Literal["u7", "u8"]],
        typer.Option(
            "--archive-format",
            help="Fresh archive format (default: manifest, U7 for .VGA, otherwise U8)",
        ),
    ] = None,
) -> None:
    """Create a Flex archive from files in a directory."""
    raise SystemExit(
        cmd_flex_create(
            SimpleNamespace(
                directory=directory,
                output=output,
                comment=comment,
                archive_format=archive_format,
            )
        )
    )


@app.command("flex-update")
def flex_update_cmd(
    file: Annotated[str, typer.Argument(help="Path to .flx archive")],
    index: Annotated[
        int, typer.Option("--index", help="Record index to replace (0-based)")
    ],
    data: Annotated[str, typer.Option("--data", help="Path to the replacement file")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o", "--output", help="Output .flx path (default: overwrite input)"
        ),
    ] = None,
) -> None:
    """Replace a single record inside a Flex archive."""
    raise SystemExit(
        cmd_flex_update(
            SimpleNamespace(
                file=file,
                index=index,
                data=data,
                output=output,
            )
        )
    )


@app.command("music-export")
def music_export_cmd(
    file: Annotated[str, typer.Argument(help="Path to .xmi XMIDI file")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory"),
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
    raise SystemExit(
        cmd_music_batch(
            SimpleNamespace(
                directory=directory,
                output=output,
            )
        )
    )


@app.command("setup")
def setup_cmd() -> None:
    """Interactive first-time setup wizard \u2014 creates titan.toml."""
    try:
        raise SystemExit(cmd_setup(SimpleNamespace(config=None)))
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        typer.echo("Setup cancelled.")
        raise SystemExit(0) from None


@app.command("config")
def config_cmd(
    edit: Annotated[
        bool,
        typer.Option("--edit", help="Open titan.toml in the system default editor"),
    ] = False,
) -> None:
    """Show or edit the active titan.toml settings."""
    import titan._config as _config_mod

    raise SystemExit(
        cmd_config(
            SimpleNamespace(
                config=_config_mod.explicit_config_path,
                edit=edit,
            )
        )
    )


# ============================================================================
# Sub-app registration
# ============================================================================

from titan.u8.cli import u8_app  # noqa: E402
from titan.u7.cli import u7_app  # noqa: E402
from titan.u3.cli import u3_app  # noqa: E402
from titan.u6.cli import u6_app  # noqa: E402
from titan.u9.cli import u9_app  # noqa: E402
from titan.uo.cli import uo_app  # noqa: E402
from titan.uw1.cli import uw1_app  # noqa: E402
from titan.uw2.cli import uw2_app  # noqa: E402
from titan.dialogue.cli import dialogue_app  # noqa: E402

app.add_typer(u8_app)
app.add_typer(u7_app)
app.add_typer(u3_app)
app.add_typer(u6_app)
app.add_typer(u9_app)
app.add_typer(uo_app)
app.add_typer(uw1_app)
app.add_typer(uw2_app)
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
    ("palette-export", _u8_cli.palette_export_cmd),
    ("shape-export", _u8_cli.shape_export_cmd),
    ("shape-batch", _u8_cli.shape_batch_cmd),
    ("shape-import", _u8_cli.shape_import_cmd),
    ("sound-export", _u8_cli.sound_export_cmd),
    ("sound-batch", _u8_cli.sound_batch_cmd),
    ("credits-decrypt", _u8_cli.credits_decrypt_cmd),
    ("xformpal-export", _u8_cli.xformpal_export_cmd),
    ("typeflag-dump", _u8_cli.typeflag_dump_cmd),
    ("gumpinfo-dump", _u8_cli.gumpinfo_dump_cmd),
    ("save-list", _u8_cli.save_list_cmd),
    ("save-extract", _u8_cli.save_extract_cmd),
    ("unkcoff-dump", _u8_cli.unkcoff_dump_cmd),
    ("map-render", _u8_cli.map_render_cmd),
    ("map-render-all", _u8_cli.map_render_all_cmd),
    ("map-sample", _u8_cli.map_sample_cmd),
    ("map-sample-all", _u8_cli.map_sample_all_cmd),
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
