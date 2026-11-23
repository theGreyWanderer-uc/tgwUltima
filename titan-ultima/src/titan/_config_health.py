"""Config drift: what in titan's config no longer matches what titan expects.

Three kinds, each a :class:`ConfigIssue`:

* ``shadowed``: a config file titan finds before the user config
  (:func:`titan._config.user_config_path`), so commands read an older copy.
* ``stale``: entries only an older ``titan setup`` wrote (:data:`STALE_RULES`).
* ``path``: a configured file or folder that no longer resolves, or a working
  folder that was never extracted.

:func:`config_report` finds them without changing anything; :func:`fix_config`
applies the fixes titan knows (backing up or renaming, never deleting). The CLI
shows them in ``titan config`` (``--fix`` applies them); front ends call these
functions. Library code: no printing.
"""

from __future__ import annotations

__all__ = [
    "ConfigIssue",
    "STALE_RULES",
    "config_report",
    "fix_config",
    "shadowing_config",
]

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional


@dataclass(frozen=True)
class ConfigIssue:
    """One way the config has drifted."""

    kind: str
    """``"shadowed"``, ``"stale"`` or ``"path"``."""
    severity: str
    """``"warning"`` (commands may misbehave) or ``"info"``."""
    title: str
    message: str
    file: Optional[Path]
    """The config file the issue is in (or is), if any."""
    action: str = ""
    """What :func:`fix_config` does: ``"retire"``, ``"prune"``, ``"migrate"``,
    ``"extract-u8"``; ``"setup"`` (run ``titan setup``) and ``""`` aren't automatic."""
    fix: str = ""
    """The fix in words, for a button or a hint."""
    key: str = ""
    """Stable id, so a front end can remember an issue someone chose to ignore. It
    includes the file's modification time where a change should bring it back."""

    @property
    def fixable(self) -> bool:
        return self.action in ("retire", "prune", "migrate", "extract-u8")


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def _mtime(path: Path) -> int:
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


def shadowing_config() -> Optional[Path]:
    """The config file titan reads instead of the user config, or ``None``.

    Only when both exist: a config found earlier in the search order (the current
    folder's ``titan.toml``, say) wins over the user config.
    """
    from titan._config import find_config, user_config_path

    user = user_config_path()
    found = find_config()
    if found is None or not user.is_file() or _same(found, user):
        return None
    return found


# --- stale entries --------------------------------------------------------


@dataclass(frozen=True)
class StaleRule:
    """Something only an older titan setup wrote, and how to find it."""

    id: str
    title: str
    message: str
    action: str
    fix: str
    applies: Callable[[dict], bool]
    """Called with the file's raw (unexpanded) TOML."""


def _legacy_u8_save(raw: dict) -> bool:
    import copy

    from titan.u8.install import prune_stale_u8_save_default

    return prune_stale_u8_save_default(copy.deepcopy(raw))


def _legacy_u8_layout(raw: dict) -> bool:
    from titan._config import has_legacy_u8_tables

    return has_legacy_u8_tables(raw)


STALE_RULES: tuple[StaleRule, ...] = (
    StaleRule(
        "u8-legacy-save",
        "Old default U8 save",
        '[u8.paths] nonfixed = "U8SAVE.000" was written by an older titan setup, '
        "and that save doesn't exist.",
        "prune",
        "Remove that line (titan reads it as no save already)",
        _legacy_u8_save,
    ),
    StaleRule(
        "u8-legacy-layout",
        "Old U8 config layout",
        "Top-level [game]/[paths] tables are titan's original U8-only layout; they "
        "belong under [u8].",
        "migrate",
        "Move them under [u8] (the file is backed up first)",
        _legacy_u8_layout,
    ),
)
"""Entries only an older ``titan setup`` wrote; ``titan setup`` and :func:`fix_config`
tidy them, never values someone set on purpose."""


# --- the report ------------------------------------------------------------


def _raw(path: Path) -> dict:
    from titan._config import _tomllib

    if _tomllib is None:
        return {}
    with open(path, "rb") as f:
        return _tomllib.load(f)


def _path_issues(path: Path) -> list[ConfigIssue]:
    from titan._config import read_config
    from titan._meta import GAMES, configured_install

    data = read_config(path)
    issues = []
    for game in GAMES:
        if not game.config_section or game.config_section not in data:
            continue
        try:
            install = configured_install(game.id, data)
        except Exception:  # noqa: BLE001 - one broken section must not hide the rest
            continue
        if install is None:
            continue
        section = game.config_section
        for key, status in sorted(install.problems.items()):
            if status == "NOT EXTRACTED" and game.id == "u8":
                from titan.u8.install import u8_working_archive

                if u8_working_archive(key, data) is None:
                    continue  # nothing to extract it from
                issues.append(
                    ConfigIssue(
                        "path",
                        "info",
                        "U8 map data not extracted",
                        f"[{section}.paths] {key} hasn't been extracted yet; U8 map commands "
                        "need it.",
                        path,
                        "extract-u8",
                        "Extract it now (U8SHAPES.FLX / GLOB.FLX)",
                        f"path:{section}:{key}:extract",
                    )
                )
            elif status == "NOT FOUND":
                issues.append(
                    ConfigIssue(
                        "path",
                        "warning",
                        f"{section}: {key} not found",
                        f"[{section}.paths] {key} points at something that doesn't exist.",
                        path,
                        "setup",
                        f"Run `titan setup` or fix [{section}.paths] {key}",
                        f"path:{section}:{key}:{_mtime(path)}",
                    )
                )
    return issues


def config_report(explicit: Optional[str] = None) -> list[ConfigIssue]:
    """Every drift titan can see, most serious first; changes nothing.

    *explicit* is a config path given on purpose (``--config``): then no other file
    can shadow it, and only that file is checked.
    """
    from titan._config import find_config, user_config_path

    issues: list[ConfigIssue] = []
    if explicit:
        active: Optional[Path] = Path(explicit).expanduser()
    else:
        active = find_config()
        shadow = shadowing_config()
        if shadow is not None:
            user = user_config_path()
            issues.append(
                ConfigIssue(
                    "shadowed",
                    "warning",
                    "titan is reading an older copy of its config",
                    f"{shadow} is found before your main config ({user}), so titan run from "
                    f"{shadow.parent} uses it instead.",
                    shadow,
                    "retire",
                    f"Rename it to {shadow.name}.old (nothing is deleted)",
                    f"shadowed:{shadow}:{_mtime(shadow)}",
                )
            )
    if active is None or not active.is_file():
        return issues
    files = [active]
    user = user_config_path()
    if not explicit and user.is_file() and not _same(user, active):
        files.append(user)  # the main config too: retiring the copy makes it active
    for path in files:
        try:
            raw = _raw(path)
        except Exception:  # noqa: BLE001 - a broken file is reported by load_config
            continue
        for rule in STALE_RULES:
            if rule.applies(raw):
                issues.append(
                    ConfigIssue(
                        "stale",
                        "warning",
                        rule.title,
                        rule.message,
                        path,
                        rule.action,
                        rule.fix,
                        f"stale:{rule.id}:{path}:{_mtime(path)}",
                    )
                )
    # A stale entry already explains its own missing path (the old U8SAVE.000).
    covered = (
        {("u8", "nonfixed")}
        if any(issue.key.startswith("stale:u8-legacy-save:") for issue in issues)
        else set()
    )
    issues += [
        issue
        for issue in _path_issues(active)
        if tuple(issue.key.split(":")[1:3]) not in covered
    ]
    order = {"warning": 0, "info": 1}
    return sorted(issues, key=lambda issue: order.get(issue.severity, 2))


# --- fixes -----------------------------------------------------------------


def _free_name(path: Path, suffix: str) -> Path:
    candidate = path.with_name(path.name + suffix)
    n = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}{suffix}.{n}")
        n += 1
    return candidate


def _backup(path: Path) -> Path:
    backup = _free_name(path, ".bak")
    backup.write_bytes(path.read_bytes())
    return backup


_LEGACY_SAVE_LINE = re.compile(
    r'^[ \t]*nonfixed[ \t]*=[ \t]*["\']U8SAVE\.000["\'][ \t]*(#.*)?\r?\n?', re.M
)


def _prune_legacy_save(path: Path) -> str:
    """Drop the ``nonfixed = "U8SAVE.000"`` line, keeping the rest of the file as is."""
    text = path.read_text(encoding="utf-8")
    section = re.search(
        r"^\[u8\.paths\][^\n]*\n(?P<body>(?:(?!^\[).*\n?)*)", text, re.M
    )
    if section is None:
        return ""
    body = section.group("body")
    pruned = _LEGACY_SAVE_LINE.sub("", body, count=1)
    if pruned == body:
        return ""
    backup = _backup(path)
    path.write_text(
        text[: section.start("body")] + pruned + text[section.end("body") :],
        encoding="utf-8",
    )
    return f'Removed nonfixed = "U8SAVE.000" from {path} (backup: {backup.name})'


def _migrate_layout(path: Path) -> str:
    import tomli_w

    from titan._config import migrate_legacy_u8

    raw = _raw(path)
    if not migrate_legacy_u8(raw):
        return ""
    backup = _backup(path)
    path.write_text(tomli_w.dumps(raw), encoding="utf-8")
    return f"Moved [game]/[paths] under [u8] in {path} (backup: {backup.name})"


def _retire(path: Path) -> str:
    retired = _free_name(path, ".old")
    os.replace(path, retired)
    return f"Renamed {path} to {retired.name}"


def fix_config(
    issues: Iterable[ConfigIssue], explicit: Optional[str] = None
) -> list[str]:
    """Apply the automatic fixes for *issues*; returns what was done, in words.

    Retiring renames the file (``.old``); edits back the file up first (``.bak``);
    U8 extraction writes only into titan's working folders. ``setup`` issues are
    left for ``titan setup``.
    """
    from titan._config import read_config

    done: list[str] = []
    issues = [issue for issue in issues if issue.fixable]
    # A file being set aside isn't edited first: its other issues go with it.
    retiring = {issue.file for issue in issues if issue.action == "retire"}
    for issue in sorted(issues, key=lambda i: i.action == "retire"):
        if issue.file is None or (
            issue.action != "extract-u8" and not issue.file.is_file()
        ):
            continue
        if issue.action != "retire" and issue.file in retiring:
            continue
        if issue.action == "prune":
            message = _prune_legacy_save(issue.file)
        elif issue.action == "migrate":
            message = _migrate_layout(issue.file)
        elif issue.action == "retire":
            message = _retire(issue.file)
        else:  # extract-u8
            from titan.u8.install import prepare_working_dirs

            extracted = prepare_working_dirs(read_config(issue.file))
            message = "; ".join(
                f"Extracted U8 {name}: {count} files -> {folder}"
                for name, folder, count in extracted
            )
        if message and message not in done:
            done.append(message)
    return done
