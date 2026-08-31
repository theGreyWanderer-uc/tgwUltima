"""Tests for U3 generation, native-map bridging, and render prompting."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from titan.cli import app
from titan.u3 import cli as u3_cli
from titan.u3 import u3_nes_map_create as u3_map_create
from titan.u3.u3_nes_map_create import U3NesMapCreateResult
from titan.u7.native_map_create import U7NativeMapCreateResult


def _native_result(tmp_path: Path, *, dry_run: bool = False) -> U7NativeMapCreateResult:
    return U7NativeMapCreateResult(
        map_directory=str(tmp_path / "output" / "map04"),
        gamedat_directory=None,
        map_number=4,
        dry_run=dry_run,
        empty_map=False,
        materialized_empty_map=False,
        u7map_bytes=73728,
        ifix_files=144,
        fixed_objects=10,
        chunks_action="create",
        chunks_path=str(tmp_path / "output" / "u7chunks"),
        definitions_written=20,
        definitions_appended=0,
        remapped_definition_references=0,
    )


def _u3_result(tmp_path: Path) -> U3NesMapCreateResult:
    return U3NesMapCreateResult(
        map_number=4,
        seed=42,
        json_path=None,
        json_only=False,
        dry_run=False,
        counts={"definitions": 20, "fixed_objects": 10},
        generation={"seed": 42},
        native_map=_native_result(tmp_path),
    )


def test_u3_generation_document_flows_into_shared_native_writer(
    tmp_path: Path, monkeypatch
) -> None:
    document = {
        "map_number": 0,
        "counts": {"definitions": 20, "fixed_objects": 10},
        "generation": {"seed": 42},
    }
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        u3_map_create,
        "load_u7_map_document",
        lambda path: {"source": str(path)},
    )
    monkeypatch.setattr(
        u3_map_create,
        "build_u3_nes_sosaria_map_document",
        lambda source, seed: document,
    )

    def capture_native(output_root, map_number, **kwargs):
        captured.update(
            output_root=output_root,
            map_number=map_number,
            **kwargs,
        )
        return _native_result(tmp_path)

    monkeypatch.setattr(u3_map_create, "create_u7_native_map", capture_native)

    result = u3_map_create.create_u3_nes_sosaria_map(
        "si_source.json",
        tmp_path / "output",
        map_number=4,
        seed=42,
    )

    assert result.native_map is not None
    assert document["map_number"] == 4
    assert captured["source_document"] is document
    assert captured["source_label"] == "titan.u3.map-create"


def test_u3_nes_map_create_forwards_native_options_and_no_render(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    def capture_create(source, output_root, **kwargs):
        captured.update(source=source, output_root=output_root, **kwargs)
        return _u3_result(tmp_path)

    monkeypatch.setattr(u3_cli, "create_u3_nes_sosaria_map", capture_create)
    result = CliRunner().invoke(
        app,
        [
            "u3",
            "map-create",
            "si_source.json",
            "--output-root",
            str(tmp_path / "output"),
            "--map-num",
            "4",
            "--seed",
            "42",
            "--overwrite-map",
            "--update-chunks",
            "--no-render",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["source"] == "si_source.json"
    assert captured["output_root"] == str(tmp_path / "output")
    assert captured["map_number"] == 4
    assert captured["seed"] == 42
    assert captured["overwrite_map"] is True
    assert captured["update_chunks"] is True
    assert "Created native U7 map 04" in result.output


def test_interactive_post_create_question_can_render_classic_map(
    tmp_path: Path, monkeypatch
) -> None:
    prompts: list[tuple[str, bool]] = []
    rendered: list[SimpleNamespace] = []

    monkeypatch.setattr(
        u3_cli,
        "create_u3_nes_sosaria_map",
        lambda *args, **kwargs: _u3_result(tmp_path),
    )
    monkeypatch.setattr(u3_cli, "_is_interactive_terminal", lambda: True)

    def confirm_render(message: str, default: bool) -> bool:
        prompts.append((message, default))
        return True

    monkeypatch.setattr(
        u3_cli.typer,
        "confirm",
        confirm_render,
    )

    def capture_render(args: SimpleNamespace) -> int:
        rendered.append(args)
        return 0

    monkeypatch.setattr(
        u3_cli,
        "_render_created_map",
        capture_render,
    )

    result = CliRunner().invoke(
        app,
        [
            "u3",
            "map-create",
            "si_source.json",
            "--output-root",
            str(tmp_path / "output"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert prompts == [
        ("Would you also like to render it in classic isometric format?", False)
    ]
    assert len(rendered) == 1
    assert rendered[0].map_num == 4


def test_noninteractive_create_does_not_prompt_or_render(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        u3_cli,
        "create_u3_nes_sosaria_map",
        lambda *args, **kwargs: _u3_result(tmp_path),
    )
    monkeypatch.setattr(u3_cli, "_is_interactive_terminal", lambda: False)
    monkeypatch.setattr(
        u3_cli.typer,
        "confirm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prompted")),
    )
    monkeypatch.setattr(
        u3_cli,
        "_render_created_map",
        lambda args: (_ for _ in ()).throw(AssertionError("rendered")),
    )

    result = CliRunner().invoke(
        app,
        [
            "u3",
            "map-create",
            "si_source.json",
            "--output-root",
            str(tmp_path / "output"),
        ],
    )

    assert result.exit_code == 0, result.output
