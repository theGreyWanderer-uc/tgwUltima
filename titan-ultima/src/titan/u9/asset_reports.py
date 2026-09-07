"""Cross-file CSV/JSON reports for Ultima IX textures and model materials.

The report builders deliberately produce dictionaries rather than fixed record
classes.  Ultima IX metadata is spread across optional companion files, so a
fixed schema would either hide useful discoveries or fill most exports with
meaningless empty columns.  :func:`write_dynamic_report` instead forms a
deterministic union of the keys actually emitted by the available helpers.
"""

from __future__ import annotations

__all__ = [
    "MODEL_REPORT_COLUMNS",
    "TEXTURE_REPORT_COLUMNS",
    "U9AssetReportError",
    "build_model_material_report",
    "build_texture_frame_report",
    "write_dynamic_report",
]

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from titan.u9.flx_archive import U9FlxArchive, U9FlxArchiveError
from titan.u9.model import INVISIBLE_TEXTURE_ID, U9Material, U9Model, U9ModelError
from titan.u9.model_naming import names_for_model
from titan.u9.sdinfo import U9SdInfo, U9SdInfoError
from titan.u9.texture import U9TextureError, parse_texture_set
from titan.u9.texture_writer import U9TextureWriteError, frame_encoding
from titan.u9.typename import U9TypeNames
from titan.u9.types_dat import U9TypesDat, U9TypesDatError


class U9AssetReportError(Exception):
    """Raised when report inputs or output options are invalid."""


@dataclass(frozen=True)
class _TextureSource:
    tier: str
    path: Path
    sdinfo_path: Path | None


@dataclass(frozen=True)
class _MaterialReference:
    model_id: int
    record_format: str
    model_fields: dict[str, Any]
    limb_index: int
    limb_id: int
    parent_limb_id: int
    limb_fields: dict[str, Any]
    lod_index: int
    material_index: int
    lod_fields: dict[str, Any]
    material: U9Material


KNOWN_TEXTURE_FILES = (
    ("bitmapsh.flx", "sh", "sdInfo.flx"),
    ("bitmap16.flx", "16", "sdInfo16.flx"),
    ("bitmapc.flx", "c", "sdInfoC.flx"),
)

TEXTURE_REPORT_COLUMNS = [
    "texture_tier",
    "texture_archive",
    "entry_id",
    "entry_offset",
    "entry_length",
    "entry_status",
    "parse_error",
    "frame_index",
    "frame_count",
    "is_multiframe",
    "animation_status",
    "animation_evidence",
    "set_width",
    "set_height",
    "frame_width",
    "frame_height",
    "mip_count",
    "compression",
    "encoding",
]

MODEL_REPORT_COLUMNS = [
    "model_archive",
    "model_id",
    "model_status",
    "parse_error",
    "record_format",
    "limb_index",
    "limb_id",
    "parent_limb_id",
    "lod_index",
    "material_index",
    "texture_id",
    "material_animation_status",
    "anim_start",
    "anim_end",
    "cur_frame",
    "anim_speed",
    "animation_type",
    "playback_direction",
    "animation_timer",
]


def _case_insensitive_child(directory: Path, filename: str) -> Path | None:
    """Return a direct child by case-insensitive name without recursive guessing."""
    wanted = filename.casefold()
    try:
        return next(
            (child for child in directory.iterdir() if child.name.casefold() == wanted),
            None,
        )
    except OSError:
        return None


def _require_path(value: str | Path, description: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise U9AssetReportError(f"{description} not found: {path}")
    return path


def _safe_tier_name(stem: str) -> str:
    tier = stem.casefold()
    if tier.startswith("bitmap"):
        tier = tier[len("bitmap") :]
    tier = re.sub(r"[^a-z0-9]+", "_", tier).strip("_")
    return tier or "default"


def _discover_texture_sources(source: str | Path) -> list[_TextureSource]:
    path = _require_path(source, "texture source")
    if path.is_dir():
        sources: list[_TextureSource] = []
        for filename, tier, sdinfo_filename in KNOWN_TEXTURE_FILES:
            texture_path = _case_insensitive_child(path, filename)
            if texture_path is None:
                continue
            sources.append(
                _TextureSource(
                    tier=tier,
                    path=texture_path,
                    sdinfo_path=_case_insensitive_child(path, sdinfo_filename),
                )
            )
        if not sources:
            raise U9AssetReportError(
                f"no bitmapsh.flx, bitmap16.flx, or bitmapC.flx found in {path}"
            )
        return sources

    known = next(
        (item for item in KNOWN_TEXTURE_FILES if item[0] == path.name.casefold()),
        None,
    )
    tier = known[1] if known else _safe_tier_name(path.stem)
    sdinfo_path = (
        _case_insensitive_child(path.parent, known[2]) if known is not None else None
    )
    return [_TextureSource(tier=tier, path=path, sdinfo_path=sdinfo_path)]


def _discover_optional_file(
    directory: Path, explicit: str | Path | None, filename: str
) -> Path | None:
    if explicit is not None:
        return _require_path(explicit, filename)
    return _case_insensitive_child(directory, filename)


def _discover_model_archive(source: str | Path) -> tuple[Path, Path]:
    path = _require_path(source, "model source")
    if path.is_dir():
        model_path = _case_insensitive_child(path, "sappear.flx")
        if model_path is None:
            raise U9AssetReportError(f"sappear.flx not found in {path}")
        return model_path, path
    return path, path.parent


def _load_names(
    directory: Path,
    types_path: str | Path | None,
    typenames_path: str | Path | None,
) -> tuple[U9TypesDat | None, U9TypeNames | None, list[str]]:
    warnings: list[str] = []
    types_file = _discover_optional_file(directory, types_path, "TYPES.DAT")
    names_file = _discover_optional_file(directory, typenames_path, "TYPENAME.FLX")
    if types_file is None or names_file is None:
        if types_file is not None or names_file is not None:
            warnings.append(
                "model names require both TYPES.DAT and TYPENAME.FLX; "
                "the incomplete pair was ignored"
            )
        return None, None, warnings
    try:
        return (
            U9TypesDat.from_file(types_file),
            U9TypeNames.from_file(names_file),
            warnings,
        )
    except (OSError, U9TypesDatError, U9FlxArchiveError) as error:
        warnings.append(f"could not load model-name helpers: {error}")
        return None, None, warnings


def _material_is_animated(material: U9Material) -> bool:
    return material.anim_end > material.anim_start


def _material_range(material: U9Material) -> str:
    return f"{material.anim_start}-{material.anim_end}"


def _read_material_references(
    model_path: Path,
    *,
    model_id: int | None = None,
) -> tuple[list[_MaterialReference], list[dict[str, Any]]]:
    """Read material references plus model-level diagnostic rows."""
    try:
        archive = U9FlxArchive.from_file(model_path)
    except (OSError, U9FlxArchiveError) as error:
        raise U9AssetReportError(
            f"could not read model archive {model_path}: {error}"
        ) from error

    if model_id is not None:
        if not 0 <= model_id < archive.num_entries:
            raise U9AssetReportError(
                f"model ID {model_id} out of range (0..{archive.num_entries - 1})"
            )
        indices = [model_id]
    else:
        indices = archive.used_entry_indices()

    references: list[_MaterialReference] = []
    diagnostics: list[dict[str, Any]] = []
    for current_id in indices:
        entry = archive.get_entry(current_id)
        data = archive.read_entry(current_id)
        if not data:
            diagnostics.append(
                {
                    "model_archive": str(model_path),
                    "model_id": current_id,
                    "model_status": "empty",
                    "parse_error": "unused or unreadable FLX entry",
                    "entry_offset": entry.offset if entry else None,
                    "entry_length": entry.length if entry else 0,
                }
            )
            continue
        try:
            model = U9Model.parse(data, model_id=current_id)
        except U9ModelError as error:
            diagnostics.append(
                {
                    "model_archive": str(model_path),
                    "model_id": current_id,
                    "model_status": "parse-error",
                    "parse_error": str(error),
                    "entry_offset": entry.offset if entry else None,
                    "entry_length": entry.length if entry else len(data),
                }
            )
            continue

        material_count = 0
        for limb_index, limb in enumerate(model.limbs):
            for lod_index, lod in enumerate(limb.lods):
                if lod is None:
                    continue
                for material_index, material in enumerate(lod.materials):
                    material_count += 1
                    references.append(
                        _MaterialReference(
                            model_id=current_id,
                            record_format=model.record_format,
                            model_fields={
                                "entry_offset": entry.offset if entry else None,
                                "entry_length": entry.length if entry else len(data),
                                "model_limb_count": len(model.limbs),
                                "model_cylinder_base_center": model.cylinder_base_center,
                                "model_cylinder_base_height": model.cylinder_base_height,
                                "model_cylinder_base_radius": model.cylinder_base_radius,
                                "model_sphere_center": model.sphere_center,
                                "model_sphere_radius": model.sphere_radius,
                                "model_min_bounds": model.min_bounds,
                                "model_max_bounds": model.max_bounds,
                                "model_lod_thresholds": model.lod_thresholds,
                                "model_center_of_mass": model.center_of_mass,
                                "model_unknown_2c": model.unknown_2c,
                                "model_mass_or_volume": model.mass_or_volume,
                                "model_inertia_matrix": model.inertia_matrix,
                                "model_unknown_8c": model.unknown_8c,
                                "model_indexed_face_count": len(model.indexed_faces),
                                "model_alternate_header_length": len(
                                    model.alternate_header
                                ),
                                "model_trailing_data_length": len(model.trailing_data),
                            },
                            limb_index=limb_index,
                            limb_id=limb.limb_id,
                            parent_limb_id=limb.parent_id,
                            limb_fields={
                                "limb_is_root": limb.is_root,
                                "limb_scale": limb.scale,
                                "limb_position": limb.position,
                                "limb_rotation": limb.rotation,
                                "limb_lod_slot_count": len(limb.lods),
                            },
                            lod_index=lod_index,
                            material_index=material_index,
                            lod_fields={
                                "lod_vertex_count": len(lod.vertices),
                                "lod_triangle_count": len(lod.triangles),
                                "lod_material_count": len(lod.materials),
                                "lod_mount_vertex_count": len(lod.mount_vertices),
                                "lod_mount_triangle_count": len(lod.mount_triangles),
                                "lod_sphere_center": lod.sphere_center,
                                "lod_sphere_radius": lod.sphere_radius,
                                "lod_min_bounds": lod.min_bounds,
                                "lod_max_bounds": lod.max_bounds,
                                "lod_mesh_size": lod.mesh_size,
                                "lod_flags": f"0x{lod.flags:08x}",
                                "lod_unknown_08": f"0x{lod.unknown_08:08x}",
                                "lod_unknown_34": f"0x{lod.unknown_34:08x}",
                                "lod_unknown_38": f"0x{lod.unknown_38:08x}",
                                "lod_max_face_count": lod.max_face_count,
                                "lod_face_offset": lod.face_offset,
                                "lod_mount_face_offset": lod.mount_face_offset,
                                "lod_vertex_offset": lod.vertex_offset,
                                "lod_mount_vertex_offset": lod.mount_vertex_offset,
                                "lod_material_offset": lod.material_offset,
                                "lod_sorted_face_offsets": lod.sorted_face_offsets,
                                "lod_unknown_78": f"0x{lod.unknown_78:08x}",
                            },
                            material=material,
                        )
                    )
        if material_count == 0:
            diagnostics.append(
                {
                    "model_archive": str(model_path),
                    "model_id": current_id,
                    "model_status": "no-materials",
                    "parse_error": "",
                    "record_format": model.record_format,
                    "limb_count": len(model.limbs),
                    "entry_offset": entry.offset if entry else None,
                    "entry_length": entry.length if entry else len(data),
                }
            )
    return references, diagnostics


def _texture_animation_fields(
    frame_count: int, references: Iterable[_MaterialReference] | None
) -> dict[str, Any]:
    if references is None:
        if frame_count > 1:
            return {
                "animation_status": "multiframe-unresolved",
                "animation_evidence": "multiple stored frames; no sappear.flx material evidence",
            }
        return {
            "animation_status": "static",
            "animation_evidence": "one stored frame",
        }

    refs = list(references)
    animated = [ref for ref in refs if _material_is_animated(ref.material)]
    valid = [
        ref
        for ref in animated
        if 0 <= ref.material.anim_start <= ref.material.anim_end < frame_count
    ]
    invalid = [ref for ref in animated if ref not in valid]
    fields: dict[str, Any] = {
        "model_reference_count": len(refs),
        "animated_material_reference_count": len(animated),
        "referencing_model_ids": sorted({ref.model_id for ref in refs}),
        "animation_ranges": sorted({_material_range(ref.material) for ref in animated}),
    }
    if invalid:
        fields.update(
            animation_status="conflicting",
            animation_evidence="model material animation range exceeds this texture tier",
        )
    elif valid:
        fields.update(
            animation_status="confirmed",
            animation_evidence="valid changing frame range in sappear.flx material",
        )
    elif frame_count > 1:
        fields.update(
            animation_status="multiframe-unresolved",
            animation_evidence="multiple stored frames; no changing sappear.flx material range",
        )
    else:
        fields.update(
            animation_status="static",
            animation_evidence="one stored frame and no changing material range",
        )
    return fields


def _sdinfo_fields(record: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "sdinfo_width": record.width,
        "sdinfo_height": record.height,
        "sdinfo_max_width": record.max_width,
        "sdinfo_max_height": record.max_height,
        "sdinfo_frame_count": record.frame_count,
        "sdinfo_mip_levels": record.mip_levels,
        "sdinfo_log2_width": record.log2_width,
        "sdinfo_log2_height": record.log2_height,
        "sdinfo_flag": record.flag,
        "sdinfo_frame_flag": record.frame_flag,
        "sdinfo_format_selector": record.format_selector,
    }
    for index, value in enumerate(record.fields):
        fields[f"sdinfo_field_{index:02d}"] = f"0x{value:08x}"
    return fields


def _passes_texture_filter(row: dict[str, Any], only: str | None) -> bool:
    if only is None:
        return True
    status = row.get("animation_status")
    if only == "animated":
        return status in {"confirmed", "probable"}
    if only == "multiframe":
        return bool(row.get("is_multiframe"))
    if only == "static":
        return status == "static"
    if only == "unresolved":
        return status in {"multiframe-unresolved", "unknown"}
    if only == "errors":
        return row.get("entry_status") != "ok" or status == "conflicting"
    raise U9AssetReportError(
        "texture --only must be animated, multiframe, static, unresolved, or errors"
    )


def build_texture_frame_report(
    source: str | Path,
    *,
    entry_id: int | None = None,
    sappear_path: str | Path | None = None,
    types_path: str | Path | None = None,
    typenames_path: str | Path | None = None,
    only: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build one row per discovered texture tier, entry, and stored frame."""
    if only not in {None, "animated", "multiframe", "static", "unresolved", "errors"}:
        raise U9AssetReportError(
            "texture --only must be animated, multiframe, static, unresolved, or errors"
        )
    sources = _discover_texture_sources(source)
    helper_dir = sources[0].path.parent
    model_file = _discover_optional_file(helper_dir, sappear_path, "sappear.flx")
    warnings: list[str] = []

    reverse_refs: dict[int, list[_MaterialReference]] | None = None
    types: U9TypesDat | None = None
    typenames: U9TypeNames | None = None
    if model_file is not None:
        references, diagnostics = _read_material_references(model_file)
        reverse_refs = defaultdict(list)
        for reference in references:
            reverse_refs[reference.material.texture_id].append(reference)
        if diagnostics:
            parse_errors = sum(
                row["model_status"] == "parse-error" for row in diagnostics
            )
            if parse_errors:
                warnings.append(
                    f"{parse_errors} model entries could not be parsed for animation evidence"
                )
        types, typenames, name_warnings = _load_names(
            model_file.parent, types_path, typenames_path
        )
        warnings.extend(name_warnings)

    rows: list[dict[str, Any]] = []
    for texture_source in sources:
        try:
            archive = U9FlxArchive.from_file(texture_source.path)
        except (OSError, U9FlxArchiveError) as error:
            raise U9AssetReportError(
                f"could not read texture archive {texture_source.path}: {error}"
            ) from error
        sdinfo: U9SdInfo | None = None
        if texture_source.sdinfo_path is not None:
            try:
                sdinfo = U9SdInfo.from_file(texture_source.sdinfo_path)
            except (OSError, U9SdInfoError) as error:
                warnings.append(
                    f"could not load {texture_source.sdinfo_path.name}: {error}"
                )

        if entry_id is not None:
            if not 0 <= entry_id < archive.num_entries:
                raise U9AssetReportError(
                    f"entry ID {entry_id} out of range for {texture_source.path.name} "
                    f"(0..{archive.num_entries - 1})"
                )
            indices = [entry_id]
        else:
            indices = archive.used_entry_indices()

        for current_id in indices:
            entry = archive.get_entry(current_id)
            common: dict[str, Any] = {
                "texture_tier": texture_source.tier,
                "texture_archive": str(texture_source.path),
                "entry_id": current_id,
                "entry_offset": entry.offset if entry else None,
                "entry_length": entry.length if entry else 0,
            }
            data = archive.read_entry(current_id)
            if not data:
                diagnostic = {
                    **common,
                    "entry_status": "empty",
                    "parse_error": "unused or unreadable FLX entry",
                    "animation_status": "unknown",
                    "animation_evidence": "texture entry could not be read",
                }
                if _passes_texture_filter(diagnostic, only):
                    rows.append(diagnostic)
                continue
            try:
                texture_set = parse_texture_set(data)
            except U9TextureError as error:
                diagnostic = {
                    **common,
                    "entry_status": "parse-error",
                    "parse_error": str(error),
                    "animation_status": "unknown",
                    "animation_evidence": "texture entry could not be parsed",
                }
                if _passes_texture_filter(diagnostic, only):
                    rows.append(diagnostic)
                continue

            refs = None if reverse_refs is None else reverse_refs.get(current_id, [])
            set_fields: dict[str, Any] = {
                **common,
                "entry_status": "ok",
                "parse_error": "",
                "set_width": texture_set.frame_width,
                "set_height": texture_set.frame_height,
                "mip_count": texture_set.mip_count,
                "compression": texture_set.compression,
                "frame_count": texture_set.frame_count,
                "is_multiframe": texture_set.frame_count > 1,
                "set_header_0c": f"0x{texture_set.unknown:08x}",
                **_texture_animation_fields(texture_set.frame_count, refs),
            }
            sd_record = None
            if sdinfo is not None:
                try:
                    sd_record = sdinfo.record(current_id)
                except U9SdInfoError as error:
                    set_fields["sdinfo_error"] = str(error)
                if sd_record is not None:
                    set_fields.update(_sdinfo_fields(sd_record))
                    set_fields["sdinfo_matches_frame_count"] = (
                        sd_record.frame_count == texture_set.frame_count
                    )
                    set_fields["sdinfo_matches_mip_count"] = (
                        sd_record.mip_levels == texture_set.mip_count
                    )

            if not texture_set.frames:
                diagnostic = {
                    **set_fields,
                    "entry_status": "no-frames",
                    "parse_error": "texture set declares zero frames",
                }
                if _passes_texture_filter(diagnostic, only):
                    rows.append(diagnostic)
                continue

            for frame in texture_set.frames:
                selector = sd_record.format_selector if sd_record is not None else None
                try:
                    encoding = frame_encoding(data, frame.index, selector=selector)
                    encoding_error = ""
                except U9TextureWriteError as error:
                    encoding = "unknown"
                    encoding_error = str(error)
                row = {
                    **set_fields,
                    "frame_index": frame.index,
                    "frame_offset": frame.offset,
                    "frame_length": frame.length,
                    "frame_width": frame.width,
                    "frame_height": frame.height,
                    "frame_flags": f"0x{frame.flags:04x}",
                    "frame_unknown_word": f"0x{frame.unknown_word:04x}",
                    "frame_unknown_3": f"0x{frame.unknown3:08x}",
                    "frame_unknown_4": f"0x{frame.unknown4:08x}",
                    "row_offset_count": len(frame.row_offsets),
                    "pixel_data_offset": frame.pixel_data_offset,
                    "is_transparent": frame.is_transparent,
                    "encoding": encoding,
                }
                if encoding_error:
                    row["encoding_error"] = encoding_error
                if refs and types is not None and typenames is not None:
                    model_names = {
                        name
                        for reference in refs
                        for name in names_for_model(
                            reference.model_id, types, typenames
                        )
                    }
                    row["referencing_model_names"] = sorted(model_names)
                if _passes_texture_filter(row, only):
                    rows.append(row)

    rows.sort(
        key=lambda row: (
            str(row.get("texture_tier", "")),
            int(row.get("entry_id", -1)),
            int(row.get("frame_index", -1)),
        )
    )
    return rows, warnings


def _base_model_row(
    model_path: Path,
    reference: _MaterialReference,
) -> dict[str, Any]:
    material = reference.material
    return {
        "model_archive": str(model_path),
        "model_id": reference.model_id,
        "model_status": "ok",
        "parse_error": "",
        "record_format": reference.record_format,
        **reference.model_fields,
        "limb_index": reference.limb_index,
        "limb_id": reference.limb_id,
        "parent_limb_id": reference.parent_limb_id,
        **reference.limb_fields,
        "lod_index": reference.lod_index,
        "material_index": reference.material_index,
        **reference.lod_fields,
        "texture_id": material.texture_id,
        "is_invisible": material.is_invisible,
        "first_face": material.first_face,
        "face_count": material.face_count,
        "flags_02": f"0x{material.flags_02:04x}",
        "render_flags": f"0x{material.render_flags:04x}",
        "flags_06": f"0x{material.flags_06:04x}",
        "is_chromakey": material.is_chromakey,
        "is_sorted": material.is_sorted,
        "is_additive": material.is_additive,
        "clamps_s": material.clamps_s,
        "clamps_t": material.clamps_t,
        "default_alpha": material.default_alpha,
        "modified_alpha": material.modified_alpha,
        "anim_start": material.anim_start,
        "anim_end": material.anim_end,
        "cur_frame": material.cur_frame,
        "anim_speed": material.anim_speed,
        "animation_type": material.animation_type,
        "playback_direction": material.playback_direction,
        "animation_timer": material.animation_timer,
        "has_changing_animation_range": _material_is_animated(material),
    }


def _texture_metadata_for_ids(
    texture_source: _TextureSource, texture_ids: set[int]
) -> tuple[dict[int, dict[str, Any]], list[str]]:
    warnings: list[str] = []
    try:
        archive = U9FlxArchive.from_file(texture_source.path)
    except (OSError, U9FlxArchiveError) as error:
        raise U9AssetReportError(
            f"could not read texture archive {texture_source.path}: {error}"
        ) from error
    sdinfo: U9SdInfo | None = None
    if texture_source.sdinfo_path is not None:
        try:
            sdinfo = U9SdInfo.from_file(texture_source.sdinfo_path)
        except (OSError, U9SdInfoError) as error:
            warnings.append(
                f"could not load {texture_source.sdinfo_path.name}: {error}"
            )

    by_id: dict[int, dict[str, Any]] = {}
    for texture_id in sorted(texture_ids):
        if texture_id == INVISIBLE_TEXTURE_ID:
            continue
        prefix = f"texture_{texture_source.tier}_"
        metadata: dict[str, Any] = {
            prefix + "archive": str(texture_source.path),
            prefix + "present": False,
        }
        if not 0 <= texture_id < archive.num_entries:
            metadata[prefix + "error"] = (
                f"texture ID outside archive range 0..{archive.num_entries - 1}"
            )
            by_id[texture_id] = metadata
            continue
        data = archive.read_entry(texture_id)
        if not data:
            metadata[prefix + "error"] = "unused or unreadable texture entry"
            by_id[texture_id] = metadata
            continue
        try:
            texture_set = parse_texture_set(data)
        except U9TextureError as error:
            metadata[prefix + "error"] = str(error)
            by_id[texture_id] = metadata
            continue
        metadata.update(
            {
                prefix + "present": True,
                prefix + "frame_count": texture_set.frame_count,
                prefix + "mip_count": texture_set.mip_count,
                prefix + "compression": texture_set.compression,
                prefix + "set_width": texture_set.frame_width,
                prefix + "set_height": texture_set.frame_height,
                prefix + "set_header_0c": f"0x{texture_set.unknown:08x}",
                prefix + "frame_dimensions": [
                    f"{frame.width}x{frame.height}" for frame in texture_set.frames
                ],
                prefix + "transparent_frame_count": sum(
                    frame.is_transparent for frame in texture_set.frames
                ),
            }
        )
        encodings: set[str] = set()
        selector = None
        if sdinfo is not None:
            try:
                record = sdinfo.record(texture_id)
            except U9SdInfoError as error:
                metadata[prefix + "sdinfo_error"] = str(error)
                record = None
            if record is not None:
                selector = record.format_selector
                metadata[prefix + "sdinfo_format_selector"] = selector
                metadata[prefix + "sdinfo_frame_count"] = record.frame_count
        for frame in texture_set.frames:
            try:
                encodings.add(frame_encoding(data, frame.index, selector=selector))
            except U9TextureWriteError as error:
                metadata[prefix + "encoding_error"] = str(error)
        if encodings:
            metadata[prefix + "encodings"] = sorted(encodings)
        by_id[texture_id] = metadata
    return by_id, warnings


def _passes_model_filter(row: dict[str, Any], only: str | None) -> bool:
    if only is None:
        return True
    status = row.get("material_animation_status")
    if only == "animated":
        return bool(row.get("has_changing_animation_range"))
    if only == "textured":
        return row.get("texture_id") not in {None, INVISIBLE_TEXTURE_ID}
    if only == "unresolved":
        return status in {
            "unverified",
            "static-unverified",
            "invalid-range",
            "missing-texture",
        }
    if only == "errors":
        return row.get("model_status") == "parse-error" or status in {
            "invalid-range",
            "missing-texture",
        }
    raise U9AssetReportError(
        "model --only must be animated, textured, unresolved, or errors"
    )


def build_model_material_report(
    source: str | Path,
    *,
    model_id: int | None = None,
    textures_path: str | Path | None = None,
    types_path: str | Path | None = None,
    typenames_path: str | Path | None = None,
    only: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build one row per model limb/LOD material and join discovered textures."""
    if only not in {None, "animated", "textured", "unresolved", "errors"}:
        raise U9AssetReportError(
            "model --only must be animated, textured, unresolved, or errors"
        )
    model_path, helper_dir = _discover_model_archive(source)
    references, diagnostics = _read_material_references(model_path, model_id=model_id)
    types, typenames, warnings = _load_names(helper_dir, types_path, typenames_path)

    rows = [_base_model_row(model_path, reference) for reference in references]
    row_references = list(zip(rows, references))
    if types is not None and typenames is not None:
        for row, reference in row_references:
            type_ids = types.type_ids_for_model(reference.model_id)
            row["type_ids"] = type_ids
            row["model_names"] = names_for_model(reference.model_id, types, typenames)
        for row in diagnostics:
            current_id = int(row["model_id"])
            row["type_ids"] = types.type_ids_for_model(current_id)
            row["model_names"] = names_for_model(current_id, types, typenames)

    texture_source_value: str | Path = textures_path or helper_dir
    try:
        texture_sources = _discover_texture_sources(texture_source_value)
    except U9AssetReportError:
        if textures_path is not None:
            raise
        texture_sources = []
        warnings.append(
            "no bitmap texture archives discovered; animation ranges are unverified"
        )

    texture_ids = {
        reference.material.texture_id
        for reference in references
        if reference.material.texture_id != INVISIBLE_TEXTURE_ID
    }
    tier_metadata: list[tuple[str, dict[int, dict[str, Any]]]] = []
    for texture_source in texture_sources:
        metadata, tier_warnings = _texture_metadata_for_ids(texture_source, texture_ids)
        warnings.extend(tier_warnings)
        tier_metadata.append((texture_source.tier, metadata))

    for row, reference in row_references:
        material = reference.material
        if material.is_invisible:
            row["material_animation_status"] = "invisible"
            row["animation_evidence"] = "texture_id is 0xffff"
            continue
        present_counts: list[int] = []
        tier_errors = False
        for _tier, metadata_by_id in tier_metadata:
            tier_fields = metadata_by_id.get(material.texture_id, {})
            row.update(tier_fields)
            present_key = next(
                (key for key in tier_fields if key.endswith("_present")), None
            )
            frame_key = next(
                (key for key in tier_fields if key.endswith("_frame_count")), None
            )
            error_key = next(
                (key for key in tier_fields if key.endswith("_error")), None
            )
            if present_key and tier_fields.get(present_key) and frame_key:
                present_counts.append(int(tier_fields[frame_key]))
            if error_key and tier_fields.get(error_key):
                tier_errors = True

        if not texture_sources:
            row["material_animation_status"] = (
                "unverified" if _material_is_animated(material) else "static-unverified"
            )
            row["animation_evidence"] = "no texture archive available"
        elif not present_counts:
            row["material_animation_status"] = "missing-texture"
            row["animation_evidence"] = (
                "texture absent or unreadable in discovered tiers"
            )
        elif _material_is_animated(material):
            valid = all(material.anim_end < count for count in present_counts)
            if valid and not tier_errors:
                row["material_animation_status"] = "confirmed"
                row["animation_evidence"] = (
                    "changing range is valid in every readable tier"
                )
            else:
                row["material_animation_status"] = "invalid-range"
                row["animation_evidence"] = (
                    "changing range exceeds or conflicts with a tier"
                )
        else:
            row["material_animation_status"] = "static"
            row["animation_evidence"] = (
                "material does not declare a changing frame range"
            )
        row["texture_tier_frame_counts"] = present_counts
        row["texture_tier_frame_counts_match"] = len(set(present_counts)) <= 1

    rows.extend(diagnostics)
    rows = [row for row in rows if _passes_model_filter(row, only)]
    rows.sort(
        key=lambda row: (
            int(row.get("model_id", -1)),
            int(row.get("limb_index", -1)),
            int(row.get("lod_index", -1)),
            int(row.get("material_index", -1)),
        )
    )
    return rows, warnings


def _dynamic_columns(
    rows: Iterable[dict[str, Any]], preferred: Iterable[str]
) -> list[str]:
    """Stable leading columns followed by first-seen optional helper columns."""
    row_list = list(rows)
    discovered: list[str] = []
    seen: set[str] = set()
    for row in row_list:
        for key in row:
            if key not in seen:
                seen.add(key)
                discovered.append(key)
    leading = [column for column in preferred if column in seen or not row_list]
    return leading + [column for column in discovered if column not in leading]


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return value


def write_dynamic_report(
    rows: list[dict[str, Any]],
    output: str | Path,
    fmt: str,
    *,
    preferred_columns: Iterable[str],
) -> Path:
    """Write CSV with unioned columns, or the same row dictionaries as JSON."""
    normalized_format = fmt.casefold()
    if normalized_format not in {"csv", "json"}:
        raise U9AssetReportError("format must be csv or json")
    destination = Path(output).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if normalized_format == "json":
            destination.write_text(
                json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        else:
            columns = _dynamic_columns(rows, preferred_columns)
            with destination.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
                writer.writeheader()
                writer.writerows(
                    {key: _csv_value(value) for key, value in row.items()}
                    for row in rows
                )
    except OSError as error:
        raise U9AssetReportError(f"could not write {destination}: {error}") from error
    return destination
