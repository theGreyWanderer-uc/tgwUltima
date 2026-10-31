"""
Ultima 8: Pagan — game-specific modules.

Re-exports all U8 public symbols for convenient access::

    from titan.u8 import U8Shape, U8Palette, U8MapRenderer
"""

from __future__ import annotations

from titan.u8.shape import U8Shape
from titan.u8.itemcach import (
    U8ItemCache,
    U8CachedItem,
    U8CacheMetadata,
    U8CacheRegion,
    U8ItemChain,
    U8ItemCacheError,
)
from titan.u8.npcdata import U8NpcData, U8NpcState, U8NpcDataError
from titan.u8.map_items import U8MapItems, U8MapItem, U8MapItemsError
from titan.u8.anim import U8AnimData, U8AnimAction, U8AnimFrame, U8AnimError
from titan.u8.wpnovlay import (
    U8WeaponOverlayData,
    U8WeaponOverlayAction,
    U8WeaponOverlayType,
    U8WeaponOverlayFrame,
    U8WeaponOverlayError,
)
from titan.u8.map import U8MapRenderer, U8MapSampler
from titan.u8.sound import SonarcDecoder
from titan.u8.save import U8SaveArchive
from titan.u8.flags import U8GlobalFlags, U8FlagSymbols, U8FlagSymbol
from titan.u8.avatar import U8AvatarState
from titan.u8.gumps import U8GumpState, U8ContainerGump
from titan.u8.kernel import U8KernelState, U8KernelProcess
from titan.u8.kernel_process import U8KernelProcessDetails, decode_u8_kernel_process
from titan.u8.save_state import U8SaveSnapshot
from titan.u8.typeflag import U8TypeFlags
from titan.u8.credits import decrypt_credit_text
from titan.u8.xformpal import U8_XFORM_PALETTE

__all__ = [
    "U8AvatarState",
    "U8GumpState",
    "U8ContainerGump",
    "U8KernelState",
    "U8KernelProcess",
    "U8KernelProcessDetails",
    "decode_u8_kernel_process",
    "U8GlobalFlags",
    "U8FlagSymbols",
    "U8FlagSymbol",
    "U8SaveSnapshot",
    "U8MapItems",
    "U8MapItem",
    "U8MapItemsError",
    "U8ItemCache",
    "U8CachedItem",
    "U8CacheMetadata",
    "U8CacheRegion",
    "U8ItemChain",
    "U8ItemCacheError",
    "U8NpcData",
    "U8NpcState",
    "U8NpcDataError",
    "U8WeaponOverlayData",
    "U8WeaponOverlayAction",
    "U8WeaponOverlayType",
    "U8WeaponOverlayFrame",
    "U8WeaponOverlayError",
    "U8AnimData",
    "U8AnimAction",
    "U8AnimFrame",
    "U8AnimError",
    "U8Shape",
    "U8MapRenderer",
    "U8MapSampler",
    "SonarcDecoder",
    "U8SaveArchive",
    "U8TypeFlags",
    "decrypt_credit_text",
    "U8_XFORM_PALETTE",
]
