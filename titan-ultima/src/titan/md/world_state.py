"""Select packaged or DOS-saved MD world data without interpreting it as U6 state."""

from pathlib import Path

from titan.md.game_profile import MD_PROFILE, resolve_martian_directory
from titan.u6.object import U6WorldObjects

__all__ = ["load_martian_objlist"]


def load_martian_objlist(
    gamedir: str | Path, savegame: str | Path | None = None
) -> bytes:
    """Read saved OBJLIST directly, or the initial state following MD's dungeon objects."""
    if savegame is not None:
        return (Path(savegame).expanduser() / "OBJLIST").read_bytes()
    directory = resolve_martian_directory(gamedir)
    return U6WorldObjects.from_directory(directory, profile=MD_PROFILE).objlist_tail
