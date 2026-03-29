"""
Ultima 7 Type Flag Array (TFA) and shape-info parser.

Provides :class:`U7TypeFlags` for reading ``TFA.DAT``, ``SHPDIMS.DAT``,
``WGTVOL.DAT``, and ``OCCLUDE.DAT`` — the per-shape metadata files that
describe U7 object physics, dimensions, animation, and properties.

Based on Exult's ``shapes/shapeinf.h``, ``shapes/shapevga.cc``, and
``shapes/shapeinf/aniinf.cc``.

Example::

    from titan.u7.typeflag import U7TypeFlags

    tfa = U7TypeFlags.from_dir("STATIC/")
    entry = tfa.get(150)
    print(entry.dims_x, entry.dims_y, entry.dims_z)
    print(entry.flag_names())
"""

from __future__ import annotations

__all__ = ["U7TypeFlags"]

import os
import struct
from dataclasses import dataclass, field


class U7TypeFlags:
    """
    U7 shape metadata from TFA.DAT, SHPDIMS.DAT, and WGTVOL.DAT.

    TFA.DAT — 3 bytes per shape::

        Byte 0:
          bit 0  — has_sfx
          bit 1  — has_strange_movement
          bit 2  — is_animated
          bit 3  — is_solid
          bit 4  — is_water
          bits 5–7 — Z dimension (height in tiles, 0–7)

        Byte 1:
          bits 0–3 — shape_class (0=unusable, 2=quality,
                     4=has_quantity, 5=has_quality, 6=container,
                     7=egg, 12=monster, 13=human, 14=building/roof)
          bit 4  — is_poisonous / is_field
          bit 5  — is_door
          bit 6  — is_barge_part
          bit 7  — is_transparent

        Byte 2:
          bits 0–2 — X dimension − 1 (0–7 → actual 1–8)
          bits 3–5 — Y dimension − 1 (0–7 → actual 1–8)
          bit 6  — is_light_source
          bit 7  — has_translucency

    SHPDIMS.DAT — 2 bytes per shape (starting at shape 0x96 = 150)::

        Byte 0: pixel width of representative frame
        Byte 1: pixel height of representative frame

    WGTVOL.DAT — 2 bytes per shape::

        Byte 0: weight
        Byte 1: volume
    """

    # TFA byte-0 flag bits
    FLAG_HAS_SFX            = 0x01
    FLAG_STRANGE_MOVEMENT   = 0x02
    FLAG_ANIMATED           = 0x04
    FLAG_SOLID              = 0x08
    FLAG_WATER              = 0x10

    # TFA byte-1: shape class (bits 0–3)
    SHAPE_CLASS_UNUSABLE   = 0
    SHAPE_CLASS_QUALITY    = 2
    SHAPE_CLASS_QUANTITY   = 3
    SHAPE_CLASS_HAS_QUANT  = 4
    SHAPE_CLASS_HAS_QUAL   = 5
    SHAPE_CLASS_CONTAINER  = 6
    SHAPE_CLASS_EGG        = 7
    SHAPE_CLASS_SPELLBOOK  = 8
    SHAPE_CLASS_BARGE      = 9    # Barge / boat
    SHAPE_CLASS_VIRTUE_STONE = 11 # Virtue stones
    SHAPE_CLASS_MONSTER    = 12
    SHAPE_CLASS_HUMAN      = 13
    SHAPE_CLASS_BUILDING   = 14   # Roof, window, mountain top

    # Human-readable shape class names
    SHAPE_CLASS_NAMES: dict[int, str] = {
        0:  "unusable",
        2:  "quality",
        3:  "quantity",
        4:  "has_hp",
        5:  "quality_flags",
        6:  "container",
        7:  "hatchable",
        8:  "spellbook",
        9:  "barge",
        11: "virtue_stone",
        12: "monster",
        13: "human",
        14: "building",
    }

    # TFA animation types (from aniinf.cc create_from_tfa)
    ANIM_TYPE_NAMES: dict[int, str] = {
        0:  "timesynched",
        1:  "timesynched",
        2:  "random_advance",      # like 0/1 but frames advance randomly
        3:  "unknown_pattern",     # unimplemented in Exult
        4:  "random_pattern",      # unimplemented in Exult
        5:  "looping",             # recycle=0, freeze=20, delay=1
        6:  "random_frames",
        7:  "toggle_bit0",         # frame ^= 1; unimplemented in Exult
        8:  "hourly",
        9:  "looping_r8",          # recycle=8
        10: "looping_r6",          # recycle=6
        11: "looping_end",         # recycle=nframes-1, freeze=0
        12: "slow_advance",        # timesynched, freeze=100, delay=4
        13: "non_looping",
        14: "grandfather_clock",   # same timing as 12
        15: "timesynched_sfx",     # 6 frames, freeze=100, delay=4, sfx=0
    }

    # TFA byte-1 flag bits
    FLAG_POISONOUS          = 0x10
    FLAG_DOOR               = 0x20
    FLAG_BARGE_PART         = 0x40
    FLAG_TRANSPARENT        = 0x80

    # TFA byte-2 flag bits
    FLAG_LIGHT_SOURCE       = 0x40
    FLAG_TRANSLUCENCY       = 0x80

    # Human-readable names for byte-0 flags (bits 0–4)
    BYTE0_FLAG_NAMES: dict[int, str] = {
        0x01: "has_sfx",
        0x02: "strange_movement",
        0x04: "animated",
        0x08: "solid",
        0x10: "water",
    }

    # Human-readable names for byte-1 flags (bits 4–7)
    BYTE1_FLAG_NAMES: dict[int, str] = {
        0x10: "poisonous",
        0x20: "door",
        0x40: "barge_part",
        0x80: "transparent",
    }

    # Human-readable names for byte-2 flags (bits 6–7)
    BYTE2_FLAG_NAMES: dict[int, str] = {
        0x40: "light_source",
        0x80: "translucency",
    }

    # First non-tile (object) shape in SHAPES.VGA
    FIRST_OBJ_SHAPE = 0x96  # 150

    @dataclass
    class ShapeEntry:
        """Decoded metadata for a single U7 shape."""

        shape_num: int

        # Raw TFA bytes
        tfa: bytes = b"\x00\x00\x00"

        # 3D tile dimensions (from TFA byte 0 + byte 2)
        dims_x: int = 1  # X footprint in tiles (1–8)
        dims_y: int = 1  # Y footprint in tiles (1–8)
        dims_z: int = 0  # Height in tiles (0–7)

        # Pixel dimensions (from SHPDIMS.DAT, only for shape >= 150)
        pixel_w: int = 0
        pixel_h: int = 0

        # Shape class (from TFA byte 1, bits 0–3)
        shape_class: int = 0

        # Occlusion flag (from OCCLUDE.DAT)
        occludes: bool = False

        # Weight and volume (from WGTVOL.DAT)
        weight: int = 0
        volume: int = 0

        # Animation type (from TFA.DAT animation nibbles, offset 3072)
        anim_type: int = -1  # -1 = none, 0-15 = animation type

        # --- Flag accessors ---

        @property
        def has_sfx(self) -> bool:
            return bool(self.tfa[0] & 0x01)

        @property
        def has_strange_movement(self) -> bool:
            return bool(self.tfa[0] & 0x02)

        @property
        def is_animated(self) -> bool:
            return bool(self.tfa[0] & 0x04)

        @property
        def is_solid(self) -> bool:
            return bool(self.tfa[0] & 0x08)

        @property
        def is_water(self) -> bool:
            return bool(self.tfa[0] & 0x10)

        @property
        def is_building(self) -> bool:
            """Shape class == 14 (building/roof/mountain top)."""
            return self.shape_class == U7TypeFlags.SHAPE_CLASS_BUILDING

        @property
        def is_poisonous(self) -> bool:
            return bool(self.tfa[1] & 0x10)

        @property
        def is_door(self) -> bool:
            return bool(self.tfa[1] & 0x20)

        @property
        def is_barge_part(self) -> bool:
            return bool(self.tfa[1] & 0x40)

        @property
        def is_transparent(self) -> bool:
            return bool(self.tfa[1] & 0x80)

        @property
        def is_light_source(self) -> bool:
            return bool(self.tfa[2] & 0x40)

        @property
        def has_translucency(self) -> bool:
            return bool(self.tfa[2] & 0x80)

        @property
        def shape_class_name(self) -> str:
            """Human-readable shape class name."""
            return U7TypeFlags.SHAPE_CLASS_NAMES.get(
                self.shape_class, f"unknown({self.shape_class})")

        @property
        def anim_type_name(self) -> str:
            """Human-readable animation type, or empty string if none."""
            if self.anim_type < 0:
                return ""
            return U7TypeFlags.ANIM_TYPE_NAMES.get(
                self.anim_type, f"unknown({self.anim_type})")

        def flag_names(self) -> list[str]:
            """Return list of all set flag names."""
            names: list[str] = []
            for bit, name in U7TypeFlags.BYTE0_FLAG_NAMES.items():
                if self.tfa[0] & bit:
                    names.append(name)
            if self.shape_class != 0:
                names.append(f"class:{self.shape_class}")
            if self.occludes:
                names.append("occludes")
            for bit, name in U7TypeFlags.BYTE1_FLAG_NAMES.items():
                if self.tfa[1] & bit:
                    names.append(name)
            for bit, name in U7TypeFlags.BYTE2_FLAG_NAMES.items():
                if self.tfa[2] & bit:
                    names.append(name)
            if self.anim_type >= 0:
                names.append(f"anim:{self.anim_type_name}")
            return names

        def footpad_tiles(self, frame: int = 0) -> tuple[int, int, int]:
            """
            Tile footprint ``(X, Y, Z)``.

            Frame bit 5 (reflected) swaps X and Y, matching Exult's
            ``Shape_info::get_3d_xtiles(framenum)``.
            """
            reflected = bool(frame & 0x20)
            if reflected:
                return (self.dims_y, self.dims_x, self.dims_z)
            return (self.dims_x, self.dims_y, self.dims_z)

    def __init__(self) -> None:
        self.entries: list[U7TypeFlags.ShapeEntry] = []
        self._by_num: dict[int, U7TypeFlags.ShapeEntry] = {}

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, shape_num: int) -> ShapeEntry | None:
        """Look up a shape entry by number."""
        return self._by_num.get(shape_num)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @classmethod
    def from_dir(cls, static_dir: str) -> U7TypeFlags:
        """
        Load TFA.DAT, SHPDIMS.DAT, WGTVOL.DAT, and OCCLUDE.DAT
        from a STATIC directory.
        """
        tfa_path = os.path.join(static_dir, "TFA.DAT")
        shpdims_path = os.path.join(static_dir, "SHPDIMS.DAT")
        wgtvol_path = os.path.join(static_dir, "WGTVOL.DAT")
        occlude_path = os.path.join(static_dir, "OCCLUDE.DAT")

        tfa_data = b""
        shpdims_data = b""
        wgtvol_data = b""
        occlude_data = b""

        if os.path.isfile(tfa_path):
            with open(tfa_path, "rb") as f:
                tfa_data = f.read()
        if os.path.isfile(shpdims_path):
            with open(shpdims_path, "rb") as f:
                shpdims_data = f.read()
        if os.path.isfile(wgtvol_path):
            with open(wgtvol_path, "rb") as f:
                wgtvol_data = f.read()
        if os.path.isfile(occlude_path):
            with open(occlude_path, "rb") as f:
                occlude_data = f.read()

        return cls.parse(tfa_data, shpdims_data, wgtvol_data, occlude_data)

    @classmethod
    def from_tfa_file(cls, filepath: str) -> U7TypeFlags:
        """Load only TFA.DAT (no shpdims or wgtvol)."""
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.parse(data)

    @classmethod
    def parse(
        cls,
        tfa_data: bytes,
        shpdims_data: bytes = b"",
        wgtvol_data: bytes = b"",
        occlude_data: bytes = b"",
    ) -> U7TypeFlags:
        """
        Parse raw TFA / SHPDIMS / WGTVOL / OCCLUDE bytes into a
        :class:`U7TypeFlags`.

        Parameters
        ----------
        tfa_data:
            Contents of TFA.DAT (3 bytes per shape).
        shpdims_data:
            Contents of SHPDIMS.DAT (2 bytes per shape, starting at
            shape 0x96 = 150).
        wgtvol_data:
            Contents of WGTVOL.DAT (2 bytes per shape).
        occlude_data:
            Contents of OCCLUDE.DAT (bit array, 1 bit per shape).
        """
        num_tfa = len(tfa_data) // 3
        num_shpdims = len(shpdims_data) // 2
        num_wgtvol = len(wgtvol_data) // 2

        # Max shape count from any source
        max_shape = num_tfa
        if num_shpdims > 0:
            max_shape = max(max_shape, cls.FIRST_OBJ_SHAPE + num_shpdims)
        if num_wgtvol > 0:
            max_shape = max(max_shape, num_wgtvol)

        obj = cls()

        for i in range(max_shape):
            entry = cls.ShapeEntry(shape_num=i)

            # TFA
            if i < num_tfa:
                off = i * 3
                raw = tfa_data[off:off + 3]
                entry.tfa = bytes(raw)
                entry.dims_x = 1 + (raw[2] & 0x07)
                entry.dims_y = 1 + ((raw[2] >> 3) & 0x07)
                entry.dims_z = raw[0] >> 5
                entry.shape_class = raw[1] & 0x0F

            # SHPDIMS (offset by FIRST_OBJ_SHAPE)
            shp_idx = i - cls.FIRST_OBJ_SHAPE
            if 0 <= shp_idx < num_shpdims:
                off = shp_idx * 2
                entry.pixel_w = shpdims_data[off]
                entry.pixel_h = shpdims_data[off + 1]

            # WGTVOL
            if i < num_wgtvol:
                off = i * 2
                entry.weight = wgtvol_data[off]
                entry.volume = wgtvol_data[off + 1]

            obj.entries.append(entry)
            obj._by_num[i] = entry

        # OCCLUDE.DAT — 1 bit per shape
        for byte_idx in range(len(occlude_data)):
            bits = occlude_data[byte_idx]
            for bit in range(8):
                if bits & (1 << bit):
                    shnum = byte_idx * 8 + bit
                    e = obj._by_num.get(shnum)
                    if e is not None:
                        e.occludes = True

        # Animation nibbles — stored at offset 3072 in TFA.DAT
        # (512 bytes = 1024 shapes × 4-bit packed).
        # Only present if the file is larger than the base 3*1024 bytes.
        anim_offset = num_tfa * 3
        anim_end = anim_offset + 512
        if len(tfa_data) >= anim_end:
            anim_data = tfa_data[anim_offset:anim_end]
            for byte_idx in range(512):
                val = anim_data[byte_idx]
                if val == 0:
                    continue
                shape_lo = byte_idx * 2
                shape_hi = shape_lo + 1
                lo_nibble = val & 0x0F
                hi_nibble = (val >> 4) & 0x0F
                if lo_nibble != 0:
                    e = obj._by_num.get(shape_lo)
                    if e is not None:
                        e.anim_type = lo_nibble
                if hi_nibble != 0:
                    e = obj._by_num.get(shape_hi)
                    if e is not None:
                        e.anim_type = hi_nibble

        return obj

    # ------------------------------------------------------------------
    # Exclusion / filtering
    # ------------------------------------------------------------------

    def build_exclude_set(self, **exclude_flags: bool) -> set[int]:
        """
        Build a set of shape numbers to exclude based on TFA flags.

        Supported keyword flags::

            no_solid, no_water, no_animated, no_sfx,
            no_transparent, no_translucent, no_door,
            no_barge, no_light, no_poisonous,
            no_strange_movement,
            no_building

        A shape is excluded if **any** of its enabled exclude flags match.
        """
        _flag_tests: dict[str, tuple[int, int]] = {
            # (byte_index, bit_mask)
            "no_sfx":               (0, 0x01),
            "no_strange_movement":  (0, 0x02),
            "no_animated":          (0, 0x04),
            "no_solid":             (0, 0x08),
            "no_water":             (0, 0x10),
            "no_poisonous":         (1, 0x10),
            "no_door":              (1, 0x20),
            "no_barge":             (1, 0x40),
            "no_transparent":       (1, 0x80),
            "no_light":             (2, 0x40),
            "no_translucent":       (2, 0x80),
        }

        exclude_set: set[int] = set()
        active = {k: v for k, v in _flag_tests.items()
                  if exclude_flags.get(k, False)}

        want_no_building = exclude_flags.get("no_building", False)

        if not active and not want_no_building:
            return exclude_set

        for entry in self.entries:
            if want_no_building and entry.is_building:
                exclude_set.add(entry.shape_num)
                continue
            for _name, (byte_idx, mask) in active.items():
                if entry.tfa[byte_idx] & mask:
                    exclude_set.add(entry.shape_num)
                    break

        return exclude_set

    def dump_summary(self) -> str:
        """Return a human-readable summary of all shape entries."""
        lines = ["shape | dims(xyz) | weight | vol | flags"]
        lines.append("-" * 60)
        for e in self.entries:
            flags = ", ".join(e.flag_names()) or "-"
            lines.append(
                f"{e.shape_num:5d} | "
                f"{e.dims_x:d}×{e.dims_y:d}×{e.dims_z:d}     | "
                f"{e.weight:6d} | {e.volume:3d} | {flags}"
            )
        return "\n".join(lines)

    def dump_detail(self) -> str:
        """
        Return a comprehensive per-shape dump with full decoded data.

        Includes raw TFA hex, all decoded fields, shape class name,
        animation type, pixel dimensions, weight/volume, and occlusion.
        """
        lines: list[str] = []
        lines.append("# Ultima 7 — TFA.DAT Full Shape Reference")
        lines.append(f"# {len(self.entries)} shapes")
        lines.append("#")
        lines.append("# Format: TFA.DAT (3 bytes/shape, 1024 shapes)")
        lines.append("#   Byte 0: bits 0-4 = flags, bits 5-7 = Z height")
        lines.append("#   Byte 1: bits 0-3 = shape class, bits 4-7 = flags")
        lines.append("#   Byte 2: bits 0-2 = X dim-1, bits 3-5 = Y dim-1, bits 6-7 = flags")
        lines.append("#")
        lines.append("# Companion files:")
        lines.append("#   SHPDIMS.DAT — pixel width/height (shapes >= 150)")
        lines.append("#   WGTVOL.DAT  — weight/volume (2 bytes/shape)")
        lines.append("#   OCCLUDE.DAT — bit-packed occlusion flags")
        lines.append("#   TFA.DAT[3072..3583] — animation nibbles (4 bits/shape)")
        lines.append("")

        # Statistics header
        stats = self._compute_stats()
        lines.append("## Statistics")
        lines.append("")
        for label, count in stats:
            lines.append(f"  {label:30s}: {count:5d}")
        lines.append("")

        # Per-shape detail
        lines.append("## Per-Shape Data")
        lines.append("")
        hdr = (f"{'shape':>5s}  {'hex':>6s}  {'tfa_raw':8s}  "
               f"{'dims':7s}  {'class':15s}  {'pxl':9s}  "
               f"{'wt':>3s}  {'vol':>3s}  {'occ':>3s}  "
               f"{'anim':20s}  flags")
        lines.append(hdr)
        lines.append("-" * len(hdr))

        for e in self.entries:
            tfa_hex = f"{e.tfa[0]:02X} {e.tfa[1]:02X} {e.tfa[2]:02X}"
            dims = f"{e.dims_x}x{e.dims_y}x{e.dims_z}"
            cls_name = e.shape_class_name if e.shape_class != 0 else "-"
            pxl = f"{e.pixel_w}x{e.pixel_h}" if e.pixel_w or e.pixel_h else "-"
            occ = "yes" if e.occludes else "-"
            anim = e.anim_type_name or "-"
            flags = ", ".join(e.flag_names()) or "-"
            lines.append(
                f"{e.shape_num:5d}  0x{e.shape_num:04X}  {tfa_hex}  "
                f"{dims:<7s}  {cls_name:<15s}  {pxl:<9s}  "
                f"{e.weight:3d}  {e.volume:3d}  {occ:>3s}  "
                f"{anim:<20s}  {flags}"
            )

        return "\n".join(lines)

    def dump_csv(self) -> str:
        """Return CSV output of all shape entries."""
        lines: list[str] = []
        lines.append(
            "shape,hex,tfa0,tfa1,tfa2,"
            "dims_x,dims_y,dims_z,"
            "shape_class,shape_class_name,"
            "pixel_w,pixel_h,weight,volume,occludes,"
            "anim_type,anim_type_name,"
            "has_sfx,strange_movement,animated,solid,water,"
            "poisonous,door,barge_part,transparent,"
            "light_source,translucency"
        )
        for e in self.entries:
            cls_name = e.shape_class_name if e.shape_class != 0 else ""
            anim_name = e.anim_type_name
            lines.append(
                f"{e.shape_num},0x{e.shape_num:04X},"
                f"0x{e.tfa[0]:02X},0x{e.tfa[1]:02X},0x{e.tfa[2]:02X},"
                f"{e.dims_x},{e.dims_y},{e.dims_z},"
                f"{e.shape_class},{cls_name},"
                f"{e.pixel_w},{e.pixel_h},{e.weight},{e.volume},"
                f"{1 if e.occludes else 0},"
                f"{e.anim_type},{anim_name},"
                f"{1 if e.has_sfx else 0},"
                f"{1 if e.has_strange_movement else 0},"
                f"{1 if e.is_animated else 0},"
                f"{1 if e.is_solid else 0},"
                f"{1 if e.is_water else 0},"
                f"{1 if e.is_poisonous else 0},"
                f"{1 if e.is_door else 0},"
                f"{1 if e.is_barge_part else 0},"
                f"{1 if e.is_transparent else 0},"
                f"{1 if e.is_light_source else 0},"
                f"{1 if e.has_translucency else 0}"
            )
        return "\n".join(lines)

    def _compute_stats(self) -> list[tuple[str, int]]:
        """Compute flag/class/animation statistics."""
        flag_counts: dict[str, int] = {}
        class_counts: dict[str, int] = {}
        anim_counts: dict[str, int] = {}
        n_occludes = 0
        n_with_dims = 0
        n_animated_flag = 0
        n_animated_nibble = 0

        for entry in self.entries:
            for name in entry.flag_names():
                flag_counts[name] = flag_counts.get(name, 0) + 1
            if entry.shape_class != 0:
                cn = entry.shape_class_name
                class_counts[cn] = class_counts.get(cn, 0) + 1
            if entry.occludes:
                n_occludes += 1
            if entry.dims_z > 0:
                n_with_dims += 1
            if entry.is_animated:
                n_animated_flag += 1
            if entry.anim_type >= 0:
                n_animated_nibble += 1
                an = entry.anim_type_name
                anim_counts[an] = anim_counts.get(an, 0) + 1

        result: list[tuple[str, int]] = []
        result.append(("Total shapes", len(self.entries)))
        result.append(("Shapes with height > 0", n_with_dims))
        result.append(("Shapes that occlude", n_occludes))
        result.append(("Animated (TFA flag)", n_animated_flag))
        result.append(("Animated (nibble data)", n_animated_nibble))
        result.append(("", 0))  # blank line

        result.append(("--- Flags ---", 0))
        for name, count in sorted(flag_counts.items()):
            result.append((f"  {name}", count))
        result.append(("", 0))

        result.append(("--- Shape classes ---", 0))
        for name, count in sorted(class_counts.items()):
            result.append((f"  {name}", count))
        result.append(("", 0))

        if anim_counts:
            result.append(("--- Animation types ---", 0))
            for name, count in sorted(anim_counts.items()):
                result.append((f"  {name}", count))

        return result
