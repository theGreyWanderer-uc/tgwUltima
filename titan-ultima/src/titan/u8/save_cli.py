"""Read-only U8 global flags, save overview and scoped save comparison commands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from titan.u8.avatar import U8AvatarState
from titan.u8.gumps import U8GumpState
from titan.u8.kernel import U8KernelState
from titan.u8.native_state_report import (
    format_u8_avatar_report,
    format_u8_gumps_report,
    format_u8_kernel_report,
)
from titan.u8.flags import U8FlagSymbols, U8GlobalFlags
from titan.u8.flags_report import format_u8_flags_report
from titan.u8.save_diff import format_u8_save_diff
from titan.u8.save_state import U8SaveSnapshot, format_u8_save_info
from titan.u8.state_io import write_u8_state_report


def flags_dump_cmd(
    file: Annotated[
        Path,
        typer.Argument(help="FLAG.DAT, native U8SAVE archive, or GAMEDAT directory"),
    ],
    index: Annotated[
        int | None,
        typer.Option(
            "--index",
            min=0,
            max=8191,
            help="Global flag bit offset; optionally use --width",
        ),
    ] = None,
    width: Annotated[
        int,
        typer.Option(
            "--width",
            min=1,
            max=16,
            help="Unsigned field width; requires --index unless 1",
        ),
    ] = 1,
    symbols: Annotated[
        Path | None,
        typer.Option(
            "--symbols",
            help="Native FLAGSYM.DAT with verified names, bit offsets and widths",
        ),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option("--name", help="Exact variable name; requires --symbols"),
    ] = None,
    all_bits: Annotated[
        bool,
        typer.Option(
            "--all-bits",
            help="Include all 8192 bits, including zeros (default: set bits)",
        ),
    ] = False,
    output_format: Annotated[
        str, typer.Option("--format", help="Report format: text, json or csv")
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option(
            "-o", "--output", help="New report file; existing files are preserved"
        ),
    ] = None,
) -> None:
    """Inspect global usecode flag storage; absent native save FLAG uses zero defaults."""
    try:
        flag_symbols = U8FlagSymbols.from_file(symbols) if symbols is not None else None
        report = format_u8_flags_report(
            U8GlobalFlags.from_file(file),
            index=index,
            width=width,
            symbols=flag_symbols,
            name=name,
            all_bits=all_bits,
            output_format=output_format,
        )
        sources: tuple[Path, ...] = (file, symbols) if symbols is not None else (file,)
        if file.is_dir():
            sources += tuple(path for path in file.iterdir() if path.is_file())
        write_u8_state_report(report, output, sources, "Global flags")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def save_info_cmd(
    file: Annotated[
        Path, typer.Argument(help="Native U8SAVE archive or GAMEDAT directory")
    ],
    output_format: Annotated[
        str, typer.Option("--format", help="Report format: text or json")
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option(
            "-o", "--output", help="New report file; existing files are preserved"
        ),
    ] = None,
) -> None:
    """Summarize native save entries, cache, NPCs, stored maps and global flag coverage."""
    try:
        snapshot = U8SaveSnapshot.from_path(file)
        report = format_u8_save_info(snapshot, output_format=output_format)
        write_u8_state_report(
            report, output, snapshot.source_files + (file,), "Save overview"
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def save_diff_cmd(
    before: Annotated[
        Path, typer.Argument(help="Before: native U8SAVE archive or GAMEDAT directory")
    ],
    after: Annotated[
        Path, typer.Argument(help="After: native U8SAVE archive or GAMEDAT directory")
    ],
    symbols: Annotated[
        Path | None,
        typer.Option(
            "--symbols",
            help="Optional matching native FLAGSYM.DAT for named variable differences",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=0,
            help="Maximum rows/ranges per section; 0 exports all; counts remain complete",
        ),
    ] = 100,
    output_format: Annotated[
        str, typer.Option("--format", help="Report format: text or json")
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option(
            "-o", "--output", help="New report file; existing files are preserved"
        ),
    ] = None,
) -> None:
    """Compare verified save fields and map record multisets; opaque entries use bytes."""
    try:
        left, right = U8SaveSnapshot.from_path(before), U8SaveSnapshot.from_path(after)
        flag_symbols = U8FlagSymbols.from_file(symbols) if symbols is not None else None
        report = format_u8_save_diff(
            left, right, symbols=flag_symbols, limit=limit, output_format=output_format
        )
        sources = left.source_files + right.source_files + (before, after)
        if symbols is not None:
            sources += (symbols,)
        write_u8_state_report(report, output, sources, "Save comparison")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def avatar_dump_cmd(
    file: Annotated[Path, typer.Argument(help="AVATAR.DAT or native U8SAVE archive")],
    output_format: Annotated[
        str, typer.Option("--format", help="Report format: text, json or csv")
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option(
            "-o", "--output", help="New report file; existing files are preserved"
        ),
    ] = None,
) -> None:
    """Inspect all avatar extension fields, advancement, hunger, settings and raw bytes."""
    try:
        report = format_u8_avatar_report(
            U8AvatarState.from_file(file), output_format=output_format
        )
        write_u8_state_report(report, output, (file,), "Avatar state")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def gumps_dump_cmd(
    file: Annotated[Path, typer.Argument(help="GUMPS.DAT or native U8SAVE archive")],
    view: Annotated[
        str,
        typer.Option(
            "--view", help="View: containers or rects (all 16 saved screen rectangles)"
        ),
    ] = "containers",
    output_format: Annotated[
        str, typer.Option("--format", help="Report format: text, json or csv")
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option(
            "-o", "--output", help="New report file; existing files are preserved"
        ),
    ] = None,
) -> None:
    """Inspect saved container UI state, drag coordinates, screen rectangles and counter."""
    try:
        report = format_u8_gumps_report(
            U8GumpState.from_file(file), view=view, output_format=output_format
        )
        write_u8_state_report(report, output, (file,), "Container UI state")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def kernel_dump_cmd(
    file: Annotated[Path, typer.Argument(help="KERNEL.DAT or native U8SAVE archive")],
    view: Annotated[
        str, typer.Option("--view", help="View: summary, processes, decoded or records")
    ] = "summary",
    slot: Annotated[
        int | None,
        typer.Option(
            "--slot", min=0, help="Process slot; requires processes or decoded view"
        ),
    ] = None,
    record: Annotated[
        int | None,
        typer.Option(
            "--record", min=0, help="Exact Flex record; requires records view"
        ),
    ] = None,
    output_format: Annotated[
        str, typer.Option("--format", help="Report format: text, json or csv")
    ] = "text",
    output: Annotated[
        Path | None,
        typer.Option(
            "-o", "--output", help="New report file; existing files are preserved"
        ),
    ] = None,
) -> None:
    """Inspect native scheduler, clock/time, animations, usecode state and raw records."""
    try:
        report = format_u8_kernel_report(
            U8KernelState.from_file(file),
            view=view,
            slot=slot,
            record=record,
            output_format=output_format,
        )
        write_u8_state_report(report, output, (file,), "Kernel state")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


def register_u8_save_commands(app: typer.Typer) -> None:
    """Register flat U8 save state commands without importing the main CLI module."""
    app.command("flags-dump")(flags_dump_cmd)
    app.command("save-info")(save_info_cmd)
    app.command("save-diff")(save_diff_cmd)
    app.command("avatar-dump")(avatar_dump_cmd)
    app.command("gumps-dump")(gumps_dump_cmd)
    app.command("kernel-dump")(kernel_dump_cmd)
