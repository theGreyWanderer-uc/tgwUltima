"""Text, JSON and CSV views of U8 global flag bits and named packed variables."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from titan.u8.flags import FLAG_BIT_COUNT, U8FlagSymbols, U8GlobalFlags


def format_u8_flags_report(
    data: U8GlobalFlags,
    *,
    index: int | None = None,
    width: int = 1,
    symbols: U8FlagSymbols | None = None,
    name: str | None = None,
    all_bits: bool = False,
    output_format: str = "text",
) -> str:
    """Show set bits by default, an explicit field, or all verified named variables."""
    if output_format not in {"text", "json", "csv"}:
        raise ValueError("FLAG.DAT report: format must be text, json or csv")
    if width != 1 and index is None:
        raise ValueError("FLAG.DAT report: --width requires --index")
    if name is not None and symbols is None:
        raise ValueError("FLAG.DAT report: --name requires --symbols")
    if symbols is not None and (index is not None or all_bits):
        raise ValueError(
            "FLAG.DAT report: symbols cannot be combined with --index or --all-bits"
        )
    if index is not None and all_bits:
        raise ValueError("FLAG.DAT report: --index cannot be combined with --all-bits")
    rows: list[dict[str, Any]] = []
    if symbols is not None:
        selected = [
            symbol for symbol in symbols.symbols if name is None or symbol.name == name
        ]
        if name is not None and not selected:
            raise ValueError(f"FLAG.DAT report: unknown symbol {name!r}")
        rows = [
            {
                "name": symbol.name,
                "index": symbol.index,
                "width": symbol.width,
                "value": data.get_value(symbol.index, symbol.width),
            }
            for symbol in selected
        ]
        view = "named_variables"
    elif index is not None:
        rows = [
            {
                "name": None,
                "index": index,
                "width": width,
                "value": data.get_value(index, width),
            }
        ]
        view = "bit_field"
    else:
        indices = range(FLAG_BIT_COUNT) if all_bits else data.set_bit_indices()
        rows = [
            {"name": None, "index": bit, "width": 1, "value": data.get_value(bit)}
            for bit in indices
        ]
        view = "all_bits" if all_bits else "set_bits"
    metadata = {
        "file": "FLAG.DAT",
        "byte_count": len(data.raw_data),
        "bit_count": FLAG_BIT_COUNT,
        "defaulted": data.defaulted,
        "storage_basis": "absent FLAG.DAT: native zero initialization"
        if data.defaulted
        else "stored FLAG.DAT",
        "value_interpretation": "unsigned stored value; bit index 0 is byte 0 bit 0",
        "set_bit_count": len(data.set_bit_indices()),
        "view": view,
        "selected_count": len(rows),
    }
    if output_format == "json":
        return json.dumps({**metadata, "flags": rows}, indent=2) + "\n"
    fields = ["name", "index", "width", "value"]
    if output_format == "csv":
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
    lines = [
        f"FLAG.DAT: {metadata['storage_basis']}",
        f"1024 bytes / 8192 bits; {metadata['set_bit_count']} set bits; view: {view}",
        "Values are unsigned packed fields; bit rows are not necessarily independent variables.",
        "Name | Bit index | Width | Value",
    ]
    lines.extend(
        f"{row['name'] or '-'} | {row['index']} | {row['width']} | {row['value']}"
        for row in rows
    )
    return "\n".join(lines) + "\n"
