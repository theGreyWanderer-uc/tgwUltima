"""``titan u7 usecode-*`` — usecode scanning and disassembly commands."""

from __future__ import annotations

__all__ = ["usecode_scan_intrinsic_cmd", "usecode_disasm_cmd"]

import json
import os
import sys
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan.u7 import install


def _load_u7_intrinsic_names_for_cli(args: SimpleNamespace) -> dict[int, str]:
    from titan.u7.usecode import load_u7_intrinsic_names

    path = install.resolve_ucxt_intrinsics_data(
        getattr(args, "game", "bg"),
        getattr(args, "intrinsics_data", None),
    )
    if not path:
        return {}
    try:
        names = load_u7_intrinsic_names(path)
        if not names:
            raise ValueError(f"U7 intrinsic table contains no entries: {path}")
        return names
    except (OSError, ValueError) as error:
        if getattr(args, "intrinsics_data", None) is not None:
            raise ValueError(
                f"Cannot read U7 intrinsic table {path}: {error}"
            ) from error
        print(
            f"Warning: intrinsic names unavailable; using numeric IDs: {error}",
            file=sys.stderr,
        )
        return {}


def cmd_usecode_scan_intrinsic(args: SimpleNamespace) -> int:
    """Scan a U7 USECODE file for intrinsic call sites."""
    from titan.u7.usecode import U7UsecodeFile

    if not os.path.isfile(args.file):
        print(f"ERROR: USECODE file not found: {args.file}", file=sys.stderr)
        return 1
    try:
        intrinsic_id = int(str(args.intrinsic), 0)
    except ValueError:
        print(f"ERROR: invalid intrinsic id: {args.intrinsic}", file=sys.stderr)
        return 1
    if not 0 <= intrinsic_id <= 0xFFFF:
        print("ERROR: intrinsic id must be between 0 and 65535", file=sys.stderr)
        return 1

    try:
        names = _load_u7_intrinsic_names_for_cli(args)
        usecode = U7UsecodeFile.from_file(
            args.file, strict=bool(getattr(args, "strict", False))
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in usecode.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    fmt = (getattr(args, "format", None) or "table").lower()
    if fmt == "csv":
        content = usecode.scan_intrinsic_csv(intrinsic_id, names)
    else:
        calls = usecode.scan_intrinsic(intrinsic_id, names)
        lines = [
            f"Intrinsic 0x{intrinsic_id:04X}: {names.get(intrinsic_id, '')}",
            f"Matches: {len(calls)}",
        ]
        for call in calls:
            op = "callis" if call.returns_value else "calli"
            lines.append(
                f"0x{call.function_id:04X} "
                f"func@0x{call.function_offset:08X} "
                f"file@0x{call.file_offset:08X} "
                f"rel@0x{call.relative_offset:04X} "
                f"code@0x{call.code_offset:04X} "
                f"{op}@{call.arg_count:02d} "
                f"{call.raw.hex(' ').upper()}"
            )
        content = "\n".join(lines)

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            if content and not content.endswith("\n"):
                f.write("\n")
        print(f"usecode intrinsic scan written to: {args.output}")
    else:
        print(content if content else "No matches.")
    return 0


def cmd_usecode_disasm(args: SimpleNamespace) -> int:
    """Raw-disassemble a single U7 USECODE function."""
    from titan.u7.usecode import U7UsecodeFile
    from titan.u7.usecode_analysis import (
        U7UsecodeWorld,
        U7UsecodeDefinition,
        validate_usecode_function,
    )

    if not os.path.isfile(args.file):
        print(f"ERROR: USECODE file not found: {args.file}", file=sys.stderr)
        return 1
    disasm_all = bool(getattr(args, "all_functions", False))
    if disasm_all and args.function is not None:
        print("ERROR: use either FUNCTION or --all, not both", file=sys.stderr)
        return 1
    symbols_only = bool(getattr(args, "symbols", False))
    if symbols_only and (
        args.function is not None or disasm_all or getattr(args, "original", False)
    ):
        print(
            "ERROR: use --symbols without FUNCTION, --all or --original",
            file=sys.stderr,
        )
        return 1
    if not disasm_all and args.function is None and not symbols_only:
        print("ERROR: provide FUNCTION or --all", file=sys.stderr)
        return 1

    try:
        names = _load_u7_intrinsic_names_for_cli(args)
        usecode = U7UsecodeFile.from_file(
            args.file, strict=bool(getattr(args, "strict", False))
        )
        world = U7UsecodeWorld()
        world.add_stream(usecode, source=args.file)
        stream_warnings = list(usecode.warnings)
        patch_file = getattr(args, "patch_file", None)
        if patch_file:
            patch = U7UsecodeFile.from_file(
                patch_file, strict=bool(getattr(args, "strict", False))
            )
            world.add_stream(patch, source=patch_file, patch=True)
            stream_warnings.extend(patch.warnings)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for warning in stream_warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    annotate = bool(getattr(args, "annotate", False))
    original = bool(getattr(args, "original", False))

    def definitions_for_view() -> list[U7UsecodeDefinition]:
        if disasm_all and not patch_file and not original:
            return [
                U7UsecodeDefinition(usecode, record, args.file)
                for record in usecode.functions
            ]
        return list((world.originals if original else world.definitions).values())

    if symbols_only:
        from dataclasses import asdict

        content = json.dumps([asdict(symbol) for symbol in world.symbols], indent=2)
    elif disasm_all and not patch_file and not annotate and not original:
        content = usecode.disassemble_all(names)
    elif disasm_all:
        content = "\n\n".join(
            definition.disassemble(annotate=annotate, intrinsic_names=names)
            for definition in definitions_for_view()
        )
    else:
        try:
            func_id = int(str(args.function), 0)
        except ValueError:
            print(f"ERROR: invalid function id: {args.function}", file=sys.stderr)
            return 1
        try:
            definition = world.get_function(func_id, original=original)
            if definition is None:
                raise KeyError(
                    f"Function 0x{func_id:X} has no {'original' if original else 'effective'} definition"
                )
            content = definition.disassemble(annotate=annotate, intrinsic_names=names)
        except KeyError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if getattr(args, "validate", False):
        for definition in definitions_for_view():
            if (
                not disasm_all
                and args.function is not None
                and definition.record.func_id != int(str(args.function), 0)
            ):
                continue
            for issue in validate_usecode_function(
                definition.stream, definition.record
            ):
                print(
                    f"Warning: function 0x{issue.function:X} at 0x{issue.file_offset:X}: {issue.message}",
                    file=sys.stderr,
                )
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            if content and not content.endswith("\n"):
                f.write("\n")
        print(f"usecode disassembly written to: {args.output}")
    else:
        print(content)
    return 0


def usecode_scan_intrinsic_cmd(
    file: Annotated[str, typer.Argument(help="Path to U7 USECODE file")],
    intrinsic: Annotated[
        str,
        typer.Argument(help="Intrinsic id to scan for, hex or decimal"),
    ],
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI intrinsic-name table"),
    ] = "bg",
    format: Annotated[
        Optional[str],
        typer.Option("-f", "--format", help="Output format: table (default), csv"),
    ] = None,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write scan output to this file"),
    ] = None,
    intrinsics_data: Annotated[
        Optional[str],
        typer.Option(
            "--intrinsics-data",
            help="Optional UCXT-style intrinsic-name table",
        ),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Reject incomplete Usecode function records"),
    ] = False,
) -> None:
    """Scan raw U7 USECODE for CALLI/CALLIS references to one intrinsic."""
    raise SystemExit(
        cmd_usecode_scan_intrinsic(
            SimpleNamespace(
                file=file,
                intrinsic=intrinsic,
                game=game,
                format=format,
                output=output,
                intrinsics_data=intrinsics_data,
                strict=strict,
            )
        )
    )


def usecode_disasm_cmd(
    file: Annotated[str, typer.Argument(help="Path to U7 USECODE file")],
    function: Annotated[
        Optional[str],
        typer.Argument(help="Function id to disassemble, hex or decimal"),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="Use BG or SI intrinsic-name table"),
    ] = "bg",
    all_functions: Annotated[
        bool,
        typer.Option("--all", help="Disassemble every function in the USECODE file"),
    ] = False,
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write raw disassembly to this file"),
    ] = None,
    intrinsics_data: Annotated[
        Optional[str],
        typer.Option(
            "--intrinsics-data",
            help="Optional UCXT-style intrinsic-name table",
        ),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Reject incomplete Usecode function records"),
    ] = False,
    annotate: Annotated[
        bool,
        typer.Option(
            "--annotate", help="Annotate signed constants and resolved references"
        ),
    ] = False,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate", help="Report branch/data/extern reference diagnostics"
        ),
    ] = False,
    symbols: Annotated[
        bool, typer.Option("--symbols", help="Export symbol/class metadata as JSON")
    ] = False,
    patch_file: Annotated[
        Optional[str],
        typer.Option("--patch-file", help="Overlay patch Usecode functions"),
    ] = None,
    original: Annotated[
        bool,
        typer.Option(
            "--original", help="Inspect the original function retained by callo"
        ),
    ] = False,
) -> None:
    """Raw-disassemble one U7 USECODE function, or all functions with --all."""
    raise SystemExit(
        cmd_usecode_disasm(
            SimpleNamespace(
                file=file,
                function=function,
                game=game,
                all_functions=all_functions,
                output=output,
                intrinsics_data=intrinsics_data,
                strict=strict,
                annotate=annotate,
                validate=validate,
                symbols=symbols,
                patch_file=patch_file,
                original=original,
            )
        )
    )
