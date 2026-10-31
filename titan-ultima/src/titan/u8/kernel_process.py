"""Native KERNEL process tails and virtual save payloads for a verified DOS build.

The profile is from U8_SRC/out/U8.MAP, data segment 0094. Near vtable cells
are build-specific, not portable process IDs. INTER.C can change a usecode
process's processType, so its class cannot be identified by that word.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

from titan.u8.kernel import U8KernelProcess

NATIVE_PROCESS_BUILD = "Defines=f7e Id=Kernel Ver. 1.00 - T. Zurovec"

# Only these source-verified AnimPrimitive subclasses inherit Process::save.
ANIMATION_VTABLES = {
    0x25EB: "Advance",
    0x21A7: "AltitudeFall",
    0x941B: "AnimPrimitive",
    0x1DCB: "BlockEnd",
    0x1DFF: "BlockStart",
    0x22DF: "Bow",
    0x1E67: "Burn",
    0x254F: "CarefulStep",
    0x23E3: "Cast1",
    0x23AF: "Cast2",
    0x237B: "Cast3",
    0x0AE4: "Climb",
    0x24E7: "CombatStand",
    0x2687: "DrawWeapon",
    0x1E9B: "Drown",
    0x2173: "EdgeBalance",
    0x244B: "EnterCast",
    0x2417: "ExitCast",
    0x18C7: "FallDown",
    0x210B: "FallRecDmg",
    0x213F: "FallRecHurt",
    0x24B3: "FallRecovery",
    0x206F: "Fidget",
    0x203B: "Fidget2",
    0x251B: "GetHit",
    0x1893: "GetUp",
    0x1F03: "GiveItem",
    0x220F: "HighReach",
    0x1E33: "Kick",
    0x22AB: "Kneel",
    0x2007: "KneelDown",
    0x1FD3: "KneelUp",
    0x20A3: "LedgeClimb",
    0x20D7: "LedgeSwing",
    0x2347: "LookLeft",
    0x2313: "LookRight",
    0x2277: "LowReach",
    0x2243: "MidReach",
    0x247F: "NinjaFlip",
    0x25B7: "Retreat",
    0x2723: "Run",
    0x2583: "RunningLeap",
    0x2653: "SheathWeapon",
    0x1F9F: "SitDown",
    0x1F6B: "SitUp",
    0x26EF: "Stand",
    0x9450: "StandingLeap",
    0x261F: "SwingWeapon",
    0x21DB: "SwingWeapon2",
    0x1F37: "Talk",
    0x26BB: "VertLeap",
    0x2757: "Walk",
    0x1ECF: "Work",
}

# class, kind, packed DOS object size, expected process type (None: mutable).
PROCESS_PROFILES = {
    0x0331: ("GameTime", "game-time", 49, 0x245),
    0x0305: ("Animation", "clock", 78, 0x230),
    0x0400: ("RoundTimer", "round-timer", 44, 0x233),
    0x03CC: ("Wait", "wait", 60, 0x226),
    0x03A0: ("Timer", "timer", 61, 0x201),
    0x0374: ("AccurateTimer", "accurate-timer", 61, 0x226),
    0x89F7: ("UnkProcess", "usecode", 278, None),
    **{
        vtable: (name, "animation", 76, 0xF0)
        for vtable, name in ANIMATION_VTABLES.items()
    },
    # StandingLeap adds three signed words and two packed WorldPoints.
    0x9450: ("StandingLeap", "animation", 92, 0xF0),
}


@dataclass(frozen=True)
class U8KernelProcessDetails:
    """Decoded state with explicit coverage; malformed subtypes preserve the archive."""

    native_class: str | None
    kind: str | None
    status: str
    fields: dict[str, Any]
    depend_words: tuple[int, ...] | None
    notify_words: tuple[int, ...] | None
    payload_unparsed: bytes
    diagnostics: tuple[str, ...]


def _realtime_fields(raw: bytes) -> dict[str, int]:
    return dict(
        zip(
            ("interrupt_flags", "hertz", "period", "elapsed"),
            struct.unpack_from("<IHII", raw, 42),
        )
    )


def decode_u8_kernel_process(
    process: U8KernelProcess, *, build_description: str
) -> U8KernelProcessDetails:
    """Decode a matched profile without dereferencing any saved pointer.

    Lists serialize count words only when their saved data pointer is nonzero.
    UnkProcess appends thisOffset, thisSize, optional killed byte, then an IP
    offset. Invalid lengths are reported locally; unrelated records stay usable.
    """
    profile = PROCESS_PROFILES.get(process.vtable_raw)
    if build_description != NATIVE_PROCESS_BUILD or profile is None:
        return U8KernelProcessDetails(
            None, None, "unsupported", {}, None, None, process.raw_payload, ()
        )
    name, kind, size, expected_type = profile
    raw = process.raw_object
    if len(raw) != size or (
        expected_type is not None and process.process_type != expected_type
    ):
        return U8KernelProcessDetails(
            name,
            kind,
            "invalid",
            {},
            None,
            None,
            process.raw_payload,
            ("profile object size/process type mismatch",),
        )
    values: dict[str, Any] = {}
    issues: list[str] = []
    if kind in {"clock", "wait", "timer", "accurate-timer"}:
        values.update(_realtime_fields(raw))
    if kind == "game-time":
        values.update(
            zip(
                ("loops", "pause", "hour_changed_raw"),
                struct.unpack_from("<IhB", raw, 42),
            )
        )
    elif kind == "clock":
        values.update(
            zip(
                (
                    "animation_frames",
                    "last_unlocked_frame",
                    "ticks",
                    "game_hours",
                    "pending_ticks",
                    "frame_locked_raw",
                    "animation_stopped_raw",
                ),
                struct.unpack_from("<IiiiiBB", raw, 56),
            )
        )
    elif kind == "round-timer":
        values["remaining_loops"] = struct.unpack_from("<H", raw, 42)[0]
    elif kind == "wait":
        values.update(
            zip(
                ("remaining_ticks", "initial_ticks"), struct.unpack_from("<HH", raw, 56)
            )
        )
    elif kind == "timer":
        values.update(
            zip(
                ("running_raw", "seconds", "tenths"),
                struct.unpack_from("<BHH", raw, 56),
            )
        )
    elif kind == "accurate-timer":
        values.update(zip(("timing_raw", "ticks"), struct.unpack_from("<BI", raw, 56)))
    elif kind == "animation":
        values.update(
            zip(
                (
                    "interrupt_flags",
                    "animation",
                    "direction",
                    "frames",
                    "started_raw",
                    "stop_moving_raw",
                    "collided_raw",
                    "blocked_raw",
                    "stand_after_raw",
                    "try_sideways_raw",
                    "fail_next_raw",
                    "animation_result",
                    "unknown_3d",
                    "target_ref",
                    "destination_pointer_raw",
                    "saved_first_step_raw",
                    "saved_last_animation",
                    "saved_direction",
                    "saved_flipped_raw",
                    "saved_flags_2f_5_raw",
                    "saved_animation_frame",
                ),
                struct.unpack_from("<IHb8BIHHIBhbBBB", raw, 42),
            )
        )
        if name == "StandingLeap":
            values.update(
                zip(
                    (
                        "jump_total_distance",
                        "jump_z_difference",
                        "jump_frames",
                        "jump_target_x",
                        "jump_target_y",
                        "jump_target_z",
                        "jump_start_x",
                        "jump_start_y",
                        "jump_start_z",
                    ),
                    struct.unpack_from("<hhhHHBHHB", raw, 76),
                )
            )
    elif kind == "usecode":
        values["unit"] = struct.unpack_from("<H", raw, 42)[0]
        values["stack_hex"] = raw[44:244].hex()
        values.update(
            zip(
                (
                    "stack_pointer_raw",
                    "stack_top_pointer_raw",
                    "base_pointer_offset",
                    "instruction_pointer_raw",
                    "owner_pointer_raw",
                    "routine_padding_hex",
                    "suspended_raw",
                    "result_destination_pointer_raw",
                    "this_offset_raw",
                    "this_size_raw",
                    "finished_raw",
                    "running_raw",
                    "killed_pointer_raw",
                ),
                struct.unpack_from("<IIHII2sBIHBBBI", raw, 244),
            )
        )
        values["routine_padding_hex"] = values["routine_padding_hex"].hex()
        sp, top = values["stack_pointer_raw"], values["stack_top_pointer_raw"]
        # DOS pointer cells are segment:offset; only compare offsets in the same segment.
        stack_offset = 200 + (sp & 0xFFFF) - (top & 0xFFFF)
        if sp >> 16 == top >> 16 and 0 <= stack_offset <= 200:
            values["stack_pointer_offset"] = stack_offset
            values["active_stack_hex"] = raw[44 + stack_offset : 244].hex()
        else:
            values["stack_pointer_offset"] = None
            values["active_stack_hex"] = None
            issues.append("stack pointers do not describe a verified 200-byte buffer")
        if values["base_pointer_offset"] > 200:
            issues.append("base pointer lies outside stack buffer")

    dep_count = process.depend_count if process.depend_pointer_raw else 0
    notify_count = process.notify_count if process.notify_pointer_raw else 0
    list_size = (dep_count + notify_count) * 2
    suffix_size = (5 + bool(values["killed_pointer_raw"])) if kind == "usecode" else 0
    if len(process.raw_payload) != list_size + suffix_size:
        issues.append(
            f"auxiliary payload requires {list_size + suffix_size} bytes; found {len(process.raw_payload)}"
        )
        return U8KernelProcessDetails(
            name,
            kind,
            "invalid",
            values,
            None,
            None,
            process.raw_payload,
            tuple(issues),
        )
    depend_words = struct.unpack_from(f"<{dep_count}H", process.raw_payload)
    notify_words = struct.unpack_from(
        f"<{notify_count}H", process.raw_payload, dep_count * 2
    )
    if kind == "usecode":
        payload = process.raw_payload
        values["this_offset_saved"], values["this_size_saved"] = struct.unpack_from(
            "<HB", payload, list_size
        )
        cursor = list_size + 3
        values["killed_saved_raw"] = (
            payload[cursor] if values["killed_pointer_raw"] else None
        )
        cursor += bool(values["killed_pointer_raw"])
        values["instruction_offset_saved"] = struct.unpack_from("<H", payload, cursor)[
            0
        ]
        if values["this_size_saved"] > 200 or (
            values["this_offset_saved"] and values["this_offset_saved"] > 196
        ):
            issues.append("saved this state lies outside stack buffer")
        if (values["this_offset_saved"], values["this_size_saved"]) != (
            values["this_offset_raw"],
            values["this_size_raw"],
        ):
            issues.append(
                "object this state differs from authoritative auxiliary state"
            )
    return U8KernelProcessDetails(
        name, kind, "decoded", values, depend_words, notify_words, b"", tuple(issues)
    )


def describe_u8_process_details(details: U8KernelProcessDetails) -> dict[str, Any]:
    """Return JSON/CSV-safe state and native PID/operator list word interpretations."""

    def entries(words: tuple[int, ...] | None) -> list[dict[str, Any]] | None:
        if words is None:
            return None
        operators = {0x401: "true", 0x402: "and", 0x404: "or", 0x408: "end"}
        return [
            {
                "word": word,
                "operator": operators.get(word),
                "is_operator": bool(word & 0x400),
                "pid": None if word & 0x400 else word & 0x3FF,
                "passive_interrupt": bool(word & 0x800),
                "active_interrupt": bool(word & 0x1000),
                "passive_dependency": bool(word & 0x2000),
                "active_dependency": bool(word & 0x4000),
                "unknown_bits": word & 0x8000,
            }
            for word in words
        ]

    return {
        "native_class": details.native_class,
        "kind": details.kind,
        "status": details.status,
        "fields": details.fields,
        "depend_words": details.depend_words,
        "notify_words": details.notify_words,
        "depend_entries": entries(details.depend_words),
        "notify_entries": entries(details.notify_words),
        "payload_unparsed_hex": details.payload_unparsed.hex(),
        "diagnostics": details.diagnostics,
    }
