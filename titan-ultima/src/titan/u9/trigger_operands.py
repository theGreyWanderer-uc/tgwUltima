"""Typed operand views for Ultima 9 trigger instructions.

Every trigger instruction stores ``opcode``, ``arg0`` (u8), ``arg1`` (u16) and
``arg2`` (u16). This module reads those stored words; it never changes them.
Each view carries an evidence level:

``retail_confirmed``
    Read in the retail 1.19F executable: the handler, the helpers that receive
    ``arg2``, and the code that runs after dispatch. Bits a confirmed layout
    does not name are unread in the traced paths. Deferred process callbacks
    must also be checked: the G-TRG-3 audit corrected earlier movement omissions.
``retail_corroborated``
    The layout's masks agree with constants in the retail handler, or the
    handler uses ``arg2`` whole, but the layout has not been traced end to end.
    Bits it does not name are unclassified, not proven unused.

Three families are decoded:

* **Target selection** (:func:`target_selection`). 64 commands can act on each
  object a shared search finds; speech also uses it unless its type is 215.
  For them ``arg0 & 0x1F`` selects a link: 0 means no link filter, otherwise
  the link searched is the executor's current link context plus
  the value minus 16. ``arg1 & 0x1FFF`` is the object type to find, where
  ``0x1FFF`` means any type. The upper bits of both words are never set in
  the shipped 1.19F or 1.19H scripts.
* **Branches** (:func:`branch`). Labels are small numbers matched against
  ``0x16`` "mark branch destination" instructions; label 0 ends the script.
* **Parameters** (:func:`parameters`). The remaining ``arg2`` fields per
  command, as named bit fields.

Example::

    from titan.u9.triggers import U9Triggers

    for record in U9Triggers.from_file("static/triggers.flx").trigger(308).records:
        print(record.semantic_name, record.target_selection, record.branch,
              record.parameters)
"""

from __future__ import annotations

__all__ = [
    "ANY_TARGET_TYPE",
    "BRANCH_COMPARE_OPERATORS",
    "RETAIL_CORROBORATED",
    "RETAIL_CONFIRMED",
    "STATUS_BIT_OBJECT_FLAGS",
    "TARGETED_OPCODES",
    "U9TriggerBranch",
    "U9TriggerField",
    "U9TriggerParameters",
    "U9TriggerTarget",
    "branch",
    "operand_summary",
    "parameter_layout",
    "parameters",
    "target_selection",
]

from dataclasses import dataclass

RETAIL_CONFIRMED = "retail_confirmed"
RETAIL_CORROBORATED = "retail_corroborated"

WORD_MASK = 0xFFFF
LINK_SELECTOR_MASK = 0x1F
LINK_SELECTOR_BIAS = 16
TARGET_TYPE_MASK = 0x1FFF
ANY_TARGET_TYPE = 0x1FFF

# Commands with a shared target-search path; 0x21 requires a valid count.
# Speech's conditional search is handled separately by target_selection.
TARGETED_OPCODES = frozenset(
    {
        0x01,
        0x02,
        0x03,
        0x04,
        0x05,
        0x06,
        0x07,
        0x08,
        0x09,
        0x0A,
        0x0B,
        0x0C,
        0x0F,
        0x10,
        0x15,
        0x16,
        0x18,
        0x19,
        0x1A,
        0x1B,
        0x1C,
        0x1D,
        0x1E,
        0x20,
        0x21,
        0x22,
        0x23,
        0x24,
        0x25,
        0x26,
        0x27,
        0x28,
        0x29,
        0x2B,
        0x2D,
        0x2E,
        0x32,
        0x38,
        0x39,
        0x3B,
        0x3C,
        0x3D,
        0x40,
        0x41,
        0x42,
        0x43,
        0x44,
        0x45,
        0x46,
        0x47,
        0x48,
        0x49,
        0x4A,
        0x4E,
        0x4F,
        0x50,
        0x51,
        0x54,
        0x55,
        0x56,
        0x57,
        0x59,
        0x5A,
        0x5D,
    }
)

# Status bits used by opcodes 0x06-0x08, 0x29 and 0x3B, and the object flag
# each one sets, clears, inverts or tests (retail tables at 0x7930D8/0x793108).
STATUS_BIT_OBJECT_FLAGS = {
    0x0001: 0x00002,
    0x0002: 0x00040,
    0x0004: 0x00008,
    0x0008: 0x00100,
    0x0020: 0x00400,
    0x0100: 0x04000,
    0x0200: 0x08000,
    0x0400: 0x10000,
    0x0800: 0x20000,
    0x1000: 0x40000,
}

BRANCH_COMPARE_OPERATORS = {
    0: "equal",
    1: "not_equal",
    2: "greater",
    3: "less",
    4: "greater_or_equal",
    5: "less_or_equal",
}


# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class U9TriggerTarget:
    """Which objects a targeted command acts on, from ``arg0`` and ``arg1``."""

    link_selector: int
    target_type: int
    reserved_arg0_bits: int
    reserved_arg1_bits: int
    evidence: str = RETAIL_CONFIRMED

    @property
    def link_delta(self) -> int | None:
        """Offset from the executor's link context, or ``None`` for no filter."""
        if self.link_selector == 0:
            return None
        return self.link_selector - LINK_SELECTOR_BIAS

    @property
    def any_type(self) -> bool:
        """True when the search matches objects of every type (link only)."""
        return self.target_type == ANY_TARGET_TYPE


def target_selection(opcode: int, arg0: int, arg1: int) -> U9TriggerTarget | None:
    """Target-selection view for a targeted command, else ``None``."""
    if opcode not in TARGETED_OPCODES and not (
        opcode == 0x30 and arg1 & TARGET_TYPE_MASK != 215
    ):
        return None
    return U9TriggerTarget(
        link_selector=arg0 & LINK_SELECTOR_MASK,
        target_type=arg1 & TARGET_TYPE_MASK,
        reserved_arg0_bits=arg0 & ~LINK_SELECTOR_MASK & 0xFF,
        reserved_arg1_bits=arg1 & ~TARGET_TYPE_MASK & WORD_MASK,
    )


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------

BRANCH_ON_MATCH_OPCODES = frozenset(
    {
        0x0E,
        0x29,
        0x3A,
        0x3B,
        0x45,
        0x46,
        0x47,
        0x48,
        0x4B,
        0x53,
        0x58,
        0x5A,
        0x5B,
        0x61,
        0x64,
    }
)
COUNT_COMPARE_OPCODES = frozenset({0x15, 0x2D, 0x2F})
LABEL_OPCODE = 0x16
JUMP_OPCODE = 0x17
LOCAL_VALUE_BRANCH_OPCODE = 0x1A
MISSING_TINT_BRANCH_OPCODE = 0x4F


@dataclass(frozen=True)
class U9TriggerBranch:
    """The branch encoded in ``arg2``.

    ``form`` is one of ``label`` (this instruction is a destination),
    ``jump`` (unconditional), ``on_match`` (taken when the command's test
    matched any target), ``count_compare`` (taken when the number of targets
    compares true against ``compare_count``), ``local_value`` or
    ``missing_tint``. ``label`` 0 means "end of script" for every form except
    ``label``. ``mask`` covers the ``arg2`` bits the branch uses.
    """

    form: str
    label: int
    mask: int
    compare_code: int | None = None
    compare_count: int | None = None
    evidence: str = RETAIL_CONFIRMED

    @property
    def compare_operator(self) -> str | None:
        """Named comparison for ``count_compare`` (codes 6 and 7 never branch)."""
        if self.compare_code is None:
            return None
        return BRANCH_COMPARE_OPERATORS.get(self.compare_code)

    @property
    def ends_script(self) -> bool:
        return self.form != "label" and self.label == 0


def branch(opcode: int, arg2: int) -> U9TriggerBranch | None:
    """Branch view for a branching or label instruction, else ``None``."""
    if opcode == LABEL_OPCODE:
        return U9TriggerBranch("label", arg2, WORD_MASK)
    if opcode == JUMP_OPCODE:
        return U9TriggerBranch("jump", arg2, WORD_MASK)
    if opcode in BRANCH_ON_MATCH_OPCODES:
        return U9TriggerBranch("on_match", arg2 >> 13, 0xE000)
    if opcode in COUNT_COMPARE_OPCODES:
        return U9TriggerBranch(
            "count_compare",
            (arg2 >> 5) & 0x7,
            0xFFE7,
            compare_code=arg2 & 0x7,
            compare_count=arg2 >> 8,
        )
    if opcode == LOCAL_VALUE_BRANCH_OPCODE:
        return U9TriggerBranch("local_value", (arg2 >> 1) & 0x7, 0x000E)
    if opcode == MISSING_TINT_BRANCH_OPCODE:
        return U9TriggerBranch("missing_tint", 1 if arg2 & 0x8000 else 0, 0x8000)
    return None


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class U9TriggerField:
    """One named ``arg2`` bit field; its value is ``(arg2 & mask) >> shift``."""

    name: str
    mask: int

    @property
    def shift(self) -> int:
        return (self.mask & -self.mask).bit_length() - 1

    def value(self, arg2: int) -> int:
        return (arg2 & self.mask) >> self.shift


@dataclass(frozen=True)
class _Layout:
    fields: tuple[U9TriggerField, ...]
    evidence: str


@dataclass(frozen=True)
class U9TriggerParameters:
    """Named ``arg2`` fields for one instruction, with the bits left over.

    ``unclassified_bits`` are the stored bits no field or branch names. For a
    ``retail_confirmed`` layout they are unread in the traced retail paths.
    """

    fields: tuple[tuple[str, int], ...]
    unclassified_bits: int
    evidence: str

    def get(self, name: str) -> int | None:
        return next((value for field, value in self.fields if field == name), None)

    def as_dict(self) -> dict[str, int]:
        return dict(self.fields)


def _f(*pairs: tuple[str, int]) -> tuple[U9TriggerField, ...]:
    return tuple(U9TriggerField(name, mask) for name, mask in pairs)


_C = RETAIL_CONFIRMED
_W = WORD_MASK
_STATUS = ("status_bits", 0x1F2F)
_EFFECT = (("fade", 0x0003), ("scale", 0x000C), ("sound", 0x00F0))
_ROTATE = (
    ("degrees", 0x01FF),
    ("negative", 0x0200),
    ("method", 0x0400),
    ("duration", 0xF800),
)
_STEP = (
    ("x_step", 0x0003),
    ("y_step", 0x000C),
    ("z_step", 0x0030),
    ("collision_mode", 0x00C0),
    ("speed_scale", 0x0100),
    ("step_count", 0xFE00),
)
_SCALE_AXES = (("skip_x", 0x1000), ("skip_y", 0x2000), ("skip_z", 0x4000))

_LAYOUTS: dict[int, _Layout] = {
    0x00: _Layout((), _C),
    0x01: _Layout(_f(("behavior", _W)), _C),
    0x02: _Layout(_f(("link", _W)), _C),
    0x03: _Layout(_f(("property_kind", 0x000F), ("property_value", 0xFFF0)), _C),
    0x04: _Layout(_f(("object_kind", _W)), _C),
    0x05: _Layout(_f(("visual_state", _W)), _C),
    0x06: _Layout(_f(_STATUS), _C),
    0x07: _Layout(_f(_STATUS), _C),
    0x08: _Layout(_f(_STATUS), _C),
    0x09: _Layout(_f(*_EFFECT), _C),
    0x0A: _Layout(_f(*_EFFECT, ("placement", 0xC000)), _C),
    0x0B: _Layout(_f(*_EFFECT), _C),
    0x0C: _Layout(_f(*_EFFECT, ("placement", 0xC000)), _C),
    0x0D: _Layout(_f(("datum_index", 0x01FF), ("datum_value", 0xFE00)), _C),
    0x0E: _Layout(
        _f(
            ("datum_index", 0x01FF),
            ("datum_value", 0x0E00),
            ("below", 0x1000),
        ),
        _C,
    ),
    0x0F: _Layout(
        _f(
            ("effect", 0x003F),
            ("effect_flag", 0x0040),
            ("magic_kind", 0x0380),
            ("xy_scale_index", 0x1C00),
            ("z_scale_index", 0xE000),
        ),
        _C,
    ),
    0x10: _Layout((), _C),
    0x11: _Layout(_f(("link", _W)), _C),
    0x12: _Layout(_f(("amount", 0x7FFF), ("subtract", 0x8000)), _C),
    0x13: _Layout((), _C),
    0x14: _Layout(
        _f(
            ("include_source", 0x0001),
            ("include_hidden", 0x0002),
            ("include_outside_fast_area", 0x0004),
        ),
        _C,
    ),
    0x15: _Layout((), _C),
    0x16: _Layout((), _C),
    0x17: _Layout((), _C),
    0x18: _Layout(_f(("local_value", _W)), _C),
    0x19: _Layout((), _C),
    0x1A: _Layout(_f(("below", 0x0001), ("threshold", 0x0FF0)), _C),
    0x1B: _Layout(
        _f(
            ("duration", 0x001F),
            ("retry_when_blocked", 0x0020),
            ("no_vertical", 0x0040),
            ("ignore_collision", 0x0080),
            ("destination_link", 0xFF00),
        ),
        _C,
    ),
    0x1C: _Layout(
        _f(
            ("placement_mode", 0x0003),
            ("copy_marker_orientation", 0x0004),
            ("retain_altitude", 0x0008),
            ("destination_link", 0xFFF0),
        ),
        _C,
    ),
    0x1D: _Layout(_f(("duration", 0xF800)), _C),
    0x1E: _Layout(
        _f(
            ("destination_link", 0x00FF),
            ("launch_mode", 0x0300),
            ("launch_flag", 0x0400),
        ),
        _C,
    ),
    0x1F: _Layout(
        _f(
            ("map_number", 0x00FF),
            ("effect_variant", 0x0300),
            ("retain_running_tasks", 0x4000),
            ("relative_position", 0x8000),
        ),
        _C,
    ),
    0x20: _Layout(_f(("sound_category", 0x00FF)), _C),
    0x21: _Layout(_f(("target_count", _W)), _C),
    0x22: _Layout(_f(*_ROTATE), _C),
    0x23: _Layout((), _C),
    0x24: _Layout(_f(*_ROTATE), _C),
    0x25: _Layout(_f(*_ROTATE), _C),
    0x26: _Layout(_f(("sound_category", 0x00FF)), _C),
    0x27: _Layout(_f(("random_range", _W)), _C),
    0x28: _Layout(_f(("phase", 0x0003)), _C),
    0x29: _Layout(_f(_STATUS), _C),
    0x2A: _Layout(
        _f(
            ("x_direction", 0x0007),
            ("y_direction", 0x0038),
            ("z_direction", 0x01C0),
            ("targeted", 0x0200),
            ("avatar_aim", 0x0400),
            ("projectile_kind", 0xF800),
        ),
        _C,
    ),
    0x2B: _Layout((), _C),
    0x2C: _Layout(_f(("radius_value", 0x7FFF), ("absolute_units", 0x8000)), _C),
    0x2D: _Layout((), _C),
    0x2E: _Layout(_f(*_STEP), _C),
    0x2F: _Layout((), _C),
    0x30: _Layout(_f(("conversation_topic", _W)), _C),
    0x31: _Layout(_f(("activity_ordinal", 0x00FF), ("alternate_routine", 0x0100)), _C),
    0x32: _Layout((), _C),
    0x33: _Layout(_f(("sample", 0x1FFF), ("instance_id", 0xE000)), _C),
    0x34: _Layout((), _C),
    0x35: _Layout(_f(("music", 0x00FF), ("fade_time", 0xFF00)), _C),
    0x36: _Layout(_f(("fade_time", _W)), _C),
    0x37: _Layout(_f(("movie", _W)), _C),
    0x38: _Layout(
        _f(("xy_variation", 0x007F), ("reversed", 0x0080), ("z_variation", 0x7F00)), _C
    ),
    0x39: _Layout(_f(("start_link", 0x07FF), ("time_per_unit", 0xF800)), _C),
    0x3A: _Layout(_f(("minutes", 0x0FFF), ("below", 0x1000)), _C),
    0x3B: _Layout(_f(_STATUS), _C),
    0x3C: _Layout(
        _f(("timing", 0x07FF), ("storm_flag", 0x0800), ("intensity", 0xF000)), _C
    ),
    0x3D: _Layout(_f(("special_action", _W)), _C),
    0x3E: _Layout(_f(("equipment_material", _W)), _C),
    0x3F: _Layout(_f(("minutes", 0x7FFF), ("advance", 0x8000)), _C),
    0x40: _Layout(_f(("activity", 0x007F), ("activity_argument", 0xFF80)), _C),
    0x41: _Layout(_f(("opacity", 0x00FF)), _C),
    0x42: _Layout(_f(("scale", 0x0FFF), *_SCALE_AXES), _C),
    0x43: _Layout(_f(("opacity_delta", 0x00FF), ("negative", 0x8000)), _C),
    0x44: _Layout(_f(("scale_delta", 0x0FFF), *_SCALE_AXES, ("negative", 0x8000)), _C),
    0x45: _Layout(_f(("opacity", 0x00FF), ("below", 0x1000)), _C),
    0x46: _Layout(_f(("scale_percent", 0x0FFF), ("below", 0x1000)), _C),
    0x47: _Layout(_f(("scale_percent", 0x0FFF), ("below", 0x1000)), _C),
    0x48: _Layout(_f(("scale_percent", 0x0FFF), ("below", 0x1000)), _C),
    0x49: _Layout(_f(("spell", 0x003F), ("cancel", 0x0040), ("path_link", 0xFF80)), _C),
    0x4A: _Layout((), _C),
    0x4B: _Layout(_f(("quantity", 0x0FFF), ("below", 0x1000)), _C),
    0x4C: _Layout(_f(("sample", 0x1FFF), ("instance_id", 0xE000)), _C),
    0x4D: _Layout(_f(("instance_id", 0xE000)), _C),
    0x4E: _Layout(_f(("tint", 0x7FFF), ("interpolate", 0x8000)), _C),
    0x4F: _Layout(_f(("tint", 0x7FFF)), _C),
    0x50: _Layout(
        _f(
            ("amount", 0x00FF),
            ("random_direction", 0x0100),
            ("suppress_blood", 0x0200),
            ("armor_applies", 0x0400),
            ("heal", 0x0800),
            ("damage_kind", 0xF000),
        ),
        _C,
    ),
    0x51: _Layout((), _C),
    0x52: _Layout(_f(("amount", 0x0FFF), ("operation", 0x3000)), _C),
    0x53: _Layout(_f(("amount", 0x0FFF), ("below", 0x1000)), _C),
    0x54: _Layout(_f(*_STEP), _C),
    0x55: _Layout(_f(("target_value", 0x7FFF), ("target_by_type", 0x8000)), _C),
    0x56: _Layout(_f(("target", _W)), _C),
    0x57: _Layout(
        _f(("amount", 0x0FFF), ("subtract", 0x4000), ("source_only", 0x8000)), _C
    ),
    0x58: _Layout(_f(("interface_flags", 0x00FF)), _C),
    0x59: _Layout(_f(("spell", 0x003F), ("spell_flag", 0x0040)), _C),
    0x5A: _Layout(_f(("hit_points", 0x0FFF), ("below", 0x1000)), _C),
    0x5B: _Layout(
        _f(
            ("datum_index", 0x01FF),
            ("datum_value", 0x0E00),
            ("below", 0x1000),
        ),
        _C,
    ),
    0x5C: _Layout(_f(("include_npcs", 0x0001), ("include_objects", 0x0002)), _C),
    0x5D: _Layout(_f(("combat_bit", 0x0001), ("mortality_bit", 0x0002)), _C),
    0x5E: _Layout(_f(("locked", 0x0001)), _C),
    0x5F: _Layout(_f(("amount", 0x00FF), ("increase", 0x8000)), _C),
    0x60: _Layout(_f(("enabled", 0x0001)), _C),
    0x61: _Layout(
        _f(("attribute", 0x000F), ("threshold", 0x00F0), ("below", 0x1000)), _C
    ),
    0x62: _Layout(_f(("attribute", 0x000F), ("value", 0x00F0), ("mode", 0x0F00)), _C),
    0x63: _Layout(
        _f(
            ("center_interval_ms", 0x007F),
            ("fade_in", 0x0080),
            ("edge_interval_ms", 0x7F00),
        ),
        _C,
    ),
    0x64: _Layout((), _C),
}


def operand_summary(opcode: int, arg0: int, arg1: int, arg2: int) -> str:
    """One-line description of every decoded operand, for listings."""
    parts = []
    target = target_selection(opcode, arg0, arg1)
    if target is not None:
        link = (
            "any link" if target.link_delta is None else f"link {target.link_delta:+d}"
        )
        kind = "any type" if target.any_type else f"type {target.target_type}"
        parts.append(f"targets {link}, {kind}")
    branch_view = branch(opcode, arg2)
    if branch_view is not None:
        if branch_view.form == "label":
            parts.append(f"label {branch_view.label}")
        else:
            destination = (
                "end" if branch_view.ends_script else f"label {branch_view.label}"
            )
            condition = {
                "jump": "",
                "on_match": " if matched",
                "local_value": " if matched",
                "missing_tint": " if matched",
                "count_compare": (
                    f" if count {branch_view.compare_operator or f'code {branch_view.compare_code}'}"
                    f" {branch_view.compare_count}"
                ),
            }[branch_view.form]
            parts.append(f"go to {destination}{condition}")
    params = parameters(opcode, arg2)
    if params is not None:
        if params.fields:
            parts.append(" ".join(f"{name}={value}" for name, value in params.fields))
        if params.unclassified_bits:
            label = "unread" if params.evidence == RETAIL_CONFIRMED else "unclassified"
            parts.append(f"{label} 0x{params.unclassified_bits:04X}")
    return "; ".join(parts)


def parameter_layout(opcode: int) -> tuple[tuple[U9TriggerField, ...], str] | None:
    """The field list and evidence level for ``opcode``, or ``None``."""
    layout = _LAYOUTS.get(opcode)
    return None if layout is None else (layout.fields, layout.evidence)


def parameters(opcode: int, arg2: int) -> U9TriggerParameters | None:
    """Named ``arg2`` fields for ``opcode``, or ``None`` for an unknown opcode."""
    layout = _LAYOUTS.get(opcode)
    if layout is None:
        return None
    covered = 0
    for field in layout.fields:
        covered |= field.mask
    branch_view = branch(opcode, arg2)
    if branch_view is not None:
        covered |= branch_view.mask
    return U9TriggerParameters(
        fields=tuple((field.name, field.value(arg2)) for field in layout.fields),
        unclassified_bits=arg2 & ~covered & WORD_MASK,
        evidence=layout.evidence,
    )
