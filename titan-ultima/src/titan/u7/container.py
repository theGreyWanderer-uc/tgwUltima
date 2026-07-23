"""
Ultima 7 container browser.

Scans IREG using the deep parser to fully traverse container contents,
including arbitrary nesting (e.g. Ship's Hold → Backpack → Bag → items).

Entry points::

    from titan.u7.container import browse_containers, ContainerQueryParams
    results = browse_containers(params)

    from titan.u7.container import run_wizard
    exit_code = run_wizard(static_dir, gamedat_dir, text_flx)
"""

from __future__ import annotations

__all__ = [
    "ContainerQueryParams",
    "ContainerResult",
    "browse_containers",
    "run_wizard",
]

import csv
import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from titan.u7.map import (
    U7MapRenderer,
    U7MapObject,
    EggMeta,
    C_NUM_SCHUNKS,
    C_CHUNKS_PER_SCHUNK,
    C_TILES_PER_CHUNK,
)
from titan.u7.typeflag import U7TypeFlags
from titan.u7.names import U7ShapeNames, U7FrameNames
from titan.u7.world import _superchunks_for_rect
from titan.u7.ireg import object_flag_names


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------

@dataclass
class ContainerQueryParams:
    """Filters for a container-browse run."""

    static_dir: str
    gamedat_dir: str

    # Which containers to find (empty = all containers)
    container_shape_nums: list[int] = field(default_factory=list)
    container_name_filter: str = ""

    # Optional: only return containers that hold an item matching this filter
    contains_shape_nums: list[int] = field(default_factory=list)
    contains_name_filter: str = ""

    # Area
    superchunks: list[int] = field(default_factory=list)
    tile_rect: Optional[tuple[int, int, int, int]] = None

    # Names
    text_flx_path: Optional[str] = None
    exult_flx_path: Optional[str] = None  # path to exult_bg.flx or exult_si.flx

    # Map selection (0 = default/root, 1+ = mapNN/ subdirectory)
    map_num: int = 0

    # Output
    output_format: str = "tree"    # "tree", "csv"
    output_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ContainerResult:
    """A single matching container with its full contents tree.

    When a contains-filter is active, ``obj`` is the container that *directly*
    holds the matching item — which may be a nested container (e.g. a locked
    chest inside an egg).  In that case ``root_obj`` carries the root-level
    IREG object whose ``tx``/``ty`` give the world position, and
    ``parent_path`` is the ordered list of shape labels from root down to
    ``obj``'s immediate parent (e.g. ``["275 (Egg)"]``).
    """
    obj: U7MapObject
    superchunk: int
    shape_name: str = ""
    root_obj: Optional["U7MapObject"] = None
    parent_path: list[str] = field(default_factory=list)

    # ── convenience ──────────────────────────────────────────────────────────

    def label(self) -> str:
        if self.shape_name:
            return f"{self.obj.shape} ({self.shape_name})"
        return str(self.obj.shape)

    @property
    def is_nested(self) -> bool:
        return self.root_obj is not None and self.root_obj is not self.obj

    @property
    def world_tx(self) -> int:
        return (self.root_obj or self.obj).tx

    @property
    def world_ty(self) -> int:
        return (self.root_obj or self.obj).ty

    @property
    def world_tz(self) -> int:
        return (self.root_obj or self.obj).tz

    def item_count_recursive(self) -> int:
        return _count_recursive(self.obj)

    def max_depth(self) -> int:
        return _max_depth(self.obj)


# ---------------------------------------------------------------------------
# Tree helpers
# ---------------------------------------------------------------------------

def _count_recursive(obj: U7MapObject) -> int:
    """Total items inside obj at all nesting levels."""
    total = len(obj.children)
    for child in obj.children:
        total += _count_recursive(child)
    return total


def _max_depth(obj: U7MapObject, depth: int = 0) -> int:
    if not obj.children:
        return depth
    return max(_max_depth(c, depth + 1) for c in obj.children)


def _contains_any(
    obj: U7MapObject,
    shape_nums: set[int],
    name_lower: str,
    names: Optional[U7ShapeNames],
) -> bool:
    """Return True if any descendant (at any depth) matches the contains filter."""
    for child in obj.children:
        child_name = names.get(child.shape).lower() if names else ""
        if (shape_nums and child.shape in shape_nums) or \
                (name_lower and name_lower in child_name):
            return True
        if _contains_any(child, shape_nums, name_lower, names):
            return True
    return False


def _obj_label(obj: U7MapObject, names: Optional[U7ShapeNames]) -> str:
    n = names.get(obj.shape) if names else ""
    return f"{obj.shape} ({n})" if n else str(obj.shape)


def _find_direct_holders(
    obj: U7MapObject,
    root: U7MapObject,
    path: list[str],
    contains_shapes: set[int],
    contains_name: str,
    names: Optional[U7ShapeNames],
):
    """Yield (container, root, parent_path) for every container at any nesting
    depth whose *direct* children satisfy the contains filter.

    ``path`` is the list of shape labels from root down to ``obj``'s parent
    (empty when obj IS the root).
    """
    # Does obj directly hold a matching item?
    for child in obj.children:
        child_name = names.get(child.shape).lower() if names else ""
        if (contains_shapes and child.shape in contains_shapes) or \
                (contains_name and contains_name in child_name):
            yield obj, root, path
            break  # one match is enough; don't yield obj multiple times

    # Recurse into nested containers
    obj_lbl = _obj_label(obj, names)
    for child in obj.children:
        if child.children:
            yield from _find_direct_holders(
                child, root, path + [obj_lbl],
                contains_shapes, contains_name, names,
            )


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------

def browse_containers(params: ContainerQueryParams) -> list[ContainerResult]:
    """Scan IREG and return matching containers with full content trees."""

    tfa: Optional[U7TypeFlags] = None
    try:
        tfa = U7TypeFlags.from_dir(params.static_dir)
    except (FileNotFoundError, OSError):
        pass

    names: Optional[U7ShapeNames] = None
    if params.text_flx_path:
        try:
            names = U7ShapeNames.from_file(params.text_flx_path)
        except (FileNotFoundError, OSError):
            pass
    if names is None:
        names = U7ShapeNames.from_static_dir(params.static_dir)

    gamedat = Path(params.gamedat_dir)

    total_sc = C_NUM_SCHUNKS * C_NUM_SCHUNKS
    if params.superchunks:
        sc_list = params.superchunks
    elif params.tile_rect:
        sc_list = _superchunks_for_rect(*params.tile_rect)
    else:
        sc_list = list(range(total_sc))

    # Build filter sets
    container_shapes = set(params.container_shape_nums)
    container_name   = params.container_name_filter.lower()
    contains_shapes  = set(params.contains_shape_nums)
    contains_name    = params.contains_name_filter.lower()

    results: list[ContainerResult] = []

    # Resolve IREG subdirectory: map 0 uses root (or map00/), maps 1+ use mapNN/
    if params.map_num > 0:
        ireg_subdir: Optional[Path] = gamedat / f"map{params.map_num:02x}"
    else:
        ireg_subdir = None  # resolved per-superchunk below

    for sc in sc_list:
        ireg_name = f"u7ireg{sc:02X}"
        if ireg_subdir is not None:
            ireg_path = ireg_subdir / ireg_name
        else:
            ireg_path = gamedat / ireg_name
            if not ireg_path.exists():
                ireg_path = gamedat / "map00" / ireg_name
        if not ireg_path.exists():
            continue

        objects = U7MapRenderer.parse_ireg_deep(str(ireg_path), sc, tfa)

        for root_obj in objects:
            if not root_obj.children and tfa:
                entry = tfa.get(root_obj.shape)
                if not (entry and entry.shape_class == U7TypeFlags.SHAPE_CLASS_CONTAINER):
                    continue
            elif not root_obj.children:
                continue

            # Tile rect filter on root world position
            if params.tile_rect:
                tx0, ty0, tx1, ty1 = params.tile_rect
                if not (tx0 <= root_obj.tx <= tx1 and ty0 <= root_obj.ty <= ty1):
                    continue

            if contains_shapes or contains_name:
                if not _contains_any(root_obj, contains_shapes, contains_name, names):
                    continue

                # Report every container at any nesting depth that *directly* holds
                # a matching item. Nested containers are annotated with the root's
                # world position via parent_path.
                for container, root, parent_path in _find_direct_holders(
                    root_obj, root_obj, [], contains_shapes, contains_name, names,
                ):
                    shape_name = names.get(container.shape) if names else ""
                    if container_shapes and container.shape not in container_shapes:
                        continue
                    if container_name and container_name not in shape_name.lower():
                        continue
                    results.append(ContainerResult(
                        obj=container,
                        superchunk=sc,
                        shape_name=shape_name,
                        root_obj=root,
                        parent_path=parent_path,
                    ))
            else:
                shape_name = names.get(root_obj.shape) if names else ""
                if container_shapes and root_obj.shape not in container_shapes:
                    continue
                if container_name and container_name not in shape_name.lower():
                    continue
                results.append(ContainerResult(
                    obj=root_obj,
                    superchunk=sc,
                    shape_name=shape_name,
                ))

    return results


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _item_label(
    obj: U7MapObject,
    names: Optional[U7ShapeNames],
    frame_names: Optional[U7FrameNames],
) -> str:
    """Return the best display label for an item, using frame name when available."""
    if frame_names:
        fname = frame_names.get(obj.shape, obj.frame)
        if fname:
            return f"{obj.shape}:{obj.frame} ({fname})"
    shape_name = names.get(obj.shape) if names else ""
    return f"{obj.shape} ({shape_name})" if shape_name else str(obj.shape)


def _root_location(res: "ContainerResult", names: Optional[U7ShapeNames]) -> str:
    location = f"@ ({res.world_tx},{res.world_ty})  lift={res.world_tz}"
    if not res.is_nested:
        return location
    root_lbl = _obj_label(res.root_obj, names) if names else str(res.root_obj.shape)
    via = " > ".join(res.parent_path) if res.parent_path else root_lbl
    egg_info = ""
    if res.root_obj and res.root_obj.egg_meta:
        egg_info = "  " + res.root_obj.egg_meta.summary()
    return location + f"  [inside {via}{egg_info}]"


def format_tree(
    results: list[ContainerResult],
    names: Optional[U7ShapeNames],
    frame_names: Optional[U7FrameNames] = None,
    tfa: Optional[U7TypeFlags] = None,
) -> str:
    lines: list[str] = []
    lines.append(f"Container browse: {len(results)} container(s) found.")
    lines.append("")

    for res in results:
        total = res.item_count_recursive()
        depth = res.max_depth()
        lines.append(
            f"  {res.label():<30}  0x{res.obj.shape:04X}  "
            f"{_root_location(res, names)}  sc=0x{res.superchunk:02X}  "
            f"[{total} item(s), depth={depth}]"
        )
        if res.obj.egg_meta and not res.is_nested:
            lines.append(f"    egg: {res.obj.egg_meta.summary()}")
        obj_flag_names = object_flag_names(res.obj.object_flags)
        if obj_flag_names:
            lines.append(f"    flags: {', '.join(obj_flag_names)}")
        _append_children(lines, res.obj.children, names, frame_names, tfa, indent="    ")
        lines.append("")

    return "\n".join(lines)


def _child_suffix(child: U7MapObject, tfa: Optional[U7TypeFlags]) -> str:
    """Build the ' ×N  [flags]' display suffix for one container child."""
    qty_str = ""
    entry = tfa.get(child.shape) if tfa else None
    if entry is not None and entry.has_quantity and child.quality > 1:
        qty_str = f"  ×{child.quality}"

    child_flag_names = object_flag_names(child.object_flags)
    flags_str = f"  [{', '.join(child_flag_names)}]" if child_flag_names else ""
    return qty_str + flags_str


def _append_children(
    lines: list[str],
    children: list[U7MapObject],
    names: Optional[U7ShapeNames],
    frame_names: Optional[U7FrameNames],
    tfa: Optional[U7TypeFlags],
    indent: str,
) -> None:
    for i, child in enumerate(children):
        is_last = (i == len(children) - 1)
        branch = "└─ " if is_last else "├─ "
        label = _item_label(child, names, frame_names)
        suffix = _child_suffix(child, tfa)

        child_count = f"  [{len(child.children)} item(s)]" if child.children else ""

        lines.append(f"{indent}{branch}{label}{suffix}{child_count}")

        if child.children:
            child_indent = indent + ("    " if is_last else "│   ")
            _append_children(lines, child.children, names, frame_names, tfa, child_indent)


def format_csv(
    results: list[ContainerResult],
    names: Optional[U7ShapeNames],
    frame_names: Optional[U7FrameNames] = None,
) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow([
        "sc", "container_shape", "container_hex", "container_name",
        "tx", "ty", "tz",
        "depth", "item_shape", "item_hex", "item_name", "item_frame", "item_quality",
        "item_quality_raw", "item_object_flags",
        "path",
    ])

    for res in results:
        display_obj = res.obj
        if res.is_nested:
            from copy import copy as _copy
            display_obj = _copy(res.obj)
            display_obj.tx = res.world_tx
            display_obj.ty = res.world_ty
            display_obj.tz = res.world_tz
        _write_children_csv(
            writer, res.obj.children, names, frame_names,
            res.superchunk, display_obj, names.get(res.obj.shape) if names else "",
            depth=1, path_parts=[res.label()],
        )

    return buf.getvalue()


def _write_children_csv(
    writer: "csv.writer",
    children: list[U7MapObject],
    names: Optional[U7ShapeNames],
    frame_names: Optional[U7FrameNames],
    sc: int,
    container: U7MapObject,
    container_name: str,
    depth: int,
    path_parts: list[str],
) -> None:
    for child in children:
        child_label = _item_label(child, names, frame_names)
        # item_name column: prefer frame name, fall back to shape name
        if frame_names:
            child_name = frame_names.get(child.shape, child.frame) or (names.get(child.shape) if names else "")
        else:
            child_name = names.get(child.shape) if names else ""
        path = " > ".join(path_parts + [child_label])

        writer.writerow([
            f"0x{sc:02X}",
            container.shape,
            f"0x{container.shape:04X}",
            container_name,
            container.tx,
            container.ty,
            container.tz,
            depth,
            child.shape,
            f"0x{child.shape:04X}",
            child_name,
            child.frame,
            child.quality,
            f"0x{child.raw_quality:02X}",
            "|".join(object_flag_names(child.object_flags)),
            path,
        ])

        if child.children:
            _write_children_csv(
                writer, child.children, names, frame_names,
                sc, child, child_name,
                depth + 1, path_parts + [child_label],
            )


def format_results(
    results: list[ContainerResult],
    params: ContainerQueryParams,
    names: Optional[U7ShapeNames],
    frame_names: Optional[U7FrameNames] = None,
    tfa: Optional[U7TypeFlags] = None,
) -> str:
    if params.output_format == "csv":
        return format_csv(results, names, frame_names)
    return format_tree(results, names, frame_names, tfa)


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------

def run_wizard(
    static_dir: Optional[str] = None,
    gamedat_dir: Optional[str] = None,
    text_flx: Optional[str] = None,
    exult_flx_path: Optional[str] = None,
    mod_data_dir: Optional[str] = None,
    map_num: int = 0,
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

    # ── 1. Paths ─────────────────────────────────────────────────────────
    if not static_dir:
        static_dir = questionary.path("STATIC directory:", only_directories=True).ask()
        if static_dir is None:
            return 0

    if not gamedat_dir:
        gamedat_dir = questionary.path("GAMEDAT directory:", only_directories=True).ask()
        if not gamedat_dir:
            return 0

    # Load names early for hints
    _names: Optional[U7ShapeNames] = None
    if text_flx:
        try:
            _names = U7ShapeNames.from_file(text_flx)
        except (FileNotFoundError, OSError):
            pass
    if _names is None and static_dir:
        _names = U7ShapeNames.from_static_dir(static_dir)

    _frame_names: Optional[U7FrameNames] = None
    if static_dir and exult_flx_path and Path(exult_flx_path).exists():
        _text_flx = text_flx or next(
            (str(Path(static_dir) / n) for n in ("TEXT.FLX", "text.flx")
             if (Path(static_dir) / n).exists()),
            None,
        )
        if _text_flx:
            try:
                _frame_names = U7FrameNames.from_flx(exult_flx_path, _text_flx)
            except Exception:
                pass

    if mod_data_dir and Path(mod_data_dir).is_dir():
        _text_flx_for_mod = text_flx or (
            next(
                (str(Path(static_dir) / n) for n in ("TEXT.FLX", "text.flx")
                 if (Path(static_dir) / n).exists()),
                None,
            ) if static_dir else None
        )
        _names = U7ShapeNames.from_mod_dir(mod_data_dir, base=_names) or _names
        if _text_flx_for_mod:
            _frame_names = U7FrameNames.from_mod_dir(mod_data_dir, _text_flx_for_mod, base=_frame_names) or _frame_names

    # ── 2. Container filter ───────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    container_name = questionary.text(
        "Filter containers by name? (substring, leave blank for all containers)",
        default="",
    ).ask()
    if container_name is None:
        return 0
    container_name = container_name.strip()

    if container_name and _names:
        matches = _names.find_shapes(container_name)
        if matches:
            hint = ", ".join(f"{n} ({_names.get(n)})" for n in matches[:6])
            suffix = f"  …+{len(matches)-6} more" if len(matches) > 6 else ""
            print(f"  Matching shapes: {hint}{suffix}")

    container_shape_input = questionary.text(
        "Filter by container shape number(s)? (comma-separated, leave blank for all)",
        default="",
    ).ask()
    if container_shape_input is None:
        return 0

    container_shape_nums: list[int] = []
    for token in container_shape_input.split(","):
        token = token.strip()
        if token:
            try:
                container_shape_nums.append(int(token, 0))
            except ValueError:
                pass

    # ── 3. Contains filter ────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    contains_name = questionary.text(
        "Only show containers holding item by name? (substring, leave blank to skip)",
        default="",
    ).ask()
    if contains_name is None:
        return 0
    contains_name = contains_name.strip()

    if contains_name and _names:
        matches = _names.find_shapes(contains_name)
        if matches:
            hint = ", ".join(f"{n} ({_names.get(n)})" for n in matches[:6])
            suffix = f"  …+{len(matches)-6} more" if len(matches) > 6 else ""
            print(f"  Matching item shapes: {hint}{suffix}")

    contains_shape_input = questionary.text(
        "Only show containers holding item by shape number? (comma-separated, leave blank to skip)",
        default="",
    ).ask()
    if contains_shape_input is None:
        return 0

    contains_shape_nums: list[int] = []
    for token in contains_shape_input.split(","):
        token = token.strip()
        if token:
            try:
                contains_shape_nums.append(int(token, 0))
            except ValueError:
                pass

    # ── 4. Area filter ────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    area_all = questionary.confirm("Search the entire world?", default=True).ask()
    if area_all is None:
        return 0

    superchunks: list[int] = []
    tile_rect: Optional[tuple[int, int, int, int]] = None

    if not area_all:
        area_type = questionary.select(
            "Area filter type:",
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

    # ── 5. Output ─────────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    fmt = questionary.select(
        "Output format:",
        choices=["tree", "csv"],
        default="tree",
    ).ask()
    if fmt is None:
        return 0

    output_path: Optional[str] = None
    if questionary.confirm("Save output to a file?", default=False).ask():
        output_path = questionary.path("Output file path:").ask()

    # ── Run ───────────────────────────────────────────────────────────────
    print()
    print(f"  {_SEP}")
    print("  Scanning…")

    params = ContainerQueryParams(
        static_dir=static_dir,
        gamedat_dir=gamedat_dir,
        container_shape_nums=container_shape_nums,
        container_name_filter=container_name,
        contains_shape_nums=contains_shape_nums,
        contains_name_filter=contains_name,
        superchunks=superchunks,
        tile_rect=tile_rect,
        text_flx_path=text_flx,
        map_num=map_num,
        output_format=fmt,
        output_path=output_path,
    )

    results = browse_containers(params)
    output = format_results(results, params, _names, _frame_names)

    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        print(f"  Wrote {len(results)} container(s) to {output_path}")
    else:
        print()
        print(output)

    return 0
