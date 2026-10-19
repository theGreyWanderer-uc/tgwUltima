"""Tests for UO named installs, multi record detection and house footprints."""

from __future__ import annotations

import struct

import pytest

from titan.uo.housing import house_footprint, parse_house_placement_tool
from titan.uo.installs import configured_installs, resolve_install
from titan.uo.multi import UOMulti, UOMultiComponent, UOMultis, detect_mul_stride
from titan.uo.tiledata import UOStaticTile, UOTileData


# -- installs ---------------------------------------------------------------


def _config(tmp_path):
    classic = tmp_path / "classic"
    uof = tmp_path / "uof"
    classic.mkdir()
    uof.mkdir()
    return {
        "uo": {
            "game": {"install": "classic"},
            "installs": {
                "classic": {"path": str(classic), "output": str(tmp_path / "out" / "classic")},
                "UOF": {"path": str(uof), "multis": "mul"},
            },
        }
    }, classic, uof


def test_resolve_install_by_name_default_and_path(tmp_path):
    config, classic, uof = _config(tmp_path)

    path, install = resolve_install(None, config)
    assert path == classic and install.name == "classic"
    assert install.output == tmp_path / "out" / "classic"

    path, install = resolve_install("uof", config)  # names are case-insensitive
    assert path == uof and install.multis == "mul" and install.output is None

    path, install = resolve_install(str(uof), config)  # a directory maps back to its install
    assert install is not None and install.name == "UOF"

    other = tmp_path / "other"
    other.mkdir()
    assert resolve_install(str(other), config) == (other, None)


def test_resolve_install_errors(tmp_path):
    config, _classic, _uof = _config(tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_install(str(tmp_path / "missing"), config)
    config["uo"]["game"] = {"install": "nope"}
    with pytest.raises(FileNotFoundError, match="nope"):
        resolve_install(None, config)
    with pytest.raises(ValueError, match="multis"):
        configured_installs({"uo": {"installs": {"x": {"path": "p", "multis": "zip"}}}})


def test_legacy_base_still_works(tmp_path):
    assert resolve_install(None, {"uo": {"game": {"base": str(tmp_path)}}}) == (tmp_path, None)


# -- multi record size ------------------------------------------------------


def _records(stride, components):
    out = b""
    for item, x, y, z, flags in components:
        out += struct.pack("<Hhhh", item, x, y, z) + struct.pack("<I", flags)
        if stride == 16:
            out += struct.pack("<I", 0)
    return out


def _house(n=12):
    return [(0x100 + i, i % 4 - 2, i // 4 - 2, i % 3, 1) for i in range(n)]


def test_stride_detected_per_file_even_when_entries_fit_both():
    # 12 records of 12 bytes = 144 bytes, which also divides by 16.
    data12 = [_records(12, _house(12)), _records(12, _house(4))]
    assert len(data12[0]) % 16 == 0
    assert detect_mul_stride(data12) == 12
    assert detect_mul_stride([_records(16, _house(12)), _records(16, _house(3))]) == 16


def test_stride_rejects_garbage():
    with pytest.raises(ValueError):
        detect_mul_stride([b"\xff" * 48])


def test_mul_multis_read_with_detected_stride(tmp_path):
    entries = [_records(12, _house(12)), _records(12, _house(4))]
    idx = b""
    mul = b""
    for data in entries:
        idx += struct.pack("<III", len(mul), len(data), 0)
        mul += data
    (tmp_path / "multi.idx").write_bytes(idx)
    (tmp_path / "multi.mul").write_bytes(mul)

    multis = UOMultis.from_client(tmp_path, container="auto")
    assert (multis.source, multis.layout) == ("multi.mul", "mul12")
    assert len(multis.multis[0].components) == 12
    assert multis.multis[0].components[5].x == 5 % 4 - 2
    with pytest.raises(FileNotFoundError):
        UOMultis.from_client(tmp_path, container="uop")


# -- placement table and footprints -----------------------------------------


_TOOL = """
    private static HousePlacementEntry[] m_ClassicHouses = new HousePlacementEntry[]
    {
        new HousePlacementEntry( typeof( SmallOldHouse ), 1011303, 425, 212, 489, 244, 10, 37000, 0, 4, 0, 0x0064 ),
    };
    private static HousePlacementEntry[] m_TwoStoryFoundations = new HousePlacementEntry[]
    {
        new HousePlacementEntry( typeof( HouseFoundation ), 1060241, 425, 212, 489, 244, 10, 30500, 0, 4, 0, 0x13EC ), // 7x7
    };
"""


def test_parse_house_placement_tool(tmp_path):
    path = tmp_path / "HousePlacementTool.cs"
    path.write_text(_TOOL, encoding="utf-8")
    entries = parse_house_placement_tool(path)
    assert [(e.category, e.type_name, e.multi_id, e.offset, e.cost) for e in entries] == [
        ("ClassicHouses", "SmallOldHouse", 0x64, (0, 4, 0), 37000),
        ("TwoStoryFoundations", "HouseFoundation", 0x13EC, (0, 4, 0), 30500),
    ]


def _tiledata():
    statics = [UOStaticTile(i, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "x") for i in range(0x200)]
    statics[0x10] = UOStaticTile(0x10, 0x10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 20, "wall")
    statics[0x63] = UOStaticTile(0x63, 0x10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 5, "stairs")
    statics[0x20] = UOStaticTile(0x20, 0x200, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "floor")
    return UOTileData(is_new_format=True, land=[], statics=statics)


def _ring_multi(multi_id):
    components = []
    for x in range(-1, 2):
        for y in range(-1, 2):
            item = 0x20 if (x, y) == (0, 0) else 0x10
            components.append(UOMultiComponent(item, x, y, 0, 0, 0, True))
    return UOMulti(multi_id, "test", "test", tuple(components))


def test_classic_footprint_border_and_yard():
    footprint = house_footprint(_ring_multi(0x64), _tiledata())
    assert not footprint.stairs_added
    assert len(footprint.occupied) == 9
    assert len(footprint.foundation) == 8  # the floor cell is not a wall
    assert footprint.extent(footprint.border) == (-2, 2, -2, 2)
    assert (0, 0) not in footprint.border  # under a base floor
    assert footprint.extent(footprint.yard) == (-2, 2, -6, 6)


def test_customizable_foundation_gets_stairs_row():
    footprint = house_footprint(_ring_multi(0x13EC), _tiledata())
    assert footprint.stairs_added
    assert footprint.extent(footprint.occupied) == (-1, 1, -1, 2)
    assert {(x, 2) for x in (-1, 0, 1)} <= footprint.foundation
    assert footprint.extent(footprint.yard) == (-2, 2, -6, 7)


def test_footprint_drawing_and_sheet(tmp_path):
    from titan.uo.housing import footprint_sheet, render_footprint

    path = tmp_path / "HousePlacementTool.cs"
    path.write_text(_TOOL, encoding="utf-8")
    entry = parse_house_placement_tool(path)[0]
    footprint = house_footprint(_ring_multi(0x64), _tiledata())

    thumb = render_footprint(footprint, entry.offset, scale=4)
    # Yard spans x -2..2 and y -6..6; the cursor (0, 4) is inside it.
    assert thumb.size == (5 * 4, 13 * 4)
    centre = thumb.getpixel((2 * 4 + 2, 6 * 4 + 2))
    cursor = thumb.getpixel((2 * 4 + 2, 10 * 4 + 2))
    assert centre == (220, 60, 60) and cursor == (90, 200, 120)

    sheet = footprint_sheet([(entry, "Stone house", footprint)], scale=4, max_width=400, title="t")
    assert sheet.width == 400 and sheet.height > thumb.height


def _flat_map(size=48, statics=None):
    from titan.uo.map import UOMap

    blocks = (size // 8) ** 2
    land = (struct.pack("<I", 0) + struct.pack("<Hb", 3, 0) * 64) * blocks
    index = b""
    data = b""
    statics = statics or {}
    for block in range(blocks):
        recs = statics.get(block, [])
        if recs:
            index += struct.pack("<III", len(data), len(recs) * 7, 0)
            for rec in recs:
                data += struct.pack("<HBBbH", *rec)
        else:
            index += struct.pack("<III", 0xFFFFFFFF, 0, 0)
    return UOMap(land, index, data, size, size)


def _placement_tiledata():
    from titan.uo.tiledata import UOLandTile

    td = _tiledata()
    td.land = [UOLandTile(i, 0, 0, "grass") for i in range(4)]
    td.statics[0x50] = UOStaticTile(0x50, 0x40, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 20, "tree")
    return td


def test_placement_legal_area_and_tree_blocking():
    from titan.uo.placement import coverage, pack_houses, placement_legality

    td = _placement_tiledata()
    multi = _ring_multi(0x64)  # 3x3 house, border reaches +-2
    open_map = placement_legality(_flat_map(), td, multi)
    # Centres need the 5x5 border box inside the 48x48 map.
    assert open_map.legal_count == 44 * 44
    assert coverage(open_map).sum() == 46 * 46

    # A tree at (20, 20), in block (2, 2) = index 2*6+2, blocks 5x5 centres.
    treed = placement_legality(_flat_map(statics={14: [(0x50, 4, 4, 0, 0)]}), td, multi)
    assert open_map.legal_count - treed.legal_count == 25
    assert not treed.legal[20, 20] and not treed.legal[18, 22]


def test_packing_respects_yard_rule():
    from titan.uo.placement import pack_houses, placement_legality

    td = _placement_tiledata()
    result = placement_legality(_flat_map(), td, _ring_multi(0x64))
    placed = pack_houses(result, order="row")
    assert placed[0] == (2, 2)
    fp = result.footprint
    occupied = [{(x + dx, y + dy) for dx, dy in fp.occupied} for x, y in placed]
    reach = [{(x + dx, y + dy) for dx, dy in fp.occupied | fp.yard} for x, y in placed]
    for i in range(len(placed)):
        for j in range(i):
            assert not (reach[i] & occupied[j])  # later house clear of earlier ones
    # 3x3 house: yard reaches x -2..2 and y -6..6, so the next house sits
    # 4 across (x - 2 > 3) and 8 down (y - 6 > 3).
    assert placed[1] == (6, 2)
    assert (2, 10) in placed and (2, 9) not in placed


_REGIONS = """<?xml version="1.0"?>
<ServerRegions>
  <Facet name="Felucca">
    <region type="TownRegion" priority="50" name="Town">
      <zrange min="0" />
      <rect x="0" y="0" width="10" height="10" />
      <region type="FarmableWheat" name="Field">
        <rect x="0" y="0" width="2" height="2" />
      </region>
    </region>
    <region type="BaseRegion" priority="60" name="Outranks">
      <rect x="8" y="8" width="4" height="4" />
    </region>
    <region type="NoHousingRegion" priority="50" name="Smart">
      <smartNoHousing active="true" />
      <rect x="20" y="0" width="2" height="2" />
    </region>
    <region type="NoHousingRegion" priority="50" name="Plain">
      <rect x="24" y="0" width="2" height="2" />
    </region>
  </Facet>
</ServerRegions>
"""


def test_region_layers_follow_region_find(tmp_path):
    from titan.uo.placement import load_region_layers

    path = tmp_path / "Regions.xml"
    path.write_text(_REGIONS, encoding="utf-8")
    layers, counts = load_region_layers(path, "Felucca", 32, 16)
    assert [(l.z_min, l.z_max) for l in layers] == [(-128, 0), (0, 128)]
    below, ground = layers

    # The town only reaches down to z 0 (its zrange), so below that it allows.
    assert ground.blocked[5, 5] and not below.blocked[5, 5]
    # A child without its own rule inherits the town's: still forbidden.
    assert ground.blocked[1, 1]
    # A higher-priority region that allows housing wins over the town.
    assert not ground.blocked[9, 9] and ground.blocked[7, 7]
    # NoHousingRegion follows smartNoHousing; both reject a centre there.
    assert not ground.blocked[0, 20] and ground.centre[0, 20]
    assert ground.blocked[0, 24] and ground.centre[0, 24]
    assert counts["TownRegion"] == 1


def test_capacity_viewer_embeds_layers(tmp_path):
    import base64

    import numpy as np
    import io
    import json

    from PIL import Image

    from titan.uo.capacity_viewer import COVERED_BIT, write_capacity_viewer
    from titan.uo.placement import REASONS, coverage, pack_houses, placement_legality

    td = _placement_tiledata()
    facet = _flat_map(statics={14: [(0x50, 4, 4, 0, 0)]})
    result = placement_legality(facet, td, _ring_multi(0x64))
    covered = coverage(result)
    placed = pack_houses(result)
    page = write_capacity_viewer(
        tmp_path / "viewer",
        title="Test <map>",
        window=(0, 0, 48, 48),
        base_rgb=np.zeros((48, 48, 3), dtype=np.uint8),
        houses=[{"label": "Ring", "result": result, "coverage": covered, "placed": placed}],
        regions=[{"name": "Town", "type": "TownRegion", "allow": False, "no_housing": False,
                  "priority": 50, "x": 0, "y": 0, "w": 5, "h": 5}],
    )
    assert "Test &lt;map&gt;" in page.read_text(encoding="utf-8")
    data = json.loads((tmp_path / "viewer" / "data.js").read_text(encoding="utf-8")
                      .removeprefix("window.CAPACITY = ").rstrip().rstrip(";"))
    house = data["houses"][0]
    assert house["legal"] == result.legal_count and len(house["placed"]) == len(placed)
    assert [r["key"] for r in data["reasons"]] == list(REASONS)
    codes = np.asarray(Image.open(io.BytesIO(base64.b64decode(house["codes"].split(",", 1)[1]))))
    assert codes.shape == (48, 48)
    assert ((codes & COVERED_BIT) != 0).sum() == covered.sum()
    assert ((codes & 0x7F) == 0).sum() == result.legal_count
    tree_code = REASONS.index("static") + 1
    assert (codes[20, 20] & 0x7F) == tree_code


def test_mixed_packing_classes_and_conflicts():
    import numpy as np

    from titan.uo.mixed_packing import HouseKind, MixedSettings, pack_mixed, zone_distances
    from titan.uo.placement import build_placement_grids, legal_centres

    td = _placement_tiledata()
    facet = _flat_map(size=96)
    small = _ring_multi(0x64)  # 3x3 house
    grids = build_placement_grids(facet, td, window=(0, 0, 96, 96))
    centres = legal_centres(grids, small, td)
    fp = house_footprint(small, td)
    kinds = [HouseKind(0x64, "small", "small", fp), HouseKind(0x65, "big", "large", fp)]
    settings = MixedSettings(zone_size=32, seed=1, class_weights=((0, 0, 1),) * 4)
    town = np.zeros((96, 96), dtype=bool)
    town[:8, :8] = True
    rock = np.zeros((96, 96), dtype=bool)
    tdist, rdist = zone_distances((96, 96), town, rock, settings)
    assert tdist[0, 0] == 0 and tdist[-1, -1] > 0 and np.isinf(rdist).all()

    packing = pack_mixed((0, 0, 96, 96), kinds, [centres, centres], tdist, rdist, settings)
    # Every zone drew "large", so the large kind is placed first and dominates.
    assert packing.counts.get("large", 0) > 0
    assert (packing.zone_classes == 0).all()
    reach = [{(x + dx, y + dy) for dx, dy in fp.occupied | fp.yard} for x, y, _ in packing.placed]
    occ = [{(x + dx, y + dy) for dx, dy in fp.occupied} for x, y, _ in packing.placed]
    for i in range(len(occ)):
        for j in range(i):
            assert not (reach[i] & occ[j])


def test_mixed_zones_only_draw_classes_that_fit():
    import numpy as np

    from titan.uo.mixed_packing import HouseKind, MixedSettings, pack_mixed

    fp = house_footprint(_ring_multi(0x64), _tiledata())
    kinds = [HouseKind(1, "small", "small", fp), HouseKind(2, "large", "large", fp)]
    # The large kind fits only in the top-left 32x32 zone.
    small_centres = (np.array([5, 40, 70]), np.array([5, 40, 70]))
    large_centres = (np.array([5]), np.array([5]))
    settings = MixedSettings(zone_size=32, seed=3, class_weights=((0.01, 0.0, 0.99),) * 4)
    dist = np.zeros((12, 12), dtype=np.float32)
    packing = pack_mixed((0, 0, 96, 96), kinds, [small_centres, large_centres], dist,
                         np.full((12, 12), np.inf, dtype=np.float32), settings)
    classes = packing.zone_classes
    assert classes[0, 0] == 0  # "large" where a large house fits
    assert (classes.ravel()[1:] == 3).all()  # everywhere else falls to "small"
    assert sorted(k for _x, _y, k in packing.placed) == [0, 0, 1]


def test_server_profile_round_trip(tmp_path):
    from titan.uo.placement import _parse_region_rects, no_housing_region_types
    from titan.uo.server_profile import ServerProfile, build_server_profile

    regions = tmp_path / "Regions.xml"
    regions.write_text(_REGIONS, encoding="utf-8")
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "Regions.cs").write_text(
        "class GuardedRegion : BaseRegion { public override bool AllowHousing(Mobile from, Point3D p) { return false; } }\n"
        "class TownRegion : GuardedRegion { }\n"
        "class NoHousingRegion : BaseRegion { private bool m_SmartChecking;\n"
        "  public override bool AllowHousing(Mobile from, Point3D p) { return m_SmartChecking; } }\n",
        encoding="utf-8",
    )
    tool = tmp_path / "HousePlacementTool.cs"
    tool.write_text(_TOOL, encoding="utf-8")

    profile = build_server_profile(
        "Test", regions_xml=regions, scripts_dir=scripts, placement_tool=tool, source={"x": 1}
    )
    path = profile.write(tmp_path / "profile.json")
    loaded = ServerProfile.load(path)

    expected, _ = _parse_region_rects(regions, "Felucca", no_housing_region_types(scripts))
    assert loaded.region_rects("felucca") == expected
    assert loaded.region_rects("Malas") is None
    assert loaded.forbidding_types == {"TownRegion", "NoHousingRegion"}
    assert [(h.multi_id, h.offset, h.category) for h in loaded.houses] == [
        (0x64, (0, 4, 0), "ClassicHouses"),
        (0x13EC, (0, 4, 0), "TwoStoryFoundations"),
    ]
    assert loaded.source["x"] == 1 and "built" in loaded.source


def test_builtin_house_entries_from_client_multis():
    from titan.uo.server_profile import builtin_house_entries

    class _Multis:
        multis = {0x64: _ring_multi(0x64), 0x13EC: _ring_multi(0x13EC)}

    entries = builtin_house_entries(_Multis(), _tiledata())
    assert [(e.category, e.multi_id) for e in entries] == [
        ("ClassicHouses", 0x64),
        ("CustomizableFoundations", 0x13EC),
    ]
    assert entries[0].cliloc == 1011303
    assert entries[1].type_name == "3x3 customizable plot"  # 3 wide, stairs row excluded
