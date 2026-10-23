"""Synthetic freeze frames: where every player stands at the moment of a shot.

The generator first samples the three quantities the xG model reads from a real
freeze frame (defenders in the shooting cone, distance to the nearest defender,
goalkeeper distance to goal) from Premier League 2015/16 distributions conditioned
on the situation (assist type, shot distance, pressure, one-on-one), then places
the actual players on the pitch so that the frame realises those values. Team
tactics nudge the result: a deep, compact block puts more bodies in the cone, a
counter-attack catches defenders upfield.

Output entries follow the StatsBomb format, so `xg.features` reads synthetic and
real frames with the very same code.
"""
from __future__ import annotations

import math
import random

from xg.features import GOAL_X, GOAL_Y, POST_LEFT, POST_RIGHT, is_in_triangle, shot_distance

from . import calibration_data as cal
from .formations import POSITION_NAME, POSITION_XY

BANDS = ("0-12", "12-18", "18-25", "25+")


def dist_band(d: float) -> str:
    return "0-12" if d < 12 else "12-18" if d < 18 else "18-25" if d < 25 else "25+"


def sample_quantiles(rng: random.Random, q: list, lo: float = 0.25) -> float:
    """Sample from a distribution given by its 5/25/50/75/95 percentiles (piecewise linear)."""
    probs = (0.05, 0.25, 0.5, 0.75, 0.95)
    u = rng.random()
    if u <= probs[0]:
        v = q[0] - (probs[0] - u) / probs[0] * (q[1] - q[0]) * 0.5
    elif u >= probs[-1]:
        v = q[-1] + (u - probs[-1]) / (1 - probs[-1]) * (q[-1] - q[-2]) * 0.8
    else:
        for k in range(len(probs) - 1):
            if probs[k] <= u <= probs[k + 1]:
                t = (u - probs[k]) / (probs[k + 1] - probs[k])
                v = q[k] + t * (q[k + 1] - q[k])
                break
    return max(lo, v)


def _pick(rng, dist: dict):
    keys = list(dist)
    return rng.choices(keys, weights=[dist[k] for k in keys])[0]


def sample_cone(rng, assist_type: str, band: str) -> int:
    ff = cal.FREEZE_FRAME_TARGETS
    dist = ff["cone_by_assist_band"].get(f"{assist_type}|{band}") \
        or ff["by_assist"].get(assist_type, {}).get("cone") or ff["overall"]["cone"]
    return int(_pick(rng, dist))


def sample_nearest(rng, under_pressure: bool, band: str) -> float:
    q = cal.FREEZE_FRAME_TARGETS["nearest_q_by_pressure_band"][f"{bool(under_pressure)}|{band}"]
    return sample_quantiles(rng, q, lo=0.3)


def sample_gk(rng, one_on_one: bool, band: str) -> float:
    table = cal.FREEZE_FRAME_TARGETS["gk_q_by_band"]
    q = table.get(f"{bool(one_on_one)}|{band}") or table[f"False|{band}"]
    return sample_quantiles(rng, q, lo=0.3)


def _cone_angles(x, y):
    a1 = math.atan2(POST_LEFT[1] - y, POST_LEFT[0] - x)
    a2 = math.atan2(POST_RIGHT[1] - y, POST_RIGHT[0] - x)
    return min(a1, a2), max(a1, a2)


def _inside_pitch(p):
    return 0.5 <= p[0] <= 119.5 and 0.5 <= p[1] <= 79.5


def _point_in_cone(rng, shooter, min_dist, tries=300):
    """Uniform point in the triangle shooter / posts, at least `min_dist` from the shooter."""
    a, b, c = shooter, POST_LEFT, POST_RIGHT
    for _ in range(tries):
        r1, r2 = rng.random(), rng.random()
        if r1 + r2 > 1:
            r1, r2 = 1 - r1, 1 - r2
        p = (a[0] + r1 * (b[0] - a[0]) + r2 * (c[0] - a[0]), a[1] + r1 * (b[1] - a[1]) + r2 * (c[1] - a[1]))
        if math.dist(p, shooter) >= min_dist and p[0] <= 119.3:
            return p
    return None


def build_freeze_frame(rng: random.Random, shooter_xy, attackers, defenders, *, assist_type: str,
                       under_pressure: bool, one_on_one: bool, defending_tactics: dict,
                       counter_attack: bool = False, set_piece: bool = False) -> list:
    """Return a StatsBomb-style freeze frame.

    attackers / defenders: lists of (player, slot_code) currently on the pitch
    (shooter excluded from attackers; defenders include the goalkeeper).
    Coordinates are in the shooting team's attacking frame (goal at x = 120).
    """
    x, y = shooter_xy
    band = dist_band(shot_distance(x, y))

    # 1) sample the target quantities ---------------------------------------
    n_cone = 0 if one_on_one else sample_cone(rng, assist_type, band)
    line = defending_tactics.get("line_height", 0.5)
    compact = defending_tactics.get("compactness", 0.5)
    if not one_on_one:
        if rng.random() < max(0.0, (0.5 - line) * 0.35 + (compact - 0.5) * 0.25):
            n_cone += 1                                  # deep, compact block: more bodies in the way
        if counter_attack and n_cone > 0 and rng.random() < 0.15:
            n_cone -= 1                                  # defence caught out of shape
    nearest = sample_nearest(rng, under_pressure, band)
    gk_dist = sample_gk(rng, one_on_one, band)

    gk = [(p, s) for p, s in defenders if s == "GK"]
    outfield = [(p, s) for p, s in defenders if s != "GK"]
    n_cone = min(n_cone, len(outfield) - 1 if len(outfield) > 1 else 0)
    frame = []

    def entry(player, slot, loc, teammate):
        return {"location": [round(loc[0], 1), round(loc[1], 1)],
                "player": {"id": player.id, "name": player.name},
                "position": {"name": POSITION_NAME[slot]}, "teammate": teammate}

    # 2) goalkeeper: on the line between goal centre and ball ---------------
    if gk:
        vx, vy = x - GOAL_X, y - GOAL_Y
        norm = math.hypot(vx, vy) or 1.0
        gx = GOAL_X + vx / norm * gk_dist
        gy = GOAL_Y + vy / norm * gk_dist + rng.gauss(0, 0.5)
        gx = min(gx, 119.6)
        frame.append(entry(gk[0][0], "GK", (gx, gy), False))

    # 3) defenders' natural positions (mirrored into the shooting frame) ----
    # The block collapses towards its own goal and towards the ball: a deep, compact
    # team defends inside its box, a high line is caught further up.
    back_line = min(114.0, max(99.0, x + 3 + 7 * (1 - line))) if not set_piece else 112.0
    natural = {}
    attackers_up = ("RW", "LW", "ST", "RCF", "LCF", "SS", "CAM", "RAM", "LAM", "RM", "LM")
    for p, s in outfield:
        bx, by = POSITION_XY[s]
        dy = 80 - by                                     # mirror: defender's own goal is at x = 120 here
        group_depth = {"GK": 0}.get(s, 0)
        if s in ("RCB", "CB", "LCB", "RB", "LB", "RWB", "LWB"):
            nx = back_line + rng.gauss(0, 2.0)
        elif s in ("RDM", "CDM", "LDM", "RCM", "CM", "LCM"):
            nx = back_line - rng.uniform(5, 12)
        else:
            nx = (rng.uniform(55, 80) if counter_attack else back_line - rng.uniform(12, 30))
        width = 0.35 + 0.35 * (1 - compact)
        ny = (40 + (dy - 40) * width) * 0.6 + y * 0.4 + rng.gauss(0, 2.5)
        natural[p.id] = (min(118.5, max(40, nx + group_depth)), min(78, max(2, ny)))

    # 4) targets: nearest defender + cone defenders -------------------------
    targets = []
    lo, hi = _cone_angles(x, y)
    want_nearest_in_cone = n_cone > 0 and rng.random() < 0.45
    for _ in range(80):
        if want_nearest_in_cone:
            ang = rng.uniform(lo, hi)
        else:
            ang = rng.uniform(-math.pi, math.pi)
        cand = (x + nearest * math.cos(ang), y + nearest * math.sin(ang))
        inside = is_in_triangle(cand, (x, y), POST_LEFT, POST_RIGHT)
        if _inside_pitch(cand) and cand[0] <= 119.3 and (inside == want_nearest_in_cone):
            targets.append(cand)
            break
    else:
        targets.append((max(1, x - nearest), y))
    nearest_in_cone = is_in_triangle(targets[0], (x, y), POST_LEFT, POST_RIGHT)
    for _ in range(n_cone - int(nearest_in_cone)):
        pt = _point_in_cone(rng, (x, y), nearest + 0.15)
        if pt:
            targets.append(pt)

    # assign the defenders closest (by natural position) to each target
    free = dict(natural)
    assigned = {}
    for t in targets:
        if not free:
            break
        pid = min(free, key=lambda k: math.dist(free[k], t))
        assigned[pid] = t
        free.pop(pid)

    # 5) remaining defenders: natural position, kept out of the cone and the nearest radius
    for pid, loc in free.items():
        p_loc = loc
        for _ in range(40):
            if (not is_in_triangle(p_loc, (x, y), POST_LEFT, POST_RIGHT)) and math.dist(p_loc, (x, y)) > nearest + 0.15:
                break
            side = 1 if p_loc[1] >= y else -1
            p_loc = (p_loc[0] + rng.uniform(-2, 1), min(79, max(1, p_loc[1] + side * rng.uniform(1.5, 4))))
        assigned[pid] = p_loc

    for p, s in outfield:
        frame.append(entry(p, s, assigned[p.id], False))

    # 6) attacking teammates: slot positions pushed up towards the box -------
    for p, s in attackers:
        bx, by = POSITION_XY[s]
        if s == "GK":
            loc = (rng.uniform(15, 30), 40 + rng.gauss(0, 4))
        else:
            ax = bx + (x - 60) * 0.45 + rng.gauss(0, 4)
            ay = by + (y - by) * 0.15 + rng.gauss(0, 4)
            loc = (min(117, max(20, ax)), min(78, max(2, ay)))
        frame.append(entry(p, s, loc, True))
    return frame
