"""Shot features, shared by the training notebook and the synthetic match engine.

Works on StatsBomb-style shots: a location [x, y] on a 120 x 80 pitch (attacking
towards x = 120) and a freeze frame, i.e. a list of players with "location",
"teammate" and "position": {"name": ...}. Using the exact same functions for real
and synthetic shots guarantees the xG model sees identical inputs in both cases.
"""
from __future__ import annotations

import math

GOAL_X, GOAL_Y = 120, 40
POST_LEFT, POST_RIGHT = (120, 36), (120, 44)
HALF_GOAL = 4


def shot_distance(x: float, y: float) -> float:
    return math.dist((x, y), (GOAL_X, GOAL_Y))


def shot_angle(x: float, y: float) -> float:
    """Opening angle of the goal seen from the shooter, in degrees."""
    dx = GOAL_X - x
    dy = abs(y - GOAL_Y)
    angle = math.atan2(2 * HALF_GOAL * dx, dx**2 + dy**2 - HALF_GOAL**2)
    if angle < 0:
        angle += math.pi
    return math.degrees(angle)


def opponents(frame: list) -> list:
    return [p for p in frame if not p["teammate"]]


def nearest_defender_dist(x: float, y: float, frame) -> float | None:
    if not isinstance(frame, list):
        return None
    distances = [
        math.dist((x, y), p["location"])
        for p in opponents(frame)
        if p["position"]["name"] != "Goalkeeper"
    ]
    return min(distances) if distances else None


def is_in_triangle(point, a, b, c) -> bool:
    def side(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = side(point, a, b), side(point, b, c), side(point, c, a)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def n_defenders_in_cone(x: float, y: float, frame) -> int | None:
    if not isinstance(frame, list):
        return None
    shooter = (x, y)
    return sum(
        is_in_triangle(p["location"], shooter, POST_LEFT, POST_RIGHT)
        for p in opponents(frame)
        if p["position"]["name"] != "Goalkeeper"
    )


def gk_distance_to_goal(frame) -> float | None:
    if not isinstance(frame, list):
        return None
    for p in opponents(frame):
        if p["position"]["name"] == "Goalkeeper":
            return math.dist(p["location"], (GOAL_X, GOAL_Y))
    return None


def assist_type(key_pass: dict | None) -> str:
    """Categorise how the chance was created, from the key pass (StatsBomb pass fields)."""
    if not key_pass:
        return "no_assist"
    if key_pass.get("pass_type") in ("Corner", "Free Kick", "Throw-in"):
        return "set_piece"
    if key_pass.get("pass_through_ball") is True:
        return "through_ball"
    if key_pass.get("pass_cut_back") is True:
        return "cut_back"
    if key_pass.get("pass_cross") is True:
        return "cross"
    if key_pass.get("pass_height") == "High Pass":
        return "high_pass"
    return "ground_pass"


def shot_features(shot: dict) -> dict:
    """All model inputs for one shot.

    `shot` needs: location, freeze_frame, body_part, shot_type, technique,
    under_pressure, first_time, one_on_one, aerial_won, assist_type.
    """
    x, y = shot["location"]
    frame = shot["freeze_frame"]
    return {
        "distance": shot_distance(x, y),
        "angle": shot_angle(x, y),
        "nearest_defender_dist": nearest_defender_dist(x, y, frame),
        "n_defenders_in_cone": n_defenders_in_cone(x, y, frame),
        "gk_distance_to_goal": gk_distance_to_goal(frame),
        "under_pressure": bool(shot.get("under_pressure", False)),
        "shot_first_time": bool(shot.get("first_time", False)),
        "shot_one_on_one": bool(shot.get("one_on_one", False)),
        "shot_aerial_won": bool(shot.get("aerial_won", False)),
        "shot_body_part": shot["body_part"],
        "shot_type": shot["shot_type"],
        "shot_technique": shot["technique"],
        "assist_type": shot["assist_type"],
    }
