"""Interactive container-browse wizard (the terminal half of :mod:`titan.u7.container`)."""

from __future__ import annotations


from typing import Optional
from titan import _wizard_ui as ui
from titan.errors import exit_code


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


def run_wizard(
    static_dir: Optional[str] = None,
    gamedat_dir: Optional[str] = None,
    text_flx: Optional[str] = None,
    exult_flx_path: Optional[str] = None,
    mod_data_dir: Optional[str] = None,
    map_num: int = 0,
    game: str = "bg",
    custom_game: bool = False,
) -> int:
    """Interactive questionary container-browse wizard. Returns exit code."""
    try:
        import questionary
    except ImportError:
        print("questionary is required for the interactive wizard.")
        print("Install it with: pip install questionary>=2.0")
        return 1

    _SEP = "─" * 55
    print()
    print("  U7 Container Browse")
    print(f"  {_SEP}")

    from titan.u7.target_picker import SelectionCancelled, select_world
    from titan.u7.world import WorldQueryParams

    try:
        world = select_world(
            questionary,
            WorldQueryParams(
                static_dir=static_dir or "",
                gamedat_dir=gamedat_dir,
                text_flx_path=text_flx,
                mod_data_dir=mod_data_dir,
                game=game,
                map_num=map_num,
            ),
            require_gamedat=True,
        )
    except (SelectionCancelled, KeyboardInterrupt, EOFError):
        return ui.cancelled()
    from titan.u7.container_browser import load_u7_container_session
    from titan.u7.container_browser_ui import browse_u7_container_session

    if world.game != game or exult_flx_path is None:
        from titan.u7.install import resolve_u7_exult_flx

        exult_flx_path = resolve_u7_exult_flx(world.game)
    try:
        print("  Capturing containers and nested contents…")
        session = load_u7_container_session(
            world, exult_flx=exult_flx_path, custom_game=custom_game
        )
        browse_u7_container_session(session)
        return 0
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        return ui.cancelled()
    except (ValueError, OSError) as error:
        print(f"  U7 container browser unavailable: {error}")
        return exit_code(error)
