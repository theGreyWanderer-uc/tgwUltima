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

from titan import _config
from titan.u9.install import U9_FILE_PATHS, configured_u9_path, existing_u9_path

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
_NUMBERED_RESOURCES = {"terrain": "static", "fixed": "static", "nonfixed": "runtime"}
_NO_DEFAULT = {"archive", "save_source", *_NUMBERED_RESOURCES}
_TIER_PARTNERS = {
    "bitmap16.flx": "sdinfo16",
    "bitmapc.flx": "sdinfoc",
    "bitmapsh.flx": "sdinfo",
    "sdinfo16.flx": "bitmap16",
    "sdinfoc.flx": "bitmapc",
    "sdinfo.flx": "bitmapsh",
}


def _configured_owner(owner: Path) -> bool:
    directories = [
        configured_u9_path(key)
        for key in ("base", "static", "runtime", "sound", "savegame")
    ]
    if any(
        directory is not None and (owner == directory or owner.parent == directory)
        for directory in directories
    ):
        return True
    return any(
        owner == configured_u9_path(key)
        for key in _config.get_config().get("u9", {}).get("paths", {})
    )


def paired_u9_texture_key(owner: str) -> str | None:
    """Choose the companion tier from its filename or a configured renamed file."""
    path = existing_u9_path(Path(owner).expanduser().absolute())
    paired = _TIER_PARTNERS.get(path.name.casefold())
    if paired:
        return paired
    for key, (_, filename) in U9_FILE_PATHS.items():
        if filename.casefold() not in _TIER_PARTNERS:
            continue
        configured = configured_u9_path(key)
        if configured is not None and existing_u9_path(configured.absolute()) == path:
            return _TIER_PARTNERS[filename.casefold()]
    return None


def resolve_u9_input(
    value: str | None, key: str, *, owner: str | None = None
) -> str | None:
    """Prefer explicit U9 inputs, then config; keep external companions together."""
    original_key = key
    if key == "textures":
        key = "bitmap16"
    owner_path = Path(owner).expanduser() if owner else None
    partner_key = paired_u9_texture_key(owner) if owner else None
    if owner_path is not None and original_key in {"textures", "sdinfo16"}:
        key = partner_key or key
    folder_key = (
        U9_FILE_PATHS[key][0] if key in U9_FILE_PATHS else _NUMBERED_RESOURCES.get(key)
    )
    if key == "save_source":
        folder_key = "savegame"
    if value is not None:
        path = Path(value).expanduser()
        if path.is_absolute() or path.exists():
            return str(path)
        if len(path.parts) == 1:
            declared = _config.get_config().get("u9", {}).get("paths", {})
            for resource_key, (_, filename) in U9_FILE_PATHS.items():
                if (
                    resource_key in declared
                    and path.name.casefold() == filename.casefold()
                ):
                    override = configured_u9_path(resource_key)
                    if override is not None:
                        return str(override)
        if key in _NUMBERED_RESOURCES and value.isdecimal():
            path = Path(f"{key}.{int(value)}")
        candidates = []
        base = configured_u9_path("base")
        if base is not None and (len(path.parts) > 1 or path.name == folder_key):
            candidates.append(base / path)
        if owner_path is not None:
            candidates.append(
                (owner_path if owner_path.is_dir() else owner_path.parent) / path
            )
        for directory_key in (
            (folder_key,)
            if folder_key
            else ("static", "sound", "runtime", "savegame", "base")
        ):
            directory = configured_u9_path(directory_key)
            if directory is not None:
                candidates.append(directory / path)
        matches = list(
            dict.fromkeys(
                existing_u9_path(candidate)
                for candidate in candidates
                if existing_u9_path(candidate).exists()
            )
        )
        if len(matches) > 1 and key == "archive":
            raise typer.BadParameter(
                f"Ambiguous U9 archive {value!r}; supply its full path."
            )
        return str(matches[0]) if matches else value

    external = owner_path is not None and not _configured_owner(owner_path)
    explicit_paths = _config.get_config().get("u9", {}).get("paths", {})
    configured = configured_u9_path(key)
    if original_key == "textures" and not partner_key:
        configured = configured_u9_path("textures") or configured
    if not external and configured is not None:
        # A configured override is authoritative; do not silently replace a typo.
        if (
            original_key in explicit_paths
            or key in explicit_paths
            or configured.exists()
        ):
            return str(configured)
    if owner_path is not None and key in U9_FILE_PATHS:
        resource_folder, filename = U9_FILE_PATHS[key]
        parent = owner_path if owner_path.is_dir() else owner_path.parent
        adjacent = existing_u9_path(parent / filename)
        if adjacent.is_file():
            return str(adjacent)
        if parent.name.casefold() in {"static", "runtime", "sound", "savegame"}:
            sibling = existing_u9_path(parent.parent / resource_folder / filename)
            if sibling.is_file():
                return str(sibling)
    return None


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
                        parameter.type.convert(raw, parameter, ctx)
                    except typer.BadParameter:
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
        owner = None
        for parameter in arguments:
            name = parameter.name or ""
            if name not in self.inputs:
                continue
            key = self.inputs[name]
            if key == "npcs" and values.get("save"):
                key = "processes"
            resolved = resolve_u9_input(values.get(name), key, owner=owner)
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
            resolved = resolve_u9_input(
                values.get(name), self.inputs[name], owner=companion_owner
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
