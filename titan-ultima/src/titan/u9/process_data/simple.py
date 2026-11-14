"""Table-driven fixed-layout processes, with and without a process header."""

from __future__ import annotations

__all__ = [
    "CREEPER_GROWTH_PROCESS_TYPE",
    "SIMPLE_PROCESS_LAYOUTS",
    "U9SimpleProcessState",
    "HEADERLESS_PROCESS_LAYOUTS",
    "U9HeaderlessProcessState",
]

import struct
from dataclasses import dataclass

from titan.u9.process_data._base import (
    U9ProcessDataError,
    U9ProcessHeaderState,
    U9ProcessWorldState,
    U9ScriptedProcessState,
    _float32,
    _require_bytes,
    _validate_finite,
    _validate_object_reference_index,
)
from titan.u9.process_data.world import U9SpellState


# Field kinds for table-driven process layouts: struct format and value count.
_SIMPLE_FIELD_FORMATS = {
    "int": ("i", 1),
    "uint": ("I", 1),
    "float": ("f", 1),
    "flag": ("i", 1),  # 32-bit boolean
    "byte_flag": ("B", 1),
    "byte": ("B", 1),
    "ushort": ("H", 1),
    "rgb": ("3B", 3),
    "reference": ("i", 1),  # object-reference index
    "vector": ("3f", 3),
    "quaternion": ("4f", 4),
    "location": ("iih2x", 3),  # integer X/Y, 16-bit Z, two unused bytes
    "text64": ("64s", 1),  # NUL-terminated text in a 64-byte buffer
    "reserved": ("I", 1),
}


@dataclass(frozen=True)
class _SimpleProcessLayout:
    kind: str
    parent: str  # "header", "world", "scripted" or "spell"
    version: int | float | None  # a float version is stored as float32
    fields: tuple[tuple[str, str], ...]
    version_before_header: bool = False


def _simple(
    kind: str,
    parent: str,
    version: int | float | None,
    *fields: tuple[str, str],
    reserved: int = 4,
    version_before_header: bool = False,
) -> _SimpleProcessLayout:
    return _SimpleProcessLayout(
        kind,
        parent,
        version,
        fields + (("reserved", "reserved"),) * reserved,
        version_before_header,
    )


# Type 215's retail load calls the stream writer instead of the reader for
# its last field (the start time). The stream stays in step, so the rest of
# the save loads normally, but the start time is not restored: the growth
# process ends on its first update after loading (tested on a retail save).
CREEPER_GROWTH_PROCESS_TYPE = 215
_PATH_MOVER_FIELDS = (
    ("distance_to_target", "float"),
    ("distance_from_start", "float"),
    ("target_location", "location"),
    ("current_location", "vector"),
    ("mover_speed", "float"),
    ("move_delta", "vector"),
)
# Fixed-size process layouts, each read in retail stream order after the world
# state (and, for "scripted", the scripted-object state). Every layout was
# checked write by write against the retail save routine.
SIMPLE_PROCESS_LAYOUTS: dict[int, _SimpleProcessLayout] = {
    2: _simple(
        "container_use",
        "scripted",
        0,
        ("opening", "byte_flag"),
        ("current_angle", "float"),
        ("direction", "vector"),
        ("has_window", "byte_flag"),
        ("has_skeleton", "flag"),
        reserved=0,
    ),
    3: _simple(
        "object_mover",
        "world",
        1,
        ("parameter", "uint"),
        ("source_object", "reference"),
        ("destination_object", "reference"),
        ("delta_x", "float"),
        ("delta_y", "float"),
        ("delta_z", "float"),
        ("speed", "uint"),
        ("accumulated_time", "uint"),
        ("source_location", "location"),
        ("destination_location", "location"),
        ("skips_first_frame", "flag"),
    ),
    4: _simple(
        "absolute_object_mover",
        "world",
        1,
        ("parameter", "uint"),
        ("source_object", "reference"),
        ("speed", "uint"),
        ("accumulated_time", "uint"),
        ("delta", "location"),
        ("count", "int"),
        ("blocked", "int"),
        ("skips_first_frame", "flag"),
    ),
    5: _simple(
        "object_turner",
        "world",
        1,
        ("parameter", "uint"),
        ("source_object", "reference"),
        ("base_orientation", "quaternion"),
        ("delta", "float"),
        ("speed", "uint"),
        ("accumulated_time", "uint"),
        ("angle", "float"),
        ("axis", "int"),
        ("exit_state", "int"),
        ("skips_first_frame", "flag"),
    ),
    7: _simple(
        "object_fade",
        "world",
        3,
        ("source_object", "reference"),
        ("accumulated_time", "uint"),
        ("command", "int"),
        ("saved_parameter", "uint"),
        ("maximum_time", "float"),
        ("starting_translucency", "uint"),
        ("ending_translucency", "uint"),
        ("saved_translucency", "uint"),
        ("was_translucent", "flag"),
        ("was_fixed_in_place", "uint"),
    ),
    8: _simple(
        "object_scale",
        "world",
        3,
        ("source_object", "reference"),
        ("accumulated_time", "uint"),
        ("command", "int"),
        ("saved_parameter", "uint"),
        ("maximum_time", "float"),
        ("starting_scale", "vector"),
        ("ending_scale", "vector"),
        ("was_fixed_in_place", "uint"),
    ),
    9: _simple(
        "delayed_create",
        "world",
        1,
        ("source_object", "reference"),
        ("command", "int"),
        ("location", "location"),
        ("delay", "int"),
        ("parameter", "uint"),
    ),
    10: _simple(
        "object_fade_out",
        "world",
        2,
        ("object", "reference"),
        ("idle_time", "uint"),
        ("translucency_rate", "uint"),
        ("sink_rate", "uint"),
        ("sink_delay", "uint"),
        ("flags", "int"),
        ("current_translucency_rate", "uint"),
        ("current_sink_rate", "uint"),
    ),
    11: _simple(
        "object_fade_in",
        "world",
        1,
        ("object", "reference"),
        ("idle_time", "uint"),
        ("translucency_rate", "uint"),
        ("current_translucency_rate", "uint"),
        ("old_translucency", "uint"),
        ("was_translucent", "flag"),
    ),
    12: _simple(
        "object_path_mover",
        "world",
        1,
        ("object", "reference"),
        ("flags", "uint"),
        *_PATH_MOVER_FIELDS,
        ("rotation_axis", "vector"),
        ("rotation_speed", "float"),
        ("rotation_angle", "float"),
        ("time_since_update", "uint"),
        ("starting_location", "vector"),
        ("last_location", "vector"),
        ("orientation", "quaternion"),
        ("exit_callback", "int"),
        ("exit_callback_value_1", "uint"),
        ("exit_callback_value_2", "uint"),
        ("update_callback", "int"),
        ("update_callback_value_1", "uint"),
        ("update_callback_value_2", "uint"),
    ),
    14: _simple(
        "lever_animation",
        "scripted",
        1,
        ("current_angle", "int"),
        ("target_angle", "int"),
    ),
    56: _simple("bellows_animation", "scripted", 0, ("down", "byte_flag"), reserved=0),
    59: _simple(
        "drawer_chest_animation",
        "scripted",
        1,
        ("percentage_step", "float"),
        ("section", "uint"),
        ("auxiliary_value", "int"),
        ("flag_value", "uint"),
        ("current_percentage", "float"),
        ("full_open_offset", "vector"),
        ("drawer_step", "vector"),
    ),
    60: _simple(
        "wardrobe_animation",
        "scripted",
        2,
        ("open_angle_limit", "int"),
        ("open_angle_step", "int"),
        ("open", "byte_flag"),
    ),
    63: _simple(
        "portcullis_animation",
        "scripted",
        2,
        ("elapsed_time", "uint"),
        ("loop_speed", "int"),
        ("z_offset", "float"),
        ("counter", "int"),
        ("total_z_offset", "float"),
        ("initial_z", "uint"),
        ("loop_count", "int"),
        ("state", "uint"),
    ),
    64: _simple(
        "stone_block",
        "scripted",
        1,
        ("elapsed_time", "uint"),
        ("maximum_speed", "uint"),
        ("target_z", "int"),
        ("failed_z", "int"),
        ("old_z", "uint"),
    ),
    65: _simple(
        "attractor_repeller",
        "scripted",
        1,
        ("distance", "int"),
        ("elapsed_time", "uint"),
        ("pull_amount", "int"),
    ),
    66: _simple(
        "fireball",
        "scripted",
        1,
        ("elapsed_time", "uint"),
        ("orientation", "quaternion"),
        ("target_location", "location"),
    ),
    67: _simple("button_use", "scripted", 1, ("time", "uint")),
    72: _simple(
        "scripted_floating_object",
        "scripted",
        1,
        ("initial_location", "location"),
        ("delta_time", "float"),
        ("delta_time_2", "float"),
    ),
    73: _simple(
        "path_follower",
        "world",
        1,
        ("source_object", "reference"),
        ("target_path_marker", "reference"),
        ("starting_link", "int"),
        ("target_link", "int"),
        ("speed", "uint"),
        ("accumulated_time", "uint"),
        ("delta", "vector"),
        ("starting_location", "location"),
        ("total_time", "float"),
        ("skips_first_frame", "flag"),
    ),
    74: _simple(
        "floating_object",
        "world",
        1,
        ("source_object", "reference"),
        ("delta_time", "float"),
        ("delta_time_2", "float"),
        ("initial_location", "location"),
        ("reversed", "flag"),
        ("xy_variation", "float"),
        ("z_variation", "float"),
    ),
    81: _simple(
        "globe_pedestal",
        "scripted",
        1,
        ("elapsed_time", "uint"),
        ("globe", "reference"),
        ("target_location", "location"),
        ("original_location", "location"),
        ("maximum_time", "float"),
        ("image_sequence_number", "uint"),
    ),
    101: _simple(
        "magic_eye",
        "scripted",
        1,
        ("tracked_object", "reference"),
        ("update_time", "uint"),
        ("state", "int"),
        ("eyelid_update_time", "uint"),
        ("temporarily_active", "flag"),
    ),
    165: _simple("element_fade_out", "world", None, reserved=0),
    203: _simple(
        "delayed_conceal",
        "world",
        1,
        ("source_object", "reference"),
        ("command", "int"),
        ("accumulated_time", "uint"),
        ("maximum_time", "uint"),
        ("was_translucent", "flag"),
        ("saved_translucency", "uint"),
    ),
    204: _simple("world_only", "world", None, reserved=0),
    205: _simple(
        "head_turn",
        "world",
        1,
        ("source_object", "reference"),
        ("tracking_object", "reference"),
        ("accumulated_time", "uint"),
        ("maximum_time", "uint"),
        ("has_head", "flag"),
        reserved=3,
    ),
    207: _simple(
        "fire_damage",
        "world",
        0,
        ("source_object", "reference"),
        ("fire_object", "reference"),
        ("accumulated_time", "uint"),
    ),
    208: _simple("blood_spurt", "world", None, reserved=0),
    209: _simple(
        "windmill_animation",
        "scripted",
        None,
        ("maximum_yaw_difference", "float"),
        ("rpm", "float"),
        reserved=0,
    ),
}
_SPELL_CONSTANT_KINDS = {
    108: "gust_spell",
    109: "ignite_spell",
    110: "douse_spell",
    112: "telekinesis_spell",
    113: "light_spell",
    114: "light_heal_spell",
    115: "crystal_barrier_spell",
    116: "lightning_bolt_spell",
    118: "cure_spell",
    123: "charm_spell",
    124: "ethereal_sight_spell",
    125: "day_spell",
    126: "freeze_spell",
    130: "full_heal_spell",
    132: "invisibility_spell",
    133: "ring_of_fire_spell",
    134: "mana_breath_spell",
    136: "teleport_spell",
    138: "frost_storm_spell",
}
SIMPLE_PROCESS_LAYOUTS.update(
    {t: _simple(kind, "spell", 1) for t, kind in _SPELL_CONSTANT_KINDS.items()}
)
SIMPLE_PROCESS_LAYOUTS.update(
    {
        107: _simple(
            "stone_spell",
            "spell",
            1,
            ("placeholder_object", "reference"),
            ("location", "vector"),
            ("stone_location", "vector"),
        ),
        111: _simple(
            "create_reagents_spell",
            "spell",
            1,
            ("reagent_location", "vector"),
            ("reagent_orientation", "quaternion"),
            ("reagent_type", "ushort"),
        ),
        117: _simple(
            "infernal_armor_spell",
            "spell",
            1,
            ("proximity_damage_timer", "float"),
            ("fade_armor_process_id", "int"),
        ),
        119: _simple(
            "meteorite_spell", "spell", 1, ("last_meteorite_location", "vector")
        ),
        121: _simple("fireball_spell", "spell", 1, ("location", "vector")),
        122: _simple("fog_spell", "spell", None, reserved=0),
        127: _simple("summon_undead_spell", "spell", 1, ("undead", "reference")),
        128: _simple("levitate_spell", "spell", 1, ("platform", "reference")),
        152: _simple(
            "blow_light_objects_away",
            "world",
            1,
            ("direction", "vector"),
            ("maximum_force", "float"),
            ("maximum_weight", "byte"),
            ("offset_distance", "float"),
            ("orientation", "quaternion"),
            ("effect_object", "reference"),
            ("radius", "int"),
        ),
        153: _simple(
            "fade_armor",
            "world",
            1,
            ("burn_timer", "float"),
            ("caster", "reference"),
            ("direction", "int"),
            ("calling_process_id", "int"),
        ),
        169: _simple(
            "big_stone_spell",
            "spell",
            1,
            ("placeholder_object", "reference"),
            ("location", "vector"),
            ("stone_location", "vector"),
        ),
    }
)
SIMPLE_PROCESS_LAYOUTS.update(
    {
        18: _simple(
            "turn_to_angle",
            "header",
            2,
            ("npc_number", "int"),
            ("angle", "float"),
            ("duration_npc_offset", "int"),
            ("termination_npc_offset", "int"),
            ("termination_value", "int"),
            ("turning_speed", "float"),
            ("old_turn_threshold", "float"),
        ),
        # Fields named only as far as retail establishes them.
        163: _simple(
            "poison_camera",
            "world",
            _float32(1.4),
            ("current_object", "reference"),
            ("flag_1", "byte"),
            ("flag_2", "byte"),
            ("pause_delta", "int"),
            ("parameter_1", "float"),
            ("parameter_2", "float"),
            reserved=0,
            version_before_header=True,
        ),
        # No source save; named from one retail record (the 16-bit value was
        # 509, in the NPC-number range; the zero words are kept raw).
        71: _simple(
            "arrow_projectile",
            "world",
            1,
            ("short_value", "ushort"),
            ("arrow_object", "reference"),
            ("position", "vector"),
            ("word_1", "uint"),
            ("parameter_1", "float"),
            ("word_2", "uint"),
            reserved=0,
        ),
        195: _simple(
            "underwater_camera",
            "world",
            _float32(1.3),
            ("current_object", "reference"),
            ("original_horizontal_fov", "float"),
            ("original_vertical_fov", "float"),
            ("horizontal_angle", "float"),
            ("vertical_angle", "float"),
            ("horizontal_period", "float"),
            ("vertical_period", "float"),
            ("horizontal_variance", "float"),
            ("vertical_variance", "float"),
            ("stopping", "byte_flag"),
            ("flag_2", "byte"),
            reserved=0,
            version_before_header=True,
        ),
        # Layouts read from the retail save routines (2026-10-01); none of
        # these types occurs in the checked saves.
        17: _simple(
            "straight_line_path",
            "header",
            2,
            ("npc_number", "int"),
            ("target_x", "int"),
            ("target_y", "int"),
            ("speed", "int"),
            ("careful_walk", "flag"),
            ("npc_record_offset", "int"),  # -1 when there is no NPC
            ("termination_test", "int"),
            ("last_angle", "float"),
            ("target_ray", "vector"),
            ("error_tolerance", "float"),
            ("may_fail", "flag"),
            ("wants_to_exit", "flag"),
            ("success_state", "int"),
        ),
        19: _simple(
            "safe_item_rotation",
            "header",
            0,
            ("base_object", "reference"),
            ("target_object", "reference"),
            ("rotation_axis", "vector"),
            ("description", "text64"),
            reserved=0,
        ),
        20: _simple(
            "explosion",
            "header",
            1,
            ("explosion_object", "reference"),
            ("time", "int"),
            ("map_number", "int"),
        ),
        21: _simple(
            "missile_launcher",
            "header",
            2,
            ("launcher_object", "reference"),
            ("parameter", "int"),
            ("link", "int"),
            ("missile_1", "reference"),
            ("missile_2", "reference"),
            ("explodes", "flag"),
            ("map_number", "int"),
            ("fired_missile", "int"),
            ("missile_type", "int"),
            ("own_link", "int"),
        ),
        69: _simple(
            "delayed_throw",
            "header",
            1,
            ("thrown_object", "reference"),
            ("delay", "uint"),
        ),
        131: _simple(
            "death_spell",
            "spell",
            1,
            ("short_1", "ushort"),
            ("byte_1", "byte"),
            ("word_1", "uint"),
            ("word_2", "uint"),
            ("word_3", "uint"),
            ("word_4", "uint"),
            ("short_2", "ushort"),
        ),
        137: _simple(
            "summon_daemon_spell",
            "spell",
            1,
            ("object_1", "reference"),
            ("word_1", "uint"),
        ),
        139: _simple(
            "earthquake_spell", "spell", 1, ("word_1", "uint"), ("word_2", "uint")
        ),
        140: _simple(
            "lightning_storm_spell",
            "spell",
            1,
            ("object_1", "reference"),
            ("object_2", "reference"),
            ("word_1", "uint"),
        ),
        141: _simple(
            "inferno_spell",
            "spell",
            1,
            ("word_1", "uint"),
            ("word_2", "uint"),
            ("word_3", "uint"),
        ),
        154: _simple(
            "fire_ring_watcher",
            "world",
            1,
            ("object_1", "reference"),
            ("object_2", "reference"),
            ("word_1", "uint"),
        ),
        # Venom effect: a 30-second timer on a target.
        210: _simple(
            "venom_effect",
            "world",
            0,
            ("object_1", "reference"),
            ("word_1", "uint"),
            ("word_2", "uint"),
            ("word_3", "uint"),
            ("word_4", "uint"),
            reserved=0,
        ),
        # A creeper's plant growing from 0.25 to 0.75 scale. Retail does not
        # restore its start time on load (see CREEPER_GROWTH_PROCESS_TYPE).
        CREEPER_GROWTH_PROCESS_TYPE: _simple(
            "creeper_plant_growth",
            "world",
            1,
            ("plant", "reference"),
            ("scale", "float"),
            ("growth_per_millisecond", "float"),
            ("start_time", "uint"),  # saved as elapsed system-tick milliseconds
            reserved=0,
        ),
        212: _simple(
            "avatar_torch",
            "world",
            0,
            ("object_1", "reference"),
            ("object_2", "reference"),
            ("parameter_1", "float"),
            ("parameter_2", "float"),
            ("elapsed_time", "uint"),
            ("parameter_3", "float"),
            ("color_1", "rgb"),
            ("color_2", "rgb"),
            ("counter", "int"),
            reserved=0,
        ),
    }
)


def _decode_simple_fields(
    fields: tuple[tuple[str, str], ...],
    raw: tuple,
    label: str,
    object_reference_count: int,
) -> tuple[tuple[tuple[str, object], ...], tuple[int, ...]]:
    """Convert unpacked table-driven fields to ``(name, value)`` pairs and
    the reserved words, validating floats, flags and object references."""
    values: list[tuple[str, object]] = []
    reserved: list[int] = []
    cursor = 0
    for name, field_kind in fields:
        count = _SIMPLE_FIELD_FORMATS[field_kind][1]
        chunk = raw[cursor : cursor + count]
        cursor += count
        value: object = chunk[0] if count == 1 else tuple(chunk)
        if field_kind in ("float", "vector", "quaternion"):
            _validate_finite(tuple(chunk), f"{label} {name}")
        elif field_kind in ("flag", "byte_flag"):
            if chunk[0] not in (0, 1):
                raise U9ProcessDataError(f"invalid {label} {name} flag {chunk[0]}")
            value = bool(chunk[0])
        elif field_kind == "reference":
            _validate_object_reference_index(
                chunk[0], object_reference_count, f"{label} {name}"
            )
        elif field_kind == "text64":
            value = chunk[0].split(b"\0", 1)[0].decode("cp1252", errors="replace")
        if field_kind == "reserved":
            reserved.append(chunk[0])
        else:
            values.append((name, value))
    return tuple(values), tuple(reserved)


def _version_format(layout: _SimpleProcessLayout) -> str:
    return "f" if isinstance(layout.version, float) else "i"


def _simple_layout_struct(layout: _SimpleProcessLayout) -> struct.Struct:
    version = (
        _version_format(layout)
        if layout.version is not None and not layout.version_before_header
        else ""
    )
    return struct.Struct(
        "<" + version + "".join(_SIMPLE_FIELD_FORMATS[k][0] for _, k in layout.fields)
    )


_SIMPLE_LAYOUT_STRUCTS = {
    process_type: _simple_layout_struct(layout)
    for process_type, layout in SIMPLE_PROCESS_LAYOUTS.items()
}


@dataclass(frozen=True)
class U9SimpleProcessState:
    """A fixed-size process read from :data:`SIMPLE_PROCESS_LAYOUTS`.

    ``kind`` names the layout (for example ``path_follower``). ``values``
    holds the named fields in stream order: vectors and quaternions as float
    tuples, locations as integer ``(x, y, z)`` tuples, references as
    object-reference indices, flags as booleans. The trailing reserved words
    are in ``reserved``. Index a record by field name (``record["speed"]``).
    ``world_state`` is ``None`` for layouts whose save writes only the common
    process header.
    """

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState | None
    scripted_state: U9ScriptedProcessState | None
    kind: str
    version: int | float | None
    values: tuple[tuple[str, object], ...]
    reserved: tuple[int, ...]
    offset: int
    end_offset: int
    spell_state: U9SpellState | None = None

    def __getitem__(self, name: str) -> object:
        for key, value in self.values:
            if key == name:
                return value
        raise KeyError(name)

    @property
    def fields(self) -> dict[str, object]:
        return dict(self.values)

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9SimpleProcessState:
        _require_bytes(data, offset, 4, "process type")
        (process_type,) = struct.unpack_from("<i", data, offset)
        layout = SIMPLE_PROCESS_LAYOUTS.get(process_type)
        if layout is None:
            raise U9ProcessDataError(
                f"process type {process_type} is not a table-driven process"
            )
        layout_struct = _SIMPLE_LAYOUT_STRUCTS[process_type]
        label = f"{layout.kind.replace('_', '-')} process"
        version = None
        if layout.version_before_header:
            _require_bytes(data, offset + 4, 4, label)
            (version,) = struct.unpack_from(
                "<" + _version_format(layout), data, offset + 4
            )
        header = U9ProcessHeaderState.from_prefixed_bytes(
            data, offset, prefix_size=8 if layout.version_before_header else 4
        )
        world_state = None
        payload_offset = header.end_offset
        if layout.parent != "header":
            world_state = U9ProcessWorldState.from_bytes(
                data, payload_offset, object_reference_count=object_reference_count
            )
            payload_offset = world_state.end_offset
        scripted_state = None
        if layout.parent == "scripted":
            scripted_state = U9ScriptedProcessState.from_bytes(
                data, payload_offset, object_reference_count=object_reference_count
            )
            payload_offset = scripted_state.end_offset
        spell_state = None
        if layout.parent == "spell":
            spell_state = U9SpellState.from_bytes(
                data, payload_offset, object_reference_count=object_reference_count
            )
            payload_offset = spell_state.end_offset
        _require_bytes(data, payload_offset, layout_struct.size, label)
        raw = layout_struct.unpack_from(data, payload_offset)
        cursor = 0
        if layout.version is not None:
            if not layout.version_before_header:
                version = raw[0]
                cursor = 1
            if version != layout.version:
                raise U9ProcessDataError(
                    f"unsupported {label} version {version} at 0x{payload_offset:X}"
                )
        values, reserved = _decode_simple_fields(
            layout.fields, raw[cursor:], label, object_reference_count
        )
        return cls(
            header=header,
            world_state=world_state,
            scripted_state=scripted_state,
            kind=layout.kind,
            version=version,
            values=values,
            reserved=reserved,
            offset=offset,
            end_offset=payload_offset + layout_struct.size,
            spell_state=spell_state,
        )


# Process types whose save routine writes no common process header: the
# record is the type word followed only by these fields (none for the two
# spells, whose save routines are empty).
HEADERLESS_PROCESS_LAYOUTS: dict[int, _SimpleProcessLayout] = {
    135: _simple("time_stop_spell", "none", None, reserved=0),
    151: _simple("armageddon_spell", "none", None, reserved=0),
    214: _simple(
        "delayed_item_teleport",
        "none",
        0,
        ("object_1", "reference"),
        ("word_1", "uint"),
        ("word_2", "uint"),
        ("word_3", "uint"),
        ("word_4", "uint"),
    ),
}


@dataclass(frozen=True)
class U9HeaderlessProcessState:
    """A process whose save writes no common header (types 135, 151, 214).

    ``header`` and ``world_state`` are always ``None``; fields follow the
    type word directly, as in :class:`U9SimpleProcessState`.
    """

    process_type: int
    kind: str
    version: int | float | None
    values: tuple[tuple[str, object], ...]
    reserved: tuple[int, ...]
    offset: int
    end_offset: int
    header: None = None
    world_state: None = None

    def __getitem__(self, name: str) -> object:
        for key, value in self.values:
            if key == name:
                return value
        raise KeyError(name)

    @property
    def fields(self) -> dict[str, object]:
        return dict(self.values)

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9HeaderlessProcessState:
        _require_bytes(data, offset, 4, "process type")
        (process_type,) = struct.unpack_from("<i", data, offset)
        layout = HEADERLESS_PROCESS_LAYOUTS.get(process_type)
        if layout is None:
            raise U9ProcessDataError(
                f"process type {process_type} is not a headerless process"
            )
        layout_struct = _simple_layout_struct(layout)
        label = f"{layout.kind.replace('_', '-')} process"
        payload_offset = offset + 4
        _require_bytes(data, payload_offset, layout_struct.size, label)
        raw = layout_struct.unpack_from(data, payload_offset)
        version = None
        cursor = 0
        if layout.version is not None:
            version = raw[0]
            cursor = 1
            if version != layout.version:
                raise U9ProcessDataError(
                    f"unsupported {label} version {version} at 0x{payload_offset:X}"
                )
        values, reserved = _decode_simple_fields(
            layout.fields, raw[cursor:], label, object_reference_count
        )
        return cls(
            process_type,
            layout.kind,
            version,
            values,
            reserved,
            offset,
            payload_offset + layout_struct.size,
        )
