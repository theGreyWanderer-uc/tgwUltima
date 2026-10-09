"""Shared native-identity navigation, independent search predicates and export scopes."""

import json

import pytest
from typer.testing import CliRunner

from titan import _inventory_browser as flow
from titan.u8 import container_browser_ui as menus
from titan.u8.cli import u8_app
from titan.u8.container_browser import export_u8_container_bundle
from tests.test_u8_container_browser import inventory as inventory, session
from tests.test_u8_npc_animation_report import case as case


@pytest.fixture
def browser(inventory, tmp_path):
    data = session(inventory)
    return menus._u8_inventory_flow(data, tmp_path / "exports", tmp_path / "previews")


def test_direct_contents_filter_finds_holder_any_depth_finds_ancestors(browser):
    browser.filters = flow.InventoryFilters(contains_shapes=(2,))
    assert browser.results() == [1, 300]
    assert browser.matching_items(1)[0]["path"].count(" > ") == 2
    browser.filters.direct = True
    assert browser.results() == [300]
    browser.filters.name = "unmatched"
    assert browser.results() == []


def test_independent_predicates_require_the_same_matching_child(browser):
    row = browser.items[301]
    row["item_name"] = "coins"
    browser.filters = flow.InventoryFilters(
        name=flow.inventory_name(browser.items[300]),
        shapes=(3,),
        contains_name="coins",
        contains_shapes=(5,),
    )
    assert browser.results() == []  # quantity shape 5 is a different child
    browser.filters.contains_shapes = (2,)
    assert browser.results() == [300]
    browser.filters.owner = "Mordea"
    assert browser.results() == []


def test_cycle_and_repeated_shape_breadcrumbs_keep_distinct_native_ids(browser):
    browser.items[300]["item_name"] = browser.items[1]["item_name"] = "Backpack"
    browser.items[1]["npc_label"] = ""
    assert (
        flow.inventory_breadcrumb(browser.items, 300) == "Backpack [1] > Backpack [300]"
    )
    browser.children[301] = [1]
    assert [row["item_id"] for row in browser.descendants(1)] == [300, 306, 301, 302]
    browser.items[1]["container_id"] = 300
    assert "[300]" in flow.inventory_breadcrumb(browser.items, 1)


def test_compact_details_tree_and_explicit_raw_record(browser, monkeypatch, capsys):
    answers = iter(["T", "B"])
    browser.menu = lambda *args, **kwargs: next(answers)
    browser.inspect(300)
    output = capsys.readouterr().out
    assert "2 direct / 2 nested total" in output
    assert "├─" in output and "×42" in output
    assert '"frame_low"' not in output
    answers = iter(["D", "B"])
    browser.inspect(300)
    assert '"frame_low"' in capsys.readouterr().out


def test_invalid_filter_preserves_previous_value_and_reset_clears_search(
    browser, monkeypatch, capsys
):
    browser.filters.map_id = 3
    answers = iter(["M", "B"])
    browser.menu = lambda *args, **kwargs: next(answers)
    monkeypatch.setattr(flow.ui, "text", lambda *args: "256")
    browser.edit_filters()
    assert browser.filters.map_id == 3
    assert "Filter unchanged" in capsys.readouterr().out
    browser.filters.query = "coins"
    answers = iter(["R", "B"])
    browser.edit_filters()
    assert browser.filters == flow.InventoryFilters()


def test_result_page_survives_inventory_and_preview_return(browser):
    for number in range(10000, 10028):
        browser.items[number] = dict(browser.items[303], item_id=number)
        browser.containers.append(number)
    prompts = []
    answers = iter(["N", "10027", "B", "Q"])

    def menu(title, labels, *args):
        prompts.append((title, labels))
        return next(answers)

    browser.menu = menu
    browser.browse()
    lists = [labels for title, labels in prompts if title == "Choose container:"]
    assert "10027" in lists[-1] and "P" in lists[-1]


def test_current_results_and_all_exports_are_distinct_and_record_scope(
    browser, tmp_path
):
    browser.filters = flow.InventoryFilters(kind="npc", query="Mordea")
    answers = iter(["E", "R", "E", "A", "Q"])
    browser.menu = lambda *args, **kwargs: next(answers)
    browser.browse()
    current = json.loads(
        next((tmp_path / "exports").glob("*current_results/inventory.json")).read_text()
    )
    complete = json.loads(
        next((tmp_path / "exports").glob("*_all/inventory.json")).read_text()
    )
    assert [row["item_id"] for row in current["containers"]] == [7]
    assert current["orphaned_items"] == []
    assert current["selection"]["filters"]["kind"] == "npc"
    assert [row["item_id"] for row in complete["containers"]] == [1, 7, 300, 303]


def test_empty_selection_and_mutually_exclusive_export_scope(inventory, tmp_path):
    data = session(inventory)
    report = export_u8_container_bundle(
        data, tmp_path / "empty", containers=[], selection={"scope": "current_results"}
    )
    assert (
        json.loads((report.parent / "inventory.json").read_text())["containers"] == []
    )
    with pytest.raises(ValueError, match="one inventory"):
        export_u8_container_bundle(data, tmp_path / "bad", container=1, containers=[1])


def test_real_u8_cli_refined_filters_and_export_scope(inventory, tmp_path):
    static, gamedat = inventory
    result = CliRunner().invoke(
        u8_app,
        [
            "container-browse",
            str(gamedat),
            "--shapes",
            str(static / "U8SHAPES.FLX"),
            "-o",
            str(tmp_path / "reports"),
        ],
        input="F\nI\n2\nD\nB\nE\nR\n300\nT\nD\nB\nQ\n",
    )
    assert result.exit_code == 0, result.stdout
    report = json.loads(
        next((tmp_path / "reports").rglob("inventory.json")).read_text()
    )
    assert [row["item_id"] for row in report["containers"]] == [300]
    assert "Complete native record" in result.stdout and "Match:" in result.stdout
