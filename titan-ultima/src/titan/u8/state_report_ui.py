"""Show or save a U8 saved-state report from the CLI and the U8 browsers."""

from __future__ import annotations

from pathlib import Path

from titan.u8.state_io import save_u8_state_report


def write_u8_state_report(
    report: str,
    output: Path | None,
    sources: tuple[Path, ...],
    label: str,
) -> None:
    """Write a new state report or stdout, preserving sources and existing outputs."""
    if output is None:
        print(report, end="")
        return
    save_u8_state_report(report, output, sources)
    print(f"{label} report written to: {output}")
