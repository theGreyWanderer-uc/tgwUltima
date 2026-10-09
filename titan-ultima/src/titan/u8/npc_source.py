"""Paired native NPC sources shared by the browser and animation report command."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from titan.u8.avatar import U8AvatarState
from titan.u8.itemcach import U8ItemCache
from titan.u8.npcdata import U8NpcData
from titan.u8.save import U8SaveArchive
from titan.u8.shape_browser import find_u8_browser_file


@dataclass
class U8NpcSource:
    """NPCDATA and ITEMCACH from one selected snapshot; Avatar state is optional."""

    path: Path
    npcs: U8NpcData
    cache: U8ItemCache
    source_files: tuple[Path, ...]
    avatar: U8AvatarState | None = None
    diagnostics: list[str] = field(default_factory=list)


def load_u8_npc_source(path: Path, *, itemcach: Path | None = None) -> U8NpcSource:
    """Load native saves, GAMEDAT or loose NPCDATA with its paired cache, not another save."""
    path = path.expanduser().resolve()
    if path.is_dir():
        npc_path = find_u8_browser_file(path, "NPCDATA.DAT")
        cache_path = itemcach or find_u8_browser_file(path, "ITEMCACH.DAT")
        avatar_path = find_u8_browser_file(path, "AVATAR.DAT")
    else:
        npc_path = path
        native_save = U8SaveArchive.is_save_file(path.read_bytes())
        cache_path = itemcach or (
            path if native_save else find_u8_browser_file(path.parent, "ITEMCACH.DAT")
        )
        avatar_path = (
            path if native_save else find_u8_browser_file(path.parent, "AVATAR.DAT")
        )
        if native_save and U8SaveArchive.from_file(path).get_data("AVATAR.DAT") is None:
            avatar_path = None
    if npc_path is None or cache_path is None:
        raise ValueError(
            "NPC animation report requires paired NPCDATA.DAT and ITEMCACH.DAT"
        )
    source = U8NpcSource(
        path,
        U8NpcData.from_file(npc_path),
        U8ItemCache.from_file(cache_path),
        tuple(dict.fromkeys((npc_path.resolve(), cache_path.resolve()))),
    )
    if avatar_path is not None:
        if avatar_path.resolve() not in source.source_files:
            source.source_files += (avatar_path.resolve(),)
        try:
            source.avatar = U8AvatarState.from_file(avatar_path)
        except (ValueError, OSError) as error:
            source.diagnostics.append(f"Optional Avatar name unavailable: {error}")
    return source
