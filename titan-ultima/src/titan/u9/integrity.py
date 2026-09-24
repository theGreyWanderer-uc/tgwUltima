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
from titan.u9.process_data import U9ObjectReferenceTable, U9ProcessDataError
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
    "REF": "Do not load or overwrite the slot; inspect its object-reference targets and matching map data.",
    "LAY": "Supply the creation-time fixed directory with --fixed-reference.",
}


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
        lines.append(f"  {name}: {', '.join(summary)}")
    return "\n".join(lines)
