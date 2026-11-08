"""Class dispatch, extended offsets, BG/SI bodies and stream synchronization."""

from pathlib import Path

import pytest

from titan.u7.gump_metadata import U7GumpSource, U7GumpSources
from titan.u7.ireg import U7ObjectFlags, decode_ireg_payload
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.map import U7MapRenderer
from titan.u7.save import _read_ireg_inventory
from titan.u7.typeflag import U7TypeFlags


def payload(size: int, shape: int = 100, extended: bool = False) -> bytearray:
    data = bytearray(size + extended)
    data[2] = shape & 255
    data[3] = shape >> 8
    if extended:
        data[4] = 7
    return data


def decode(data: bytes | bytearray, **options):
    return decode_ireg_payload(
        bytes(data), entlen=len(data), extended=False, extended_lift=False, **options
    )


@pytest.mark.parametrize("extended", [False, True])
def test_spellbook_circles_bookmark_and_flags(extended: bool) -> None:
    data = payload(18, 2000 if extended else 100, extended)
    a = int(extended)
    data[4 + a : 9 + a] = bytes(range(5))
    data[9 + a] = 0x53
    data[10 + a : 14 + a] = bytes(range(5, 9))
    data[14 + a : 18 + a] = b"\xaa\xbb\xcc\x2a"
    result = decode_ireg_payload(
        bytes(data),
        entlen=len(data),
        extended=extended,
        extended_lift=extended,
        shape_class=8,
        inherited_flags=U7ObjectFlags.OKAY_TO_TAKE | U7ObjectFlags.TEMPORARY,
    )
    assert result is not None
    assert result.kind == "spellbook"
    assert result.class_data == {
        "circles": list(range(9)),
        "bookmark": 42,
        "unknown_hex": "aabbcc",
    }
    assert result.lift == (53 if extended else 5)
    assert result.object_flags == U7ObjectFlags.OKAY_TO_TAKE
    assert result.raw_hex == data.hex()
    assert not result.has_children_marker


@pytest.mark.parametrize(
    "game,encoded,expected",
    [("bg", 1, -1), ("si", 1, 129), ("bg", 129, 1), ("si", 128, -1)],
)
def test_body_identity_requires_supplemental_flag_and_game(
    game: str, encoded: int, expected: int
) -> None:
    data = payload(12)
    data[7], data[8], data[9], data[11] = 1, encoded, 0x40, 9
    body = decode(data, is_body=True, game=game)
    assert body is not None
    assert body.kind == "body"
    assert body.class_data["npc_number"] == expected
    assert body.lift == 4
    generic = decode(data, is_body=False, is_jawbone=False)
    assert generic is not None and generic.kind == "container"
    assert "npc_number" not in generic.class_data


@pytest.mark.parametrize("extended", [False, True])
def test_extended_body_identity_and_shifted_flag_offsets(extended: bool) -> None:
    data = payload(13, 2000 if extended else 100, extended)
    a = int(extended)
    data[7 + a] = 1
    data[8 + a : 10 + a] = (513).to_bytes(2, "little")
    data[10 + a], data[12 + a] = 0x60, 9
    result = decode_ireg_payload(
        bytes(data),
        entlen=len(data),
        extended=extended,
        extended_lift=False,
        is_body=True,
    )
    assert result is not None
    assert result.class_data["npc_number"] == 513
    assert result.lift == 6
    assert result.object_flags == U7ObjectFlags.INVISIBLE | U7ObjectFlags.OKAY_TO_TAKE
    assert (
        decode_ireg_payload(
            bytes(data),
            entlen=len(data),
            extended=extended,
            extended_lift=False,
            is_body=False,
        )
        is None
    )


def test_virtue_stone_destination_does_not_consume_following_objects() -> None:
    raw_tfa = bytearray(3072)
    raw_tfa[301] = 11
    context = U7IregContext(
        U7TypeFlags.parse(bytes(raw_tfa)), bodies_complete=True, jawbones_complete=True
    )
    stone = payload(12)
    stone[4:8] = bytes([10, 20, 25, 7])
    stone[9:12] = bytes([0x30, 2, 0])
    child = payload(6, 101)
    stream = bytes([12]) + stone + bytes([6]) + child + b"\x01"
    objects = U7MapRenderer.parse_ireg_deep("fixture", 0, data=stream, context=context)
    items, end = _read_ireg_inventory(stream, 0, ireg_context=context)
    assert len(objects) == len(items) == 2
    assert end == len(stream)
    assert objects[0].children == []
    assert objects[0].ireg_data == {
        "target_x": 266,
        "target_y": 532,
        "target_lift": 7,
        "target_map": 2,
    }
    assert items[0].ireg_data == objects[0].ireg_data
    assert objects[1].shape == items[1].shape == 101


def test_barge_and_jawbone_preserve_child_marker_and_resistance() -> None:
    data = payload(12)
    data[4], data[5], data[7], data[10] = 8, 16, 14, 17
    barge = decode(data, shape_class=9, is_body=False)
    assert barge is not None and barge.kind == "barge" and barge.has_children_marker
    assert barge.class_data == {
        "width": 8,
        "height": 16,
        "direction": 3,
        "moving": True,
    }
    jaw = decode(data, shape_class=6, is_body=False, is_jawbone=True)
    assert jaw is not None and jaw.kind == "jawbone"
    assert jaw.class_data["resistance"] == 17


@pytest.mark.parametrize("extended", [False, True])
def test_custom_hatchable_uses_egg_lift_and_never_container_recursion(
    extended: bool,
) -> None:
    data = payload(14, 2000 if extended else 100, extended)
    a = int(extended)
    data[4 + a : 7 + a] = b"\x14\x88\x64"
    data[9 + a] = 0x52
    data[12 + a : 14 + a] = b"\x34\x12"
    result = decode_ireg_payload(
        bytes(data),
        entlen=len(data),
        extended=extended,
        extended_lift=True,
        shape_class=7,
        inherited_flags=U7ObjectFlags.INVISIBLE,
    )
    assert result is not None
    assert result.kind == "egg" and result.lift == 37
    assert result.object_flags == U7ObjectFlags.NONE
    assert not result.has_children_marker
    assert result.class_data["data3"] == 0x1234


def test_missing_context_is_reported_and_short_payload_rejected() -> None:
    result = decode(payload(13))
    assert result is not None and result.kind == "body"
    assert any("inferred" in warning for warning in result.context_warnings)
    assert (
        decode_ireg_payload(b"1234", entlen=12, extended=False, extended_lift=False)
        is None
    )


def test_body_text_version_one_and_sparse_flag_removal() -> None:
    layers = U7GumpSources(
        [
            U7GumpSource(
                "BODIES.TXT",
                b"%%section bodyshapes\n400:1\n414:1\n%%endsection\n",
                "base",
                Path("base"),
            ),
            U7GumpSource(
                "BODIES.TXT",
                b"%%section version\n:2\n%%endsection\n%%section bodyshapes\n:400/0\n%%endsection\n",
                "patch",
                Path("patch"),
                True,
            ),
            U7GumpSource(
                "SHAPE_INFO.TXT",
                b"%%section is_jawbone\n:555/1\n%%endsection\n",
                "base",
                Path("base"),
            ),
        ]
    )
    context = U7IregContext.from_sources(layers, game="si")
    assert context.bodies == {400: False, 414: True}
    assert context.bodies_complete and context.jawbones_complete
    data = payload(12, 555)
    result = decode(data, context=context)
    assert result is not None and result.kind == "jawbone"


def test_map_special_endmark_has_no_length() -> None:
    data = b"\xff\x02" + bytes([6]) + payload(6, 101)
    objects = U7MapRenderer.parse_ireg_deep("fixture", 0, data=data)
    assert [obj.shape for obj in objects] == [101]
