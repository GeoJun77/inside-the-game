"""Tactical tools: shape, territory, pressing, attacking patterns and shot context.

All locations of matchsim events are in the ACTING team's attacking frame
(StatsBomb pitch 120 x 80): x = 0 is the team's own goal line, x = 120 the opponent's,
and for that team y < 26.7 is the left channel, y > 53.3 the right channel.
So "x" directly measures how high up the pitch an action happened.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean

from agents.match_tools import MatchContext, _normalise, minute_label

FINAL_THIRD_X = 80          # x >= 80: attacking third
OWN_60_PCT_X = 72           # x < 72: a team's own 60% of the pitch (used for PPDA)
DEFENSIVE_DUEL_X = 48       # x >= 48: defensive action in the opponent's 60% (PPDA)
BOX_X, BOX_Y = 102, (18, 62)
MIN_PPDA_ACTIONS = 6        # below this, PPDA is too noisy to report


def _channel(y: float) -> str:
    return "left" if y < 26.7 else ("right" if y > 53.3 else "centre")


def _level(value: float, low: float, high: float, words=("low", "medium", "high")) -> str:
    return words[0] if value < low else (words[2] if value >= high else words[1])


def _pct(part: float, total: float):
    return round(100 * part / total) if total else None


class TacticalTools:
    def __init__(self, ctx: MatchContext):
        self.ctx = ctx

    # ---------- helpers ----------
    def _team(self, team: str):
        """Resolve 'home', 'away', a team name or a team code to (team dict, opponent dict)."""
        q = _normalise(team)
        home, away = self.ctx.home, self.ctx.away
        if q in ("home", _normalise(home["code"])) or q in _normalise(home["name"]):
            return home, away
        if q in ("away", _normalise(away["code"])) or q in _normalise(away["name"]):
            return away, home
        raise ValueError(f"Unknown team '{team}'. Use '{home['name']}' or '{away['name']}'.")

    def _window(self, from_minute: int, to_minute: int):
        return self.ctx.window(from_minute, to_minute)

    def _start(self):
        return self.ctx.all_events[0]["details"]

    # ---------- tools ----------
    def get_team_setup(self, team: str) -> dict:
        """Identity, formation, instructions and every in-game change of one team."""
        t, _ = self._team(team)
        side = "home" if t is self.ctx.home else "away"
        start = self._start()[side]
        instructions = dict(t["instructions"])
        formation, mentality = start["formation"], "balanced"
        timeline = []

        # current eleven: start from the starting XI, apply substitutions and red cards
        on_pitch = {p["id"]: {"player": p["name"], "slot": p["slot"], "role": p["role"]}
                    for p in start["starting_xi"]}
        bench = {p["id"]: p for p in start["bench"]}

        for e in self.ctx.seen:
            if e["team_id"] != t["id"]:
                continue
            d = e["details"]
            if e["type"] == "tactical_change":
                instructions.update(d["instructions_after"])
                formation, mentality = d["to_formation"], d["to_mentality"]
                timeline.append({"minute": minute_label(e), "type": "tactical change",
                                 "reason": d["reason"].replace("_", " "),
                                 "description": d["description"],
                                 "formation": f"{d['from_formation']} -> {d['to_formation']}",
                                 "mentality": f"{d['from_mentality']} -> {d['to_mentality']}",
                                 "instructions_changed": d["instructions_after"]})
            elif e["type"] == "substitution":
                on_pitch.pop(d["player_off_id"], None)
                incoming = bench.get(d["player_on_id"], {})
                on_pitch[d["player_on_id"]] = {"player": d["player_on"], "slot": d["slot"],
                                               "role": incoming.get("role")}
                timeline.append({"minute": minute_label(e), "type": "substitution",
                                 "description": f"{d['player_on']} on for {d['player_off']} "
                                                f"({d['slot']})",
                                 "reason": d["reason"].replace("_", " ")})
            elif e["type"] == "card" and e["outcome"] in ("red", "second_yellow"):
                on_pitch.pop(e["player_id"], None)
                timeline.append({"minute": minute_label(e), "type": "red card",
                                 "description": f"{e['player']} sent off"})

        return {
            "team": t["name"],
            "manager": t["manager"],
            "identity": t["identity"],
            "starting_formation": start["formation"],
            "current_formation": formation,
            "current_mentality": mentality,
            "players_on_pitch": len(on_pitch),
            "current_lineup": sorted(on_pitch.values(), key=lambda p: p["slot"]),
            "instructions": {
                "build_up": instructions["build_up"],
                "chance_creation": instructions["chance_creation"],
                "defensive_style": instructions["defensive_style"].replace("_", " "),
                "defensive_line": _level(instructions["defensive_line"], 40, 60,
                                         ("deep", "medium", "high")),
                "attacking_width": _level(instructions["attacking_width"], 40, 60,
                                          ("narrow", "balanced", "wide")),
                "tempo": _level(instructions["tempo"], 40, 60, ("slow", "balanced", "fast")),
                "players_in_box": instructions["players_in_box"],
            },
            "alternative_formations": t["alt_formations"],
            "in_game_changes": timeline,
        }

    def get_territory_and_pressing(self, from_minute: int, to_minute: int) -> dict:
        """Who controls territory and how each team presses, between two minutes."""
        window = self._window(from_minute, to_minute)
        out = {}
        teams = (self.ctx.home, self.ctx.away)
        final_third = {t["id"]: sum(e["type"] == "pass" and e["team_id"] == t["id"]
                                    and e["location"][0] >= FINAL_THIRD_X for e in window)
                       for t in teams}
        for t, opp in (teams, teams[::-1]):
            mine = [e for e in window if e["team_id"] == t["id"]]
            pressures = [e for e in mine if e["type"] == "pressure"]
            def_actions = [e for e in mine if e["location"] and (
                e["type"] in ("interception", "foul", "ball_recovery", "clearance", "block")
                or (e["type"] == "duel" and e["details"].get("duel_type") == "Tackle"))]
            # PPDA: opponent passes in their own 60% / our defensive actions in that zone.
            opp_passes = sum(e["type"] == "pass" and e["team_id"] == opp["id"]
                             and e["location"][0] < OWN_60_PCT_X for e in window)
            high_actions = sum(e["type"] in ("interception", "foul")
                               or (e["type"] == "duel" and e["details"].get("duel_type") == "Tackle")
                               for e in def_actions if e["location"][0] >= DEFENSIVE_DUEL_X)
            high_turnovers = sum(e["type"] in ("ball_recovery", "interception")
                                 and e["location"][0] >= FINAL_THIRD_X - 10 for e in def_actions)
            avg_press = mean(e["location"][0] for e in pressures) if pressures else None
            shots = [e for e in mine if e["type"] == "shot"]
            out[t["name"]] = {
                # outcome first: a change "works" if it creates or prevents chances
                "goals": sum(e["type"] == "goal" for e in mine),
                "shots": len(shots),
                "xg": round(sum(s["details"]["xg"] for s in shots), 2),
                "field_tilt_pct": _pct(final_third[t["id"]], sum(final_third.values())),
                "passes_in_final_third": final_third[t["id"]],
                "pressures": len(pressures),
                "pressures_in_attacking_third": sum(e["location"][0] >= FINAL_THIRD_X
                                                    for e in pressures),
                "average_pressure_location_m": round(avg_press, 1) if avg_press else None,
                # PPDA on a handful of actions is noise: only give it with enough data
                "ppda": round(opp_passes / high_actions, 1) if high_actions >= MIN_PPDA_ACTIONS else None,
                "defensive_actions_used_for_ppda": high_actions,
                "high_turnovers": high_turnovers,
            }
        coverage = self.ctx.coverage(from_minute, to_minute)
        minutes = coverage["minutes_covered"]
        result = {**coverage, "teams": out,
                  "how_to_read": {
                      "field_tilt_pct": "share of the passes played in the attacking third: "
                                        "who is pinning the other team back",
                      "ppda": "opponent passes allowed per defensive action in the opponent's "
                              "60% of the pitch: LOWER means more intense pressing (below 9 is "
                              "aggressive, above 15 is passive). Null when there are too few "
                              "defensive actions to be meaningful",
                      "average_pressure_location_m": "where pressures happened, from the team's "
                                                     "own goal line (pitch length 120). It follows "
                                                     "where the ball was: a team that dominates "
                                                     "territory presses higher. Use PPDA to judge "
                                                     "pressing intent, not this",
                      "high_turnovers": "ball won back near the opponent's goal (x >= 70)"}}
        if minutes < 20:
            result["sample_warning"] = (f"Only {minutes} minutes of data: treat pressing and "
                                        "territory numbers as indicative, not conclusive.")
        return result

    def get_dominance_timeline(self) -> dict:
        """15-minute windows: xG, shots, field tilt and passes, to see when the match turned."""
        windows, last = [], self.ctx.minute
        bounds = [(0, 15, "1-15"), (16, 30, "16-30"), (31, 45, "31-45+"),
                  (46, 60, "46-60"), (61, 75, "61-75"), (76, 200, "76-90+")]
        for start, end, label in bounds:
            if start > last:
                break
            ev = self._window(start, end)
            finished = end <= last or any(e["type"] == "match_end" for e in self.ctx.seen)
            row = {"minutes": label if finished else f"{start}-{last} (in progress)"}
            for t in (self.ctx.home, self.ctx.away):
                mine = [e for e in ev if e["team_id"] == t["id"]]
                shots = [e for e in mine if e["type"] == "shot"]
                row[t["name"]] = {
                    "goals": sum(e["type"] == "goal" for e in mine),
                    "xg": round(sum(s["details"]["xg"] for s in shots), 2),
                    "shots": len(shots),
                    "passes": sum(e["type"] == "pass" for e in mine),
                    "final_third_passes": sum(e["type"] == "pass" and e["location"][0] >= FINAL_THIRD_X
                                              for e in mine),
                }
            h, a = row[self.ctx.home["name"]], row[self.ctx.away["name"]]
            score = (h["xg"] - a["xg"]) * 4 + (h["final_third_passes"] - a["final_third_passes"]) / 10
            row["on_top"] = (self.ctx.home["name"] if score > 0.6 else
                             self.ctx.away["name"] if score < -0.6 else "even")
            windows.append(row)
        return {"windows": windows}

    def get_attacking_patterns(self, team: str, from_minute: int, to_minute: int) -> dict:
        """How a team attacks: channels, crosses, through balls, counters, chance types, creators."""
        t, _ = self._team(team)
        mine = [e for e in self._window(from_minute, to_minute) if e["team_id"] == t["id"]]
        passes = [e for e in mine if e["type"] == "pass"]
        done = [p for p in passes if p["outcome"] == "complete"]
        entries = [e for e in mine if e["type"] in ("pass", "carry") and e["end_location"]
                   and e["outcome"] == "complete" and e["location"][0] < FINAL_THIRD_X
                   <= e["end_location"][0]]
        channels = defaultdict(int)
        for e in entries:
            channels[_channel(e["end_location"][1])] += 1
        shots = [e for e in mine if e["type"] == "shot"]
        by_assist = defaultdict(lambda: {"shots": 0, "xg": 0.0, "goals": 0})
        for s in shots:
            b = by_assist[s["details"]["assist_type"]]
            b["shots"] += 1
            b["xg"] = round(b["xg"] + s["details"]["xg"], 2)
            b["goals"] += s["outcome"] == "Goal"
        in_box = [s for s in shots if s["location"][0] >= BOX_X and BOX_Y[0] <= s["location"][1] <= BOX_Y[1]]

        creators = defaultdict(lambda: {"key_passes": 0, "expected_assists": 0.0})
        by_id = {e["event_id"]: e for e in self.ctx.seen}
        for s in shots:
            kp = s["details"].get("key_pass_id")
            if kp in by_id:
                c = creators[by_id[kp]["player"]]
                c["key_passes"] += 1
                c["expected_assists"] = round(c["expected_assists"] + s["details"]["xg"], 2)
        progressors = defaultdict(int)
        for e in mine:
            if e["type"] in ("pass", "carry") and e["outcome"] == "complete" and e["details"].get("progressive"):
                progressors[e["player"]] += 1

        return {
            "team": t["name"], **self.ctx.coverage(from_minute, to_minute),
            "final_third_entries": len(entries),
            "entries_by_channel_pct": {c: _pct(channels[c], len(entries))
                                       for c in ("left", "centre", "right")},
            "passes": len(passes),
            "pass_accuracy_pct": _pct(len(done), len(passes)),
            "long_ball_pct": _pct(sum(p["details"].get("pass_type") == "long" for p in passes), len(passes)),
            "crosses": sum(bool(p["details"].get("cross")) for p in passes),
            "through_balls": sum(bool(p["details"].get("through_ball")) for p in passes),
            "cut_backs": sum(bool(p["details"].get("cut_back")) for p in passes),
            "passes_into_box": sum(bool(p["details"].get("into_box")) and p["outcome"] == "complete"
                                   for p in passes),
            "dribbles_won": sum(e["type"] == "dribble" and e["outcome"] == "complete" for e in mine),
            "shots": len(shots),
            "shots_inside_box_pct": _pct(len(in_box), len(shots)),
            "counter_attack_shots": sum(bool(s["details"]["counter_attack"]) for s in shots),
            "average_shot_distance_m": round(mean(s["details"]["distance"] for s in shots), 1) if shots else None,
            "chances_by_assist_type": dict(by_assist),
            "top_creators": sorted(({"player": k, **v} for k, v in creators.items()),
                                   key=lambda c: -c["expected_assists"])[:3],
            "top_ball_progressors": [{"player": k, "progressive_actions": v} for k, v in
                                     sorted(progressors.items(), key=lambda kv: -kv[1])[:3]],
        }

    def get_shot_context(self, shot_event_id: int) -> dict:
        """Read the freeze frame of one shot: defensive shape around the shooter. 0 = latest shot."""
        shots = [e for e in self.ctx.seen if e["type"] == "shot"]
        if not shots:
            return {"error": "No shot has been taken yet."}
        s = shots[-1] if shot_event_id == 0 else next((x for x in shots if x["event_id"] == shot_event_id), None)
        if s is None:
            return {"error": f"No shot with event id {shot_event_id}.",
                    "recent_shot_ids": [x["event_id"] for x in shots[-5:]]}
        d, (sx, sy) = s["details"], s["location"]
        frame = d["freeze_frame"]
        opponents = [p for p in frame if not p["teammate"] and p["position"]["name"] != "Goalkeeper"]
        mates = [p for p in frame if p["teammate"]]
        gk = next((p for p in frame if not p["teammate"] and p["position"]["name"] == "Goalkeeper"), None)
        in_box = lambda p: p["location"][0] >= BOX_X and BOX_Y[0] <= p["location"][1] <= BOX_Y[1]

        key_pass = None
        kp = next((e for e in self.ctx.seen if e["event_id"] == d.get("key_pass_id")), None)
        if kp:
            k = kp["details"]
            kind = next((name for name, flag in (("cross", k.get("cross")), ("cut-back", k.get("cut_back")),
                                                 ("through ball", k.get("through_ball"))) if flag),
                        k.get("pass_type", "pass").replace("_", " "))
            key_pass = {"by": kp["player"], "player_position": kp["position"], "kind": kind,
                        "height": k.get("height"), "length_m": k.get("length"),
                        "played_from_channel": _channel(kp["location"][1]),
                        "played_from_distance_to_goal_line_m": round(120 - kp["location"][0], 1)}
        return {
            "event_id": s["event_id"], "minute": minute_label(s), "team": s["team"],
            "shooter": s["player"], "outcome": s["outcome"], "xg": d["xg"],
            "shot_from": {"distance_m": d["distance"], "channel": _channel(sy),
                          "inside_box": sx >= BOX_X and BOX_Y[0] <= sy <= BOX_Y[1]},
            "body_part": d["body_part"], "first_time": d["first_time"],
            "under_pressure": s["under_pressure"],
            "assist_type": d["assist_type"], "assisted_by": d["assist_player"],
            "key_pass": key_pass,
            "counter_attack": d["counter_attack"],
            "defenders_in_shooting_cone": d["n_defenders_in_cone"],
            "nearest_defender_m": d["nearest_defender_dist"],
            "defenders_goal_side_of_ball": sum(p["location"][0] > sx for p in opponents),
            "defenders_in_box": sum(in_box(p) for p in opponents),
            "attacking_teammates_in_box": sum(in_box(p) for p in mates),
            "goalkeeper": d["goalkeeper"],
            "goalkeeper_off_line_m": d["gk_distance_to_goal"],
            "goalkeeper_in_frame": gk is not None,
        }


TOOL_SCHEMAS = [
    {
        "name": "get_team_setup",
        "description": "Tactical identity of one team: manager, style, starting and current formation, "
                       "mentality, team instructions (build-up, chance creation, defensive style, "
                       "defensive line, width, tempo), current lineup with roles, and every in-game "
                       "change (tactical changes with the manager's reason, substitutions, red cards).",
        "parameters": {"type": "object",
                       "properties": {"team": {"type": "string",
                                               "description": "Team name, or 'home' / 'away'."}},
                       "required": ["team"], "additionalProperties": False},
    },
    {
        "name": "get_territory_and_pressing",
        "description": "For both teams between two minutes: field tilt (who plays in the attacking "
                       "third), pressing volume and height, PPDA (pressing intensity), high turnovers "
                       "and defensive line height. Call it on two windows to measure the effect of a change.",
        "parameters": {"type": "object",
                       "properties": {"from_minute": {"type": "integer"}, "to_minute": {"type": "integer"}},
                       "required": ["from_minute", "to_minute"], "additionalProperties": False},
    },
    {
        "name": "get_dominance_timeline",
        "description": "The match cut into 15-minute windows with goals, xG, shots, passes and "
                       "attacking-third passes per team, and which team was on top. Use it to find "
                       "when the match turned.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "get_attacking_patterns",
        "description": "How one team attacks between two minutes: final-third entries by channel "
                       "(left / centre / right), passing accuracy, long balls, crosses, through balls, "
                       "cut-backs, dribbles, counter-attack shots, shot distance, chance quality by "
                       "assist type, top creators and ball progressors.",
        "parameters": {"type": "object",
                       "properties": {"team": {"type": "string", "description": "Team name, or 'home' / 'away'."},
                                      "from_minute": {"type": "integer"}, "to_minute": {"type": "integer"}},
                       "required": ["team", "from_minute", "to_minute"], "additionalProperties": False},
    },
    {
        "name": "get_shot_context",
        "description": "Freeze-frame reading of one shot: where it was taken, how it was created, "
                       "defenders in the shooting cone, defenders goal-side and in the box, attackers "
                       "in the box, goalkeeper position. Use 0 for the most recent shot.",
        "parameters": {"type": "object",
                       "properties": {"shot_event_id": {"type": "integer",
                                                        "description": "Event id of the shot, or 0 for the latest."}},
                       "required": ["shot_event_id"], "additionalProperties": False},
    },
]
