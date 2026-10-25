"""Tools for the Producer: the match's key moments, ranked, with who was involved.

The Producer is the director of the show. To decide what a given viewer should see,
it needs a menu of moments (goals, big chances, saves, cards, tactical changes...)
with an importance score and the players involved, so it can pick what matters for
a Harbourne fan, for someone following one player, or for a neutral analyst.
"""
from __future__ import annotations

from agents.match_tools import MatchContext, _normalise, match_minute, minute_label
from matchsim.stats import team_stats

# The match stats panel, in the order a Premier League broadcast shows them.
# (label, key in matchsim team_stats, decimals)
PANEL_ROWS = [("Possession %", "possession_pct", 0), ("Expected goals (xG)", "xg", 2),
              ("Shots", "shots", 0), ("Shots on target", "shots_on_target", 0),
              ("Big chances", "big_chances", 0), ("Passes", "passes", 0),
              ("Pass accuracy %", "pass_accuracy_pct", 0), ("Crosses", "crosses", 0),
              ("Corners", "corners", 0), ("Offsides", "offsides", 0), ("Fouls", "fouls", 0),
              ("Yellow cards", "yellow_cards", 0), ("Red cards", "red_cards", 0),
              ("Tackles", "tackles", 0), ("Interceptions", "interceptions", 0),
              ("Saves", "saves", 0)]

OUTCOME_WORDS = {"Off T": "off target", "Wayward": "wide", "Blocked": "blocked", "Saved": "saved"}
BASE_IMPORTANCE = {"goal": 0.75, "red_card": 0.7, "woodwork": 0.55, "big_chance": 0.45,
                   "big_save": 0.45, "tactical_change": 0.35, "yellow_card": 0.2,
                   "substitution": 0.15, "injury": 0.15}


def _shot_kind(d: dict) -> str:
    """'header', 'right-footed shot'... so nobody has to guess how the shot was taken."""
    body = d["body_part"].lower()
    return "header" if body == "head" else f"{body.replace(' foot', '-footed')} shot"


class ProducerTools:
    def __init__(self, ctx: MatchContext):
        self.ctx = ctx

    def _moments(self) -> list[dict]:
        """Every notable moment seen so far, with an importance score from 0 to 1."""
        moments, score, goals_by = [], {"home": 0, "away": 0}, {}
        home_id = self.ctx.home["id"]
        for e in self.ctx.seen:
            t, d = e["type"], e.get("details") or {}
            m = None
            if t == "shot":
                xg = d["xg"]
                players = [p for p in (e["player"], d.get("assist_player"), d.get("goalkeeper")) if p]
                # explicit roles: an agent must never mistake the goalkeeper for the assister
                roles = {"shooter": e["player"], "assist": d.get("assist_player"),
                         "goalkeeper_facing": d.get("goalkeeper")}
                if e["outcome"] == "Goal":
                    side = "home" if e["team_id"] == home_id else "away"
                    before = score[side] - score["away" if side == "home" else "home"]
                    score[side] += 1
                    meaning = ("opener" if sum(score.values()) == 1 else "equaliser" if before == -1
                               else "go-ahead goal" if before == 0 else "extends the lead" if before > 0
                               else "pulls one back")
                    goals_by[e["player"]] = goals_by.get(e["player"], 0) + 1
                    n = goals_by[e["player"]]
                    if n >= 2:
                        meaning += ", hat-trick" if n == 3 else f", his {['', '', 'second', 'third', 'fourth', 'fifth'][min(n, 5)]} goal"
                    m = {"type": "goal", "players": players, "roles": roles,
                         "description": f"{e['player']} scores ({meaning}), xG {xg:.2f}"
                                        + (f", assisted by {d['assist_player']}" if d.get("assist_player") else "")
                                        + f"; score now {self.ctx.home['name']} {score['home']}-{score['away']} "
                                          f"{self.ctx.away['name']}",
                         "score_after": f"{score['home']}-{score['away']}",
                         "importance": BASE_IMPORTANCE["goal"] + 0.15 * (meaning in ("equaliser", "go-ahead goal"))
                                       + 0.1 * (match_minute(e) >= 80) + 0.1 * (n == 3)}
                elif e["outcome"] in ("Post", "Saved to Post"):
                    how = {"Post": "hits the post", "Saved to Post": f"is saved onto the post by {d['goalkeeper']}"}
                    m = {"type": "woodwork", "players": players, "roles": roles,
                         "description": f"{e['player']}'s {_shot_kind(d)} {how[e['outcome']]} (xG {xg:.2f})",
                         "importance": BASE_IMPORTANCE["woodwork"] + 0.3 * xg}
                elif e["outcome"] == "Saved" and xg >= 0.2:
                    m = {"type": "big_save", "players": players, "roles": roles,
                         "description": f"{d['goalkeeper']} saves {e['player']}'s {_shot_kind(d)} (xG {xg:.2f})",
                         "importance": BASE_IMPORTANCE["big_save"] + 0.4 * xg}
                elif xg >= 0.2 or d.get("big_chance"):
                    m = {"type": "big_chance", "players": players, "roles": roles,
                         "description": f"{e['player']} misses a big chance with a {_shot_kind(d)} "
                                        f"(xG {xg:.2f}, {OUTCOME_WORDS.get(e['outcome'], e['outcome'].lower())})",
                         "importance": BASE_IMPORTANCE["big_chance"] + 0.4 * xg}
            elif t == "card":
                red = e["outcome"] in ("red", "second_yellow")
                m = {"type": "red_card" if red else "yellow_card", "players": [e["player"]],
                     "description": f"{'Red' if red else 'Yellow'} card for {e['player']}",
                     "importance": BASE_IMPORTANCE["red_card" if red else "yellow_card"]}
            elif t == "tactical_change":
                m = {"type": "tactical_change", "players": [],
                     "description": d["description"], "importance": BASE_IMPORTANCE["tactical_change"]}
            elif t == "substitution":
                m = {"type": "substitution", "players": [d["player_on"], d["player_off"]],
                     "description": f"{d['player_on']} on for {d['player_off']} ({d['reason'].replace('_', ' ')})",
                     "importance": BASE_IMPORTANCE["substitution"]}
            elif t == "injury":
                m = {"type": "injury", "players": [e["player"]], "description": f"{e['player']} injured",
                     "importance": BASE_IMPORTANCE["injury"]}
            if m:
                m.update(moment_id=e["event_id"], minute=minute_label(e), team=e["team"],
                         importance=round(min(1.0, m["importance"]), 2))
                moments.append(m)
        return moments

    def match_stats_panel(self) -> dict:
        """The Premier League-style stats panel, computed from the events seen so far."""
        if not self.ctx.seen:
            return {}
        stats = team_stats(self.ctx.seen)
        home, away = self.ctx.home, self.ctx.away
        for team, opp in ((home, away), (away, home)):
            # a save is credited to the goalkeeper's team
            stats[team["id"]]["saves"] = sum(e["type"] == "goalkeeper" and e["outcome"] == "save"
                                             and e["team_id"] == team["id"] for e in self.ctx.seen)

        def fmt(v, dec):
            return round(v, dec) if dec else int(round(v))

        rows = [{"label": label, "home": fmt(stats[home["id"]][key], dec),
                 "away": fmt(stats[away["id"]][key], dec)} for label, key, dec in PANEL_ROWS]
        return {"minute": minute_label(self.ctx.seen[-1]), "home": home["name"], "away": away["name"],
                "score": self.ctx.score, "rows": rows}

    # ---------- tools ----------
    def get_match_stats(self) -> dict:
        """Full team statistics, as in a Premier League broadcast."""
        return self.match_stats_panel()

    def get_key_moments(self, team: str, player: str, min_importance: float) -> dict:
        """Key moments so far, optionally only those of one team or involving one player."""
        moments = self._moments()
        if team:
            q = _normalise(team)
            moments = [m for m in moments if q in _normalise(m["team"])]
        if player:
            q = _normalise(player)
            moments = [m for m in moments if any(q in _normalise(p) for p in m["players"])]
        moments = [m for m in moments if m["importance"] >= min_importance]
        # "players" is only used for filtering; "roles" says who did what
        moments = [{k: v for k, v in m.items() if k != "players"} for m in moments]
        return {"minute": self.ctx.minute, "count": len(moments), "moments": moments}

    def get_match_state(self) -> dict:
        return self.ctx.get_match_state()

    def get_player_stats(self, player_name: str) -> dict:
        return self.ctx.get_player_stats(player_name)


TOOL_SCHEMAS = [
    {
        "name": "get_key_moments",
        "description": "Key moments of the match so far (goals with their meaning, big chances, "
                       "saves, woodwork, cards, tactical changes, substitutions, injuries), each with "
                       "an id, minute, team, an importance score from 0 to 1 and, for shots, the "
                       "roles: shooter, assist (null if none) and goalkeeper_facing (the opponent "
                       "keeper, never an assister). "
                       "Filter by team and/or player (empty string = no filter).",
        "parameters": {"type": "object",
                       "properties": {
                           "team": {"type": "string", "description": "Team name, or empty for both teams."},
                           "player": {"type": "string", "description": "Player name, or empty for everyone."},
                           "min_importance": {"type": "number", "description": "0 for everything, 0.4 for the big moments."}},
                       "required": ["team", "player", "min_importance"], "additionalProperties": False},
    },
    {
        "name": "get_match_stats",
        "description": "The Premier League-style match stats of both teams so far: possession, xG, "
                       "shots, shots on target, big chances, passes, pass accuracy, crosses, corners, "
                       "offsides, fouls, yellow and red cards, tackles, interceptions, saves.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "get_match_state",
        "description": "Score, minute, goals with the score after each, red cards, possession, xG, "
                       "momentum and formations.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "get_player_stats",
        "description": "Live statistics and rating (0-10) of one player.",
        "parameters": {"type": "object",
                       "properties": {"player_name": {"type": "string"}},
                       "required": ["player_name"], "additionalProperties": False},
    },
]
