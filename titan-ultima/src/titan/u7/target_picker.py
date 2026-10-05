"""Shared interactive selection of archive owners and searchable worlds."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any, TYPE_CHECKING

from titan.fonts.exult_cfg import find_exult_cfg, parse_exult_cfg
from titan.u7.archive_targets import (
    ArchiveTarget,
    base_target,
    discover_targets,
    target_from_folder,
)
from titan.u7.install import existing_path, resolve_u7_path
from titan._wizard_ui import PromptCancelled as SelectionCancelled
from titan import _wizard_ui as ui

if TYPE_CHECKING:
    from titan.u7.world import WorldQueryParams


def ask(prompt: Any) -> Any:
    answer = prompt.ask()
    if answer is None:
        raise SelectionCancelled
    return answer


def game_targets(game: str) -> tuple[ArchiveTarget, list[ArchiveTarget]]:
    from titan._config import get_config

    config = get_config()
    cfg_path = find_exult_cfg()
    paths = None
    if cfg_path:
        try:
            paths = parse_exult_cfg(cfg_path, game)
        except (OSError, ValueError):
            pass
    static = resolve_u7_path(game, "static")
    return base_target(game, config, static, paths, cfg_path), discover_targets(
        game, config, static, paths, cfg_path
    )


def select_target(
    base: ArchiveTarget,
    targets: list[ArchiveTarget],
    *,
    q: Any = None,
    current: ArchiveTarget | None = None,
) -> ArchiveTarget:
    if q is None and ui.menus_enabled():
        import questionary as q
    choices = ([current] if current else []) + [base, *targets]
    if q:
        options = [
            q.Choice(
                f"{target.name} — {target.static or '(no STATIC)'}"
                + (
                    " | keep supplied paths"
                    if target is current
                    else f" | patch: {target.patch}"
                ),
                value="current" if target is current else target,
            )
            for target in choices
        ]
        options.append(q.Choice("Other mod or Exult game folder", value="manual"))
        selected = ask(
            ui.select(
                "Choose game/world target:",
                q=q,
                choices=options,
                default="current" if current else base,
            )
        )
        if selected == "current" and current:
            return current
    else:
        print(
            "\nChoose where the archive belongs (BG/SI above selects the game flavour):"
        )
        for index, target in enumerate(choices, 1):
            print(
                f"  [{index}] {target.name}"
                + (f" — {target.patch}" if index > 1 else "")
            )
        print(f"  [{len(choices) + 1}] Other mod or Exult game folder")
        while True:
            value = input("> ").strip() or "1"
            if value.isdigit() and 1 <= int(value) <= len(choices) + 1:
                selected = (
                    choices[int(value) - 1] if int(value) <= len(choices) else "manual"
                )
                break
            print("  Choose one of the listed numbers.")
    if isinstance(selected, ArchiveTarget):
        return selected
    while True:
        folder = (
            ask(
                ui.path_prompt(
                    "Mod root, Exult game root, or patch folder:",
                    q=q,
                    only_directories=True,
                )
            )
            if q
            else input("  Mod root, Exult game root, or patch folder: ")
            .strip()
            .strip('"')
        )
        try:
            return target_from_folder(Path(folder), base.static)
        except ValueError as error:
            print(f"  {error}")


def directory(q: Any, label: str, default: str = "") -> str:
    while True:
        value = ask(
            ui.path_prompt(label, q=q, default=default, only_directories=True)
        ).strip()
        path = existing_path(Path(value).expanduser())
        if value and path.is_dir():
            return str(path)
        print("  Enter an existing directory.")
        default = value


def select_map(q: Any, directories: list[str | None], default: int = 0) -> int:
    maps = {0}
    for value in directories:
        path = Path(value).expanduser() if value else None
        if path and path.is_dir():
            for child in path.iterdir():
                match = re.fullmatch(r"map([0-9a-f]{2})", child.name, re.IGNORECASE)
                if child.is_dir() and match:
                    maps.add(int(match[1], 16))
    maps.add(default)
    if q is None:
        values = {
            str(number): f"Map {number}"
            + (" (main world)" if number == 0 else f" (map{number:02x})")
            for number in sorted(maps)
        }
        values["M"] = "Other map number"
        ui.legacy_menu(
            "Choose map:", *(f"  [{key}] {label}" for key, label in values.items())
        )
        selected = ui.choice("> ", list(values), str(default), labels=values)
        if selected != "M":
            return int(selected)
        while True:
            try:
                number = int(
                    ui.text(f"  Map number (0-255) [{default}]: ", str(default)).strip()
                    or str(default),
                    0,
                )
                if 0 <= number <= 255:
                    return number
            except ValueError:
                pass
            print("  Enter a map number within 0-255.")
    options = [
        q.Choice(
            f"Map {number}"
            + (" (main world)" if number == 0 else f" (map{number:02x})"),
            value=number,
        )
        for number in sorted(maps)
    ]
    options.append(q.Choice("Other map number", value="manual"))
    selected = ask(ui.select("Choose map:", q=q, choices=options, default=default))
    if selected != "manual":
        return int(selected)
    while True:
        try:
            number = int(ask(q.text("Map number (0-255):", default=str(default))), 0)
            if 0 <= number <= 255:
                return number
        except ValueError:
            pass
        print("  Enter a map number within 0-255.")


def select_world(
    q: Any, params: WorldQueryParams, *, require_gamedat: bool = False
) -> WorldQueryParams:
    """Return WorldQueryParams with either preserved explicit paths or a new owner."""
    game = ask(
        ui.select(
            "Game flavour:",
            q=q,
            choices=[
                q.Choice("Black Gate", value="bg"),
                q.Choice("Serpent Isle", value="si"),
            ],
            default=params.game.lower(),
        )
    )
    base, targets = game_targets(game)
    current = (
        ArchiveTarget(
            "Current supplied world",
            Path(params.base_static or params.static_dir),
            Path(params.patch_dir) if params.patch_dir else Path(params.static_dir),
            gamedat=Path(params.gamedat_dir) if params.gamedat_dir else None,
        )
        if params.static_dir
        else None
    )
    target = select_target(base, targets, q=q, current=current)
    if target is current:
        selected = replace(params, game=game)
    else:
        static = str(target.static) if target.static else ""
        patch = str(target.patch) if target.patch.is_dir() else None
        selected = replace(
            params,
            game=game,
            static_dir=static,
            base_static=static or None,
            patch_dir=patch,
            mod_data_dir=patch,
            text_flx_path=None,
            gamedat_dir=str(target.gamedat)
            if target.gamedat and target.gamedat.is_dir()
            else None,
            output_path=None,
        )
    if not selected.static_dir or not Path(selected.static_dir).is_dir():
        selected.static_dir = directory(
            q, "Base STATIC directory:", selected.static_dir
        )
        selected.base_static = selected.static_dir
    if require_gamedat:
        selected.gamedat_dir = directory(
            q, "GAMEDAT directory for the selected world:", selected.gamedat_dir or ""
        )
    selected.map_num = select_map(
        q,
        [selected.static_dir, selected.patch_dir, selected.gamedat_dir],
        selected.map_num,
    )
    print(
        f"\nSelected world: {target.name} ({game.upper()} flavour), map {selected.map_num}"
    )
    print(f"  Base STATIC: {selected.base_static or selected.static_dir}")
    print(f"  Patch: {selected.patch_dir or '(none)'}")
    print(f"  GAMEDAT: {selected.gamedat_dir or '(select when including IREG)'}")
    return selected
