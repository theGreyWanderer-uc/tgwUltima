"""Captured native U8 inventories, bounded containment graphs and offline reports."""

from __future__ import annotations

import csv
import html
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image
from titan._inventory_browser import (
    inventory_descendants,
    inventory_tree,
    inventory_breadcrumb,
)

from titan.u8.container_gump import U8ContainerGumpPreview, resolve_u8_container_gumps
from titan.u8.container_gump_render import (
    U8GumpComposition,
    U8GumpItemSprite,
    compose_u8_container_gump,
)
from titan.u8.gumpage import U8GumpAreas
from titan.u8.container_records import (
    U8InventoryId,
    build_u8_stored_inventories,
    u8_inventory_file_stem,
    u8_inventory_identity_label,
    u8_inventory_sort_key,
)
from titan.u8.map_items import U8MapItems
from titan.u8.npc_browser import U8NpcSession, u8_npc_is_allocated
from titan.u8.npc_names import load_u8_npc_labels
from titan.u8.npc_source import U8NpcSource
from titan.u8.save_browser import (
    describe_u8_save_browser_view,
    validate_u8_save_browser_output,
)
from titan.u8.save_state import U8SaveSnapshot, format_u8_save_info
from titan.u8.shape_browser import U8ShapeLibrary, find_u8_browser_file

U8_CONTAINER_BROWSER_OUTPUT = Path("titan-out/u8_container_browse_export")


@dataclass
class U8ContainerSession:
    """Captured live and stored inventories; every parent retains its ID namespace."""

    snapshot: U8SaveSnapshot
    library: U8ShapeLibrary | None
    gumps: U8ShapeLibrary | None
    items: dict[U8InventoryId, dict[str, Any]]
    children: dict[U8InventoryId, list[U8InventoryId]]
    containers: list[U8InventoryId]
    diagnostics: list[str]
    npc_session: U8NpcSession | None = None
    names_file: Path | None = None
    gumpage: U8GumpAreas | None = None
    gumpage_path: Path | None = None
    gump_layout: str = "random"
    gump_seed: int = 0
    fixed: U8MapItems | None = None
    fixed_path: Path | None = None
    stored_maps: tuple[int, ...] = ()
    include_stored: bool = True
    npc_backpack: bool = True
    filter_map: int | None = None

    @property
    def sources(self) -> tuple[Path, ...]:
        return (
            self.snapshot.source_files
            + (self.library.source_paths if self.library else ())
            + (self.gumps.source_paths if self.gumps else ())
            + ((self.names_file,) if self.names_file else ())
            + ((self.gumpage_path,) if self.gumpage_path else ())
            + ((self.fixed_path,) if self.fixed_path else ())
        )


def build_u8_container_session(
    snapshot: U8SaveSnapshot,
    library: U8ShapeLibrary | None = None,
    *,
    gumps: U8ShapeLibrary | None = None,
    names: Path | None = None,
    gumpage: Path | None = None,
    layout: str = "random",
    seed: int = 0,
    fixed: Path | None = None,
    include_stored: bool = True,
    npc_backpack: bool = True,
    map_id: int | None = None,
) -> U8ContainerSession:
    """Decode contextual q fields and audit parent/list links without losing items."""
    if layout not in {"random", "saved"}:
        raise ValueError("U8 gump layout must be random or saved")
    if map_id is not None and not 0 <= map_id <= 255:
        raise ValueError("U8 container browser: map ID must be 0–255")
    if fixed is not None and not include_stored:
        raise ValueError(
            "U8 container browser: --fixed cannot be combined with --cache-only"
        )
    cache = snapshot.item_cache
    if cache is None:
        raise ValueError(
            snapshot.decode_errors.get(
                "ITEMCACH.DAT", "U8 container browser: snapshot has no ITEMCACH.DAT"
            )
        )
    if library and not library.world_shapes:
        raise ValueError("U8 container browser: item graphics must be U8SHAPES.FLX")
    labels = load_u8_npc_labels(names) if names else {}
    npc_rows = (
        describe_u8_save_browser_view(snapshot, "npcs", all_slots=True, names=labels)[
            "rows"
        ]
        if snapshot.npc_data
        else []
    )
    npcs = {row["npc_id"]: row for row in npc_rows if u8_npc_is_allocated(row)}
    items: dict[U8InventoryId, dict[str, Any]] = {}
    children: dict[U8InventoryId, list[U8InventoryId]] = {}
    diagnostics = cache.list_diagnostics() + [
        f"{name}: {error}" for name, error in snapshot.decode_errors.items()
    ]
    area_path = gumpage or (
        find_u8_browser_file(gumps.path.parent, "GUMPAGE.DAT") if gumps else None
    )
    areas = None
    if area_path:
        try:
            areas = U8GumpAreas.from_file(area_path)
        except (ValueError, OSError) as error:
            if gumpage is not None:
                raise
            diagnostics.append(f"Gump storage bounds unavailable: {error}")
    elif gumps:
        diagnostics.append(
            "GUMPAGE.DAT missing from gump graphics owner; only empty artwork can be previewed"
        )
    for item in cache.iter_items():
        props = library.properties.get(item.shape) if library else None
        npc = npcs.get(item.item_id)
        family = props.family if props else None
        row = asdict(item)
        row.update(
            cache_id=item.item_id,
            identity=str(item.item_id),
            archive_kind="cache",
            record_index=None,
            is_npc=0 < item.item_id < 256,
            slot_membership=cache.slot_membership(item.item_id),
            container_id=item.container_id,
            location_kind=item.location_kind,
            gump_x=item.y & 255 if item.container_id is not None else None,
            gump_y=item.y >> 8 if item.container_id is not None else None,
            equipment_slot=item.z if item.status & 0x200 else None,
            frame=snapshot.npc_data.get_npc(item.item_id).full_frame(item.frame_low)
            if snapshot.npc_data and 0 < item.item_id < 256
            else item.frame_low,
            shape_name=library.names.get(item.shape, "") if library else "",
            npc_name=npc["npc_name"] if npc else "",
            npc_label=npc["npc_label"] if npc else "",
            label_source=npc["label_source"] if npc else "",
            family=family,
            family_name=props.family_name() if props else "unknown",
            quantity=item.quality
            if family in {2, 9}
            else 1
            if family is not None
            else None,
            quality_meaning={
                1: "quality",
                2: "quantity",
                6: "contents_head",
                9: "quantity",
            }.get(family, "raw")
            if family is not None
            else "raw",
            contents_head=item.quality if family == 6 else None,
            flag_names=item.status_names(),
            diagnostics=[],
        )
        items[item.item_id] = row
        row["gump_previews"] = [
            asdict(preview)
            for preview in resolve_u8_container_gumps(
                snapshot, item.item_id, family=family, npc_backpack=npc_backpack
            )
        ]
        if item.container_id is not None:
            children.setdefault(item.container_id, []).append(item.item_id)
    for row in items.values():
        parent = row["container_id"]
        if parent is not None and parent not in items:
            row["diagnostics"].append(
                f"parent cache ID {parent} is null, free or outside the cache"
            )
        seen = {row["item_id"]}
        cursor = parent
        while cursor in items:
            if cursor in seen:
                row["diagnostics"].append(
                    f"containment cycle reaches cache ID {cursor}"
                )
                break
            seen.add(cursor)
            cursor = items[cursor]["container_id"]
        root = items.get(cursor) if cursor is not None else None
        # Only an intact ancestry has an identifiable top-level owner.
        root_id = None
        if cursor is None:
            root_id = row["item_id"]
            while items[root_id]["container_id"] is not None:
                root_id = items[root_id]["container_id"]
            root = items[root_id]
        row["root_item_id"] = root_id
        row["owner_npc_id"] = root_id if root_id in npcs else None
        row["owner_name"] = npcs[root_id]["npc_label"] if root_id in npcs else ""
        row["map_id"] = (
            npcs[root_id]["item_map"]
            if root_id in npcs
            else cache.metadata.map_in
            if root
            and root["location_kind"] == "world_stored"
            and 0 <= cache.metadata.map_in < 256
            else None
        )
    containers: list[U8InventoryId] = sorted(
        [
            number
            for number, row in items.items()
            if row["family"] == 6 or number in children or row["is_npc"]
        ],
        key=u8_inventory_sort_key,
    )
    for number in containers:
        row = items[number]
        direct = children.get(number, [])
        if row["contents_head"] is not None:
            ordered = []
            cursor = row["contents_head"]
            seen = set()
            while cursor:
                if cursor in seen:
                    row["diagnostics"].append(
                        f"contents list cycle reaches cache ID {cursor}"
                    )
                    break
                seen.add(cursor)
                if cursor not in items or items[cursor]["container_id"] != number:
                    row["diagnostics"].append(
                        f"contents list references cache ID {cursor} with no matching live parent"
                    )
                    break
                ordered.append(cursor)
                cursor = items[cursor]["next_item"]
            missing = [child for child in direct if child not in seen]
            if missing:
                row["diagnostics"].append(
                    f"parent-linked contents absent from head list: {missing}"
                )
            children[number] = ordered + [
                child for child in direct if child not in ordered
            ]
        row["child_count"] = len(direct)
    for row in items.values():
        row.setdefault("child_count", 0)
        diagnostics.extend(
            f"cache ID {row['item_id']}: {issue}" for issue in row["diagnostics"]
        )
    if library:
        diagnostics.extend(library.diagnostics)
    if gumps:
        diagnostics.extend(gumps.diagnostics)
    if snapshot.gumps:
        diagnostics.extend(snapshot.gumps.diagnostics())
        for gump in snapshot.gumps.containers:
            if gump.container_id not in items:
                diagnostics.append(
                    f"saved gump {gump.index}: container cache ID {gump.container_id} is null, free or outside the cache"
                )
    fixed_path = None
    fixed_data = None
    stored_maps: tuple[int, ...] = ()
    if include_stored:
        fixed_path = fixed or (
            find_u8_browser_file(library.path.parent, "FIXED.DAT") if library else None
        )
        if fixed_path:
            try:
                fixed_data = U8MapItems.from_file(fixed_path, kind="fixed")
            except (ValueError, OSError) as error:
                if fixed is not None:
                    raise
                diagnostics.append(f"Stored FIXED inventories unavailable: {error}")
        else:
            diagnostics.append(
                "FIXED.DAT unavailable; static containers on unloaded maps are omitted (supply --fixed)"
            )
        if snapshot.nonfixed is None:
            diagnostics.append(
                "NONFIXED.DAT unavailable; movable containers on unloaded maps are omitted"
            )
        stored = build_u8_stored_inventories(
            [
                archive
                for archive in (fixed_data, snapshot.nonfixed)
                if archive is not None
            ],
            active_map=cache.metadata.map_in,
            properties=library.properties if library else {},
            names=library.names if library else {},
        )
        items.update(stored.items)
        children.update(stored.children)
        containers.extend(stored.containers)
        stored_maps = tuple(stored.map_ids)
        diagnostics.extend(stored.diagnostics)
    npc_session = None
    if library and snapshot.npc_data:
        for row in npc_rows:
            row["class_label"] = library.names.get(row["item_shape"], "")
        npc_session = U8NpcSession(
            U8NpcSource(
                snapshot.source,
                snapshot.npc_data,
                cache,
                snapshot.source_files,
                snapshot.avatar,
            ),
            library,
            npc_rows,
            labels,
            names,
            format_u8_save_info(snapshot),
            snapshot,
        )
    return U8ContainerSession(
        snapshot,
        library,
        gumps,
        items,
        children,
        containers,
        diagnostics,
        npc_session,
        names,
        areas,
        area_path,
        layout,
        seed,
        fixed_data,
        fixed_path,
        stored_maps,
        include_stored,
        npc_backpack,
        map_id,
    )


def u8_inventory_rows(
    session: U8ContainerSession, container: U8InventoryId
) -> list[dict[str, Any]]:
    """Flatten descendants in native list order; bound cycles with a visited set."""
    if container not in session.containers:
        raise ValueError(
            f"U8 container browser: inventory {container} is not a container or NPC inventory"
        )
    return inventory_descendants(session.items, session.children, container)


def filter_u8_containers(
    session: U8ContainerSession,
    query: str = "",
    *,
    kind: str = "all",
    map_id: int | None = None,
) -> list[U8InventoryId]:
    """Search IDs, names, owners, contents and flags, including empty containers."""
    if kind not in {"all", "npc", "container", "diagnostics", "cache", "stored"}:
        raise ValueError("U8 container browser: unknown filter")
    query = query.strip().casefold()
    result = []
    for number in session.containers:
        row = session.items[number]
        npc = row["is_npc"]
        if map_id is not None and row["map_id"] != map_id:
            continue
        if (
            kind == "cache"
            and row["archive_kind"] != "cache"
            or kind == "stored"
            and row["archive_kind"] == "cache"
        ):
            continue
        if (
            kind == "npc"
            and not npc
            or kind == "container"
            and npc
            or kind == "diagnostics"
            and not row["diagnostics"]
        ):
            continue
        if query and not any(
            query in json.dumps(item, ensure_ascii=False).casefold()
            for item in [row, *u8_inventory_rows(session, number)]
        ):
            continue
        result.append(number)
    return result


def u8_container_item_image(
    session: U8ContainerSession, number: U8InventoryId
) -> Image.Image:
    """Use full NPC frames and native horizontal flip, preserving source pixels."""
    if session.library is None:
        raise ValueError("U8 container browser: world graphics unavailable")
    row = session.items[number]
    image = session.library.image(row["shape"], row["frame"])
    return (
        image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if row["status"] & 0x20
        else image
    )


def u8_container_gump_images(
    session: U8ContainerSession, number: U8InventoryId
) -> list[tuple[int, Image.Image]]:
    """Render saved or verified usecode artwork; mapped previews use index -1."""
    if not session.gumps:
        return []
    return [
        (
            preview.index if preview.index is not None else -1,
            session.gumps.image(preview.shape, preview.frame),
        )
        for row in session.items[number]["gump_previews"]
        for preview in [U8ContainerGumpPreview(**row)]
    ]


def u8_container_gump_composition(
    session: U8ContainerSession,
    number: U8InventoryId,
    preview: U8ContainerGumpPreview,
    *,
    seed: int | None = None,
) -> U8GumpComposition:
    """Compose live direct children using captured storage bounds, never editing cache Y."""
    if session.gumps is None:
        raise ValueError("U8 container browser: gump graphics unavailable")
    artwork = session.gumps.image(preview.shape, preview.frame)
    seed = session.gump_seed if seed is None else seed
    fallback = U8GumpComposition(artwork, None, None, [], [], session.gump_layout, seed)
    if session.gumpage is None or session.library is None:
        fallback.diagnostics.append(
            "Inventory composition unavailable: matching GUMPAGE.DAT and world graphics are required; showing empty artwork"
        )
        return fallback
    try:
        area = session.gumpage.get_area(preview.shape)
        gump_frame = session.gumps.shape(preview.shape).frames[preview.frame]
        # Validate the area even for inventories whose sprites cannot be decoded.
        result = compose_u8_container_gump(
            artwork,
            area,
            [],
            gump_origin=(gump_frame.xoff, gump_frame.yoff),
            layout=session.gump_layout,
            seed=seed,
        )
    except ValueError as error:
        fallback.diagnostics.append(
            f"Inventory composition unavailable: {error}; showing empty artwork"
        )
        return fallback
    sprites = []
    issues = []
    for child in session.children.get(number, []):
        if child == number:
            issues.append(
                f"cache ID {child}: self-containing item omitted from preview"
            )
            continue
        row = session.items[child]
        try:
            image = u8_container_item_image(session, child)
            frame = session.library.shape(row["shape"]).frames[row["frame"]]
            props = session.library.properties.get(row["shape"])
            sprites.append(
                U8GumpItemSprite(
                    child,
                    row["shape"],
                    row["frame"],
                    image,
                    image.width - 1 - frame.xoff
                    if row["status"] & 0x20
                    else frame.xoff,
                    frame.yoff,
                    row["gump_x"] or 0,
                    row["gump_y"] or 0,
                    bool(props and props.flags & 0x1000),
                )
            )
        except (ValueError, OSError, IndexError, KeyError) as error:
            issues.append(f"cache ID {child}: inventory sprite unavailable: {error}")
    result = compose_u8_container_gump(
        artwork,
        area,
        sprites,
        gump_origin=(gump_frame.xoff, gump_frame.yoff),
        layout=session.gump_layout,
        seed=seed,
    )
    result.diagnostics.extend(issues)
    return result


def validate_u8_container_output(session: U8ContainerSession, output: Path) -> None:
    """Keep reports outside live state and the selected graphics owner's directory."""
    validate_u8_save_browser_output(session.snapshot, output, session.sources)
    resolved = output.resolve()
    for library in (session.library, session.gumps):
        if library and resolved.is_relative_to(library.path.parent.resolve()):
            raise ValueError(
                "U8 container browser: export outside the graphics directory"
            )


def _csv(rows: list[dict[str, Any]]) -> str:
    fields = list(dict.fromkeys(key for row in rows for key in row)) or ["item_id"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
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
    return "\ufeff" + stream.getvalue()


def _label(row: dict[str, Any]) -> str:
    return row["npc_label"] or row["shape_name"] or f"Shape {row['shape']}"


def _page(title: str, body: str) -> str:
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title><style>body{{font:16px system-ui;margin:2rem;background:#202020;color:#eee}}a{{color:#9cd2ff}}table{{border-collapse:collapse}}td,th{{padding:.4rem;border:1px solid #666;text-align:left}}img{{image-rendering:pixelated;vertical-align:middle}}pre{{white-space:pre-wrap}}</style></head><body><h1>{html.escape(title)}</h1>{body}</body></html>'


def export_u8_container_bundle(
    session: U8ContainerSession,
    output: Path,
    *,
    container: U8InventoryId | None = None,
    containers: list[U8InventoryId] | None = None,
    selection: dict[str, Any] | None = None,
) -> Path:
    """Write fresh offline HTML, master CSV and complete JSON; never replace reports."""
    validate_u8_container_output(session, output)
    if output.exists():
        raise ValueError("U8 container browser: report requires a new directory")
    if container is not None and containers is not None:
        raise ValueError(
            "U8 container browser: choose one inventory or a result selection"
        )
    numbers = (
        list(dict.fromkeys(containers))
        if containers is not None
        else (
            filter_u8_containers(session, map_id=session.filter_map)
            if container is None and containers is None
            else [container]
        )
    )
    inventories = {number: u8_inventory_rows(session, number) for number in numbers}
    if container is not None:
        numbers = [
            container,
            *(
                row["item_id"]
                for row in inventories[container]
                if row["item_id"] in session.containers
            ),
        ]
        inventories = {number: u8_inventory_rows(session, number) for number in numbers}
    orphaned = (
        [
            row
            for row in session.items.values()
            if row["status"] & 8
            and row["root_item_id"] is None
            and (
                selection
                and selection.get("scope") == "all"
                or session.filter_map is None
                or row["map_id"] == session.filter_map
            )
        ]
        if container is None
        and (containers is None or selection and selection.get("scope") == "all")
        else []
    )
    selected_ids = (
        set(numbers)
        | {row["item_id"] for row in orphaned}
        | {row["item_id"] for rows in inventories.values() for row in rows}
    )
    issues = list(session.diagnostics)
    output.mkdir(parents=True, exist_ok=False)
    images = output / "images"
    images.mkdir()
    pages = output / "containers"
    pages.mkdir()
    image_links: dict[U8InventoryId, str] = {}
    for number in sorted(selected_ids, key=u8_inventory_sort_key):
        if session.library is None:
            continue
        try:
            u8_container_item_image(session, number).save(
                images / f"item_{u8_inventory_file_stem(number)}.png"
            )
            image_links[number] = f"images/item_{u8_inventory_file_stem(number)}.png"
        except (ValueError, OSError, IndexError, KeyError) as error:
            issues.append(f"cache ID {number}: sprite preview unavailable: {error}")
    summaries = [
        dict(session.items[number], descendant_count=len(inventories[number]))
        for number in numbers
    ]
    membership = [row for rows in inventories.values() for row in rows]
    (output / "tree.txt").write_text(
        "\n\n".join(
            inventory_tree(session.items[number], inventories[number])
            for number in numbers
        ),
        encoding="utf-8",
    )
    for filename, rows in (
        ("containers.csv", summaries),
        ("contents.csv", membership),
        ("orphaned_items.csv", orphaned),
    ):
        (output / filename).write_text(_csv(rows), encoding="utf-8")
    report: dict[str, Any] = {
        "source": str(session.snapshot.source),
        "source_files": [str(path) for path in session.sources],
        "scope_container_id": container,
        "scope_map_id": selection.get("filters", {}).get("map_id")
        if selection is not None
        else session.filter_map,
        "selection": selection
        or {"scope": "inventory" if container is not None else "all"},
        "coverage": {
            "includes_stored_maps": session.include_stored,
            "active_map": session.snapshot.item_cache.metadata.map_in
            if session.snapshot.item_cache
            else None,
            "stored_map_ids": session.stored_maps,
            "fixed_available": session.fixed is not None,
            "nonfixed_available": session.snapshot.nonfixed is not None,
            "npc_backpack_fallback": session.npc_backpack,
        },
        "containers": summaries,
        "items": [
            session.items[number]
            for number in sorted(selected_ids, key=u8_inventory_sort_key)
        ],
        "inventories": inventories,
        "orphaned_items": orphaned,
        "saved_gumps": [
            {key: value for key, value in asdict(gump).items() if key != "raw_data"}
            for gump in session.snapshot.gumps.containers
        ]
        if session.snapshot.gumps
        else [],
        "diagnostics": issues,
        "gump_compositions": [],
        "notes": [
            "Numeric IDs refer to live ITEMCACH slots; FIXED:MAP:RECORD and NONFIXED:MAP:RECORD identify stored records with zero-based indices.",
            "The active map uses live cache inventories exclusively; unloaded maps use FIXED and saved NONFIXED records. Slot 0's NPC registry is represented by live NPC slots, not duplicate stored records.",
            "Stored containment uses serialized depth and record order; quality/next fields are never treated as live cache links.",
            "NPCs with no saved or verified native artwork use a labelled backpack preview fallback when enabled; this does not assert that the game opens that artwork.",
            "Quality is a raw contextual field; container family 6 uses it as the contents-list head.",
            "Contained Y stores gump X/Y; equipped Z stores an equipment slot.",
            "World-cache XY are retained as native raw coordinates.",
            "Gump artwork prefers saved GUMPS.DAT shape/frame, then verified usecode defaults; provenance is retained.",
            "Inventory previews place direct children inside matching GUMPAGE.DAT rectangles at native pixel size; nested contents remain inside their own containers.",
            "Random placement is a reproducible preview layout, not a reconstruction of historical positions. Saved layout uses nonzero native anchors and scatters unset (0,0) positions.",
            "Editor markers are included so every captured child can be inspected. Avatar previews use the generic storage area, not the game's equipment paperdoll.",
        ],
    }
    index_rows = []
    placement_rows: list[dict[str, Any]] = []
    for number in numbers:
        row = session.items[number]
        title = f"{u8_inventory_identity_label(row)}: {_label(row)}"
        index_rows.append(
            f'<tr><td><a href="containers/{u8_inventory_file_stem(number)}.html">{html.escape(str(number))}</a></td><td>{html.escape(_label(row))}</td><td>{row["map_id"]}</td><td>{row["archive_kind"]}</td><td>{row["shape"]}</td><td>{row["child_count"]}</td><td>{len(inventories[number])}</td><td>{html.escape(row["owner_name"])}</td></tr>'
        )
        body = '<p><a href="../index.html">All exported containers</a></p>'
        body += (
            "<p>" + html.escape(inventory_breadcrumb(session.items, number)) + "</p>"
        )
        body += (
            "<pre>" + html.escape(inventory_tree(row, inventories[number])) + "</pre>"
        )
        parent = row["container_id"]
        if parent in numbers:
            body += f'<p><a href="{u8_inventory_file_stem(parent)}.html">Parent inventory {html.escape(str(parent))}</a></p>'
        if number in image_links:
            body += f'<img src="../{image_links[number]}" alt="Container world sprite">'
        try:
            for metadata, (index, image) in zip(
                row["gump_previews"], u8_container_gump_images(session, number)
            ):
                preview = U8ContainerGumpPreview(**metadata)
                suffix = f"saved_{index:02d}" if index >= 0 else preview.source
                filename = f"gump_{u8_inventory_file_stem(number)}_s{preview.shape:03d}_f{preview.frame:03d}_{suffix}.png"
                image.save(images / filename)
                composition = u8_container_gump_composition(session, number, preview)
                composed_file = Path(filename).stem + "_contents.png"
                composition.image.save(images / composed_file)
                entry = {
                    "container_id": number,
                    "gump": metadata,
                    "layout": composition.layout,
                    "seed": composition.seed,
                    "area": asdict(composition.area) if composition.area else None,
                    "pixel_area": composition.pixel_area,
                    "placements": [asdict(item) for item in composition.placements],
                    "diagnostics": composition.diagnostics,
                    "image": f"images/{composed_file}",
                    "artwork": f"images/{filename}",
                }
                report["gump_compositions"].append(entry)
                placement_rows.extend(
                    dict(
                        container_id=number,
                        gump_shape=preview.shape,
                        gump_frame=preview.frame,
                        gump_source=preview.source,
                        gump_index=preview.index,
                        layout=composition.layout,
                        seed=composition.seed,
                        **asdict(item),
                    )
                    for item in composition.placements
                )
                issues.extend(
                    f"cache ID {number}: {issue}" for issue in composition.diagnostics
                )
                caption = html.escape(
                    f"{preview.description}: gump shape {preview.shape}, frame {preview.frame}"
                )
                body += (
                    f"<p>{caption}; {composition.layout} layout; "
                    f"{len(composition.placements)}/{row['child_count']} direct items placed; "
                    f'seed {composition.seed}</p><img src="../images/{composed_file}" alt="{caption} with inventory">'
                    f'<p><a href="../images/{filename}">Empty artwork</a></p>'
                )
                if composition.area:
                    area = composition.area
                    body += f"<p>Storage area: ({area.left}, {area.top})–({area.right}, {area.bottom}); {area.width}×{area.height} native pixels.</p>"
                if composition.diagnostics:
                    body += (
                        "<pre>"
                        + html.escape("\n".join(composition.diagnostics))
                        + "</pre>"
                    )
        except (ValueError, OSError, IndexError, KeyError) as error:
            issues.append(f"cache ID {number}: gump preview unavailable: {error}")
        body += "<table><tr><th>Depth</th><th>Inventory item ID</th><th>Name</th><th>Shape / frame</th><th>Quantity</th><th>Raw quality / meaning</th><th>Parent</th><th>Gump X/Y; equipment slot</th><th>Flags</th><th>Preview</th></tr>"
        for child in inventories[number]:
            cid = child["item_id"]
            name = html.escape(_label(child))
            if cid in numbers:
                name = f'<a href="{u8_inventory_file_stem(cid)}.html">{name}</a>'
            picture = (
                f'<img src="../{image_links[cid]}" alt="Item {cid}">'
                if cid in image_links
                else "unavailable"
            )
            body += f"<tr><td>{child['depth']}</td><td>{cid}</td><td>{name}</td><td>{child['shape']} / {child['frame']}</td><td>{child['quantity'] if child['quantity'] is not None else 'unknown'}</td><td>{child['quality']} / {child['quality_meaning']}</td><td>{child['container_id']}</td><td>{child['gump_x']}, {child['gump_y']}; {child['equipment_slot']}</td><td>{html.escape(', '.join(child['flag_names']))}</td><td>{picture}</td></tr>"
        body += (
            "</table><h2>Native container record</h2><pre>"
            + html.escape(json.dumps(row, indent=2, ensure_ascii=False))
            + "</pre>"
        )
        (pages / f"{u8_inventory_file_stem(number)}.html").write_text(
            _page(title, body), encoding="utf-8"
        )
    (output / "gump_placements.csv").write_text(_csv(placement_rows), encoding="utf-8")
    (output / "inventory.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    body = f'<p>Source: {html.escape(str(session.snapshot.source))}</p><p>Coverage: {html.escape(json.dumps(report["coverage"]))}</p><p><a href="containers.csv">Container CSV</a> · <a href="contents.csv">Master contents CSV</a> · <a href="gump_placements.csv">Gump placements CSV</a> · <a href="orphaned_items.csv">Orphaned items ({len(orphaned)})</a> · <a href="inventory.json">Complete JSON</a></p><table><tr><th>Inventory ID</th><th>Name</th><th>Map</th><th>Storage</th><th>Shape</th><th>Direct contents</th><th>All descendants</th><th>NPC owner</th></tr>{"".join(index_rows)}</table><h2>Notes</h2><pre>{html.escape(chr(10).join(report["notes"]))}</pre><h2>Diagnostics ({len(issues)})</h2><pre>{html.escape(chr(10).join(issues))}</pre>'
    (output / "index.html").write_text(
        _page("U8 container inventories", body), encoding="utf-8"
    )
    return output / "index.html"
