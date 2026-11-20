"""Recipe descriptions (``CommandMeta.recipe_spec``) match what the wizards read."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from titan import _meta
from titan.fonts import wizard as font_wizard
from titan.u7 import shape_wizard

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

WIZARDS = {
    ("u7", "font-create"): font_wizard,
    ("u7", "shape-create"): shape_wizard,
}


def _spec(path: tuple[str, ...]) -> _meta.RecipeSpec:
    info = _meta.command_meta(*path)
    assert info is not None
    spec = info.recipe_spec()
    assert spec is not None
    return spec


def test_recipe_commands_are_the_wizards() -> None:
    tagged = {path for path, info in _meta.command_metas().items() if info.recipe}
    assert tagged == set(WIZARDS)


@pytest.mark.parametrize("path", sorted(WIZARDS))
def test_recipe_spec_is_well_formed(path: tuple[str, ...]) -> None:
    info = _meta.command_meta(*path)
    assert info is not None
    spec = _spec(path)
    assert info.params[spec.param] == "recipe"
    assert spec.param in info.batch_with
    names = [f.name for f in spec.fields]
    assert len(names) == len(set(names))
    for field in spec.fields:
        assert field.type in _meta.RECIPE_TYPES, field.name
        assert field.help, field.name
        if field.kind is not None:
            assert field.kind in _meta.PARAM_KINDS, field.name
        if field.type == "path" or field.open:
            assert field.kind is not None, field.name
        if field.default is not None:
            # Defaults are values the recipe writer accepts.
            spec.to_toml({field.name: field.default, **_required(spec)})
        if field.when is not None:
            other = spec.field(field.when[0])
            assert other is not None, field.name
            assert set(field.when[1]) <= set(other.choices), field.name


def _required(spec: _meta.RecipeSpec) -> dict[str, object]:
    return {f.name: "x.png" for f in spec.fields if f.required}


class _Section(dict):
    def __init__(self, name: str, seen: set[str]) -> None:
        super().__init__()
        self._name, self._seen = name, seen

    def get(self, key, default=None):
        self._seen.add(f"{self._name}.{key}")
        return default

    def __contains__(self, key) -> bool:
        self._seen.add(f"{self._name}.{key}")
        return False


class _Recipe(dict):
    """An empty recipe that records every ``section.key`` the wizard asks for."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: set[str] = set()

    def get(self, key, default=None):
        return _Section(key, self.seen)


@pytest.mark.parametrize("path", sorted(WIZARDS))
def test_recipe_spec_matches_what_run_from_config_reads(
    path: tuple[str, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = WIZARDS[path]
    recipe = _Recipe()
    monkeypatch.setattr(module, "tomllib", SimpleNamespace(load=lambda _: recipe))
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("recipe prompted"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "recipe.toml").write_text("", encoding="utf-8")
    # An empty recipe fails validation after every field has been read.
    module.run_from_config(str(tmp_path / "recipe.toml"))
    assert {f.name for f in _spec(path).fields} == recipe.seen


def test_to_toml_round_trips_and_rejects_bad_values() -> None:
    spec = _spec(("u7", "font-create"))
    values = {
        "target.game": "SI",
        "target.slot": 2,
        "target.code_range": (33, 126),
        "source.font": "./My Font.ttf",  # open choices accept a path
        "rendering.method": "threshold",
        "palette.file": Path("C:/u7/STATIC/PALETTES.FLX"),
        "output.force": True,
        "output.name": None,  # left out
    }
    data = tomllib.loads(spec.to_toml(values))
    assert data == {
        "target": {"game": "SI", "slot": 2, "code_range": [33, 126]},
        "source": {"font": "./My Font.ttf"},
        "rendering": {"method": "threshold"},
        "palette": {"file": "C:/u7/STATIC/PALETTES.FLX"},
        "output": {"force": True},
    }
    for bad in (
        {"target.slot": True},
        {"target.slot": "2"},
        {"target.game": "U8"},
        {"output.force": 1},
        {"target.code_range": [33, "z"]},
        {"output.path": ""},
        {"nowhere.key": 1},
    ):
        with pytest.raises(ValueError):
            spec.to_toml(bad)
    with pytest.raises(ValueError, match="source.path"):
        _spec(("u7", "shape-create")).to_toml({"target.game": "BG"})


def test_generated_font_recipe_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("recipe prompted"))
    output = tmp_path / "out" / "font.shp"
    recipe = tmp_path / "recipe.toml"
    recipe.write_text(
        _spec(("u7", "font-create")).to_toml(
            {
                "target.game": "BG",
                "target.slot": 2,
                "source.font": "dosVga437",
                "rendering.method": "mono",
                "output.format": "shp",
                "output.path": output,
            }
        ),
        encoding="utf-8",
    )
    assert font_wizard.run_from_config(str(recipe)) == 0
    assert output.is_file()


def test_generated_shape_recipe_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("recipe prompted"))
    monkeypatch.setattr(shape_wizard, "_open_preview", lambda path: None)
    palette = tmp_path / "palette.pal"
    colors = np.zeros((256, 3), dtype=np.uint8)
    colors[1] = (255, 0, 0)
    palette.write_bytes(colors.tobytes())
    source = tmp_path / "art.png"
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(source)
    output = tmp_path / "out" / "art.shp"
    recipe = tmp_path / "recipe.toml"
    recipe.write_text(
        _spec(("u7", "shape-create")).to_toml(
            {
                "source.path": source,
                "palette.file": palette,
                "palette.index": 0,
                "output.path": output,
            }
        ),
        encoding="utf-8",
    )
    assert shape_wizard.run_from_config(str(recipe)) == 0
    assert output.is_file()
