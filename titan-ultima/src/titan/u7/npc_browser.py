"""Sessions, filters and reports for read-only browsing of a world's NPCs and saved games."""

from __future__ import annotations

import json
import struct
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from titan.u7.archive_targets import ArchiveTarget
from titan.u7.install import existing_path
from titan.u7.save import (
    U7GameState,
    U7Identity,
    U7NPC,
    U7NPCData,
    U7ReadyTypes,
    U7Save,
    U7SaveInfo,
    U7Schedules,
)
from titan.u7.names import U7ShapeNames
from titan.u7.shape_archive import U7ShapeArchive, find_archive
from titan.u7.shape_browser import ShapeLibrary
from titan.u7.world import WorldQueryParams, load_query_metadata
from titan.u7.avatar_metadata import U7AvatarMetadata, read_u7_avatar_metadata
from titan.u7.gump_metadata import load_u7_gump_sources
from titan.u7.ireg_metadata import U7IregContext
from titan.u7.ireg_specials import saved_slot_row
from titan.u7.ready_metadata import U7ReadyMetadata
from titan.u7.typeflag import U7TypeFlags
from titan.u7.usecode import U7UsecodeFile
from titan.u7.usecode_analysis import U7UsecodeWorld

READ_ERRORS = (OSError, ValueError, struct.error, zipfile.BadZipFile, EOFError)


def clean(value: str) -> str:
    """File titles and names must not inject terminal controls."""
    return "".join(
        c if ord(c) >= 32 and not 127 <= ord(c) < 160 else " " for c in value
    )


def owner_file(target: ArchiveTarget, name: str) -> Path | None:
    return find_archive(target.patch, name) or (
        find_archive(target.static, name) if target.static else None
    )


@dataclass(frozen=True)
class Source:
    path: Path
    kind: str = "custom"  # initial, live, save, custom


@dataclass
class Session:
    target: ArchiveTarget
    source: Source
    title: str = ""
    format: str = "directory"
    identity: str = ""
    entries: list[tuple[str, int]] = field(default_factory=list)
    npcs: U7NPCData | None = None
    schedules: U7Schedules | None = None
    info: U7SaveInfo | None = None
    state: U7GameState | None = None
    names: U7ShapeNames | None = None
    ready: U7ReadyTypes | None = None
    effective_ready: U7ReadyMetadata | None = None
    ireg_context: U7IregContext | None = None
    warnings: list[str] = field(default_factory=list)
    game: str = "bg"
    preview_library: ShapeLibrary | None = field(default=None, repr=False)
    preview_error: str | None = None
    avatar_metadata: U7AvatarMetadata | None = None
    usecode_symbols: dict[str, int] | None = None
    usecode_sources: list[str] = field(default_factory=list)
    have_si_shapes: bool | None = None
    avatar_skin: int | None = None
    avatar_female: bool | None = None

    def overview(self) -> str:
        lines = [
            f"World: {clean(self.target.name)}",
            f"Source: {self.source.path} ({self.source.kind}; {self.format})",
            f"Title: {clean(self.title) or '(no stored title)'}",
            f"Identity: {clean(self.identity) or '(not stored)'}",
            f"Files: {len(self.entries)}; {sum(size for _, size in self.entries):,} bytes",
        ]
        if self.npcs is not None:
            declared = self.npcs.num_npcs1 + self.npcs.num_npcs2
            lines.append(
                f"NPCs: {len(self.npcs.npcs)} of {declared} records; {self.npcs.npc_flavor}"
            )
        else:
            lines.append("NPC data unavailable in this source.")
        if self.schedules is not None:
            lines.append(self.schedules.dump_summary())
        if self.info is not None:
            lines.append(clean_lines(self.info.dump()))
        if self.state is not None:
            lines.append(self.state.dump())
        lines.extend(f"WARNING: {clean(warning)}" for warning in self.warnings)
        return "\n".join(lines)


def clean_lines(value: str) -> str:
    return "\n".join(clean(line) for line in value.splitlines())


def save_paths(target: ArchiveTarget) -> list[Path]:
    """List only this owner's save directory, never recursively enter other mods."""
    root = target.save_root
    if root is None and target.gamedat is not None:
        root = target.gamedat.parent
    if root is None:
        root = target.root
    if root is None or not existing_path(root).is_dir():
        return []
    return sorted(
        (
            p
            for p in existing_path(root).iterdir()
            if p.is_file() and p.suffix.lower() == ".sav"
        ),
        key=lambda p: p.name.casefold(),
    )


def _schedule_checks(data: bytes) -> None:
    """Compatibility entry point for the shared strict schedule parser."""
    U7Schedules.from_bytes(data, strict=True)


def load_inventory_metadata(session: Session, tfa: U7TypeFlags | None) -> None:
    """Share owner-specific READY and IREG context with NPC and monster browsers."""
    target = session.target
    try:
        sources = load_u7_gump_sources(
            target.static,
            patch_dir=target.patch,
            game=session.game,
            custom_game=target.standalone,
        )
        session.effective_ready = U7ReadyMetadata.from_dir(
            target.static,
            patch_dir=target.patch,
            game=session.game,
            sources=sources,
        )
        session.warnings.extend(session.effective_ready.warnings)
        # Retain the existing raw-preference interface for compatibility.
        session.ready = U7ReadyTypes(
            dict(session.effective_ready.preferred),
            list(session.effective_ready.records),
        )
        session.ireg_context = U7IregContext.from_sources(
            sources, tfa, game=session.game
        )
    except READ_ERRORS as error:
        session.warnings.append(f"Inventory metadata unavailable: {error}")


def _metadata(session: Session, game: str) -> tuple[set[int] | None, int | None]:
    target = session.target
    containers, shape_count = None, None
    tfa: U7TypeFlags | None = None
    if target.static is not None:
        try:
            tfa, session.names, _, count = load_query_metadata(
                WorldQueryParams(
                    static_dir=str(target.static),
                    base_static=str(target.static),
                    patch_dir=str(target.patch) if target.patch.is_dir() else None,
                    game=game,
                )
            )
            if count:
                containers = {
                    entry.shape_num
                    for entry in tfa.entries[:count]
                    if entry.shape_class == 6
                }
        except READ_ERRORS as error:
            session.warnings.append(f"World metadata unavailable: {error}")
    if containers is None:
        session.warnings.append(
            "TFA classes unavailable; inventory nesting uses the reader's heuristics."
        )
    if session.names is None:
        session.warnings.append("Item names unavailable; numeric shape IDs are shown.")
    shapes = owner_file(target, "SHAPES.VGA")
    if shapes is not None:
        try:
            base = find_archive(target.static, "SHAPES.VGA") if target.static else None
            archive = U7ShapeArchive.from_file(
                str(shapes),
                base_archive=str(base) if base and base != shapes else None,
                infer_base=False,
            )
            shape_count = len(archive.effective.records)
        except READ_ERRORS as error:
            session.warnings.append(f"Shape bounds unavailable: {error}")
    load_inventory_metadata(session, tfa)
    try:
        session.avatar_metadata = read_u7_avatar_metadata(
            load_u7_gump_sources(
                target.static,
                patch_dir=target.patch,
                game=game,
                custom_game=target.standalone,
            )
        )
        session.warnings.extend(session.avatar_metadata.warnings)
    except READ_ERRORS as error:
        session.warnings.append(f"Avatar metadata unavailable: {error}")
    try:
        world = U7UsecodeWorld()
        paths: set[Path] = set()
        for directory, patch in ((target.static, False), (target.patch, True)):
            path = find_archive(directory, "USECODE") if directory is not None else None
            if path is not None and path.resolve() not in paths:
                paths.add(path.resolve())
                world.add_stream(
                    U7UsecodeFile.from_file(str(path), strict=True),
                    source=str(path),
                    patch=patch,
                )
                session.usecode_sources.append(str(path))
        if paths:
            session.usecode_symbols = world.symbol_values
    except READ_ERRORS as error:
        session.warnings.append(f"Named Usecode bindings unavailable: {error}")
        session.usecode_symbols = None
    return containers, shape_count


def load_session(
    target: ArchiveTarget,
    source: Source,
    game: str,
    *,
    have_si_shapes: bool | None = None,
    avatar_skin: int | None = None,
    avatar_female: bool | None = None,
) -> Session:
    path = existing_path(source.path.expanduser()).absolute()
    source = Source(path, source.kind)
    session = Session(target, source, game=game)
    session.have_si_shapes = (
        have_si_shapes
        if have_si_shapes is not None
        else True
        if game == "si" and not target.standalone
        else None
    )
    session.avatar_skin, session.avatar_female = avatar_skin, avatar_female
    directory = path if path.is_dir() else path.parent
    if path.is_dir() or path.name.casefold() == "npc.dat":
        if not path.exists():
            raise ValueError(f"Source not found: {path}")
        session.format = "directory" if path.is_dir() else "loose NPC file"
        session.entries = sorted(
            (p.name, p.stat().st_size) for p in directory.iterdir() if p.is_file()
        )

        def data(name: str) -> bytes | None:
            p = (
                path
                if name == "npc.dat" and path.is_file()
                else find_archive(directory, name)
            )
            return p.read_bytes() if p else None

        flavor = "runtime" if source.kind == "live" else "auto"
    else:
        archive = U7Save.from_file(str(path))
        session.warnings.extend(archive.warnings)
        session.title, session.format = archive.title, archive.container_format
        session.entries = archive.list_entries()
        data = archive.get_data
        # Original retail INITGAME uses different sex/flags/face fields.
        initial = source.kind == "initial" or path.name.casefold() == "initgame.dat"
        flavor = (
            "original-new-game"
            if initial and archive.container_format == "flex"
            else "runtime"
        )
        if initial and archive.get_data("schedule.dat") is None:
            # BG initializes schedules from STATIC, rather than INITGAME.
            # Saved/live data must never inherit new-game schedules.
            schedule = owner_file(target, "SCHEDULE.DAT")
            archive_data = data

            def data(name: str) -> bytes | None:
                if name == "schedule.dat" and schedule is not None:
                    return schedule.read_bytes()
                return archive_data(name)

            if schedule is not None:
                session.entries.append(
                    (f"new-game schedules: {schedule}", schedule.stat().st_size)
                )

    try:
        identity = data("identity")
        if identity is not None:
            session.identity = U7Identity.from_bytes(identity).game
    except READ_ERRORS as error:
        session.warnings.append(f"Cannot read identity: {error}")
    known = {"BLACKGATE": "bg", "SERPENTISLE": "si"}
    if session.identity.upper() in known and known[session.identity.upper()] != game:
        session.warnings.append(
            "Stored game identity differs from the selected BG/SI flavour; world item metadata is disabled. Choose the matching world."
        )
        session.preview_error = "Choose the world matching this save's game identity."
        containers, shape_count = None, None
    else:
        containers, shape_count = _metadata(session, game)
    for name, parser, attr in (
        ("npc.dat", None, "npcs"),
        ("schedule.dat", U7Schedules.from_bytes, "schedules"),
        ("saveinfo.dat", U7SaveInfo.from_bytes, "info"),
        ("gamewin.dat", U7GameState.from_bytes, "state"),
    ):
        try:
            blob = data(name)
            if blob is None:
                if name in {"npc.dat", "schedule.dat"}:
                    session.warnings.append(f"{name} is not present in this source.")
                continue
            if name == "npc.dat":
                session.npcs = U7NPCData.from_bytes(
                    blob,
                    containers,
                    shape_count,
                    npc_flavor=flavor,
                    game=game,
                    ireg_context=session.ireg_context,
                )
                session.warnings.extend(session.npcs.warnings)
                expected = session.npcs.num_npcs1 + session.npcs.num_npcs2
                if len(session.npcs.npcs) != expected:
                    session.warnings.append(
                        f"npc.dat is partial: parsed {len(session.npcs.npcs)} of {expected} declared NPCs; the last NPC record is incomplete or absent."
                    )
                elif session.npcs._parsed_bytes > len(blob):
                    session.warnings.append(
                        "npc.dat is partial: the last NPC record is incomplete."
                    )
            elif name == "schedule.dat":
                session.schedules = U7Schedules.from_bytes(blob, strict=True)
                session.warnings.extend(session.schedules.warnings)
            elif parser is not None:
                setattr(session, attr, parser(blob))
        except READ_ERRORS as error:
            session.warnings.append(f"Cannot read {name}: {error}")
    if session.info:
        session.warnings.extend(session.info.warnings)
    if session.state:
        session.warnings.extend(session.state.warnings)
    return session


def filter_npcs(npcs: list[U7NPC], query: str = "", mode: str = "all") -> list[U7NPC]:
    query = query.strip().casefold()
    number = int(query) if query.isdecimal() else None
    return [
        npc
        for npc in npcs
        if (
            not query
            or (
                npc.npc_num == number
                if number is not None
                else query in npc.name.casefold()
            )
        )
        and (mode != "party" or npc.in_party)
        and (mode != "alive" or not npc.is_dead and not npc.unused)
        and (mode != "dead" or npc.is_dead)
        and (mode != "unused" or npc.unused)
    ]


def npc_detail(session: Session, npc: U7NPC) -> str:
    sex = "unknown" if npc.is_female is None else "female" if npc.is_female else "male"
    return "\n".join(
        [
            f"NPC {npc.npc_num}: {clean(npc.name) or '(unnamed)'}",
            f"Source: {session.source.path}",
            f"Shape {npc.shape}, frame {npc.frame}, face {npc.face_num}; {sex}",
            f"Map {npc.map_num}; tile ({npc.tile_x}, {npc.tile_y}, {npc.lift}); superchunk {npc.superchunk}",
            f"Health {npc.health}; STR {npc.strength}; DEX {npc.dexterity}; INT {npc.intelligence}; combat {npc.combat}",
            f"Magic {npc.magic}; mana {npc.mana}; EXP {npc.experience}; training {npc.training}; food {npc.food}",
            f"Current activity: {npc.schedule_name}; alignment: {npc.alignment_name}; attack: {npc.attack_mode_name}",
            f"Party: {npc.in_party}; dead: {npc.is_dead}; unused: {npc.unused}",
            f"Flags: rflags=0x{npc.rflags:04X}, type_flags=0x{npc.type_flags:04X}",
            f"Inventory: {len(npc.inventory)} parsed items (including nested contents)",
            f"Saved actor IREG specials: {json.dumps([special.as_row() for special in npc.ireg_specials])}",
            f"Actor extensions: {json.dumps(npc.metadata.as_row()) if npc.metadata is not None else 'unavailable'}",
            f"Resolved actor context: {json.dumps(actor_context(session, npc))}",
        ]
    )


def actor_context(session: Session, npc: U7NPC) -> dict[str, object]:
    """Use the selected world's metadata and symbols; report only unresolved runtime dependencies."""
    if npc.metadata is None:
        return {"required_context": ["actor_metadata"]}
    avatar_shape = None
    if session.npcs is not None and npc.npc_num != 0:
        avatar = next(
            (actor for actor in session.npcs.npcs if actor.npc_num == 0), None
        )
        if avatar is not None and avatar.metadata is not None:
            result = avatar.metadata.appearance(
                avatar.shape,
                avatar_metadata=session.avatar_metadata,
                have_si_shapes=session.have_si_shapes,
                avatar_skin=session.avatar_skin,
                avatar_female=session.avatar_female,
                avatar_sex_known=avatar.is_female is not None,
            )
            skin_result = result.get("avatar_resolution")
            candidate = (
                skin_result.get("resolved_shape")
                if isinstance(skin_result, dict)
                else None
            )
            avatar_shape = candidate if isinstance(candidate, int) else None
    appearance = npc.metadata.appearance(
        npc.shape,
        avatar_shape=avatar_shape,
        avatar_metadata=session.avatar_metadata,
        have_si_shapes=session.have_si_shapes,
        avatar_skin=session.avatar_skin,
        avatar_female=session.avatar_female,
        avatar_sex_known=npc.is_female is not None,
    )
    named = not npc.metadata.original_new_game and bool(npc.metadata.iflag1 & 8)
    usecode = npc.metadata.resolve_usecode(session.usecode_symbols)
    return {
        "appearance": appearance,
        "resolved_usecode": usecode,
        "usecode_status": "symbols_unavailable"
        if named and session.usecode_symbols is None
        else "symbol_not_found"
        if named and usecode is None
        else "resolved"
        if usecode is not None
        else "unassigned",
        "usecode_sources": session.usecode_sources,
    }


def inventory_rows(session: Session, npc: U7NPC) -> list[dict]:
    rows = []
    for item in npc.inventory:
        row = asdict(item)
        row.update(
            name=session.names.get(item.shape) if session.names else "",
            preferred_slot=session.ready.slot_name_for_shape(item.shape)
            if session.ready
            else "",
            location=f"inside {item.path}" if item.depth else "actor inventory",
        )
        row.update(saved_slot_row(item.ireg_index_id))
        if (
            not item.depth
            and item.ireg_index_id is not None
            and item.ireg_index_id.slot_name
        ):
            row["location"] = f"saved_readied:{item.ireg_index_id.slot_name}"
        if session.effective_ready is not None:
            row["effective_ready"] = session.effective_ready.resolve(
                item.shape, item.frame
            ).as_row()
        rows.append(row)
    return rows


def schedules_text(session: Session, npc: U7NPC) -> str:
    if session.schedules is None:
        return "Daily schedule data unavailable in this source."
    entries = session.schedules.entries.get(npc.npc_num, [])
    if not entries:
        return f"No daily schedule entries for NPC {npc.npc_num}."
    schedules = U7Schedules(
        {npc.npc_num: entries},
        session.schedules.num_npcs,
        session.schedules.format,
        script_names=session.schedules.script_names,
    )
    return schedules.dump_detail({npc.npc_num: clean(npc.name)})
