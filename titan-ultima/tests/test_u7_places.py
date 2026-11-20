"""titan.u7.places: bundled place data, document assembly and places-export.

The finders need retail game files, so they are not run here; these tests
cover the parts that do not: the shipped data, compaction, geometry, sign
decoding, NPC presence, the export document and the CLI's refusals.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.places import (
    assemble_document,
    available_games,
    compact_place_data,
    dump_place_data,
    load_place_data,
)
from titan.u7.places.buildings import BuildingFinds
from titan.u7.places.dungeons import DungeonFinds
from titan.u7.places.geometry import chunk_area, group_tiles, in_rects, to_rects
from titan.u7.places.npcs import presence
from titan.u7.places.signs import decode_sign_line


def test_bundled_bg_data_is_compact_and_complete():
    data = load_place_data("bg")
    assert "bg" in available_games() and "si" not in available_games()
    assert data["format"] == "titan-u7-place-data" and data["game"] == "u7-bg"
    places, regions = data["places"], data["regions"]
    ids = [p["id"] for p in places] + [r["id"] for r in regions]
    assert len(ids) == len(set(ids))
    # Only what the finders read ships: every place is on the map, and no
    # review notes, rejected guesses or dropped entries come along.
    allowed = {
        "id",
        "name",
        "type",
        "town",
        "number",
        "keeper",
        "anchor",
        "rects",
        "source",
    }
    for p in places:
        assert p["anchor"] and set(p) <= allowed, p
    for r in regions:
        assert (
            (r.get("anchor") or r.get("rects"))
            and "note" not in r
            and "placed_by" not in r
        )
    towns = [r for r in regions if r["kind"] == "town"]
    assert len(towns) == 14 and all(t["rects"] for t in towns)
    assert {"Britain", "Trinsic", "Skara Brae"} <= {t["name"] for t in towns}


def test_compact_place_data_keeps_only_placed_entries():
    profile = {
        "game": "u7-bg",
        "map": 0,
        "places": [
            {"id": "a", "name": "Inn", "type": "building", "town": "T", "number": 1,
             "keeper": None, "anchor": [5, 5], "placed_by": "sign", "rejected": [[1, 1]]},
            {"id": "b", "name": "Lost", "type": "building", "anchor": None},
            {"id": "c", "name": "Gone", "type": "area", "anchor": [9, 9], "dropped": "no"},
            {"id": "d", "name": "Home", "type": "building", "anchor": [7, 7],
             "source": "review", "note": "x", "rects": [[6, 6, 8, 8]]},
        ],
        "regions": [
            {"id": "t", "name": "Town", "kind": "town", "anchor": [1, 1], "rects": [[0, 0, 9, 9]]},
            {"id": "i", "name": "Isle", "kind": "island", "anchor": None, "rects": []},
        ],
    }  # fmt: skip
    data = compact_place_data(profile)
    assert [p["id"] for p in data["places"]] == ["a", "d"]
    assert data["places"][0] == {
        "id": "a", "name": "Inn", "type": "building", "town": "T", "number": 1, "anchor": [5, 5],
    }  # fmt: skip
    assert data["places"][1]["source"] == "review" and "note" not in data["places"][1]
    assert [r["id"] for r in data["regions"]] == ["t"]
    assert json.loads(dump_place_data(data)) == data


def test_geometry_helpers():
    tiles = {(0, 0), (1, 0), (0, 1), (1, 1), (5, 5)}
    groups = sorted(sorted(g) for g in group_tiles(tiles))
    assert groups == [[(0, 0), (0, 1), (1, 0), (1, 1)], [(5, 5)]]
    assert to_rects(groups[0]) == [(0, 0, 1, 1)]
    assert to_rects([(0, 0), (1, 0), (0, 1)]) == [(0, 0, 1, 0), (0, 1, 0, 1)]
    assert chunk_area((1, 2, 1, 2)) == (16, 32, 31, 47)
    assert in_rects(3, 3, [[0, 0, 3, 3]]) and not in_rects(4, 3, [[0, 0, 3, 3]])


def test_runic_sign_lines_decode():
    assert decode_sign_line("BLUE BOAR") == ("BLUE BOAR", False)
    text, runic = decode_sign_line("*e|bl+ ")
    assert runic and text == "Nge Blea"


def test_npc_presence_marks_start_sleep_and_work():
    npcs = [
        {"num": 1, "name": "Iolo", "start": (5, 5, 0),
         "schedule": [(0, "sleep", 5, 5, 0), (9, "tend_shop", 50, 50, 0)]},
    ]  # fmt: skip
    found = presence(npcs, lambda tx, ty: 0 if tx < 10 else 1, 2)
    home, shop = found[0][0], found[1][0]
    assert home["starts_here"] and home["sleeps_here"] and not home["works_here"]
    assert shop["works_here"] and not shop["starts_here"]


def _building(id_, name, places, center, source="official"):
    return {
        "id": id_, "name": name, "name_source": source, "places": places,
        "sign_name": None, "bbox": {"tx0": 0, "ty0": 0, "tx1": 9, "ty1": 9},
        "center": center, "tile_count": 100, "rects": [[0, 0, 9, 9]],
        "roof_kind": "pitched", "rooms": 1, "confidence": "high", "flags": [],
        "doors": [{"tx": 1, "ty": 1, "tz": 0, "shape": 1, "frame": 0,
                   "name": "door", "kind": "outside", "source": "ireg"}],
        "signs": [], "npcs_at_start": [], "zones": [],
    }  # fmt: skip


def test_assemble_document_towns_footprints_and_areas():
    data = {
        "game": "u7-bg",
        "places": [
            {"id": "t-01", "name": "Shop", "town": "Townsville", "anchor": [5, 5],
             "rects": [[0, 0, 4, 9]]},
            {"id": "review-x", "name": "Home", "anchor": [7, 5], "source": "review",
             "rects": [[5, 0, 9, 9]]},
        ],
        "regions": [
            {"id": "town-x", "name": "Townsville", "kind": "town", "rects": [[0, 0, 99, 99]]},
            {"id": "cave", "name": "Cave", "kind": "dungeon", "anchor": [500, 500]},
        ],
    }  # fmt: skip
    finds = BuildingFinds(
        records=[
            _building("b1", "Shop", [{"id": "t-01", "town": "Townsville", "number": 1,
                                      "name": "Shop", "keeper": None},
                                     {"id": "review-x", "town": None, "number": None,
                                      "name": "Home", "keeper": None}], [5.0, 5.0]),
            _building("b2", "Barn", [], [500.0, 500.0], source="sign"),
            _building("b3", "Shed", [], [50.0, 50.0], source="sign"),
        ],
        places_other=[
            {"status": "footprint", "id": "t-02", "name": "Ruin", "town": "Townsville",
             "number": 2, "anchor": [20, 20], "rects": [[16, 16, 31, 31]]},
            {"status": "area", "id": "t-03", "name": "Docks", "town": None,
             "anchor": [60, 60], "rects": [[56, 56, 63, 63]]},
        ],
    )  # fmt: skip
    dungeons = DungeonFinds(records=[{
        "id": "d1", "name": "Cave", "name_source": "official", "region": "cave",
        "bbox": {"tx0": 490, "ty0": 490, "tx1": 510, "ty1": 510}, "center": [500.0, 500.0],
        "tile_count": 400, "rects": [[490, 490, 510, 510]], "entrances": [], "floor": {},
        "doors": 2, "signs": [], "npcs_at_start": [], "zones": [],
    }])  # fmt: skip
    npcs = [{"num": 7, "name": "Ghost", "start": (20, 20, 0), "schedule": []}]
    scan = SimpleNamespace(game="bg", map_num=0, npcs=npcs)

    doc = assemble_document(scan, data, finds, dungeons)

    assert doc["format"] == "titan-u7-places" and doc["counts"]["buildings"] == 4
    by_id = {b["id"]: b for b in doc["buildings"]}
    shop = by_id["b1"]
    assert shop["town"] == "Townsville" and shop["detected"]
    # A building shared by two places carries each place's own part.
    assert [p.get("rects") for p in shop["places"]] == [[[0, 0, 4, 9]], [[5, 0, 9, 9]]]
    assert "keeper" not in shop["places"][0]
    assert shop["doors"] == [
        {"tx": 1, "ty": 1, "tz": 0, "kind": "outside", "name": "door"}
    ]
    assert by_id["b2"]["town"] is None and by_id["b3"]["town"] == "Townsville"
    ruin = by_id["t-02"]
    assert not ruin["detected"] and ruin["flags"] == ["hand_drawn"]
    assert ruin["bbox"] == [16, 16, 31, 31] and ruin["center"] == [23.5, 23.5]
    assert [n["name"] for n in ruin["npcs_at_start"]] == ["Ghost"]
    assert doc["areas"] == [
        {"id": "t-03", "name": "Docks", "town": "Townsville", "anchor": [60, 60],
         "rects": [[56, 56, 63, 63]]}
    ]  # fmt: skip
    assert doc["dungeons"][0]["door_count"] == 2 and doc["dungeons"][0]["town"] is None
    assert doc["towns"] == [
        {"id": "town-x", "name": "Townsville", "rects": [[0, 0, 99, 99]]}
    ]


def test_places_export_cli_refuses_games_without_data(tmp_path):
    out = tmp_path / "si.json"
    result = CliRunner().invoke(
        u7_app, ["places-export", "--game", "si", "-o", str(out)]
    )
    assert result.exit_code == 1 and not out.exists()
    assert "No place data for --game si" in result.output


def test_places_export_cli_needs_an_output_file():
    result = CliRunner().invoke(u7_app, ["places-export"])
    assert result.exit_code != 0
    assert "places-export" in CliRunner().invoke(u7_app, ["--help"]).output


def test_places_export_cli_reports_a_missing_static_dir(tmp_path):
    out = tmp_path / "bg.json"
    result = CliRunner().invoke(
        u7_app, ["places-export", str(tmp_path / "nope"), "-o", str(out)]
    )
    assert result.exit_code == 1 and not out.exists()
    assert "STATIC directory not found" in result.output
