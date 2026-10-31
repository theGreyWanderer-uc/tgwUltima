"""Persistent U7 container browsing and fresh reports over captured IREG trees."""

from __future__ import annotations

import csv
import html
import io
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from titan._image_preview import open_preview
from titan._inventory_browser import (
    InventoryBrowser,
    InventoryFilters,
    inventory_descendants,
    inventory_name,
    inventory_tree,
)
from titan._terminal_image import terminal_image
from titan.u7 import container
from titan.u7.archive_targets import ArchiveTarget
from titan.u7.container_gump import (
    U7ContainerGumps,
    U7GumpComposition,
    U7GumpItemSprite,
    compose_u7_container_gump,
    load_u7_container_gumps,
)
from titan.u7.ireg import object_flag_names
from titan.u7.map import U7MapObject
from titan.u7.shape_browser import ShapeLibrary, load_library, owner_file
from titan.u7.world import WorldQueryParams, load_query_metadata, resolve_world_sources

U7_CONTAINER_BROWSER_OUTPUT = Path("titan-out/u7_container_browse_export")


def parse_u7_inventory_id(raw: str) -> str:
    """Accept IREG browser IDs in either case while returning their captured spelling."""
    prefix, separator, path = raw.strip().rpartition(":")
    return prefix.upper() + separator + ("root" if path.casefold() == "root" else path)


@dataclass
class U7ContainerSession:
    """One selected map's IREG objects; IDs are local browser identities, not save IDs."""

    world: WorldQueryParams
    items: dict[int | str, dict[str, Any]]
    children: dict[int | str, list[int | str]]
    containers: list[int | str]
    source_files: tuple[Path, ...]
    target: ArchiveTarget
    library: ShapeLibrary | None = None
    library_error: str | None = None
    diagnostics: list[str] = field(default_factory=list)
    gumps: U7ContainerGumps = field(default_factory=U7ContainerGumps)
    gump_library: ShapeLibrary | None = None
    layout: str = "random"


def load_u7_container_session(
    world: WorldQueryParams, *, exult_flx: str | None = None
) -> U7ContainerSession:
    """Capture selected-map roots, nested containers, frame names and mod metadata once."""
    if not world.gamedat_dir:
        raise ValueError("U7 container browser: select a GAMEDAT directory")
    if exult_flx is None:
        from titan.u7.cli import _resolve_u7_exult_flx

        exult_flx = _resolve_u7_exult_flx(world.game)
    tfa, names, frame_names, _ = load_query_metadata(world)
    base, patch = resolve_world_sources(world)
    diagnostics = []
    text_path = Path(world.text_flx_path) if world.text_flx_path else None
    if text_path is None:
        from titan.u7.shape_archive import find_archive

        text_path = (
            find_archive(patch, "TEXT.FLX") if patch else None
        ) or find_archive(base, "TEXT.FLX")
    if exult_flx and text_path:
        from titan.u7.names import U7FrameNames

        try:
            frame_names = U7FrameNames.from_flx(
                exult_flx, str(text_path), game=world.game
            )
            for directory in dict.fromkeys(
                str(path) for path in (patch, world.mod_data_dir) if path
            ):
                frame_names = (
                    U7FrameNames.from_mod_dir(
                        directory, str(text_path), base=frame_names
                    )
                    or frame_names
                )
        except (ValueError, OSError) as error:
            diagnostics.append(f"Per-frame names unavailable: {error}")
    params = container.ContainerQueryParams(
        world.static_dir,
        world.gamedat_dir,
        text_flx_path=world.text_flx_path,
        patch_dir=world.patch_dir,
        mod_data_dir=world.mod_data_dir,
        map_num=world.map_num,
    )
    roots = container.browse_containers(params)
    items: dict[int | str, dict[str, Any]] = {}
    children: dict[int | str, list[int | str]] = {}
    inventories: list[int | str] = []
    # Browser IDs distinguish repeated shapes and are stable for this captured map.
    for root_index, result in enumerate(roots):
        stack: list[tuple[U7MapObject, str | None, tuple[int, ...]]] = [
            (result.obj, None, ())
        ]
        while stack:
            obj, parent, path = stack.pop()
            number = f"IREG:{world.map_num}:{result.superchunk}:{root_index}:" + (
                ".".join(map(str, path)) or "root"
            )
            entry = tfa.get(obj.shape) if tfa else None
            shape_name = names.get(obj.shape) if names else ""
            item_name = (
                frame_names.get(obj.shape, obj.frame) if frame_names else ""
            ) or shape_name
            row = {
                "item_id": number,
                "identity_kind": "snapshot_browser_path",
                "container_id": parent,
                "shape": obj.shape,
                "frame": obj.frame,
                "shape_name": shape_name,
                "item_name": item_name,
                "x": result.world_tx,
                "y": result.world_ty,
                "z": result.world_tz,
                "stored_x": obj.tx,
                "stored_y": obj.ty,
                "stored_z": obj.tz,
                "map_id": world.map_num,
                "superchunk": result.superchunk,
                "archive_kind": "ireg",
                "quality": obj.quality,
                "quality_raw": obj.raw_quality,
                "quantity": obj.quality if entry and entry.has_quantity else 1,
                "flag_names": object_flag_names(obj.object_flags),
                "object_flags": int(obj.object_flags),
                "raw_flag_byte": obj.raw_flag_byte,
                "record_length": obj.record_length,
                "is_extended": obj.is_extended,
                "egg": asdict(obj.egg_meta) if obj.egg_meta else None,
                "child_count": len(obj.children),
                "is_npc": False,
                "owner_name": "",
                "diagnostics": [],
            }
            items[number] = row
            if parent is not None:
                children.setdefault(parent, []).append(number)
            if (
                obj.children
                or entry
                and entry.shape_class == container.U7TypeFlags.SHAPE_CLASS_CONTAINER
            ):
                inventories.append(number)
            stack.extend(
                (child, number, (*path, index))
                for index, child in reversed(list(enumerate(obj.children)))
            )
    static = base
    target = ArchiveTarget(
        f"U7 {world.game}",
        static,
        Path(world.patch_dir or world.mod_data_dir or world.static_dir),
        gamedat=Path(world.gamedat_dir),
    )
    # Guard every potential input path, including inherited metadata and IREG maps.
    files = tuple(
        dict.fromkeys(
            path
            for directory in (Path(world.gamedat_dir), static, target.patch)
            if directory.is_dir()
            for path in directory.rglob("*")
            if path.is_file()
        )
    )
    files = tuple(
        dict.fromkeys(
            (
                *files,
                *((text_path,) if text_path else ()),
                *((Path(exult_flx),) if exult_flx else ()),
            )
        )
    )
    session = U7ContainerSession(
        world, items, children, inventories, files, target, diagnostics=diagnostics
    )
    try:
        session.gumps = load_u7_container_gumps(target, world.game, exult_flx=exult_flx)
        session.source_files = tuple(
            dict.fromkeys((*files, *session.gumps.source_files))
        )
    except (OSError, ValueError) as error:
        session.diagnostics.append(f"Container gump metadata unavailable: {error}")
    return session


def validate_u7_container_output(session: U7ContainerSession, output: Path) -> None:
    """Keep browser exports outside the selected world's game and mod input folders."""
    target = output.resolve()
    if target in {path.resolve() for path in session.source_files}:
        raise ValueError("U7 container browser: output overlaps an input file")
    for directory in (
        session.target.static,
        session.target.patch,
        session.target.gamedat,
    ):
        if directory:
            source = directory.resolve()
            if target == source or source in target.parents:
                raise ValueError(
                    "U7 container browser: output must be outside game input folders"
                )


def _next_export(output: Path, stem: str, suffix: str = "") -> Path:
    number = 1
    path = output / (stem + suffix)
    while path.exists():
        number += 1
        path = output / f"{stem}_{number:03d}{suffix}"
    return path


def u7_container_item_image(
    session: U7ContainerSession, number: int | str, *, frame: int | None = None
) -> Image.Image:
    """Render captured shape/frame through the selected base/patch owner's library."""
    return u7_container_item_sprite(session, number, frame=frame).image


def u7_container_item_sprite(
    session: U7ContainerSession, number: int | str, *, frame: int | None = None
) -> U7GumpItemSprite:
    """Decode native frame pixels and draw anchors, including Exult bit-5 reflection."""
    if session.library is None:
        if session.library_error:
            raise ValueError(session.library_error)
        try:
            path = owner_file(session.target, "SHAPES.VGA")
            if path is None:
                raise ValueError("SHAPES.VGA unavailable for this world")
            session.library = load_library(session.target, session.world.game, path)
        except (ValueError, OSError) as error:
            session.library_error = str(error)
            raise
    row = session.items[number]
    shape = session.library.shape(row["shape"])
    index = row["frame"] if frame is None else frame
    if index < 0:
        raise ValueError("U7 container browser: frame must be nonnegative")
    reflected = len(shape.frames) <= 32 and bool(index & 32)
    if reflected:
        index &= 31
    images = session.library.images(shape, row["shape"])
    if not 0 <= index < len(images):
        raise ValueError(
            f"U7 container browser: frame {index} unavailable for shape {row['shape']}"
        )
    native = shape.frames[index]
    image = images[index]
    xleft, yabove = native.hotspot_x_from_left, native.hotspot_y_from_top
    if reflected:
        image = image.transpose(Image.Transpose.TRANSPOSE)
        xleft, yabove = yabove, xleft
    return U7GumpItemSprite(
        number, image, xleft, yabove, row["stored_x"], row["stored_y"]
    )


def u7_container_gump_preview(
    session: U7ContainerSession,
    number: int | str,
    *,
    contents: bool = True,
    seed: int = 0,
) -> tuple[int, U7GumpComposition, str]:
    """Compose the selected owner's gump with direct children; never flatten nested bags."""
    gump, area, source = session.gumps.resolve(session.items[number]["shape"])
    if session.gump_library is None:
        path = owner_file(session.target, "GUMPS.VGA")
        if path is None:
            raise ValueError("U7 container gump: GUMPS.VGA unavailable for this world")
        session.gump_library = load_library(session.target, session.world.game, path)
    library = session.gump_library
    shape = library.shape(gump)
    if not shape.frames:
        raise ValueError(f"U7 container gump: no artwork for gump {gump}")
    artwork = library.images(shape, gump)[0]
    origin = shape.frames[0].hotspot_x_from_left, shape.frames[0].hotspot_y_from_top
    sprites, diagnostics = [], []
    for child in session.children.get(number, []) if contents else []:
        try:
            sprites.append(u7_container_item_sprite(session, child))
        except (ValueError, OSError, IndexError) as error:
            diagnostics.append(f"{child}: item artwork unavailable: {error}")
    composition = compose_u7_container_gump(
        artwork, area, sprites, gump_origin=origin, layout=session.layout, seed=seed
    )
    composition.diagnostics.extend(diagnostics)
    return gump, composition, source


def _csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    fields = list(dict.fromkeys(key for row in rows for key in row)) or ["item_id"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (list, dict))
                else value
                for key, value in row.items()
            }
        )
    return output.getvalue()


def _page(title: str, body: str) -> str:
    return f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title><style>body{{font-family:system-ui;background:#202020;color:#eee;margin:2em}}a{{color:#8cf}}td,th{{padding:.5em;border:1px solid #666}}table{{border-collapse:collapse}}img{{image-rendering:pixelated}}pre{{white-space:pre-wrap}}</style></head><body><h1>{html.escape(title)}</h1>{body}</body></html>'


def export_u7_container_bundle(
    session: U7ContainerSession,
    output: Path,
    *,
    numbers: list[int | str],
    selection: dict[str, Any],
) -> Path:
    """Create new linked HTML/CSV/JSON/tree/native-PNG reports, preserving earlier outputs."""
    validate_u7_container_output(session, output)
    if output.exists():
        raise ValueError("U7 container browser: report requires a new directory")
    numbers = list(dict.fromkeys(numbers))
    if any(number not in session.containers for number in numbers):
        raise ValueError("U7 container browser: selected ID is not an inventory")
    rows = {
        key: inventory_descendants(session.items, session.children, key)
        for key in numbers
    }
    selected = set(numbers) | {
        row["item_id"] for contents in rows.values() for row in contents
    }
    stems = {
        key: f"item_{index:05d}"
        for index, key in enumerate(sorted(selected, key=str), 1)
    }
    (output / "images").mkdir(parents=True)
    (output / "containers").mkdir()
    image_links = {}
    gump_links = {}
    gump_details = {}
    diagnostics = list(session.diagnostics)
    for key in selected:
        try:
            filename = stems[key] + ".png"
            u7_container_item_image(session, key).save(output / "images" / filename)
            image_links[key] = "images/" + filename
        except (ValueError, OSError, IndexError) as error:
            diagnostics.append(f"{key}: artwork unavailable: {error}")
    for key in numbers:
        try:
            gump, composition, source = u7_container_gump_preview(session, key)
            filename = stems[key] + "_gump.png"
            composition.image.save(output / "images" / filename)
            gump_links[key] = "images/" + filename
            gump_details[str(key)] = {
                "gump_shape": gump,
                "frame": 0,
                "mapping_source": source,
                "area": asdict(composition.area),
                "pixel_area": composition.pixel_area,
                "layout": composition.layout,
                "seed": composition.seed,
                "direct_count": len(session.children.get(key, [])),
                "rendered_count": len(composition.placements),
                "placements": composition.placements,
                "diagnostics": composition.diagnostics,
                "image": gump_links[key],
            }
            diagnostics.extend(
                f"{key}: {message}" for message in composition.diagnostics
            )
        except (ValueError, OSError, IndexError) as error:
            gump_details[str(key)] = {"diagnostics": [str(error)]}
            diagnostics.append(f"{key}: gump unavailable: {error}")
    (output / "containers.csv").write_text(
        _csv([session.items[key] for key in numbers]), encoding="utf-8"
    )
    (output / "contents.csv").write_text(
        _csv([row for contents in rows.values() for row in contents]), encoding="utf-8"
    )
    (output / "tree.txt").write_text(
        "\n\n".join(inventory_tree(session.items[key], rows[key]) for key in numbers),
        encoding="utf-8",
    )
    report = {
        "game": session.world.game,
        "source": session.world.gamedat_dir,
        "map_id": session.world.map_num,
        "selection": selection,
        "identity_note": "IREG browser paths identify this captured scan; they are not native persistent IDs.",
        "source_files": list(map(str, session.source_files)),
        "containers": [session.items[key] for key in numbers],
        "inventories": rows,
        "gump_previews": gump_details,
        "diagnostics": diagnostics,
    }
    (output / "inventory.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    index_rows = []
    for key in numbers:
        row = session.items[key]
        page_name = stems[key] + ".html"
        title = inventory_name(row) + " [" + str(key) + "]"
        index_rows.append(
            f'<tr><td><a href="containers/{page_name}">{html.escape(title)}</a></td><td>{row["map_id"]}</td><td>{row["shape"]}</td><td>{row["child_count"]}</td><td>{len(rows[key])}</td></tr>'
        )
        body = '<p><a href="../index.html">Exported inventories</a></p>'
        if row["container_id"] in numbers:
            body += f'<p><a href="{stems[row["container_id"]]}.html">Parent inventory</a></p>'
        if key in gump_links:
            detail = gump_details[str(key)]
            body += f'<h2>Container gump with direct contents</h2><p>Gump {detail["gump_shape"]}, frame 0; {detail["rendered_count"]}/{detail["direct_count"]} direct items; {detail["layout"]} layout, seed {detail["seed"]}. Nested inventories open separately.</p><a href="../{gump_links[key]}"><img src="../{gump_links[key]}" alt="Container gump with contents" style="width:auto;min-width:0;max-width:none"></a>'
        body += (
            "<details><summary>Gump placement and diagnostics</summary><pre>"
            + html.escape(json.dumps(gump_details[str(key)], indent=2))
            + "</pre></details>"
        )
        body += (
            "<pre>"
            + html.escape(inventory_tree(row, rows[key]))
            + "</pre><table><tr><th>ID</th><th>Name</th><th>Shape/frame</th><th>Quantity</th><th>Path</th><th>Preview</th></tr>"
        )
        for item in [row, *rows[key]]:
            identity = item["item_id"]
            name = html.escape(inventory_name(item))
            if identity in numbers:
                name = f'<a href="{stems[identity]}.html">{name}</a>'
            image = (
                f'<img src="../{image_links[identity]}" alt="Item sprite">'
                if identity in image_links
                else "Unavailable"
            )
            body += f"<tr><td>{identity}</td><td>{name}</td><td>{item['shape']}/{item['frame']}</td><td>{item['quantity']}</td><td>{html.escape(item.get('path', ''))}</td><td>{image}</td></tr>"
        body += (
            "</table><h2>Native record</h2><pre>"
            + html.escape(json.dumps(row, indent=2, ensure_ascii=False))
            + "</pre>"
        )
        (output / "containers" / page_name).write_text(
            _page(title, body), encoding="utf-8"
        )
    body = f'<p>Source: {html.escape(str(session.world.gamedat_dir))}; selected map {session.world.map_num}; {len(numbers)} inventories.</p><p><a href="containers.csv">Container CSV</a> · <a href="contents.csv">Contents CSV</a> · <a href="tree.txt">Contents trees</a> · <a href="inventory.json">Complete JSON</a></p><table><tr><th>Inventory</th><th>Map</th><th>Shape</th><th>Direct</th><th>Total</th></tr>{"".join(index_rows)}</table><h2>Diagnostics</h2><pre>{html.escape(chr(10).join(diagnostics))}</pre>'
    (output / "index.html").write_text(
        _page("U7 container inventories", body), encoding="utf-8"
    )
    return output / "index.html"


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
