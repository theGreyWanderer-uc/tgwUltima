"""Scoped native U8 save differences without inventing persistent object IDs."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import fields, is_dataclass
from typing import Any

from titan.u8.flags import U8FlagSymbols
from titan.u8.map_items import ONE_ITEM, U8MapItem
from titan.u8.save_state import U8SaveSnapshot, u8_state_digest
from titan.u8.kernel_process import decode_u8_kernel_process
from titan.u8.native_state_report import (
    describe_u8_avatar_state,
    describe_u8_kernel_process,
)


def _state_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _state_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, (tuple, list)):
        return [_state_value(element) for element in value]
    return value


def _field_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in sorted(before.keys() | after.keys())
        if before.get(key) != after.get(key)
    }


def _byte_difference(before: bytes, after: bytes, limit: int) -> dict[str, Any]:
    """Count every changed/added/removed byte and bound displayed offset ranges."""
    changed_count = 0
    range_count = 0
    ranges: list[dict[str, int]] = []
    start: int | None = None
    length = max(len(before), len(after))
    for offset in range(length + 1):
        different = offset < length and (
            offset >= len(before)
            or offset >= len(after)
            or before[offset] != after[offset]
        )
        if different:
            changed_count += 1
            if start is None:
                start = offset
        elif start is not None:
            range_count += 1
            if limit == 0 or len(ranges) < limit:
                ranges.append({"start": start, "end_exclusive": offset})
            start = None
    return {
        "changed_byte_count": changed_count,
        "range_count": range_count,
        "ranges": ranges,
        "omitted_range_count": range_count - len(ranges),
    }


def _map_record_counter(
    items: tuple[U8MapItem, ...],
) -> Counter[tuple[bytes, tuple[bytes, ...], tuple[str, ...]]]:
    """Compare record multisets with raw ancestor context, independent of file order."""
    ancestry: dict[int, tuple[bytes, ...]] = {}
    counter: Counter[tuple[bytes, tuple[bytes, ...], tuple[str, ...]]] = Counter()
    for item in items:
        parent = item.parent_record_index
        parents = ancestry[parent] if parent is not None else ()
        raw = item.to_bytes()
        counter[(raw, parents, item.diagnostics)] += 1
        ancestry[item.record_index] = parents + (raw,)
    return counter


def compare_u8_save_snapshots(
    before: U8SaveSnapshot,
    after: U8SaveSnapshot,
    *,
    symbols: U8FlagSymbols | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Compare entries, verified fields and contextual map records; zero limit means all."""
    if limit < 0:
        raise ValueError("U8 save diff: limit must be nonnegative")
    sections: dict[str, Any] = {}

    def add_section(name: str, rows: list[dict[str, Any]]) -> None:
        selected = rows if limit == 0 else rows[:limit]
        sections[name] = {
            "total_count": len(rows),
            "rows": selected,
            "omitted_count": len(rows) - len(selected),
        }

    entries: list[dict[str, Any]] = []
    for name in sorted(before.entries.keys() | after.entries.keys()):
        left, right = before.entries.get(name), after.entries.get(name)
        status = (
            "added"
            if left is None
            else "removed"
            if right is None
            else "unchanged"
            if left == right
            else "changed"
        )
        entry: dict[str, Any] = {
            "name": name,
            "status": status,
            "before_size": None if left is None else len(left),
            "after_size": None if right is None else len(right),
            "before_sha256": None if left is None else u8_state_digest(left),
            "after_sha256": None if right is None else u8_state_digest(right),
        }
        if status != "unchanged":
            entry["byte_difference"] = _byte_difference(
                left or b"", right or b"", limit
            )
        entries.append(entry)
    add_section("entries", entries)

    if before.avatar is not None and after.avatar is not None:
        left_avatar, right_avatar = (
            describe_u8_avatar_state(before.avatar),
            describe_u8_avatar_state(after.avatar),
        )
        # Keep native stored fields rather than duplicate their display interpretations.
        for key in ("raw_hex", "name", "language_code", "random_seed_signed"):
            left_avatar.pop(key)
            right_avatar.pop(key)
        add_section(
            "avatar_fields",
            [
                {"field": key, **change}
                for key, change in _field_changes(left_avatar, right_avatar).items()
            ],
        )

    if before.gumps is not None and after.gumps is not None:
        add_section(
            "gump_counter",
            []
            if before.gumps.gump_count == after.gumps.gump_count
            else [{"before": before.gumps.gump_count, "after": after.gumps.gump_count}],
        )
        add_section(
            "gump_rects",
            [
                {"index": index, "before": left_rect, "after": right_rect}
                for index, (left_rect, right_rect) in enumerate(
                    zip(before.gumps.rects, after.gumps.rects)
                )
                if left_rect != right_rect
            ],
        )
        # Serialized UI order and reusable container references are not stable gump IDs.
        left_gumps = Counter(gump.raw_data for gump in before.gumps.containers)
        right_gumps = Counter(gump.raw_data for gump in after.gumps.containers)
        add_section(
            "container_gump_records",
            [
                {"status": status, "count": count, "raw_hex": raw.hex()}
                for status, delta in (
                    ("removed", left_gumps - right_gumps),
                    ("added", right_gumps - left_gumps),
                )
                for raw, count in sorted(delta.items())
            ],
        )

    if before.kernel is not None and after.kernel is not None:
        add_section(
            "kernel_core",
            [
                {"field": key, **change}
                for key, change in _field_changes(
                    before.kernel.core_fields(), after.kernel.core_fields()
                ).items()
            ],
        )
        add_section(
            "kernel_realtime_words",
            []
            if before.kernel.realtime_words == after.kernel.realtime_words
            else [
                {
                    "before": before.kernel.realtime_words,
                    "after": after.kernel.realtime_words,
                }
            ],
        )
        add_section(
            "kernel_priority_counts",
            [
                {"index": index, "before": left_count, "after": right_count}
                for index, (left_count, right_count) in enumerate(
                    zip(before.kernel.priority_counts, after.kernel.priority_counts)
                )
                if left_count != right_count
            ],
        )
        left_processes = {process.slot: process for process in before.kernel.processes}
        right_processes = {process.slot: process for process in after.kernel.processes}
        process_rows = []
        for slot in sorted(left_processes.keys() | right_processes.keys()):
            left_process, right_process = (
                left_processes.get(slot),
                right_processes.get(slot),
            )
            left_fields = (
                describe_u8_kernel_process(left_process)
                if left_process is not None
                else {}
            )
            right_fields = (
                describe_u8_kernel_process(right_process)
                if right_process is not None
                else {}
            )
            for record_fields in (left_fields, right_fields):
                record_fields.pop("object_hex", None)
                record_fields.pop("flag_names", None)
                record_fields.pop("process_type_hex", None)
                record_fields.pop("priority", None)
            changes = _field_changes(left_fields, right_fields)
            if changes:
                process_rows.append(
                    {
                        "slot": slot,
                        "reference_kind": "reusable_process_slot",
                        "status": "added"
                        if left_process is None
                        else "removed"
                        if right_process is None
                        else "changed",
                        "changes": changes,
                    }
                )
        add_section("kernel_process_slots", process_rows)
        decoded_rows = []
        for slot in sorted(left_processes.keys() | right_processes.keys()):
            states: list[dict[str, Any]] = []
            for processes, kernel in (
                (left_processes, before.kernel),
                (right_processes, after.kernel),
            ):
                process = processes.get(slot)
                if process is None:
                    states.append({})
                    continue
                details = decode_u8_kernel_process(
                    process, build_description=kernel.build_description
                )
                states.append(
                    {
                        "native_class": details.native_class,
                        "kind": details.kind,
                        "status": details.status,
                        **{
                            f"fields.{key}": value
                            for key, value in details.fields.items()
                        },
                        "depend_words": details.depend_words,
                        "notify_words": details.notify_words,
                        "diagnostics": details.diagnostics,
                    }
                    if details.status != "unsupported"
                    else {}
                )
            changes = _field_changes(states[0], states[1])
            if changes:
                decoded_rows.append(
                    {
                        "slot": slot,
                        "reference_kind": "reusable_process_slot",
                        "changes": changes,
                    }
                )
        add_section("kernel_process_state", decoded_rows)

    left_flags, right_flags = before.global_flags, after.global_flags
    if left_flags is not None and right_flags is not None:
        add_section(
            "global_flag_bits",
            [
                {
                    "index": index,
                    "before": left_flags.get_value(index),
                    "after": right_flags.get_value(index),
                }
                for index in sorted(
                    set(left_flags.set_bit_indices())
                    ^ set(right_flags.set_bit_indices())
                )
            ],
        )
        if symbols is not None:
            add_section(
                "global_flag_variables",
                [
                    {
                        "name": symbol.name,
                        "index": symbol.index,
                        "width": symbol.width,
                        "before": left_flags.get_value(symbol.index, symbol.width),
                        "after": right_flags.get_value(symbol.index, symbol.width),
                    }
                    for symbol in symbols.symbols
                    if left_flags.get_value(symbol.index, symbol.width)
                    != right_flags.get_value(symbol.index, symbol.width)
                ],
            )

    left_cache, right_cache = before.item_cache, after.item_cache
    if left_cache is not None and right_cache is not None:
        cache_rows = []
        for left_item, right_item in zip(left_cache.items, right_cache.items):
            left_fields, right_fields = (
                _state_value(left_item),
                _state_value(right_item),
            )
            left_fields["slot_membership"] = left_cache.slot_membership(
                left_item.item_id
            )
            right_fields["slot_membership"] = right_cache.slot_membership(
                right_item.item_id
            )
            changes = _field_changes(left_fields, right_fields)
            if changes:
                cache_rows.append(
                    {
                        "item_id": left_item.item_id,
                        "reference_kind": "reserved_npc_slot"
                        if 0 < left_item.item_id < 256
                        else "null_slot"
                        if left_item.item_id == 0
                        else "reusable_item_slot",
                        "changes": changes,
                    }
                )
        add_section("item_cache_slots", cache_rows)
        left_meta, right_meta = (
            _state_value(left_cache.metadata),
            _state_value(right_cache.metadata),
        )
        left_meta.pop("regions")
        right_meta.pop("regions")
        add_section(
            "item_cache_metadata",
            [
                {"field": name, **change}
                for name, change in _field_changes(left_meta, right_meta).items()
            ],
        )
        add_section(
            "item_cache_regions",
            [
                {
                    "rx": left.rx,
                    "ry": left.ry,
                    "changes": _field_changes(_state_value(left), _state_value(right)),
                }
                for left, right in zip(
                    left_cache.metadata.regions, right_cache.metadata.regions
                )
                if left != right
            ],
        )
        add_section(
            "item_array_tail",
            []
            if left_cache.array_tail == right_cache.array_tail
            else [
                {
                    "before": left_cache.array_tail.hex(),
                    "after": right_cache.array_tail.hex(),
                }
            ],
        )

    if before.npc_data is not None and after.npc_data is not None:
        npc_rows = []
        for left_npc, right_npc in zip(before.npc_data.npcs, after.npc_data.npcs):
            left_fields, right_fields = _state_value(left_npc), _state_value(right_npc)
            left_fields.pop("raw")
            right_fields.pop("raw")
            if left_cache is not None and right_cache is not None:
                for npc, cache, record in (
                    (left_npc, left_cache, left_fields),
                    (right_npc, right_cache, right_fields),
                ):
                    item = cache.get_item(npc.npc_id)
                    record["cache_item"] = _state_value(item)
                    record["slot_membership"] = cache.slot_membership(npc.npc_id)
                    record["full_frame"] = npc.full_frame(item.frame_low)
            changes = _field_changes(left_fields, right_fields)
            if changes:
                npc_rows.append({"npc_id": left_npc.npc_id, "changes": changes})
        add_section("npc_slots", npc_rows)
        add_section(
            "npc_record_tail",
            []
            if before.npc_data.trailing_bytes == after.npc_data.trailing_bytes
            else [
                {
                    "before": before.npc_data.trailing_bytes.hex(),
                    "after": after.npc_data.trailing_bytes.hex(),
                }
            ],
        )

    if before.nonfixed is not None and after.nonfixed is not None:
        map_rows = []
        record_rows = []
        for map_id, (left_items, right_items) in enumerate(
            zip(before.nonfixed.maps, after.nonfixed.maps)
        ):
            left_records, right_records = (
                _map_record_counter(left_items),
                _map_record_counter(right_items),
            )
            removed, added = left_records - right_records, right_records - left_records
            if removed or added:
                map_rows.append(
                    {
                        "map_id": map_id,
                        "before_record_count": len(left_items),
                        "after_record_count": len(right_items),
                        "removed_record_count": sum(removed.values()),
                        "added_record_count": sum(added.values()),
                    }
                )
                for status, record_delta in (("removed", removed), ("added", added)):
                    for (raw, parents, issues), count in sorted(record_delta.items()):
                        record_rows.append(
                            {
                                "map_id": map_id,
                                "status": status,
                                "count": count,
                                "raw_hex": raw.hex(),
                                "fields": dict(
                                    zip(
                                        (
                                            "x",
                                            "y",
                                            "z",
                                            "shape",
                                            "frame",
                                            "status",
                                            "quality",
                                            "npc_num",
                                            "map_num_raw",
                                            "next_item",
                                        ),
                                        ONE_ITEM.unpack(raw),
                                    )
                                ),
                                "ancestor_raw_hex": [
                                    parent.hex() for parent in parents
                                ],
                                "diagnostics": list(issues),
                            }
                        )
        add_section("nonfixed_maps", map_rows)
        add_section("nonfixed_records", record_rows)

    skipped = []
    for entry_name, attribute in (
        ("ITEMCACH.DAT", "item_cache"),
        ("NPCDATA.DAT", "npc_data"),
        ("NONFIXED.DAT", "nonfixed"),
        ("FLAG.DAT", "global_flags"),
        ("AVATAR.DAT", "avatar"),
        ("GUMPS.DAT", "gumps"),
        ("KERNEL.DAT", "kernel"),
    ):
        unavailable = [
            side
            for side, snapshot in (("before", before), ("after", after))
            if getattr(snapshot, attribute) is None
        ]
        if unavailable:
            skipped.append(
                {
                    "entry": entry_name,
                    "unavailable_sides": unavailable,
                    "reason": "missing or invalid layout",
                }
            )
    return {
        "before": str(before.source),
        "after": str(after.source),
        "limit_per_section": limit,
        "changed_entry_count": sum(entry["status"] != "unchanged" for entry in entries),
        "flags_defaulted": {
            "before": left_flags.defaulted if left_flags is not None else None,
            "after": right_flags.defaulted if right_flags is not None else None,
        },
        "decode_errors": {"before": before.decode_errors, "after": after.decode_errors},
        "cache_list_diagnostics": {
            "before": left_cache.list_diagnostics() if left_cache is not None else None,
            "after": right_cache.list_diagnostics()
            if right_cache is not None
            else None,
        },
        "skipped_semantic_comparisons": skipped,
        "notes": [
            "Entry byte comparisons include opaque files, headers, padding and unknown tails; archive packing order is ignored.",
            "Global flag bits are storage differences; named variable meanings require verified symbols. Missing FLAG uses native zero defaults.",
            "NPCs are compared by reserved slot; cache rows include free/stale data. Ordinary cache IDs can be reused, so slot changes do not prove object continuity.",
            "NONFIXED compares raw record multisets with ancestor context per map; sibling order is ignored. Changed records appear as removals/additions, not inferred movement.",
            "Current map cache, stored NONFIXED and static FIXED are separate; this report does not reconstruct the live world.",
            "Avatar fields, UI rectangles/container multisets and verified kernel core/process bases are compared. Matched native clock/time, animation and usecode state is compared separately; process slots can be reused and other types remain raw.",
            "Kernel statics outside the verified prefix, marker residue and unknown entries remain covered by complete entry byte comparisons.",
        ],
        "sections": sections,
    }


def format_u8_save_diff(
    before: U8SaveSnapshot,
    after: U8SaveSnapshot,
    *,
    symbols: U8FlagSymbols | None = None,
    limit: int = 100,
    output_format: str = "text",
) -> str:
    """Render scoped save differences, with exact counts even when rows are limited."""
    if output_format not in {"text", "json"}:
        raise ValueError("U8 save diff: format must be text or json")
    report = compare_u8_save_snapshots(before, after, symbols=symbols, limit=limit)
    if output_format == "json":
        return json.dumps(report, indent=2) + "\n"
    lines = [
        f"U8 save diff: {before.source} -> {after.source}",
        f"Changed entries: {report['changed_entry_count']}",
        f"Global flags defaulted: {report['flags_defaulted']}",
    ]
    for name, section in report["sections"].items():
        lines.append(
            f"\n{name}: {section['total_count']} rows; {section['omitted_count']} omitted"
        )
        lines.extend(json.dumps(row, sort_keys=True) for row in section["rows"])
    if report["skipped_semantic_comparisons"]:
        lines.append(
            "Skipped semantic comparisons: "
            + json.dumps(report["skipped_semantic_comparisons"])
        )
    if before.decode_errors or after.decode_errors:
        lines.append("Decode errors: " + json.dumps(report["decode_errors"]))
    if (
        report["cache_list_diagnostics"]["before"]
        or report["cache_list_diagnostics"]["after"]
    ):
        lines.append(
            "Cache list diagnostics: " + json.dumps(report["cache_list_diagnostics"])
        )
    lines.extend(f"Note: {note}" for note in report["notes"])
    return "\n".join(lines) + "\n"
