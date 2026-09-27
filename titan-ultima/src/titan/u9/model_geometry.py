"""Lossless reader for Ultima IX ``static/dimension.dat``.

The file is four structure-of-arrays blocks for 8,000 model identifiers:

* one little-endian float radius per identifier;
* one little-endian XYZ float triplet per identifier;
* a 32,000-byte prefix of the model minimum-bound triplet array; and
* a 32,000-byte prefix of the model maximum-bound triplet array.

The two bound blocks are deliberately described as prefixes.  Each is only
large enough for 2,666 complete triplets plus X/Y for identifier 2,666.  The
retail loader performs exactly those short block reads over model-derived
runtime arrays.  Titan therefore reports absent components instead of
inventing values or treating the blocks as 8,000 independent scalars.
"""

from __future__ import annotations

__all__ = [
    "BOUND_PREFIX_SIZE",
    "COMPLETE_STORED_BOUND_COUNT",
    "EXPECTED_SIZE",
    "MODEL_SLOT_COUNT",
    "PARTIAL_STORED_BOUND_ID",
    "U9ModelGeometryRecord",
    "U9ModelGeometryTable",
    "U9ModelGeometryTableError",
]

import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path

MODEL_SLOT_COUNT = 8_000
_FLOAT_SIZE = 4
_VECTOR_SIZE = 12
_SCALAR_BLOCK_SIZE = MODEL_SLOT_COUNT * _FLOAT_SIZE
_VECTOR_BLOCK_SIZE = MODEL_SLOT_COUNT * _VECTOR_SIZE
BOUND_PREFIX_SIZE = _SCALAR_BLOCK_SIZE
EXPECTED_SIZE = _SCALAR_BLOCK_SIZE + _VECTOR_BLOCK_SIZE + 2 * BOUND_PREFIX_SIZE
COMPLETE_STORED_BOUND_COUNT = BOUND_PREFIX_SIZE // _VECTOR_SIZE
PARTIAL_STORED_BOUND_ID = COMPLETE_STORED_BOUND_COUNT

_RADIUS_OFFSET = 0
_CENTER_OFFSET = _RADIUS_OFFSET + _SCALAR_BLOCK_SIZE
_MINIMUM_OFFSET = _CENTER_OFFSET + _VECTOR_BLOCK_SIZE
_MAXIMUM_OFFSET = _MINIMUM_OFFSET + BOUND_PREFIX_SIZE

Vec3 = tuple[float, float, float]
OptionalVec3 = tuple[float | None, float | None, float | None]


class U9ModelGeometryTableError(Exception):
    """Raised when ``dimension.dat`` does not have its fixed retail extent."""


@dataclass(frozen=True)
class U9ModelGeometryRecord:
    """One model ID's values gathered from the four discontiguous blocks."""

    model_id: int
    culling_radius: float
    culling_center: Vec3
    bounds_minimum: OptionalVec3
    bounds_maximum: OptionalVec3
    radius_raw_data: bytes
    center_raw_data: bytes
    minimum_raw_data: bytes
    maximum_raw_data: bytes

    @property
    def bounds_storage_status(self) -> str:
        """Describe exactly how much of this ID's bound triplets is on disk."""
        if len(self.minimum_raw_data) == _VECTOR_SIZE:
            return "complete"
        if len(self.minimum_raw_data) == 2 * _FLOAT_SIZE:
            return "xy_only"
        return "absent"

    @property
    def culling_radius_status(self) -> str:
        """Classify the stored radius without changing its value."""
        if not math.isfinite(self.culling_radius):
            return "nonfinite"
        if self.culling_radius == -1.0:
            return "unavailable_sentinel"
        if self.culling_radius < 0.0:
            return "unexpected_negative"
        return "available"

    @property
    def stored_fragments_hex(self) -> str:
        """Return all four stored fragments with their boundaries visible."""
        return ";".join(
            part.hex()
            for part in (
                self.radius_raw_data,
                self.center_raw_data,
                self.minimum_raw_data,
                self.maximum_raw_data,
            )
        )

    def structural_warnings(self) -> tuple[str, ...]:
        """Report numeric anomalies while retaining every stored bit."""
        warnings: list[str] = []
        if self.culling_radius_status in {"nonfinite", "unexpected_negative"}:
            warnings.append(f"culling_radius_{self.culling_radius_status}")
        if not all(math.isfinite(value) for value in self.culling_center):
            warnings.append("culling_center_nonfinite")

        for label, bounds in (
            ("bounds_minimum", self.bounds_minimum),
            ("bounds_maximum", self.bounds_maximum),
        ):
            if any(value is not None and not math.isfinite(value) for value in bounds):
                warnings.append(f"{label}_nonfinite")

        if self.bounds_storage_status == "complete":
            for axis, (minimum, maximum) in enumerate(
                zip(self.bounds_minimum, self.bounds_maximum)
            ):
                if minimum is not None and maximum is not None and minimum > maximum:
                    warnings.append(f"bounds_axis_{axis}_reversed")
        return tuple(warnings)


class U9ModelGeometryTable:
    """Lossless identifier-indexed view of ``static/dimension.dat``."""

    def __init__(self, data: bytes) -> None:
        if len(data) != EXPECTED_SIZE:
            raise U9ModelGeometryTableError(
                f"dimension.dat must be exactly {EXPECTED_SIZE} bytes; "
                f"found {len(data)}"
            )
        self._data = bytes(data)
        self._records = tuple(
            self._parse_record(model_id) for model_id in range(MODEL_SLOT_COUNT)
        )

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> U9ModelGeometryTable:
        try:
            return cls(Path(path).read_bytes())
        except OSError as error:
            raise U9ModelGeometryTableError(str(error)) from error

    @property
    def records(self) -> tuple[U9ModelGeometryRecord, ...]:
        return self._records

    def record(self, model_id: int) -> U9ModelGeometryRecord:
        if not 0 <= model_id < MODEL_SLOT_COUNT:
            raise IndexError(f"model ID {model_id} outside 0..{MODEL_SLOT_COUNT - 1}")
        return self._records[model_id]

    def warning_model_ids(self) -> tuple[int, ...]:
        return tuple(
            record.model_id for record in self._records if record.structural_warnings()
        )

    def to_bytes(self) -> bytes:
        """Return the complete original table byte for byte."""
        return self._data

    def _parse_record(self, model_id: int) -> U9ModelGeometryRecord:
        radius_offset = _RADIUS_OFFSET + model_id * _FLOAT_SIZE
        center_offset = _CENTER_OFFSET + model_id * _VECTOR_SIZE
        minimum_offset = _MINIMUM_OFFSET + model_id * _VECTOR_SIZE
        maximum_offset = _MAXIMUM_OFFSET + model_id * _VECTOR_SIZE

        radius_raw = self._data[radius_offset : radius_offset + _FLOAT_SIZE]
        center_raw = self._data[center_offset : center_offset + _VECTOR_SIZE]
        minimum_raw = self._bounded_fragment(minimum_offset, _MINIMUM_OFFSET)
        maximum_raw = self._bounded_fragment(maximum_offset, _MAXIMUM_OFFSET)

        return U9ModelGeometryRecord(
            model_id=model_id,
            culling_radius=struct.unpack("<f", radius_raw)[0],
            culling_center=struct.unpack("<3f", center_raw),
            bounds_minimum=_decode_optional_vector(minimum_raw),
            bounds_maximum=_decode_optional_vector(maximum_raw),
            radius_raw_data=radius_raw,
            center_raw_data=center_raw,
            minimum_raw_data=minimum_raw,
            maximum_raw_data=maximum_raw,
        )

    def _bounded_fragment(self, offset: int, block_offset: int) -> bytes:
        block_end = block_offset + BOUND_PREFIX_SIZE
        if offset >= block_end:
            return b""
        return self._data[offset : min(offset + _VECTOR_SIZE, block_end)]


def _decode_optional_vector(data: bytes) -> OptionalVec3:
    values = struct.unpack(f"<{len(data) // _FLOAT_SIZE}f", data) if data else ()
    padded = (*values, *(None for _ in range(3 - len(values))))
    return padded  # type: ignore[return-value]
