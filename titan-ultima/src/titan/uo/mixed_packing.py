"""Mixed house packing: house sizes chosen by distance from towns and mountains.

A scenario on top of the exact placement check (``titan.uo.placement``):

- **Classes.** Each house kind is in one class: ``forge`` (the workshops),
  ``small``, ``medium`` or ``large``, by its occupied tiles unless listed.
- **Zones.** The window is split into square zones. Each zone draws a class
  at random among the classes with a kind that fits in it: small houses
  dominate near town regions, large ones grow more likely further out, and
  forges dominate near mountain rock. Each zone also picks one preferred
  kind among those that fit, so neighbourhoods share a style.
- **Packing.** Houses are placed greedily at exactly legal centres: largest
  classes first (castles need the most room), each zone trying its own kind,
  then others of its class, then smaller classes to fill gaps. A house's
  tiles and yard must miss every earlier house's tiles, as in
  :func:`titan.uo.placement.pack_houses`. Fallback kinds are tried in a
  shuffled order per zone.

The draws use a fixed seed, so a run is repeatable. The result is one
plausible built-up world, not a maximum.
"""

from __future__ import annotations

__all__ = [
    "HouseKind",
    "MixedPacking",
    "MixedSettings",
    "class_for",
    "pack_mixed",
    "zone_distances",
]

from dataclasses import dataclass, field

import numpy as np

from titan.uo.housing import HouseFootprint

CLASSES = ("large", "medium", "forge", "small")  # packing order
SMALLER = {"large": ("medium", "small"), "medium": ("small",), "forge": ("small",), "small": ()}


@dataclass(frozen=True)
class HouseKind:
    """One house type taking part in the mix."""

    multi_id: int
    label: str
    house_class: str
    footprint: HouseFootprint

    @property
    def tiles(self) -> int:
        return len(self.footprint.occupied)


@dataclass
class MixedSettings:
    """Tunable scenario parameters (distances in tiles)."""

    zone_size: int = 32
    # Class weights (small, medium, large) at these town distances; linear between.
    town_distance_steps: tuple[int, ...] = (0, 120, 400, 800)
    class_weights: tuple[tuple[float, float, float], ...] = (
        (0.85, 0.13, 0.02),
        (0.60, 0.32, 0.08),
        (0.35, 0.40, 0.25),
        (0.20, 0.35, 0.45),
    )
    mountain_distance: int = 40  # zones this close to rock favour forges
    forge_weight: float = 0.65  # share of such zones that become forge zones
    rock_share: float = 0.25  # a block counts as rock when this share of its cells is rock
    small_tiles: int = 110  # kinds up to this many tiles are small
    large_tiles: int = 280  # kinds from this many tiles are large
    seed: int = 20261018


def class_for(tiles: int, settings: MixedSettings, forge: bool = False) -> str:
    if forge:
        return "forge"
    if tiles <= settings.small_tiles:
        return "small"
    if tiles >= settings.large_tiles:
        return "large"
    return "medium"


def zone_distances(
    shape: tuple[int, int],
    town_mask: np.ndarray,
    rock_mask: np.ndarray,
    settings: MixedSettings,
    block: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """Distance in tiles from each ``block``-cell block to towns and to rock.

    Distances grow one block per step of an alternating 4/8-neighbour
    dilation (an octagonal approximation of Euclidean distance).
    """
    h, w = shape
    bh, bw = (h + block - 1) // block, (w + block - 1) // block

    def blocks(mask, threshold):
        padded = np.zeros((bh * block, bw * block), dtype=np.float32)
        padded[:h, :w] = mask
        share = padded.reshape(bh, block, bw, block).mean(axis=(1, 3))
        return share > threshold

    def distance(seed_mask):
        dist = np.full((bh, bw), np.inf, dtype=np.float32)
        reached = seed_mask.copy()
        dist[reached] = 0
        step = 0
        while not reached.all() and step < max(bh, bw):
            step += 1
            grown = reached.copy()
            grown[1:, :] |= reached[:-1, :]
            grown[:-1, :] |= reached[1:, :]
            grown[:, 1:] |= reached[:, :-1]
            grown[:, :-1] |= reached[:, 1:]
            if step % 2 == 0:  # diagonals every other step
                grown[1:, 1:] |= reached[:-1, :-1]
                grown[1:, :-1] |= reached[:-1, 1:]
                grown[:-1, 1:] |= reached[1:, :-1]
                grown[:-1, :-1] |= reached[1:, 1:]
            dist[grown & ~reached] = step * block
            reached = grown
        return dist

    return distance(blocks(town_mask, 0.0)), distance(blocks(rock_mask, settings.rock_share))


@dataclass
class MixedPacking:
    """Placed houses: ``(x, y, kind index)`` plus the kinds and zone classes."""

    kinds: list[HouseKind]
    placed: list[tuple[int, int, int]]
    zone_classes: np.ndarray  # (zones_high, zones_wide) index into CLASSES
    zone_size: int
    counts: dict[str, int] = field(default_factory=dict)


def _weights_at(distance: float, settings: MixedSettings) -> np.ndarray:
    steps = settings.town_distance_steps
    weights = np.array(settings.class_weights, dtype=np.float64)
    if distance <= steps[0]:
        return weights[0]
    for i in range(1, len(steps)):
        if distance <= steps[i]:
            f = (distance - steps[i - 1]) / (steps[i] - steps[i - 1])
            return weights[i - 1] * (1 - f) + weights[i] * f
    return weights[-1]


def pack_mixed(
    window: tuple[int, int, int, int],
    kinds: list[HouseKind],
    legal_centres: list[tuple[np.ndarray, np.ndarray]],
    town_distance: np.ndarray,
    rock_distance: np.ndarray,
    settings: MixedSettings | None = None,
    block: int = 8,
) -> MixedPacking:
    """Pack a mix of ``kinds`` given each kind's legal ``(rows, cols)`` centres.

    ``town_distance``/``rock_distance`` come from :func:`zone_distances`
    (per ``block``-cell block, in tiles).
    """
    settings = settings or MixedSettings()
    rng = np.random.default_rng(settings.seed)
    x0, y0, x1, y1 = window
    h, w = y1 - y0, x1 - x0
    zs = settings.zone_size
    zh, zw = (h + zs - 1) // zs, (w + zs - 1) // zs

    # Which kinds have legal centres in each zone.
    by_class = {c: [i for i, k in enumerate(kinds) if k.house_class == c] for c in CLASSES}
    zone_of = [(rows // zs) * zw + (cols // zs) for rows, cols in legal_centres]
    fits = np.stack(
        [np.bincount(z, minlength=zh * zw)[: zh * zw] > 0 for z in zone_of], axis=1
    ) if kinds else np.zeros((zh * zw, 0), dtype=bool)

    # Zone classes from town and rock distance at each zone's centre block. A
    # zone only draws a class with at least one kind that fits in it, so large
    # draws land where large houses can actually go.
    zone_class = np.zeros((zh, zw), dtype=np.int8)
    zone_kind = np.full((zh, zw), -1, dtype=np.int32)
    zone_order: list[list[int]] = []
    for zy in range(zh):
        for zx in range(zw):
            zone = zy * zw + zx
            by_ = min((zy * zs + zs // 2) // block, town_distance.shape[0] - 1)
            bx_ = min((zx * zs + zs // 2) // block, town_distance.shape[1] - 1)
            fitting = {
                c: [i for i in by_class[c] if fits[zone, i]] for c in CLASSES
            }
            weights = dict(zip(("small", "medium", "large"),
                               _weights_at(float(town_distance[by_, bx_]), settings)))
            near_rock = rock_distance[by_, bx_] <= settings.mountain_distance
            cls = None
            if near_rock and fitting["forge"] and rng.random() < settings.forge_weight:
                cls = "forge"
            if cls is None:
                options = [c for c in ("small", "medium", "large") if fitting[c]]
                if options:
                    p = np.array([weights[c] for c in options])
                    cls = str(rng.choice(options, p=p / p.sum())) if p.sum() > 0 else options[0]
                else:
                    cls = "small"
            zone_class[zy, zx] = CLASSES.index(cls)
            own = int(rng.choice(fitting[cls])) if fitting[cls] else -1
            zone_kind[zy, zx] = own
            # Preference: own kind, the rest of its class, then smaller
            # classes, each group in a shuffled order so no kind always wins.
            order = [own] if own >= 0 else []
            rest = [i for i in by_class[cls] if i != own]
            order += [int(i) for i in rng.permutation(rest)] if rest else []
            for smaller in SMALLER[cls]:
                group = by_class[smaller]
                order += [int(i) for i in rng.permutation(group)] if group else []
            zone_order.append(order)

    # Conflict stamps: a centre c' for kind k is blocked by a house of kind s at
    # c when c' + (yard_k | occupied_k) meets c + occupied_s.
    reach = [np.array(sorted(k.footprint.yard | k.footprint.occupied)) for k in kinds]
    occupied = [np.array(sorted(k.footprint.occupied)) for k in kinds]
    stamps: dict[tuple[int, int], tuple[np.ndarray, int, int]] = {}

    def stamp(k: int, s: int):
        key = (k, s)
        if key not in stamps:
            diffs = (occupied[s][:, None, :] - reach[k][None, :, :]).reshape(-1, 2)
            dx0, dy0 = diffs.min(axis=0)
            dx1, dy1 = diffs.max(axis=0)
            mask = np.zeros((dy1 - dy0 + 1, dx1 - dx0 + 1), dtype=bool)
            mask[diffs[:, 1] - dy0, diffs[:, 0] - dx0] = True
            stamps[key] = (mask, int(dx0), int(dy0))
        return stamps[key]

    margin = 64
    blocked = [np.zeros((h + 2 * margin, w + 2 * margin), dtype=bool) for _ in kinds]

    max_rank = max((len(order) for order in zone_order), default=0)
    placed: list[tuple[int, int, int]] = []
    pref_rank = np.full((zh * zw, len(kinds)), 10**6, dtype=np.int32)
    for zone, order in enumerate(zone_order):
        for rank, k in enumerate(order):
            pref_rank[zone, k] = rank

    for rank in range(max_rank):
        for k in sorted(range(len(kinds)), key=lambda i: -kinds[i].tiles):
            rows, cols = legal_centres[k]
            if len(rows) == 0:
                continue
            take = pref_rank[zone_of[k], k] == rank
            for r, c in zip(rows[take].tolist(), cols[take].tolist()):
                if blocked[k][r + margin, c + margin]:
                    continue
                placed.append((x0 + c, y0 + r, k))
                for other in range(len(kinds)):
                    mask, dx0, dy0 = stamp(other, k)
                    ys = r + margin + dy0
                    xs = c + margin + dx0
                    region = blocked[other][ys : ys + mask.shape[0], xs : xs + mask.shape[1]]
                    region |= mask[: region.shape[0], : region.shape[1]]

    counts: dict[str, int] = {}
    for _x, _y, k in placed:
        counts[kinds[k].house_class] = counts.get(kinds[k].house_class, 0) + 1
    return MixedPacking(kinds, placed, zone_class, zs, counts)
