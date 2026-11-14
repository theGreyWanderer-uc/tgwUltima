"""Interactive U7 container browser session."""

from __future__ import annotations

from pathlib import Path

from titan._image_preview import open_preview
from titan._inventory_browser import InventoryBrowser, InventoryFilters
from titan._terminal_image import terminal_image
from titan.u7.container_browser import (
    U7ContainerSession,
    _next_export,
    export_u7_container_bundle,
    parse_u7_inventory_id,
    u7_container_gump_preview,
    u7_container_item_image,
    validate_u7_container_output,
)


U7_CONTAINER_BROWSER_OUTPUT = Path("titan-out/u7_container_browse_export")


def browse_u7_container_session(
    session: U7ContainerSession, *, output: Path = U7_CONTAINER_BROWSER_OUTPUT
) -> None:
    """Use the same result/filter/detail/tree/export flow as U8 on the selected U7 map."""
    validate_u7_container_output(session, output)

    def perform(action: str, number: int | str, counter: int) -> None:
        if action in {"G", "H"}:
            gump, composition, source = u7_container_gump_preview(
                session, number, contents=action == "G", seed=counter
            )
            if source.startswith("Preview locked"):
                print(f"  {source}; preview does not unlock the container.")
            output.mkdir(parents=True, exist_ok=True)
            path = _next_export(output, f"gump_{gump:03d}_preview", ".png")
            composition.image.save(path)
            print(
                f"  Gump {gump}, frame 0; {len(composition.placements)}/{len(session.children.get(number, [])) if action == 'G' else 0} direct items; {session.layout} layout; seed {counter}"
            )
            print(
                f"  Storage bounds: {composition.pixel_area}; native image {composition.image.width}x{composition.image.height}: {path}"
            )
            for message in composition.diagnostics:
                print(f"  {message}")
            if not open_preview(path):
                print(
                    f"  Viewer could not open the preview; open this file directly: {path}"
                )
        elif action == "L":
            choice = flow.menu(
                "Gump item positions:",
                {
                    "R": "Random positions (G rerolls)",
                    "S": "Saved IREG positions; arrange unplaced items",
                    "B": "Back",
                },
            )
            if choice != "B":
                session.layout = "random" if choice == "R" else "saved"
        elif action == "V":
            output.mkdir(parents=True, exist_ok=True)
            target = _next_export(output, "item_preview", ".png")
            u7_container_item_image(session, number).save(target)
            print(f"  Preview: {target}")
            open_preview(target)
        elif action == "S":
            frame = session.items[number]["frame"]
            while True:
                image = u7_container_item_image(session, number, frame=frame)
                print(f"  Shape {session.items[number]['shape']}, frame {frame}")
                terminal_image(image)
                choice = flow.menu(
                    "Shape frames:",
                    {
                        "F": "Next frame",
                        "P": "Previous frame",
                        "V": "Open frame in viewer",
                        "B": "Back to inventory",
                    },
                )
                if choice == "B":
                    return
                if choice == "V":
                    output.mkdir(parents=True, exist_ok=True)
                    path = _next_export(output, "frame_preview", ".png")
                    image.save(path)
                    open_preview(path)
                else:
                    if session.library is None:
                        raise ValueError(
                            "U7 container browser: artwork library unavailable"
                        )
                    count = len(
                        session.library.shape(session.items[number]["shape"]).frames
                    )
                    frame = (frame + (1 if choice == "F" else -1)) % count

    def export(numbers, number, selection) -> None:
        scope = (
            [
                number,
                *(
                    row["item_id"]
                    for row in flow.descendants(number)
                    if row["item_id"] in session.containers
                ),
            ]
            if number is not None
            else numbers
        )
        target = _next_export(
            output,
            f"{session.world.game}_map{session.world.map_num:02d}_{selection['scope']}",
        )
        print(
            f"  Exported: {export_u7_container_bundle(session, target, numbers=scope, selection=selection)}"
        )

    flow = InventoryBrowser(
        f"U7 {session.world.game}; source {session.world.gamedat_dir}; captured map {session.world.map_num}",
        session.items,
        session.children,
        session.containers,
        export,
        lambda number: {
            "V": "Preview item sprite in image viewer",
            "G": "Preview gump with inventory (random layout rerolls)",
            "H": "Preview empty gump artwork",
            "L": "Choose random / saved item positions",
            "S": "Open shape browser",
        },
        perform,
        parse_u7_inventory_id,
        filters=InventoryFilters(map_id=session.world.map_num),
        area_filters=True,
        diagnostics=session.diagnostics,
    )
    flow.browse()
