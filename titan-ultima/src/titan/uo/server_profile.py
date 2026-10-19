"""Server profiles: the server-side data house placement needs, in one file.

The client holds maps, tiles and house layouts, but not the rules a server
applies on top of them:
- which areas forbid housing (regions);
- which region types forbid it;
- which houses the placement menu offers, and where each anchors.

A server profile is a JSON file carrying that data, resolved so it can be
used without the emulator's source:

- ``regions``: per facet, each region's rank (priority, nesting level, file
  order), whether it allows housing, whether it is in a NoHousingRegion
  chain, and its rectangles with z ranges;
- ``forbidding_types``: region classes whose ``AllowHousing`` is false;
- ``houses``: the placement menu (category, type, cliloc, multi, cursor
  offset, cost and storage).

Build one from an emulator folder with :func:`build_server_profile`. A
profile built from RunUO or ServUO is derived from GPL-licensed data, so
profiles are kept with a user's data, not shipped with Titan.

Without a profile, :func:`builtin_house_entries` lists the classic houses
and customizable plots found in the client's multis, and region rules are
absent.
"""

from __future__ import annotations

__all__ = [
    "PROFILE_FORMAT",
    "ServerProfile",
    "build_server_profile",
    "builtin_house_entries",
]

from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path

from titan.uo.housing import HousePlacementEntry, house_footprint, parse_house_placement_tool
from titan.uo.placement import _parse_region_rects, no_housing_region_types

PROFILE_FORMAT = "titan-uo-server-profile"
PROFILE_VERSION = 1
FACETS = ("Felucca", "Trammel", "Ilshenar", "Malas", "Tokuno", "TerMur")

# The original classic houses: multi ID, cliloc name, emulator type.
_CLASSIC_HOUSES = (
    (0x0064, 1011303, "SmallOldHouse"),
    (0x0066, 1011304, "SmallOldHouse"),
    (0x0068, 1011305, "SmallOldHouse"),
    (0x006A, 1011306, "SmallOldHouse"),
    (0x006C, 1011307, "SmallOldHouse"),
    (0x006E, 1011308, "SmallOldHouse"),
    (0x0074, 1011309, "GuildHouse"),
    (0x0076, 1011310, "TwoStoryHouse"),
    (0x0078, 1011311, "TwoStoryHouse"),
    (0x007A, 1011312, "Tower"),
    (0x007C, 1011313, "Keep"),
    (0x007E, 1011314, "Castle"),
    (0x008C, 1011315, "LargePatioHouse"),
    (0x0096, 1011316, "LargeMarbleHouse"),
    (0x0098, 1011317, "SmallTower"),
    (0x009A, 1011318, "LogCabin"),
    (0x009C, 1011320, "SandStonePatio"),
    (0x009E, 1011319, "TwoStoryVilla"),
    (0x00A0, 1011321, "SmallShop"),
    (0x00A2, 1011322, "SmallShop"),
)
_PLOT_RANGE = range(0x13EC, 0x147C)  # customizable foundations, 7x7 .. 18x18


@dataclass
class ServerProfile:
    """A loaded server profile."""

    name: str
    source: dict[str, object]
    forbidding_types: frozenset[str]
    regions: dict[str, list[dict[str, object]]]
    houses: list[HousePlacementEntry]
    notes: list[str] = field(default_factory=list)
    path: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> ServerProfile:
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != PROFILE_FORMAT:
            raise ValueError(f"{path} is not a {PROFILE_FORMAT} file")
        if data.get("version") != PROFILE_VERSION:
            raise ValueError(f"{path}: unsupported profile version {data.get('version')}")
        houses = [
            HousePlacementEntry(
                category=h["category"],
                type_name=h["type"],
                cliloc=int(h["cliloc"]),
                storage=int(h.get("storage", 0)),
                lockdowns=int(h.get("lockdowns", 0)),
                new_storage=int(h.get("new_storage", 0)),
                new_lockdowns=int(h.get("new_lockdowns", 0)),
                vendors=int(h.get("vendors", 0)),
                cost=int(h.get("cost", 0)),
                offset=tuple(h.get("offset", (0, 0, 0))),
                multi_id=int(h["multi"], 0),
            )
            for h in data.get("houses", [])
        ]
        return cls(
            name=data.get("name", path.stem),
            source=data.get("source", {}),
            forbidding_types=frozenset(data.get("forbidding_types", [])),
            regions=data.get("regions", {}),
            houses=houses,
            notes=data.get("notes", []),
            path=path,
        )

    def region_rects(self, facet_name: str) -> list[tuple] | None:
        """Region rectangles for ``facet_name``, lowest rank first, or ``None``.

        Items match :func:`titan.uo.placement.region_layers_from_rects`.
        """
        regions = next(
            (v for k, v in self.regions.items() if k.lower() == facet_name.lower()), None
        )
        if regions is None:
            return None
        rects = []
        for region in regions:
            key = (int(region["priority"]), int(region["level"]), -int(region["order"]))
            for x, y, w, h, z1, z2 in region["rects"]:
                rects.append((
                    key, bool(region["allow"]), bool(region["no_housing"]),
                    x, y, w, h, z1, z2, region["name"], region["type"],
                ))
        rects.sort(key=lambda r: r[0])
        return rects

    def to_json(self) -> dict[str, object]:
        return {
            "format": PROFILE_FORMAT,
            "version": PROFILE_VERSION,
            "name": self.name,
            "source": self.source,
            "notes": self.notes,
            "forbidding_types": sorted(self.forbidding_types),
            "houses": [
                {
                    "category": h.category,
                    "type": h.type_name,
                    "cliloc": h.cliloc,
                    "multi": f"0x{h.multi_id:04X}",
                    "offset": list(h.offset),
                    "cost": h.cost,
                    "storage": h.storage,
                    "lockdowns": h.lockdowns,
                    "new_storage": h.new_storage,
                    "new_lockdowns": h.new_lockdowns,
                    "vendors": h.vendors,
                }
                for h in self.houses
            ],
            "regions": self.regions,
        }

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1), encoding="utf-8")
        self.path = path
        return path


def build_server_profile(
    name: str,
    *,
    regions_xml: str | Path,
    scripts_dir: str | Path,
    placement_tool: str | Path,
    source: dict[str, object] | None = None,
    notes: list[str] | None = None,
) -> ServerProfile:
    """Resolve an emulator's regions, region rules and house menu into a profile.

    Region rules are resolved exactly as ``house-capacity`` resolves them
    from the XML: rank, nesting, z ranges, AllowHousing through the parent
    chain, and the NoHousingRegion centre rule.
    """
    forbidding = no_housing_region_types(scripts_dir)
    regions: dict[str, list[dict[str, object]]] = {}
    for facet in FACETS:
        try:
            rects, _counts = _parse_region_rects(regions_xml, facet, forbidding)
        except ValueError:
            continue  # facet absent from this emulator's file
        grouped: dict[tuple, dict[str, object]] = {}
        for key, allow, no_housing, x, y, w, h, z1, z2, region_name, rtype in rects:
            record = grouped.setdefault(key, {
                "name": region_name,
                "type": rtype,
                "priority": key[0],
                "level": key[1],
                "order": -key[2],
                "allow": allow,
                "no_housing": no_housing,
                "rects": [],
            })
            record["rects"].append([x, y, w, h, z1, z2])
        regions[facet] = sorted(grouped.values(), key=lambda r: r["order"])
    used = {r["type"] for facet in regions.values() for r in facet}
    return ServerProfile(
        name=name,
        source={"built": date.today().isoformat(), **(source or {})},
        forbidding_types=frozenset(t for t in forbidding if t in used),
        regions=regions,
        houses=parse_house_placement_tool(placement_tool),
        notes=notes or [],
    )


def builtin_house_entries(multis, tiledata) -> list[HousePlacementEntry]:
    """Classic houses and customizable plots present in the client's multis.

    Used when no server profile or placement table is available. Plots are
    named by their size (``7x7 customizable plot``); cursor offsets, costs
    and storage are unknown and left at 0.
    """
    entries = [
        HousePlacementEntry("ClassicHouses", type_name, cliloc, 0, 0, 0, 0, 0, 0, (0, 0, 0), multi_id)
        for multi_id, cliloc, type_name in _CLASSIC_HOUSES
        if multi_id in multis.multis
    ]
    for multi_id in _PLOT_RANGE:
        multi = multis.multis.get(multi_id)
        if multi is None:
            continue
        footprint = house_footprint(multi, tiledata)
        x0, x1, y0, y1 = footprint.extent(footprint.occupied)
        width, depth = x1 - x0 + 1, y1 - y0  # the last row is the added stairs
        entries.append(
            HousePlacementEntry(
                "CustomizableFoundations",
                f"{width}x{depth} customizable plot",
                0, 0, 0, 0, 0, 0, 0, (0, 0, 0), multi_id,
            )
        )
    return entries
