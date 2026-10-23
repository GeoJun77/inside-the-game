"""Positions and formations, using StatsBomb position names and codes.

FORMATIONS maps a StatsBomb formation code (e.g. "4231") to its 11 slots, in the
order StatsBomb lists them in "Starting XI" events. FORMATION_WEIGHTS holds how
often each formation was used as a starting formation in the Premier League
2015/16 (StatsBomb Open Data). Both are produced by tools/calibrate_from_statsbomb.py.
"""
from __future__ import annotations

# StatsBomb position name -> short code
POSITION_CODE = {
    "Goalkeeper": "GK", "Right Back": "RB", "Right Center Back": "RCB", "Center Back": "CB",
    "Left Center Back": "LCB", "Left Back": "LB", "Right Wing Back": "RWB", "Left Wing Back": "LWB",
    "Right Defensive Midfield": "RDM", "Center Defensive Midfield": "CDM", "Left Defensive Midfield": "LDM",
    "Right Midfield": "RM", "Right Center Midfield": "RCM", "Center Midfield": "CM",
    "Left Center Midfield": "LCM", "Left Midfield": "LM", "Right Wing": "RW",
    "Right Attacking Midfield": "RAM", "Center Attacking Midfield": "CAM", "Left Attacking Midfield": "LAM",
    "Left Wing": "LW", "Right Center Forward": "RCF", "Center Forward": "ST", "Left Center Forward": "LCF",
    "Secondary Striker": "SS",
}
POSITION_NAME = {v: k for k, v in POSITION_CODE.items()}

# Coarse group used for attributes, overall ratings and substitutions.
POSITION_GROUP = {
    "GK": "GK", "RCB": "CB", "CB": "CB", "LCB": "CB", "RB": "FB", "LB": "FB", "RWB": "FB", "LWB": "FB",
    "RDM": "DM", "CDM": "DM", "LDM": "DM", "RCM": "CM", "CM": "CM", "LCM": "CM", "RM": "W", "LM": "W",
    "RAM": "AM", "CAM": "AM", "LAM": "AM", "RW": "W", "LW": "W", "RCF": "ST", "ST": "ST", "LCF": "ST",
    "SS": "ST",
}

# Base position of each slot when the team is in a neutral shape, in the team's
# attacking frame (pitch 120 x 80, attacking towards x = 120, y = 0 = left touchline).
POSITION_XY = {
    "GK": (6, 40),
    "RB": (34, 70), "RCB": (24, 54), "CB": (22, 40), "LCB": (24, 26), "LB": (34, 10),
    "RWB": (52, 73), "LWB": (52, 7),
    "RDM": (42, 50), "CDM": (40, 40), "LDM": (42, 30),
    "RM": (62, 70), "RCM": (54, 52), "CM": (54, 40), "LCM": (54, 28), "LM": (62, 10),
    "RAM": (72, 58), "CAM": (72, 40), "LAM": (72, 22),
    "RW": (82, 70), "LW": (82, 10),
    "RCF": (90, 50), "ST": (92, 40), "LCF": (90, 30), "SS": (80, 40),
}

# Filled in from StatsBomb data (see tools/calibrate_from_statsbomb.py).
FORMATIONS: dict[str, list[str]] = {}
FORMATION_WEIGHTS: dict[str, float] = {}

from .calibration_data import FORMATIONS as _F, FORMATION_WEIGHTS as _W  # noqa: E402

FORMATIONS.update(_F)
FORMATION_WEIGHTS.update(_W)

# Back-five shapes, rare as starting formations in 2015/16 but used by managers
# protecting a lead in-game (never chosen as a club's starting formation).
FORMATIONS.setdefault("532", ["GK", "RCB", "CB", "LCB", "RWB", "LWB", "RCM", "CDM", "LCM", "RCF", "LCF"])
FORMATIONS.setdefault("541", ["GK", "RCB", "CB", "LCB", "RWB", "LWB", "RM", "RCM", "LCM", "LM", "ST"])
