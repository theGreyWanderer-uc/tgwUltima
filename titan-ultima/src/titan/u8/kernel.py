"""Verified KERNEL.DAT directory, scheduler core and process inventory.

Native U8/KERNEL.C writes ten shared records and two records per process slot.
Matched process tails/payloads are decoded separately in kernel_process.py.
Stored pointer/vtable cells are runtime residue, never file offsets or names.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

from titan.u8.state_io import parse_u8_state_flex, read_u8_state_bytes

PROCESS_FLAG_NAMES = (
    "suspended",
    "daemon",
    "interrupt_handler",
    "phantom",
    "conditional",
    "failed",
    "skip",
    "messages",
    "interrupt",
    "realtime",
    "on_realtime",
    "linear",
    "executor",
    "safe",
    "terminated",
    "dependency_failed",
)


@dataclass(frozen=True)
class U8KernelProcess:
    """One saved process slot; PID slots can be reused between snapshots."""

    slot: int
    object_record: int
    payload_record: int
    raw_object: bytes
    raw_payload: bytes
    declared_size: int
    vtable_raw: int
    pid: int
    ref: int
    process_type: int
    priority_raw: int
    padding_09: int
    result: int
    flags: int
    save_flags_raw: int
    allocations: int
    message_groups: int
    depend_vtable_raw: int
    depend_count: int
    depend_linear_type: int
    depend_pointer_raw: int
    notify_vtable_raw: int
    notify_count: int
    notify_linear_type: int
    notify_pointer_raw: int
    derived_object_bytes: bytes

    def flag_names(self) -> list[str]:
        """Decode all native process flag bits while preserving the original word."""
        return [
            name
            for bit, name in enumerate(PROCESS_FLAG_NAMES)
            if self.flags & (1 << bit)
        ]


@dataclass(frozen=True)
class U8KernelState:
    """Partially decoded native scheduler snapshot with every record preserved."""

    raw_data: bytes
    records: tuple[bytes, ...]
    build_description: str
    build_defines: int
    max_processes: int
    process_sizes: tuple[int, ...]
    processes: tuple[U8KernelProcess, ...]
    realtime_words: tuple[int, ...]
    priority_counts: tuple[int, ...]

    @classmethod
    def from_file(cls, filepath: str | Path) -> U8KernelState:
        """Read loose KERNEL.DAT or its entry inside a native U8 save archive."""
        return cls.from_bytes(read_u8_state_bytes(filepath, "KERNEL.DAT"))

    @classmethod
    def from_bytes(cls, data: bytes) -> U8KernelState:
        """Validate native 1.00 record structure and decode the 42-byte Process base."""
        if len(data) < 128:
            raise ValueError("KERNEL.DAT: truncated Flex header")
        count = struct.unpack_from("<I", data, 84)[0]
        if count < 12 or (count - 10) % 2:
            raise ValueError(
                "KERNEL.DAT: expected ten shared records and paired process slots"
            )
        archive = parse_u8_state_flex(data, "KERNEL.DAT", count)
        records = tuple(archive.records)
        intervals = sorted(
            struct.unpack_from("<II", data, 128 + index * 8)
            for index in range(count)
            if struct.unpack_from("<II", data, 128 + index * 8)[1]
        )
        if any(
            offset + size > following
            for (offset, size), (following, _) in zip(intervals, intervals[1:])
        ):
            raise ValueError("KERNEL.DAT: record payloads overlap")
        max_processes = (count - 10) // 2
        for index, expected in (
            (1, 157),
            (3, max_processes * 2),
            (4, 1152),
            (5, 9216),
            (6, 64),
            (7, max_processes * 4),
        ):
            if len(records[index]) != expected:
                raise ValueError(
                    f"KERNEL.DAT: record {index} requires {expected} bytes"
                )
        try:
            description = records[0].decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("KERNEL.DAT: build description must be ASCII") from error
        match = re.fullmatch(
            r"Defines=([0-9a-fA-F]+) Id=Kernel Ver\. 1\.00[^\x00]*\x00", description
        )
        if match is None:
            raise ValueError(
                "KERNEL.DAT: unsupported or invalid native build description"
            )
        if struct.unpack_from("<H", records[1], 14)[0] != max_processes:
            raise ValueError(
                "KERNEL.DAT: scheduler capacity differs from record directory"
            )
        if len(records[2]) % 2:
            raise ValueError("KERNEL.DAT: partial realtime list word")
        sizes = struct.unpack(f"<{max_processes}H", records[3])
        processes = []
        for slot, size in enumerate(sizes):
            object_index = 10 + slot * 2
            raw, payload = records[object_index : object_index + 2]
            if not size:
                if raw or payload:
                    raise ValueError(
                        f"KERNEL.DAT: unused slot {slot} has process records"
                    )
                continue
            if len(raw) != size or size < 42:
                raise ValueError(
                    f"KERNEL.DAT: slot {slot} has invalid process object size"
                )
            base = struct.unpack_from("<HHHBBiHHHH", raw, 2)
            depend = struct.unpack_from("<HHHI", raw, 22)
            notify = struct.unpack_from("<HHHI", raw, 32)
            processes.append(
                U8KernelProcess(
                    slot=slot,
                    object_record=object_index,
                    payload_record=object_index + 1,
                    raw_object=raw,
                    raw_payload=payload,
                    declared_size=size,
                    vtable_raw=struct.unpack_from("<H", raw)[0],
                    pid=base[0],
                    ref=base[1],
                    process_type=base[2],
                    priority_raw=base[3],
                    padding_09=base[4],
                    result=base[5],
                    flags=base[6],
                    save_flags_raw=base[7],
                    allocations=base[8],
                    message_groups=base[9],
                    depend_vtable_raw=depend[0],
                    depend_count=depend[1],
                    depend_linear_type=depend[2],
                    depend_pointer_raw=depend[3],
                    notify_vtable_raw=notify[0],
                    notify_count=notify[1],
                    notify_linear_type=notify[2],
                    notify_pointer_raw=notify[3],
                    derived_object_bytes=raw[42:],
                )
            )
        return cls(
            bytes(data),
            records,
            description[:-1],
            int(match[1], 16),
            max_processes,
            sizes,
            tuple(processes),
            struct.unpack(f"<{len(records[2]) // 2}H", records[2]),
            struct.unpack("<32H", records[6]),
        )

    def core_fields(self) -> dict[str, int]:
        """Expose verified scheduler prefix fields; the remaining statics stay raw."""
        raw = self.records[1]
        values = {
            "process_list_pointer_raw": struct.unpack_from("<I", raw)[0],
            "process_sizes_pointer_raw": struct.unpack_from("<I", raw, 4)[0],
        }
        names: tuple[str, ...] = (
            "reconfigure_counter",
            "current_scan_slot",
            "current_linear_scan_pid",
            "max_processes",
            "total_processes",
            "current_process",
            "current_process_size",
        )
        values.update(zip(names, struct.unpack_from("<7H", raw, 8)))
        names = (
            "expand_on_demand_raw",
            "processing_raw",
            "initialized_raw",
            "keyboard_vector_changed_raw",
            "keyboard_buffer_overflow_raw",
            "restarting_raw",
        )
        values.update(zip(names, raw[22:28]))
        values.update(
            zip(
                ("num_phantoms", "searching_ref", "searching_process_type"),
                struct.unpack_from("<3H", raw, 28),
            )
        )
        values.update(
            priority_count_pointer_raw=struct.unpack_from("<I", raw, 38)[0],
            current_tick=struct.unpack_from("<I", raw, 42)[0],
            current_priority_raw=raw[46],
            abort_do_processes_raw=raw[47],
            current_polled_interrupt_pid=struct.unpack_from("<H", raw, 48)[0],
        )
        return values

    def diagnostics(self) -> list[str]:
        """Report PID/counter mismatches without resolving stored runtime pointers."""
        issues = [
            f"slot {process.slot}: stored PID {process.pid} differs from slot"
            for process in self.processes
            if process.pid != process.slot
        ]
        if self.core_fields()["total_processes"] != len(self.processes):
            issues.append("stored process count differs from saved process inventory")
        return issues

    def to_bytes(self) -> bytes:
        """Return the exact archive, including unused directory slots, gaps and residue."""
        return self.raw_data
