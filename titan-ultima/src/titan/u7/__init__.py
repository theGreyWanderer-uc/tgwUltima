"""
Ultima 7 subpackage.

Modules for Ultima 7: The Black Gate and Serpent Isle file formats.

Canonical imports::

    from titan.u7.shape import U7Shape
    from titan.u7.palette import U7Palette
    from titan.u7.sound import VocDecoder
    from titan.u7.music import extract_music
    from titan.u7.typeflag import U7TypeFlags
    from titan.u7.map import U7MapRenderer, U7MapSampler
"""

from titan.u7.flex import U7FlexArchive
from titan.u7.map import U7MapRenderer, U7MapSampler
from titan.u7.music import convert_xmidi_file, extract_music
from titan.u7.monster import (
    U7MonsterDefinition,
    U7MonsterDefinitions,
    U7MonsterEquipment,
    monster_equipment_csv,
    monster_equipment_summary,
)
from titan.u7.palette import U7Palette
from titan.u7.save import (
    U7GlobalFlags,
    U7Save,
    U7Identity,
    U7SaveInfo,
    U7PartyMember,
    U7GameState,
    U7UsecodeData,
    U7UsecodeTimer,
    U7UsecodeVars,
    U7Keyring,
    U7FrameFlags,
    U7Schedules,
    U7ScheduleEntry,
    U7NPCData,
    U7NPC,
    U7NPCInventoryItem,
    U7ReadyTypes,
)
from titan.u7.shape import U7Shape
from titan.u7.shapeinfo import (
    U7Ammos,
    U7Armors,
    U7Blends,
    U7Containers,
    U7UsecodeIndex,
    U7Weapons,
    U7Xforms,
)
from titan.u7.sound import VocDecoder
from titan.u7.typeflag import U7TypeFlags
from titan.u7.usecode import (
    U7UsecodeCallSite,
    U7UsecodeFile,
    U7UsecodeFunctionRecord,
    U7UsecodeInstruction,
    load_u7_intrinsic_names,
)
from titan.u7.wihh import U7WeaponInHandOffsets, U7WeaponOffsetFrame

__all__ = [
    "U7FlexArchive",
    "U7Shape",
    "U7Palette",
    "VocDecoder",
    "extract_music",
    "convert_xmidi_file",
    "U7TypeFlags",
    "U7MapRenderer",
    "U7MapSampler",
    "U7MonsterDefinition",
    "U7MonsterDefinitions",
    "U7MonsterEquipment",
    "monster_equipment_csv",
    "monster_equipment_summary",
    "U7Save",
    "U7GlobalFlags",
    "U7Identity",
    "U7SaveInfo",
    "U7PartyMember",
    "U7GameState",
    "U7UsecodeData",
    "U7UsecodeTimer",
    "U7UsecodeVars",
    "U7Keyring",
    "U7FrameFlags",
    "U7Schedules",
    "U7ScheduleEntry",
    "U7NPCData",
    "U7NPC",
    "U7NPCInventoryItem",
    "U7ReadyTypes",
    "U7WeaponInHandOffsets",
    "U7WeaponOffsetFrame",
    "U7Weapons",
    "U7Ammos",
    "U7Armors",
    "U7Containers",
    "U7Xforms",
    "U7Blends",
    "U7UsecodeIndex",
    "U7UsecodeFile",
    "U7UsecodeFunctionRecord",
    "U7UsecodeInstruction",
    "U7UsecodeCallSite",
    "load_u7_intrinsic_names",
]
