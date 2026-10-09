"""Shared container browser flow over captured, game-owned inventory records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from titan import _wizard_ui as ui

InventoryId = int | str
InventoryRow = dict[str, Any]
Menu = Callable[..., str]
PAGE_SIZE = 25


def inventory_menu(title: str, labels: dict[str, str], default: str = "B") -> str:
    """Use the same hotkeys, arrow selection and redirected input in both games."""
    ui.legacy_menu(title, *(f"  [{key}] {label}" for key, label in labels.items()))
    return ui.choice(
        "> ",
        list(labels),
        default if default in labels else next(iter(labels)),
        labels=labels,
        message=title,
        hotkeys=True,
    )


@dataclass
class InventoryFilters:
    """Independent container/contents filters; all active fields are combined."""

    query: str = ""
    name: str = ""
    shapes: tuple[int, ...] = ()
    contains_name: str = ""
    contains_shapes: tuple[int, ...] = ()
    direct: bool = False
    owner: str = ""
    map_id: int | None = None
    kind: str = "all"
    rectangle: tuple[int, int, int, int] | None = None
    superchunks: tuple[int, ...] = ()


def inventory_name(row: InventoryRow) -> str:
    """Prefer the captured NPC or frame name before falling back to shape identity."""
    return str(
        row.get("npc_label")
        or row.get("item_name")
        or row.get("shape_name")
        or f"Shape {row['shape']}"
    )


def inventory_descendants(
    items: dict[InventoryId, InventoryRow],
    children: dict[InventoryId, list[InventoryId]],
    number: InventoryId,
) -> list[InventoryRow]:
    """Flatten in native order with parent/depth/path evidence and bounded cycles."""
    rows = []
    visited = {number}
    stack = [
        (child, 1, inventory_name(items[number]))
        for child in reversed(children.get(number, []))
    ]
    while stack:
        child, depth, parent_path = stack.pop()
        if child in visited or child not in items:
            continue
        visited.add(child)
        path = parent_path + " > " + inventory_name(items[child])
        rows.append(dict(items[child], inventory_id=number, depth=depth, path=path))
        stack.extend(
            (nested, depth + 1, path) for nested in reversed(children.get(child, []))
        )
    return rows


def inventory_matches(
    row: InventoryRow, descendants: list[InventoryRow], filters: InventoryFilters
) -> bool:
    """Match structured fields explicitly while retaining raw-record quick search."""
    if filters.map_id is not None and row.get("map_id") != filters.map_id:
        return False
    kind = filters.kind
    npc = bool(row.get("is_npc"))
    storage = row.get("archive_kind", "")
    if (
        kind == "npc"
        and not npc
        or kind == "container"
        and npc
        or kind == "cache"
        and storage != "cache"
        or kind == "stored"
        and storage == "cache"
        or kind == "diagnostics"
        and not row.get("diagnostics")
    ):
        return False
    if filters.name.casefold() not in inventory_name(row).casefold():
        return False
    if filters.shapes and row["shape"] not in filters.shapes:
        return False
    if filters.owner.casefold() not in str(row.get("owner_name", "")).casefold():
        return False
    if filters.superchunks and row.get("superchunk") not in filters.superchunks:
        return False
    if filters.rectangle:
        left, top, right, bottom = filters.rectangle
        if not (
            left <= row.get("x", -1) <= right and top <= row.get("y", -1) <= bottom
        ):
            return False
    candidates = [
        item for item in descendants if not filters.direct or item["depth"] == 1
    ]
    if filters.contains_name or filters.contains_shapes:
        if not any(
            filters.contains_name.casefold() in inventory_name(item).casefold()
            and (
                not filters.contains_shapes or item["shape"] in filters.contains_shapes
            )
            for item in candidates
        ):
            return False
    query = filters.query.strip().casefold()
    return not query or any(
        query in json.dumps(item, ensure_ascii=False).casefold()
        for item in [row, *descendants]
    )


def inventory_breadcrumb(
    items: dict[InventoryId, InventoryRow], number: InventoryId
) -> str:
    """Follow parent identities, so repeated shapes never collapse into one container."""
    labels = []
    visited = set()
    while number in items and number not in visited:
        visited.add(number)
        row = items[number]
        labels.append(f"{inventory_name(row)} [{number}]")
        parent = row.get("container_id")
        if parent is None:
            break
        number = parent
    return " > ".join(reversed(labels))


def inventory_summary(row: InventoryRow, descendants: list[InventoryRow]) -> str:
    """Show useful counts, provenance and location without dumping the native record."""
    location = f"map {row.get('map_id', '—')}"
    if row.get("x") is not None and row.get("container_id") is None:
        location += f"; position ({row['x']}, {row.get('y')}, {row.get('z')})"
    return (
        f"{row['item_id']} — {inventory_name(row)}; shape {row['shape']}, frame {row['frame']}\n"
        f"  {location}; storage {row.get('archive_kind', '—')}; owner {row.get('owner_name') or '—'}\n"
        f"  Contents: {row.get('child_count', 0)} direct / {len(descendants)} nested total; "
        f"flags: {', '.join(row.get('flag_names', [])) or 'none'}; diagnostics: {len(row.get('diagnostics', []))}"
    )


def inventory_tree(root: InventoryRow, descendants: list[InventoryRow]) -> str:
    """Render the same named, indented contents tree and quantities in both games."""
    lines = [f"{inventory_name(root)} [{root['item_id']}]"]
    last_children = {row.get("container_id"): row["item_id"] for row in descendants}
    ancestor_last: list[bool] = []
    for row in descendants:
        depth = row["depth"]
        last = last_children[row.get("container_id")] == row["item_id"]
        quantity = row.get("quantity")
        suffix = f" ×{quantity}" if quantity is not None and quantity != 1 else ""
        flags = (
            f" [{', '.join(row.get('flag_names', []))}]"
            if row.get("flag_names")
            else ""
        )
        prefix = "".join(
            "    " if ended else "│   " for ended in ancestor_last[: depth - 1]
        )
        lines.append(
            f"{prefix}{'└─' if last else '├─'} {inventory_name(row)} [{row['item_id']}]; shape {row['shape']}, frame {row['frame']}{suffix}{flags}"
        )
        ancestor_last = [*ancestor_last[: depth - 1], last]
    if not descendants:
        lines.append("  (empty inventory)")
    return "\n".join(lines)


@dataclass
class InventoryBrowser:
    """Common persistent navigation; callbacks keep native actions in each game."""

    title: str
    items: dict[InventoryId, InventoryRow]
    children: dict[InventoryId, list[InventoryId]]
    containers: list[InventoryId]
    export: Callable[
        [list[InventoryId] | None, InventoryId | None, dict[str, Any]], None
    ]
    actions: Callable[[InventoryId], dict[str, str]]
    perform: Callable[[str, InventoryId, int], None]
    parse_id: Callable[[str], InventoryId]
    menu: Menu = inventory_menu
    filters: InventoryFilters = field(default_factory=InventoryFilters)
    kinds: dict[str, str] = field(
        default_factory=lambda: {"all": "All inventories", "container": "Containers"}
    )
    area_filters: bool = False
    diagnostics: list[str] = field(default_factory=list)

    def descendants(self, number: InventoryId) -> list[InventoryRow]:
        return inventory_descendants(self.items, self.children, number)

    def results(self) -> list[InventoryId]:
        return [
            number
            for number in self.containers
            if inventory_matches(
                self.items[number], self.descendants(number), self.filters
            )
        ]

    def matching_items(self, number: InventoryId) -> list[InventoryRow]:
        """Expose why a result matched and retain the path to the actual held item."""
        filters = self.filters
        if not (filters.contains_name or filters.contains_shapes or filters.query):
            return []
        return [
            row
            for row in self.descendants(number)
            if (not filters.direct or row["depth"] == 1)
            and filters.contains_name.casefold() in inventory_name(row).casefold()
            and (not filters.contains_shapes or row["shape"] in filters.contains_shapes)
            and (
                not filters.query
                or filters.query.casefold()
                in json.dumps(row, ensure_ascii=False).casefold()
            )
        ]

    def edit_filters(self) -> None:
        """Apply validated filters without rescanning or losing the selected source."""
        while True:
            labels = {
                "N": f"Container name: {self.filters.name or 'all'}",
                "S": f"Container shapes: {self.filters.shapes or 'all'}",
                "C": f"Contains item name: {self.filters.contains_name or 'any'}",
                "I": f"Contains item shapes: {self.filters.contains_shapes or 'any'}",
                "D": f"Contents search: {'direct only' if self.filters.direct else 'any depth'}",
                "M": f"Map: {self.filters.map_id if self.filters.map_id is not None else 'all in this source'}",
                "K": f"Kind: {self.filters.kind}",
                "R": "Reset filters and search",
                "B": "Back to results",
            }
            if any(row.get("owner_name") for row in self.items.values()):
                labels["O"] = f"NPC owner: {self.filters.owner or 'all'}"
            if self.area_filters:
                labels.update(
                    {
                        "A": f"Tile rectangle: {self.filters.rectangle or 'all'}",
                        "X": f"Superchunks: {self.filters.superchunks or 'all'}",
                    }
                )
            selected = self.menu("Container filters:", labels)
            try:
                if selected == "B":
                    return
                if selected == "R":
                    self.filters = InventoryFilters()
                elif selected == "D":
                    self.filters.direct = not self.filters.direct
                elif selected == "K":
                    self.filters.kind = self.menu("Inventory kind:", self.kinds, "all")
                elif selected in {"N", "C", "O"}:
                    field_name = {"N": "name", "C": "contains_name", "O": "owner"}[
                        selected
                    ]
                    setattr(
                        self.filters,
                        field_name,
                        ui.text(
                            "  Name substring (blank clears): ",
                            getattr(self.filters, field_name),
                        ).strip(),
                    )
                else:
                    field_name = {
                        "S": "shapes",
                        "I": "contains_shapes",
                        "M": "map_id",
                        "A": "rectangle",
                        "X": "superchunks",
                    }[selected]
                    raw = ui.text(
                        "  Decimal/0x numbers, comma separated (blank clears): "
                    ).strip()
                    values = (
                        tuple(
                            int(
                                token.strip(),
                                16 if token.strip().lower().startswith("0x") else 10,
                            )
                            for token in raw.split(",")
                        )
                        if raw
                        else ()
                    )
                    if any(value < 0 for value in values):
                        raise ValueError("numbers must be nonnegative")
                    if selected == "M" and (
                        len(values) > 1 or values and values[0] > 255
                    ):
                        raise ValueError("map must be one number from 0 to 255")
                    if (
                        selected == "A"
                        and values
                        and (
                            len(values) != 4
                            or values[0] > values[2]
                            or values[1] > values[3]
                        )
                    ):
                        raise ValueError(
                            "rectangle must be left,top,right,bottom in increasing order"
                        )
                    setattr(
                        self.filters,
                        field_name,
                        (values[0] if values else None)
                        if selected == "M"
                        else (values or None)
                        if selected == "A"
                        else values,
                    )
            except (ValueError, KeyError) as error:
                print(f"  Filter unchanged: {error}")

    def inspect(
        self, number: InventoryId, *, back_label: str = "Back to container list"
    ) -> None:
        """Inspect native identities; U/P opens parent and B returns to the caller."""
        page = 0
        counter = 0
        while True:
            row = self.items[number]
            descendants = self.descendants(number)
            print("\n" + inventory_breadcrumb(self.items, number))
            print(inventory_summary(row, descendants))
            for match in self.matching_items(number)[:3]:
                print(f"  Match: {match['path']} [{match['item_id']}]")
            direct = self.children.get(number, [])
            labels = {
                str(
                    child
                ): f"{inventory_name(self.items[child])} [{child}]; shape {self.items[child]['shape']}, frame {self.items[child]['frame']}; quantity {self.items[child].get('quantity', '—')}"
                for child in direct[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
            }
            if page:
                labels["<"] = "Previous contents"
            if (page + 1) * PAGE_SIZE < len(direct):
                labels[">"] = "Next contents"
            labels.update(
                {
                    "T": "Contents tree",
                    "D": "Complete native record",
                    **self.actions(number),
                    "E": "Export this inventory: HTML + CSV + JSON",
                }
            )
            if row.get("container_id") in self.containers:
                labels.update(
                    {
                        "U": "Up to parent inventory",
                        "P": "Up to parent inventory (alias)",
                    }
                )
            labels["B"] = back_label
            selected = self.menu("Inventory / item:", labels)
            try:
                if selected == "B":
                    return
                if selected in {"<", ">"}:
                    page += 1 if selected == ">" else -1
                elif selected in {"U", "P"}:
                    number, page = row["container_id"], 0
                elif selected == "T":
                    print(inventory_tree(row, descendants))
                elif selected == "D":
                    print(json.dumps(row, indent=2, ensure_ascii=False))
                elif selected == "E":
                    self.export(None, number, {"scope": "inventory"})
                elif selected in self.actions(number):
                    self.perform(selected, number, counter)
                    counter += int(selected == "G")
                else:
                    child = self.parse_id(selected)
                    if child not in direct:
                        raise ValueError("select an item from this inventory")
                    if child in self.containers:
                        number, page = child, 0
                    else:
                        self.inspect_item(child)
            except (ValueError, OSError, IndexError, KeyError) as error:
                print(f"  View/export unavailable: {error}")

    def inspect_item(self, number: InventoryId) -> None:
        """Leaf inspection returns to its exact parent with the parent's page intact."""
        while True:
            print("\n" + inventory_breadcrumb(self.items, number))
            print(inventory_summary(self.items[number], []))
            actions = {
                key: label
                for key, label in self.actions(number).items()
                if key in {"V", "S"}
            }
            selected = self.menu(
                "Item:",
                {"D": "Complete native record", **actions, "B": "Back to inventory"},
            )
            if selected == "B":
                return
            if selected == "D":
                print(json.dumps(self.items[number], indent=2, ensure_ascii=False))
            else:
                self.perform(selected, number, 0)

    def browse(self, number: InventoryId | None = None) -> None:
        """Keep search, filters and result page while entering or leaving inventories."""
        if number is not None:
            self.inspect(number)
        page = 0
        while True:
            numbers = self.results()
            page = min(page, max(0, (len(numbers) - 1) // PAGE_SIZE))
            active = {
                key: value
                for key, value in vars(self.filters).items()
                if value not in (None, "", (), False, "all")
            }
            print(
                f"\n{self.title}; results {len(numbers)}/{len(self.containers)}; page {page + 1}; filters {active or 'none'}"
            )
            labels = {
                str(
                    key
                ): f"{inventory_name(self.items[key])} [{key}]; map {self.items[key].get('map_id')}; {self.items[key].get('child_count', 0)} direct / {len(self.descendants(key))} total; owner {self.items[key].get('owner_name') or '—'}"
                for key in numbers[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
            }
            if page:
                labels["P"] = "Previous results"
            if (page + 1) * PAGE_SIZE < len(numbers):
                labels["N"] = "Next results"
            labels.update(
                {
                    "S": "Quick search",
                    "F": "Container / contents / location filters",
                    "I": "Open inventory ID",
                    "T": "Contents trees for current results",
                    "E": "Export current results or all inventories",
                    "Q": "Quit / back",
                }
            )
            for key in numbers[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]:
                matches = self.matching_items(key)
                if matches:
                    labels[str(key)] += f"; match: {matches[0]['path']}"
            labels.update(
                {
                    "K": "Inventory kind (filter shortcut)",
                    "J": "Map (filter shortcut)",
                    "D": "Source diagnostics",
                }
            )
            selected = self.menu("Choose container:", labels, "Q")
            try:
                if selected == "Q":
                    return
                if selected in {"P", "N"}:
                    page += 1 if selected == "N" else -1
                elif selected == "S":
                    self.filters.query = ui.text(
                        "  Search: ", self.filters.query
                    ).strip()
                    page = 0
                elif selected == "F":
                    self.edit_filters()
                    page = 0
                elif selected == "K":
                    self.filters.kind = self.menu("Inventory kind:", self.kinds, "all")
                    page = 0
                elif selected == "J":
                    raw = ui.text("  Map ID (blank clears): ").strip()
                    number_value = int(raw, 0) if raw else None
                    if number_value is not None and not 0 <= number_value <= 255:
                        raise ValueError("map must be from 0 to 255")
                    self.filters.map_id, page = number_value, 0
                elif selected == "D":
                    print("\n".join(self.diagnostics) or "No source diagnostics.")
                elif selected == "T":
                    print(
                        "\n\n".join(
                            inventory_tree(self.items[key], self.descendants(key))
                            for key in numbers
                        )
                        or "No matching inventories."
                    )
                elif selected == "E":
                    scope = self.menu(
                        "Export inventories:",
                        {
                            "R": f"Current results ({len(numbers)})",
                            "A": f"All inventories ({len(self.containers)})",
                            "B": "Back to results",
                        },
                        "R",
                    )
                    if scope != "B":
                        self.export(
                            numbers if scope == "R" else list(self.containers),
                            None,
                            {
                                "scope": "current_results" if scope == "R" else "all",
                                "filters": vars(replace(self.filters))
                                if scope == "R"
                                else {},
                            },
                        )
                else:
                    key = self.parse_id(
                        ui.text("  Inventory ID: ").strip()
                        if selected == "I"
                        else selected
                    )
                    if key not in self.containers:
                        raise ValueError("ID is not an inventory in this source")
                    self.inspect(key)
            except (ValueError, OSError, IndexError, KeyError) as error:
                print(f"  View/export unavailable: {error}")
