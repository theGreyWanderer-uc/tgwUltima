"""High-bit AMMO ambiguity, derived skin imports and explicit runtime actor context."""

import csv
import io
import struct

import pytest
from typer.testing import CliRunner

from titan.u7.actor_metadata import U7ActorMetadata
from titan.u7.avatar_metadata import U7AvatarMetadata, read_u7_avatar_metadata
from titan.u7.cli import u7_app
from titan.u7.gump_metadata import U7GumpSource, U7GumpSources
from titan.u7.npc_browser import Session, Source, actor_context, load_session
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.paperdoll_metadata import read_u7_paperdoll_metadata
from titan.u7.save import U7NPC, U7NPCData
from titan.u7.shapeinfo import U7Ammos
from titan.u7.usecode import U7UsecodeFile
from titan.u7.usecode_analysis import U7UsecodeWorld
from tests.test_u7_advanced_gumps import section
from tests.test_u7_remaining_followups import actor_record
from tests.test_u7_usecode_validation import _function_record, _scope, _symbol


@pytest.mark.parametrize(
    "word,meaning",
    [
        (0xFFFF, "keep_weapon_projectile"),
        (0xFFFD, "ammo_item_shape"),
        (0x8000, "unknown_negative_selector"),
    ],
)
def test_ammo_high_bits_export_both_interpretations_without_changing_existing_decoding(
    word, meaning
):
    raw = struct.pack("<HHH7B", 100, 200, word, *([0] * 7))
    ammo = U7Ammos.from_bytes(b"\1" + raw)
    record = ammo.records[0]
    assert record.sprite_shape == word - 65536 and record.sprite_word == word
    assert record.signed_sprite_meaning == meaning
    assert record.raw == raw and ammo.table.raw == b"\1" + raw
    assert "high-bit" in ammo.warnings[0]
    assert "Retail BG/SI signed i16 decoding is verified" in ammo.warnings[0]
    row = next(csv.DictReader(io.StringIO(ammo.dump_csv())))
    assert int(row["exult_loaded_sprite_shape"]) == word
    assert row["reference_interpretation"] == "signed_unsigned_disagree"


@pytest.mark.parametrize(
    "family,sprite,expected,meaning",
    [
        (200, 0xFFFF, 500, "keep_weapon_projectile"),
        (200, 0xFFFD, 100, "ammo_item_shape"),
        (200, 200, 500, "keep_weapon_projectile"),
        (0xFFFD, 0xFFFD, 100, "ammo_item_shape"),
        (200, 300, 300, "explicit_shape"),
        (200, 0x8000, -32768, "literal_projectile_word"),
        (200, 0xFFFE, -2, "literal_projectile_word"),
        (0x8000, 0x8000, 500, "keep_weapon_projectile"),
    ],
)
def test_retail_attack_projectile_matches_bg_si_sentinel_and_family_precedence(
    family, sprite, expected, meaning
):
    ammo = U7Ammos.from_bytes(
        b"\1" + struct.pack("<HHH7B", 100, family, sprite, *([0] * 7))
    )
    record = ammo.records[0]
    assert record.resolve_retail_attack_projectile(500) == expected
    assert record.retail_sprite_meaning == meaning
    if sprite == 65535:
        assert record.resolve_retail_attack_projectile(-1) == -1


@pytest.mark.parametrize("word,signed", [(0, 0), (127, 127), (128, -128), (255, -1)])
def test_retail_ammo_damage_is_separate_from_exult_unsigned_damage(word, signed):
    ammo = U7Ammos.from_bytes(
        b"\1" + struct.pack("<HHH7B", 100, 200, 200, word, *([0] * 6))
    )
    assert ammo.records[0].damage == word and ammo.records[0].retail_damage == signed
    assert any("damage byte" in warning for warning in ammo.warnings) == (word >= 128)


def test_ammo_family_high_bit_warns_and_low_words_agree():
    high = U7Ammos.from_bytes(
        b"\1" + struct.pack("<HHH7B", 100, 65535, 200, *([0] * 7))
    )
    assert high.records[0].family_shape == -1 and high.records[0].family_word == 65535
    assert high.warnings
    low = U7Ammos.from_bytes(b"\1" + struct.pack("<HHH7B", 100, 200, 200, *([0] * 7)))
    assert (
        not low.warnings
        and low.records[0].reference_interpretation == "signed_unsigned_agree"
    )
    assert low.records[0].signed_sprite_meaning == "keep_weapon_projectile"


def metadata():
    result = U7AvatarMetadata()
    result.apply_imports(
        section("multiracial_imports", "1024/%0", "1025/%1"), "imports"
    )
    result.apply_avatars(
        section("version", "2")
        + section("baseracesex", "3/0")
        + section("defaultshape", "0/721/0/0", "1/989/0/1")
        + section(
            "multiracial_table", "0/0/%0/%1/5000/0/5000/1/1", "3/0/721/721/0/0/0/0/0"
        ),
        "avatars",
    )
    return result


def test_import_allocation_ignores_duplicates_and_keeps_patch_counter():
    result = metadata()
    result.apply_imports(
        section("multiracial_imports", "1024/%ignored", "1026/4000", "1027/%extra"),
        "patch",
    )
    assert result.skin_shapes == {"%0": 2048, "%1": 2049, "%extra": 2050}
    assert result.imports[-2:] == [(4000, 1026), (2050, 1027)]
    assert result.skin_shape_sources["%extra"].startswith("patch#")
    assert result.skins[(0, False)].shape == 2048
    assert not result.skins[(3, False)].copy_info


def test_shape_availability_is_required_only_when_it_changes_the_answer():
    result = metadata()
    unknown = result.resolve_shape(skin=0, female=False)
    assert unknown["resolved_shape"] is None and unknown["required_context"] == [
        "have_si_shapes"
    ]
    assert (unknown["without_si_shapes"], unknown["with_si_shapes"]) == (721, 2048)
    assert (
        result.resolve_shape(skin=0, female=False, have_si_shapes=False)[
            "resolved_shape"
        ]
        == 721
    )
    assert (
        result.resolve_shape(skin=0, female=False, have_si_shapes=True, naked=True)[
            "resolved_shape"
        ]
        == 2049
    )
    assert result.resolve_shape(skin=3, female=False)["resolved_shape"] == 721
    assert result.resolve_shape(skin=77, female=False)["resolved_shape"] == 721
    assert result.resolve_shape(skin=None, female=None)["required_context"] == [
        "avatar_sex",
        "avatar_skin",
    ]


def test_patch_imports_are_available_to_default_avatar_and_paperdoll_rows(tmp_path):
    sources = U7GumpSources(
        layers=[
            U7GumpSource(
                "AVATAR_DATA.TXT",
                section("multiracial_table", "0/0/%new/%new/1/2/3/4"),
                "avatar",
                tmp_path,
            ),
            U7GumpSource(
                "PAPERDOL_INFO.TXT",
                section("characters", "%new/0/0/13/1/4/2/3/7/1/2/3"),
                "doll",
                tmp_path,
            ),
            U7GumpSource(
                "SHAPE_FILES.TXT",
                section("multiracial_imports", "1050/%new"),
                "patch",
                tmp_path,
                True,
            ),
        ]
    )
    avatar = read_u7_avatar_metadata(sources)
    assert avatar.skins[(0, False)].shape == 2048
    paperdoll = read_u7_paperdoll_metadata(sources)
    assert not paperdoll.unresolved and 2048 in paperdoll.characters
    explicit = read_u7_paperdoll_metadata(sources, skin_shapes={"%new": 5000})
    assert 5000 in explicit.characters


def test_avatar_patch_replaces_only_skin_sex_key_and_retains_bad_reference_warning():
    result = metadata()
    result.apply_avatars(
        section("multiracial_table", "0/0/777/778/1/2/3/4", "1/0/%absent/5/1/2/3/4"),
        "patch",
        patch=True,
    )
    assert result.skins[(0, False)].shape == 777 and (3, False) in result.skins
    assert (1, False) not in result.skins and "%absent" in result.warnings[0]
    with pytest.raises(ValueError, match="incomplete"):
        result.apply_avatars(section("multiracial_table", "0/0/1"))


def actor(npc=0, *, game="bg", original=False, **kwargs):
    combat, name = kwargs.pop("combat", 0), kwargs.pop("name", None)
    raw = bytearray(actor_record(**kwargs))
    raw[21] = combat
    if name is not None:
        raw[78:78] = bytes([len(name)]) + name
    return U7ActorMetadata.from_bytes(
        raw, game=game, original_new_game=original, npc_num=npc, health=20, strength=30
    )


def test_actor_appearance_resolves_skin_naked_flag_and_sex_override():
    avatar = actor(flags2=1 << 6)
    assert (
        avatar.appearance(
            721, avatar_metadata=metadata(), avatar_skin=0, have_si_shapes=True
        )["resolved_shape"]
        == 2049
    )
    assert (
        avatar.appearance(721, avatar_metadata=metadata(), avatar_skin=3)[
            "resolved_shape"
        ]
        == 721
    )
    unknown = avatar.appearance(721, avatar_metadata=metadata(), avatar_skin=0)
    assert unknown["required_context"] == ["have_si_shapes"]
    assert (
        actor().appearance(721, avatar_metadata=metadata(), avatar_female=True)[
            "resolved_shape"
        ]
        is None
    )


def test_ambiguous_avatar_sex_stays_unresolved_without_override():
    result = actor().appearance(721, avatar_metadata=metadata(), avatar_sex_known=False)
    assert result["resolved_shape"] is None and result["required_context"] == [
        "avatar_sex"
    ]
    explicit = actor().appearance(
        721, avatar_metadata=metadata(), avatar_sex_known=False, avatar_female=False
    )
    assert explicit["resolved_shape"] == 721


def test_polymorph_uses_main_avatar_skin_mapping_and_default_rules():
    poly = actor(1, intel=128 | 10, poly=721)
    unresolved = poly.appearance(100, avatar_metadata=metadata())
    assert (
        unresolved["resolved_shape"] is None
        and unresolved["polymorph_context_required"]
    )
    assert (
        poly.appearance(100, avatar_metadata=metadata(), avatar_shape=2048)[
            "resolved_shape"
        ]
        == 2048
    )
    direct = actor(1, intel=128 | 10, poly=900).appearance(
        100, avatar_metadata=metadata()
    )
    assert direct["resolved_shape"] == 900 and not direct["required_context"]
    # Exult's fallback is load-time engine behavior, including the BG guard.
    assert (
        actor(0, original=True, intel=128 | 10).appearance(100)["resolved_shape"] == 530
    )
    assert (
        actor(0, original=True, intel=128 | 10, combat=128 | 10).appearance(100)[
            "resolved_shape"
        ]
        == 658
    )
    assert (
        actor(28, game="si", original=True, intel=128 | 10).appearance(
            100, avatar_shape=2048
        )["resolved_shape"]
        == 2048
    )
    assert (
        actor(1, game="si", original=True, intel=128 | 10).appearance(100)[
            "resolved_shape"
        ]
        == 100
    )


def test_default_polymorph_uses_petra_before_extended_flags_are_loaded():
    raw = bytearray(actor_record(intel=128 | 10, flags2=8))
    struct.pack_into("<H", raw, 64, 0)
    late_petra = U7ActorMetadata.from_bytes(
        raw, game="si", original_new_game=False, npc_num=0, health=20, strength=30
    )
    assert late_petra.effective_flags & (1 << 35)
    assert late_petra.appearance(100)["resolved_shape"] == 530


def test_named_actor_lookup_uses_replacing_patch_symbol_table(tmp_path):
    base = U7UsecodeFile.from_bytes(
        b"\xff\xff\xff\xffYSCU"
        + _scope(_symbol("handler", 1, 123))
        + _function_record(123)
    )
    patch = U7UsecodeFile.from_bytes(
        b"\xff\xff\xff\xffYSCU"
        + _scope(_symbol("handler", 1, 456))
        + _function_record(456)
    )
    world = U7UsecodeWorld()
    world.add_stream(base)
    world.add_stream(patch, patch=True)
    extension = actor(1, iflag=8, name=b"handler")
    target = ArchiveTarget("test", None, tmp_path)
    session = Session(target, Source(tmp_path), usecode_symbols=world.symbol_values)
    npc = U7NPC(npc_num=1, name="test", shape=100, frame=0, metadata=extension)
    assert actor_context(session, npc)["resolved_usecode"] == 456
    session.usecode_symbols = {}
    assert actor_context(session, npc)["usecode_status"] == "symbol_not_found"
    session.usecode_symbols = None
    assert actor_context(session, npc)["usecode_status"] == "symbols_unavailable"


def test_npc_browser_polymorph_maps_to_skin_not_avatar_current_polymorph(tmp_path):
    target = ArchiveTarget("test", None, tmp_path)
    avatar = U7NPC(
        npc_num=0,
        name="Avatar",
        frame=0,
        shape=721,
        metadata=actor(0, intel=128 | 10, poly=530),
    )
    other = U7NPC(
        npc_num=1,
        name="other",
        frame=0,
        shape=100,
        metadata=actor(1, intel=128 | 10, poly=721),
    )
    session = Session(
        target,
        Source(tmp_path),
        npcs=U7NPCData([avatar, other]),
        avatar_metadata=metadata(),
        avatar_skin=0,
        have_si_shapes=True,
    )
    assert actor_context(session, avatar)["appearance"]["resolved_shape"] == 530
    assert actor_context(session, other)["appearance"]["resolved_shape"] == 2048


def test_browser_loads_symbols_from_selected_world_and_patch(tmp_path):
    static, patch, live = tmp_path / "STATIC", tmp_path / "patch", tmp_path / "gamedat"
    for directory in (static, patch, live):
        directory.mkdir()
    base = (
        b"\xff\xff\xff\xffYSCU"
        + _scope(_symbol("handler", 1, 123))
        + _function_record(123)
    )
    mod = (
        b"\xff\xff\xff\xffYSCU"
        + _scope(_symbol("handler", 1, 456))
        + _function_record(456)
    )
    (static / "USECODE").write_bytes(base)
    (patch / "usecode").write_bytes(mod)
    raw = bytes.fromhex(actor(1, iflag=8, name=b"handler").raw_hex)
    (live / "NPC.DAT").write_bytes(struct.pack("<HH", 2, 0) + raw * 2)
    target = ArchiveTarget("custom", static, patch, standalone=True)
    session = load_session(target, Source(live, "live"), "bg")
    assert session.usecode_symbols == {"handler": 456}
    assert actor_context(session, session.npcs.npcs[1])["resolved_usecode"] == 456
    assert session.usecode_sources == [str(static / "USECODE"), str(patch / "usecode")]


def test_paperdoll_cli_resolves_custom_imports(tmp_path):
    (tmp_path / "shape_files.txt").write_bytes(
        section("multiracial_imports", "1024/%0")
    )
    (tmp_path / "paperdol_info.txt").write_bytes(
        section("characters", "%0/0/0/13/1/4/2/3/7/1/2/3")
    )
    result = CliRunner().invoke(
        u7_app, ["static-data-dump", "paperdoll", str(tmp_path), "--custom-game"]
    )
    assert result.exit_code == 0, result.output
    assert "characters,2048," in result.stdout and "unresolved," not in result.stdout
    help_result = CliRunner().invoke(u7_app, ["npc-browse", "--help"])
    assert help_result.exit_code == 0 and "--avatar-skin" in help_result.stdout
