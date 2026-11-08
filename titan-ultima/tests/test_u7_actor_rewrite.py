"""Actor header writes preserve opaque prefix bytes, framed tails and localized name bytes."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan.u7.actor_rewrite import (
    U7ActorHeaderEdit,
    read_actor_wire_file,
    rewrite_actor_file,
    rewrite_actor_header,
    rewrite_actor_save,
)
from titan.u7.actor_rewrite_cli import read_actor_edit_plan
from titan.u7.cli import u7_app
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_tree import ireg_context_sha256
from titan.u7.save import U7Save
from titan.u7.typeflag import U7TypeFlags


def metadata(game: str = "bg") -> U7IregContext:
    raw = bytearray(3072)
    raw[100 * 3 + 1] = 2
    raw[200 * 3 + 1] = 6
    return U7IregContext(
        U7TypeFlags.parse(bytes(raw)),
        game=game,
        bodies_complete=True,
        jawbones_complete=True,
    )


def header(flags: int = 0, name: bytes = b"") -> bytes:
    raw = bytearray((index * 17 + 3) & 255 for index in range(117))
    struct.pack_into("<H", raw, 4, flags)
    struct.pack_into("<H", raw, 14, 1)
    raw[18] = 0xE5
    raw[101:117] = b"\xc4Actor\0tail\xffbytes"[:16]
    if flags & 8:
        raw[78:78] = bytes([len(name)]) + name
    return bytes(raw)


def actor_file() -> bytes:
    # Nested container, unknown record, persistent slot, owned and orphan specials.
    container = b"\x0c\0\0\xc8\0\1\0\0\0\0\0\0\0"
    item = b"\6\x08\x09\x64\0\0\0"
    inventory = b"\2\3\xab" + container + item + b"\1\3abc\1"
    specials = b"\xff\x4d\3\0raw\xff\2"
    return (
        struct.pack("<HH", 1, 1)
        + header(3)
        + inventory
        + specials
        + header()
        + b"trailer\xff"
    )


def edit(raw: bytes, fields: dict[str, int | str], *, game: str = "bg", index: int = 0):
    context = metadata(game)
    actor = read_actor_wire_file(raw, context=context).actors[index]
    return rewrite_actor_file(
        raw,
        [U7ActorHeaderEdit(index, hashlib.sha256(actor.raw).hexdigest(), fields)],
        context=context,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_context_sha256=ireg_context_sha256(context),
    )


@pytest.mark.parametrize("game,expected", [("bg", 0xFF), ("si", 0xFF)])
def test_stat_masks_preserve_skin_freeze_and_other_packed_flags(
    game: str, expected: int
) -> None:
    raw = actor_file()
    result = edit(
        raw,
        {"strength": 31 if game == "si" else 63, "intelligence": 30, "combat": 99},
        game=game,
    )
    before = read_actor_wire_file(raw, context=metadata(game))
    after = read_actor_wire_file(result.data, context=metadata(game))
    assert after.actors[0].header[18] == expected
    assert after.actors[0].header[20] & 0xE0 == before.actors[0].header[20] & 0xE0
    assert after.actors[0].inventory == before.actors[0].inventory
    assert after.actors[0].specials == before.actors[0].specials
    assert (
        after.actors[1].raw == before.actors[1].raw
        and after.trailing == before.trailing
    )


def test_strength_si_rejects_sixth_bit_bg_keeps_it() -> None:
    with pytest.raises(ValueError):
        edit(actor_file(), {"strength": 32}, game="si")
    assert edit(actor_file(), {"strength": 32}, game="bg").data[4 + 18] & 63 == 32


def test_named_function_growth_and_removal_preserve_shifted_unknowns_and_tails() -> (
    None
):
    raw = actor_file()
    result = edit(
        raw,
        {
            "usecode_name_hex": b"localized_\xe4_function".hex(),
            "food": -17,
            "name_hex": bytes(range(128, 144)).hex(),
        },
    )
    before = read_actor_wire_file(raw, context=metadata())
    after = read_actor_wire_file(result.data, context=metadata())
    assert len(after.actors[0].header) == 117 + 1 + len(b"localized_\xe4_function")
    assert after.actors[0].inventory == before.actors[0].inventory
    assert after.actors[1].raw == before.actors[1].raw
    removed = edit(result.data, {"usecode_name_hex": ""})
    restored = read_actor_wire_file(removed.data, context=metadata()).actors[0].header
    assert len(restored) == 117 and restored[79:93] == before.actors[0].header[79:93]
    assert restored[93] == (-17 & 255) and restored[101:] == bytes(range(128, 144))


def test_full_header_replacement_can_update_reserved_bytes_without_zeroing_others() -> (
    None
):
    raw = actor_file()
    parsed = read_actor_wire_file(raw, context=metadata())
    replacement = bytearray(parsed.actors[0].header)
    replacement[11:14] = b"NEW"
    request = U7ActorHeaderEdit(
        0,
        hashlib.sha256(parsed.actors[0].raw).hexdigest(),
        replacement_header=bytes(replacement),
    )
    result = rewrite_actor_file(
        raw,
        [request],
        context=metadata(),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_context_sha256=ireg_context_sha256(metadata()),
    )
    assert result.data == raw[:15] + b"NEW" + raw[18:]


@pytest.mark.parametrize(
    "fields",
    [
        {"iflag1": 0},
        {"iflag1": 11},
        {"strength": 10, "strength_byte": 5},
        {"name": "x" * 17},
        {"usecode_name_hex": "00"},
        {"usecode_name_hex": "xx"},
        {"lift": True},
        {"unknown": 1},
    ],
)
def test_unsafe_or_conflicting_header_fields_fail(fields: dict[str, int | str]) -> None:
    with pytest.raises(ValueError):
        edit(actor_file(), fields)


def test_multiple_actor_edits_keep_original_guards_and_report_shifted_offsets() -> None:
    raw = actor_file()
    before = read_actor_wire_file(raw, context=metadata())
    requests = [
        U7ActorHeaderEdit(
            0,
            hashlib.sha256(before.actors[0].raw).hexdigest(),
            {"usecode_name_hex": "616263"},
        ),
        U7ActorHeaderEdit(
            1, hashlib.sha256(before.actors[1].raw).hexdigest(), {"health": -10}
        ),
    ]
    result = rewrite_actor_file(
        raw,
        requests,
        context=metadata(),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_context_sha256=ireg_context_sha256(metadata()),
    )
    after = read_actor_wire_file(result.data, context=metadata())
    assert result.changes[1]["offset"] == before.actors[1].offset
    assert (
        result.changes[1]["output_offset"]
        == after.actors[1].offset
        == before.actors[1].offset + 4
    )
    assert after.actors[1].header[10] == 246
    with pytest.raises(ValueError, match="SHA-256"):
        rewrite_actor_file(
            raw,
            [U7ActorHeaderEdit(0, "0" * 64, {"health": 1})],
            context=metadata(),
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expected_context_sha256=ireg_context_sha256(metadata()),
        )


@pytest.mark.parametrize("offset", [0, 2, 4, 80, 120, 142])
def test_truncated_actor_streams_fail(offset: int) -> None:
    with pytest.raises(ValueError):
        read_actor_wire_file(actor_file()[:offset], context=metadata())


def test_monster_wrapper_original_flavor_and_noop() -> None:
    context = metadata("si")
    monsters = struct.pack("<H", 1) + header()
    parsed = read_actor_wire_file(monsters, context=context, kind="monsters")
    assert parsed.to_bytes() == monsters
    assert (
        rewrite_actor_file(
            monsters,
            [],
            context=context,
            kind="monsters",
            expected_sha256=hashlib.sha256(monsters).hexdigest(),
            expected_context_sha256=ireg_context_sha256(context),
        ).data
        == monsters
    )
    original = bytearray(header())
    struct.pack_into("<H", original, 4, 0)
    assert (
        rewrite_actor_header(
            bytes(original),
            {"strength": 30},
            context=context,
            flavor="original-new-game",
        )[18]
        == 0xFE
    )
    with pytest.raises(ValueError, match="runtime"):
        rewrite_actor_header(
            bytes(original), {"flags2": 0}, context=context, flavor="original-new-game"
        )


def save(raw: bytes) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("NPC.DAT", raw)
        archive.writestr("empty", b"")
        archive.writestr("other", b"unchanged")
    return stream.getvalue()


def test_actor_save_embedding_preserves_other_members() -> None:
    raw = actor_file()
    archived = save(raw)
    actor = read_actor_wire_file(raw, context=metadata()).actors[0]
    result, report = rewrite_actor_save(
        archived,
        (0,),
        [U7ActorHeaderEdit(0, hashlib.sha256(actor.raw).hexdigest(), {"health": -12})],
        context=metadata(),
        kind="npc",
        flavor="runtime",
        expected_save_sha256=hashlib.sha256(archived).hexdigest(),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_context_sha256=ireg_context_sha256(metadata()),
    )
    after = U7Save.from_bytes(result, strict=True)
    assert after.members[0].data[14] == 244
    assert [(m.name, m.data) for m in after.members[1:]] == [
        ("empty", b""),
        ("other", b"unchanged"),
    ]
    assert "actor_edit" in report


@pytest.mark.parametrize("archived", [False, True])
def test_actor_cli_inspect_dry_run_write_and_stale_guards(
    tmp_path: Path, archived: bool
) -> None:
    runner = CliRunner()
    static = tmp_path / "STATIC"
    static.mkdir()
    context = metadata()
    assert context.tfa is not None
    (static / "TFA.DAT").write_bytes(
        b"".join(entry.tfa for entry in context.tfa.entries)
    )
    for name, section in (
        ("bodies.txt", "bodyshapes"),
        ("shape_info.txt", "is_jawbone"),
    ):
        (static / name).write_text(
            f"%%section version\n:2\n%%endsection\n%%section {section}\n%%endsection\n"
        )
    raw = actor_file()
    source = tmp_path / "actors.dat"
    original = save(raw) if archived else raw
    source.write_bytes(original)
    inspect_args = [
        "actor-headers",
        str(source),
        "--static",
        str(static),
        "--game",
        "bg",
        "--flavor",
        "runtime",
        "--custom-game",
    ]
    if archived:
        inspect_args += ["--member-path", "0"]
    inspected = runner.invoke(u7_app, inspect_args)
    assert inspected.exit_code == 0, inspected.output
    row = json.loads(inspected.stdout)
    plan = {
        key: row[key]
        for key in ("source_sha256", "context_sha256", "game", "kind", "flavor")
    }
    plan["edits"] = [
        {
            "index": 0,
            "expected_sha256": row["actors"][0]["sha256"],
            "fields": {"health": -10, "usecode_name_hex": "74657374"},
        }
    ]
    if archived:
        plan["save"] = row["save"]
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    output = tmp_path / "new.dat"
    args = [
        "actor-rewrite",
        str(source),
        "--static",
        str(static),
        "--custom-game",
        "--plan",
        str(plan_path),
        "-o",
        str(output),
    ]
    preview = runner.invoke(u7_app, [*args, "--dry-run"])
    assert preview.exit_code == 0, preview.output
    assert not output.exists()
    written = runner.invoke(u7_app, args)
    assert written.exit_code == 0, written.output
    assert (
        source.read_bytes() == original and runner.invoke(u7_app, args).exit_code == 1
    )
    output.unlink()
    plan["source_sha256"] = "0" * 64
    plan_path.write_text(json.dumps(plan))
    assert runner.invoke(u7_app, args).exit_code == 1 and not output.exists()


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"source_sha256": "bad"},
        {
            "source_sha256": "0" * 64,
            "context_sha256": "0" * 64,
            "game": "xx",
            "kind": "npc",
            "flavor": "runtime",
            "edits": [],
        },
    ],
)
def test_malformed_actor_plans_fail(value: object) -> None:
    with pytest.raises(ValueError):
        read_actor_edit_plan(value)
