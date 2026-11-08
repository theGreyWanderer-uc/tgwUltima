"""U7 text namespace, authoring grammar and retained frame-rule regressions."""

from pathlib import Path

import pytest

from titan.u7.flex import U7FlexArchive
from titan.u7.names import U7FrameNames, U7ShapeNames, format_u7_name
from titan.u7.text import U7TextBanks, U7TextMessages, remap_si_misc_index
from titan.u7.text_names import load_u7_text_names


def flex(path: Path, records: list[bytes]) -> Path:
    archive = U7FlexArchive()
    archive.records = records
    path.write_bytes(archive.to_bytes())
    return path


@pytest.mark.parametrize(
    ("raw", "bare", "single", "plural"),
    [
        ("/kni/fe/ves", "knife", "knife", "2 knives"),
        (
            "some long prefix/berry//berries",
            "berry",
            "some long prefix berry",
            "2 berryberries",
        ),
        ("a/coin//s", "coin", "a coin", "2 coins"),
        ("water", "water", "water", "2 water"),
        ("bad/slashes", "?", "?", "?"),
    ],
)
def test_morphology(raw, bare, single, plural):
    assert format_u7_name(raw, bare=True) == bare
    assert format_u7_name(raw) == single
    assert format_u7_name(raw, 0) == single
    assert format_u7_name(raw, 2) == plural


def test_message_numbers_auto_whitespace_and_explicit_empty():
    parsed = U7TextMessages.from_bytes(
        b"10:decimal\n010:octal\n0x10:hex\n:first\n"
        b"%%section shapes\n:second\n2:  value: # kept  \n3:\n2: final  \n%%endsection\n"
    )
    assert parsed.sections[""] == {10: "decimal", 8: "octal", 16: "hex", 0: "first"}
    assert parsed.sections["shapes"] == {1: "second", 2: " final  ", 3: ""}
    assert parsed.strings("shapes", ["base", "old", "old", "old"]) == [
        "base",
        "second",
        " final  ",
        "",
    ]


@pytest.mark.parametrize(
    "data",
    [
        b"-1:bad",
        b"+1:bad",
        b"ff:bad",
        b"09:bad",
        b"65536:bad",
        b"%%section shapes\n%%section msgs\n",
        b"%%endsection\n",
        b"%%section shapes\n",
        b"%%section shapes\n%%endsection\n%%section shapes\n%%endsection",
    ],
)
def test_invalid_authoring_does_not_mutate_a_base(data):
    with pytest.raises(ValueError):
        U7TextMessages.from_bytes(data)


def test_encoding():
    assert (
        U7TextMessages.from_bytes("0:café".encode("utf-8-sig")).sections[""][0]
        == "café"
    )
    assert U7TextMessages.from_bytes(b"0:caf\xe9").encoding == "latin-1"
    with pytest.raises(UnicodeDecodeError):
        U7TextMessages.from_bytes(b"0:caf\xe9", encoding="utf-8")


def test_banks_caps_raw_extra_and_shape_identity(tmp_path):
    records = [b""] * 0x700
    for index in (615, 0x400, 0x500, 0x5FF, 0x600, 0x685, 0x686):
        records[index] = f"slot {index}".encode() + b"\0"
    records[615] = b"/kni/fe/ves\0"
    path = flex(tmp_path / "TEXT.FLX", records)
    names = U7ShapeNames.from_file(str(path))
    assert len(names) == 1024
    assert names.get(615) == "knife"
    assert names.get(1024) == ""
    banks = names.text_banks
    assert banks is not None
    assert len(banks.misc) == 256 and len(banks.extra_records) == 256
    assert banks.messages[0] == "slot 1024"
    assert banks.raw_records == tuple(records)
    si = U7TextBanks.from_file(path, game="si")
    assert len(si.misc) == 390
    assert si.extra_records[0] == b"slot 1670\0"


def test_explicit_si_variants_and_beta_message_shift():
    records = [b""] * 0x686
    records[0x400 + 0xD2] = b"beta message\0"
    records[0x500 + 0x7F] = b"shifted misc\0"
    records[0x685] = b"cut off\0"
    beta = U7TextBanks.from_records(records, game="si", si_variant="beta")
    assert beta.messages[0xD2] == "" and beta.messages[0xD3] == "beta message"
    assert beta.misc[0x81] == "shifted misc"
    assert "cut off" not in beta.misc
    assert remap_si_misc_index(0xFA, "original") == 0x105
    assert remap_si_misc_index(0x146, "beta") == 0x157
    assert remap_si_misc_index(0x146, "silver-seed") == 0x146
    with pytest.raises(ValueError):
        U7TextBanks.from_records(records, game="bg", si_variant="original")


def rules(rows, misc=()):
    return U7FrameNames.from_text(
        "%%section framenames\n" + rows + "\n%%endsection", misc
    )


def test_quality_wildcards_actions_and_short_rows():
    from titan.u7.map import U7MapObject
    from titan.u7.typeflag import U7TypeFlags
    from titan.u7.world import object_name

    frames = rules(
        ":5/-1/-1/0/0\n:5/1/-1/0/1\n:5/-1/2/0/2\n:5/1/2/0/3\n"
        ":6/0/-1/-1\n:7/0/-1/-255\n:8/0/-1/0/4\n:467/0/4",
        ["both", "frame", "quality", "exact", ""],
    )
    assert [frames.get(5, f, q) for f, q in ((1, 2), (1, 3), (2, 2), (2, 3))] == [
        "exact",
        "frame",
        "quality",
        "both",
    ]
    names = U7ShapeNames(["base"] * 468)
    assert frames.resolve(6, 0, names).kind == "suppressed"
    assert frames.label(6, 0, names) == ""
    assert frames.resolve(7, 0, names).kind == "default"
    assert frames.label(7, 0, names) == "base"
    assert frames.resolve(8, 0, names).kind == "empty"
    tfa_data = bytearray(3 * 9)
    tfa_data[5 * 3 + 1] = 2
    tfa = U7TypeFlags.parse(tfa_data)
    obj = U7MapObject(0, 0, 0, 5, 1, quality=2)
    assert object_name(obj, names, frames, tfa) == "exact"
    tfa_data[5 * 3 + 1] = 12
    assert object_name(obj, names, frames, U7TypeFlags.parse(tfa_data)) == "frame"
    assert object_name(U7MapObject(0, 0, 0, 6, 0), names, frames, tfa) == ""
    short = frames.rule_for(467, 0, 4)
    assert short is not None and (short.type, short.msgid, short.supplied_fields) == (
        0,
        0,
        3,
    )


def test_positive_composition_and_runtime_context():
    frames = rules(
        ":0/0/-1/1/0/1\n:0/1/-1/2/0/1\n:0/2/-1/3/0/-255\n:0/3/-1/4/0/-1\n:0/4/-1/3/0/1",
        [" suffix ", "prefix "],
    )
    names = U7ShapeNames(["a/base//s"])
    assert frames.label(0, 0, names, has_quality=True) == "prefix  suffix "
    assert frames.label(0, 1, names, has_quality=True) == " suffix prefix "
    assert frames.resolve(0, 0, names).kind == "unresolved"
    assert frames.label(0, 0, names, has_quality=False) == "base"
    assert frames.resolve(0, 2, names, is_body=True).kind == "unresolved"
    assert frames.label(0, 2, names, is_body=True, npc_name="Iolo") == "Iolo suffix "
    assert frames.label(0, 3, names, is_body=True, npc_name="Iolo") == " suffix Iolo"
    assert frames.label(0, 2, names, is_body=True, npc_name="") == "base"
    assert frames.resolve(0, 3, names, is_body=True, npc_name="").kind == "suppressed"
    assert frames.label(0, 4, names, is_body=True, npc_name="") == "prefix "


def test_misc_only_rebinds_retained_ids(tmp_path):
    base = rules(":5/0/-1/0/0", ["old"])
    (tmp_path / "textmsg.txt").write_text("%%section miscnames\n0:new\n%%endsection\n")
    updated = U7FrameNames.from_mod_dir(str(tmp_path), None, base)
    assert updated is not None and updated.get(5, 0) == "new"
    assert base.get(5, 0) == "old"
    assert updated.rule_for(5, 0).msgid == 0


def test_selected_sources_replacement_and_engine_message_merge(tmp_path):
    static, patch = tmp_path / "STATIC", tmp_path / "patch"
    static.mkdir()
    patch.mkdir()
    records = [b""] * 1281
    records[1] = b"retail\0"
    records[1280] = b"retail frame\0"
    text = flex(static / "TEXT.FLX", records)
    (static / "textmsg.txt").write_text("%%section shapes\n1:static\n%%endsection\n")
    (static / "shape_info.txt").write_text(
        "%%section framenames\n:1/0/-1/0/0\n%%endsection\n"
    )
    (patch / "textmsg.txt").write_text(
        "%%section shapes\n2:patch\n%%endsection\n"
        "%%section miscnames\n0:new frame\n%%endsection\n"
        "%%section msgs\n0:\n%%endsection\n"
    )
    (patch / "exultmsg.txt").write_text("0x400:engine zero\n0x401:engine one\n")
    selected = load_u7_text_names(static, patch_dirs=[patch])
    assert selected.names.get(1) == "" and selected.names.get(2) == "patch"
    assert selected.frames.get(1, 0) == "new frame"
    assert selected.banks.messages == ("", "engine one")
    explicit = load_u7_text_names(static, patch_dirs=[patch], text_flx_path=text)
    assert explicit.names.get(1) == "retail"
    assert explicit.frames.get(1, 0) == "retail frame"


@pytest.mark.parametrize(("game", "index"), [("bg", 7), ("si", 4)])
def test_bundle_defaults_rebind_to_selected_misc(tmp_path, game, index):
    (tmp_path / "textmsg.txt").write_text(
        "%%section miscnames\n0:selected\n%%endsection\n"
    )
    records = [b""] * 8
    records[index] = b"%%section framenames\n:5/0/-1/0/0\n%%endsection\n"
    bundle = flex(tmp_path / f"exult_{game}.flx", records)
    common = [b""] * 24
    common[20] = b"0x400:common\n"
    common[21] = b"0x400:deutsch\n"
    flex(tmp_path / "exult.flx", common)
    selected = load_u7_text_names(
        tmp_path, exult_flx_path=bundle, game=game, language="de"
    )
    assert selected.frames.get(5, 0) == "selected"
    assert selected.banks.messages[0] == "deutsch"
