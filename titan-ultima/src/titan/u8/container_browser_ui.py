"""U8 container browser menus, native PNG previews and fresh inventory exports."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import typer

from titan import _wizard_ui as ui
from titan._config import cfg
from titan._image_preview import open_preview
from titan._inventory_browser import InventoryBrowser, InventoryFilters
from titan.u8.container_browser import (
    U8_CONTAINER_BROWSER_OUTPUT,
    U8ContainerSession,
    build_u8_container_session,
    export_u8_container_bundle,
    u8_container_gump_composition,
    u8_container_gump_images,
    u8_container_item_image,
    u8_inventory_rows,
    validate_u8_container_output,
)
from titan.u8.map_browser import load_u8_map_session
from titan.u8.container_gump import U8ContainerGumpPreview
from titan.u8.container_records import (
    U8InventoryId,
    parse_u8_inventory_id,
    u8_inventory_file_stem,
    u8_inventory_identity_label,
)
from titan.u8.map_browser_ui import browse_u8_map_session
from titan.u8.npc_browser_ui import browse_u8_npc_session
from titan.u8.save_browser import next_u8_save_browser_export
from titan.u8.save_browser_ui import choose_u8_save_browser_source
from titan.u8.save_state import U8SaveSnapshot
from titan.u8.shape_browser import find_u8_browser_file, load_u8_shape_library
from titan.u8.shape_browser_ui import browse_u8_npc_shape, choose_u8_shape_target

PAGE_SIZE = 25


def _container_menu(title: str, labels: dict[str, str], default: str = "B") -> str:
    ui.legacy_menu(title, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice(
        "> ",
        list(labels),
        default if default in labels else next(iter(labels)),
        labels=labels,
        message=title,
        hotkeys=True,
    )


def _container_label(session: U8ContainerSession, number: U8InventoryId) -> str:
    row = session.items[number]
    label = row["npc_label"] or row["shape_name"] or f"Shape {row['shape']}"
    return f"{u8_inventory_identity_label(row)} — {label}; map {row['map_id']}; shape {row['shape']}, frame {row['frame']}; contents {row['child_count']}; owner {row['owner_name'] or '—'}"


def _container_export(
    session: U8ContainerSession, output: Path, number: U8InventoryId | None
) -> Path:
    stem = session.snapshot.source.stem + (
        f"_cache_{number:04d}"
        if isinstance(number, int)
        else f"_{u8_inventory_file_stem(number)}"
        if number is not None
        else "_all_containers"
    )
    if number is None and session.filter_map is not None:
        stem += f"_map_{session.filter_map:03d}"
    target = next_u8_save_browser_export(output, stem)
    result = export_u8_container_bundle(session, target, container=number)
    print(f"  Exported: {result}")
    return result


def _u8_inventory_flow(
    session: U8ContainerSession, output: Path, previews: Path
) -> InventoryBrowser:
    """Adapt captured U8 records and native actions to the shared browser flow."""

    def actions(number: U8InventoryId) -> dict[str, str]:
        row = session.items[number]
        labels = {"V": "Preview item sprite in image viewer", "S": "Open shape browser"}
        if number in session.containers:
            labels.update(
                {
                    "G": "Preview gump with inventory (random layout rerolls)",
                    "H": "Preview empty gump artwork",
                    "L": "Choose random / saved item positions",
                }
            )
        if session.npc_session and row["owner_npc_id"] is not None:
            labels["N"] = "Open owning NPC browser"
        if session.library and row["map_id"] is not None:
            labels["M"] = "Open map browser for top-level owner"
        return labels

    def perform(selected: str, number: U8InventoryId, counter: int) -> None:
        row = session.items[number]
        if selected == "V":
            target = next_u8_save_browser_export(
                previews, f"item_{u8_inventory_file_stem(number)}", ".png"
            )
            u8_container_item_image(session, number).save(target)
            print(f"  Preview: {target}")
            open_preview(target)
        elif selected in {"G", "H"}:
            preview_u8_container_gump(
                session,
                number,
                previews,
                seed=session.gump_seed + counter,
                empty=selected == "H",
            )
        elif selected == "L":
            layout = _container_menu(
                "Gump item positions:",
                {"R": "Random scatter", "S": "Saved anchors; scatter unset positions"},
                "R" if session.gump_layout == "random" else "S",
            )
            session.gump_layout = "random" if layout == "R" else "saved"
        elif selected == "S":
            if session.library is None:
                raise ValueError("world graphics unavailable; restart with --shapes")
            browse_u8_npc_shape(
                session.library,
                row["shape"],
                frame=row["frame"],
                output=output / "shapes",
            )
        elif selected == "N" and session.npc_session:
            browse_u8_npc_session(
                session.npc_session, npc=row["owner_npc_id"], output=output / "npcs"
            )
        elif selected == "M" and session.library:
            maps = load_u8_map_session(
                session.library, snapshot=session.snapshot, fixed=session.fixed_path
            )
            maps.npc_session = session.npc_session
            browse_u8_map_session(maps, map_id=row["map_id"], output=output / "maps")

    def export(numbers, number, selection) -> None:
        if number is not None:
            _container_export(session, output, number)
            return
        target = next_u8_save_browser_export(
            output, session.snapshot.source.stem + "_" + selection["scope"]
        )
        report = export_u8_container_bundle(
            session, target, containers=numbers, selection=selection
        )
        print(f"  Exported: {report}")

    return InventoryBrowser(
        f"Source: {session.snapshot.source}",
        session.items,
        session.children,
        session.containers,
        export,
        actions,
        perform,
        parse_u8_inventory_id,
        menu=_container_menu,
        filters=InventoryFilters(map_id=session.filter_map),
        kinds={
            "all": "All inventories",
            "npc": "NPC inventories",
            "container": "Containers",
            "cache": "Live cache",
            "stored": "Stored maps",
            "diagnostics": "Diagnostics",
        },
        diagnostics=session.diagnostics,
    )


def _browse_inventory(
    session: U8ContainerSession,
    number: U8InventoryId,
    output: Path,
    previews: Path,
    *,
    back_label: str = "Back to container list",
) -> None:
    _u8_inventory_flow(session, output, previews).inspect(number, back_label=back_label)


def preview_u8_container_gump(
    session: U8ContainerSession,
    number: U8InventoryId,
    previews: Path,
    *,
    seed: int | None = None,
    empty: bool = False,
) -> list[Path]:
    """Open even empty NPC inventories; keep source pixels and diagnose viewer failures."""
    validate_u8_container_output(session, previews)
    row = session.items[number]
    images = u8_container_gump_images(session, number)
    if not images:
        print(
            "  Gump graphics are unavailable; supply matching U8GUMPS.FLX."
            if row["gump_previews"]
            else "  No saved gump, verified mapping or NPC fallback is available for this item."
        )
        return []
    previews.mkdir(parents=True, exist_ok=True)
    targets = []
    for metadata, (_, image) in zip(row["gump_previews"], images):
        preview = U8ContainerGumpPreview(**metadata)
        if not empty:
            composition = u8_container_gump_composition(
                session, number, preview, seed=seed
            )
            image = composition.image
            print(
                f"  {composition.layout} layout; {len(composition.placements)}/{row['child_count']} direct items; seed {composition.seed}"
            )
            if not row["child_count"]:
                print(
                    "  This NPC/container has no captured inventory items; opening empty artwork."
                )
            if composition.area:
                area = composition.area
                print(
                    f"  Storage bounds ({area.left}, {area.top})–({area.right}, {area.bottom}); {area.width}x{area.height} native pixels"
                )
            for issue in composition.diagnostics:
                print(f"  {issue}")
        target = next_u8_save_browser_export(
            previews,
            f"gump_{u8_inventory_file_stem(number)}_s{preview.shape}_f{preview.frame}",
            ".png",
        )
        image.save(target)
        targets.append(target)
        print(
            f"  {preview.description}: gump shape {preview.shape}, frame {preview.frame}; native image {image.width}x{image.height}: {target}"
        )
        if open_preview(target) is False:
            print(
                f"  Image viewer could not open the preview. Open this PNG manually: {target}"
            )
    return targets


def browse_u8_container_inventory(
    session: U8ContainerSession,
    number: U8InventoryId,
    *,
    output: Path = U8_CONTAINER_BROWSER_OUTPUT,
    back_label: str = "Back to parent browser",
) -> None:
    """Enter one captured inventory and return directly to its calling NPC browser."""
    validate_u8_container_output(session, output)
    u8_inventory_rows(session, number)
    with tempfile.TemporaryDirectory(prefix="titan-u8-inventory-") as temporary:
        _browse_inventory(
            session, number, output, Path(temporary), back_label=back_label
        )


def browse_u8_container_session(
    session: U8ContainerSession,
    *,
    container: U8InventoryId | None = None,
    output: Path = U8_CONTAINER_BROWSER_OUTPUT,
) -> None:
    """Use the shared persistent flow while retaining native U8 IDs and actions."""
    validate_u8_container_output(session, output)
    if container is not None:
        u8_inventory_rows(session, container)
    with tempfile.TemporaryDirectory(prefix="titan-u8-container-") as temporary:
        flow = _u8_inventory_flow(session, output, Path(temporary))
        flow.browse(container)


def run_u8_container_browser(
    *,
    source: Path | None = None,
    game_dir: Path | None = None,
    shapes: Path | None = None,
    palette: Path | None = None,
    gumps: Path | None = None,
    gumpage: Path | None = None,
    layout: str = "random",
    seed: int = 0,
    names: Path | None = None,
    container: U8InventoryId | None = None,
    fixed: Path | None = None,
    cache_only: bool = False,
    npc_backpack: bool = True,
    map_id: int | None = None,
    output: Path = U8_CONTAINER_BROWSER_OUTPUT,
    data_only: bool = False,
    export: bool = False,
) -> int:
    """Load source-bound inventories once; --export provides a repeatable batch path."""
    print("\nTitan U8 Container Browser")
    try:
        library = None
        gump_library = None
        if not data_only:
            configured = cfg("u8shapes")
            shapes = shapes or (
                Path(configured) if configured and not game_dir else None
            )
            if shapes is None:
                target = choose_u8_shape_target(game_dir)
                if target is None:
                    return 0
                shapes = find_u8_browser_file(target.static, "U8SHAPES.FLX")
                if shapes is None:
                    raise ValueError("U8SHAPES.FLX missing from selected STATIC")
            library = load_u8_shape_library(shapes, palette=palette)
            owner_gumps = gumps or find_u8_browser_file(
                library.path.parent, "U8GUMPS.FLX"
            )
            if owner_gumps:
                try:
                    gump_library = load_u8_shape_library(
                        owner_gumps, palette=library.palette_path
                    )
                except (ValueError, OSError) as error:
                    if gumps is not None:
                        raise
                    print(f"  Gump graphics unavailable: {error}")
        elif (
            shapes is not None
            or palette is not None
            or gumps is not None
            or gumpage is not None
        ):
            raise ValueError("--data-only cannot be combined with graphics options")
        source = source or choose_u8_save_browser_source(
            library.path.parent if library else game_dir
        )
        if source is None:
            return 0
        session = build_u8_container_session(
            U8SaveSnapshot.from_path(source),
            library,
            gumps=gump_library,
            names=names,
            gumpage=gumpage,
            layout=layout,
            seed=seed,
            fixed=fixed,
            include_stored=not cache_only,
            npc_backpack=npc_backpack,
            map_id=map_id,
        )
        validate_u8_container_output(session, output)
        print(
            f"  Coverage: {sum(isinstance(key, int) for key in session.containers)} live inventories; {sum(isinstance(key, str) for key in session.containers)} stored containers across {len(session.stored_maps)} unloaded maps"
        )
        if export:
            _container_export(session, output, container)
        else:
            browse_u8_container_session(session, container=container, output=output)
        return 0
    except (ui.PromptCancelled, KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0
    except (ValueError, OSError) as error:
        print(f"  ERROR: {error}")
        return 1


def container_browse_cmd(
    source: Annotated[
        Path | None,
        typer.Argument(help="Native U8SAVE or GAMEDAT; otherwise choose interactively"),
    ] = None,
    game_dir: Annotated[
        Path | None,
        typer.Option(
            "--game-dir", help="U8 installation, language or STATIC directory"
        ),
    ] = None,
    shapes: Annotated[
        Path | None,
        typer.Option("--shapes", help="Matching U8SHAPES.FLX world graphics"),
    ] = None,
    palette: Annotated[
        Path | None,
        typer.Option(
            "-p", "--palette", help="Matching U8PAL.PAL; otherwise graphics owner"
        ),
    ] = None,
    gumps: Annotated[
        Path | None,
        typer.Option("--gumps", help="Matching U8GUMPS.FLX; otherwise graphics owner"),
    ] = None,
    gumpage: Annotated[
        Path | None,
        typer.Option(
            "--gumpage",
            help="Matching GUMPAGE.DAT storage bounds; otherwise gump graphics owner",
        ),
    ] = None,
    layout: Annotated[
        str,
        typer.Option("--layout", help="Gump contents placement: random or saved"),
    ] = "random",
    seed: Annotated[
        int,
        typer.Option("--seed", help="Repeatable random layout seed; each G rerolls"),
    ] = 0,
    names: Annotated[
        Path | None, typer.Option("--names", help="Optional npc_id,name CSV overrides")
    ] = None,
    fixed: Annotated[
        Path | None,
        typer.Option(
            "--fixed", help="Matching FIXED.DAT; otherwise world graphics owner"
        ),
    ] = None,
    cache_only: Annotated[
        bool,
        typer.Option(
            "--cache-only", help="Restrict discovery to live ITEMCACH inventories"
        ),
    ] = False,
    npc_backpack: Annotated[
        bool,
        typer.Option(
            "--npc-backpack/--no-npc-backpack",
            help="Use labelled backpack previews for NPCs with no native gump",
        ),
    ] = True,
    map_id: Annotated[
        int | None,
        typer.Option(
            "--map",
            min=0,
            max=255,
            help="Initial map filter for the list and all-inventory export",
        ),
    ] = None,
    container: Annotated[
        str | None,
        typer.Option(
            "--container",
            help="Initial cache ID or FIXED:MAP:RECORD / NONFIXED:MAP:RECORD",
        ),
    ] = None,
    output: Annotated[
        Path,
        typer.Option(
            "-o", "--output", help="Export folder; each report uses a fresh directory"
        ),
    ] = U8_CONTAINER_BROWSER_OUTPUT,
    data_only: Annotated[
        bool,
        typer.Option(
            "--data-only",
            help="Inspect cache links without graphics; empty unidentified containers remain unknown",
        ),
    ] = False,
    export: Annotated[
        bool,
        typer.Option("--export", help="Export --container or all inventories and exit"),
    ] = False,
) -> None:
    """Browse U8 nested containers, NPC inventories, native previews and offline reports."""
    try:
        selected_container = (
            parse_u8_inventory_id(container) if container is not None else None
        )
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--container") from error
    raise SystemExit(
        run_u8_container_browser(
            source=source,
            game_dir=game_dir,
            shapes=shapes,
            palette=palette,
            gumps=gumps,
            gumpage=gumpage,
            layout=layout,
            seed=seed,
            names=names,
            container=selected_container,
            fixed=fixed,
            cache_only=cache_only,
            npc_backpack=npc_backpack,
            map_id=map_id,
            output=output,
            data_only=data_only,
            export=export,
        )
    )


def register_u8_container_browser(app: typer.Typer) -> None:
    """Register container-browse alongside the U8 map, NPC, shape and save browsers."""
    app.command("container-browse")(container_browse_cmd)
