"""Shape browser screens for U7 shape properties: the filter menu and the report pager.

The data comes from :mod:`titan.u7.shape_properties`, which never prints or prompts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from titan.u7.shape_properties import (
    filtered_ids,
    property_report,
    report_lines,
    save_report,
)
from titan.u7.typeflag import U7TypeFlags

if TYPE_CHECKING:
    from titan.u7.shape import U7Shape
    from titan.u7.shape_browser import ShapeLibrary


def choose_filter(library: ShapeLibrary) -> None:
    from titan.u7 import shape_browser_ui as browser_ui

    labels = {
        "A": "All populated shapes",
        "C": "Shape class",
        "F": "Physical flag",
        "W": "Weapons",
        "M": "Ammunition",
        "R": "Armour",
        "E": "Ready-slot data",
        "G": "Container gump mappings",
        "U": "Unknown TFA metadata",
        "Q": "Keep current filter",
    }
    selected = browser_ui._menu("Filter shapes:", labels, "A")
    mode = {
        "A": "all",
        "W": "weapon",
        "M": "ammo",
        "R": "armor",
        "E": "ready",
        "G": "container",
        "U": "unknown",
    }.get(selected)
    if selected == "C":
        classes = {
            str(number): f"{number}: {name}"
            for number, name in U7TypeFlags.SHAPE_CLASS_NAMES.items()
        }
        classes["Q"] = "Back"
        choice = browser_ui._menu("Shape class:", classes, "6")
        mode = "class:" + choice if choice != "Q" else None
    elif selected == "F":
        flags = (
            list(U7TypeFlags.BYTE0_FLAG_NAMES.values())
            + list(U7TypeFlags.BYTE1_FLAG_NAMES.values())
            + list(U7TypeFlags.BYTE2_FLAG_NAMES.values())
            + ["occludes", "x_obstacle", "y_obstacle"]
        )
        options = {str(i): name for i, name in enumerate(flags, 1)}
        options["Q"] = "Back"
        choice = browser_ui._menu("Physical flag:", options, "4")
        mode = "flag:" + options[choice] if choice != "Q" else None
    if mode is not None:
        library.property_filter = mode
        print(f"  Filter: {mode}; {len(filtered_ids(library, mode))} populated shapes.")


def export_report(library: ShapeLibrary, report: dict[str, object]) -> None:
    """Ask for a new JSON file and save *report* there."""
    from titan.u7 import shape_browser_ui as browser_ui

    path = browser_ui._path(
        "JSON report (new file)", f"shape_{report['shape']}_properties.json"
    )
    save_report(library, report, path)
    print(f"  Saved: {path}")


def show_properties(
    library: ShapeLibrary, shape: U7Shape, number: int, frame: int
) -> None:
    from titan.u7 import shape_browser_ui as browser_ui

    report = property_report(library, shape, number, frame)
    lines = report_lines(report)
    page, size = 0, 15
    last = (len(lines) - 1) // size
    while True:
        print(f"\nShape {number} properties — page {page + 1}/{last + 1}")
        print("\n".join(lines[page * size : (page + 1) * size]))
        labels = {"E": "Export JSON properties report", "Q": "Back to shape"}
        if page < last:
            labels["N"] = "Next page"
        if page:
            labels["B"] = "Previous page"
        action = browser_ui._menu(
            "Shape properties:", labels, "N" if "N" in labels else "Q"
        )
        if action == "Q":
            return
        if action == "E":
            try:
                export_report(library, report)
            except (OSError, ValueError) as error:
                print(f"  ERROR: {error}")
        else:
            page += 1 if action == "N" else -1
