"""Ultima Online multi component support."""

from __future__ import annotations

__all__ = ["UOMulti", "UOMultiComponent", "UOMultis", "detect_mul_stride"]

from dataclasses import dataclass
from pathlib import Path
import struct

from titan.uo.indexed import UOIndexedFile
from titan.uo.uop import UOPArchive, hash_uop_path


@dataclass(frozen=True)
class UOMultiComponent:
    """One placed static-art component inside a multi."""

    item_id: int
    x: int
    y: int
    z: int
    flags: int
    extra: int
    is_visible: bool
    clilocs: tuple[int, ...] = ()

    @property
    def visible(self) -> bool:
        return self.is_visible


@dataclass(frozen=True)
class UOMulti:
    """One multi definition, such as a house, boat, or structure."""

    multi_id: int
    source: str
    layout: str
    components: tuple[UOMultiComponent, ...]

    @property
    def visible_components(self) -> tuple[UOMultiComponent, ...]:
        visible = tuple(component for component in self.components if component.visible)
        return visible or self.components

    @property
    def bounds(self) -> tuple[int, int, int, int, int, int]:
        components = self.visible_components
        if not components:
            return (0, 0, 0, 0, 0, 0)
        xs = [component.x for component in components]
        ys = [component.y for component in components]
        zs = [component.z for component in components]
        return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


class UOMultis:
    """Parsed UO multis from legacy MUL/IDX or MultiCollection.uop.

    ``source`` names the file read and ``layout`` the record format detected
    (``uop``, ``mul16`` or ``mul12``).
    """

    def __init__(
        self, multis: dict[int, UOMulti], *, source: str = "", layout: str = ""
    ) -> None:
        self.multis = multis
        self.source = source
        self.layout = layout

    @classmethod
    def from_client(
        cls,
        client: str | Path,
        *,
        range_start: int | None = None,
        range_end: int | None = None,
        limit: int | None = None,
        prefer_uop: bool = True,
        container: str | None = None,
    ) -> UOMultis:
        """Load multis from a client directory.

        ``container`` is ``auto`` (``MultiCollection.uop`` when present, else
        ``multi.mul``), ``uop`` or ``mul``. When omitted, ``prefer_uop=False``
        means ``mul``.
        """
        root = Path(client)
        if container is None:
            container = "auto" if prefer_uop else "mul"
        if container not in ("auto", "uop", "mul"):
            raise ValueError(f"unknown multi container: {container}")
        uop = root / "MultiCollection.uop"
        idx, mul = root / "multi.idx", root / "multi.mul"

        if container == "uop" or (container == "auto" and uop.is_file()):
            if not uop.is_file():
                raise FileNotFoundError("MultiCollection.uop not found")
            multis = _load_uop_multis(
                uop, range_start=range_start, range_end=range_end, limit=limit
            )
            return cls(multis, source=uop.name, layout="uop")

        if not (idx.is_file() and mul.is_file()):
            raise FileNotFoundError("multi.mul/multi.idx not found")
        multis, layout = _load_mul_multis(
            idx, mul, range_start=range_start, range_end=range_end, limit=limit
        )
        return cls(multis, source=mul.name, layout=layout)


def _load_mul_multis(
    idx_path: Path,
    mul_path: Path,
    *,
    range_start: int | None,
    range_end: int | None,
    limit: int | None,
) -> tuple[dict[int, UOMulti], str]:
    indexed = UOIndexedFile.from_mul_idx(mul_path, idx_path)
    # The record size is a property of the file, so detect it from every
    # entry before applying a range or limit.
    stride = detect_mul_stride([entry.data for entry in indexed.entries.values()])
    layout = f"mul{stride}"
    multis: dict[int, UOMulti] = {}
    start = 0 if range_start is None else range_start
    end = (
        max(indexed.entries) + 1 if range_end is None and indexed.entries else range_end
    )
    if end is None:
        end = 0

    for multi_id, entry in sorted(indexed.entries.items()):
        if not (start <= multi_id < end):
            continue
        if limit is not None and len(multis) >= limit:
            break
        components = _decode_mul_components(entry.data, stride)
        if components:
            multis[multi_id] = UOMulti(
                multi_id=multi_id,
                source="multi.mul",
                layout=layout,
                components=tuple(components),
            )
    return multis, layout


# Component offsets and altitudes beyond these are not plausible in any
# shipped multi; misaligned reads produce them in roughly a quarter of records.
_MAX_OFFSET = 128
_Z_RANGE = (-256, 512)
_ACCEPT_BAD_RATE = 0.01
_REJECT_BAD_RATE = 0.05


def detect_mul_stride(entries: list[bytes]) -> int:
    """Return the multi.mul record size (12 or 16) for a whole file.

    A size is a candidate only if every entry length divides by it. Each
    candidate is scored by the share of records with implausible offsets or
    altitudes. The best must be clean and any other candidate clearly worse;
    otherwise the file is ambiguous and ``ValueError`` is raised.
    """
    entries = [data for data in entries if data]
    if not entries:
        return 16
    rates: dict[int, float] = {}
    for stride in (16, 12):
        if any(len(data) % stride for data in entries):
            continue
        rates[stride] = _implausible_rate(entries, stride)
    if not rates:
        raise ValueError("multi.mul entries fit neither 12- nor 16-byte records")
    best = min(rates, key=rates.get)
    if rates[best] > _ACCEPT_BAD_RATE:
        raise ValueError(
            f"multi.mul does not decode cleanly: {rates[best]:.1%} implausible "
            f"records at {best} bytes"
        )
    rivals = [rate for stride, rate in rates.items() if stride != best]
    if rivals and min(rivals) < _REJECT_BAD_RATE:
        raise ValueError(
            "multi.mul record size is ambiguous: both 12 and 16 bytes decode cleanly"
        )
    return best


def _implausible_rate(entries: list[bytes], stride: int) -> float:
    bad = total = 0
    for data in entries:
        for pos in range(0, len(data), stride):
            _item, x, y, z = struct.unpack_from("<Hhhh", data, pos)
            total += 1
            if (
                abs(x) > _MAX_OFFSET
                or abs(y) > _MAX_OFFSET
                or not _Z_RANGE[0] <= z <= _Z_RANGE[1]
            ):
                bad += 1
    return bad / total if total else 0.0


def _decode_mul_components(data: bytes, stride: int) -> list[UOMultiComponent]:
    components: list[UOMultiComponent] = []
    for pos in range(0, len(data) - stride + 1, stride):
        item_id, x, y, z = struct.unpack_from("<Hhhh", data, pos)
        if stride == 16:
            flags, extra = struct.unpack_from("<II", data, pos + 8)
        else:
            flags = struct.unpack_from("<I", data, pos + 8)[0]
            extra = 0
        components.append(
            UOMultiComponent(
                item_id=item_id,
                x=x,
                y=y,
                z=z,
                flags=flags,
                extra=extra,
                is_visible=flags != 0,
            )
        )
    return components


def _load_uop_multis(
    uop_path: Path,
    *,
    range_start: int | None,
    range_end: int | None,
    limit: int | None,
) -> dict[int, UOMulti]:
    archive = UOPArchive(uop_path)
    multis: dict[int, UOMulti] = {}
    start = 0 if range_start is None else range_start
    end = 0x2200 if range_end is None else min(range_end, 0x2200)

    for multi_id in range(start, end):
        if limit is not None and len(multis) >= limit:
            break
        virtual_path = f"build/multicollection/{multi_id:06d}.bin"
        entry = archive.entries_by_hash.get(hash_uop_path(virtual_path))
        if entry is None:
            continue
        data = archive.read_entry(entry)
        decoded = _decode_uop_multi(data)
        if decoded is not None:
            multis[decoded.multi_id] = decoded
    return multis


def _decode_uop_multi(data: bytes) -> UOMulti | None:
    if len(data) < 8:
        return None
    multi_id, count = struct.unpack_from("<Ii", data, 0)
    if count <= 0 or count > 100000:
        return None
    pos = 8
    components: list[UOMultiComponent] = []
    for _ in range(count):
        if pos + 14 > len(data):
            return None
        item_id, x, y, z, flags = struct.unpack_from("<HHHHH", data, pos)
        pos += 10
        cliloc_count = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        if (
            cliloc_count < 0
            or cliloc_count > 10000
            or pos + cliloc_count * 4 > len(data)
        ):
            return None
        clilocs = tuple(
            struct.unpack_from("<I", data, pos + index * 4)[0]
            for index in range(cliloc_count)
        )
        pos += cliloc_count * 4
        components.append(
            UOMultiComponent(
                item_id=item_id,
                x=_signed_u16(x),
                y=_signed_u16(y),
                z=_signed_u16(z),
                flags=flags,
                extra=0,
                is_visible=flags in (0, 0x100),
                clilocs=clilocs,
            )
        )
    return UOMulti(
        multi_id=multi_id,
        source="MultiCollection.uop",
        layout="uop",
        components=tuple(components),
    )


def _signed_u16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value
