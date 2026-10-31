"""Read-only data views for native avatar, container UI and kernel state."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from dataclasses import fields
from typing import Any

from titan.u8.avatar import U8AvatarState
from titan.u8.gumps import U8ContainerGump, U8GumpState
from titan.u8.kernel import U8KernelProcess, U8KernelState
from titan.u8.kernel_process import (
    decode_u8_kernel_process,
    describe_u8_process_details,
)


def _record_fields(record: Any) -> dict[str, Any]:
    return {
        field.name: (value.hex() if isinstance(value, bytes) else value)
        for field in fields(record)
        if field.name not in {"raw_data", "raw_object", "raw_payload"}
        for value in (getattr(record, field.name),)
    }


def describe_u8_avatar_state(data: U8AvatarState) -> dict[str, Any]:
    """Expose every avatar extension field and byte-preserving display interpretations."""
    return {
        **_record_fields(data),
        "name": data.name,
        "language_code": data.language_code,
        "random_seed_signed": data.random_seed_signed,
        "raw_hex": data.raw_data.hex(),
    }


def describe_u8_gump_state(data: U8GumpState) -> dict[str, Any]:
    """Describe saved container gumps and all rectangle slots; barks have no payload."""
    return {
        "container_count": len(data.containers),
        "gump_count_stored": data.gump_count,
        "rects": data.rects,
        "diagnostics": data.diagnostics(),
        "containers": [
            {**_record_fields(gump), "raw_hex": gump.raw_data.hex()}
            for gump in data.containers
        ],
    }


def describe_u8_kernel_state(data: U8KernelState) -> dict[str, Any]:
    """Summarize verified scheduler and matched native process coverage."""
    details = [
        decode_u8_kernel_process(process, build_description=data.build_description)
        for process in data.processes
    ]
    return {
        "coverage": "partial: scheduler prefix, Process base and matched native clock/time, animation and usecode objects/payloads; other types remain raw",
        "build_description": data.build_description,
        "build_defines": data.build_defines,
        "record_count": len(data.records),
        "max_processes": data.max_processes,
        "saved_process_count": len(data.processes),
        "core": data.core_fields(),
        "realtime_words": data.realtime_words,
        "priority_counts": data.priority_counts,
        "process_decode_counts": dict(Counter(detail.status for detail in details)),
        "decoded_class_counts": dict(
            Counter(
                detail.native_class for detail in details if detail.status == "decoded"
            )
        ),
        "game_clocks": [
            {
                "slot": process.slot,
                **detail.fields,
                "ticks_per_second": 30,
                "ticks_per_game_hour": 27000,
            }
            for process, detail in zip(data.processes, details)
            if detail.kind == "clock" and detail.status == "decoded"
        ],
        "process_state_diagnostics": [
            {
                "slot": process.slot,
                "status": detail.status,
                "diagnostics": detail.diagnostics,
            }
            for process, detail in zip(data.processes, details)
            if detail.diagnostics
        ],
        "diagnostics": data.diagnostics(),
    }


def describe_u8_kernel_process(
    process: U8KernelProcess, *, build_description: str | None = None
) -> dict[str, Any]:
    """Expose a saved process base and raw derived bytes; pointers retain raw values."""
    values = {
        **_record_fields(process),
        "priority": process.priority_raw & 31,
        "process_type_hex": f"0x{process.process_type:04X}",
        "flag_names": process.flag_names(),
        "object_hex": process.raw_object.hex(),
        "payload_hex": process.raw_payload.hex(),
    }
    if build_description is not None:
        values["decoded"] = describe_u8_process_details(
            decode_u8_kernel_process(process, build_description=build_description)
        )
    return values


def _format_native_rows(
    label: str,
    metadata: dict[str, Any],
    rows: list[dict[str, Any]],
    output_format: str,
    columns: list[str] | None = None,
) -> str:
    if output_format not in {"text", "json", "csv"}:
        raise ValueError(f"{label} report: format must be text, json or csv")
    if output_format == "json":
        return json.dumps({"file": label, **metadata, "rows": rows}, indent=2) + "\n"
    if output_format == "csv":
        output = io.StringIO(newline="")
        field_names = list(rows[0]) if rows else columns or ["index"]
        writer = csv.DictWriter(output, fieldnames=field_names, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, separators=(",", ":"))
                    if isinstance(value, (tuple, list, dict))
                    else value
                    for key, value in row.items()
                }
            )
        return output.getvalue()
    lines = [f"{label}: {len(rows)} selected rows"]
    lines.extend(
        f"{key}: {json.dumps(value, ensure_ascii=True)}"
        for key, value in metadata.items()
    )
    for index, row in enumerate(rows):
        if len(rows) > 1:
            lines.append(f"\nRow {index}:")
        lines.extend(
            f"{key}: {json.dumps(value, ensure_ascii=True)}"
            for key, value in row.items()
        )
    return "\n".join(lines) + "\n"


def format_u8_avatar_report(data: U8AvatarState, *, output_format: str = "text") -> str:
    """Render all avatar extension fields; NPC slot 1 remains a separate report."""
    return _format_native_rows(
        "AVATAR.DAT",
        {
            "byte_count": 77,
            "name_encoding": "cp437; all 32 name bytes retained",
            "notes": "Toggle bytes/words are retained raw, including noncanonical values.",
        },
        [describe_u8_avatar_state(data)],
        output_format,
    )


def format_u8_gumps_report(
    data: U8GumpState, *, view: str = "containers", output_format: str = "text"
) -> str:
    """Render container UI records with all 16 saved rectangles and the stored counter."""
    if view not in {"containers", "rects"}:
        raise ValueError("GUMPS.DAT report: view must be containers or rects")
    metadata = describe_u8_gump_state(data)
    rows = metadata.pop("containers")
    metadata.update(
        byte_count=len(data.raw_data),
        raw_hex=data.raw_data.hex(),
        view=view,
        notes="Native bark save writes nothing; container IDs are cache references; rectangles use inclusive right/bottom.",
    )
    columns = [
        field.name for field in fields(U8ContainerGump) if field.name != "raw_data"
    ] + ["raw_hex"]
    if view == "rects":
        rows = [
            {
                "index": index,
                "left": rect[0],
                "top": rect[1],
                "right": rect[2],
                "bottom": rect[3],
            }
            for index, rect in enumerate(data.rects)
        ]
    return _format_native_rows("GUMPS.DAT", metadata, rows, output_format, columns)


def format_u8_kernel_report(
    data: U8KernelState,
    *,
    view: str = "summary",
    slot: int | None = None,
    record: int | None = None,
    output_format: str = "text",
) -> str:
    """Render kernel coverage, process inventory or exact record bytes with safe filters."""
    if view not in {"summary", "processes", "decoded", "records"}:
        raise ValueError(
            "KERNEL.DAT report: view must be summary, processes, decoded or records"
        )
    if slot is not None and (
        view not in {"processes", "decoded"} or not 0 <= slot < data.max_processes
    ):
        raise ValueError(
            "KERNEL.DAT report: --slot requires processes or decoded view and a valid slot"
        )
    if record is not None and (
        view != "records" or not 0 <= record < len(data.records)
    ):
        raise ValueError(
            "KERNEL.DAT report: --record requires records view and a valid index"
        )
    metadata = describe_u8_kernel_state(data)
    metadata["view"] = view
    rows: list[dict[str, Any]]
    if view == "summary":
        columns = [
            "slot",
            "pid",
            "ref",
            "process_type",
            "process_type_hex",
            "priority",
            "flags",
            "flag_names",
            "object_bytes",
            "payload_bytes",
            "native_class",
            "kind",
            "decode_status",
        ]
        rows = [
            {
                "slot": process.slot,
                "pid": process.pid,
                "ref": process.ref,
                "process_type": process.process_type,
                "process_type_hex": f"0x{process.process_type:04X}",
                "priority": process.priority_raw & 31,
                "flags": process.flags,
                "flag_names": process.flag_names(),
                "object_bytes": len(process.raw_object),
                "payload_bytes": len(process.raw_payload),
                "native_class": detail.native_class,
                "kind": detail.kind,
                "decode_status": detail.status,
            }
            for process in data.processes
            for detail in [
                decode_u8_kernel_process(
                    process, build_description=data.build_description
                )
            ]
        ]
    elif view == "processes":
        columns = [
            field.name
            for field in fields(U8KernelProcess)
            if field.name not in {"raw_object", "raw_payload"}
        ] + [
            "priority",
            "process_type_hex",
            "flag_names",
            "object_hex",
            "payload_hex",
            "decoded",
        ]
        rows = [
            describe_u8_kernel_process(
                process, build_description=data.build_description
            )
            for process in data.processes
            if slot is None or process.slot == slot
        ]
    elif view == "decoded":
        columns = [
            "slot",
            "pid",
            "ref",
            "process_type",
            "native_class",
            "kind",
            "status",
            "fields",
            "depend_words",
            "notify_words",
            "depend_entries",
            "notify_entries",
            "payload_unparsed_hex",
            "diagnostics",
        ]
        rows = [
            {
                "slot": process.slot,
                "pid": process.pid,
                "ref": process.ref,
                "process_type": process.process_type,
                **describe_u8_process_details(detail),
            }
            for process in data.processes
            if slot is None or process.slot == slot
            for detail in [
                decode_u8_kernel_process(
                    process, build_description=data.build_description
                )
            ]
        ]
    else:
        columns = ["index", "size", "raw_hex"]
        rows = [
            {"index": index, "size": len(raw), "raw_hex": raw.hex()}
            for index, raw in enumerate(data.records)
            if record is None or index == record
        ]
    return _format_native_rows("KERNEL.DAT", metadata, rows, output_format, columns)
