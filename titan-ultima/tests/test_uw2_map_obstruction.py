"""Tests for the wall-height obstruction clip in render_uuw2_as_u7_style.py.

This renderer draws each wall as an independent quad sorted by a rough
screen-proximity key, not a real per-pixel depth buffer, so a wall taller
than the gap to whatever tile sits "behind" it on screen can paint over
that tile's floor. obstruction_limited_wall_height detects that and caps
the wall's height to stop just short of it. See the "Wall Height vs.
Obstruction" entry in UU2_mapping_data_structure_report.md for how this was
diagnosed against Ice Caverns Level 1's real data (median ceiling-floor
span 96 units, in a level with narrow winding 1-2 tile-wide passages).
"""

from titan.uw2 import map_render as renderer


class Args:
    tile_size = 64
    lift_pixels = 4.0
    floor_height_per_lift = 8.0
    wall_height_scale = 1.0
    max_wall_height = 128.0
    orientation = "display"


def make_tile(x, y, type_name="open", floor_height=0, ceiling_height=128):
    return {
        "x": x,
        "y": y,
        "type_name": type_name,
        "floor_height": floor_height,
        "ceiling_height": ceiling_height,
        "texture_wall": 1,
    }


def test_no_limit_when_back_diagonal_is_solid():
    tile = make_tile(5, 5)
    tile_map = {(5, 5): tile, (4, 6): make_tile(4, 6, "solid")}
    assert (
        renderer.obstruction_limited_wall_height(tile, tile_map, 0, 64, Args()) is None
    )


def test_no_limit_when_back_diagonal_is_missing():
    tile = make_tile(5, 5)
    tile_map = {(5, 5): tile}
    assert (
        renderer.obstruction_limited_wall_height(tile, tile_map, 0, 64, Args()) is None
    )


def test_no_limit_when_neighbor_is_same_height_and_adjacent():
    # Matches ordinary architecture: evenly spaced, same-height tiles must
    # not get clipped just because a neighbor happens to exist back there.
    tile = make_tile(5, 5, floor_height=96, ceiling_height=128)
    neighbor = make_tile(4, 6, floor_height=96, ceiling_height=128)
    tile_map = {(5, 5): tile, (4, 6): neighbor}
    assert (
        renderer.obstruction_limited_wall_height(tile, tile_map, 0, 64, Args()) is None
    )


def test_limit_applies_when_back_diagonal_floor_is_much_higher():
    tile = make_tile(5, 5, floor_height=0, ceiling_height=128)
    neighbor = make_tile(4, 6, floor_height=200, ceiling_height=228)
    tile_map = {(5, 5): tile, (4, 6): neighbor}
    limit = renderer.obstruction_limited_wall_height(tile, tile_map, 0, 64, Args())
    assert limit is not None
    assert 0 < limit < renderer.wall_screen_height(tile, Args())


def test_search_walks_past_solid_tiles_to_find_open_floor():
    tile = make_tile(5, 5, floor_height=0, ceiling_height=128)
    solid_gap = make_tile(4, 6, "solid")
    far_neighbor = make_tile(3, 7, floor_height=200, ceiling_height=228)
    tile_map = {(5, 5): tile, (4, 6): solid_gap, (3, 7): far_neighbor}
    limit = renderer.obstruction_limited_wall_height(tile, tile_map, 0, 64, Args())
    assert limit is not None


def test_search_is_bounded_by_max_wall_height():
    # A non-solid tile far enough out that even the tallest possible wall
    # could never reach it should not be found (and would be wasted work).
    tile = make_tile(5, 5, floor_height=0, ceiling_height=128)
    tile_map = {(5, 5): tile}
    for k in range(1, 6):
        tile_map[(5 - k, 5 + k)] = make_tile(5 - k, 5 + k, "solid")
    tile_map[(5 - 6, 5 + 6)] = make_tile(
        5 - 6, 5 + 6, floor_height=0, ceiling_height=128
    )

    class ShortReachArgs(Args):
        max_wall_height = 64.0  # only reaches ~1-2 tiles back

    assert (
        renderer.obstruction_limited_wall_height(
            tile, tile_map, 0, 64, ShortReachArgs()
        )
        is None
    )


def test_no_obstruction_clip_flag_disables_clipping_in_make_tile_walls():
    # obstruction_limited_wall_height checks raw (x-1, y+1) under display
    # orientation -- put a much-higher-floored tile exactly there so the
    # clip actually has something to bite on.
    tile = make_tile(5, 5, floor_height=0, ceiling_height=128)
    back_diagonal = make_tile(4, 6, floor_height=200, ceiling_height=228)
    # A blocked "left" neighbor gives tile a normal edge wall to inspect.
    tile_map = {(5, 5): tile, (4, 6): back_diagonal, (4, 5): make_tile(4, 5, "solid")}

    class ClipArgs(Args):
        no_obstruction_clip = False
        no_doors = True
        no_flat_objects = True

    class NoClipArgs(Args):
        no_obstruction_clip = True
        no_doors = True
        no_flat_objects = True

    def left_wall_height(walls):
        wall = next(w for w in walls if w.side == "left")
        top_a, _top_b, base_a, _base_b = wall.quad
        return base_a[1] - top_a[1]

    clipped_height = left_wall_height(
        renderer.make_tile_walls(tile, tile_map, 0, 64, ClipArgs())
    )
    unclipped_height = left_wall_height(
        renderer.make_tile_walls(tile, tile_map, 0, 64, NoClipArgs())
    )

    assert clipped_height < unclipped_height
    assert unclipped_height == renderer.wall_screen_height(tile, ClipArgs())
