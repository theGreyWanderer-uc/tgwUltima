"""``titan u9 highway-*`` / ``spaces-*`` / ``treedat-*`` / ``areas-*`` — navigation, volume and gameplay zone commands."""

from __future__ import annotations

__all__ = [
    "highway_info_cmd",
    "highway_points_cmd",
    "highway_routes_cmd",
    "spaces_info_cmd",
    "spaces_show_cmd",
    "spaces_csv_cmd",
    "treedat_info_cmd",
    "treedat_show_cmd",
    "treedat_csv_cmd",
    "areas_info_cmd",
    "areas_show_cmd",
    "areas_csv_cmd",
]

import csv
import os
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Optional

import typer

from titan.u9.gameplay_zones import U9Areas, U9AreasError, U9GameplayZone
from titan.u9.highway import U9Highway, U9HighwayError
from titan.u9.space_tree import U9VolumeLookupCache, U9VolumeLookupError
from titan.u9.spaces import U9Spaces, U9SpacesError


def _load_highway(filepath: str) -> Optional[U9Highway]:
    """Open static/highway.dat, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Highway.from_file(filepath)
    except U9HighwayError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return None


def cmd_highway_info(args: SimpleNamespace) -> int:
    """Summarize the U9 NPC navigation graph: points, routes, connectivity."""
    highway = _load_highway(args.file)
    if highway is None:
        return 1

    adjacency = highway.neighbors()
    edges = sum(len(v) for v in adjacency.values()) // 2
    unknown = highway.unknown_path_nodes()
    xs = [p.x for p in highway.points]
    ys = [p.y for p in highway.points]
    links = [p.link for p in highway.points]

    print(f"{args.file} -- U9 highway navigation graph")
    print(
        f"  Points          : {len(highway.points)} of {highway.declared_point_count} declared"
    )
    print(
        f"  Routes          : {len(highway.routes)} of {highway.declared_route_count} declared"
    )
    print(
        f"  Route block     : {highway.route_bytes} bytes, {highway.route_bytes_consumed} consumed"
    )
    if links:
        print(f"  Links           : {min(links)}..{max(links)}")
        print(f"  World extent    : x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)}")
    print(
        f"  Connectivity    : {len(adjacency)} point(s) appear in a route, {edges} edge(s)"
    )
    if highway.routes:
        longest = max(highway.routes, key=lambda r: r.path_length)
        print(
            f"  Longest route   : {longest.start_link} -> {longest.last_link}, "
            f"{longest.path_length} nodes, distance {longest.route_distance}"
        )
    if unknown:
        print(
            f"  WARNING: {len(unknown)} route node(s) have no declared point: {unknown[:10]}"
        )
    if not highway.is_complete:
        print(
            "  WARNING: file did not parse completely -- truncated or not a highway.dat"
        )
    print(
        "  Points are keyed by their marker's link; the world markers are entities of"
    )
    print("  type 1134 -- see 'titan u9 nonfixed-entities'.")
    return 0


def cmd_highway_points(args: SimpleNamespace) -> int:
    """List highway navigation points and their absolute world positions."""
    highway = _load_highway(args.file)
    if highway is None:
        return 1

    adjacency = highway.neighbors()
    if args.id is not None:
        point = highway.point(args.id)
        if point is None:
            print(f"No highway point with link {args.id}.")
            return 0
        points = [point]
    else:
        points = list(highway.points)

    shown = points[: args.limit] if args.limit else points
    print(f"{args.file} -- {len(points)} point(s)")
    print(f"{'Link':>10}  {'X':>8}  {'Y':>8}  {'Edges':>5}  Routes")
    print("-" * 52)
    for p in shown:
        edges = len(adjacency.get(p.link, ()))
        through = len(highway.routes_through(p.link))
        print(f"{p.link:>10}  {p.x:>8}  {p.y:>8}  {edges:>5}  {through}")
    if args.limit and len(points) > args.limit:
        print(f"... ({len(points) - args.limit} more; raise --limit to see more)")
    return 0


def cmd_highway_routes(args: SimpleNamespace) -> int:
    """List precomputed routes through the highway graph."""
    highway = _load_highway(args.file)
    if highway is None:
        return 1

    routes = (
        highway.routes_through(args.id) if args.id is not None else list(highway.routes)
    )
    if args.id is not None and not routes:
        print(f"No route visits link {args.id}.")
        return 0

    shown = routes[: args.limit] if args.limit else routes
    print(f"{args.file} -- {len(routes)} route(s)")
    for r in shown:
        print(
            f"  {r.start_link} -> {r.last_link}  "
            f"nodes {r.path_length}, hops {r.hops}, distance {r.route_distance}"
        )
        if args.paths:
            print(f"      {' -> '.join(str(n) for n in r.path)}")
    if args.limit and len(routes) > args.limit:
        print(f"... ({len(routes) - args.limit} more; raise --limit to see more)")
    return 0


def _load_spaces(filepath: str) -> Optional[U9Spaces]:
    """Open static/spaces.flx, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Spaces.from_file(filepath)
    except U9SpacesError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def cmd_spaces_info(args: SimpleNamespace) -> int:
    """Summarize enclosed spaces, boundary planes, and visibility portals."""
    spaces = _load_spaces(args.file)
    if spaces is None:
        return 1
    records = spaces.spaces()
    plane_count = sum(len(space.boundaries) for space in records)
    portal_count = sum(space.portal_count for space in records)
    rebuilt = sum(not space.stored_space_number_matches_runtime for space in records)
    reset_flags = sum(
        opening.stored_flags != 0
        for space in records
        for boundary in space.boundaries
        for opening in boundary.openings
    )
    print(
        f"{args.file} -- {len(records)} enclosed space(s) of {spaces.num_entries} slots"
    )
    print(f"  boundary planes        : {plane_count}")
    print(f"  visibility portals     : {portal_count}")
    print(f"  runtime-rebuilt IDs    : {rebuilt}")
    print(f"  nonzero reset flag cells: {reset_flags}")
    missing = spaces.missing_visibility_target_ids()
    print(
        "  unresolved space links: "
        + (", ".join(str(value) for value in missing) if missing else "none")
    )
    return 0


def cmd_spaces_show(args: SimpleNamespace) -> int:
    """Show one enclosed space without interpreting forensic-only cells."""
    spaces = _load_spaces(args.file)
    if spaces is None:
        return 1
    space = spaces.space(args.id)
    if space is None:
        print(f"Space {args.id} is an unused slot.")
        return 0

    template = (
        "none" if space.sound_template_id is None else str(space.sound_template_id)
    )
    environment = (
        "none"
        if space.acoustic_environment_id is None
        else str(space.acoustic_environment_id)
    )
    print(f"{args.file} -- space {space.space_id}: {space.name!r}")
    print(f"  map={space.world_map_id} sorting_priority={space.draw_order_priority}")
    print(
        f"  visible_space={space.visibility_target_id} "
        f"hide_outside={space.hide_outside}"
    )
    print(
        f"  sound_template={template} acoustic_environment={environment} "
        f"audio_raw={space.audio_code:#010x}"
    )
    print(
        f"  stored_space_number={space.stored_space_number} "
        f"runtime_space_id={space.runtime_space_id} "
        f"status={space.stored_space_number_status}"
    )
    print(
        f"  planes={len(space.boundaries)} portals={space.portal_count} "
        f"stored_flags={space.stored_flags:#06x}"
    )
    for plane_index, boundary in enumerate(space.boundaries):
        print(
            f"  plane {plane_index}: center={boundary.reference_point} "
            f"normal={boundary.normal} w={boundary.plane_w} "
            f"portals={len(boundary.openings)}"
        )
        for portal_index, opening in enumerate(boundary.openings):
            range_text = (
                "runtime maximum"
                if opening.uses_runtime_maximum_range
                else str(opening.range_limit)
            )
            print(
                f"    portal {portal_index}: target={opening.visibility_target_id} "
                f"range={range_text} stored_flags={opening.stored_flags:#010x} "
                f"status={opening.stored_flags_status}"
            )
    return 0


def cmd_spaces_csv(args: SimpleNamespace) -> int:
    """Export normalized space, plane, and portal tables with raw records."""
    spaces = _load_spaces(args.file)
    if spaces is None:
        return 1

    output = Path(args.output or "spaces_csv")
    try:
        output.mkdir(parents=True, exist_ok=True)
        space_path = output / "u9_spaces.csv"
        plane_path = output / "u9_space_planes.csv"
        portal_path = output / "u9_space_portals.csv"

        with space_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "space_id",
                    "name",
                    "world_map_id",
                    "draw_order_priority",
                    "visibility_target_id",
                    "boundary_plane_count",
                    "portal_count",
                    "hide_outside",
                    "stored_flags",
                    "unclassified_flag_bits",
                    "audio_code",
                    "has_sound_template",
                    "sound_template_id",
                    "has_acoustic_environment",
                    "acoustic_environment_id",
                    "unclassified_audio_bits",
                    "stored_space_number",
                    "runtime_space_id",
                    "stored_space_number_status",
                    "header_reserved",
                    "boundary_head_sentinel",
                    "name_field_hex",
                    "raw_hex",
                ]
            )
            for space in spaces.spaces():
                writer.writerow(
                    [
                        space.space_id,
                        space.name,
                        space.world_map_id,
                        space.draw_order_priority,
                        space.visibility_target_id,
                        len(space.boundaries),
                        space.portal_count,
                        space.hide_outside,
                        f"0x{space.stored_flags:04x}",
                        f"0x{space.unclassified_flag_bits:04x}",
                        f"0x{space.audio_code:08x}",
                        space.has_sound_template,
                        ""
                        if space.sound_template_id is None
                        else space.sound_template_id,
                        space.has_acoustic_environment,
                        ""
                        if space.acoustic_environment_id is None
                        else space.acoustic_environment_id,
                        f"0x{space.unclassified_audio_bits:08x}",
                        space.stored_space_number,
                        space.runtime_space_id,
                        space.stored_space_number_status,
                        space.header_reserved,
                        f"0x{space.boundary_head_sentinel:08x}",
                        f"0x{space.name_field.hex()}",
                        f"0x{space.raw_data.hex()}",
                    ]
                )

        with plane_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "space_id",
                    "plane_index",
                    "entry_offset",
                    "reference_x",
                    "reference_y",
                    "reference_z",
                    "normal_x",
                    "normal_y",
                    "normal_z",
                    "plane_w",
                    "portal_count",
                    "next_plane_sentinel",
                    "portal_head_sentinel",
                    "plane_reserved",
                    "raw_hex",
                ]
            )
            for space in spaces.spaces():
                for plane_index, boundary in enumerate(space.boundaries):
                    writer.writerow(
                        [
                            space.space_id,
                            plane_index,
                            boundary.entry_offset,
                            *boundary.reference_point,
                            *boundary.normal,
                            boundary.plane_w,
                            len(boundary.openings),
                            f"0x{boundary.next_plane_sentinel:08x}",
                            f"0x{boundary.portal_head_sentinel:08x}",
                            boundary.plane_reserved,
                            f"0x{boundary.raw_data.hex()}",
                        ]
                    )

        corner_columns = [
            f"corner_{corner}_{axis}" for corner in range(4) for axis in ("x", "y", "z")
        ]
        with portal_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "space_id",
                    "plane_index",
                    "portal_index",
                    "entry_offset",
                    *corner_columns,
                    "visibility_target_id",
                    "range_limit",
                    "uses_runtime_maximum_range",
                    "reserved_link",
                    "stored_flags",
                    "stored_blocked",
                    "stored_disabled",
                    "unclassified_flag_bits",
                    "runtime_initial_flags",
                    "stored_flags_status",
                    "next_portal_sentinel",
                    "raw_hex",
                ]
            )
            for space in spaces.spaces():
                for plane_index, boundary in enumerate(space.boundaries):
                    for portal_index, opening in enumerate(boundary.openings):
                        writer.writerow(
                            [
                                space.space_id,
                                plane_index,
                                portal_index,
                                opening.entry_offset,
                                *(
                                    value
                                    for corner in opening.corners
                                    for value in corner
                                ),
                                opening.visibility_target_id,
                                opening.range_limit,
                                opening.uses_runtime_maximum_range,
                                opening.reserved_link,
                                f"0x{opening.stored_flags:08x}",
                                opening.stored_blocked,
                                opening.stored_disabled,
                                f"0x{opening.unclassified_flag_bits:08x}",
                                f"0x{opening.runtime_initial_flags:08x}",
                                opening.stored_flags_status,
                                f"0x{opening.next_portal_sentinel:08x}",
                                f"0x{opening.raw_data.hex()}",
                            ]
                        )
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {len(spaces.spaces())} enclosed spaces -> {space_path}")
    print(
        f"Wrote {sum(len(space.boundaries) for space in spaces.spaces())} "
        f"boundary planes -> {plane_path}"
    )
    print(
        f"Wrote {sum(space.portal_count for space in spaces.spaces())} "
        f"visibility portals -> {portal_path}"
    )
    return 0


def _load_volume_lookup_cache(filepath: str) -> Optional[U9VolumeLookupCache]:
    """Open static/treedat.flx, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9VolumeLookupCache.from_file(filepath)
    except U9VolumeLookupError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def cmd_treedat_info(args: SimpleNamespace) -> int:
    """Summarize map entries and partition nodes in treedat.flx."""
    cache = _load_volume_lookup_cache(args.file)
    if cache is None:
        return 1
    maps = cache.map_indices()
    versions = Counter(map_index.format_version for map_index in maps)
    partition_count = sum(len(map_index.partitions) for map_index in maps)
    memberships = sum(map_index.leaf_membership_count for map_index in maps)
    duplicates = sum(map_index.duplicated_leaf_memberships for map_index in maps)
    invalid = cache.structurally_invalid_map_ids()
    print(f"{args.file} -- {len(maps)} cached map(s) of {cache.num_entries} slots")
    print(
        "  format versions          : "
        + ", ".join(f"{version}={count}" for version, count in sorted(versions.items()))
    )
    print(f"  empty map caches         : {sum(item.is_empty for item in maps)}")
    print(f"  partition nodes          : {partition_count}")
    print(f"  leaf memberships         : {memberships}")
    print(f"  duplicated memberships  : {duplicates}")
    print(
        "  structurally invalid maps: "
        + (", ".join(str(map_id) for map_id in invalid) if invalid else "none")
    )
    if args.spaces:
        spaces = _load_spaces(args.spaces)
        if spaces is None:
            return 1
        rebuild = cache.maps_requiring_rebuild(spaces)
        print(
            "  maps requiring rebuild   : "
            + (", ".join(str(map_id) for map_id in rebuild) if rebuild else "none")
        )
    return 0


def cmd_treedat_show(args: SimpleNamespace) -> int:
    """Show one map's cached volume list and partition table."""
    cache = _load_volume_lookup_cache(args.file)
    if cache is None:
        return 1
    map_index = cache.map_index(args.id)
    if map_index is None:
        print(f"Map {args.id} has no stored cache entry.")
        return 0

    warnings = map_index.structural_warnings()
    print(f"{args.file} -- cached map {map_index.map_id}")
    print(
        f"  version={map_index.format_version} volumes={len(map_index.volume_ids)} "
        f"partitions={len(map_index.partitions)}"
    )
    print(
        "  volume IDs: "
        + (", ".join(str(value) for value in map_index.volume_ids) or "none")
    )
    print(
        f"  leaf memberships={map_index.leaf_membership_count} "
        f"duplicates={map_index.duplicated_leaf_memberships}"
    )
    print("  warnings: " + (", ".join(warnings) if warnings else "none"))
    for node in map_index.partitions:
        kind = "leaf" if node.is_leaf else "branch"
        members = ",".join(str(value) for value in node.local_volume_ids) or "-"
        print(
            f"  node {node.node_index:>3} {kind:<6} "
            f"front={node.front_child_index:>3} back={node.back_child_index:>3} "
            f"subtree={node.subtree_volume_count:>3} local=[{members}] "
            f"equation={(*node.partition_normal, node.partition_w)}"
        )
    return 0


def cmd_treedat_csv(args: SimpleNamespace) -> int:
    """Export map, partition, and leaf-membership cache tables to CSV."""
    cache = _load_volume_lookup_cache(args.file)
    if cache is None:
        return 1
    spaces = None
    if args.spaces:
        spaces = _load_spaces(args.spaces)
        if spaces is None:
            return 1

    expected_by_map: dict[int, tuple[int, ...]] = {}
    volume_world_map: dict[int, int] = {}
    if spaces is not None:
        pending: dict[int, list[int]] = {}
        for volume in spaces.spaces():
            pending.setdefault(volume.world_map_id, []).append(volume.space_id)
            volume_world_map[volume.space_id] = volume.world_map_id
        expected_by_map = {
            map_id: tuple(volume_ids) for map_id, volume_ids in pending.items()
        }
    rebuild = set(cache.maps_requiring_rebuild(spaces)) if spaces is not None else set()
    exported_map_ids = sorted(set(cache.used_map_ids) | set(expected_by_map))

    output = Path(args.output or "treedat_csv")
    try:
        output.mkdir(parents=True, exist_ok=True)
        map_path = output / "u9_treedat_maps.csv"
        node_path = output / "u9_treedat_nodes.csv"
        membership_path = output / "u9_treedat_node_volumes.csv"

        with map_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "map_id",
                    "format_version",
                    "declared_volume_count",
                    "volume_ids",
                    "declared_partition_count",
                    "partition_count",
                    "leaf_membership_count",
                    "duplicated_leaf_memberships",
                    "root_subtree_volume_count",
                    "structural_status",
                    "warnings",
                    "spaces_expected_volume_ids",
                    "spaces_join_status",
                    "runtime_rebuild_required",
                    "raw_hex",
                ]
            )
            for map_id in exported_map_ids:
                map_index = cache.map_index(map_id)
                expected = None if spaces is None else expected_by_map.get(map_id, ())
                if map_index is None:
                    writer.writerow(
                        [
                            map_id,
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "absent",
                            "",
                            ""
                            if expected is None
                            else ";".join(str(value) for value in expected),
                            "missing_cache",
                            map_id in rebuild,
                            "",
                        ]
                    )
                    continue
                warnings = map_index.structural_warnings()
                if spaces is None:
                    join_status = "not_checked"
                elif expected == map_index.volume_ids:
                    join_status = "matches_spaces"
                else:
                    join_status = "differs_from_spaces"
                writer.writerow(
                    [
                        map_index.map_id,
                        map_index.format_version,
                        map_index.declared_volume_count,
                        ";".join(str(value) for value in map_index.volume_ids),
                        map_index.declared_partition_count,
                        len(map_index.partitions),
                        map_index.leaf_membership_count,
                        map_index.duplicated_leaf_memberships,
                        ""
                        if map_index.root_subtree_volume_count is None
                        else map_index.root_subtree_volume_count,
                        "ok" if not warnings else "warning",
                        ";".join(warnings),
                        ""
                        if expected is None
                        else ";".join(str(value) for value in expected),
                        join_status,
                        map_id in rebuild,
                        f"0x{map_index.raw_data.hex()}",
                    ]
                )

        with node_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "map_id",
                    "node_index",
                    "entry_offset",
                    "node_kind",
                    "front_child_index",
                    "back_child_index",
                    "has_complete_child_pair",
                    "local_volume_count",
                    "local_volume_ids",
                    "partition_normal_x",
                    "partition_normal_y",
                    "partition_normal_z",
                    "partition_w",
                    "subtree_volume_count",
                    "raw_hex",
                ]
            )
            for map_index in cache.map_indices():
                for node in map_index.partitions:
                    writer.writerow(
                        [
                            map_index.map_id,
                            node.node_index,
                            node.entry_offset,
                            "leaf" if node.is_leaf else "branch",
                            node.front_child_index,
                            node.back_child_index,
                            node.has_complete_child_pair,
                            len(node.local_volume_ids),
                            ";".join(str(value) for value in node.local_volume_ids),
                            *node.partition_normal,
                            node.partition_w,
                            node.subtree_volume_count,
                            f"0x{node.raw_data.hex()}",
                        ]
                    )

        with membership_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "map_id",
                    "node_index",
                    "membership_index",
                    "volume_id",
                    "in_map_volume_list",
                    "spaces_world_map_id",
                    "spaces_map_match",
                ]
            )
            for map_index in cache.map_indices():
                map_volume_ids = set(map_index.volume_ids)
                for node in map_index.partitions:
                    for membership_index, volume_id in enumerate(node.local_volume_ids):
                        world_map_id = volume_world_map.get(volume_id)
                        writer.writerow(
                            [
                                map_index.map_id,
                                node.node_index,
                                membership_index,
                                volume_id,
                                volume_id in map_volume_ids,
                                "" if world_map_id is None else world_map_id,
                                ""
                                if spaces is None
                                else world_map_id == map_index.map_id,
                            ]
                        )
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        f"Wrote {len(exported_map_ids)} map status row(s) "
        f"({len(cache.map_indices())} cached) -> {map_path}"
    )
    print(
        f"Wrote {sum(len(item.partitions) for item in cache.map_indices())} "
        f"partition nodes -> {node_path}"
    )
    print(
        f"Wrote {sum(item.leaf_membership_count for item in cache.map_indices())} "
        f"node-volume memberships -> {membership_path}"
    )
    return 0


def _load_areas(filepath: str) -> Optional[U9Areas]:
    """Open static/areas.flx, reporting the reason on failure."""
    if not os.path.isfile(filepath):
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        return None
    try:
        return U9Areas.from_file(filepath)
    except U9AreasError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return None


def cmd_areas_info(args: SimpleNamespace) -> int:
    """Summarize gameplay zones, boxes, and encounter tables."""
    areas = _load_areas(args.file)
    if areas is None:
        return 1
    zones = areas.zones()
    kinds = Counter(record.record_kind for record in areas.records())
    warning_ids = [zone.zone_id for zone in zones if zone.structural_warnings()]
    print(
        f"{args.file} -- {len(areas.records())} used gameplay-zone record(s) "
        f"of {areas.num_entries} slots"
    )
    print(
        "  record kinds          : "
        + ", ".join(f"{kind}={count}" for kind, count in sorted(kinds.items()))
    )
    print(f"  decoded box zones      : {len(zones)}")
    print(f"  world boxes            : {sum(len(zone.boxes) for zone in zones)}")
    print(f"  trigger-enabled zones  : {sum(zone.trigger_enabled for zone in zones)}")
    print(
        f"  encounter-table zones : {sum(zone.has_encounter_table for zone in zones)}"
    )
    print(f"  unsupported records    : {len(areas.unsupported_records())}")
    print(
        "  structural warnings   : "
        + (
            ", ".join(str(zone_id) for zone_id in warning_ids)
            if warning_ids
            else "none"
        )
    )
    return 0


def cmd_areas_show(args: SimpleNamespace) -> int:
    """Show one gameplay-zone record and its nested data."""
    areas = _load_areas(args.file)
    if areas is None:
        return 1
    record = areas.record(args.id)
    if record is None:
        print(f"Gameplay-zone slot {args.id} is unused.")
        return 0
    if not isinstance(record, U9GameplayZone):
        print(
            f"{args.file} -- gameplay-zone record {record.zone_id}: "
            f"unsupported kind {record.record_kind}, {len(record.raw_data)} raw byte(s)"
        )
        return 0

    warnings = record.structural_warnings()
    marker = record.path_marker_position
    print(f"{args.file} -- gameplay zone {record.zone_id}, kind {record.record_kind}")
    print(
        f"  stored_zone_id={record.stored_zone_id} "
        f"status={record.stored_zone_id_status} map={record.world_map_id}"
    )
    print(
        f"  flags={record.stored_flags:#010x} trigger={record.trigger_enabled} "
        f"encounters={record.has_encounter_table} "
        f"unclassified={record.unclassified_flag_bits:#010x}"
    )
    print(
        f"  path_marker=({marker.x}, {marker.y}, {marker.z}) "
        f"status={record.path_marker_position_status} "
        f"padding=0x{marker.padding.hex()}"
    )
    print(
        f"  encounter_chance={record.encounter_chance_percent} "
        f"status={record.encounter_chance_status} "
        f"stored_total_weight={record.stored_total_weight}"
    )
    if record.encounter_table is not None:
        table = record.encounter_table
        print(
            f"  encounter_choices={table.declared_choice_count} "
            f"active_weight_total={table.active_weight_total} "
            f"stored_flags={table.stored_flags:#06x}"
        )
        for choice in table.choice_slots:
            active = choice.slot_index < table.declared_choice_count
            print(
                f"    slot {choice.slot_index:>2}: active={active} "
                f"object_type={choice.object_type_id} weight={choice.selection_weight}"
            )
    print(f"  boxes={len(record.boxes)}")
    for box in record.boxes:
        first, second = box.corners
        print(
            f"    box {box.box_index}: ({first.x}, {first.y}, {first.z}) -> "
            f"({second.x}, {second.y}, {second.z}) "
            f"unbounded_height={box.uses_unbounded_height}"
        )
    print("  warnings: " + (", ".join(warnings) if warnings else "none"))
    return 0


def cmd_areas_csv(args: SimpleNamespace) -> int:
    """Export gameplay-zone, box, and encounter-slot tables to CSV."""
    areas = _load_areas(args.file)
    if areas is None:
        return 1

    output = Path(args.output or "areas_csv")
    try:
        output.mkdir(parents=True, exist_ok=True)
        area_path = output / "u9_areas.csv"
        box_path = output / "u9_area_boxes.csv"
        encounter_path = output / "u9_area_encounter_choices.csv"

        with area_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "zone_id",
                    "record_kind",
                    "record_kind_name",
                    "stored_zone_id",
                    "stored_zone_id_status",
                    "world_map_id",
                    "stored_flags",
                    "trigger_enabled",
                    "has_encounter_table",
                    "unclassified_flag_bits",
                    "encounter_chance_percent",
                    "encounter_chance_status",
                    "stored_total_weight",
                    "declared_encounter_choice_count",
                    "active_encounter_weight_total",
                    "encounter_reserved_prefix",
                    "encounter_reserved_suffix",
                    "encounter_stored_flags",
                    "declared_box_count",
                    "box_count",
                    "path_marker_x",
                    "path_marker_y",
                    "path_marker_z",
                    "path_marker_status",
                    "path_marker_padding_hex",
                    "structural_status",
                    "warnings",
                    "trailing_hex",
                    "raw_hex",
                ]
            )
            for record in areas.records():
                if not isinstance(record, U9GameplayZone):
                    writer.writerow(
                        [
                            record.zone_id,
                            record.record_kind,
                            "unsupported",
                            *([""] * 22),
                            "warning",
                            "unsupported_record_kind",
                            "",
                            f"0x{record.raw_data.hex()}",
                        ]
                    )
                    continue
                table = record.encounter_table
                warnings = record.structural_warnings()
                marker = record.path_marker_position
                writer.writerow(
                    [
                        record.zone_id,
                        record.record_kind,
                        "box_zone",
                        record.stored_zone_id,
                        record.stored_zone_id_status,
                        record.world_map_id,
                        f"0x{record.stored_flags:08x}",
                        record.trigger_enabled,
                        record.has_encounter_table,
                        f"0x{record.unclassified_flag_bits:08x}",
                        record.encounter_chance_percent,
                        record.encounter_chance_status,
                        record.stored_total_weight,
                        "" if table is None else table.declared_choice_count,
                        "" if table is None else table.active_weight_total,
                        "" if table is None else table.reserved_prefix,
                        "" if table is None else table.reserved_suffix,
                        "" if table is None else f"0x{table.stored_flags:04x}",
                        record.declared_box_count,
                        len(record.boxes),
                        marker.x,
                        marker.y,
                        marker.z,
                        record.path_marker_position_status,
                        f"0x{marker.padding.hex()}",
                        "ok" if not warnings else "warning",
                        ";".join(warnings),
                        f"0x{record.trailing_data.hex()}",
                        f"0x{record.raw_data.hex()}",
                    ]
                )

        with box_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "zone_id",
                    "box_index",
                    "entry_offset",
                    "corner_0_x",
                    "corner_0_y",
                    "corner_0_z",
                    "corner_0_padding_hex",
                    "corner_1_x",
                    "corner_1_y",
                    "corner_1_z",
                    "corner_1_padding_hex",
                    "minimum_x",
                    "minimum_y",
                    "minimum_z",
                    "maximum_x",
                    "maximum_y",
                    "maximum_z",
                    "uses_unbounded_height",
                    "raw_hex",
                ]
            )
            for zone in areas.zones():
                for box in zone.boxes:
                    first, second = box.corners
                    writer.writerow(
                        [
                            zone.zone_id,
                            box.box_index,
                            box.entry_offset,
                            first.x,
                            first.y,
                            first.z,
                            f"0x{first.padding.hex()}",
                            second.x,
                            second.y,
                            second.z,
                            f"0x{second.padding.hex()}",
                            *box.minimum,
                            *box.maximum,
                            box.uses_unbounded_height,
                            f"0x{box.raw_data.hex()}",
                        ]
                    )

        with encounter_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "zone_id",
                    "slot_index",
                    "is_active",
                    "object_type_id",
                    "selection_weight",
                    "raw_hex",
                ]
            )
            for zone in areas.zones():
                table = zone.encounter_table
                if table is None:
                    continue
                for choice in table.choice_slots:
                    writer.writerow(
                        [
                            zone.zone_id,
                            choice.slot_index,
                            choice.slot_index < table.declared_choice_count,
                            choice.object_type_id,
                            choice.selection_weight,
                            f"0x{choice.raw_data.hex()}",
                        ]
                    )
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {len(areas.records())} gameplay-zone rows -> {area_path}")
    print(
        f"Wrote {sum(len(zone.boxes) for zone in areas.zones())} "
        f"zone boxes -> {box_path}"
    )
    print(
        f"Wrote {sum(len(zone.encounter_table.choice_slots) for zone in areas.zones() if zone.encounter_table is not None)} "
        f"encounter slots -> {encounter_path}"
    )
    return 0


def highway_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/highway.dat")],
) -> None:
    """Summarize the U9 NPC navigation graph: points, routes, connectivity."""
    raise SystemExit(cmd_highway_info(SimpleNamespace(file=file)))


def highway_points_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/highway.dat")],
    id: Annotated[
        Optional[int],
        typer.Option("-i", "--id", help="Show only the point with this link"),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum rows to print"),
    ] = None,
) -> None:
    """List U9 highway navigation points and their world positions."""
    raise SystemExit(cmd_highway_points(SimpleNamespace(file=file, id=id, limit=limit)))


def highway_routes_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/highway.dat")],
    id: Annotated[
        Optional[int],
        typer.Option("-i", "--id", help="Only routes visiting this link"),
    ] = None,
    paths: Annotated[
        bool,
        typer.Option("-p", "--paths", help="Print each route's full node path"),
    ] = False,
    limit: Annotated[
        Optional[int],
        typer.Option("-n", "--limit", help="Maximum routes to print"),
    ] = None,
) -> None:
    """List the precomputed routes through the U9 highway graph."""
    raise SystemExit(
        cmd_highway_routes(SimpleNamespace(file=file, id=id, paths=paths, limit=limit))
    )


def spaces_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/spaces.flx")],
) -> None:
    """Summarize U9 enclosed spaces and their nested geometry."""
    raise SystemExit(cmd_spaces_info(SimpleNamespace(file=file)))


def spaces_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/spaces.flx")],
    id: Annotated[int, typer.Argument(help="Space ID (the FLX entry index)")],
) -> None:
    """Show one enclosed space, its boundary planes, and its portals."""
    raise SystemExit(cmd_spaces_show(SimpleNamespace(file=file, id=id)))


def spaces_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/spaces.flx")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory for space, plane, and portal CSV files",
        ),
    ] = None,
) -> None:
    """Export lossless U9 space, boundary-plane, and portal tables."""
    raise SystemExit(cmd_spaces_csv(SimpleNamespace(file=file, output=output)))


def treedat_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/treedat.flx")],
    spaces: Annotated[
        Optional[str],
        typer.Option("--spaces", help="Optional static/spaces.flx validation join"),
    ] = None,
) -> None:
    """Summarize the derived U9 volume lookup cache."""
    raise SystemExit(cmd_treedat_info(SimpleNamespace(file=file, spaces=spaces)))


def treedat_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/treedat.flx")],
    id: Annotated[int, typer.Argument(help="Map ID (the FLX entry index)")],
) -> None:
    """Show one map's cached volume list and partition nodes."""
    raise SystemExit(cmd_treedat_show(SimpleNamespace(file=file, id=id)))


def treedat_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/treedat.flx")],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Output directory for cache CSV files"),
    ] = None,
    spaces: Annotated[
        Optional[str],
        typer.Option("--spaces", help="Optional static/spaces.flx validation join"),
    ] = None,
) -> None:
    """Export map, partition, and node-volume cache tables."""
    raise SystemExit(
        cmd_treedat_csv(SimpleNamespace(file=file, output=output, spaces=spaces))
    )


def areas_info_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/areas.flx")],
) -> None:
    """Summarize U9 gameplay zones, boxes, and encounter tables."""
    raise SystemExit(cmd_areas_info(SimpleNamespace(file=file)))


def areas_show_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/areas.flx")],
    id: Annotated[int, typer.Argument(help="Gameplay-zone ID (FLX entry index)")],
) -> None:
    """Show one U9 gameplay-zone record and its nested data."""
    raise SystemExit(cmd_areas_show(SimpleNamespace(file=file, id=id)))


def areas_csv_cmd(
    file: Annotated[str, typer.Argument(help="Path to static/areas.flx")],
    output: Annotated[
        Optional[str],
        typer.Option(
            "-o",
            "--output",
            help="Output directory for zone, box, and encounter CSV files",
        ),
    ] = None,
) -> None:
    """Export lossless U9 gameplay-zone, box, and encounter tables."""
    raise SystemExit(cmd_areas_csv(SimpleNamespace(file=file, output=output)))
