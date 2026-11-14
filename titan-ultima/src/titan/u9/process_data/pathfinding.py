"""Path grid, pathfinder process and path manager states."""

from __future__ import annotations

__all__ = [
    "U9PathGridCell",
    "U9PathGridState",
    "U9PathfinderProcessState",
    "U9PathManagerState",
]

import struct
from dataclasses import dataclass

from titan.u9.process_data._base import (
    PATHFINDER_PROCESS_TYPE,
    U9ProcessDataError,
    U9ProcessHeaderState,
    U9ProcessWorldState,
    _read_world_process_prefix,
    _require_bytes,
    _validate_finite,
    _validate_object_reference_index,
)


PATHFINDER_PROCESS_VERSION = 6
# Fixed part up to and including the grid-present byte, then the tail after
# the optional grid.
PATHFINDER_STATE = struct.Struct("<iiiff" + "3f" * 7 + "iiiiif3ffiiiifff3fB")
PATHFINDER_TAIL = struct.Struct("<7i")
PATH_GRID_HEADER = struct.Struct("<15f4f4i2f2iiI")
PATH_GRID_CELL = struct.Struct("<6i3fI")
PATH_GRID_TAIL = struct.Struct("<IIfiI")
MAX_PATH_GRID_SIDE = 1024
PATH_MANAGER_VERSION = 0
PATH_MANAGER_ARRAY_ELEMENTS = (
    struct.Struct("<3f"),
    struct.Struct("<f"),
    struct.Struct("<4f"),
    struct.Struct("<f"),
)
PATH_MANAGER_TAIL = struct.Struct("<iffffiiiiii")
MAX_PATH_MANAGER_NODES = 0x10000


@dataclass(frozen=True)
class U9PathGridCell:
    """One 40-byte cell of a saved path-search grid.

    Only cells the search touched (``flags`` non-zero) hold meaningful
    values; the game never clears the others, so their remaining fields are
    arbitrary. ``next_address`` is a raw pointer to the next cell in the
    search queue (not the next step of the path); use
    :meth:`U9PathGridState.cell_index` to turn it into a cell index.
    """

    x: int
    y: int
    flags: int
    distance: int
    priority: int
    estimate: int
    location: tuple[float, float, float]
    next_address: int


@dataclass(frozen=True)
class U9PathGridState:
    """The optional grid search saved inside a pathfinder process.

    The grid holds ``x_cells * y_cells`` cells in row-major order (cell
    ``i`` is at ``x = i % x_cells``, ``y = i // x_cells``). The queue, path
    and best-cell links are saved as raw pointers into the grid;
    ``grid_address`` is the grid's own address at save time, so
    :meth:`cell_index` converts any of them to a cell index.
    """

    from_position: tuple[float, float, float]
    to_position: tuple[float, float, float]
    horizontal: tuple[float, float, float]
    vertical: tuple[float, float, float]
    origin: tuple[float, float, float]
    vertical_tolerance: float
    allowed_slope: float
    maximum_stair_height: float
    maximum_stair_slope: float
    from_cell: tuple[int, int]
    to_cell: tuple[int, int]
    cell_radius: float
    cylinder_height: float
    x_cells: int
    y_cells: int
    path_found: bool
    grid_address: int
    cells: tuple[U9PathGridCell, ...]
    queue_address: int
    path_address: int
    cell_spacing: float
    blocked: bool
    best_cell_address: int
    offset: int
    end_offset: int

    def cell_index(self, address: int) -> int | None:
        """Index of the cell a saved pointer refers to, or ``None``."""
        relative = address - self.grid_address
        if address == 0 or relative % PATH_GRID_CELL.size:
            return None
        index = relative // PATH_GRID_CELL.size
        return index if 0 <= index < len(self.cells) else None

    @property
    def queue_cell_index(self) -> int | None:
        return self.cell_index(self.queue_address)

    @property
    def path_cell_index(self) -> int | None:
        return self.cell_index(self.path_address)

    @property
    def best_cell_index(self) -> int | None:
        return self.cell_index(self.best_cell_address)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> U9PathGridState:
        _require_bytes(data, offset, PATH_GRID_HEADER.size, "path-grid header")
        v = PATH_GRID_HEADER.unpack_from(data, offset)
        x_cells, y_cells = v[25], v[26]
        if not (
            0 < x_cells <= MAX_PATH_GRID_SIDE and 0 < y_cells <= MAX_PATH_GRID_SIDE
        ):
            raise U9ProcessDataError(f"invalid path-grid size {x_cells}x{y_cells}")
        if v[27] not in (0, 1):
            raise U9ProcessDataError(f"invalid path-grid path-found flag {v[27]}")
        _validate_finite(v[0:19] + v[23:25], "path-grid geometry")
        cursor = offset + PATH_GRID_HEADER.size
        count = x_cells * y_cells
        _require_bytes(data, cursor, count * PATH_GRID_CELL.size, "path-grid cells")
        cells = tuple(
            U9PathGridCell(
                x=c[0],
                y=c[1],
                flags=c[2],
                distance=c[3],
                priority=c[4],
                estimate=c[5],
                location=(c[6], c[7], c[8]),
                next_address=c[9],
            )
            for c in PATH_GRID_CELL.iter_unpack(
                data[cursor : cursor + count * PATH_GRID_CELL.size]
            )
        )
        cursor += count * PATH_GRID_CELL.size
        _require_bytes(data, cursor, PATH_GRID_TAIL.size, "path-grid tail")
        queue, path, spacing, blocked, best = PATH_GRID_TAIL.unpack_from(data, cursor)
        if blocked not in (0, 1):
            raise U9ProcessDataError(f"invalid path-grid blocked flag {blocked}")
        _validate_finite((spacing,), "path-grid cell spacing")
        return cls(
            from_position=v[0:3],
            to_position=v[3:6],
            horizontal=v[6:9],
            vertical=v[9:12],
            origin=v[12:15],
            vertical_tolerance=v[15],
            allowed_slope=v[16],
            maximum_stair_height=v[17],
            maximum_stair_slope=v[18],
            from_cell=(v[19], v[20]),
            to_cell=(v[21], v[22]),
            cell_radius=v[23],
            cylinder_height=v[24],
            x_cells=x_cells,
            y_cells=y_cells,
            path_found=bool(v[27]),
            grid_address=v[28],
            cells=cells,
            queue_address=queue,
            path_address=path,
            cell_spacing=spacing,
            blocked=bool(blocked),
            best_cell_address=best,
            offset=offset,
            end_offset=cursor + PATH_GRID_TAIL.size,
        )


@dataclass(frozen=True)
class U9PathfinderProcessState:
    """A type-1 pathfinder process: one NPC walking to a goal.

    The fixed part covers the target (an NPC number, or -1 for a point), the
    origin, goal, current leg and step goals, termination tests, search and
    walk states, and collision limits. ``grid`` is present when the walker
    had fallen back to a grid search. ``duration_npc_offset`` and
    ``termination_npc_offset`` are byte offsets into the NPC table (-1 for
    none). Several fields are only set in some walk states (the previous walk
    state, blocked and last-seen positions, obstacle-avoid angle), so their
    stored values can be anything, including NaN; the fixed part's numbers
    are therefore not range-checked.
    """

    header: U9ProcessHeaderState
    world_state: U9ProcessWorldState
    version: int
    npc_number: int
    target_npc_number: int
    target_radius: float
    approach_angle: float
    origin: tuple[float, float, float]
    step_start: tuple[float, float, float]
    goal: tuple[float, float, float]
    leg_goal: tuple[float, float, float]
    step_goal: tuple[float, float, float]
    blocked_position: tuple[float, float, float]
    goal_offset: tuple[float, float, float]
    speed: int
    careful_walk: int
    duration_npc_offset: int
    termination_npc_offset: int
    termination_value: int
    last_angle: float
    target_ray: tuple[float, float, float]
    arrive_tolerance: float
    flags: int
    search_state: int
    walk_state: int
    previous_walk_state: int
    radius: float
    cylinder_radius: float
    avoidance_angle: float
    last_seen_position: tuple[float, float, float]
    grid: U9PathGridState | None
    continue_callback: int
    ending_callback: int
    status_code: int
    last_grid_step_ok: int
    probes_per_frame: int
    probe_limit: int
    probes_remaining: int
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9PathfinderProcessState:
        header, world_state = _read_world_process_prefix(
            data,
            offset,
            frozenset({PATHFINDER_PROCESS_TYPE}),
            "pathfinder",
            object_reference_count,
        )
        cursor = world_state.end_offset
        _require_bytes(data, cursor, PATHFINDER_STATE.size, "pathfinder process")
        v = PATHFINDER_STATE.unpack_from(data, cursor)
        if v[0] != PATHFINDER_PROCESS_VERSION:
            raise U9ProcessDataError(
                f"unsupported pathfinder version {v[0]} at 0x{cursor:X}"
            )
        has_grid = v[46]
        if has_grid not in (0, 1):
            raise U9ProcessDataError(f"invalid pathfinder grid flag {has_grid}")
        cursor += PATHFINDER_STATE.size
        grid = U9PathGridState.from_bytes(data, cursor) if has_grid else None
        if grid is not None:
            cursor = grid.end_offset
        _require_bytes(data, cursor, PATHFINDER_TAIL.size, "pathfinder tail")
        tail = PATHFINDER_TAIL.unpack_from(data, cursor)
        return cls(
            header=header,
            world_state=world_state,
            version=v[0],
            npc_number=v[1],
            target_npc_number=v[2],
            target_radius=v[3],
            approach_angle=v[4],
            origin=v[5:8],
            step_start=v[8:11],
            goal=v[11:14],
            leg_goal=v[14:17],
            step_goal=v[17:20],
            blocked_position=v[20:23],
            goal_offset=v[23:26],
            speed=v[26],
            careful_walk=v[27],
            duration_npc_offset=v[28],
            termination_npc_offset=v[29],
            termination_value=v[30],
            last_angle=v[31],
            target_ray=v[32:35],
            arrive_tolerance=v[35],
            flags=v[36],
            search_state=v[37],
            walk_state=v[38],
            previous_walk_state=v[39],
            radius=v[40],
            cylinder_radius=v[41],
            avoidance_angle=v[42],
            last_seen_position=v[43:46],
            grid=grid,
            continue_callback=tail[0],
            ending_callback=tail[1],
            status_code=tail[2],
            last_grid_step_ok=tail[3],
            probes_per_frame=tail[4],
            probe_limit=tail[5],
            probes_remaining=tail[6],
            offset=offset,
            end_offset=cursor + PATHFINDER_TAIL.size,
        )


@dataclass(frozen=True)
class U9PathManagerState:
    """A path along path markers, saved inside a floating-lantern process.

    Four count-prefixed arrays (spline points, their distances from the
    start, orientations at the input nodes, and their distances), then the
    path's link, distances, direction, speed, node counts, marked position
    and orientation indices, and the last and first path markers. When no
    path is built the arrays are empty and the later words can be stale.
    """

    version: int
    spline_points: tuple[tuple[float, float, float], ...]
    spline_distances: tuple[float, ...]
    orientations: tuple[tuple[float, float, float, float], ...]
    orientation_distances: tuple[float, ...]
    link: int
    current_distance: float
    previous_distance: float
    direction: float
    speed: float
    input_node_count: int
    output_node_count: int
    marked_position: int
    marked_orientation: int
    last_path_marker_object_reference_index: int
    first_path_marker_object_reference_index: int
    offset: int
    end_offset: int

    @classmethod
    def from_bytes(
        cls, data: bytes, offset: int, *, object_reference_count: int
    ) -> U9PathManagerState:
        _require_bytes(data, offset, 4, "path-manager version")
        (version,) = struct.unpack_from("<i", data, offset)
        if version != PATH_MANAGER_VERSION:
            raise U9ProcessDataError(
                f"unsupported path-manager version {version} at 0x{offset:X}"
            )
        cursor = offset + 4
        arrays: list[tuple[object, ...]] = []
        for element in PATH_MANAGER_ARRAY_ELEMENTS:
            _require_bytes(data, cursor, 4, "path-manager array count")
            (count,) = struct.unpack_from("<i", data, cursor)
            cursor += 4
            if not 0 <= count <= MAX_PATH_MANAGER_NODES:
                raise U9ProcessDataError(
                    f"invalid path-manager array count {count} at 0x{cursor - 4:X}"
                )
            _require_bytes(data, cursor, count * element.size, "path-manager array")
            values = tuple(
                item if len(item) > 1 else item[0]
                for item in element.iter_unpack(
                    data[cursor : cursor + count * element.size]
                )
            )
            cursor += count * element.size
            arrays.append(values)
        _require_bytes(data, cursor, PATH_MANAGER_TAIL.size, "path-manager tail")
        t = PATH_MANAGER_TAIL.unpack_from(data, cursor)
        for index, label in ((9, "last marker"), (10, "first marker")):
            _validate_object_reference_index(
                t[index], object_reference_count, f"path-manager {label}"
            )
        return cls(
            version=version,
            spline_points=arrays[0],  # type: ignore[arg-type]
            spline_distances=arrays[1],  # type: ignore[arg-type]
            orientations=arrays[2],  # type: ignore[arg-type]
            orientation_distances=arrays[3],  # type: ignore[arg-type]
            link=t[0],
            current_distance=t[1],
            previous_distance=t[2],
            direction=t[3],
            speed=t[4],
            input_node_count=t[5],
            output_node_count=t[6],
            marked_position=t[7],
            marked_orientation=t[8],
            last_path_marker_object_reference_index=t[9],
            first_path_marker_object_reference_index=t[10],
            offset=offset,
            end_offset=cursor + PATH_MANAGER_TAIL.size,
        )
