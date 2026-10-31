"""Native U7 IREG capture, repeated containers and shared fresh-report workflow."""

import csv
from pathlib import Path

import pytest
from PIL import Image

from titan._inventory_browser import inventory_descendants
from titan.u7 import container_browser as browser
from titan.u7.container import browse_containers, ContainerQueryParams, format_tree
from titan.u7.flex import U7FlexArchive
from titan.u7.world import WorldQueryParams
from tests.test_u7_ireg import _container_payload, _simple_payload


@pytest.fixture
def world(tmp_path):
    static, gamedat = tmp_path / "STATIC", tmp_path / "GAMEDAT"
    static.mkdir()
    gamedat.mkdir()
    flags = bytearray(3584)
    for shape in (522, 801):
        flags[shape * 3 + 1] = 6
    flags[100 * 3 + 1] = 3
    (static / "TFA.DAT").write_bytes(flags)
    names = U7FlexArchive()
    names.records = [b""] * 802
    for shape, name in ((522, "Chest"), (801, "Bag"), (100, "Coins")):
        names.records[shape] = (name + "\0").encode()
    (static / "TEXT.FLX").write_bytes(names.to_bytes())

    def box(shape, contents):
        return (
            bytes([12])
            + _container_payload(0, 0, shape=shape, has_children=bool(contents))
            + contents
            + (b"\x01" if contents else b"")
        )

    coin = bytes([6]) + _simple_payload(42, shape=100)
    (gamedat / "u7ireg00").write_bytes(box(522, box(801, coin) + box(801, b"")))
    return WorldQueryParams(str(static), str(gamedat))


def test_capture_distinguishes_repeated_bags_and_keeps_empty_nested_inventory(world):
    data = browser.load_u7_container_session(world)
    assert len(data.containers) == 3
    root, bag, empty_bag = data.containers
    assert root.endswith("root") and bag != empty_bag
    rows = inventory_descendants(data.items, data.children, root)
    assert [row["shape"] for row in rows] == [801, 100, 801]
    assert rows[1]["quantity"] == 42
    assert data.children[root] == [bag, empty_bag]
    assert rows[1]["path"] == "Chest > Bag > Coins"


def test_captured_ireg_browsing_does_not_reread_save(
    world, tmp_path, monkeypatch, capsys
):
    data = browser.load_u7_container_session(world)
    (Path(world.gamedat_dir) / "u7ireg00").write_bytes(b"changed after capture")
    answers = iter(["T", "Q"])
    monkeypatch.setattr(
        "titan._inventory_browser.inventory_menu", lambda *args: next(answers)
    )
    # Dataclass menu defaults retain the original function; intercept its shared prompt.
    monkeypatch.setattr(
        "titan._inventory_browser.ui.choice", lambda *args, **kwargs: next(answers)
    )
    browser.browse_u7_container_session(data, output=tmp_path / "exports")
    assert "Coins" in capsys.readouterr().out


def test_batch_tree_contains_queries_remain_compatible(world):
    params = ContainerQueryParams(
        world.static_dir, world.gamedat_dir, contains_shape_nums=[100]
    )
    results = browse_containers(params)
    assert len(results) == 1 and results[0].obj.shape == 801
    assert results[0].is_nested
    assert "inside" in format_tree(results, None)


def test_fresh_u7_reports_have_native_sprite_links_paths_and_preserve_inputs(
    world, tmp_path, monkeypatch
):
    data = browser.load_u7_container_session(world)
    before = {path: path.read_bytes() for path in data.source_files}
    monkeypatch.setattr(
        browser,
        "u7_container_item_image",
        lambda *args, **kwargs: Image.new("RGBA", (4, 3), "red"),
    )
    output = tmp_path / "reports"
    report = browser.export_u7_container_bundle(
        data, output, numbers=data.containers, selection={"scope": "all"}
    )
    assert len(list((output / "containers").glob("*.html"))) == 3
    assert len(list((output / "images").glob("*.png"))) == 4
    with (output / "contents.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert any(row["path"] == "Chest > Bag > Coins" for row in rows)
    assert "×42" in (output / "tree.txt").read_text(encoding="utf-8")
    before_report = report.read_bytes()
    with pytest.raises(ValueError, match="new directory"):
        browser.export_u7_container_bundle(
            data, output, numbers=data.containers, selection={"scope": "all"}
        )
    assert report.read_bytes() == before_report
    assert all(path.read_bytes() == content for path, content in before.items())


def test_u7_export_rejects_input_folders_and_invalid_inventory(world):
    data = browser.load_u7_container_session(world)
    with pytest.raises(ValueError, match="input folders"):
        browser.validate_u7_container_output(data, Path(world.gamedat_dir) / "reports")
    with pytest.raises(ValueError, match="not an inventory"):
        browser.export_u7_container_bundle(
            data,
            Path(world.gamedat_dir).parent / "bad",
            numbers=["missing"],
            selection={},
        )
