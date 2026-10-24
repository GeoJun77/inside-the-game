"""Turn raw matchsim events into a short, factual feed for the Narrator.

A match has ~1,600 events (passes, carries, pressures...). A commentator only talks
about what matters: chances, goals, cards, changes, long spells of possession and
dangerous attacks. This module filters and describes those moments in plain English
facts, with real player names, so the Narrator writes from facts instead of inventing.

It also adds the match context a real commentator knows by heart: a player's second
goal or hat-trick, an equaliser, a team taking the lead, a player already booked.
That context is computed here, in Python, from everything that happened before.
"""
from __future__ import annotations

from collections import Counter

from agents.match_tools import minute_label

SHOT_OUTCOME = {
    "Goal": "GOAL", "Saved": "saved by {gk}", "Saved to Post": "saved onto the post by {gk}",
    "Blocked": "blocked by a defender", "Off T": "off target", "Wayward": "well wide",
    "Post": "hits the post",
}
LONG_SPELL_PASSES = 10      # a possession with this many passes is worth a line
GOAL_COUNT = {2: "his second goal of the game", 3: "HAT-TRICK", 4: "his fourth goal of the game",
              5: "his fifth goal of the game"}


class MatchMemory:
    """What a commentator remembers: score, goals per player, bookings."""

    def __init__(self, teams: dict):
        self.teams = teams
        self.score = {"home": 0, "away": 0}
        self.goals = Counter()          # player name -> goals
        self.booked = set()             # player names with a yellow card

    def side(self, team_name: str) -> str:
        return "home" if team_name == self.teams["home"] else "away"

    def goal_context(self, team_name: str, scorer: str) -> list[str]:
        """Update the memory with a goal and describe what it means."""
        us, them = self.side(team_name), "away" if self.side(team_name) == "home" else "home"
        before = self.score[us] - self.score[them]
        self.score[us] += 1
        self.goals[scorer] += 1
        if self.score[us] + self.score[them] == 1:
            meaning = "opens the scoring"
        elif before == -1:
            meaning = "EQUALISER"
        elif before == 0:
            meaning = "puts them in front"
        elif before > 0:
            meaning = "extends the lead"
        else:
            meaning = "pulls one back"
        context = [meaning]
        if self.goals[scorer] in GOAL_COUNT:
            context.append(GOAL_COUNT[self.goals[scorer]])
        return context

    def update(self, e: dict) -> None:
        """Replay an event the Narrator has already commented (no text produced)."""
        if e["type"] == "shot" and e["outcome"] == "Goal":
            self.goal_context(e["team"], e["player"])
        elif e["type"] == "card" and e["outcome"] == "yellow":
            self.booked.add(e["player"])


def _shot_line(e: dict, memory: MatchMemory) -> str:
    d = e["details"]
    how = d["body_part"].lower().replace("right foot", "right-footed shot") \
                                .replace("left foot", "left-footed shot").replace("head", "header")
    if d["shot_type"] == "Penalty":
        how = "penalty"
    elif d["shot_type"] == "Free Kick":
        how = "direct free kick"
    origin = ""
    if d["assist_player"]:
        kind = d["assist_type"].replace("_", " ").replace("no assist", "pass")
        origin = f" from a {kind} by {d['assist_player']}"
    extra = []
    if d["counter_attack"]:
        extra.append("on the counter")
    if d["one_on_one"]:
        extra.append("one-on-one with the keeper")
    if d["big_chance"]:
        extra.append("big chance")
    outcome = SHOT_OUTCOME.get(e["outcome"], e["outcome"]).format(gk=d["goalkeeper"])
    line = (f"{minute_label(e)}' {e['player']} ({e['team']}): {how} from {d['distance']:.0f} m"
            f"{origin}{', ' + ', '.join(extra) if extra else ''} -> {outcome} (xG {d['xg']:.2f}).")
    if e["outcome"] == "Goal":
        context = memory.goal_context(e["team"], e["player"])
        t, s = memory.teams, memory.score
        line += (f" Context: {', '.join(context)}. "
                 f"Score now {t['home']} {s['home']}-{s['away']} {t['away']}.")
    return line


def describe(events: list[dict], teams: dict, history: list[dict] = ()) -> list[str]:
    """Factual lines for the notable moments in a batch of events.

    teams   = {"home": "<home team name>", "away": "<away team name>"}
    history = every event before this batch (gives the context: goals so far, bookings)
    """
    if not events:
        return []
    memory = MatchMemory(teams)
    for e in history:
        memory.update(e)

    lines = []
    spell = {"id": None, "team": None, "minute": None, "passes": 0, "into_box": False, "shot": False}

    def close_spell():
        """Summarise the possession that just ended, if it was notable and had no shot."""
        if spell["id"] is None or spell["shot"]:
            return
        if spell["passes"] >= LONG_SPELL_PASSES:
            lines.append(f"{spell['minute']}' {spell['team']} keep the ball for a spell of "
                         f"{spell['passes']} passes.")
        elif spell["into_box"]:
            lines.append(f"{spell['minute']}' {spell['team']} work the ball into the box, "
                         f"but no shot comes.")

    for e in events:
        t, d = e["type"], e.get("details") or {}
        if t in ("pass", "carry", "dribble", "shot") and e["possession_id"] != spell["id"]:
            close_spell()
            spell.update(id=e["possession_id"], team=e["team"], minute=minute_label(e),
                         passes=0, into_box=False, shot=False)
        if t == "match_start":
            lines.append(f"Kick-off: {teams['home']} ({d['home']['formation']}) vs "
                         f"{teams['away']} ({d['away']['formation']}) at {d['venue']}, "
                         f"referee {d['referee']}, {d['weather']}, attendance {d['attendance']}.")
        elif t == "period_start" and e["period"] == 2:
            lines.append(f"Second half under way. Score {e['score']['home']}-{e['score']['away']}.")
        elif t == "period_end":
            label = "Half-time" if d.get("period") == 1 else "Full-time"
            lines.append(f"{label}: {e['score']['home']}-{e['score']['away']}.")
        elif t == "shot":
            spell["shot"] = True
            lines.append(_shot_line(e, memory))
        elif t == "card":
            kind = {"yellow": "Yellow card", "second_yellow": "Second yellow, sent off",
                    "red": "Straight red card"}[e["outcome"]]
            lines.append(f"{minute_label(e)}' {kind}: {e['player']} ({e['team']}).")
            if e["outcome"] == "yellow":
                memory.booked.add(e["player"])
        elif t == "substitution":
            note = ", he was on a yellow card" if d["player_off"] in memory.booked else ""
            lines.append(f"{minute_label(e)}' Substitution {e['team']}: {d['player_on']} on for "
                         f"{d['player_off']} ({d['reason'].replace('_', ' ')}{note}).")
        elif t == "tactical_change":
            lines.append(f"{minute_label(e)}' Tactical change, {e['team']}: {d['description']}")
        elif t == "injury":
            lines.append(f"{minute_label(e)}' {e['player']} ({e['team']}) is down injured "
                         f"({d.get('severity', 'knock')}).")
        elif t == "foul":
            if d.get("in_box"):
                lines.append(f"{minute_label(e)}' Foul in the box by {e['player']} on {d['on_player']}.")
            elif e["player"] in memory.booked and not d.get("card"):
                lines.append(f"{minute_label(e)}' {e['player']} ({e['team']}), already booked, "
                             f"fouls {d['on_player']}.")
        elif t == "pass":
            spell["passes"] += 1
            spell["into_box"] |= bool(d.get("into_box")) and e["outcome"] == "complete"
        elif t == "dribble" and e["outcome"] == "complete" and e["location"][0] >= 80:
            lines.append(f"{minute_label(e)}' {e['player']} ({e['team']}) beats "
                         f"{d['beaten_player']} in the final third.")
    close_spell()

    last = events[-1]
    lines.append(f"[now {minute_label(last)}', score {last['score']['home']}-{last['score']['away']}]")
    return lines


def is_key_moment(e: dict) -> bool:
    """Events that deserve immediate commentary (instead of waiting for the next batch)."""
    # A scoring shot is followed by a "goal" event: we cut on the goal, so the new score is in.
    if e["type"] == "shot":
        return e["outcome"] != "Goal" and (e["details"]["big_chance"] or e["details"]["xg"] >= 0.15)
    return e["type"] in ("goal", "card", "tactical_change", "period_end", "match_end")
