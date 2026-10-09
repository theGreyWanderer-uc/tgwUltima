"""Verified U8 usecode gump choices for closed containers and native NPC inventories."""

from __future__ import annotations

from dataclasses import dataclass

from titan.u8.save_state import U8SaveSnapshot

# U8_SRC/source/EUSECODE/<class>.unk: Item_openGump(constant, this).
# These are usecode class IDs, not inferred matches on the object's name.
U8_CONTAINER_GUMP_SHAPES: dict[int, int] = {
    78: 7,  # CHEST_EW
    115: 4,  # BARREL
    116: 10,  # JBOX
    117: 7,  # CHEST_NS
    185: 14,  # BASKET
    203: 13,  # CODNS
    204: 13,  # CODEW
    205: 13,  # DESKEW
    208: 13,  # DESKNS
    218: 12,  # DEADNS
    219: 12,  # DEADEW
    235: 12,  # BONES
    237: 12,  # BONES2
    306: 13,  # WARDNS
    307: 13,  # WARDEW
    332: 12,  # BONES3
    358: 12,  # BONES4
    529: 2,  # BACKPACK
    618: 7,  # LCHST_EW
    637: 3,  # BAG
    673: 7,  # LCHST_NS
}


@dataclass(frozen=True)
class U8ContainerGumpPreview:
    """Artwork identity with provenance; usecode defaults do not represent an open UI."""

    index: int | None
    shape: int
    frame: int
    source: str
    usecode_class: int | None = None

    @property
    def description(self) -> str:
        """Describe why this gump shape was selected without implying the UI is open."""
        if self.source == "saved_gumps":
            return f"Saved gump {self.index}"
        if self.source == "native_dead_npc":
            return "Native dead-NPC inventory"
        if self.source == "npc_backpack_fallback":
            return "Backpack preview fallback for NPC inventory"
        return f"Verified usecode class {self.usecode_class}"


def resolve_u8_container_gumps(
    snapshot: U8SaveSnapshot,
    item_id: int,
    *,
    family: int | None,
    npc_backpack: bool = True,
) -> list[U8ContainerGumpPreview]:
    """Prefer saved/native artwork; label optional backpack fallbacks for unknown NPC gumps."""
    if snapshot.gumps:
        saved = [
            U8ContainerGumpPreview(gump.index, gump.shape, gump.frame, "saved_gumps")
            for gump in snapshot.gumps.containers
            if gump.container_id == item_id
        ]
        if saved:
            return saved
    if snapshot.item_cache is None:
        return []
    item = snapshot.item_cache.get_item(item_id)
    if 0 < item_id < 256:
        if not item.shape or snapshot.item_cache.slot_membership(item_id) in {
            "null",
            "free_npc",
            "free_item",
        }:
            return []
        # Native ITEM.C::use checks NPC death before usecode dispatch.
        if snapshot.npc_data is None:
            return (
                [U8ContainerGumpPreview(None, 2, 0, "npc_backpack_fallback")]
                if npc_backpack
                else []
            )
        if snapshot.npc_data.get_npc(item_id).state_flags & 0x10:
            return [U8ContainerGumpPreview(None, 12, 0, "native_dead_npc")]
        # UPROCESS.C::spawnUnk dispatches permanent slots to slot+1024.
        # AVATAR.unk::use opens gump 1; other living NPCs have no default here.
        if item_id == 1 and not item.status & 0x80:
            return [U8ContainerGumpPreview(None, 1, 0, "verified_usecode", 1025)]
        return (
            [U8ContainerGumpPreview(None, 2, 0, "npc_backpack_fallback")]
            if npc_backpack
            else []
        )
    return resolve_u8_shape_container_gumps(item.shape, family=family)


def resolve_u8_shape_container_gumps(
    shape: int, *, family: int | None
) -> list[U8ContainerGumpPreview]:
    """Resolve verified ordinary usecode artwork without using cache IDs for map records."""
    if family != 6:
        return []
    gump_shape = U8_CONTAINER_GUMP_SHAPES.get(shape)
    if gump_shape is None:
        return []
    # ContainerGump is initially created with frame 0 (native GumpShape/Pentagram Item).
    return [U8ContainerGumpPreview(None, gump_shape, 0, "verified_usecode", shape)]
