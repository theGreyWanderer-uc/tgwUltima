"""U7 map inventory: chunk-template expansion, fixed and movable objects, outputs."""

import csv
import json
import struct

from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.map_inventory import build_u7_map_inventory, write_u7_map_inventory


def _cell(shape: int, frame: int) -> bytes:
    return bytes([shape & 0xFF, ((shape >> 8) & 0x03) | (frame << 2)])


def _write_world(static):
    static.mkdir(parents=True)
    # Two chunk templates: 0 is all grass (flat 5:0); 1 is grass with a
    # wall (object 150:2) at cell (3, 4) and a flat 6:1 at cell (0, 0).
    grass = _cell(5, 0) * 256
    template1 = bytearray(grass)
    template1[0:2] = _cell(6, 1)
    index = 4 * 16 + 3
    template1[index * 2 : index * 2 + 2] = _cell(150, 2)
    (static / "U7CHUNKS").write_bytes(grass + bytes(template1))
    # U7MAP: every chunk uses template 0 except three chunks in superchunk 0.
    u7map = bytearray(144 * 256 * 2)
    for chunk in (0, 1, 17):  # (0,0), (1,0), (1,1) of superchunk 0
        struct.pack_into("<H", u7map, chunk * 2, 1)
    (static / "U7MAP").write_bytes(bytes(u7map))

    tfa = bytearray(3 * 1024)
    tfa[150 * 3 : 150 * 3 + 3] = bytes([8 | (5 << 5), 0, 3 << 3])  # solid, z 5, 1x4
    tfa[151 * 3 : 151 * 3 + 3] = bytes([0, 6, 0])  # container
    (static / "TFA.DAT").write_bytes(tfa + bytes(512))
    names = U7FlexArchive()
    names.records = [b""] * 1024
    names.records[5] = b"grass\x00"
    names.records[150] = b"wall\x00"
    names.records[151] = b"chest\x00"
    (static / "TEXT.FLX").write_bytes(names.to_bytes())

    # Fixed objects: two walls in superchunk 1.
    ifix = U7FlexArchive()
    ifix.records = [b""] * 256
    ifix.records[0] = bytes([(2 << 4) | 3, 5, 150, 2 << 2]) + bytes([(4 << 4) | 4, 0, 150, 7 << 2])
    for sc in range(144):
        archive = ifix if sc == 1 else U7FlexArchive()
        if sc != 1:
            archive.records = [b""] * 256
        (static / f"U7IFIX{sc:02X}").write_bytes(archive.to_bytes())
    return static


def test_inventory_counts_templates_fixed_objects_and_coverage(tmp_path):
    static = _write_world(tmp_path / "STATIC")
    inv = build_u7_map_inventory(str(static), include_ireg=False)

    wall = inv.rows[(150, 2)]
    # Three chunks use template 1 (one wall each) plus one fixed wall.
    assert wall.counts["chunk"] == 3 and wall.counts["ifix"] == 1
    assert wall.placements == 4
    assert wall.lifts[5] == 1 and wall.lifts[0] == 3
    assert inv.rows[(150, 7)].counts["ifix"] == 1

    flat = inv.rows[(5, 0)]
    assert flat.counts["terrain"] == 192 * 192 * 256 - 3 * 2  # minus wall and 6:1 cells
    assert inv.rows[(6, 1)].counts["terrain"] == 3
    assert inv.name(150, 2) == "wall"

    summary = write_u7_map_inventory(inv, tmp_path / "out", previews=False)
    assert summary["objects"]["placements"] == 5
    assert summary["objects"]["by_source"] == {"chunk": 3, "ifix": 2, "ireg": 0}
    assert summary["flats"]["cells"] == 192 * 192 * 256 - 3
    rows = list(csv.DictReader(open(tmp_path / "out" / "objects.csv", encoding="utf-8")))
    assert [(r["shape"], r["frame"], r["placements"]) for r in rows] == [("150", "2", "4"), ("150", "7", "1")]
    assert rows[0]["dims_y"] == "4" and rows[0]["dims_z"] == "5" and rows[-1]["cumulative_pct"] == "100.0"
    shapes = list(csv.DictReader(open(tmp_path / "out" / "shapes.csv", encoding="utf-8")))
    wall_shape = next(s for s in shapes if s["shape"] == "150")
    assert wall_shape["frames_used"] == "2" and wall_shape["placements"] == "5"


def test_inventory_reads_movable_objects_from_initgame(tmp_path):
    static = _write_world(tmp_path / "STATIC")
    # INITGAME.DAT as a U7 Flex with named entries is complex to build here;
    # a GAMEDAT folder exercises the same u7ireg decoding path.
    gamedat = tmp_path / "gamedat"
    gamedat.mkdir()
    # One plain 6-byte IREG entry: length 6, x/y, shape 151 frame 0, lift/quality.
    entry = bytes([6, 0x12, 0x34, 151 & 0xFF, (151 >> 8) & 3, 0, 0])
    (gamedat / "u7ireg00").write_bytes(entry)
    inv = build_u7_map_inventory(str(static), gamedat_dir=str(gamedat))
    assert inv.rows[(151, 0)].counts["ireg"] == 1
    assert "GAMEDAT" in inv.sources["ireg"]


def test_cli_writes_inventory(tmp_path, monkeypatch):
    static = _write_world(tmp_path / "STATIC")
    import titan.u7.cli as cli

    monkeypatch.setattr(cli, "_resolve_u7_paths", lambda game: (None, None))
    out = tmp_path / "inv"
    result = CliRunner().invoke(u7_app, ["map-inventory", str(static), "--no-ireg", "--no-previews", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "Objects: 5 placements" in result.output
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["objects"]["shapes"] == 1


def test_area_limits_counts_and_lists_placements(tmp_path):
    from titan.u7.map_inventory import chunk_rect, superchunk_rect

    static = _write_world(tmp_path / "STATIC")
    inv = build_u7_map_inventory(str(static), include_ireg=False, area=[chunk_rect(0, 0, 0, 0)])
    # Chunk (0, 0) uses template 1: one wall at (3, 4), the rest ground.
    assert inv.rows[(150, 2)].placements == 1
    assert inv.rows[(5, 0)].counts["terrain"] == 256 - 2 and inv.rows[(6, 1)].counts["terrain"] == 1
    assert (150, 7) not in inv.rows  # fixed walls are in superchunk 1
    assert len(inv.placements) == 256

    summary = write_u7_map_inventory(inv, tmp_path / "out", previews=False)
    assert summary["area"] == [[0, 0, 15, 15]]
    listed = list(csv.DictReader(open(tmp_path / "out" / "placements.csv", encoding="utf-8")))
    wall = [r for r in listed if r["kind"] == "object"]
    assert [(r["source"], r["shape"], r["tx"], r["ty"], r["dims_y"]) for r in wall] == [("chunk", "150", "3", "4", "4")]

    fixed = build_u7_map_inventory(str(static), include_ireg=False, area=[superchunk_rect(1)])
    assert fixed.rows[(150, 2)].counts["ifix"] == 1 and fixed.rows[(150, 7)].counts["ifix"] == 1


def test_area_counts_objects_whose_footprint_reaches_in(tmp_path):
    static = _write_world(tmp_path / "STATIC")
    # The 1x4 wall anchored at (3, 4) covers tiles y 1-4.
    reach = build_u7_map_inventory(str(static), include_ireg=False, area=[(3, 1, 3, 1)])
    assert reach.rows[(150, 2)].placements == 1
    clear = build_u7_map_inventory(str(static), include_ireg=False, area=[(3, 0, 3, 0)])
    assert (150, 2) not in clear.rows


def test_cli_area_options_name_the_output(tmp_path, monkeypatch):
    static = _write_world(tmp_path / "STATIC")
    import titan.u7.cli as cli

    monkeypatch.setattr(cli, "_resolve_u7_paths", lambda game: (None, None))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        u7_app, ["map-inventory", str(static), "--no-ireg", "--no-previews", "--cx0", "0", "--cy0", "0"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "u7data" / "map-inventory" / "bg-map00-c0_0_0_0" / "placements.csv").is_file()
    bad = CliRunner().invoke(u7_app, ["map-inventory", str(static), "--sc", "0x90"])
    assert bad.exit_code == 1
