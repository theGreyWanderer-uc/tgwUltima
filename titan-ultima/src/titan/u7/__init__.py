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
from titan.u7.palette import U7Palette
from titan.u7.save import (
    U7GlobalFlags, U7Save, U7Identity, U7SaveInfo, U7PartyMember,
    U7GameState, U7Schedules, U7ScheduleEntry, U7NPCData, U7NPC,
)
from titan.u7.shape import U7Shape
from titan.u7.sound import VocDecoder
from titan.u7.typeflag import U7TypeFlags

__all__ = [
    "U7FlexArchive",
    "U7Shape", "U7Palette", "VocDecoder",
    "extract_music", "convert_xmidi_file",
    "U7TypeFlags", "U7MapRenderer", "U7MapSampler",
    "U7Save", "U7GlobalFlags",
    "U7Identity", "U7SaveInfo", "U7PartyMember",
    "U7GameState", "U7Schedules", "U7ScheduleEntry",
    "U7NPCData", "U7NPC",
]
