"""In-game manager AI: tactical changes driven by score, time, red cards and dominance.

Rates are calibrated on Premier League 2015/16 (StatsBomb "Tactical Shift" events):
about 0.8 tactical change per team per match, mostly after half-time, more often
when trailing, and about a third of them involving a new formation.

Every decision comes with a machine-readable reason and an English sentence, so the
agents can explain *why* the manager reacted, not only *what* changed.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .formations import FORMATIONS

MAX_CHANGES = 3
CHECKPOINTS = (45, 52, 58, 64, 70, 76, 82, 87)


@dataclass
class TacticalDecision:
    reason: str
    description: str
    mentality: str
    instruction_changes: dict
    new_formation: str | None = None
    sub_profile: str | None = None      # "attacking" | "defensive" | None: preferred substitution


def _clip(v, lo=10, hi=95):
    return int(max(lo, min(hi, v)))


class Coach:
    def __init__(self, rng: random.Random):
        self.rng = rng

    # ------------------------------------------------------------------ hazards
    def hazard(self, minute: int, diff: int, trigger: str | None) -> float:
        """Probability of reacting at this checkpoint (or right after a trigger)."""
        if trigger == "red_card_own":
            return 0.95
        if trigger == "red_card_opponent":
            return 0.55
        if trigger == "conceded":
            return 0.12 if minute >= 55 else 0.04
        if minute == 45:
            return {True: 0.30, False: 0.17}[diff < 0] if diff <= 0 else 0.10
        if diff < 0:
            return 0.07 + 0.03 * (minute >= 70)
        if diff == 0:
            return 0.04 + 0.015 * (minute >= 75)
        return 0.06 if minute >= 72 else 0.02

    # ----------------------------------------------------------------- decision
    def decide(self, *, minute: int, diff: int, trigger: str | None, team, current_formation: str,
               instructions: dict, mentality: str, xg_for_recent: float, xg_against_recent: float,
               changes_so_far: int, players_on_pitch: int, team_is_favourite: bool = False) -> TacticalDecision | None:
        if changes_so_far >= MAX_CHANGES and trigger not in ("red_card_own",):
            return None
        if self.rng.random() > self.hazard(minute, diff, trigger):
            return None
        rng = self.rng
        alt_att, alt_def = team.alt_formations
        ins = instructions

        if trigger == "red_card_own":
            new_f = "442" if current_formation not in ("442", "4411", "451") else None
            return TacticalDecision(
                "red_card_reshuffle", f"Down to {players_on_pitch} men, {team.manager} reorganises into a compact shape.",
                "defensive", {"defensive_line": _clip(ins["defensive_line"] - 12), "defensive_style": "drop_back",
                              "players_in_box": max(2, ins["players_in_box"] - 1)}, new_f, "defensive")

        if trigger == "red_card_opponent":
            return TacticalDecision(
                "exploit_extra_man", f"With an extra man, {team.manager} pushes the team higher to make it count.",
                "attacking", {"defensive_line": _clip(ins["defensive_line"] + 10), "tempo": _clip(ins["tempo"] + 8),
                              "players_in_box": min(8, ins["players_in_box"] + 1)}, None, "attacking")

        dominated = xg_against_recent - xg_for_recent >= 0.45
        dominating_no_goal = xg_for_recent - xg_against_recent >= 0.45 and diff <= 0

        if diff < 0:
            late = minute >= 75
            new_f = alt_att if (rng.random() < (0.45 if late else 0.3) and alt_att in FORMATIONS
                                and alt_att != current_formation) else None
            changes = {"defensive_line": _clip(ins["defensive_line"] + (14 if late else 8)),
                       "tempo": _clip(ins["tempo"] + 10), "players_in_box": min(8, ins["players_in_box"] + 1 + late)}
            if late and diff <= -1 and rng.random() < 0.5:
                changes["build_up"] = "long_ball"
                changes["chance_creation"] = "wings"
            desc = (f"Chasing the game, {team.manager} throws more players forward"
                    + (f" and switches to {_fmt(new_f)}." if new_f else "."))
            return TacticalDecision("chasing_game", desc, "all_out_attack" if late else "attacking", changes, new_f,
                                    "attacking")

        if diff > 0 and minute >= 70:
            new_f = alt_def if (rng.random() < 0.35 and alt_def in FORMATIONS and alt_def != current_formation) else None
            changes = {"defensive_line": _clip(ins["defensive_line"] - 15), "defensive_style": "drop_back",
                       "tempo": _clip(ins["tempo"] - 12), "players_in_box": max(2, ins["players_in_box"] - 1),
                       "build_up": "slow"}
            desc = (f"Protecting the lead, {team.manager} drops the block deeper and slows the game down"
                    + (f", moving to {_fmt(new_f)}." if new_f else "."))
            return TacticalDecision("protecting_lead", desc, "defensive", changes, new_f, "defensive")

        if dominated:
            new_f = alt_def if (rng.random() < 0.3 and alt_def in FORMATIONS and alt_def != current_formation) else None
            changes = {"defensive_style": "drop_back" if ins["defensive_style"] != "drop_back" else "balanced",
                       "defensive_width": _clip(ins["defensive_width"] - 10), "defensive_line": _clip(ins["defensive_line"] - 6)}
            desc = (f"Under pressure, {team.manager} tightens the team: narrower, deeper"
                    + (f", in {_fmt(new_f)}." if new_f else "."))
            return TacticalDecision("tighten_up", desc, "defensive", changes, new_f, None)

        if dominating_no_goal or (diff == 0 and minute >= 70 and team_is_favourite):
            options = ["wings", "direct_passing", "forward_runs"]
            options = [o for o in options if o != ins["chance_creation"]] or options
            cc = rng.choice(options)
            new_f = alt_att if (rng.random() < 0.25 and alt_att in FORMATIONS and alt_att != current_formation) else None
            changes = {"chance_creation": cc, "players_in_box": min(8, ins["players_in_box"] + 1),
                       "tempo": _clip(ins["tempo"] + 6)}
            label = {"wings": "attack down the flanks", "direct_passing": "play more direct passes between the lines",
                     "forward_runs": "make more runs in behind"}[cc]
            desc = f"Looking for a winner, {team.manager} asks the team to {label}" + (
                f" and goes {_fmt(new_f)}." if new_f else ".")
            return TacticalDecision("going_for_win", desc, "attacking", changes, new_f, "attacking")

        if minute == 45:
            new_style = rng.choice([s for s in ("pressure_heavy_touch", "counter_press", "balanced", "drop_back")
                                    if s != ins["defensive_style"]])
            changes = {"defensive_style": new_style}
            desc = {
                "pressure_heavy_touch": f"At half-time {team.manager} tells the team to jump on every heavy touch.",
                "counter_press": f"At half-time {team.manager} asks for an immediate counter-press after losing the ball.",
                "balanced": f"At half-time {team.manager} calms things down: a more balanced press.",
                "drop_back": f"At half-time {team.manager} drops the team off to protect the space behind.",
            }[new_style]
            return TacticalDecision("half_time_adjustment", desc, "balanced", changes, None, None)
        return None


def _fmt(code: str | None) -> str:
    if not code:
        return ""
    return "-".join(code)
