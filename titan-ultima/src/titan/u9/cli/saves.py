"""``titan u9 save-check`` — savegame integrity command."""

from __future__ import annotations

__all__ = ["save_check_cmd"]

from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.integrity import check_save, render_integrity_report


def cmd_save_check(args: SimpleNamespace) -> int:
    """Check custody, structure, and fixed-layout compatibility for one save."""
    report = check_save(
        args.target,
        slot=args.slot,
        static_directory=args.static,
        fixed_reference_directory=args.fixed_reference,
        allow_partial=args.partial,
    )
    print(render_integrity_report(report))
    if args.json_output:
        report.write_json(args.json_output)
        print(f"\nJSON: {args.json_output}")
    return {"PASS": 0, "WARN": 1, "ERROR": 2, "FATAL": 3}[report.overall]


def save_check_cmd(
    target: Annotated[
        str,
        typer.Argument(help="Ultima IX install root or savegame directory"),
    ],
    slot: Annotated[
        Optional[int],
        typer.Option("--slot", help="Check this slot instead of start.dat's selection"),
    ] = None,
    static: Annotated[
        Optional[str],
        typer.Option(
            "--static", help="Directory containing installed fixed.<map> files"
        ),
    ] = None,
    fixed_reference: Annotated[
        Optional[str],
        typer.Option(
            "--fixed-reference",
            help="Trusted creation-time fixed.<map> directory for identity comparison",
        ),
    ] = None,
    json_output: Annotated[
        Optional[str],
        typer.Option("--json", help="Also write the complete report as JSON"),
    ] = None,
    partial: Annotated[
        bool,
        typer.Option(
            "--partial",
            help="Treat omitted archive/fixed files as an intentional forensic subset",
        ),
    ] = False,
) -> None:
    """Check a selected U9 save's custody, heap structure, and compatibility."""
    raise SystemExit(
        cmd_save_check(
            SimpleNamespace(
                target=target,
                slot=slot,
                static=static,
                fixed_reference=fixed_reference,
                json_output=json_output,
                partial=partial,
            )
        )
    )
