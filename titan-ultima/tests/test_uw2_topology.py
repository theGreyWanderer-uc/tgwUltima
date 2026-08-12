"""Unit tests for uu2map.topology's tile-adjacency and diagonal-boundary rules.

These pin down the hand-debugged behavior described in
uuw2data/references/UU2_debug_render_commands.md and
UU2_mapping_data_structure_report.md so a future refactor of the shared
topology module (used by all three renderers) can't silently regress it.
"""

from titan.uw2.topology import (
    diagonal_hypotenuse_endpoints,
    find_door_object,
    infer_flag_door_heading,
    is_blocked_diagonal_neighbor,
    iter_tile_objects,
    neighbor_coords,
    neighbor_is_open_across_side,
    opposite_side,
    skip_external_side_for_diagonal,
)


def make_tile(type_name, x=5, y=5):
    return {"x": x, "y": y, "type_name": type_name}


DIAGONAL_TYPES = ("diagonal_se", "diagonal_sw", "diagonal_nw", "diagonal_ne")


def test_opposite_side_is_involutive():
    for side in ("left", "right", "back", "front"):
        assert opposite_side(opposite_side(side)) == side


def test_neighbor_coords_round_trip_through_opposite_side():
    x, y = 12, 30
    for side in ("left", "right", "back", "front"):
        nx, ny = neighbor_coords(side, x, y)
        assert neighbor_coords(opposite_side(side), nx, ny) == (x, y)


def test_each_diagonal_type_skips_exactly_two_adjacent_sides():
    # A diagonal tile's floor is a right triangle: exactly two of its four
    # sides border the cut-off solid corner and are not part of the floor.
    for type_name in DIAGONAL_TYPES:
        skipped = [
            s
            for s in ("left", "right", "back", "front")
            if skip_external_side_for_diagonal(type_name, s)
        ]
        assert len(skipped) == 2


def test_neighbor_is_open_across_side_blocks_solid_neighbor():
    assert neighbor_is_open_across_side(make_tile("solid"), "front") is False


def test_neighbor_is_open_across_side_blocks_missing_neighbor():
    assert neighbor_is_open_across_side(None, "front") is False


def test_neighbor_is_open_across_side_respects_diagonal_cut_corner():
    # diagonal_nw's floor triangle does not touch its "right"/"back" sides
    # (the cut-off corner); a tile bordering it there must see it as blocked,
    # matching the Castle Britannia display 35,30 fix.
    diagonal_nw = make_tile("diagonal_nw")
    assert neighbor_is_open_across_side(diagonal_nw, "back") is False
    assert neighbor_is_open_across_side(diagonal_nw, "right") is False
    # ...but the two sides that ARE part of its floor triangle are open.
    assert neighbor_is_open_across_side(diagonal_nw, "left") is True
    assert neighbor_is_open_across_side(diagonal_nw, "front") is True


def test_is_blocked_diagonal_neighbor_only_true_on_the_cut_corner_sides():
    diagonal_nw = make_tile("diagonal_nw")
    assert is_blocked_diagonal_neighbor(diagonal_nw, "back") is True
    assert is_blocked_diagonal_neighbor(diagonal_nw, "right") is True
    assert is_blocked_diagonal_neighbor(diagonal_nw, "left") is False
    assert is_blocked_diagonal_neighbor(diagonal_nw, "front") is False
    assert is_blocked_diagonal_neighbor(make_tile("open"), "back") is False
    assert is_blocked_diagonal_neighbor(None, "back") is False


def test_diagonal_hypotenuse_endpoints_pair_with_that_type_s_skipped_sides():
    # Each hypotenuse endpoint terminates one of the tile's two skipped
    # (non-floor) sides. This is the invariant make_diagonal_corner_fills
    # relies on to find the right neighbor to bridge against.
    for type_name in DIAGONAL_TYPES:
        skipped = {
            s
            for s in ("left", "right", "back", "front")
            if skip_external_side_for_diagonal(type_name, s)
        }
        endpoints = diagonal_hypotenuse_endpoints(type_name, 5, 5)
        assert endpoints is not None
        paired_sides = {side for _point, side in endpoints}
        assert paired_sides == skipped


def test_diagonal_hypotenuse_endpoints_none_for_non_diagonal():
    assert diagonal_hypotenuse_endpoints("open", 5, 5) is None


def test_iter_tile_objects_follows_chain_and_stops_on_cycle():
    tile = {"object_chain_start": 1}
    object_map = {
        1: {"slot": 1, "next": 2},
        2: {"slot": 2, "next": 1},  # cycle back to 1
    }
    seen = list(iter_tile_objects(tile, object_map))
    assert [obj["slot"] for obj in seen] == [1, 2]


def test_find_door_object_matches_item_id_range():
    tile = {"object_chain_start": 1}
    object_map = {1: {"slot": 1, "item_id": 0x0143, "next": 0}}
    assert find_door_object(tile, object_map) is object_map[1]


def test_find_door_object_ignores_non_door_items():
    tile = {"object_chain_start": 1}
    object_map = {1: {"slot": 1, "item_id": 0x0170, "next": 0}}
    assert find_door_object(tile, object_map) is None


def test_infer_flag_door_heading_picks_the_axis_with_two_open_sides():
    # A hallway open on left/right (and blocked front/back) is a north-south
    # wall opening, i.e. heading 2 in this coordinate scheme.
    x, y = 5, 5
    tile = make_tile("open", x, y)
    tile_map = {
        (x, y): tile,
        neighbor_coords("left", x, y): make_tile("open"),
        neighbor_coords("right", x, y): make_tile("open"),
        neighbor_coords("back", x, y): make_tile("solid"),
        neighbor_coords("front", x, y): make_tile("solid"),
    }
    assert infer_flag_door_heading(tile, tile_map) == 2


def test_infer_flag_door_heading_defaults_to_zero_when_ambiguous():
    x, y = 5, 5
    tile = make_tile("open", x, y)
    tile_map = {(x, y): tile}
    assert infer_flag_door_heading(tile, tile_map) == 0
