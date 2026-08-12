"""LEV.ARK map block parsing."""

from __future__ import annotations

from collections import Counter, defaultdict
import struct


TILE_TYPE_NAMES = {
    0: "solid",
    1: "open",
    2: "diagonal_se",
    3: "diagonal_sw",
    4: "diagonal_ne",
    5: "diagonal_nw",
    6: "slope_n",
    7: "slope_s",
    8: "slope_e",
    9: "slope_w",
}

WORLD_RANGES = [
    (0, 4, "Castle Britannia / Sewers"),
    (8, 15, "Prison Tower"),
    (16, 17, "Killorn Keep"),
    (24, 25, "Ice Caverns"),
    (32, 33, "Talorus"),
    (40, 47, "Scintillus Academy"),
    (48, 51, "Praecor Loth's Tomb"),
    (56, 58, "Pits of Carnage"),
    (64, 72, "Ethereal Void"),
]

LEVEL_NAMES = {
    1: "Britannia - Castle of Lord British",
    2: "Britannia - Castle Basement",
    3: "Britannia - Sewer 1",
    4: "Britannia - Sewer 2",
    5: "Britannia - Sewer 3",
    9: "Prison Tower - Basement",
    10: "Prison Tower - First Floor",
    11: "Prison Tower - Second Floor",
    12: "Prison Tower - Third Floor",
    13: "Prison Tower - Fourth Floor",
    14: "Prison Tower - Fifth Floor",
    15: "Prison Tower - Sixth Floor",
    16: "Prison Tower - Seventh Floor",
    17: "Killorn Keep - Level 1",
    18: "Killorn Keep - Level 2",
    25: "Ice Caverns - Level 1",
    26: "Ice Caverns - Level 2",
    33: "Talorus - Level 1",
    34: "Talorus - Level 2",
    41: "Scintillus Academy - Level 1",
    42: "Scintillus Academy - Level 2",
    43: "Scintillus Academy - Level 3",
    44: "Scintillus Academy - Level 4",
    45: "Scintillus Academy - Level 5",
    46: "Scintillus Academy - Level 6",
    47: "Scintillus Academy - Level 7",
    48: "Scintillus Academy - Level 8",
    49: "Tomb of Praecor Loth - Level 1",
    50: "Tomb of Praecor Loth - Level 2",
    51: "Tomb of Praecor Loth - Level 3",
    52: "Tomb of Praecor Loth - Level 4",
    57: "Pits of Carnage - Prison",
    58: "Pits of Carnage - Upper Dungeons",
    59: "Pits of Carnage - Lower Dungeons",
    65: "Ethereal Void - Color Zone",
    66: "Ethereal Void - Purple Zone",
    67: "Scintillus Academy - Secure Vault",
    68: "Ethereal Void - Yellow Zone",
    69: "Ethereal Void",
    70: "Secret Level",
    71: "Ethereal Void - Red Zone",
    72: "Killorn Deathtrap",
    73: "Tomb of Praecor Loth - Level 3-Alt",
}

DOOR_TEXTURE_BASE = 0x0410
LEVEL_BLOCK_MIN_SIZE = 0x7E08
TILEMAP_SIZE = 0x4000
MOBILE_OBJECT_OFFSET = 0x4000
STATIC_OBJECT_OFFSET = 0x5B00
MOBILE_FREE_OFFSET = 0x7300
STATIC_FREE_OFFSET = 0x74FC
ACTIVE_MOBILE_OFFSET = 0x7AFC
UNKNOWN_7BFA_OFFSET = 0x7BFA
COUNTERS_OFFSET = 0x7C00
ANIMATION_OVERLAY_OFFSET = 0x7C08


def world_name_for_slot(slot_index: int) -> str | None:
    if slot_index == 69:
        return "Secret Level"
    for start, end, name in WORLD_RANGES:
        if start <= slot_index <= end:
            return name
    return None


def level_name_for_slot(slot_index: int) -> str | None:
    return LEVEL_NAMES.get(slot_index + 1)


def parse_texture_mapping(block: bytes) -> dict:
    if len(block) < 0x86:
        raise ValueError(f"texture mapping block is too small: {len(block)} bytes")
    entries = [struct.unpack_from("<H", block, i * 2)[0] for i in range(64)]
    door_raw = list(block[0x80:0x86])
    door_resolved = [value + DOOR_TEXTURE_BASE for value in door_raw]
    return {
        "raw_size": len(block),
        "entries": entries,
        "door_raw": door_raw,
        "door_resolved": door_resolved,
        "all_resolved": entries + door_resolved,
        "ceiling_texture_ua": entries[32],
        "ceiling_texture_runtime": entries[16] if False else entries[15],
    }


def parse_level(
    slot_index: int,
    level_block: bytes,
    texture_mapping: dict,
    automap_block: bytes | None = None,
    notes_block: bytes | None = None,
    light_level: int | None = None,
) -> dict:
    if len(level_block) < LEVEL_BLOCK_MIN_SIZE:
        raise ValueError(
            f"level {slot_index} decoded block is too small: "
            f"{len(level_block)} bytes, expected at least {LEVEL_BLOCK_MIN_SIZE}"
        )

    tiles = parse_tiles(level_block[:TILEMAP_SIZE], texture_mapping, slot_index)
    free_lists = parse_free_lists(level_block)
    overlays = parse_animation_overlays(level_block)
    objects = parse_objects(level_block, tiles, free_lists)
    automap = parse_automap(automap_block) if automap_block else None
    notes = (
        parse_map_notes(notes_block)
        if notes_block
        else {"records": [], "non_empty": []}
    )

    tile_counts = Counter(tile["type_name"] for tile in tiles)
    reachable_count = sum(1 for obj in objects if obj["reachable_from_tile"])

    return {
        "slot_index": slot_index,
        "level_id_1based": slot_index + 1,
        "world_name": world_name_for_slot(slot_index),
        "level_name": level_name_for_slot(slot_index),
        "light_level": light_level,
        "decoded_level_block_size": len(level_block),
        "texture_mapping": texture_mapping,
        "tiles": tiles,
        "objects": objects,
        "free_lists": free_lists,
        "animation_overlays": overlays,
        "automap": automap,
        "map_notes": notes,
        "summary": {
            "tile_type_counts": dict(sorted(tile_counts.items())),
            "nonzero_object_slots": sum(1 for obj in objects if obj["item_id"] != 0),
            "reachable_object_slots": reachable_count,
            "free_mobile_count": len(free_lists["free_mobile_slots"]),
            "free_static_count": len(free_lists["free_static_slots"]),
            "active_mobile_count": free_lists["active_mobile_count"],
            "animation_overlay_count": len(overlays),
            "map_note_count": len(notes["non_empty"]),
        },
    }


def parse_tiles(block: bytes, texture_mapping: dict, slot_index: int) -> list[dict]:
    if len(block) != TILEMAP_SIZE:
        raise ValueError(f"tilemap slice must be 0x4000 bytes, got {len(block)}")

    mapping = texture_mapping["entries"]
    ceiling_runtime_index = 16 if slot_index == 68 else 15
    tiles = []

    for y in range(64):
        for x in range(64):
            offset = (y * 64 + x) * 4
            word1, word2 = struct.unpack_from("<HH", block, offset)
            raw_type = word1 & 0x0F
            floor_index = (word1 >> 10) & 0x0F
            wall_index = word2 & 0x3F
            object_chain_start = word2 >> 6

            tiles.append(
                {
                    "x": x,
                    "y": y,
                    "display_y": 63 - y,
                    "raw_word1": word1,
                    "raw_word2": word2,
                    "raw_type": raw_type,
                    "type_name": TILE_TYPE_NAMES.get(raw_type, "solid"),
                    "floor_height": ((word1 >> 4) & 0x0F) << 3,
                    "ceiling_height": 128,
                    "slope_height": 8,
                    "special_light_feature": bool((word1 >> 8) & 1),
                    "unused_bit_9": bool((word1 >> 9) & 1),
                    "floor_texture_index": floor_index,
                    "wall_texture_index": wall_index,
                    "texture_floor": mapping[floor_index],
                    "texture_wall": mapping[wall_index],
                    "texture_ceiling_ua": mapping[32],
                    "texture_ceiling_runtime": mapping[ceiling_runtime_index],
                    "object_chain_start": object_chain_start,
                    "no_magic": bool((word1 >> 14) & 1),
                    "door_present": bool((word1 >> 15) & 1),
                }
            )

    return tiles


def parse_objects(
    level_block: bytes, tiles: list[dict], free_lists: dict
) -> list[dict]:
    free_mobile = set(free_lists["free_mobile_slots"])
    free_static = set(free_lists["free_static_slots"])
    active_mobile = set(free_lists["active_mobile_slots"])

    objects = [_parse_object_slot(level_block, slot) for slot in range(1024)]

    tile_refs: dict[int, list[dict]] = defaultdict(list)
    special_refs: dict[int, list[int]] = defaultdict(list)

    for tile in tiles:
        start = tile["object_chain_start"]
        if start:
            _follow_object_chain(
                objects,
                start,
                tile["x"],
                tile["y"],
                tile_refs,
                special_refs,
                path=set(),
            )

    for obj in objects:
        slot = obj["slot"]
        obj["free"] = slot in free_mobile if obj["is_mobile"] else slot in free_static
        obj["active_mobile"] = obj["is_mobile"] and slot in active_mobile
        obj["tile_refs"] = tile_refs.get(slot, [])
        obj["special_link_refs_from"] = special_refs.get(slot, [])
        obj["reachable_from_tile"] = bool(obj["tile_refs"])
        obj["reachable_from_special_link"] = bool(obj["special_link_refs_from"])

    return objects


def _parse_object_slot(level_block: bytes, slot: int) -> dict:
    is_mobile = slot < 0x100
    if is_mobile:
        offset = MOBILE_OBJECT_OFFSET + slot * 27
        record = level_block[offset : offset + 27]
        extra = record[8:27]
    else:
        offset = STATIC_OBJECT_OFFSET + (slot - 0x100) * 8
        record = level_block[offset : offset + 8]
        extra = None

    word0, word1, word2, word3 = struct.unpack_from("<HHHH", record, 0)
    item_id = word0 & 0x01FF
    is_quantity_raw = bool(word0 & 0x8000)
    loader_forces_link = 0x01A0 <= item_id <= 0x01BF or item_id == 0x018B
    is_quantity = is_quantity_raw and not loader_forces_link
    quantity_or_link = word3 >> 6

    return {
        "slot": slot,
        "is_mobile": is_mobile,
        "record_offset": offset,
        "raw_words": [word0, word1, word2, word3],
        "raw_record_hex": record.hex(),
        "item_id": item_id,
        "flags": (word0 >> 9) & 0x0F,
        "enchanted": bool(word0 & 0x1000),
        "hidden": bool(word0 & 0x4000),
        "is_quantity_raw": is_quantity_raw,
        "is_quantity_loader_adjusted": is_quantity,
        "loader_forces_special_link": loader_forces_link,
        "zpos": word1 & 0x7F,
        "heading": (word1 >> 7) & 0x07,
        "in_tile_y": (word1 >> 10) & 0x07,
        "in_tile_x": (word1 >> 13) & 0x07,
        "quality": word2 & 0x3F,
        "next": word2 >> 6,
        "owner": word3 & 0x3F,
        "quantity_or_link": quantity_or_link,
        "quantity_value": quantity_or_link
        if is_quantity and quantity_or_link < 0x200
        else None,
        "special_property_value": (
            quantity_or_link - 0x200
            if is_quantity and quantity_or_link > 0x200
            else None
        ),
        "special_link": quantity_or_link if not is_quantity else None,
        "mobile_extra": _parse_mobile_extra(extra) if extra is not None else None,
    }


def _parse_mobile_extra(extra: bytes) -> dict:
    goal_word = struct.unpack_from("<H", extra, 0x03)[0]
    level_word = struct.unpack_from("<H", extra, 0x05)[0]
    height_word = struct.unpack_from("<H", extra, 0x07)[0]
    home_word = struct.unpack_from("<H", extra, 0x0E)[0]

    return {
        "raw_hex": extra.hex(),
        "npc_hp": extra[0x00],
        "projectile_heading": extra[0x01],
        "unknown_02": extra[0x02],
        "goal": goal_word & 0x0F,
        "goal_target": (goal_word >> 4) & 0xFF,
        "goal_unknown": (goal_word >> 12) & 0x0F,
        "npc_level": level_word & 0x0F,
        "talked_to": bool(level_word & 0x2000),
        "attitude": (level_word >> 14) & 0x03,
        "npc_height": (height_word >> 6) & 0x3F,
        "projectile_source_or_context": extra[0x0A],
        "projectile_speed": extra[0x0C] & 0x0F,
        "projectile_pitch": (extra[0x0C] >> 4) & 0x0F,
        "void_animation": extra[0x0D] & 0x1F,
        "home_y": (home_word >> 4) & 0x3F,
        "home_x": (home_word >> 10) & 0x3F,
        "heading_extra": extra[0x10] & 0x1F,
        "hunger": extra[0x11] & 0x3F,
        "npc_whoami": extra[0x12],
    }


def _follow_object_chain(
    objects: list[dict],
    start: int,
    tile_x: int,
    tile_y: int,
    tile_refs: dict[int, list[dict]],
    special_refs: dict[int, list[int]],
    path: set[int],
) -> None:
    current = start
    while current:
        if current >= len(objects) or current in path:
            return

        path.add(current)
        obj = objects[current]
        tile_refs[current].append({"x": tile_x, "y": tile_y})

        special_link = obj["special_link"]
        if special_link:
            special_refs[special_link].append(current)
            _follow_object_chain(
                objects,
                special_link,
                0xFF,
                0xFF,
                tile_refs,
                special_refs,
                set(path),
            )

        current = obj["next"]


def parse_free_lists(level_block: bytes) -> dict:
    raw_active = level_block[ACTIVE_MOBILE_OFFSET : ACTIVE_MOBILE_OFFSET + 0xFE]
    unknown_7bfa = level_block[UNKNOWN_7BFA_OFFSET : UNKNOWN_7BFA_OFFSET + 6]
    active_count = struct.unpack_from("<H", level_block, COUNTERS_OFFSET)[0]
    mobile_free_count_minus_one = struct.unpack_from(
        "<H", level_block, COUNTERS_OFFSET + 2
    )[0]
    static_free_count_minus_one = struct.unpack_from(
        "<H", level_block, COUNTERS_OFFSET + 4
    )[0]
    magic_marker = struct.unpack_from("<H", level_block, COUNTERS_OFFSET + 6)[0]

    mobile_count = min(mobile_free_count_minus_one + 1, 254)
    static_count = min(static_free_count_minus_one + 1, 768)

    free_mobile = [
        struct.unpack_from("<H", level_block, MOBILE_FREE_OFFSET + i * 2)[0]
        for i in range(mobile_count)
    ]
    free_static = [
        struct.unpack_from("<H", level_block, STATIC_FREE_OFFSET + i * 2)[0]
        for i in range(static_count)
    ]
    active_mobile = list(raw_active[: min(active_count, len(raw_active))])

    return {
        "active_mobile_count": active_count,
        "active_mobile_slots": active_mobile,
        "raw_active_mobile_list_hex": raw_active.hex(),
        "unknown_7bfa_hex": unknown_7bfa.hex(),
        "mobile_free_count_minus_one": mobile_free_count_minus_one,
        "static_free_count_minus_one": static_free_count_minus_one,
        "free_mobile_slots": free_mobile,
        "free_static_slots": free_static,
        "magic_marker": magic_marker,
        "magic_marker_hex": f"0x{magic_marker:04x}",
    }


def parse_animation_overlays(level_block: bytes) -> list[dict]:
    overlays = []
    for index in range(64):
        offset = ANIMATION_OVERLAY_OFFSET + index * 6
        record = level_block[offset : offset + 6]
        if record == b"\x00" * 6:
            continue
        word0, word1, word2 = struct.unpack_from("<HHH", record, 0)
        overlays.append(
            {
                "index": index,
                "raw_words": [word0, word1, word2],
                "object_id": word0 >> 6,
                "frame_count": -1 if word1 == 0xFFFF else word1,
                "tile_x": word2 & 0xFF,
                "tile_y": (word2 >> 8) & 0xFF,
            }
        )
    return overlays


def parse_automap(block: bytes) -> dict:
    if len(block) < 0x1000:
        raise ValueError(f"automap block is too small: {len(block)} bytes")
    cells = []
    for y in range(64):
        for x in range(64):
            raw = block[y * 64 + x]
            cells.append(
                {
                    "x": x,
                    "y": y,
                    "display_y": 63 - y,
                    "raw_byte": raw,
                    "tile_type": raw & 0x0F,
                    "display_type": raw >> 4,
                }
            )
    return {"raw_size": len(block), "cells": cells}


def parse_map_notes(block: bytes | None) -> dict:
    if not block:
        return {"records": [], "non_empty": []}

    records = []
    non_empty = []
    count = len(block) // 54
    for index in range(count):
        offset = index * 54
        record = block[offset : offset + 54]
        text_raw = record[:0x32]
        text = text_raw.split(b"\x00", 1)[0].decode("cp437", errors="replace")
        x = struct.unpack_from("<H", record, 0x32)[0]
        y = struct.unpack_from("<H", record, 0x34)[0]
        decoded = {
            "index": index,
            "text": text,
            "raw_text_hex": text_raw.hex(),
            "raw_x": x,
            "raw_y": y,
            "normalized_y_ua": 200 - y,
            "raw_record_hex": record.hex(),
        }
        records.append(decoded)
        if text and x and y:
            non_empty.append(decoded)

    return {"raw_size": len(block), "records": records, "non_empty": non_empty}


def parse_terrain_dat(block: bytes) -> dict:
    count = min(len(block) // 2, 256)
    entries = [struct.unpack_from("<H", block, i * 2)[0] for i in range(count)]
    labels = {
        0x0000: "normal",
        0x0002: "ankh_or_shrine",
        0x0003: "stairs_up",
        0x0004: "stairs_down",
        0x0005: "pipe",
        0x0006: "grating",
        0x0007: "drain",
        0x0008: "chained_princess",
        0x0010: "water",
        0x0020: "lava",
    }
    return {
        "raw_size": len(block),
        "entries": [
            {
                "texture_id": i,
                "terrain_word": value,
                "terrain_hex": f"0x{value:04x}",
                "label": labels.get(value),
                "is_water": bool(value & 0x0010),
                "is_lava": bool(value & 0x0020 or value & 0x0080),
            }
            for i, value in enumerate(entries)
        ],
    }


def parse_shades_dat(block: bytes) -> dict:
    records = []
    for index in range(len(block) // 12):
        values = struct.unpack_from("<6H", block, index * 12)
        records.append(
            {
                "index": index,
                "shading": values[0],
                "starting_light_level": values[1],
                "start_of_shading_distance": values[2],
                "viewing_distance": values[3],
                "raw_words": list(values),
            }
        )
    return {"raw_size": len(block), "records": records}
