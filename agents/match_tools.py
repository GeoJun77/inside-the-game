"""Read-only tools that let the agents query a live matchsim match.

A MatchContext holds the events seen so far (the "live" part of the match).
Every public method returns a small JSON-serialisable dict, so the agents
get facts computed in Python instead of guessing numbers.
"""
from __future__ import annotations

import unicodedata

from matchsim.ratings import player_match_stats
from matchsim.stats import team_stats


def _normalise(text: str) -> str:
    """Lower-case and strip accents, so 'theo' matches 'Théo'."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def match_minute(e: dict) -> int:
    """Minute used for every time window, so the two halves never overlap.

    The engine's clock restarts at 45:00 in the second half, while first-half
    added time runs 45:00, 46:00, 47:00... So we count all first-half added
    time as minute 45, and the second half from minute 46 onwards.
    """
    if e["period"] == 1:
        return min(e["minute"], 45)
    if e["period"] >= 2:
        return max(e["minute"], 46)
    return e["minute"]


def minute_label(e: dict) -> str:
    """Broadcast-style minute: '23', '45+2', '90+4'."""
    m = e["minute"]
    if e["period"] == 1 and m >= 45:
        return f"45+{m - 44}"
    if e["period"] >= 2 and m >= 90:
        return f"90+{m - 89}"
    return str(match_minute(e))


class MatchContext:
    def __init__(self, events: list[dict]):
        self.all_events = events
        start = events[0]["details"]
        self.home = start["home"]["team"]
        self.away = start["away"]["team"]
        self.seen: list[dict] = []

    # ---------- live feed ----------
    def advance_to(self, minute: int) -> None:
        """Mark every event up to `minute` as seen (used for demos and tests)."""
        self.seen = [e for e in self.all_events if match_minute(e) <= minute]

    def push(self, event: dict) -> None:
        """Add one event from the live stream."""
        self.seen.append(event)

    def window(self, from_minute: int, to_minute: int) -> list[dict]:
        """Events seen between two match minutes (inclusive)."""
        return [e for e in self.seen if from_minute <= match_minute(e) <= to_minute]

    def coverage(self, from_minute: int, to_minute: int) -> dict:
        """What a window really covers: it cannot go beyond the current minute.

        Returned with every window so that the agents compare periods of equal length.
        """
        end = min(to_minute, self.minute)
        info = {"from_minute": from_minute, "to_minute": end,
                "minutes_covered": max(0, end - from_minute + 1)}
        if end < to_minute:
            info["note"] = (f"Window truncated at the current minute ({end}). Compare it only "
                            f"with a window of the same length.")
        return info

    @property
    def minute(self) -> int:
        return match_minute(self.seen[-1]) if self.seen else 0

    @property
    def score(self) -> dict:
        return self.seen[-1]["score"] if self.seen else {"home": 0, "away": 0}

    def _team_name(self, team_id: str) -> str:
        return self.home["name"] if team_id == self.home["id"] else self.away["name"]

    # ---------- tools ----------
    def get_match_state(self) -> dict:
        """Score, minute and the latest 5-minute snapshot (possession, xG, momentum...)."""
        snapshot = next((e["details"] for e in reversed(self.seen) if e["type"] == "match_state"), None)
        goals, running = [], {"home": 0, "away": 0}
        for e in self.seen:
            if e["type"] == "goal":
                running["home" if e["team_id"] == self.home["id"] else "away"] += 1
                # the score after each goal is given, so no agent has to recount it
                goals.append({"minute": minute_label(e), "team": e["team"],
                              "scorer": e["details"]["scorer"], "assist": e["details"]["assist"],
                              "xg": e["details"]["xg"],
                              "score_after": f"{self.home['name']} {running['home']}-{running['away']} {self.away['name']}"})
        reds = [{"minute": minute_label(e), "team": e["team"], "player": e["player"]}
                for e in self.seen if e["type"] == "card" and e["outcome"] in ("red", "second_yellow")]
        state = {
            "minute": self.minute,
            "home_team": self.home["name"],
            "away_team": self.away["name"],
            "venue": self.all_events[0]["details"]["venue"],
            "score": self.score,
            "goals": goals,
            "red_cards": reds,
        }
        # xG is recomputed from every shot seen so far, so it is always up to date
        # (the 5-minute snapshot can miss a shot taken just after it).
        state["xg"] = self._xg_between(0, self.minute)
        state["xg_last_15_minutes"] = self._xg_between(max(0, self.minute - 15), self.minute)
        # Possession from the time each team had the ball: the same figure as the stats panel.
        if any(e["type"] == "match_start" for e in self.seen[:1]):
            ts = team_stats(self.seen)
            state["possession_pct"] = {"home": round(ts[self.home["id"]]["possession_pct"]),
                                       "away": round(ts[self.away["id"]]["possession_pct"])}
        if snapshot:
            state.update({
                "momentum": self._momentum(snapshot["momentum"]),
                "formations": snapshot["formations"],
                "mentality": snapshot["mentality"],
            })
        return state

    def get_shot_details(self, shot_event_id: int) -> dict:
        """xG of one shot and why. shot_event_id = 0 means the most recent shot."""
        shots = [e for e in self.seen if e["type"] == "shot"]
        if not shots:
            return {"error": "No shot has been taken yet."}
        shot = shots[-1] if shot_event_id == 0 else next(
            (s for s in shots if s["event_id"] == shot_event_id), None)
        if shot is None:
            return {"error": f"No shot with event id {shot_event_id}. Pick one from this list.",
                    "shots": self.list_shots("", "")["shots"]}
        d = shot["details"]
        return {
            "event_id": shot["event_id"],
            "minute": minute_label(shot),
            "team": shot["team"],
            "shooter": shot["player"],
            "assisted_by": d["assist_player"],
            "outcome": shot["outcome"],
            "xg": d["xg"],
            "assist_type": d["assist_type"],
            "body_part": d["body_part"],
            "shot_type": d["shot_type"],
            "distance_m": d["distance"],
            "angle_deg": d["angle_deg"],
            "defenders_in_shooting_cone": d["n_defenders_in_cone"],
            "nearest_defender_m": d["nearest_defender_dist"],
            "one_on_one": d["one_on_one"],
            "under_pressure": shot["under_pressure"],
            "goalkeeper": d["goalkeeper"],
            "why_this_xg": [{"factor": x["label"], "value": x["value"], "effect": x["effect"]}
                            for x in d["xg_explanation"]],
        }

    def list_shots(self, team: str, player: str) -> dict:
        """Every shot so far (id, minute, shooter, outcome, xG), to find a shot's event id."""
        out = []
        for e in self.seen:
            if e["type"] != "shot":
                continue
            if team and _normalise(team) not in _normalise(e["team"]):
                continue
            if player and _normalise(player) not in _normalise(e["player"]):
                continue
            out.append({"event_id": e["event_id"], "minute": minute_label(e), "team": e["team"],
                        "shooter": e["player"], "outcome": e["outcome"], "xg": e["details"]["xg"]})
        return {"count": len(out), "shots": out}

    def summarize_period(self, from_minute: int, to_minute: int) -> dict:
        """Per-team box score between two minutes (inclusive)."""
        window = self.window(from_minute, to_minute)
        teams = {}
        for team in (self.home, self.away):
            mine = [e for e in window if e["team_id"] == team["id"]]
            shots = [e for e in mine if e["type"] == "shot"]
            passes = [e for e in mine if e["type"] == "pass"]
            teams[team["name"]] = {
                "goals": sum(e["type"] == "goal" for e in mine),
                "shots": len(shots),
                "shots_on_target": sum(s["details"]["on_target"] for s in shots),
                "xg": round(sum(s["details"]["xg"] for s in shots), 2),
                "big_chances": sum(s["details"]["big_chance"] for s in shots),
                "passes": len(passes),
                "pass_accuracy_pct": round(100 * sum(p["outcome"] == "complete" for p in passes)
                                           / len(passes)) if passes else None,
                "fouls": sum(e["type"] == "foul" for e in mine),
                "corners": sum(e["type"] == "pass" and e["details"].get("pass_type") == "corner"
                               for e in mine),
            }
        total_passes = sum(t["passes"] for t in teams.values()) or 1
        for t in teams.values():
            t["possession_pct_estimate"] = round(100 * t["passes"] / total_passes)
        key_moments = [
            {"minute": minute_label(e), "type": e["type"], "team": e["team"],
             "description": self._describe(e)}
            for e in window if e["type"] in ("goal", "card", "substitution", "tactical_change", "injury")
        ]
        return {**self.coverage(from_minute, to_minute), "teams": teams,
                "key_moments": key_moments}

    def get_player_stats(self, player_name: str) -> dict:
        """Live stats and rating of one player, found by (part of) their name."""
        stats = player_match_stats(self.seen)
        query = _normalise(player_name)
        matches = [s for s in stats.values() if query in _normalise(s["player"])]
        if not matches:
            return {"error": f"No player on the pitch matches '{player_name}'.",
                    "players_on_record": sorted(s["player"] for s in stats.values())}
        if len(matches) > 1:
            exact = [s for s in matches if _normalise(s["player"]) == query]
            if len(exact) != 1:
                return {"error": "Several players match, be more specific.",
                        "candidates": [s["player"] for s in matches]}
            matches = exact
        s = dict(matches[0])
        s["team"] = self._team_name(s.pop("team_id"))
        s["live_rating"] = s.pop("rating")
        s.pop("player_id")
        return s

    # ---------- helpers ----------
    def _xg_between(self, from_minute: int, to_minute: int) -> dict:
        """Total xG of each side between two minutes (inclusive), from the shots seen."""
        xg = {"home": 0.0, "away": 0.0}
        for e in self.window(from_minute, to_minute):
            if e["type"] == "shot":
                xg["home" if e["team_id"] == self.home["id"] else "away"] += e["details"]["xg"]
        return {side: round(v, 2) for side, v in xg.items()}

    def _momentum(self, value: int) -> dict:
        """Turn the engine's signed momentum (-100 away ... +100 home) into words."""
        if abs(value) < 15:
            return {"favours": None, "strength": "balanced"}
        team = self.home["name"] if value > 0 else self.away["name"]
        strength = "slight" if abs(value) < 35 else ("clear" if abs(value) < 65 else "strong")
        return {"favours": team, "strength": strength}

    @staticmethod
    def _describe(e: dict) -> str:
        d = e["details"]
        if e["type"] == "goal":
            assist = f", assisted by {d['assist']}" if d["assist"] else ""
            return f"Goal by {d['scorer']}{assist} (xG {d['xg']:.2f})"
        if e["type"] == "card":
            return f"{e['outcome'].replace('_', ' ')} card for {e['player']}"
        if e["type"] == "substitution":
            return f"{d['player_on']} replaces {d['player_off']} ({d['reason'].replace('_', ' ')})"
        if e["type"] == "tactical_change":
            return d["description"]
        if e["type"] == "injury":
            return f"{e['player']} is injured"
        return e["type"]


# JSON schemas of the tools, in the format expected by Foundry function tools.
# strict=True requires every property to be listed in "required"
# and "additionalProperties": False.
TOOL_SCHEMAS = [
    {
        "name": "get_match_state",
        "description": "Current score, minute, goals, red cards, possession, xG, xG of the last "
                       "15 minutes, momentum, formations and mentality of both teams.",
        "parameters": {"type": "object", "properties": {}, "required": [],
                       "additionalProperties": False},
    },
    {
        "name": "get_shot_details",
        "description": "Expected goals (xG) of one shot and the factors that raised or lowered it "
                       "(distance, angle, defenders in the shooting cone, assist type...). "
                       "Use 0 for the most recent shot.",
        "parameters": {"type": "object",
                       "properties": {"shot_event_id": {"type": "integer",
                                                        "description": "Event id of the shot, or 0 for the latest shot."}},
                       "required": ["shot_event_id"], "additionalProperties": False},
    },
    {
        "name": "list_shots",
        "description": "Every shot so far with its event id, minute, shooter, outcome and xG. "
                       "Use it to find the event id of a shot (e.g. 'Ashworth's shot at 29'') before "
                       "calling get_shot_details. Filter by team and/or player, or empty strings.",
        "parameters": {"type": "object",
                       "properties": {"team": {"type": "string"}, "player": {"type": "string"}},
                       "required": ["team", "player"], "additionalProperties": False},
    },
    {
        "name": "summarize_period",
        "description": "Per-team statistics (goals, shots, xG, big chances, passes, pass accuracy, "
                       "fouls, corners, possession estimate) and key moments between two minutes.",
        "parameters": {"type": "object",
                       "properties": {"from_minute": {"type": "integer"},
                                      "to_minute": {"type": "integer"}},
                       "required": ["from_minute", "to_minute"], "additionalProperties": False},
    },
    {
        "name": "get_player_stats",
        "description": "Live statistics and rating (0-10) of one player: goals, assists, shots, xG, "
                       "xA, key passes, passing, dribbles, defensive actions, saves, cards.",
        "parameters": {"type": "object",
                       "properties": {"player_name": {"type": "string",
                                                      "description": "Full name or surname of the player."}},
                       "required": ["player_name"], "additionalProperties": False},
    },
]
