"""Cross-file integrity checks for Ultima IX save ecosystems."""

from __future__ import annotations

__all__ = [
    "IntegrityFinding",
    "IntegrityReport",
    "check_save",
    "render_integrity_report",
]

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from titan.u9.fixed import U9Fixed, U9FixedError
from titan.u9.nonfixed import U9Nonfixed, U9NonfixedError
from titan.u9.process_data import (
    U9AnimationControllerProcessState,
    U9HangingObjectProcessState,
    U9ObjectReferenceTable,
    U9ParticlePresetState,
    U9PlayerProximityProcessState,
    U9PortableLightProcessState,
    U9ProcessDataError,
    U9ProcessDataPrefix,
    U9ScriptedProcessState,
    U9ScriptTimerProcessState,
)
from titan.u9.savegame import (
    MAX_MAP_NUMBER,
    MAX_SHIPPED_MAP_NUMBER,
    U9SaveArchive,
    U9SaveError,
    U9StartDat,
)

AXES = ("custody", "structure", "compatibility")
SEVERITY_RANK = {"PASS": 0, "INFO": 0, "WARN": 1, "ERROR": 2, "FATAL": 3}
MAP_FILE_RE = re.compile(r"^(fixed|nonfixed)\.(\d+)$", re.IGNORECASE)

ASSESSMENTS = {
    "PASS": "PASS - no integrity problems detected",
    "WARN": "REVIEW ADVISED - evidence is incomplete or uncertain",
    "ERROR": "INTEGRITY ERRORS - repair or investigate before loading",
    "FATAL": "UNSAFE TO LOAD - a required invariant is broken",
}

AXIS_DESCRIPTIONS = {
    "custody": "archive and working-file provenance",
    "structure": "binary layout and allocator health",
    "compatibility": "saved references against map data",
}

RECOMMENDATIONS = {
    "SEL": "Select an existing save slot or repair start.dat.",
    "ARC": "Recover or replace the save archive before loading it.",
    "CUS": "Re-extract the selected archive; do not mix loose files from other slots.",
    "NFS": "Preserve the files and inspect the named nonfixed maps before loading.",
    "FXS": "Restore the affected fixed maps from a known-good installation.",
    "HND": "Do not load until processes.dat and its object-reference table are repaired.",
    "PRC": "Do not load until the deterministic processes.dat prefix is repaired.",
    "REF": "Do not load or overwrite the slot; inspect its object-reference targets and matching map data.",
    "LAY": "Supply the creation-time fixed directory with --fixed-reference.",
}


def _particle_preset_record_json(
    record: U9ParticlePresetState,
) -> dict[str, object]:
    """Return a JSON-safe complete particle-preset record."""
    payload = asdict(record)
    payload["version_5_item_extension"] = record.version_5_item_extension.hex()
    payload["version_5_ramp_extension"] = record.version_5_ramp_extension.hex()
    payload["end_offset"] = record.end_offset
    return payload


def _scripted_process_json(record: U9ScriptedProcessState) -> dict[str, object]:
    """Return a JSON-safe scripted-object process prefix."""
    return {
        "version": record.version,
        "primary_object_reference_index": record.primary_object_reference_index,
        "user_object_reference_index": record.user_object_reference_index,
        "argument_1": record.argument_1,
        "argument_2": record.argument_2,
        "temporary_buffer_hex": record.temporary_buffer.hex(),
        "state": record.state,
    }


def _following_process_json(
    record: U9AnimationControllerProcessState
    | U9HangingObjectProcessState
    | U9ScriptTimerProcessState
    | U9PortableLightProcessState
    | U9PlayerProximityProcessState,
) -> dict[str, object]:
    """Return the common and type-specific fields of one decoded process."""
    header = record.header
    world = record.world_state
    payload: dict[str, object] = {
        "offset": record.offset,
        "end_offset": record.end_offset,
        "type": header.process_type,
        "process_id": header.process_id,
        "category": header.category,
        "paused_frames": header.paused_frames,
        "timeout_frames": header.timeout_frames,
        "run_count": header.run_count,
        "next_process_id": header.next_process_id,
        "previous_process_id": header.previous_process_id,
        "execution_mask": header.execution_mask,
        "state_flags": header.state_flags,
        "name": header.name,
        "world_state": {
            "version": world.version,
            "object_reference_indices": list(world.object_reference_indices),
            "map_number": world.map_number,
        },
    }
    if isinstance(record, U9AnimationControllerProcessState):
        payload["animation_controller"] = {
            "version": record.version,
            "object_reference_index": record.object_reference_index,
            "initial_position": list(record.initial_position),
            "calculates_transforms": record.calculates_transforms,
            "shutting_down": record.shutting_down,
            "last_animation_id": record.last_animation_id,
            "animation_root_position": list(record.animation_root_position),
            "translation_scale": list(record.translation_scale),
            "scales_translation": record.scales_translation,
            "upper_lock_count": record.upper_lock_count,
            "upper_lock_slots": list(record.upper_lock_slots),
            "upper_limb_ids": list(record.upper_limb_ids),
            "lower_lock_count": record.lower_lock_count,
            "lower_lock_slots": list(record.lower_lock_slots),
            "lower_limb_ids": list(record.lower_limb_ids),
            "current_translation": list(record.current_translation),
            "applies_events": record.applies_events,
            "forces_animations_to_stop": record.forces_animations_to_stop,
            "attached_element_id": record.attached_element_id,
            "parent_process_id": record.parent_process_id,
            "child_process_id": record.child_process_id,
            "included_limb_ids": list(record.included_limb_ids),
            "excluded_limb_ids": list(record.excluded_limb_ids),
            "animation_tracks": [
                {**asdict(track), "active": track.active}
                for track in record.animation_tracks
            ],
            "kinematic_tracks": [asdict(track) for track in record.kinematic_tracks],
        }
    elif isinstance(record, U9HangingObjectProcessState):
        payload["scripted_state"] = _scripted_process_json(record.scripted_state)
        payload["hanging_object"] = {
            "version": record.version,
            "is_swingable": record.is_swingable,
            "swing_period": record.swing_period,
            "maximum_swing_angle": record.maximum_swing_angle,
            "swing_envelope_period": record.swing_envelope_period,
            "turning_type": record.turning_type,
            "turn_period": record.turn_period,
            "maximum_turn_angle": record.maximum_turn_angle,
            "turn_envelope_period": record.turn_envelope_period,
            "object_status_flags": record.object_status_flags,
            "initial_orientation": list(record.initial_orientation),
            "new_orientation": list(record.new_orientation),
            "old_orientation": list(record.old_orientation),
            "pitch_orientation": list(record.pitch_orientation),
            "yaw_orientation": list(record.yaw_orientation),
            "pitch": record.pitch,
            "yaw": record.yaw,
            "is_swinging": record.is_swinging,
            "swing_envelope_value": record.swing_envelope_value,
            "swing_time_ms": record.swing_time_ms,
            "swing_envelope_time_ms": record.swing_envelope_time_ms,
            "swing_time_constant": record.swing_time_constant,
            "pitch_changed": record.pitch_changed,
            "last_direction": record.last_direction,
            "is_turning": record.is_turning,
            "turn_envelope_value": record.turn_envelope_value,
            "turn_time_ms": record.turn_time_ms,
            "turn_envelope_time_ms": record.turn_envelope_time_ms,
            "turn_time_constant": record.turn_time_constant,
            "yaw_changed": record.yaw_changed,
            "is_collided": record.is_collided,
            "hit_magnitude": record.hit_magnitude,
            "swing_magnitude_fraction": record.swing_magnitude_fraction,
            "turn_magnitude_fraction": record.turn_magnitude_fraction,
            "last_wind": record.last_wind,
            "swing_configuration_bits": record.swing_configuration_bits,
            "turn_configuration_bits": record.turn_configuration_bits,
            "configured_swingable": record.configured_swingable,
            "configured_swing_period": record.configured_swing_period,
            "configured_maximum_swing_angle": (record.configured_maximum_swing_angle),
            "configured_swing_half_life": record.configured_swing_half_life,
            "configured_turning_type": record.configured_turning_type,
            "configured_turn_period": record.configured_turn_period,
            "configured_turn_limit_is_degrees": (
                record.configured_turn_limit_is_degrees
            ),
            "configured_turn_limit": record.configured_turn_limit,
            "configured_turn_half_life": record.configured_turn_half_life,
            "reversed": record.reversed,
            "facing": list(record.facing),
            "reserved": list(record.reserved),
        }
    elif isinstance(record, U9ScriptTimerProcessState):
        payload["scripted_state"] = _scripted_process_json(record.scripted_state)
        payload["script_timer"] = {
            "version": record.version,
            "timer_flags": record.timer_flags,
            "phase_1_duration": record.phase_1_duration,
            "dual_mode": record.dual_mode,
            "time_system": record.time_system,
            "phase_2_duration": record.phase_2_duration,
            "accumulated_time": record.accumulated_time,
            "has_started": record.has_started,
            "phase": record.phase,
            "runs_continuously": record.runs_continuously,
            "starts_in_fast_area": record.starts_in_fast_area,
            "fast_area_stop_flag": record.fast_area_stop_flag,
            "is_quiet_outside_fast_area": record.is_quiet_outside_fast_area,
            "configured_dual_percentage": record.configured_dual_percentage,
            "configured_time_system": record.configured_time_system,
            "configured_duration": record.configured_duration,
            "reserved": list(record.reserved),
        }
    elif isinstance(record, U9PortableLightProcessState):
        payload["portable_light"] = {
            "version": record.version,
            "object_reference_index": record.light_object_reference_index,
            "maximum_fuel": record.maximum_fuel,
            "current_fuel": record.current_fuel,
            "update_elapsed": record.update_elapsed,
            "flare_elapsed": record.flare_elapsed,
            "flare_duration": record.flare_duration,
            "flags": record.flags,
            "is_on": record.is_on,
            "uses_skeletal_flame": record.uses_skeletal_flame,
            "is_flaring": record.is_flaring,
            "is_automatic": record.is_automatic,
            "has_manual_override": record.has_manual_override,
        }
    else:
        payload["scripted_state"] = _scripted_process_json(record.scripted_state)
        payload["player_proximity"] = {
            "version": record.version,
            "enter_distance_squared": record.enter_distance_squared,
            "exit_distance_squared": record.exit_distance_squared,
            "uses_double_threshold": record.uses_double_threshold,
            "location": list(record.location),
            "x": record.x,
            "y": record.y,
            "idle_count": record.idle_count,
            "enabled": record.enabled,
            "reserved": list(record.reserved),
        }
    return payload


@dataclass(frozen=True)
class IntegrityFinding:
    check_id: str
    axis: str
    severity: str
    message: str
    path: str | None = None
    offset: int | None = None
    details: dict[str, object] = field(default_factory=dict)


@dataclass
class IntegrityReport:
    target: str
    slot: int | None = None
    archive: str | None = None
    findings: list[IntegrityFinding] = field(default_factory=list)
    artifacts: dict[str, dict[str, object]] = field(default_factory=dict)

    def add(
        self,
        check_id: str,
        axis: str,
        severity: str,
        message: str,
        *,
        path: str | Path | None = None,
        offset: int | None = None,
        **details: object,
    ) -> None:
        self.findings.append(
            IntegrityFinding(
                check_id,
                axis,
                severity,
                message,
                str(path) if path is not None else None,
                offset,
                details,
            )
        )

    def verdict(self, axis: str | None = None) -> str:
        relevant = [f for f in self.findings if axis is None or f.axis == axis]
        rank = max((SEVERITY_RANK[f.severity] for f in relevant), default=0)
        return ("PASS", "WARN", "ERROR", "FATAL")[rank]

    @property
    def overall(self) -> str:
        return self.verdict()

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "slot": self.slot,
            "archive": self.archive,
            "verdicts": {axis: self.verdict(axis) for axis in AXES},
            "overall": self.overall,
            "artifacts": self.artifacts,
            "findings": [asdict(finding) for finding in self.findings],
        }

    def write_json(self, filepath: str | Path) -> None:
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(self.to_dict(), file, indent=2)
            file.write("\n")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files_by_map(directory: Path, kind: str) -> dict[int, Path]:
    files: dict[int, Path] = {}
    if not directory.is_dir():
        return files
    for path in directory.iterdir():
        match = MAP_FILE_RE.match(path.name)
        if match and match.group(1).casefold() == kind and path.is_file():
            files[int(match.group(2))] = path
    return files


def _record_artifact(
    report: IntegrityReport, name: str, data: bytes, *, source: str, **details: object
) -> None:
    report.artifacts[name] = {
        "source": source,
        "bytes": len(data),
        "sha256": _sha256(data),
        **details,
    }


def _check_nonfixed(
    report: IntegrityReport, name: str, data: bytes, *, source: str
) -> U9Nonfixed | None:
    _record_artifact(report, name, data, source=source)
    try:
        nonfixed = U9Nonfixed(data)
        chunks = nonfixed.chunks()
    except (U9NonfixedError, ValueError, IndexError) as error:
        report.add("NFS01", "structure", "FATAL", str(error), path=source)
        return None
    incomplete = [chunk.index for chunk in chunks if not chunk.allocation_is_complete]
    report.artifacts[name].update(
        grid=f"{nonfixed.width}x{nonfixed.height}",
        chunks=len(chunks),
        pages=sum(len(chunk.pages) for chunk in chunks),
        indexed_entities=sum(len(chunk.entities) for chunk in chunks),
        allocated_entities=sum(len(chunk.allocated_entities) for chunk in chunks),
        extra_data=sum(len(chunk.extra_data_records) for chunk in chunks),
        incomplete_chunks=len(incomplete),
    )
    if nonfixed.declared_payload_size not in (0, nonfixed.payload_size):
        report.add(
            "NFS01",
            "structure",
            "WARN",
            "declared payload watermark differs from physical payload",
            path=source,
            declared=nonfixed.declared_payload_size,
            actual=nonfixed.payload_size,
        )
    if incomplete:
        report.add(
            "NFS07",
            "structure",
            "WARN",
            f"allocator recovery is incomplete in {len(incomplete)} chunks",
            path=source,
            chunk_indices=incomplete,
        )
    return nonfixed


def _check_fixed(
    report: IntegrityReport, path: Path, map_number: int
) -> U9Fixed | None:
    data = path.read_bytes()
    name = f"fixed.{map_number}"
    _record_artifact(report, name, data, source=str(path))
    try:
        fixed = U9Fixed(data)
        chunks = fixed.chunks()
    except (U9FixedError, ValueError, IndexError) as error:
        report.add("FXS01", "structure", "FATAL", str(error), path=path)
        return None
    pages = [page for chunk in chunks for page in chunk.pages]
    invalid = [page.offset for page in pages if not page.free_list_walked]
    report.artifacts[name].update(
        grid=f"{fixed.width}x{fixed.height}",
        regions=len(chunks),
        pages=len(pages),
        objects=sum(len(chunk.objects) for chunk in chunks),
        invalid_free_lists=len(invalid),
        declared_heap=fixed.heap_size,
        physical_payload=fixed.payload_size,
    )
    if fixed.heap_size > fixed.payload_size:
        report.add(
            "FXS01",
            "structure",
            "FATAL",
            "declared fixed heap extends beyond EOF",
            path=path,
            declared=fixed.heap_size,
            actual=fixed.payload_size,
        )
    if invalid:
        report.add(
            "FXS04",
            "structure",
            "FATAL",
            f"{len(invalid)} of {len(pages)} page free lists are invalid",
            path=path,
            page_offsets=invalid,
        )
    return fixed


def _target_records(
    table: U9ObjectReferenceTable,
    indices: list[int],
    nonfixed: dict[int, U9Nonfixed],
    fixed: dict[int, U9Fixed],
    allocation_state: str,
) -> list[dict[str, object]]:
    references_by_target: dict[tuple[str, int, int], list[int]] = {}
    for index in indices:
        entry = table.entries[index]
        arena = "fixed" if entry.is_fixed else "nonfixed"
        references_by_target.setdefault(
            (arena, entry.map_number, entry.object_offset), []
        ).append(index)

    records: list[dict[str, object]] = []
    for (arena, map_number, offset), reference_indices in sorted(
        references_by_target.items()
    ):
        page_offset = offset & ~0xFFF
        slot_size = 24 if arena == "fixed" else 32
        slot = (offset - page_offset - 0x60) // slot_size
        if arena == "fixed":
            heap = fixed.get(map_number)
            record = heap.object_record_at(offset) if heap is not None else None
            local_x = record.x if record is not None else None
            local_y = record.y if record is not None else None
        else:
            heap = nonfixed.get(map_number)
            record = heap.entity_record_at(offset) if heap is not None else None
            local_x = record.offset_x if record is not None else None
            local_y = record.offset_y if record is not None else None
        detail: dict[str, object] = {
            "reference_indices": reference_indices,
            # Compatibility alias for version-1 integrity-report readers.
            "handles": reference_indices,
            "arena": arena,
            "map": map_number,
            "offset": offset,
            "page_offset": page_offset,
            "slot": slot,
            "allocation_state": allocation_state,
        }
        if record is not None:
            detail.update(
                page=[record.base_x, record.base_y],
                xyz=[local_x, local_y, record.z],
                world_xyz=[record.world_x, record.world_y, record.z],
                type=record.type_index,
                rotation=list(record.rotation),
                status=record.flags,
                status_hex=f"{record.flags:05x}",
            )
        records.append(detail)
    return records


def _resolve_object_references(
    report: IntegrityReport,
    table: U9ObjectReferenceTable,
    nonfixed: dict[int, U9Nonfixed],
    fixed: dict[int, U9Fixed],
) -> None:
    missing_maps: set[tuple[str, int]] = set()
    invalid_slots: list[int] = []
    fixed_free: list[int] = []
    nonfixed_free: list[int] = []
    unknown: list[int] = []

    nonfixed_state: dict[int, tuple[set[int], set[int]]] = {}
    for map_number, heap in nonfixed.items():
        chunks = heap.chunks()
        live = {
            entity.offset for chunk in chunks for entity in chunk.allocated_entities
        }
        uncertain_pages = {
            page.offset
            for chunk in chunks
            if not chunk.allocation_is_complete
            for page in chunk.pages
        }
        nonfixed_state[map_number] = live, uncertain_pages

    fixed_state: dict[int, tuple[set[int], dict[int, bool], int]] = {}
    for map_number, heap in fixed.items():
        chunks = heap.chunks()
        live = {obj.offset for chunk in chunks for obj in chunk.objects}
        pages = {
            page.offset: page.free_list_walked
            for chunk in chunks
            for page in chunk.pages
        }
        fixed_state[map_number] = live, pages, min(heap.heap_size, heap.payload_size)

    for entry in table.live_entries:
        offset = entry.object_offset
        page_offset = offset & ~0xFFF
        if entry.is_fixed:
            state = fixed_state.get(entry.map_number)
            if state is None:
                missing_maps.add(("fixed", entry.map_number))
                continue
            live, pages, heap_size = state
            slot_delta = offset - page_offset - 0x60
            if (
                offset >= heap_size
                or slot_delta < 0
                or slot_delta % 24
                or slot_delta // 24 >= 166
            ):
                invalid_slots.append(entry.index)
            elif not pages.get(page_offset, False):
                unknown.append(entry.index)
            elif offset not in live:
                fixed_free.append(entry.index)
        else:
            state = nonfixed_state.get(entry.map_number)
            if state is None:
                missing_maps.add(("nonfixed", entry.map_number))
                continue
            live, uncertain_pages = state
            slot_delta = offset - page_offset - 0x60
            if slot_delta < 0 or slot_delta % 32 or slot_delta // 32 >= 125:
                invalid_slots.append(entry.index)
            elif offset in live:
                continue
            elif page_offset in uncertain_pages:
                unknown.append(entry.index)
            else:
                nonfixed_free.append(entry.index)

    if missing_maps:
        report.add(
            "REF01",
            "compatibility",
            "FATAL",
            f"{len(missing_maps)} object-reference target map arenas are unavailable",
            arenas=[
                f"{kind}.{map_number}" for kind, map_number in sorted(missing_maps)
            ],
        )
    if invalid_slots:
        report.add(
            "REF02",
            "compatibility",
            "FATAL",
            f"{len(invalid_slots)} object references have out-of-bounds or "
            "misaligned object offsets",
            reference_indices=invalid_slots,
            # Compatibility alias retained for existing JSON consumers.
            handle_indices=invalid_slots,
        )
    if fixed_free:
        targets = {
            (table.entries[index].map_number, table.entries[index].object_offset)
            for index in fixed_free
        }
        report.add(
            "REF03",
            "compatibility",
            "FATAL",
            f"{len(fixed_free)} fixed object references resolve to "
            f"{len(targets)} non-live slots",
            reference_indices=fixed_free,
            # Compatibility alias retained for existing JSON consumers.
            handle_indices=fixed_free,
            targets=[
                {"map": map_number, "offset": offset}
                for map_number, offset in sorted(targets)
            ],
            target_records=_target_records(
                table, fixed_free, nonfixed, fixed, "non-live"
            ),
        )
    if nonfixed_free:
        report.add(
            "REF04",
            "compatibility",
            "ERROR",
            f"{len(nonfixed_free)} nonfixed object references resolve to non-live slots",
            reference_indices=nonfixed_free,
            # Compatibility alias retained for existing JSON consumers.
            handle_indices=nonfixed_free,
            target_records=_target_records(
                table, nonfixed_free, nonfixed, fixed, "non-live"
            ),
        )
    if unknown:
        report.add(
            "REF07",
            "compatibility",
            "WARN",
            f"{len(unknown)} object-reference targets cannot be classified on "
            "invalid/incomplete pages",
            reference_indices=unknown,
            # Compatibility alias retained for existing JSON consumers.
            handle_indices=unknown,
            target_records=_target_records(table, unknown, nonfixed, fixed, "unknown"),
        )


def _resolve_directories(target: Path) -> tuple[Path, Path | None]:
    if (target / "savegame").is_dir():
        return target / "savegame", target / "static"
    return target, target.parent / "static"


def check_save(
    target: str | Path,
    *,
    slot: int | None = None,
    static_directory: str | Path | None = None,
    fixed_reference_directory: str | Path | None = None,
    allow_partial: bool = False,
) -> IntegrityReport:
    """Check one U9 install/save directory and return a display-neutral report."""
    target_path = Path(target)
    save_directory, default_static = _resolve_directories(target_path)
    static_path = Path(static_directory) if static_directory else default_static
    report = IntegrityReport(str(target_path))

    if not save_directory.is_dir():
        report.add(
            "SEL02",
            "custody",
            "FATAL",
            "save directory does not exist",
            path=save_directory,
        )
        return report

    if slot is None:
        start_path = save_directory / "start.dat"
        try:
            slot = U9StartDat.from_file(start_path).slot
        except (OSError, U9SaveError) as error:
            report.add("SEL01", "custody", "FATAL", str(error), path=start_path)
            return report
    report.slot = slot

    archive_path = save_directory / f"u9game{slot}.sav"
    report.archive = str(archive_path)
    try:
        archive_data = archive_path.read_bytes()
        archive = U9SaveArchive.from_bytes(archive_data)
    except (OSError, U9SaveError) as error:
        report.add("ARC01", "custody", "FATAL", str(error), path=archive_path)
        return report
    _record_artifact(
        report,
        "archive",
        archive_data,
        source=str(archive_path),
        description=archive.header.description,
        saved_map=archive.header.saved_map,
        maps=[member.map_number for member in archive.nonfixed],
    )
    _record_artifact(
        report,
        "archive/processes.dat",
        archive.processes.data,
        source=f"{archive_path}!processes.dat",
    )
    stray_maps = [
        member.map_number
        for member in archive.nonfixed
        if member.map_number is not None and member.map_number > MAX_SHIPPED_MAP_NUMBER
    ]
    if stray_maps:
        report.add(
            "ARC10",
            "custody",
            "WARN",
            f"{len(stray_maps)} archived map members are numbered above "
            f"{MAX_SHIPPED_MAP_NUMBER}: {stray_maps}. The game archives and restores "
            f"nonfixed.0-{MAX_MAP_NUMBER}, so this is legal, but no shipped map has "
            "these numbers; they come from stray loose files in the save directory",
            path=archive_path,
        )
    object_references: U9ObjectReferenceTable | None = None
    try:
        object_references = U9ObjectReferenceTable.from_bytes(archive.processes.data)
    except U9ProcessDataError as error:
        report.add(
            "HND01",
            "structure",
            "FATAL",
            str(error),
            path=f"{archive_path}!processes.dat",
        )
    process_prefix: U9ProcessDataPrefix | None = None
    if object_references is not None:
        try:
            process_prefix = U9ProcessDataPrefix.from_bytes(archive.processes.data)
        except U9ProcessDataError as error:
            report.add(
                "PRC01",
                "structure",
                "FATAL",
                str(error),
                path=f"{archive_path}!processes.dat",
            )

    pairs = [(archive.processes, save_directory / "processes.dat")]
    pairs.extend((member, save_directory / member.name) for member in archive.nonfixed)
    missing_members: list[str] = []
    for member, loose_path in pairs:
        check_id = "CUS01" if member.name == "processes.dat" else "CUS03"
        if not loose_path.is_file():
            if allow_partial:
                missing_members.append(member.name)
                continue
            report.add(
                "CUS02" if member.map_number is not None else check_id,
                "custody",
                "FATAL",
                f"archived member {member.name} is missing from working directory",
                path=loose_path,
            )
            continue
        loose_data = loose_path.read_bytes()
        if member.name == "processes.dat":
            _record_artifact(
                report,
                "working/processes.dat",
                loose_data,
                source=str(loose_path),
            )
        if loose_data != member.data:
            report.add(
                check_id,
                "custody",
                "FATAL",
                f"working {member.name} differs from selected archive member",
                path=loose_path,
                archive_sha256=_sha256(member.data),
                working_sha256=_sha256(loose_data),
            )
    if missing_members:
        report.add(
            "CUS07",
            "custody",
            "INFO",
            f"partial bundle omits {len(missing_members)} archived working files",
            omitted=missing_members,
        )

    archived_maps = {member.map_number for member in archive.nonfixed}
    loose_nonfixed = _files_by_map(save_directory, "nonfixed")
    for map_number, path in sorted(loose_nonfixed.items()):
        if map_number not in archived_maps:
            report.add(
                "CUS04",
                "custody",
                "WARN",
                f"working nonfixed.{map_number} has no member in selected archive",
                path=path,
            )

    archive_nonfixed: dict[int, U9Nonfixed] = {}
    for member in archive.nonfixed:
        parsed = _check_nonfixed(
            report,
            f"archive/{member.name}",
            member.data,
            source=f"{archive_path}!{member.name}",
        )
        if parsed is not None and member.map_number is not None:
            archive_nonfixed[member.map_number] = parsed
    for map_number, path in sorted(loose_nonfixed.items()):
        _check_nonfixed(
            report,
            f"working/nonfixed.{map_number}",
            path.read_bytes(),
            source=str(path),
        )

    # A member numbered above the shipped range is a stray file the save swept up
    # (ARC10). It needs no fixed map unless an object reference points at it.
    relevant_maps = {archive.header.saved_map}
    relevant_maps.update(m for m in archived_maps if m <= MAX_SHIPPED_MAP_NUMBER)
    if object_references is not None:
        relevant_maps.update(
            entry.map_number for entry in object_references.live_entries
        )
    fixed_files = _files_by_map(static_path, "fixed") if static_path else {}
    fixed_maps_to_check = (
        relevant_maps & fixed_files.keys() if allow_partial else relevant_maps
    )
    parsed_fixed: dict[int, U9Fixed] = {}
    missing_fixed: list[int] = []
    for map_number in sorted(fixed_maps_to_check):
        fixed_path = fixed_files.get(map_number)
        if fixed_path is None:
            missing_fixed.append(map_number)
            report.add(
                "REF01",
                "compatibility",
                "FATAL",
                f"fixed.{map_number} is unavailable for a save-relevant map",
                path=static_path,
            )
            continue
        parsed = _check_fixed(report, fixed_path, map_number)
        if parsed is not None:
            parsed_fixed[map_number] = parsed

    if allow_partial:
        missing_fixed = sorted(relevant_maps - fixed_files.keys())
        if missing_fixed:
            report.add(
                "REF08",
                "compatibility",
                "INFO",
                f"partial bundle omits fixed files for {len(missing_fixed)} archive maps",
                map_numbers=missing_fixed,
            )

    if fixed_reference_directory is not None:
        references = _files_by_map(Path(fixed_reference_directory), "fixed")
        comparison_maps = (
            fixed_maps_to_check & references.keys() if allow_partial else relevant_maps
        )
        for map_number in sorted(comparison_maps):
            current = fixed_files.get(map_number)
            reference = references.get(map_number)
            if current is None or reference is None:
                report.add(
                    "LAY04",
                    "compatibility",
                    "WARN",
                    f"fixed.{map_number} cannot be compared with a trusted reference",
                    path=reference or current,
                )
            elif current.read_bytes() != reference.read_bytes():
                report.add(
                    "LAY02",
                    "compatibility",
                    "ERROR",
                    f"fixed.{map_number} differs byte-for-byte from the trusted reference",
                    path=current,
                    current_sha256=_sha256(current.read_bytes()),
                    reference_sha256=_sha256(reference.read_bytes()),
                )
            else:
                report.add(
                    "LAY01",
                    "compatibility",
                    "INFO",
                    f"fixed.{map_number} is byte-identical to the trusted reference",
                    path=current,
                )
    else:
        report.add(
            "LAY04",
            "compatibility",
            "WARN",
            "no creation-time fixed reference directory was supplied",
        )

    if object_references is not None:
        try:
            free_chain = object_references.walk_free_chain()
        except U9ProcessDataError as error:
            free_chain = ()
            report.add(
                "HND02",
                "structure",
                "ERROR",
                str(error),
                path=f"{archive_path}!processes.dat",
            )
        report.artifacts["archive/processes.dat"].update(
            reference_table_offset=object_references.offset,
            reference_count=object_references.count,
            free_references=len(free_chain),
            live_references=len(object_references.live_entries),
            fixed_references=len(object_references.fixed_entries),
            nonfixed_references=len(object_references.nonfixed_entries),
            # Compatibility aliases retained for existing JSON consumers.
            handle_offset=object_references.offset,
            handle_count=object_references.count,
            free_handles=len(free_chain),
            live_handles=len(object_references.live_entries),
            fixed_handles=len(object_references.fixed_entries),
            nonfixed_handles=len(object_references.nonfixed_entries),
        )
        if process_prefix is not None:
            camera = process_prefix.camera
            control = process_prefix.camera_control
            targeting = control.targeting
            first_process = process_prefix.first_process
            report.artifacts["archive/processes.dat"].update(
                camera={
                    "offset": camera.offset,
                    "version": camera.version,
                    "focus_position": list(camera.focus_position),
                    "orientation": [camera.yaw, camera.pitch, camera.roll],
                    "focus_distance": camera.focus_distance,
                    "mode": camera.mode,
                    "exclusive_interface": camera.exclusive_interface,
                    "horizontal_fov": camera.horizontal_fov,
                    "clip_distances": [
                        camera.near_distance,
                        camera.middle_distance,
                        camera.far_distance,
                    ],
                    "effect_count": len(camera.effects),
                    "effect_versions": [effect.version for effect in camera.effects],
                    "effect_record_sizes": [effect.size for effect in camera.effects],
                },
                camera_control={
                    "offset": control.offset,
                    "version": control.version,
                    "target_position": list(control.target_position),
                    "target_orientation": [control.target_yaw, control.target_pitch],
                    "current_distance": control.current_distance,
                    "maximum_distance": control.maximum_distance,
                    "underground": control.underground,
                    "underwater": control.underwater,
                    "on_moon": control.on_moon,
                    "target_mode": control.target_mode,
                    "temporary_camera_present": control.has_temporary_camera,
                    "targeting": (
                        {
                            "version": targeting.version,
                            "movement_mode": targeting.movement_mode,
                            "visual_mode": targeting.visual_mode,
                            "visibility": targeting.visibility,
                            "ranges": list(targeting.ranges),
                            "position": list(targeting.position),
                            "screen_position": list(targeting.screen_position),
                        }
                        if targeting is not None
                        else None
                    ),
                },
                process_list_offset=process_prefix.process_list_offset,
                first_process_type=process_prefix.first_process_type,
                first_process=(
                    {
                        "offset": first_process.header.offset,
                        "payload_offset": first_process.payload_offset,
                        "type": first_process.header.process_type,
                        "process_id": first_process.header.process_id,
                        "category": first_process.header.category,
                        "paused_frames": first_process.header.paused_frames,
                        "timeout_frames": first_process.header.timeout_frames,
                        "run_count": first_process.header.run_count,
                        "next_process_id": first_process.header.next_process_id,
                        "previous_process_id": first_process.header.previous_process_id,
                        "execution_mask": first_process.header.execution_mask,
                        "state_flags": first_process.header.state_flags,
                        "name": first_process.header.name,
                        "next_process_offset": process_prefix.next_process_offset,
                        "next_process_type": process_prefix.next_process_type,
                        "next_process_name": (
                            process_prefix.next_process_header.name
                            if process_prefix.next_process_header is not None
                            else None
                        ),
                        "world_state": (
                            {
                                "version": first_process.world_state.version,
                                "object_reference_indices": list(
                                    first_process.world_state.object_reference_indices
                                ),
                                "map_number": first_process.world_state.map_number,
                            }
                            if first_process.world_state is not None
                            else None
                        ),
                        "particle_state": (
                            {
                                "version": first_process.particle_state.version,
                                "animation_time": (
                                    first_process.particle_state.animation_time
                                ),
                                "translation_flag": (
                                    first_process.particle_state.translation_flag
                                ),
                                "translation_pending": (
                                    first_process.particle_state.translation_pending
                                ),
                                "next_particle_id": (
                                    first_process.particle_state.next_particle_id
                                ),
                                "record_counts": {
                                    "particle_presets": (
                                        first_process.particle_state.particle_preset_count
                                    ),
                                    "generations": (
                                        first_process.particle_state.generation_count
                                    ),
                                    "particles": (
                                        first_process.particle_state.particle_count
                                    ),
                                    "force_presets": (
                                        first_process.particle_state.force_preset_count
                                    ),
                                    "forces": first_process.particle_state.force_count,
                                },
                                "records_offset": (
                                    first_process.particle_state.end_offset
                                ),
                                "end_offset": (
                                    first_process.particle_state.records.end_offset
                                ),
                                "collections": {
                                    collection_key: {
                                        "offset": collection.offset,
                                        "end_offset": collection.end_offset,
                                        "count": collection.count,
                                        "record_size": collection.record_size,
                                    }
                                    for collection_key, collection in (
                                        (
                                            "particle_presets",
                                            first_process.particle_state.records.particle_presets,
                                        ),
                                        (
                                            "force_presets",
                                            first_process.particle_state.records.force_presets,
                                        ),
                                        (
                                            "forces",
                                            first_process.particle_state.records.forces,
                                        ),
                                        (
                                            "generations",
                                            first_process.particle_state.records.generations,
                                        ),
                                        (
                                            "particles",
                                            first_process.particle_state.records.particles,
                                        ),
                                    )
                                },
                                "particle_preset_records": [
                                    _particle_preset_record_json(record)
                                    for record in first_process.particle_state.records.particle_preset_records
                                ],
                                "force_preset_records": [
                                    {
                                        "record_id": record.record_id,
                                        "force_type": record.force_type,
                                        "lifetime": record.lifetime,
                                        "initial_age": record.initial_age,
                                        "trigger_age": record.trigger_age,
                                        "location": list(record.location),
                                        "strength": record.strength,
                                        "influence_distance": (
                                            record.influence_distance
                                        ),
                                        "inner_radius": record.inner_radius,
                                        "scale": list(record.scale),
                                        "speed_limit": record.speed_limit,
                                        "twist_velocity": list(record.twist_velocity),
                                        "offset_vector": list(record.offset_vector),
                                        "element_id": record.element_id,
                                        "hard_point_id": record.hard_point_id,
                                        "numeric_type": record.numeric_type,
                                        "object_reference_index": (
                                            record.object_reference_index
                                        ),
                                        "offset": record.offset,
                                        "end_offset": record.end_offset,
                                    }
                                    for record in first_process.particle_state.records.force_preset_records
                                ],
                                "force_records": [
                                    {
                                        "record_id": record.record_id,
                                        "age": record.age,
                                        "location": list(record.location),
                                        "preset_id": record.preset_id,
                                        "offset": record.offset,
                                        "end_offset": record.end_offset,
                                    }
                                    for record in first_process.particle_state.records.force_records
                                ],
                                "generation_records": [
                                    {
                                        "record_id": record.record_id,
                                        "particle_preset_id": (
                                            record.particle_preset_id
                                        ),
                                        "birth_generation_id": (
                                            record.birth_generation_id
                                        ),
                                        "lifetime_generation_id": (
                                            record.lifetime_generation_id
                                        ),
                                        "death_generation_id": (
                                            record.death_generation_id
                                        ),
                                        "birth_force_ids": list(record.birth_force_ids),
                                        "lifetime_force_ids": list(
                                            record.lifetime_force_ids
                                        ),
                                        "death_force_ids": list(record.death_force_ids),
                                        "slave_force_ids": list(record.slave_force_ids),
                                        "slave_generation_ids": list(
                                            record.slave_generation_ids
                                        ),
                                        "offset": record.offset,
                                        "end_offset": record.end_offset,
                                    }
                                    for record in first_process.particle_state.records.generation_records
                                ],
                                "particle_records": [
                                    {
                                        "record_id": record.record_id,
                                        "generation_id": record.generation_id,
                                        "parent_particle_id": (
                                            record.parent_particle_id
                                        ),
                                        "child_particle_ids": list(
                                            record.child_particle_ids
                                        ),
                                        "lifetime": record.lifetime,
                                        "age": record.age,
                                        "location": list(record.location),
                                        "velocity": list(record.velocity),
                                        "snap_velocity": list(record.snap_velocity),
                                        "scale": list(record.scale),
                                        "orientation_quaternion": list(
                                            record.orientation_quaternion
                                        ),
                                        "rotation_quaternion": list(
                                            record.rotation_quaternion
                                        ),
                                        "spawn_mean_lifetime": (
                                            record.spawn_mean_lifetime
                                        ),
                                        "spawn_pulse_count": (record.spawn_pulse_count),
                                        "spawn_pulse_count_byte": (
                                            record.spawn_pulse_count_byte
                                        ),
                                        "pulse_count_byte_matches": (
                                            record.pulse_count_byte_matches
                                        ),
                                        "object_type_id": record.object_type_id,
                                        "object_status_flags": (
                                            record.object_status_flags
                                        ),
                                        "swap_sequence": record.swap_sequence,
                                        "sequence_index": record.sequence_index,
                                        "swap_elapsed_frames": (
                                            record.swap_elapsed_frames
                                        ),
                                        "attached_element_id": (
                                            record.attached_element_id
                                        ),
                                        "sound_id": record.sound_id,
                                        "light_source_flag": (record.light_source_flag),
                                        "has_light_source": record.has_light_source,
                                        "callback_id": record.callback_id,
                                        "callback_effect_id": (
                                            record.callback_effect_id
                                        ),
                                        "callback_magic_type": (
                                            record.callback_magic_type
                                        ),
                                        "callback_caster_reference_index": (
                                            record.callback_caster_reference_index
                                        ),
                                        "object_reference_index": (
                                            record.object_reference_index
                                        ),
                                        "offset": record.offset,
                                        "end_offset": record.end_offset,
                                    }
                                    for record in first_process.particle_state.records.particle_records
                                ],
                            }
                            if first_process.particle_state is not None
                            else None
                        ),
                    }
                    if first_process is not None
                    else None
                ),
                next_process_offset=process_prefix.next_process_offset,
                next_process_type=process_prefix.next_process_type,
                next_process_name=(
                    process_prefix.next_process_header.name
                    if process_prefix.next_process_header is not None
                    else None
                ),
                decoded_following_process_count=len(process_prefix.following_processes),
                decoded_following_processes=[
                    _following_process_json(record)
                    for record in process_prefix.following_processes
                ],
                blocked_process_offset=process_prefix.blocked_process_offset,
                blocked_process_type=process_prefix.blocked_process_type,
                process_terminator_offset=process_prefix.terminator_offset,
            )
        invalid_entries = [
            entry.index
            for entry in object_references.live_entries
            if entry.reference_count <= 0 or entry.map_number > MAX_MAP_NUMBER
        ]
        if invalid_entries:
            report.add(
                "HND04",
                "structure",
                "ERROR",
                f"{len(invalid_entries)} live object references have invalid "
                "count/map fields",
                path=f"{archive_path}!processes.dat",
                reference_indices=invalid_entries,
                # Compatibility alias retained for existing JSON consumers.
                handle_indices=invalid_entries,
            )
        _resolve_object_references(
            report, object_references, archive_nonfixed, parsed_fixed
        )
    return report


def render_integrity_report(report: IntegrityReport) -> str:
    """Render a compact, deterministic terminal report."""
    lines = [
        "Ultima IX save integrity",
        f"Target: {report.target}",
        f"Slot: {report.slot if report.slot is not None else '-'}",
        f"Archive: {report.archive or '-'}",
        "",
        f"Assessment: {ASSESSMENTS[report.overall]}",
        "",
        "Checks",
    ]
    for axis in AXES:
        lines.append(
            f"  {axis.title():13} {report.verdict(axis):5}  {AXIS_DESCRIPTIONS[axis]}"
        )

    actionable = [finding for finding in report.findings if finding.severity != "INFO"]
    confirmations = [
        finding for finding in report.findings if finding.severity == "INFO"
    ]
    problem_groups: dict[tuple[str, str, str, str], list[IntegrityFinding]] = {}
    for finding in actionable:
        key = (finding.severity, finding.check_id, finding.axis, finding.message)
        problem_groups.setdefault(key, []).append(finding)
    problem_count = len(problem_groups)
    problem_label = str(problem_count)
    if problem_count != len(actionable):
        problem_label = f"{problem_count} distinct, {len(actionable)} findings"
    lines.extend(("", f"Problems ({problem_label})"))
    if not actionable:
        lines.append("  None")
    for key, findings in sorted(
        problem_groups.items(),
        key=lambda item: (-SEVERITY_RANK[item[0][0]], item[0][2], item[0][1]),
    ):
        severity, check_id, axis, message = key
        lines.append(f"  {severity:5} {check_id} {axis}: {message}")
        sources = sorted({finding.path for finding in findings if finding.path})
        for source in sources:
            lines.append(f"        Source: {source}")
        target_records: list[dict[str, object]] = []
        seen_targets: set[tuple[object, object, object]] = set()
        for finding in findings:
            for record in finding.details.get("target_records", []):
                identity = (
                    record.get("arena"),
                    record.get("map"),
                    record.get("offset"),
                )
                if identity not in seen_targets:
                    seen_targets.add(identity)
                    target_records.append(record)
        for record in target_records[:8]:
            references = ",".join(str(value) for value in record["reference_indices"])
            prefix = (
                f"        Evidence: reference({references}) "
                f"{record['arena']}.{record['map']} "
                f"offset 0x{record['offset']:X} slot {record['slot']}"
            )
            if "page" not in record:
                lines.append(f"{prefix} state {record['allocation_state']}")
                continue
            page_x, page_y = record["page"]
            x, y, z = record["xyz"]
            rotation = ", ".join(str(value) for value in record["rotation"])
            lines.append(
                f"{prefix} page({page_x},{page_y}) xyz({x},{y},{z}) "
                f"type {record['type']} rot({rotation}) status {record['status_hex']} "
                f"state {record['allocation_state']}"
            )
        if len(target_records) > 8:
            lines.append(
                f"        Evidence: {len(target_records) - 8} more target records in JSON"
            )

    recommendation_families = {
        finding.check_id[:3]
        for finding in actionable
        if finding.check_id[:3] in RECOMMENDATIONS
    }
    if recommendation_families:
        lines.extend(("", "Next steps"))
        for family in sorted(recommendation_families):
            lines.append(f"  {family}: {RECOMMENDATIONS[family]}")

    lines.extend(("", f"Confirmations ({len(confirmations)})"))
    if not confirmations:
        lines.append("  None")
    for finding in sorted(confirmations, key=lambda item: (item.axis, item.check_id)):
        location = f" [{finding.path}]" if finding.path else ""
        lines.append(f"  {finding.check_id} {finding.message}{location}")

    lines.extend(("", "Evidence"))
    for name, artifact in report.artifacts.items():
        summary = [
            f"{artifact.get('bytes', 0)} bytes",
            str(artifact.get("sha256", ""))[:12],
        ]
        for key in (
            "maps",
            "reference_count",
            "live_references",
            "fixed_references",
            "nonfixed_references",
            "chunks",
            "pages",
            "objects",
            "incomplete_chunks",
            "invalid_free_lists",
        ):
            if key in artifact:
                summary.append(f"{key}={artifact[key]}")
        camera = artifact.get("camera")
        if isinstance(camera, dict):
            summary.append(
                f"camera=v{camera['version']}/effects{camera['effect_count']}"
            )
        camera_control = artifact.get("camera_control")
        if isinstance(camera_control, dict):
            summary.append(f"camera_control=v{camera_control['version']}")
        if "first_process_type" in artifact:
            summary.append(f"first_process_type={artifact['first_process_type']}")
        first_process = artifact.get("first_process")
        if isinstance(first_process, dict):
            summary.append(
                f"first_process={first_process['type']}/{first_process['name']}"
            )
        if artifact.get("next_process_type") is not None:
            summary.append(
                f"next_process={artifact['next_process_type']}/"
                f"{artifact.get('next_process_name') or '(unnamed)'}"
            )
        if "decoded_following_process_count" in artifact:
            summary.append(
                "decoded_following_processes="
                f"{artifact['decoded_following_process_count']}"
            )
        if artifact.get("blocked_process_type") is not None:
            summary.append(f"blocked_process_type={artifact['blocked_process_type']}")
        lines.append(f"  {name}: {', '.join(summary)}")
    return "\n".join(lines)
