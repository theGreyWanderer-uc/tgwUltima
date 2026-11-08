"""Exercise load-order inheritance and Exult's runtime preference search."""

from pathlib import Path

import pytest

from titan.u7.gump_metadata import U7GumpSource, U7GumpSources
from titan.u7.ready_metadata import U7ReadyMetadata
from titan.u7.save import U7ReadyTypes


def table(*rows: tuple[int, int, bool]) -> bytes:
    return bytes([len(rows)]) + b"".join(
        shape.to_bytes(2, "little") + bytes([(code << 3) | spell]) + bytes(6)
        for shape, code, spell in rows
    )


def sources(
    text: bytes, name: str = "SHAPE_INFO.TXT", patch: bool = False
) -> U7GumpSources:
    return U7GumpSources([U7GumpSource(name, text, "fixture", Path("fixture"), patch)])


@pytest.mark.parametrize("game,default", [("bg", 1), ("si", 8)])
def test_absent_and_invalid_use_game_default_without_changing_raw_api(
    game: str, default: int
) -> None:
    data = table((100, 31, True))
    raw = U7ReadyTypes.from_bytes(data, game)
    ready = U7ReadyMetadata(game)
    ready.apply_ready(data)
    for shape in (100, 101):
        result = ready.resolve(shape)
        assert result.preferred == default
        assert result.defaulted
        assert result.search_order == (default, 3, 3, 2, 1, 12, 13, 3, 8)
    assert raw.slot_for_shape(100) == 255
    assert raw.slot_for_shape(101) is None
    assert ready.resolve(100).spell


def test_binary_overlays_preserve_unassigned_alternatives_and_duplicate_order() -> None:
    ready = U7ReadyMetadata()
    ready.apply_ready(table((100, 1, True)), "base")  # left hand: right hand, belt
    ready.apply_ready(table((100, 6, False), (100, 5, False)), "patch")
    result = ready.resolve(100)
    assert (result.preferred, result.alternate1, result.alternate2) == (9, 7, 2)
    assert result.source == "patch#record=1"
    assert result.alternatives_source == "patch#record=0"
    assert not result.spell


def test_text_overrides_replace_both_alternatives_and_missing_fields_mean_invalid() -> (
    None
):
    ready = U7ReadyMetadata()
    ready.apply_ready(table((100, 1, False), (101, 20, False)))
    ready.apply_sources(
        sources(b"%%section altready\n:100/21\n:101/-1/-1\n%%endsection\n")
    )
    result = ready.resolve(100)
    assert (result.alternate1, result.alternate2) == (21, 3)
    assert not result.context_complete  # no frame/paperdoll handedness context
    result = ready.resolve(101)
    assert (result.preferred, result.alternate1, result.alternate2) == (18, 3, 3)
    assert result.context_complete
    ready.apply_sources(
        sources(b"%%section altready\n:100/13/12\n%%endsection\n", patch=True)
    )
    assert ready.alternatives[100] == (13, 12)


def test_frame_specific_paperdoll_can_prefer_right_hand() -> None:
    ready = U7ReadyMetadata()
    ready.apply_ready(table((100, 1, False)))
    ready.apply_sources(sources(b"%%section altready\n%%endsection\n"))
    ready.apply_sources(
        sources(
            b"%%section version\n:3\n%%endsection\n%%section items\n:100/2/0/8/0/0/100/0\n:100/-1/0/3/0/0/100/0\n%%endsection\n",
            "PAPERDOL_INFO.TXT",
        )
    )
    assert ready.resolve(100, 2).preferred == 3  # wildcard left also allowed
    ready.paperdoll.items.pop((100, -1, 3))
    assert ready.resolve(100, 2).preferred == 8
    assert ready.resolve(100, 2).context_complete
    assert ready.resolve(100, 3).preferred == 3


def test_directory_sparse_patch_and_text_are_applied_after_binary(
    tmp_path: Path,
) -> None:
    static, patch = tmp_path / "static", tmp_path / "patch"
    static.mkdir()
    patch.mkdir()
    (static / "READY.DAT").write_bytes(table((100, 1, False), (101, 6, True)))
    (patch / "ready.dat").write_bytes(table((100, 5, False)))
    (static / "shape_info.txt").write_bytes(
        b"%%section altready\n:100/12/13\n%%endsection\n"
    )
    (patch / "shape_info.txt").write_bytes(
        b"%%section altready\n:100/21/-1\n%%endsection\n"
    )
    ready = U7ReadyMetadata.from_dir(static, patch_dir=patch, custom_game=True)
    assert (ready.resolve(100).preferred, ready.resolve(100).alternate1) == (9, 21)
    assert ready.resolve(101).preferred == 4
    assert ready.resolve(101).spell
    assert ready.resolve(100).context_complete


def test_truncated_ready_cannot_produce_authoritative_preferences() -> None:
    with pytest.raises(ValueError, match="Incomplete READY"):
        U7ReadyMetadata().apply_ready(b"\x01\x00")
