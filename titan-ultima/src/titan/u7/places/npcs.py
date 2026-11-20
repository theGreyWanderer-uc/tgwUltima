"""NPCs at the START OF THE GAME: where each stands and where its schedule sends it.

Everything here is read from the starting world only:
- positions from STATIC/INITGAME.DAT (where each NPC stands when a new game
  begins), and
- schedules from STATIC/SCHEDULE.DAT (the eight 3-hour slots each NPC is
  given at the start).
Both change as the game is played (NPCs die, move, join the party, and the
plot rewrites schedules), so nothing here says who is in a place later on.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from titan.u7.save import SCHEDULE_TYPE_NAMES, U7NPCData, U7Schedules

BASIS = "start of game: INITGAME.DAT positions and SCHEDULE.DAT schedules"
# Schedule activities that mean the NPC works here, or lives here.
WORK = {
    "tend_shop", "bake", "blacksmith", "sew", "lab", "waiter", "desk_work",
    "farm", "miner", "preach",
}  # fmt: skip
HOME = {"sleep"}


def _find(static_dir, name):
    return next((p for p in Path(static_dir).iterdir() if p.name.upper() == name), None)


def load_npcs(static_dir, game: str, map_num: int = 0) -> list[dict]:
    """[{num, name, shape, start: (tx, ty, tz), schedule: [(hour, activity, tx, ty, tz)]}]"""
    init = _find(static_dir, "INITGAME.DAT")
    sched_path = _find(static_dir, "SCHEDULE.DAT")
    if init is None:
        return []
    npcs = U7NPCData.from_initgame_file(str(init), game=game)
    schedules = (
        U7Schedules.from_file(str(sched_path), strict=False).entries
        if sched_path
        else {}
    )
    out = []
    for npc in npcs.npcs:
        name = (npc.name or "").strip()
        if not name or npc.npc_num == 0 or npc.map_num != map_num:
            continue
        out.append(
            {
                "num": npc.npc_num,
                "name": name,
                "shape": npc.shape,
                "start": (npc.tile_x, npc.tile_y, npc.lift),
                "schedule": [
                    (
                        e.time * 3,
                        SCHEDULE_TYPE_NAMES.get(e.type, f"type_{e.type}"),
                        e.tx,
                        e.ty,
                        e.tz,
                    )
                    for e in schedules.get(npc.npc_num, [])
                ],
            }
        )
    return out


def presence(
    npcs: list[dict], owner_at: Callable[[int, int], int | None], count: int
) -> list[list[dict]]:
    """Per place, the NPCs that start there or are scheduled there.

    `owner_at(tx, ty)` gives a place index or None. Returns `count` lists of
    {num, name, starts_here, start, sleeps_here, works_here, schedule_here}.
    """
    found: list[dict] = [{} for _ in range(count)]

    def entry(owner, npc):
        return found[owner].setdefault(
            npc["num"],
            {
                "num": npc["num"],
                "name": npc["name"],
                "starts_here": False,
                "start": list(npc["start"]),
                "sleeps_here": False,
                "works_here": False,
                "schedule_here": [],
            },
        )

    for npc in npcs:
        owner = owner_at(npc["start"][0], npc["start"][1])
        if owner is not None:
            entry(owner, npc)["starts_here"] = True
        for hour, activity, tx, ty, _tz in npc["schedule"]:
            owner = owner_at(tx, ty)
            if owner is None:
                continue
            rec = entry(owner, npc)
            rec["schedule_here"].append({"hour": hour, "activity": activity})
            rec["sleeps_here"] |= activity in HOME
            rec["works_here"] |= activity in WORK
    return [sorted(place.values(), key=lambda r: r["num"]) for place in found]
