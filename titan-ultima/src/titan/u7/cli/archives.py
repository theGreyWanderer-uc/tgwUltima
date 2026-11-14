"""``titan u7 flex-*`` — U7 Flex archive creation and shape insertion."""

from __future__ import annotations

__all__ = ["u7_flex_create_cmd", "u7_flex_add_shape_cmd"]

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal, Optional

import typer

from titan import _wizard_ui as ui
from titan.u7 import install
from titan.u7.cli import _common


def cmd_u7_flex_create(args: SimpleNamespace) -> int:
    """Create a new empty U7/Exult Flex archive without overwriting by default."""
    from titan._version import TITAN_VERSION
    from titan.u7.flex import U7FlexArchive

    output_path = Path(args.output)
    if output_path.suffix.lower() not in {".vga", ".flx"}:
        print(
            f"ERROR: U7 Flex create output must end in .VGA or .FLX: {output_path}",
            file=sys.stderr,
        )
        return 1
    if output_path.exists() and not args.force:
        print(
            f"ERROR: U7 Flex create output already exists (use --force to replace): {output_path}",
            file=sys.stderr,
        )
        return 1

    archive = U7FlexArchive()
    archive.title = (
        args.title or f"Empty U7 Flex archive created by TITAN v{TITAN_VERSION}"
    )

    try:
        archive.save(str(output_path))
    except OSError as error:
        print(f"ERROR: U7 Flex create failed: {error}", file=sys.stderr)
        return 1

    return 0


def cmd_u7_flex_add_shape(args: SimpleNamespace) -> int:
    """Add a standalone U7 shape to the first permitted free Flex record."""
    from titan.u7.shape_animation_flag import (
        choose_u7_shape_animation,
        read_u7_shape_animation,
        prepare_u7_archive_animation,
        write_u7_animation_payloads,
    )
    from titan.u7.shape_archive import discover_base_archive
    from titan.u7.flex_shape_add import (
        add_shape_at_record_index,
        add_shape_to_first_available_record,
        save_u7_flex_atomically,
    )
    from titan.u7.shape import FIRST_OBJ_SHAPE, U7Shape
    from titan.u7.shape_import import validate_u7_import_frame_size

    archive_path = Path(args.archive)
    shape_path = Path(args.shape)
    if not archive_path.is_file():
        print(
            f"ERROR: U7 Flex add-shape archive not found: {archive_path}",
            file=sys.stderr,
        )
        return 1
    if not shape_path.is_file():
        print(
            f"ERROR: U7 Flex add-shape shape not found: {shape_path}", file=sys.stderr
        )
        return 1
    if bool(args.output) == bool(args.in_place):
        print(
            "ERROR: U7 Flex add-shape requires exactly one of --output or --in-place",
            file=sys.stderr,
        )
        return 1

    requested_index = getattr(args, "index", None)
    replace_record = getattr(args, "replace", False)
    archive_kind = getattr(args, "archive_kind", "shapes")
    flat = getattr(args, "flat", False)
    if archive_kind not in {"shapes", "generic"}:
        print("ERROR: U7 Flex archive kind must be shapes or generic", file=sys.stderr)
        return 1
    if flat and archive_kind != "shapes":
        print("ERROR: U7 Flex --flat requires --archive-kind shapes", file=sys.stderr)
        return 1
    if requested_index is not None and requested_index < 0:
        print(
            f"ERROR: U7 Flex add-shape record index must be non-negative: {requested_index}",
            file=sys.stderr,
        )
        return 1
    if replace_record and requested_index is None:
        print(
            "ERROR: U7 Flex add-shape --replace requires --index",
            file=sys.stderr,
        )
        return 1

    output_path = archive_path if args.in_place else Path(args.output)
    if output_path.suffix.lower() not in {".vga", ".flx"}:
        print(
            f"ERROR: U7 Flex add-shape output must end in .VGA or .FLX: {output_path}",
            file=sys.stderr,
        )
        return 1
    if not args.in_place and output_path.resolve() == archive_path.resolve():
        print(
            "ERROR: U7 Flex add-shape requires --in-place when output is the source archive",
            file=sys.stderr,
        )
        return 1
    if not args.in_place and output_path.exists() and not args.force:
        print(
            f"ERROR: U7 Flex add-shape output already exists (use --force to replace): {output_path}",
            file=sys.stderr,
        )
        return 1

    try:
        resolved = _common._load_u7_shape_archive(str(archive_path), args, strict=True)
        if resolved is None:
            return 1
        archive = resolved.selected
        shape_data = shape_path.read_bytes()
        shape = U7Shape.from_data(shape_data, strict=True)
        if not shape.frames:
            print(
                f"ERROR: U7 Flex add-shape input contains no valid frames: {shape_path}",
                file=sys.stderr,
            )
            return 1
        for frame_index, frame in enumerate(shape.frames):
            validate_u7_import_frame_size(
                frame.width, frame.height, f"{shape_path.name}, frame {frame_index}"
            )
        if archive_kind == "shapes":
            if flat:
                if any(
                    not frame.is_tile or (frame.width, frame.height) != (8, 8)
                    for frame in shape.frames
                ):
                    raise ValueError(
                        "U7 flat insertion requires raw 8x8 frames; "
                        "create the shape with shape-import --flat"
                    )
                if requested_index is not None and requested_index >= FIRST_OBJ_SHAPE:
                    raise ValueError(
                        "U7 flat insertion must use a slot from 0 through 149"
                    )
            else:
                if any(frame.is_tile for frame in shape.frames):
                    raise ValueError(
                        "U7 raw flat shapes require --flat; object shapes must be RLE"
                    )
                if requested_index is not None and requested_index < FIRST_OBJ_SHAPE:
                    raise ValueError(
                        "U7 object insertion must use slot 150 or higher; "
                        "slots 0 through 149 require --flat and raw 8x8 frames"
                    )
        if requested_index is None:
            minimum_record_index = (
                FIRST_OBJ_SHAPE if archive_kind == "shapes" and not flat else 0
            )
            record_index = add_shape_to_first_available_record(
                archive,
                shape_data,
                minimum_record_index=minimum_record_index,
                maximum_record_index=FIRST_OBJ_SHAPE - 1 if flat else None,
                base_archive=resolved.base,
            )
        else:
            record_index = add_shape_at_record_index(
                archive,
                shape_data,
                requested_index,
                replace=replace_record,
                base_archive=resolved.base,
            )
        default = read_u7_shape_animation(shape_path, shape_data)
        animated = choose_u7_shape_animation(
            shape, animated=getattr(args, "animated", None), default=default
        )
        base_value = getattr(args, "base_archive", None) or discover_base_archive(
            archive_path,
            install.resolve_u7_static_and_palette(getattr(args, "game", "bg"))[0],
        )
        sources = (archive_path,) + ((Path(base_value),) if base_value else ())
        metadata = (
            prepare_u7_archive_animation(
                output_path,
                {record_index: (shape_data, animated)},
                world_shapes=archive_kind == "shapes" and not flat,
                sources=sources,
            )
            if animated is not None
            else []
        )
        save_u7_flex_atomically(archive, output_path)
        write_u7_animation_payloads(metadata)
    except (ui.PromptCancelled, KeyboardInterrupt):
        print("Cancelled.")
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: U7 Flex add-shape failed: {error}", file=sys.stderr)
        return 1

    print(
        f"Shape added: {shape_path} -> {output_path} "
        f"(record {record_index}, {len(archive.records)} total records)"
    )
    return 0


def u7_flex_create_cmd(
    output: Annotated[
        str,
        typer.Argument(help="New empty U7 Flex archive path (.VGA or .FLX)"),
    ],
    title: Annotated[
        Optional[str],
        typer.Option(
            "-t", "--title", help="Archive title stored in the U7 Flex header"
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace the output file if it already exists"),
    ] = False,
) -> None:
    """Create a new empty U7/Exult Flex archive with zero records."""
    raise SystemExit(
        cmd_u7_flex_create(
            SimpleNamespace(
                output=output,
                title=title,
                force=force,
            )
        )
    )


def u7_flex_add_shape_cmd(
    archive: Annotated[
        str,
        typer.Argument(help="Source U7 Flex archive (.VGA or .FLX)"),
    ],
    shape: Annotated[
        str,
        typer.Argument(help="Standalone U7 .shp file to add"),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write a separate updated archive"),
    ] = None,
    in_place: Annotated[
        bool,
        typer.Option("--in-place", help="Atomically update the source archive"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace an existing --output archive"),
    ] = False,
    index: Annotated[
        Optional[int],
        typer.Option("--index", help="Specific zero-based shape record index"),
    ] = None,
    replace: Annotated[
        bool,
        typer.Option("--replace", help="Replace an occupied --index record"),
    ] = False,
    archive_kind: Annotated[
        Literal["shapes", "generic"],
        typer.Option(
            "--archive-kind",
            help="shapes: reserve slots 0-149 for flats; generic: other Flex archives",
        ),
    ] = "shapes",
    flat: Annotated[
        bool,
        typer.Option("--flat", help="Insert raw 8x8 flat frames into slots 0-149"),
    ] = False,
    base_archive: Annotated[
        Optional[str],
        typer.Option(
            "--base-archive",
            help="Original VGA/Flex archive for sparse patch inheritance",
        ),
    ] = None,
    animated: Annotated[
        Optional[bool],
        typer.Option(
            "--animate/--no-animate",
            help="Set frame animation explicitly; otherwise prompt for multiple RLE frames",
        ),
    ] = None,
    game: Annotated[
        Literal["bg", "si"],
        typer.Option("--game", help="BG or SI config fallback for the patch base"),
    ] = "bg",
) -> None:
    """Add a U7 shape to a specific or the lowest permitted empty record.

    Object allocation starts at shape 150 regardless of the archive filename.
    """
    raise SystemExit(
        cmd_u7_flex_add_shape(
            SimpleNamespace(
                base_archive=base_archive,
                game=game,
                archive=archive,
                shape=shape,
                output=output,
                in_place=in_place,
                force=force,
                index=index,
                replace=replace,
                archive_kind=archive_kind,
                flat=flat,
                animated=animated,
            )
        )
    )
