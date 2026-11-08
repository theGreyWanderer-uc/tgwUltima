"""Dynamic gump section replacement and paperdoll native metadata inspection."""

import pytest
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.gump_metadata import U7GumpMetadata
from titan.u7.paperdoll_metadata import (
    U7PaperdollMetadata,
    PAPERDOLL_SLOT_NAMES,
    PAPERDOLL_SLOT_POSITIONS,
)


def section(name, *rows):
    return (
        f"%%section {name}\n"
        + "\n".join(":" + row for row in rows)
        + "\n%%endsection\n"
    ).encode()


def test_widgets_replace_per_section_and_shape_on_first_patch_entry():
    metadata = U7GumpMetadata()
    metadata.apply_text(
        section("dynamic_texts", "100/1/2/3/4", "101/1/5/6/7")
        + section("dynamic_shapes", "100/2/3/4/5/6/1"),
        "base",
    )
    metadata.apply_text(
        section("dynamic_texts", "100/8/9/10/11/1/2", "100/9/10/11/12"),
        "patch",
        patch=True,
    )
    assert [row["field_id"] for row in metadata.widgets["dynamic_texts"][100]] == [8, 9]
    assert metadata.widgets["dynamic_texts"][101][0]["font_num"] == 7
    assert metadata.widgets["dynamic_shapes"][100][0]["shape_num"] == 5
    assert metadata.widgets["dynamic_texts"][100][1]["valign"] == 0
    assert "dynamic_texts" in metadata.dump_csv()


def test_snap_zone_strings_rejection_and_patch_clearing():
    metadata = U7GumpMetadata()
    metadata.apply_text(
        section("snap_zones", "100/altar/1/2/30/40/5/6/7/offering"), "base"
    )
    metadata.apply_text(
        section("snap_zones", "100/reject/1/2/0/4/5/6/7/no"), "patch", patch=True
    )
    assert metadata.widgets["snap_zones"][100] == [] and metadata.warnings


@pytest.mark.parametrize(
    "section_name,row",
    [
        ("dynamic_buttons", "100/1"),
        ("dynamic_sliders", "100/1/2"),
        ("dynamic_shapes", "100/1/2/3/0x10/5/1"),
    ],
)
def test_bad_widgets_are_not_silently_ignored(section_name, row):
    with pytest.raises(ValueError, match="malformed"):
        U7GumpMetadata().apply_text(section(section_name, row), "bad")


def test_paperdoll_keys_removals_optional_frames_and_version_conversion():
    parsed = U7PaperdollMetadata()
    parsed.apply_text(
        section("version", "1")
        + section("characters", "100/0/0/13/1/4/2/3/7/1/2/3")
        + section("items", "200/-1/0/3/7/0/5/6"),
        "base",
    )
    assert parsed.items[(200, -1, 3)]["type"] == 1
    assert parsed.items[(200, -1, 3)]["frame3"] == -1
    parsed.apply_text(
        section("characters", "100/-255") + section("items", "200/-1/0/3/-255"), "patch"
    )
    assert not parsed.characters and not parsed.items and len(parsed.raw_rows) == 4
    assert len(PAPERDOLL_SLOT_NAMES) == 18 and PAPERDOLL_SLOT_POSITIONS[3] == (38, 55)
    assert "slot_layout" in parsed.dump_csv()


def test_paperdoll_skin_references_require_context_instead_of_guessing():
    data = section("characters", "%skin/0/0/13/1/4/2/3/7/1/2/3")
    unresolved = U7PaperdollMetadata()
    unresolved.apply_text(data, "skin")
    assert unresolved.unresolved and not unresolved.characters
    resolved = U7PaperdollMetadata()
    resolved.apply_text(data, "skin", skin_shapes={"%skin": 1024})
    assert 1024 in resolved.characters


def test_paperdoll_cli_uses_custom_static_metadata(tmp_path):
    (tmp_path / "paperdol_info.txt").write_bytes(
        section("characters", "100/0/0/13/1/4/2/3/7/1/2/3")
    )
    result = CliRunner().invoke(
        u7_app, ["static-data-dump", "paperdoll", str(tmp_path), "--custom-game"]
    )
    assert result.exit_code == 0, result.output
    assert "characters" in result.stdout and "slot_layout" in result.stdout
