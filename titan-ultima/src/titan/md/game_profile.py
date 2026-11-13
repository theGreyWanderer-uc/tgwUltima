"""Martian Dreams resource names and initial animation state.

Storage and animation defaults were checked against Nuvie's TileManager.cpp
and the retail MD files. MD actor and save layouts live in the dedicated
md.actor and md.gamestate readers rather than inheriting U6 state offsets.
"""

from pathlib import Path

from titan.u6.game_profile import U6GameProfile

__all__ = ["MD_PROFILE", "resolve_martian_directory"]

MD_PROFILE = U6GameProfile(
    game_id="md",
    palette_filename="MDPAL",
    library_resources=frozenset(
        {"MASKTYPE.VGA", "MAPTILES.VGA", "LZOBJBLK", "LZDNGBLK", "LZMAP", "LOOK.LZC"}
    ),
    # Gameplay-controlled entries; md.map_animation resolves their state.
    inactive_animation_tiles=frozenset(
        {*range(1, 5), *range(16, 24), *range(616, 628), 1992, 1993, 1980, 1981}
    ),
    hidden_marker_tiles=frozenset(range(2041, 2048)),
)


def resolve_martian_directory(gamedir: str | Path) -> Path:
    """Resolve MARTIAN itself or the installation parent, requiring MD's own palette."""
    directory = Path(gamedir).expanduser()
    if (
        not (directory / "MDPAL").is_file()
        and (directory / "MARTIAN" / "MDPAL").is_file()
    ):
        directory /= "MARTIAN"
    if not (directory / "MDPAL").is_file():
        raise ValueError(
            f"Martian Dreams game directory must contain MDPAL: {directory}"
        )
    return directory
