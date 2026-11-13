"""Martian Dreams actor decoding, checked against Nuvie's ActorManager.cpp.

MD uses status bit 0 for cold rather than U6's protection effect. The byte
Nuvie loads as magic at 0x12f1 has uncertain MD semantics and remains raw.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from titan.u6.actor import U6Actor, U6ActorLayout, U6Actors

__all__ = ["MD_ACTOR_LAYOUT", "MartianActor", "parse_martian_actors"]

MD_ACTOR_LAYOUT = U6ActorLayout(
    base_appearance=0x16F1,
    talk_flags=0x18F1,
    movement_flags=0x1AF1,
    combat_mode=0x13F1,
    magic=0x12F1,
)


@dataclass
class MartianActor(U6Actor):
    """One MD actor slot, with movement points, current worktype and MD status meanings."""

    movement_points: int
    worktype: int
    name: str = ""

    @property
    def is_cold(self) -> bool:
        """MD status bit 0 indicates cold exposure."""
        return bool(self.status_flags & 1)

    @property
    def is_protected(self) -> bool:
        """MD's cold bit must never be interpreted as Ultima VI protection."""
        return False

    @property
    def is_hypoxic(self) -> bool:
        """MD object flag 6 indicates hypoxia."""
        return bool(self.obj_flags & 0x40)

    @property
    def is_frenzied(self) -> bool:
        """MD object flag 7 indicates battle frenzy."""
        return bool(self.obj_flags & 0x80)


def parse_martian_actors(data: bytes) -> list[MartianActor]:
    """Read all 256 MD actor slots without applying U6 save-state offsets."""
    return [
        MartianActor(
            **asdict(actor),
            movement_points=data[0x15F1 + actor.actor_id],
            worktype=data[0x11F1 + actor.actor_id],
        )
        for actor in U6Actors.parse(data, layout=MD_ACTOR_LAYOUT)
    ]
