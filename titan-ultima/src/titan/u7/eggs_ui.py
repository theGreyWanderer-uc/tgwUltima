"""Interactive egg-query wizard for `titan u7 egg-query` (the terminal half of :mod:`titan.u7.eggs`)."""

from __future__ import annotations


from pathlib import Path
from typing import Optional
from titan import _wizard_ui as ui

from titan.u7.map import (
    EGG_TYPE_NAMES,
    C_NUM_SCHUNKS,
    C_CHUNKS_PER_SCHUNK,
    C_TILES_PER_CHUNK,
)


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


from titan.u7.eggs import (
    EggQueryParams,
    format_results,
    query_eggs,
)


def run_wizard(
    static_dir: Optional[str] = None,
    gamedat_dir: Optional[str] = None,
    *,
    game: str = "bg",
) -> int:
    """Interactive questionary egg-query wizard. Returns exit code."""
    try:
        import questionary
    except ImportError:
        print("questionary is required for the interactive wizard.")
        print("Install it with: pip install questionary>=2.0")
        return 1

    _SEP = "─" * 55
    print()
    print("  U7 Egg Query")
    print(f"  {_SEP}")

    from titan.u7.target_picker import SelectionCancelled, select_world
    from titan.u7.world import WorldQueryParams

    try:
        world = select_world(
            questionary,
            WorldQueryParams(
                static_dir=static_dir or "", gamedat_dir=gamedat_dir, game=game
            ),
            require_gamedat=True,
        )
    except (SelectionCancelled, KeyboardInterrupt, EOFError):
        return 0
    static_dir, gamedat_dir = world.static_dir, world.gamedat_dir

    # ── 1. Paths ─────────────────────────────────────────────────────────────
    if not static_dir:
        static_dir = ui.path_prompt(
            "STATIC directory:", q=questionary, only_directories=True
        ).ask()
        if static_dir is None:
            return 0

    if not gamedat_dir:
        gamedat_dir = ui.path_prompt(
            "GAMEDAT directory:", q=questionary, only_directories=True
        ).ask()
        if not gamedat_dir:
            return 0

    # ── 2. Egg type filter ────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    type_choices = [v for k, v in sorted(EGG_TYPE_NAMES.items()) if k < 128]
    selected_types: list[str] = (
        questionary.checkbox(
            "Filter by egg type? (space to toggle, leave blank for all)",
            choices=type_choices,
        ).ask()
        or []
    )
    if selected_types is None:
        return 0

    # ── 3. Usecode function filter ────────────────────────────────────────────
    fn_filter: Optional[int] = None
    if not selected_types or "usecode" in selected_types:
        print()
        print(f"  {_SEP}")
        fn_raw = questionary.text(
            "Filter by usecode function number? (hex or decimal, leave blank for all)",
            default="",
        ).ask()
        if fn_raw is None:
            return 0
        fn_raw = fn_raw.strip()
        if fn_raw:
            try:
                fn_filter = int(fn_raw, 0)
            except ValueError:
                print(f"  Invalid function number {fn_raw!r} — ignored.")

    # ── 4. Area ───────────────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    area_all = questionary.confirm("Search the entire world?", default=True).ask()
    if area_all is None:
        return 0

    superchunks: list[int] = []
    tile_rect: Optional[tuple[int, int, int, int]] = None

    if not area_all:
        area_type = ui.select(
            "Area filter type:",
            q=questionary,
            choices=["Superchunks", "Tile rectangle"],
        ).ask()
        if area_type is None:
            return 0

        if area_type == "Superchunks":
            sc_input = questionary.text(
                "Superchunk numbers (hex or decimal, comma-separated):",
                default="",
            ).ask()
            if sc_input is None:
                return 0
            for token in sc_input.split(","):
                token = token.strip()
                try:
                    superchunks.append(int(token, 0))
                except ValueError:
                    pass
        else:
            _TILE_MAX = C_NUM_SCHUNKS * C_CHUNKS_PER_SCHUNK * C_TILES_PER_CHUNK - 1
            print(f"  Tile coordinates are 0–{_TILE_MAX} on each axis.")
            tx0_raw = questionary.text("Top-left tile X:").ask()
            ty0_raw = questionary.text("Top-left tile Y:").ask()
            tx1_raw = questionary.text("Bottom-right tile X:").ask()
            ty1_raw = questionary.text("Bottom-right tile Y:").ask()
            if None in (tx0_raw, ty0_raw, tx1_raw, ty1_raw):
                return 0
            try:
                tx0 = int(tx0_raw.strip(), 0)
                ty0 = int(ty0_raw.strip(), 0)
                tx1 = int(tx1_raw.strip(), 0)
                ty1 = int(ty1_raw.strip(), 0)
                tile_rect = (min(tx0, tx1), min(ty0, ty1), max(tx0, tx1), max(ty0, ty1))
            except ValueError:
                print("  Invalid coordinates — searching entire world.")

    # ── 5. Output ─────────────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    fmt = ui.select(
        "Output format:",
        q=questionary,
        choices=["table", "csv"],
        default="table",
    ).ask()
    if fmt is None:
        return 0

    output_path: Optional[str] = None
    if questionary.confirm("Save output to a file?", default=False).ask():
        output_path = ui.path_prompt("Output file path:", q=questionary).ask()

    # ── Run ───────────────────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    print("  Scanning…")

    params = EggQueryParams(
        static_dir=static_dir,
        gamedat_dir=gamedat_dir,
        egg_types=selected_types,
        fn_filter=fn_filter,
        superchunks=superchunks,
        tile_rect=tile_rect,
        output_format=fmt,
        output_path=output_path,
        patch_dir=world.patch_dir,
        map_num=world.map_num,
    )

    results = query_eggs(params)
    output = format_results(results, params)

    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        print(f"  Wrote {len(results)} egg(s) to {output_path}")
    else:
        print()
        print(output)

    return 0
