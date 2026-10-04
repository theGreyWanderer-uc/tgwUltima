"""Real IFIX/IREG searches, mod inheritance, recipes, and wizard refinement."""

from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from titan.u7.cli import u7_app
from titan.u7.flex import U7FlexArchive
from titan.u7.world import WorldQueryParams, parse_numbers, parse_rectangle, run_query
from titan.u7 import world_workflow as workflow


def write_ifix(directory, sc, objects):
    directory.mkdir(parents=True, exist_ok=True)
    archive = U7FlexArchive()
    archive.records = [b"" for _ in range(256)]
    for shape, frame, x, y in objects:
        chunk = (y // 16) * 16 + x // 16
        archive.records[chunk] += bytes(
            [
                ((x % 16) << 4) | (y % 16),
                0,
                shape & 255,
                ((shape >> 8) & 3) | (frame << 2),
            ]
        )
    (directory / f"u7ifix{sc:02x}").write_bytes(archive.to_bytes())


@pytest.fixture
def world(tmp_path, monkeypatch):
    static = tmp_path / "game" / "STATIC"
    static.mkdir(parents=True)
    data = bytearray(3 * 1024)
    data[150 * 3 : 150 * 3 + 3] = bytes([8, 2, 0])
    data[151 * 3 : 151 * 3 + 3] = bytes([0, 2, 0])
    data[522 * 3 + 1] = 6
    (static / "TFA.DAT").write_bytes(data + bytes(512))
    names = U7FlexArchive()
    names.records = [b""] * 1282
    names.records[150] = b"a/door//s\x00"
    names.records[151] = b"table\x00"
    names.records[1280] = b"frame zero\x00"
    names.records[1281] = b"frame one\x00"
    (static / "TEXT.FLX").write_bytes(names.to_bytes())
    write_ifix(static, 0, [(150, 0, 1, 2), (150, 1, 3, 4), (151, 0, 5, 6)])
    write_ifix(static, 1, [(151, 2, 7, 8)])
    import titan.u7.cli as cli

    monkeypatch.setattr(cli, "_resolve_u7_paths", lambda game: (None, None))
    monkeypatch.setattr(cli, "_resolve_u7_gamedat", lambda game: None)
    monkeypatch.setattr(cli, "_resolve_u7_text_flx", lambda game, static: None)
    return WorldQueryParams(static_dir=str(static), superchunks=[0, 1])


def test_shape_frame_name_flag_and_rectangle_filters(world):
    result = run_query(
        replace(
            world,
            shape_nums=[150],
            frames=[1],
            name_filter="door",
            tfa_flags=["solid"],
            tile_rect=(0, 0, 4, 4),
        )
    )
    assert [(r.shape, r.frame, r.tx, r.ty) for r in result.records] == [(150, 1, 3, 4)]
    assert result.records[0].shape_name == "door"
    assert not result.warnings


def test_patch_replaces_whole_ifix_and_inherits_missing_files(world, tmp_path):
    patch = tmp_path / "game" / "mods" / "Test" / "patch"
    write_ifix(patch, 0, [(150, 3, 9, 10)])
    (patch / "textmsg.txt").write_text(
        "%%section shapes\n0096:mod door\n%%endsection\n"
    )
    result = run_query(replace(world, static_dir=str(patch)))
    assert [(r.shape, r.frame) for r in result.records] == [(150, 3), (151, 2)]
    assert result.records[0].shape_name == "mod door"
    assert "solid" in result.records[0].flags


def test_explicit_patch_tfa_replaces_base_file(world, tmp_path):
    patch = tmp_path / "external"
    patch.mkdir()
    data = bytearray(3 * 1024)
    data[151 * 3 : 151 * 3 + 3] = bytes([8, 14, 0])
    (patch / "tfa.dat").write_bytes(data)
    result = run_query(replace(world, patch_dir=str(patch), tfa_flags=["solid"]))
    assert [r.shape for r in result.records] == [151, 151]
    assert all(r.shape_class == 14 for r in result.records)


def test_frame_names_are_used_for_search_and_display(world, tmp_path):
    mod = tmp_path / "names"
    mod.mkdir()
    (mod / "textmsg.txt").write_text(
        "%%section miscnames\n0001:mod frame one\n%%endsection\n"
    )
    (mod / "shape_info.txt").write_text(
        "%%section framenames\n:150/1/-1/0/1\n%%endsection\n"
    )
    result = run_query(replace(world, mod_data_dir=str(mod), name_filter="mod frame"))
    assert [(r.shape, r.frame, r.shape_name) for r in result.records] == [
        (150, 1, "mod frame one")
    ]


def test_map_number_does_not_fall_back_to_map_zero(world):
    static = Path(world.static_dir)
    write_ifix(static / "MAP01", 0, [(151, 3, 4, 5)])
    result = run_query(replace(world, map_num=1))
    assert [(r.frame, r.tx, r.ty) for r in result.records] == [(3, 4, 5)]
    assert not result.warnings
    absent = run_query(replace(world, map_num=2))
    assert not absent.records
    assert "No IFIX files" in absent.warnings[-1]


def test_ireg_mixed_case_map_directory_and_file(world, tmp_path):
    gamedat = tmp_path / "gamedat"
    (gamedat / "MAP01").mkdir(parents=True)
    (gamedat / "MAP01" / "U7IREG00").write_bytes(bytes([6, 1, 2, 150, 4, 0, 0]))
    result = run_query(
        replace(
            world,
            gamedat_dir=str(gamedat),
            include_ifix=False,
            include_ireg=True,
            map_num=1,
        )
    )
    assert [(r.shape, r.frame, r.source) for r in result.records] == [(150, 1, "ireg")]


def test_no_tfa_fails_filters_but_allows_numeric_search_with_warning(world):
    (Path(world.static_dir) / "TFA.DAT").unlink()
    for changes in ({"tfa_flags": ["solid"]}, {"shape_classes": [0]}):
        with pytest.raises(ValueError, match="TFA.DAT"):
            run_query(replace(world, **changes))
    result = run_query(replace(world, shape_nums=[150]))
    assert result.count == 2
    assert result.records[0].shape_class_name == "unknown"
    assert any("TFA.DAT" in w for w in result.warnings)


def test_auxiliary_entries_do_not_pass_missing_class_or_flag_filters(world):
    static = Path(world.static_dir)
    (static / "TFA.DAT").write_bytes(bytes(3 * 151))
    (static / "WGTVOL.DAT").write_bytes(bytes(2 * 152))
    result = run_query(replace(world, shape_classes=[0]))
    assert [r.shape for r in result.records] == [150, 150]
    assert any("Excluded 2" in w for w in result.warnings)


def test_missing_names_reject_name_filter(world):
    (Path(world.static_dir) / "TEXT.FLX").unlink()
    with pytest.raises(ValueError, match="name filter"):
        run_query(replace(world, name_filter="door"))
    assert run_query(world).count == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"shape_nums": [-1]},
        {"shape_nums": [65536]},
        {"frames": [256]},
        {"map_num": -1},
        {"map_num": 256},
        {"superchunks": [144]},
        {"tile_rect": (0, 0, 3072, 1)},
        {"tile_rect": (4, 0, 1, 1)},
        {"tfa_flags": ["typo"]},
        {"shape_classes": [1]},
        {"output_format": "typo"},
        {"include_ifix": False},
        {"include_ireg": True},
    ],
)
def test_invalid_filters_do_not_run(world, changes):
    with pytest.raises(ValueError):
        run_query(replace(world, **changes))


@pytest.mark.parametrize("raw", ["150,nope", "150,", "-1", "65536"])
def test_numeric_parser_never_drops_invalid_tokens(raw):
    with pytest.raises(ValueError):
        parse_numbers(raw, 65535, "Shape number")


def test_rectangle_normalization_and_decimal_leading_zeroes():
    assert parse_rectangle("10,20,01,02") == (1, 2, 10, 20)
    assert parse_numbers("010,0x0a,11", 100, "number") == [10, 11]


def test_recipe_round_trip_relative_paths_and_original_defaults(
    world, tmp_path, monkeypatch
):
    path = tmp_path / "search.toml"
    params = replace(
        world,
        game="si",
        frames=[1],
        name_filter="door",
        tfa_flags=["solid"],
        output_format="csv",
        output_path=str(tmp_path / "results.csv"),
    )
    workflow.save_recipe(params, str(path))
    assert 'static = "game' in path.read_text()
    monkeypatch.chdir(tmp_path.parent)
    assert workflow.load_recipe(str(path)) == params
    with pytest.raises(FileExistsError):
        workflow.save_recipe(params, str(path))


@pytest.mark.parametrize(
    "contents",
    [
        "[filters]\nshapes=['150']",
        "[filters]\nshapes=[true]",
        "[filters]\nclasses=['typo']",
        "[filters]\nflags='solid'",
        "[filters]\ntile_rect=[0,0,3]",
        "[filters]\nframes=[256]",
        "[sources]\nireg='yes'",
        "[world]\nmap_num=true",
        "[world]\nstatic=42",
        "[world]\nunknown='oops'",
        "[unknown]\nx=1",
    ],
)
def test_malformed_recipes_rejected(contents, tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text(contents)
    with pytest.raises(ValueError):
        workflow.load_recipe(str(path))


def test_cli_recipe_is_noninteractive_and_explicit_flags_override(
    world, tmp_path, monkeypatch
):
    recipe = tmp_path / "search.toml"
    workflow.save_recipe(replace(world, shape_nums=[150], frames=[0]), str(recipe))
    import questionary

    monkeypatch.setattr(
        questionary, "text", lambda *a, **k: pytest.fail("Recipe prompted")
    )
    result = CliRunner().invoke(
        u7_app, ["world-query", "-c", str(recipe), "--frame", "1", "-f", "full_text"]
    )
    assert result.exit_code == 0, result.output
    assert "1 match(es)" in result.output
    assert "frame=  1" in result.output


def test_cli_no_ireg_overrides_container_auto_selection(world, tmp_path):
    gamedat = tmp_path / "gamedat"
    gamedat.mkdir()
    (gamedat / "u7ireg00").write_bytes(bytes([6, 1, 2, 10, 2, 0, 0]))
    result = CliRunner().invoke(
        u7_app,
        [
            "world-query",
            world.static_dir,
            "--gamedat",
            str(gamedat),
            "--class",
            "container",
            "--no-ireg",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "matched 0" in result.output


def test_cli_map_number_passed_to_wizard(world, monkeypatch):
    import titan.u7.world as engine

    context = {}

    def wizard(**kwargs):
        context.update(kwargs)
        return 0

    monkeypatch.setattr(engine, "run_wizard", wizard)
    result = CliRunner().invoke(
        u7_app, ["world-query", world.static_dir, "--map-num", "3", "--game", "si"]
    )
    assert result.exit_code == 0, result.output
    assert context["map_num"] == 3
    assert context["game"] == "si"


@pytest.mark.parametrize(
    "flags",
    [
        ["--shape", "150,nope"],
        ["--shape", ""],
        ["--sc", ""],
        ["--sc", "144"],
        ["--flag", "typo"],
        ["--tile-rect", "0,0,3072,4"],
        ["-f", "typo"],
        ["--frame", "256"],
    ],
)
def test_cli_bad_filters_report_errors(world, flags):
    result = CliRunner().invoke(u7_app, ["world-query", world.static_dir, *flags])
    assert result.exit_code == 1
    assert "World query failed" in result.output


def scripted_questions(monkeypatch, answers):
    import questionary

    queue = iter(answers)
    prompts = []

    class Prompt:
        def ask(self):
            return next(queue)

    def factory(message, **kwargs):
        prompts.append((message, kwargs))
        return Prompt()

    for name in ("text", "path", "select", "checkbox", "confirm"):
        monkeypatch.setattr(questionary, name, factory)
    return prompts


def test_wizard_reprompts_invalid_input_and_refines_without_losing_choices(
    world, monkeypatch, capsys
):
    answers = [
        [],
        False,
        "door",
        "typo",
        "150",
        "1",
        [],
        "Entire world",
        True,
        "Refine filters",
        [],
        False,
        "door",
        "150",
        "0",
        [],
        "Tile rectangle",
        "0,0,9999,4",
        "0,0,4,4",
        True,
        "Finish",
    ]
    prompts = scripted_questions(monkeypatch, answers)
    assert workflow.run_wizard(world) == 0
    output = capsys.readouterr().out
    assert "Invalid Shape number" in output
    assert "Tile coordinate must" in output
    assert output.count("matched 1") == 2
    shape_prompts = [
        options for message, options in prompts if message.startswith("Shape numbers")
    ]
    assert shape_prompts[-1]["default"] == "150"
    name_prompts = [
        options for message, options in prompts if message.startswith("Name contains")
    ]
    assert name_prompts[-1]["default"] == "door"


def test_wizard_change_area_does_not_reask_filters_and_can_save_recipe(
    world, tmp_path, monkeypatch
):
    recipe = tmp_path / "wizard.toml"
    answers = [
        [],
        False,
        "",
        "151",
        "",
        [],
        "Entire world",
        True,
        "Change area",
        "Superchunks",
        "1",
        True,
        "Save recipe",
        str(recipe),
        "Finish",
    ]
    prompts = scripted_questions(monkeypatch, answers)
    assert workflow.run_wizard(world) == 0
    assert sum(message.startswith("Shape numbers") for message, _ in prompts) == 1
    assert workflow.load_recipe(str(recipe)).superchunks == [1]
    assert workflow.load_recipe(str(recipe)).shape_nums == [151]


@pytest.mark.parametrize("stage", range(9))
def test_cancel_at_each_initial_stage_is_clean(world, monkeypatch, stage):
    answers = [[], False, "", "", "", [], "Entire world", True, "Finish"]
    scripted_questions(monkeypatch, answers[:stage] + [None])
    assert workflow.run_wizard(world) == 0


def test_export_guards_overwrites_and_game_data(world, tmp_path):
    result = run_query(world)
    output = tmp_path / "results.txt"
    workflow.write_results(result, str(output))
    with pytest.raises(FileExistsError):
        workflow.write_results(result, str(output))
    workflow.write_results(result, str(output), overwrite=True)
    with pytest.raises(ValueError, match="Export outside"):
        workflow.write_results(
            result, str(Path(world.static_dir) / "TFA.DAT"), overwrite=True
        )
    assert (Path(world.static_dir) / "TFA.DAT").stat().st_size == 3584


def test_exult_extended_ifix_and_patch_tfa(world, tmp_path):
    from titan.u7.flex import U7_FLEX_EXULT_MAGIC2

    patch = tmp_path / "extended"
    patch.mkdir()
    data = bytearray(3 * 1101)
    data[1100 * 3 : 1100 * 3 + 3] = bytes([8, 2, 0])
    (patch / "TFA.DAT").write_bytes(data)
    archive = U7FlexArchive()
    archive.magic2 = U7_FLEX_EXULT_MAGIC2 | 1
    archive.records = [bytes([0x12, 0, 1100 & 255, 1100 >> 8, 200])]
    (patch / "U7IFIX00").write_bytes(archive.to_bytes())
    result = run_query(
        replace(
            world,
            patch_dir=str(patch),
            superchunks=[0],
            frames=[200],
            tfa_flags=["solid"],
        )
    )
    assert [(r.shape, r.frame, r.tx, r.ty) for r in result.records] == [
        (1100, 200, 1, 2)
    ]


def test_unknown_properties_warning_only_counts_otherwise_matching_objects(world):
    (Path(world.static_dir) / "TFA.DAT").write_bytes(bytes(151 * 3))
    result = run_query(replace(world, shape_nums=[150], shape_classes=[0]))
    assert result.count == 2
    assert not any("Excluded" in warning for warning in result.warnings)


def test_cli_can_supply_missing_recipe_gamedat_or_disable_ireg(world, tmp_path):
    recipe = tmp_path / "search.toml"
    recipe.write_text("[sources]\nireg=true\n")
    gamedat = tmp_path / "gamedat"
    gamedat.mkdir()
    for flags in (["--gamedat", str(gamedat)], ["--no-ireg"]):
        result = CliRunner().invoke(
            u7_app, ["world-query", world.static_dir, "-c", str(recipe), *flags]
        )
        assert result.exit_code == 0, result.output


def test_saved_patch_recipe_pins_the_effective_base(world, tmp_path):
    patch = tmp_path / "game" / "mods" / "Test" / "patch"
    patch.mkdir(parents=True)
    params = replace(world, static_dir=str(patch))
    recipe = tmp_path / "search.toml"
    workflow.save_recipe(params, str(recipe))
    loaded = workflow.load_recipe(str(recipe))
    assert Path(loaded.base_static) == Path(world.static_dir)
    assert Path(loaded.patch_dir) == patch
    assert run_query(loaded).count == 4


def test_wizard_shows_placements_exports_and_clears_new_search_filters(
    world, tmp_path, monkeypatch, capsys
):
    output = tmp_path / "search.csv"
    answers = [
        [],
        False,
        "",
        "150",
        "1",
        [],
        "Entire world",
        True,
        "Show placements",
        150,
        "Export results",
        "csv",
        str(output),
        "New search",
        [],
        False,
        "",
        "",
        "",
        [],
        "Entire world",
        True,
        "Finish",
    ]
    prompts = scripted_questions(monkeypatch, answers)
    assert workflow.run_wizard(world) == 0
    assert "frame=  1" in capsys.readouterr().out
    assert output.read_text().count("\n") == 2
    shape_prompts = [
        options for message, options in prompts if message.startswith("Shape numbers")
    ]
    assert shape_prompts[-1]["default"] == ""


def test_cli_csv_warnings_do_not_corrupt_stdout(world):
    (Path(world.static_dir) / "TFA.DAT").unlink()
    result = CliRunner().invoke(
        u7_app, ["world-query", world.static_dir, "--shape", "150", "-f", "csv"]
    )
    assert result.exit_code == 0
    assert result.stdout.startswith("source,shape,shape_hex")
    assert "Warning:" not in result.stdout
    assert "Warning:" in result.stderr


def test_cli_existing_output_requires_force(world, tmp_path):
    path = tmp_path / "out.csv"
    path.write_text("preserve me")
    args = ["world-query", world.static_dir, "--shape", "150", "-o", str(path)]
    failed = CliRunner().invoke(u7_app, args)
    assert failed.exit_code == 1
    assert path.read_text() == "preserve me"
    assert CliRunner().invoke(u7_app, [*args, "--force"]).exit_code == 0
    assert "matched 2" in path.read_text()


def test_external_selected_patch_uses_explicit_base(world, tmp_path):
    patch = tmp_path / "custom-folder"
    write_ifix(patch, 0, [(150, 4, 1, 2)])
    result = run_query(
        replace(world, static_dir=str(patch), base_static=world.static_dir)
    )
    assert [(r.shape, r.frame) for r in result.records] == [(150, 4), (151, 2)]
    cli_result = CliRunner().invoke(
        u7_app,
        ["world-query", str(patch), "--base-static", world.static_dir, "--frame", "4"],
    )
    assert cli_result.exit_code == 0, cli_result.output
    assert "matched 1" in cli_result.output


def test_missing_static_is_not_silently_treated_as_working_directory():
    with pytest.raises(ValueError, match="Provide a STATIC"):
        run_query(WorldQueryParams(static_dir=""))


def test_cli_explicit_base_and_patch_without_config(world, tmp_path):
    patch = tmp_path / "external"
    write_ifix(patch, 0, [(150, 5, 1, 2)])
    result = CliRunner().invoke(
        u7_app,
        [
            "world-query",
            "--base-static",
            world.static_dir,
            "--patch",
            str(patch),
            "--frame",
            "5",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "matched 1" in result.output


def test_partial_names_report_excluded_placements(world):
    names = U7FlexArchive.from_file(str(Path(world.static_dir) / "TEXT.FLX"))
    names.records[151] = b""
    (Path(world.static_dir) / "TEXT.FLX").write_bytes(names.to_bytes())
    result = run_query(replace(world, name_filter="door"))
    assert result.count == 2
    assert any(
        "Excluded 2 placement(s) with unavailable names" in warning
        for warning in result.warnings
    )
