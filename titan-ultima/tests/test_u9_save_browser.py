"""U9 browser policy, custody, preserving exports and portable wording contracts."""

from __future__ import annotations

import json
import struct
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from titan import _wizard_ui as ui
from titan.u9.cli import u9_app
from titan.u9.integrity import (
    IntegrityReport,
    RECOMMENDATIONS,
    check_save,
    check_save_archive,
)
from titan.u9.save_backup import backup_u9_save
from titan.u9.save_browser import (
    U9_SAVE_BROWSER_VIEWS,
    build_u9_save_browser_report,
    describe_u9_save_browser_view,
    discover_u9_save_archives,
    export_u9_save_browser_bundle,
    extract_u9_save_browser_archive,
    filter_u9_save_browser_rows,
    open_u9_save_browser_session,
)
from titan.u9 import save_browser_ui as browser
from titan.u9.save_wording import (
    describe_u9_browser_map,
    describe_u9_save_integrity,
    fill_u9_save_wording,
    load_u9_region_catalogue,
    load_u9_save_wording,
    render_u9_plain_integrity,
    validate_u9_save_wording,
)
from tests.test_u9_integrity import _archive, _fixed, _nonfixed, _processes
from tests.test_u9_process_sections import _sections


@pytest.fixture
def save_install(tmp_path):
    root = tmp_path / "game"
    save, static, reference = (
        root / "savegame",
        root / "static",
        tmp_path / "original_maps",
    )
    for folder in (save, static, reference):
        folder.mkdir(parents=True)
    processes, nonfixed = _processes(), _nonfixed()
    (save / "start.dat").write_bytes(b"U9.008" + struct.pack("<i", 4))
    (save / "u9game4.sav").write_bytes(_archive(processes, nonfixed))
    (save / "processes.dat").write_bytes(processes)
    (save / "nonfixed.9").write_bytes(nonfixed)
    (save / "diary.txt").write_bytes(b"A journal")
    (static / "fixed.9").write_bytes(_fixed())
    (reference / "fixed.9").write_bytes(_fixed())
    return root, save, static, reference


def session_for(save_install, tmp_path, *, archive_only=False, reference=True):
    root, save, static, original = save_install
    return open_u9_save_browser_session(
        save / "u9game4.sav" if archive_only else root,
        static_directory=static,
        fixed_reference_directory=original if reference else None,
        output=tmp_path / "out",
    )


def test_missing_selector_has_neutral_presentation_and_preserves_diagnostic(
    save_install,
):
    root, save, _, reference = save_install
    (save / "start.dat").unlink()
    report = check_save(root, fixed_reference_directory=reference)
    assert report.no_save_selected and report.overall == "FATAL"
    assert report.findings[0].check_id == "SEL01"
    plain = describe_u9_save_integrity(report)
    assert plain["summary"]["result"] == "NO_SAVE_SELECTED"
    assert plain["summary"]["title"] == "No save selected"
    assert plain["cards"] == [] and plain["axes"] == {}
    assert plain["actions"] == ["choose_save"]
    assert report.to_dict()["no_save_selected"] is True
    (save / "start.dat").write_bytes(b"damaged")
    assert not check_save(root).no_save_selected
    assert not check_save(root, slot=99).no_save_selected


def test_missing_save_folder_keeps_explicit_slot(save_install):
    root, save, _, reference = save_install
    for file in save.iterdir():
        file.unlink()
    save.rmdir()
    assert check_save(root).no_save_selected
    report = check_save(root, slot=4, fixed_reference_directory=reference)
    assert report.slot == 4 and not report.no_save_selected
    assert report.findings[0].details["slot"] == 4


def test_self_comparison_is_hidden_only_in_plain_view(save_install):
    root, _, static, _ = save_install
    report = check_save(root, fixed_reference_directory=static)
    plain = describe_u9_save_integrity(report)
    assert report.self_reference and report.overall == "PASS"
    assert not any(card["check_id"] == "LAY01" for card in plain["cards"])
    assert "compared with themselves" in plain["notes"][0]
    assert any(
        finding["check_id"] == "LAY01" for finding in report.to_dict()["findings"]
    )
    assert "LAY01" in browser.render_integrity_report(report)


def test_missing_reference_is_a_note_without_raising_any_verdict(save_install):
    root, _, static, _ = save_install
    report = check_save(root)
    assert report.overall == report.verdict("compatibility") == "PASS"
    plain = describe_u9_save_integrity(report)
    (card,) = plain["cards"]
    assert plain["summary"]["title"] == "No problems found"
    assert card["key"] == "LAY04/WARN" and card["display_kind"] == "note"
    assert card["affects_verdict"] is False
    (finding,) = [f for f in report.to_dict()["findings"] if f["check_id"] == "LAY04"]
    assert finding["severity"] == "WARN" and finding["affects_verdict"] is False
    rendered = browser.render_integrity_report(report)
    assert "Problems (0)\n  None" in rendered and "Comparison notes (1)" in rendered
    assert "Note: Original map layout" in render_u9_plain_integrity(plain)
    assert check_save(root, fixed_reference_directory=static).overall == report.overall


@pytest.mark.parametrize(
    "problem,expected",
    [("difference", "ERROR"), ("missing", "FATAL"), ("size", "WARN")],
)
def test_optional_reference_note_does_not_hide_real_problems(
    save_install, problem, expected
):
    root, save, static, reference = save_install
    if problem == "difference":
        original = bytearray((reference / "fixed.9").read_bytes())
        original[-1] ^= 1
        (reference / "fixed.9").write_bytes(original)
        report = check_save(root, fixed_reference_directory=reference)
    elif problem == "missing":
        (static / "fixed.9").unlink()
        report = check_save(root)
    else:
        mismatched = bytearray(_nonfixed())
        struct.pack_into("<I", mismatched, 0x0C, 4096)
        (save / "nonfixed.9").write_bytes(mismatched)
        (save / "u9game4.sav").write_bytes(_archive(_processes(), bytes(mismatched)))
        report = check_save(root)
    assert report.overall == expected
    assert describe_u9_save_integrity(report)["summary"]["result"] == expected


def test_historical_archives_do_not_check_current_loose_files(save_install):
    root, save, static, reference = save_install
    (save / "processes.dat").write_bytes(b"another slot's state")
    (save / "nonfixed.9").write_bytes(b"damaged working map")
    report = check_save_archive(
        save / "u9game4.sav",
        static_directory=static,
        fixed_reference_directory=reference,
    )
    assert report.overall == "PASS" and report.verdict("custody") == "N/A"
    assert not report.custody_applicable
    assert not any(finding.check_id.startswith("CUS") for finding in report.findings)
    assert check_save(root, fixed_reference_directory=reference).overall == "FATAL"


def test_unreadable_historical_archive_is_fatal_despite_custody_not_applicable(
    save_install,
):
    _, save, static, _ = save_install
    archive = save / "u9game98.sav"
    archive.write_bytes(b"bad")
    report = check_save_archive(archive, static_directory=static)
    assert report.overall == "FATAL" and report.verdict("custody") == "N/A"
    assert report.verdict("structure") == "FATAL"
    assert describe_u9_save_integrity(report)["cards"][0]["key"] == "ARC01/FATAL"


@pytest.mark.parametrize("unreadable", ["fixed", "working", "reference"])
def test_unreadable_map_files_remain_reportable(save_install, monkeypatch, unreadable):
    root, save, static, reference = save_install
    target = {
        "fixed": static / "fixed.9",
        "working": save / "nonfixed.9",
        "reference": reference / "fixed.9",
    }[unreadable]
    original = type(target).read_bytes

    def read_bytes(path):
        if path == target:
            raise PermissionError("Unreadable test file")
        return original(path)

    monkeypatch.setattr(type(target), "read_bytes", read_bytes)
    report = check_save(root, fixed_reference_directory=reference)
    assert report.overall == ("PASS" if unreadable == "reference" else "FATAL")
    plain = describe_u9_save_integrity(report)
    assert plain["summary"]["result"] == report.overall
    assert any(
        "Unreadable test file" in finding.message
        or finding.details.get("read_error") == "Unreadable test file"
        for finding in report.findings
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_refresh_rereads_selection_unless_slot_was_explicit(
    save_install, tmp_path, monkeypatch, explicit
):
    root, save, static, reference = save_install
    session = open_u9_save_browser_session(
        root,
        slot=4 if explicit else None,
        static_directory=static,
        fixed_reference_directory=reference,
        output=tmp_path / "out",
    )
    (save / "u9game2.sav").write_bytes((save / "u9game4.sav").read_bytes())
    (save / "start.dat").write_bytes(b"U9.008" + struct.pack("<i", 2))
    real_open = browser.open_u9_save_browser_session
    refreshed = []

    def reopen(*args, **kwargs):
        result = real_open(*args, **kwargs)
        refreshed.append(result)
        return result

    menus = iter(["U", "Q"])
    monkeypatch.setattr(browser, "_menu", lambda *args: next(menus))
    monkeypatch.setattr(browser, "open_u9_save_browser_session", reopen)
    assert browser._browse_u9_save_session(session) == "Q"
    assert refreshed[0].report.slot == (4 if explicit else 2)


@pytest.mark.parametrize("case_name", ["healthy_slot_4", "broken_slot_631", "f14"])
@pytest.mark.parametrize("group", ["cases", "self_reference_cases"])
def test_portable_known_save_expectations_replay_from_structured_details(
    case_name, group
):
    from titan.u9.save_wording import RESOURCE_DIRECTORY

    case = json.loads(
        (RESOURCE_DIRECTORY / "save_browser_examples.json").read_text(encoding="utf-8")
    )[group][case_name]
    report = IntegrityReport(
        target="test",
        slot=case["slot"],
        custody_applicable=False,
        self_reference=case.get("self_reference", False),
    )
    for card in case["cards"]:
        for context in card["contexts"]:
            report.add(
                card["check_id"],
                "structure",
                card["severity"],
                "Technical message is deliberately irrelevant",
                affects_verdict=card["affects_verdict"],
                **context,
            )
    plain = describe_u9_save_integrity(report)
    assert plain["summary"] == case["summary"]
    assert plain["actions"] == case["actions"]
    assert render_u9_plain_integrity(plain) == case["plain_text"]
    for actual, expected in zip(plain["cards"], case["cards"]):
        assert {
            key: value for key, value in actual.items() if key != "paths"
        } == expected


@pytest.mark.parametrize(
    "check_id", ["ARC10", "CUS04", "NFS01", "NFS07", "PRC02", "REF07"]
)
def test_warning_cards_offer_player_recovery_path_and_obey_loading_prohibition(
    check_id,
):
    report = IntegrityReport("fixture", slot=4)
    report.add(
        check_id, "structure", "WARN", "technical", declared=4096, actual=0, maps=[9]
    )
    (card,) = describe_u9_save_integrity(report)["cards"]
    assert "Keep a backup, then try loading" in card["what_to_do"]
    assert "things are missing or out of place" in card["what_to_do"]
    assert "an older save and save a report to share" in card["what_to_do"]
    assert card["load_policy"] == "try_after_backup"
    assert card["actions"] == ["backup", "try_load", "load_older_save", "send_report"]
    report.add("NFS01", "structure", "FATAL", "unreadable", maps=[9])
    blocked = next(
        card
        for card in describe_u9_save_integrity(report)["cards"]
        if card["key"] == f"{check_id}/WARN"
    )
    assert "try loading" not in blocked["what_to_do"]
    assert "before loading this save" in blocked["what_to_do"]
    assert (
        blocked["load_policy"] == "do_not_load" and "try_load" not in blocked["actions"]
    )


@pytest.mark.parametrize(
    "change",
    [
        {"requires_explicit_activation": False},
        {"automatic_launch_allowed": True},
        {"allowed_overall_results": ["PASS", "WARN", "ERROR"]},
        {"allowed_overall_results": ["PASS", "WARN", "FATAL"]},
    ],
)
def test_try_load_contract_requires_explicit_safe_activation(change):
    catalog = json.loads(json.dumps(load_u9_save_wording()))
    assert catalog["actions"]["try_load"]["launch_on_activation_allowed"] is True
    catalog["actions"]["try_load"].update(change)
    with pytest.raises(ValueError, match="unsafe try_load"):
        validate_u9_save_wording(catalog)


def test_player_map_names_preserve_catalogue_identity_and_classification():
    for number, stored, player in [
        (0, "The Lunch Room", "Setup area"),
        (14, "Avatar's House Earth", "Avatar's home"),
        (41, "Stonegate Fix", "Stonegate"),
    ]:
        record = describe_u9_browser_map(number)
        assert record["name"] == stored and record["player_name"] == player
        assert record["display_name"].startswith(f"{player} [map {number}]")
        assert (
            record["development"]
            == load_u9_region_catalogue()["maps"][str(number)]["development"]
        )
    assert describe_u9_browser_map(9)["display_name"] == "Britannia [map 9]"


def test_wording_covers_all_emitted_advice_and_information():
    catalog = load_u9_save_wording()
    assert {f"{check}/{severity}" for check, severity in RECOMMENDATIONS} <= set(
        catalog["findings"]
    )
    for key in ("PRC03/INFO", "PRC04/INFO", "LAY01/INFO", "CUS07/INFO", "REF08/INFO"):
        assert key in catalog["findings"]
    validate_u9_save_wording(catalog)
    modified = json.loads(json.dumps(catalog))
    modified["findings"]["NFS07/WARN"]["meaning"] = "Objects {count:03d}"
    with pytest.raises(ValueError, match="plain placeholders"):
        validate_u9_save_wording(modified)
    modified["findings"]["NFS07/WARN"]["meaning"] = "Objects {count}"
    modified["findings"]["NFS07/WARN"]["actions"].append("unexpected")
    with pytest.raises(ValueError, match="unknown action"):
        validate_u9_save_wording(modified)
    with pytest.raises(ValueError, match="missing detail"):
        fill_u9_save_wording("Objects {count}", {})


@pytest.mark.parametrize(
    "result,title,load_action",
    [
        ("PASS", "No problems found", True),
        ("WARN", "Review advised", True),
        ("ERROR", "Integrity errors", False),
        ("FATAL", "Unsafe to load", False),
    ],
)
def test_overall_result_controls_loading_actions(result, title, load_action):
    report = IntegrityReport("fixture", slot=4)
    if result != "PASS":
        report.add(
            "NFS01", "structure", result, "test", declared=4096, actual=0, maps=[9]
        )
    report.add("PRC04", "compatibility", "INFO", "cosmetic", count=1)
    plain = describe_u9_save_integrity(report)
    assert plain["summary"]["title"] == title
    assert ("try_load" in plain["actions"]) is load_action
    assert all(
        ("try_load" not in card["actions"]) or load_action for card in plain["cards"]
    )
    if not load_action:
        assert all(card["load_policy"] == "do_not_load" for card in plain["cards"])
        assert all(
            card["load_text"] == plain["summary"]["load_text"]
            for card in plain["cards"]
        )


def test_findings_use_json_details_and_pair_keys_instead_of_message_parsing():
    report = IntegrityReport("fixture", slot=4)
    report.add(
        "NFS01",
        "structure",
        "WARN",
        "irrelevant text",
        declared=4096,
        actual=0,
        maps=[9],
    )
    report.add("NFS01", "structure", "FATAL", "irrelevant text", maps=[4])
    plain = describe_u9_save_integrity(report)
    assert {card["key"] for card in plain["cards"]} == {"NFS01/WARN", "NFS01/FATAL"}
    rendered = render_u9_plain_integrity(plain)
    assert "4096 bytes" in rendered and "0 bytes" in rendered
    assert "Britannia [map 9]" in rendered and "development/test" in rendered
    assert "irrelevant text" not in rendered
    assert "try_load" not in plain["actions"]


def test_plain_details_use_the_checkers_strict_json_serialization():
    report = IntegrityReport("fixture", slot=4)
    report.add(
        "REF07",
        "compatibility",
        "WARN",
        "evidence",
        maps=[9],
        count=1,
        target_records=[{"local_xyz": [float("nan"), float("inf"), 0]}],
    )
    plain = describe_u9_save_integrity(report)
    encoded = json.dumps(plain, allow_nan=False)
    assert json.loads(encoded)["cards"][0]["contexts"][0]["target_records"][0][
        "local_xyz"
    ] == [None, None, 0]


def test_region_names_identify_britannia_and_mark_map_four_as_development():
    assert len(load_u9_region_catalogue()["maps"]) == 168
    britannia, demo = describe_u9_browser_map(9), describe_u9_browser_map(4)
    assert britannia["name"] == "Britannia" and not britannia["development"]
    assert demo["development"] and demo["category"] == "development"
    assert demo["terrain_name"] == "Moonglow"
    assert "development/test" in demo["display_name"]
    assert "unidentified" in describe_u9_browser_map(255)["display_name"]
    assert describe_u9_browser_map(164)["development"]


def test_discovery_is_scoped_and_keeps_unreadable_archives(save_install, tmp_path):
    root, save, _, _ = save_install
    (save / "u9game5.sav").write_bytes(b"bad")
    other = tmp_path / "another_install"
    other.mkdir()
    (other / "u9game77.sav").write_bytes(b"bad")
    rows = discover_u9_save_archives(root)
    assert [row["slot"] for row in rows] == [4, 5]
    assert rows[0]["selected"] and rows[0]["map_name"].startswith("Britannia")
    assert rows[1]["read_error"]


def test_browser_views_and_filtering_reuse_saved_data(save_install, tmp_path):
    session = session_for(save_install, tmp_path)
    for view in U9_SAVE_BROWSER_VIEWS:
        assert isinstance(describe_u9_save_browser_view(session, view), list)
    members = describe_u9_save_browser_view(session, "members")
    assert {row["name"] for row in members} == {
        "screenshot",
        "processes.dat",
        "diary.txt",
        "nonfixed.9",
    }
    assert filter_u9_save_browser_rows(members, "processes.dat")[0]["bytes"] > 1000
    assert describe_u9_save_browser_view(session, "maps")[0]["name"] == "Britannia"
    assert (
        build_u9_save_browser_report(session)["presentation"]["summary"]["result"]
        == "PASS"
    )


def test_creeper_finding_has_plain_cosmetic_loading_advice(save_install, tmp_path):
    root, save, static, reference = save_install
    from tests.test_u9_integrity import _world_header

    growth = _world_header(215, b"CreeperGrow") + struct.pack(
        "<iiffI", 1, 1, 0.25, 0.00002, 5000
    )
    processes = _processes(first_process=True, extra=growth, sections=_sections(refs=2))
    (save / "processes.dat").write_bytes(processes)
    (save / "u9game4.sav").write_bytes(_archive(processes, _nonfixed()))
    session = open_u9_save_browser_session(
        root,
        static_directory=static,
        fixed_reference_directory=reference,
        output=tmp_path / "out",
    )
    plain = describe_u9_save_integrity(session.report)
    card = next(card for card in plain["cards"] if card["key"] == "PRC04/INFO")
    assert card["contexts"][0]["count"] == 1
    assert "cosmetic" in card["load_text"] and "try_load" in card["actions"]
    assert "stop growing" in card["meanings"][0]


def test_exports_and_extractions_preserve_sources_and_prior_outputs(
    save_install, tmp_path
):
    session = session_for(save_install, tmp_path)
    before = {path: path.read_bytes() for path in session.save_directory.iterdir()}
    first, second = (
        export_u9_save_browser_bundle(session),
        export_u9_save_browser_bundle(session),
    )
    assert first != second and (first / "index.html").is_file()
    data = json.loads((first / "browser.json").read_text(encoding="utf-8"))
    assert data["integrity"] == session.report.to_dict()
    page = (first / "index.html").read_text(encoding="utf-8")
    assert "<summary>Details</summary>" in page and "Copy report" in page
    assert "id='technical'" in page and "integrity.txt" in page
    extraction = extract_u9_save_browser_archive(session)
    assert (extraction / "processes.dat").read_bytes() == session.archive.processes.data
    assert (extraction / "nonfixed.9").read_bytes() == session.archive.nonfixed[0].data
    assert before == {
        path: path.read_bytes() for path in session.save_directory.iterdir()
    }


def test_html_escapes_saved_npc_names(save_install, tmp_path):
    _, save, _, _ = save_install
    processes = bytearray(_processes())
    name = b"<script>alert(1)</script>"
    processes[8 + 1024 + 4 : 8 + 1024 + 4 + len(name)] = name
    (save / "processes.dat").write_bytes(processes)
    (save / "u9game4.sav").write_bytes(_archive(bytes(processes), _nonfixed()))
    session = session_for(save_install, tmp_path)
    folder = export_u9_save_browser_bundle(session)
    page = (folder / "index.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert(1)</script>" not in page


def test_backups_copy_selected_archive_all_loose_files_and_selector(
    save_install, tmp_path
):
    _, save, _, _ = save_install
    archive = save / "u9game4.sav"
    (save / "u9game5.sav").write_bytes(b"other archive")
    (save / "notes.txt").write_bytes(b"extra loose file")
    moment = datetime(2026, 10, 10, 2, 3, 4, 123000, tzinfo=timezone.utc)
    first = backup_u9_save(archive, save, tmp_path / "backups", slot=4, now=moment)
    second = backup_u9_save(archive, save, tmp_path / "backups", slot=4, now=moment)
    assert first.name == "u9-save-slot-4-20261010T020304123Z"
    assert second.name == first.name + "_1"
    assert (first / "archive/u9game4.sav").read_bytes() == archive.read_bytes()
    for name in ("processes.dat", "nonfixed.9", "diary.txt", "start.dat", "notes.txt"):
        assert (first / "working" / name).read_bytes() == (save / name).read_bytes()
    assert not (first / "archive/u9game5.sav").exists()
    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["complete"] and manifest["start_dat_present"]
    assert all(len(record["sha256"]) == 64 for record in manifest["files"])


def test_backup_detects_changed_sources_and_retains_incomplete_manifest(
    save_install, tmp_path, monkeypatch
):
    from titan.u9 import save_backup

    _, save, _, _ = save_install
    copy = save_backup.shutil.copy2

    def mutate(source, target):
        result = copy(source, target)
        source.write_bytes(source.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(save_backup.shutil, "copy2", mutate)
    output = tmp_path / "backups"
    with pytest.raises(ValueError, match="source changed"):
        backup_u9_save(save / "u9game4.sav", save, output, slot=4)
    folder = next(output.iterdir())
    assert json.loads((folder / "manifest.json").read_text())["complete"] is False


@pytest.mark.parametrize("target", ["savegame", "static", "reference"])
def test_all_outputs_reject_game_or_reference_data(save_install, tmp_path, target):
    _, save, static, reference = save_install
    session = session_for(save_install, tmp_path)
    session.output = {"savegame": save, "static": static, "reference": reference}[
        target
    ] / "exports"
    with pytest.raises(ValueError, match="outside game data"):
        export_u9_save_browser_bundle(session)
    with pytest.raises(ValueError, match="outside game data"):
        extract_u9_save_browser_archive(session)
    if target != "reference":
        with pytest.raises(ValueError, match="outside game data"):
            backup_u9_save(save / "u9game4.sav", save, session.output, slot=4)
    assert not session.output.exists()


def test_cli_help_and_headless_report(save_install, tmp_path):
    root, _, _, reference = save_install
    runner = CliRunner()
    help_result = runner.invoke(u9_app, ["save-browse", "--help"])
    assert help_result.exit_code == 0
    for option in ("--slot", "--static", "--fixed-reference", "--report", "--output"):
        assert option in help_result.output
    output = tmp_path / "out"
    result = runner.invoke(
        u9_app,
        [
            "save-browse",
            str(root),
            "--fixed-reference",
            str(reference),
            "--report",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (
        "No problems found" in result.output
        and (output / "save_report/index.html").is_file()
    )


def test_line_menus_navigate_views_export_and_backup(save_install, tmp_path):
    root, _, _, reference = save_install
    result = CliRunner().invoke(
        u9_app,
        [
            "save-browse",
            str(root),
            "--fixed-reference",
            str(reference),
            "-o",
            str(tmp_path / "out"),
        ],
        input="M\nQ\nF\n1\nH\n0\nQ\nQ\nB\nE\nQ\n",
    )
    assert result.exit_code == 0, result.output
    assert "Britannia" in result.output and "Backup complete" in result.output
    assert (tmp_path / "out/save_report/index.html").is_file()


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt, ui.PromptCancelled])
def test_browser_cancellation_is_clean(save_install, tmp_path, monkeypatch, error):
    root, _, _, _ = save_install

    def cancel(*args, **kwargs):
        raise error()

    monkeypatch.setattr(browser, "_menu", cancel)
    assert browser.run_u9_save_browser(source=root, output=tmp_path / "out") == 0
    assert not (tmp_path / "out").exists()
