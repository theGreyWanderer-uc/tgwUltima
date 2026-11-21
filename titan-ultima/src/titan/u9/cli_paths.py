"""Resolve U9 CLI inputs before Click converts positional IDs and options.

The command parser adapter keeps existing FILE ID syntax working while allowing
ID alone when FILE has a configured default. Outputs and user-authored inputs
(PNGs, CSVs, plans, replacement directories and comparison saves) stay explicit.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any

import typer
from typer.core import TyperArgument, TyperCommand, TyperOption

from titan.u9 import inputs as _inputs
from titan.u9.inputs import NO_DEFAULT as _NO_DEFAULT, U9InputError
from titan.u9.install import U9_FILE_PATHS

# Typer 0.29 vendors its own Click and converts values through a runtime
# coercer instead of `parameter.type`; its failures may be a plain UsageError
# (e.g. from the pydantic adapter), not only BadParameter. BadParameter
# subclasses UsageError in both Click and Typer's copy, so take it from there.
_USAGE_ERROR: type[Exception] = next(
    cls for cls in typer.BadParameter.__mro__ if cls.__name__ == "UsageError"
)


def _convert_argument(parameter: Any, raw: Any, ctx: Any) -> Any:
    """Convert one raw token the way the installed Typer will."""
    runtime = getattr(parameter, "get_runtime_param", None)
    if runtime is not None:  # typer >= 0.29
        return runtime().coerce(raw, param=parameter, ctx=ctx)
    return parameter.type.convert(raw, parameter, ctx)


# Each mapping names the CLI parameter and its [u9.paths] resource. Literal
# command names keep both the command and its resource mapping searchable.
U9_COMMAND_INPUTS = {
    command: resources
    for commands, resources in (
        (
            ("flx-list", "flx-extract", "flx-extract-all", "flx-repack"),
            {"file": "archive"},
        ),
        (("typename-dump", "typename-csv", "typename-import"), {"file": "typenames"}),
        (("types-csv",), {"file": "types", "typenames": "typenames"}),
        (("sound-category-list", "sound-category-csv"), {"file": "categories"}),
        (("sound-environment-list", "sound-environment-csv"), {"file": "environments"}),
        (
            ("sound-template-csv",),
            {"file": "templates", "categories": "categories", "sounds": "sfx"},
        ),
        (
            ("sound-association-csv",),
            {
                "file": "associations",
                "templates": "templates",
                "types": "types",
                "typenames": "typenames",
            },
        ),
        (("palette-info", "palette-export"), {"file": "palette"}),
        (("sound-list", "sound-extract", "sound-extract-pcm"), {"file": "archive"}),
        (("sound-import", "sound-import-batch"), {"archive": "archive"}),
        (("sound-report",), {"source": "sound"}),
        (
            ("model-info",),
            {"file": "sappear", "types": "types", "typenames": "typenames"},
        ),
        (
            ("model-export", "model-export-all"),
            {
                "file": "sappear",
                "textures": "textures",
                "palette": "palette",
                "types": "types",
                "typenames": "typenames",
            },
        ),
        (
            ("model-material-report",),
            {
                "source": "sappear",
                "textures": "static",
                "types": "types",
                "typenames": "typenames",
            },
        ),
        (("texture-info",), {"textures": "textures"}),
        (("texture-export-all",), {"source": "static", "palette": "palette"}),
        (
            ("texture-export", "texture-import", "icon-export"),
            {"textures": "textures", "palette": "palette"},
        ),
        (
            ("texture-frame-report",),
            {
                "source": "static",
                "sappear": "sappear",
                "types": "types",
                "typenames": "typenames",
            },
        ),
        (
            ("icon-list", "icon-export-all"),
            {"file": "sappear", "textures": "textures", "palette": "palette"},
        ),
        (
            ("nonfixed-info", "nonfixed-chunks", "nonfixed-entities"),
            {"file": "nonfixed", "typenames": "typenames"},
        ),
        (
            ("nonfixed-diff",),
            {"left": "nonfixed", "right": "nonfixed", "typenames": "typenames"},
        ),
        (("highway-info", "highway-points", "highway-routes"), {"file": "highway"}),
        (("animation-list", "animation-show"), {"file": "animations"}),
        (
            ("animation-library-plan", "animation-model-report"),
            {
                "file": "animations",
                "sappear": "sappear",
                "registry": "registry",
                "types": "types",
                "typenames": "typenames",
            },
        ),
        (
            (
                "animation-pose-export",
                "animation-bundle-export",
                "animation-set-export",
                "avatar-animation-library-export",
                "animation-library-export",
            ),
            {
                "animations": "animations",
                "sappear": "sappear",
                "registry": "registry",
                "textures": "textures",
                "palette": "palette",
            },
        ),
        (
            ("dimension-info", "dimension-show", "dimension-csv"),
            {"file": "dimension", "models": "sappear"},
        ),
        (("spaces-info", "spaces-show", "spaces-csv"), {"file": "spaces"}),
        (
            ("treedat-info", "treedat-show", "treedat-csv"),
            {"file": "treedat", "spaces": "spaces"},
        ),
        (("areas-info", "areas-show", "areas-csv"), {"file": "areas"}),
        (("trigger-list", "trigger-show", "trigger-opcodes"), {"file": "triggers"}),
        (
            ("activity-list", "activity-show", "activity-opcodes"),
            {"file": "activities"},
        ),
        (
            ("script-research-export",),
            {"triggers": "triggers", "activities": "activities"},
        ),
        (
            ("npc-list", "npc-show", "npc-classes", "npc-csv"),
            {"file": "npcs"},
        ),
        (("npc-diff",), {"file": "npcs", "save_file": "save_source"}),
        (("sdinfo-list", "sdinfo-show"), {"file": "sdinfo16"}),
        (("sdinfo-verify",), {"file": "sdinfo16", "textures": "textures"}),
        (
            ("text-list", "text-blocks", "text-search", "text-export", "text-import"),
            {"file": "text"},
        ),
        (
            ("books-list", "books-show", "books-search", "books-export"),
            {"file": "books"},
        ),
        (
            ("text-keys-info", "text-key-lookup", "text-keys-export"),
            {"file": "text_keys", "text": "text", "npcs": "npcs"},
        ),
        (("shade-info", "shade-csv"), {"file": "shade", "palette": "palette"}),
        (
            ("color-cube-info", "color-cube-lookup", "color-cube-csv"),
            {"file": "color_cube", "palette": "palette"},
        ),
        (
            ("save-check",),
            {
                "target": "base",
                "static": "static",
                "fixed_reference": "fixed_reference",
            },
        ),
        (
            ("save-browse",),
            {
                "source": "save_source",
                "game_dir": "base",
                "static": "static",
                "fixed_reference": "fixed_reference",
            },
        ),
        (
            ("fixed-info", "fixed-chunks", "fixed-objects", "fixed-types"),
            {"file": "fixed", "typenames": "typenames"},
        ),
        (
            (
                "terrain-info",
                "terrain-tiles",
                "terrain-chunk",
                "terrain-textures",
                "terrain-heightmap",
                "terrain-export",
            ),
            {"file": "terrain", "sdinfo": "sdinfo16"},
        ),
        (
            ("map-atlas",),
            {
                "static": "static",
                "runtime": "runtime",
                "textures": "textures",
                "models": "sappear",
                "types": "types",
                "palette": "palette",
                "sdinfo": "sdinfo16",
            },
        ),
        (
            ("map-render", "map-export-glb"),
            {
                "terrain": "terrain",
                "textures": "textures",
                "fixed": "fixed",
                "nonfixed": "nonfixed",
                "models": "sappear",
                "types": "types",
                "palette": "palette",
                "sdinfo": "sdinfo16",
            },
        ),
        # These consume user-generated files, not installed game resources.
        (("map-render-3d", "flx-pack"), {}),
    )
    for command in commands
}
_UNSET: Any = object()


def _configured_install() -> Any:
    from titan._meta import configured_install

    return configured_install("u9")


def paired_u9_texture_key(owner: str, install: Any = _UNSET) -> str | None:
    """:func:`titan.u9.inputs.paired_u9_texture_key`, using the configured install by default."""
    if install is _UNSET:
        install = _configured_install()
    return _inputs.paired_u9_texture_key(owner, install)


def resolve_u9_input(
    value: str | None, key: str, *, owner: str | None = None, install: Any = _UNSET
) -> str | None:
    """:func:`titan.u9.inputs.resolve_u9_input`, using the configured install by default.

    An ambiguous name is a usage error, as Click reports bad values.
    """
    if install is _UNSET:
        install = _configured_install()
    try:
        return _inputs.resolve_u9_input(value, key, owner=owner, install=install)
    except U9InputError as error:
        raise typer.BadParameter(str(error)) from error


def _report_missing(key: str, install: Any) -> None:
    """A ``[u9.paths]`` entry for *key* that points at nothing is a setup error."""
    if install is None:
        return
    for name in dict.fromkeys([key, "bitmap16" if key == "textures" else key]):
        if install.problems.get(name) == "NOT FOUND":
            from titan._input_fill import configured_path

            configured_path("u9", name)  # raises ConfigFileError naming the path


class _U9InputParser:
    """Adapt Click's raw parse result before its normal type conversion runs."""

    def __init__(self, parser: Any, command: ConfiguredU9Command, ctx: Any):
        self.parser = parser
        self.command = command
        self.ctx = ctx

    def __getattr__(self, name: str) -> Any:
        return getattr(self.parser, name)

    def parse_args(self, args: list[str]) -> Any:
        values, remaining, order = self.parser.parse_args(args)
        if not remaining and not values.get("help") and not self.ctx.resilient_parsing:
            values = self.command.resolve_inputs(self.ctx, values)
        return values, remaining, order


class ConfiguredU9Command(TyperCommand):
    """A U9 command with explicit per-parameter game-resource defaults."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.inputs = U9_COMMAND_INPUTS.get(self.name or "", {})
        for parameter in self.params:
            if (
                isinstance(parameter, TyperArgument)
                and self.inputs.get(parameter.name or "") not in _NO_DEFAULT
                and parameter.name in self.inputs
            ):
                parameter.required = False
        if self.inputs:
            self.epilog = (
                (self.epilog or "")
                + "\nGame inputs use u9.game / u9.paths in titan.toml when omitted. Bare game filenames resolve under configured folders. Explicit paths take precedence. IDs, search terms and user-created inputs remain required."
            )

    def make_parser(self, ctx: Any) -> Any:
        return _U9InputParser(super().make_parser(ctx), self, ctx)

    def resolve_inputs(self, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
        """Fill game paths without shifting or defaulting user-authored inputs."""
        arguments = [
            parameter
            for parameter in self.params
            if isinstance(parameter, TyperArgument)
        ]
        tokens = [
            values[parameter.name or ""]
            for parameter in arguments
            if values.get(parameter.name or "") is not None
        ]
        omittable = [
            parameter.name or ""
            for parameter in arguments
            if parameter.name in self.inputs
            and self.inputs[parameter.name] not in _NO_DEFAULT
        ]
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        for count in range(len(omittable) + 1):
            for omitted in combinations(omittable, count):
                assigned: dict[str, Any] = {}
                cursor = 0
                score = 0
                for parameter in arguments:
                    name = parameter.name or ""
                    if name in omitted:
                        assigned[name] = None
                        continue
                    if cursor >= len(tokens):
                        if parameter.required:
                            break
                        assigned[name] = None
                        continue
                    raw = tokens[cursor]
                    try:
                        _convert_argument(parameter, raw, ctx)
                    except _USAGE_ERROR:
                        break
                    assigned[name] = raw
                    cursor += 1
                    key = self.inputs.get(name or "")
                    if key == "textures":
                        key = "bitmap16"
                    if (
                        key in U9_FILE_PATHS
                        and Path(str(raw)).name.casefold()
                        == U9_FILE_PATHS[key][1].casefold()
                    ):
                        score += 1
                else:
                    if cursor == len(tokens):
                        candidates.append((count, -score, assigned))
            if candidates:
                break
        if not candidates:
            return values  # Preserve Click's existing missing/invalid argument errors.
        _, _, assigned = min(candidates, key=lambda candidate: candidate[:2])
        values.update(assigned)
        install = _configured_install()
        owner = None
        for parameter in arguments:
            name = parameter.name or ""
            if name not in self.inputs:
                continue
            key = self.inputs[name]
            if key == "npcs" and values.get("save"):
                key = "processes"
            if values.get(name) is None:
                _report_missing(key, install)
            resolved = resolve_u9_input(
                values.get(name), key, owner=owner, install=install
            )
            if resolved is None:
                if (
                    not parameter.required
                    and name == "source"
                    and self.name == "save-browse"
                ):
                    continue
                raise typer.BadParameter(
                    f"No U9 input for {name.upper()}. Supply a path or run 'titan setup' to configure [u9.paths].",
                    ctx,
                )
            values[name] = resolved
            if owner is None:
                owner = resolved
        for option in self.params:
            name = option.name or ""
            if not isinstance(option, TyperOption) or name not in self.inputs:
                continue
            companion_owner = owner
            if self.inputs[name] in {"palette", "sdinfo16"}:
                companion_owner = values.get("textures") or owner
            if values.get(name) is None:
                _report_missing(self.inputs[name], install)
            resolved = resolve_u9_input(
                values.get(name),
                self.inputs[name],
                owner=companion_owner,
                install=install,
            )
            if resolved is not None:
                values[name] = resolved
                if owner is None and name == "game_dir":
                    owner = resolved
        return values


class ConfiguredU9App(typer.Typer):
    """Register every U9 command with the shared config-aware path parser."""

    def command(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("cls", ConfiguredU9Command)
        return super().command(*args, **kwargs)
