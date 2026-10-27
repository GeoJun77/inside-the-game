"""Event-level synthetic football match engine (StatsBomb-style coordinates and fields).

A match is played as a sequence of possessions. Inside a possession the ball carrier
picks an action (pass, carry, dribble, cross, through ball, shot...) whose odds
depend on pitch zone, player attributes, team instructions, pressure, fatigue,
score state and momentum. Shots are characterised (body part, technique, first time,
assist type...) from Premier League 2015/16 distributions, get a synthetic freeze
frame, and are scored by the trained xG model. An AI manager changes tactics and
makes substitutions during the game.

Coordinates: 120 x 80 pitch. `location` is expressed in the acting team's attacking
frame (x = 0 own goal line, x = 120 opponent goal line, y = 0 left touchline),
like StatsBomb. `location_abs` is a fixed broadcast frame where the home team
attacks left -> right in the first half.
"""
from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field

from xg import load_default_model, fallback_xg, shot_features
from xg.features import GOAL_X, GOAL_Y, shot_angle, shot_distance

from . import calibration_data as cal
from .coach import CHECKPOINTS, Coach
from .formations import FORMATIONS, POSITION_GROUP, POSITION_NAME, POSITION_XY
from .freeze import build_freeze_frame, dist_band
from .names import REFEREES
from .ratings import player_match_stats
from .teams import LEAGUE_NAME, Player, Team, engine_params, select_matchday_squad

L, W = 120.0, 80.0
PERIOD_SECONDS = 45 * 60
WEATHER = ["clear", "overcast", "light rain", "heavy rain", "windy", "cold and dry"]
RUN_RATE = {"GK": 55, "CB": 104, "FB": 116, "DM": 118, "CM": 124, "AM": 117, "W": 114, "ST": 108}
FORWARD_SLOTS = ("ST", "RCF", "LCF", "SS")
ATTACKING_GROUPS = ("ST", "W", "AM")
DEFENSIVE_GROUPS = ("CB", "FB", "DM")


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def mirror(x, y):
    return L - x, W - y


def logit(p):
    p = clamp(p, 1e-4, 1 - 1e-4)
    return math.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + math.exp(-z))


def quick_xg(x, y, header=False):
    """Cheap geometric xG used only to decide whether shooting is a good idea."""
    d, a = shot_distance(x, y), math.radians(shot_angle(x, y))
    z = -1.5 + 1.85 * a - 0.092 * d - (0.9 if header else 0)
    return clamp(sigmoid(z), 0.005, 0.9)


@dataclass
class TeamState:
    team: Team
    side: str
    lineup: dict = field(default_factory=dict)        # player id -> slot code
    on_pitch: list = field(default_factory=list)
    bench: list = field(default_factory=list)
    formation: str = ""
    instructions: dict = field(default_factory=dict)
    mentality: str = "balanced"
    subs_used: int = 0
    sub_windows_used: int = 0
    planned_windows: list = field(default_factory=list)  # [(minute, n_subs)]
    yellow: dict = field(default_factory=dict)
    sent_off: list = field(default_factory=list)
    momentum: float = 0.0
    score: int = 0
    tactical_changes: int = 0
    shot_log: list = field(default_factory=list)       # (match_seconds, xg)
    used_players: set = field(default_factory=set)
    came_on: set = field(default_factory=set)          # substitutes who came on: not taken off again

    @property
    def tactics(self) -> dict:
        return engine_params(self.instructions)

    @property
    def gk(self) -> Player | None:
        for p in self.on_pitch:
            if self.lineup.get(p.id) == "GK":
                return p
        return None

    def slot(self, p: Player) -> str:
        return self.lineup[p.id]

    def strength(self) -> float:
        if not self.on_pitch:
            return 60.0
        return sum(p.position_rating(self.lineup[p.id]) for p in self.on_pitch) / 11


@dataclass
class PlayerLoad:
    distance_m: float = 0.0
    top_speed_kmh: float = 0.0
    sprints: int = 0
    minutes: float = 0.0


class MatchSimulator:
    def __init__(self, home: Team, away: Team, seed: int | None = None, match_id: str | None = None,
                 kickoff_utc: str = "2026-10-24T14:00:00Z", matchday: int = 1,
                 home_fitness: dict | None = None, away_fitness: dict | None = None,
                 unavailable: set | None = None, xg_model="default"):
        self.rng = random.Random(seed)
        self.seed = seed
        self.match_id = match_id or f"M-{home.code}-{away.code}-{uuid.UUID(int=self.rng.getrandbits(128)).hex[:8]}"
        self.kickoff_utc = kickoff_utc
        self.matchday = matchday
        self.xg_model = load_default_model() if xg_model == "default" else xg_model
        self.coach = Coach(self.rng)
        self.ts = [self._init_team(home, "home", home_fitness, unavailable),
                   self._init_team(away, "away", away_fitness, unavailable)]
        self.events: list[dict] = []
        self.load: dict[str, PlayerLoad] = {p.id: PlayerLoad() for t in self.ts for p in t.team.players}
        self.period = 0
        self.t = 0.0
        self.period_len = PERIOD_SECONDS
        self.poss = 0
        self.ball = (60.0, 40.0)
        self.carrier: Player | None = None
        self.possession_id = 0
        self.poss_start = (60.0, 0.0)                   # (x where possession started, match_seconds)
        self.restart: tuple | None = None
        self.assist_ev: dict | None = None                # last completed pass to the current carrier
        self.chain = 0                                    # completed passes in the current possession
        self.pending_triggers: list = []                  # (team_idx, trigger)
        self.next_checkpoint = 0
        self.last_load_minute = 0
        self.next_state_minute = 5

    # ------------------------------------------------------------------ setup
    def _init_team(self, team: Team, side: str, fitness, unavailable) -> TeamState:
        ts = TeamState(team=team, side=side, formation=team.formation, instructions=dict(team.instructions))
        lineup, bench = select_matchday_squad(team, team.formation, unavailable=unavailable, fitness=fitness,
                                              rng=self.rng)
        ts.on_pitch = [p for p, _ in lineup]
        ts.lineup = {p.id: s for p, s in lineup}
        ts.bench = list(bench)
        ts.used_players = {p.id for p in ts.on_pitch}
        self._plan_subs(ts)
        return ts

    def _plan_subs(self, ts: TeamState):
        """Premier League rules: up to 5 substitutions in at most 3 windows (half-time excluded)."""
        rng = self.rng
        n = rng.choices([3, 4, 5], weights=[20, 35, 45])[0]
        q = cal.SUBSTITUTIONS["minute_by_order"]
        minutes = sorted(self._sample_q(q[k]) for k in ("1", "2", "3"))
        split = {3: [1, 1, 1], 4: [2, 1, 1], 5: [2, 2, 1]}[n]
        rng.shuffle(split)
        ts.planned_windows = [(max(46, m), k) for m, k in zip(minutes, split)]

    def _sample_q(self, q):
        """Sample a minute from 10/25/50/75/90 percentiles."""
        u = self.rng.random()
        ps = (0.1, 0.25, 0.5, 0.75, 0.9)
        if u <= ps[0]:
            return q[0] - self.rng.uniform(0, 6)
        if u >= ps[-1]:
            return min(92, q[-1] + self.rng.uniform(0, 4))
        for k in range(4):
            if ps[k] <= u <= ps[k + 1]:
                return q[k] + (u - ps[k]) / (ps[k + 1] - ps[k]) * (q[k + 1] - q[k])
        return q[2]

    # ---------------------------------------------------------------- helpers
    @property
    def minute(self) -> int:
        if self.period == 0:
            return 0
        return int((self.period - 1) * 45 + self.t // 60)

    @property
    def match_seconds(self) -> float:
        return round((self.period - 1) * PERIOD_SECONDS + self.t, 1) if self.period else 0.0

    def _edge(self, i: int) -> float:
        """Signed strength edge of team i (home advantage, momentum, game state, red cards)."""
        def s(k):
            ts = self.ts[k]
            v = ts.strength() + (2.0 if ts.side == "home" else 0) + 5 * ts.momentum
            v -= 6 * (11 - len(ts.on_pitch))
            diff = ts.score - self.ts[1 - k].score
            urgency = (0.5 + max(0, self.minute - 45) / 45) if self.period else 0
            if diff < 0:
                v += min(2, -diff) * 1.4 * urgency
            elif diff >= 2:
                v -= 1.5 * urgency
            v += {"all_out_attack": 1.5, "attacking": 0.8, "defensive": -0.5}.get(ts.mentality, 0)
            return v
        return clamp((s(i) - s(1 - i)) / 130, -0.15, 0.15)

    def _fatigue(self, p: Player) -> float:
        m = self.load[p.id].minutes
        return 1 - max(0, m - 55) * 0.0011 * (1.3 - p.a("stamina") / 100)

    def _abs(self, team_idx: int, x: float, y: float):
        home_attacks_right = self.period != 2
        attacks_right = (team_idx == 0) == home_attacks_right
        return (round(x, 1), round(y, 1)) if attacks_right else (round(L - x, 1), round(W - y, 1))

    def _pos_of(self, i: int, p: Player, bx: float, by: float):
        """Approximate position of player p of team i, given the ball in team i's frame."""
        ts = self.ts[i]
        slot = ts.lineup[p.id]
        sx, sy = POSITION_XY[slot]
        tac = ts.tactics
        if slot == "GK":
            return clamp(sx + (bx - 60) * 0.12, 2, 24), clamp(40 + (by - 40) * 0.15, 33, 47)
        x = sx + (bx - 60) * (0.42 + 0.2 * tac["line_height"]) + self.rng.gauss(0, 3.4)
        y = 40 + (sy - 40) * (0.75 + 0.45 * tac["width"]) + (by - 40) * 0.22 + self.rng.gauss(0, 3.4)
        group = POSITION_GROUP[slot]
        if bx > 85 and group in ("AM", "CM", "DM"):
            # late runs from midfield: when the team attacks the final third, the midfielders
            # push up, and now and then one arrives in the box
            x += (bx - 85) * {"AM": 0.9, "CM": 0.8, "DM": 0.4}[group]
            if self.rng.random() < {"AM": 0.26, "CM": 0.22, "DM": 0.07}[group] * (0.6 + 0.8 * tac.get("box_presence", 0.5)):
                x, y = self.rng.uniform(94, 106), 40 + self.rng.gauss(0, 9)   # edge of the box, sometimes in it
        if x > 100:
            # the attacking line flattens around the box: strikers, wingers and runners
            # from midfield arrive at similar depths instead of the striker standing alone
            x = 100 + (x - 100) * 0.6
        return clamp(x, 2, 116), clamp(y, 1, 79)

    def _nearest(self, i: int, x: float, y: float, exclude=(), outfield_only=True) -> Player:
        cands, ws = [], []
        for p in self.ts[i].on_pitch:
            if p.id in exclude or (outfield_only and self.ts[i].lineup[p.id] == "GK"):
                continue
            px, py = self._pos_of(i, p, x, y)
            cands.append(p)
            ws.append(1 / (1 + math.dist((px, py), (x, y))) ** 2.2)
        return self.rng.choices(cands, weights=ws)[0]

    def _player_ref(self, p: Player | None, team_idx: int | None):
        if p is None:
            return None
        ts = self.ts[team_idx]
        return {"id": p.id, "name": p.name, "number": p.number,
                "position": POSITION_NAME.get(ts.lineup.get(p.id, p.position), POSITION_NAME.get(p.position))}

    def _emit(self, etype: str, team_idx: int | None, player: Player | None, loc=None, end=None, outcome=None,
              details=None, under_pressure=False, duration=0.0, related=None):
        minute, second = self.minute, int(self.t % 60)
        if loc:
            loc = (clamp(loc[0], 0, L), clamp(loc[1], 0, W))
        if end:
            end = (clamp(end[0], 0, L), clamp(end[1], 0, W))
        ev = {
            "event_id": len(self.events) + 1,
            "match_id": self.match_id,
            "type": etype,
            "period": self.period,
            "minute": minute,
            "second": second,
            "clock": f"{minute:02d}:{second:02d}",
            "match_seconds": self.match_seconds,
            "added_time": self.t >= PERIOD_SECONDS,
            "team_id": self.ts[team_idx].team.id if team_idx is not None else None,
            "team": self.ts[team_idx].team.name if team_idx is not None else None,
            "player_id": player.id if player else None,
            "player": player.name if player else None,
            "position": self._player_ref(player, team_idx)["position"] if player and team_idx is not None else None,
            "possession_id": self.possession_id,
            "possession_team_id": self.ts[self.poss].team.id,
            "location": [round(loc[0], 1), round(loc[1], 1)] if loc else None,
            "location_abs": list(self._abs(team_idx, *loc)) if (loc and team_idx is not None) else None,
            "end_location": [round(end[0], 1), round(end[1], 1)] if end else None,
            "end_location_abs": list(self._abs(team_idx, *end)) if (end and team_idx is not None) else None,
            "outcome": outcome,
            "under_pressure": under_pressure,
            "duration_s": round(duration, 2),
            "details": details or {},
            "related_event_ids": related or [],
            "score": {"home": self.ts[0].score, "away": self.ts[1].score},
        }
        self.events.append(ev)
        self._advance(duration)
        return ev

    def _advance(self, seconds: float):
        self.t += seconds
        self._tick_loads()

    # ------------------------------------------------------- tracking metrics
    def _tick_loads(self):
        if self.period == 0:
            return
        abs_minute = (self.period - 1) * 45 + self.t / 60
        while self.last_load_minute + 1 <= abs_minute:
            self.last_load_minute += 1
            for ts in self.ts:
                tempo = 0.9 + 0.2 * ts.tactics["tempo"]
                for p in ts.on_pitch:
                    ld = self.load[p.id]
                    grp = POSITION_GROUP[ts.lineup[p.id]]
                    work = {"High": 1.05, "Medium": 1.0, "Low": 0.94}[p.work_rate[0]]
                    rate = RUN_RATE[grp] * tempo * work * (0.85 + 0.3 * p.a("stamina") / 100) * self._fatigue(p)
                    ld.distance_m += rate * self.rng.uniform(0.85, 1.15)
                    ld.minutes += 1
                    vmax = 24 + (p.a("sprint_speed") - 40) * 0.2 if grp != "GK" else 22
                    if self.rng.random() < (0.32 if grp != "GK" else 0.03):
                        ld.sprints += 1
                        ld.top_speed_kmh = max(ld.top_speed_kmh, vmax * self.rng.uniform(0.86, 1.0))
            if self.last_load_minute >= self.next_state_minute:
                self._emit_match_state()
                self.next_state_minute += 5

    def _emit_match_state(self):
        rows = []
        for ts in self.ts:
            for p in ts.on_pitch:
                ld = self.load[p.id]
                rows.append({"team_id": ts.team.id, "player_id": p.id, "player": p.name,
                             "distance_m": round(ld.distance_m), "top_speed_kmh": round(ld.top_speed_kmh, 1),
                             "sprints": ld.sprints})
        poss = self._possession_shares()
        recent = [self._recent_xg(k, 900) for k in (0, 1)]
        momentum = clamp((self.ts[0].momentum - self.ts[1].momentum) * 120 + (recent[0] - recent[1]) * 60, -100, 100)
        ev = self._emit("match_state", None, None, details={
            "minute": self.last_load_minute,
            "possession_pct": {"home": poss[0], "away": poss[1]},
            "xg": {"home": round(sum(x for _, x in self.ts[0].shot_log), 2),
                   "away": round(sum(x for _, x in self.ts[1].shot_log), 2)},
            "xg_last_15": {"home": round(recent[0], 2), "away": round(recent[1], 2)},
            "momentum": round(momentum),
            "formations": {"home": self.ts[0].formation, "away": self.ts[1].formation},
            "mentality": {"home": self.ts[0].mentality, "away": self.ts[1].mentality},
            "players": rows,
        })
        ev["minute"], ev["second"], ev["clock"] = self.last_load_minute, 0, f"{self.last_load_minute:02d}:00"

    def _possession_shares(self):
        time = [0.0, 0.0]
        prev = None
        for e in self.events:
            if prev is not None and e["period"] == prev["period"] and e["period"] in (1, 2):
                dt = e["match_seconds"] - prev["match_seconds"]
                if 0 < dt < 20:
                    time[0 if prev["possession_team_id"] == self.ts[0].team.id else 1] += dt
            prev = e
        tot = sum(time) or 1
        return round(100 * time[0] / tot), round(100 * time[1] / tot)

    def _recent_xg(self, k: int, window_s: float) -> float:
        now = self.match_seconds
        return sum(x for t, x in self.ts[k].shot_log if now - t <= window_s)

    # ------------------------------------------------------------ possession
    def _change_possession(self, new_team: int, x: float, y: float, carrier: Player | None, reason: str):
        """Switch possession; (x, y) is given in the NEW team's attacking frame."""
        self.poss = new_team
        self.possession_id += 1
        self.ball = (clamp(x, 0.5, 119.5), clamp(y, 0.5, 79.5))
        self.carrier = carrier
        self.assist_ev = None
        self.chain = 0
        self.poss_start = (self.ball[0], self.match_seconds)
        self._emit("possession_change", new_team, carrier, self.ball, details={"reason": reason})

    def _is_counter(self) -> bool:
        x0, t0 = self.poss_start
        return x0 < 55 and self.match_seconds - t0 < 15

    # -------------------------------------------------------------- the match
    def run(self) -> list[dict]:
        self._emit_match_start()
        for period in (1, 2):
            self.period = period
            self.t = 0.0
            stoppage = self.rng.choice([60, 90, 120, 120, 180, 240]) if period == 1 else \
                self.rng.choice([180, 240, 240, 300, 360, 420, 480])
            self.period_len = PERIOD_SECONDS + stoppage
            self._emit("period_start", None, None, details={
                "period": period, "added_time_announced_min": stoppage // 60,
                "attacking_left_to_right": self.ts[0].team.id if period == 1 else self.ts[1].team.id,
            })
            self.restart = ("kick_off", 0 if period == 1 else 1)
            if period == 2:
                self._manager_checkpoint(45)
                self._half_time_subs()
            while self.t < self.period_len:
                self._update_momentum()
                self._handle_triggers()
                if period == 2:
                    self._scheduled_checkpoints()
                    self._maybe_substitute()
                self._maybe_injury()
                self._step()
            self._emit("period_end", None, None, details={"period": period})
        self._emit_match_end()
        return self.events

    def _emit_match_start(self):
        rng = self.rng
        h = self.ts[0].team

        def lineup(ts: TeamState):
            return {
                "team": {k: v for k, v in ts.team.to_dict().items() if k != "players"},
                "formation": ts.formation,
                "starting_xi": [{**p.to_dict(), "slot": ts.lineup[p.id], "slot_name": POSITION_NAME[ts.lineup[p.id]]}
                                for p in ts.on_pitch],
                "bench": [p.to_dict() for p in ts.bench],
            }

        self._emit("match_start", None, None, details={
            "league": LEAGUE_NAME, "matchday": self.matchday, "kickoff_utc": self.kickoff_utc,
            "venue": h.stadium, "city": h.city, "referee": rng.choice(REFEREES), "weather": rng.choice(WEATHER),
            "attendance": int(rng.uniform(0.82, 0.99) * rng.choice([28000, 34000, 41000, 52000, 61000])),
            "home": lineup(self.ts[0]), "away": lineup(self.ts[1]),
            "seed": self.seed, "synthetic": True,
            "xg_model": "trained logistic regression (PL 2015/16)" if self.xg_model else "geometric fallback",
            "pitch": {"length": L, "width": W, "units": "StatsBomb (120 x 80)"},
            "coordinate_note": "location = acting team's attacking frame; location_abs = home attacks left->right in period 1",
        })

    def _emit_match_end(self):
        stats = player_match_stats(self.events)
        motm = max(stats.values(), key=lambda r: r["rating"]) if stats else None
        self._emit("match_end", None, None, details={
            "final_score": {"home": self.ts[0].score, "away": self.ts[1].score},
            "xg": {"home": round(sum(x for _, x in self.ts[0].shot_log), 2),
                   "away": round(sum(x for _, x in self.ts[1].shot_log), 2)},
            "player_of_the_match": {"player_id": motm["player_id"], "player": motm["player"],
                                    "team_id": motm["team_id"], "rating": motm["rating"]} if motm else None,
            "player_ratings": sorted(stats.values(), key=lambda r: -r["rating"]),
        })

    def _update_momentum(self):
        for ts in self.ts:
            ts.momentum += self.rng.gauss(0, 0.012) - ts.momentum * 0.004
            ts.momentum = clamp(ts.momentum, -0.6, 0.6)

    # ----------------------------------------------------- manager decisions
    def _scheduled_checkpoints(self):
        while self.next_checkpoint < len(CHECKPOINTS) and self.minute >= CHECKPOINTS[self.next_checkpoint]:
            m = CHECKPOINTS[self.next_checkpoint]
            self.next_checkpoint += 1
            if m != 45:
                self._manager_checkpoint(m)

    def _manager_checkpoint(self, minute: int, trigger: str | None = None, only: int | None = None):
        if minute == 45:
            self.next_checkpoint = max(self.next_checkpoint, 1)
        for k in ([only] if only is not None else (0, 1)):
            ts, opp = self.ts[k], self.ts[1 - k]
            decision = self.coach.decide(
                minute=minute, diff=ts.score - opp.score, trigger=trigger, team=ts.team,
                current_formation=ts.formation, instructions=ts.instructions, mentality=ts.mentality,
                xg_for_recent=self._recent_xg(k, 900), xg_against_recent=self._recent_xg(1 - k, 900),
                changes_so_far=ts.tactical_changes, players_on_pitch=len(ts.on_pitch),
                team_is_favourite=ts.strength() + (2 if ts.side == "home" else 0) > opp.strength())
            if decision:
                self._apply_decision(k, decision)

    def _apply_decision(self, k: int, d):
        ts = self.ts[k]
        before = {"formation": ts.formation, "mentality": ts.mentality,
                  **{key: ts.instructions[key] for key in d.instruction_changes}}
        ts.instructions.update(d.instruction_changes)
        ts.mentality = d.mentality
        ts.tactical_changes += 1
        if d.new_formation and d.new_formation in FORMATIONS:
            ts.formation = d.new_formation
            self._reassign_slots(ts)
        self._emit("tactical_change", k, None, details={
            "reason": d.reason, "description": d.description, "manager": ts.team.manager,
            "from_formation": before["formation"], "to_formation": ts.formation,
            "from_mentality": before["mentality"], "to_mentality": ts.mentality,
            "instructions_before": {key: before[key] for key in d.instruction_changes},
            "instructions_after": dict(d.instruction_changes),
            "score_diff": ts.score - self.ts[1 - k].score,
        }, duration=0.0)
        if d.sub_profile and self.period == 2:
            self._substitute(k, reason={"attacking": "tactical_attacking", "defensive": "tactical_defensive"}[d.sub_profile],
                             profile=d.sub_profile)

    def _reassign_slots(self, ts: TeamState):
        slots = list(FORMATIONS[ts.formation])
        n = len(ts.on_pitch)
        drop_order = ["ST", "RCF", "LCF", "SS", "CAM", "RAM", "LAM", "RW", "LW", "RM", "LM"]
        while len(slots) > n:
            for code in drop_order:
                if code in slots and len(slots) > n:
                    slots.remove(code)
                    break
            else:
                slots.pop()
        players = list(ts.on_pitch)
        new = {}
        gk = ts.gk
        if gk and "GK" in slots:
            new[gk.id] = "GK"
            slots.remove("GK")
            players.remove(gk)
        for slot in sorted(slots, key=lambda s: {"CB": 0, "FB": 1, "ST": 2}.get(POSITION_GROUP[s], 3)):
            best = max(players, key=lambda p: p.position_rating(slot))
            new[best.id] = slot
            players.remove(best)
        ts.lineup = new

    def _handle_triggers(self):
        while self.pending_triggers:
            k, trig = self.pending_triggers.pop(0)
            self._manager_checkpoint(self.minute, trigger=trig, only=k)

    # ------------------------------------------------------------ substitutions
    def _half_time_subs(self):
        for k, ts in enumerate(self.ts):
            booked_risk = [p for p in ts.on_pitch if ts.yellow.get(p.id) and p.a("aggression") > 70]
            if (ts.score < self.ts[1 - k].score and self.rng.random() < 0.25) or (booked_risk and self.rng.random() < 0.3):
                self._substitute(k, reason="half_time_change", count_window=False,
                                 profile="attacking" if ts.score < self.ts[1 - k].score else None,
                                 prefer_off=booked_risk[0] if booked_risk else None)

    def _maybe_substitute(self):
        now = self.minute + (self.t % 60) / 60
        for k, ts in enumerate(self.ts):
            while ts.planned_windows and now >= ts.planned_windows[0][0]:
                _, n = ts.planned_windows.pop(0)
                if ts.sub_windows_used >= 3:
                    break
                diff = ts.score - self.ts[1 - k].score
                profile = "attacking" if diff < 0 else ("defensive" if diff > 0 and self.minute >= 75 else None)
                for j in range(n):
                    self._substitute(k, reason="fatigue" if profile is None else
                                     ("tactical_attacking" if profile == "attacking" else "tactical_defensive"),
                                     profile=profile, count_window=(j == 0))

    def _maybe_injury(self):
        for k, ts in enumerate(self.ts):
            if self.rng.random() < 0.00004 * 15:
                victim = self.rng.choice([p for p in ts.on_pitch])
                self._emit("injury", k, victim, details={"severity": self.rng.choice(["knock", "muscle strain"])},
                           duration=self.rng.uniform(40, 120))
                if not self._substitute(k, reason="injury", prefer_off=victim, profile=None):
                    pass  # no subs left: the player carries on

    def _substitute(self, k: int, reason: str, profile: str | None = None, prefer_off: Player | None = None,
                    count_window: bool = True) -> bool:
        ts = self.ts[k]
        if ts.subs_used >= 5 or not ts.bench:
            return False
        if count_window and reason != "injury":
            if ts.sub_windows_used >= 3:
                return False
            ts.sub_windows_used += 1
        outfield = [p for p in ts.on_pitch if ts.lineup[p.id] != "GK"]
        if not outfield:
            return False
        # A substitute who came on is not taken off again (only an injury can force it):
        # a large penalty keeps him out of the choice without changing the random draws.
        fresh = lambda p: 1000 * (p.id in ts.came_on)
        if prefer_off and prefer_off in ts.on_pitch:
            pass
        elif profile == "attacking":
            pool = [p for p in outfield if POSITION_GROUP[ts.lineup[p.id]] in ("DM", "FB", "CM")] or outfield
            off = min(pool, key=lambda p: p.position_rating(ts.lineup[p.id]) + self.rng.uniform(0, 6) + fresh(p))
        elif profile == "defensive":
            pool = [p for p in outfield if POSITION_GROUP[ts.lineup[p.id]] in ATTACKING_GROUPS] or outfield
            off = min(pool, key=lambda p: p.position_rating(ts.lineup[p.id]) + self.rng.uniform(0, 6) + fresh(p))
        else:
            off = max(outfield, key=lambda p: self.load[p.id].distance_m / (p.a("stamina") + 1)
                      + (ts.yellow.get(p.id, 0) * 15) + self.rng.uniform(0, 25) - fresh(p))
        if prefer_off and prefer_off in ts.on_pitch:
            off = prefer_off
        if off.id in ts.came_on and off is not prefer_off:
            return False
        slot = ts.lineup[off.id]
        if off.id == (ts.gk.id if ts.gk else None):
            cands = [p for p in ts.bench if p.group == "GK"]
        else:
            cands = [p for p in ts.bench if p.group != "GK"]
            if profile == "attacking":
                att = [p for p in cands if p.group in ATTACKING_GROUPS]
                cands = att or cands
            elif profile == "defensive":
                dfn = [p for p in cands if p.group in DEFENSIVE_GROUPS]
                cands = dfn or cands
        if not cands:
            return False
        on = max(cands, key=lambda p: p.position_rating(slot) + self.rng.uniform(0, 2))
        if profile == "attacking" and POSITION_GROUP[slot] in ("DM", "FB", "CM") and on.group in ATTACKING_GROUPS:
            # an attacker replaces a midfielder/full-back: keep the slot, the player brings attacking intent
            pass
        ts.bench.remove(on)
        ts.on_pitch[ts.on_pitch.index(off)] = on
        del ts.lineup[off.id]
        ts.lineup[on.id] = slot
        ts.subs_used += 1
        ts.used_players.add(on.id)
        ts.came_on.add(on.id)
        if self.carrier is off:
            self.carrier = on
        self._emit("substitution", k, off, details={
            "player_off": off.name, "player_off_id": off.id, "player_on": on.name, "player_on_id": on.id,
            "slot": slot, "position": POSITION_NAME[slot], "reason": reason,
            "subs_used": ts.subs_used, "windows_used": ts.sub_windows_used,
        }, duration=self.rng.uniform(15, 35))
        return True

    # ------------------------------------------------------------------- steps
    def _step(self):
        if self.restart:
            self._do_restart()
            return
        i = self.poss
        ts, opp = self.ts[i], self.ts[1 - i]
        tac, otac = ts.tactics, opp.tactics
        x, y = self.ball
        if self.carrier is None or self.carrier not in ts.on_pitch:
            self.carrier = self._nearest(i, x, y, outfield_only=x > 20)
        p = self.carrier

        # --- pressure from the opponent
        zone_press = 0.19 + 0.20 * otac["pressing"] * (1 - x / L) + (0.12 if x > 80 else 0)
        if otac["counter_press"] and self.match_seconds - self.poss_start[1] < 6:
            zone_press += 0.18
        under_pressure = self.rng.random() < zone_press * (1 + 0.5 * opp.momentum)
        if under_pressure:
            presser = self._nearest(1 - i, *mirror(x, y))
            px, py = mirror(x + self.rng.uniform(-3, 3), y + self.rng.uniform(-3, 3))
            self._emit("pressure", 1 - i, presser, (px, py), details={
                "on_player_id": p.id, "on_player": p.name,
                "intensity": round(self.rng.uniform(0.4, 1.0) * (0.6 + 0.4 * otac["pressing"]), 2),
            })
            in_box = x > 102 and abs(y - GOAL_Y) < 22
            if self.rng.random() < 0.074 * (0.6 + 0.8 * otac["pressing"]) * (presser.a("aggression") / 70) \
                    * (0.06 if in_box else 1.0):
                self._foul(1 - i, presser, i, p, x, y)
                return
            if self.rng.random() < 0.24 * (1.25 - p.a("composure") / 100) * (1 + opp.momentum) \
                    * (presser.a("tackling") / 70):
                ox, oy = mirror(x, y)
                self._emit("duel", 1 - i, presser, (ox, oy), outcome="won",
                           details={"duel_type": "Tackle", "on_player_id": p.id, "on_player": p.name},
                           duration=self.rng.uniform(0.4, 1.2))
                self._change_possession(1 - i, ox, oy, presser, "tackle")
                return

        dist, ang = shot_distance(x, y), shot_angle(x, y)
        edge = self._edge(i)
        wide = abs(y - GOAL_Y) > 22
        attack_mult = {"all_out_attack": 1.2, "attacking": 1.1, "defensive": 0.88}.get(ts.mentality, 1.0)
        # sustained possession pins the opponent back and opens space: chances grow with the pass chain
        attack_mult *= 0.55 + 0.085 * min(self.chain, 12)
        if x > 96:
            # in and around the box a counter-attack is as dangerous as a long move: no penalty
            # for a short pass chain there (otherwise strikers through on goal pass it back)
            attack_mult = max(attack_mult, 0.85 * {"all_out_attack": 1.2, "attacking": 1.1, "defensive": 0.9}.get(ts.mentality, 1.0))

        weights = {}
        if dist < 34 and x > 76:
            central = abs(y - GOAL_Y) < 18
            weights["shot"] = 0.9 * ((0.195 if central else 0.039) + 1.4 * quick_xg(x, y)) \
                * (1 + 0.5 * (p.a("finishing") - 60) / 40) * (0.6 if under_pressure else 1.0) * attack_mult \
                * (1.25 if "Long shot taker" in p.traits and dist > 20 else 1.0) * (1 + 1.5 * edge) \
                * {"ST": 0.5 if x < 100 else 0.6, "W": 1.2, "AM": 1.3, "CM": 1.2, "DM": 0.9, "FB": 0.8, "CB": 0.5,
                   "GK": 0.05}[POSITION_GROUP[ts.lineup[p.id]]]
            if x > 102 and abs(y - GOAL_Y) < 22:
                weights["shot"] *= 0.62            # in the box: chosen often enough, without overdoing it
            elif dist > 20:
                weights["shot"] *= 1.0             # efforts from distance, about 40% of shots as in the PL
        if x > 86 and wide:
            weights["cross"] = (0.15 + 0.30 * tac["crossing"]) * attack_mult
        weights["dribble"] = (0.016 + 0.06 * max(0, p.a("dribbling") - 55) / 40) * (1.5 if x > 68 else 0.6) \
            * (0.7 + 0.15 * p.skill_moves)
        weights["carry"] = 0.16 + 0.07 * tac["tempo"]
        if x < 28 and under_pressure:
            weights["clearance"] = 0.06 + 0.10 * tac["directness"]
        weights["pass"] = 1.0
        if x > 102 and not wide:
            weights["pass"] = 0.75                 # in the box the pass is no longer the default option
        if 57 < x < 102 and not wide:
            weights["through_ball"] = (0.02 + 0.075 * tac["through_balls"] * p.a("vision") / 80) * attack_mult
        action = self.rng.choices(list(weights), weights=list(weights.values()))[0]
        getattr(self, f"_a_{action}")(i, p, x, y, under_pressure, edge)

    # -------------------------------------------------------------- passing
    def _pick_target(self, i, p, x, y, long=False):
        ts = self.ts[i]
        tac = ts.tactics
        cands, ws, poss = [], [], []
        for q in ts.on_pitch:
            if q is p:
                continue
            qx, qy = self._pos_of(i, q, x, y)
            d = math.dist((qx, qy), (x, y))
            dx = qx - x
            if long:
                w = math.exp(-((d - 43) ** 2) / (2 * 14 ** 2)) * (1 + max(0, dx) / 14)
            else:
                pref = 16 + 11 * tac["directness"]
                w = math.exp(-((d - pref) ** 2) / (2 * 10 ** 2))
                w *= (1 + (0.5 + 0.9 * tac["directness"]) * max(0, dx) / 17)
                if dx < -4:
                    w *= 0.5 + 0.35 * (1 - tac["directness"])
                    if x > 100:
                        w *= 0.4                   # from inside the box, players rarely play it back out
            if ts.lineup[q.id] == "GK":
                w *= 0.25 if x < 45 else 0.01
            if qx > 80:
                w *= {"ST": 0.38, "W": 1.2, "AM": 1.35, "CM": 1.3, "DM": 0.95, "FB": 1.0, "CB": 0.6}.get(
                    POSITION_GROUP[ts.lineup[q.id]], 1.0)
            cands.append(q)
            ws.append(max(w, 1e-4))
            poss.append((qx, qy))
        k = self.rng.choices(range(len(cands)), weights=ws)[0]
        return cands[k], poss[k]

    def _pass_success(self, p, x, y, ex, ey, under_pressure, edge, kind="ground"):
        d = math.dist((x, y), (ex, ey))
        dx = ex - x
        prob = 0.94 + (p.a("passing") - 70) / 250 + edge * 0.35
        prob -= max(0, d - 16) * 0.0052
        prob -= max(0, dx) / 34 * 0.085
        if ex > 97:
            prob -= 0.10
        if ex > 102 and abs(ey - GOAL_Y) < 22:
            prob -= 0.16
        if under_pressure:
            prob -= 0.085 * (1 - (p.a("composure") - 50) / 100)
        if kind == "long":
            prob -= 0.12
        prob *= self._fatigue(p)
        prob = clamp(prob, 0.2, 0.985)
        return prob, round(clamp((1 - prob) * 14, 0, 10), 1)

    def _pass_details(self, x, y, ex, ey, recipient, kind, difficulty, height="Ground Pass", **flags):
        d = math.dist((x, y), (ex, ey))
        ang = math.degrees(math.atan2(ey - y, ex - x))
        prog = (L - x) - (L - ex) >= (11 if x > 60 else 28) or (ex > 102 and x <= 102)
        speed = (32 if height == "Ground Pass" else 40) + d * 1.05 + self.rng.gauss(0, 5)
        det = {
            "recipient_id": recipient.id if recipient else None,
            "recipient": recipient.name if recipient else None,
            "pass_type": kind, "height": height,
            "length": round(d, 1), "angle_deg": round(ang, 1),
            "ball_speed_kmh": round(clamp(speed, 25, 115), 1),
            "difficulty": difficulty, "progressive": bool(prog),
            "into_final_third": bool(ex > 80 and x <= 80),
            "into_box": bool(ex > 102 and abs(ey - GOAL_Y) < 22 and not (x > 102 and abs(y - GOAL_Y) < 22)),
            "cross": False, "cut_back": False, "through_ball": False, "switch": abs(ey - y) > 40,
        }
        det.update(flags)
        return det

    def _a_pass(self, i, p, x, y, up, edge, long=None):
        tac = self.ts[i].tactics
        if long is None:
            long = self.rng.random() < (0.03 + 0.11 * tac["directness"] + (0.08 if up and x < 45 else 0)) \
                * (1 if x < 68 else 0.3)
        q, (qx, qy) = self._pick_target(i, p, x, y, long=long)
        ex, ey = clamp(qx + self.rng.gauss(0, 1.6), 1, 118), clamp(qy + self.rng.gauss(0, 1.6), 0.5, 79.5)
        kind = "long" if long else ("back" if ex < x - 4 else ("switch" if abs(ey - y) > 40 else "short"))
        prob, diff = self._pass_success(p, x, y, ex, ey, up, edge, "long" if long else "ground")
        d = math.dist((x, y), (ex, ey))
        dur = 0.4 + d / (18 if not long else 22) + self.rng.uniform(0.3, 1.2) * (1.05 - 0.45 * tac["tempo"])
        if long or (ex > 96 and d > 14 and self.rng.random() < 0.2):
            height = "High Pass"
        else:
            height = "Low Pass" if d > 25 and self.rng.random() < 0.35 else "Ground Pass"
        det = self._pass_details(x, y, ex, ey, q, kind, diff, height)
        if self.rng.random() < prob:
            ev = self._emit("pass", i, p, (x, y), (ex, ey), "complete", det, up, dur)
            self._received(ev, q, (ex, ey))
            return
        self._failed_pass(i, p, x, y, ex, ey, det, up, dur)

    def _received(self, pass_ev, recipient, loc):
        self.assist_ev = pass_ev
        self.chain += 1
        self.ball, self.carrier = loc, recipient

    def _failed_pass(self, i, p, x, y, ex, ey, det, up, dur):
        u = self.rng.uniform(0.45, 1.0)
        ix, iy = x + (ex - x) * u, y + (ey - y) * u
        if self.rng.random() < 0.28:
            det = {**det, "out_of_play": True}
            self._emit("pass", i, p, (x, y), (ex, ey), "out", det, up, dur)
            if ex > 116:
                self._set_restart("goal_kick", 1 - i, (6, 40))
            else:
                side = 0.3 if ey < 40 else 79.7
                ox, oy = mirror(clamp(ix, 1, 119), side)
                self._set_restart("throw_in", 1 - i, (ox, oy))
            return
        self._emit("pass", i, p, (x, y), (ex, ey), "incomplete", det, up, dur)
        ox, oy = mirror(ix, iy)
        rec = self._nearest(1 - i, ox, oy, outfield_only=ox > 18)
        kind = "interception" if self.rng.random() < 0.24 else "ball_recovery"
        self._emit(kind, 1 - i, rec, (ox, oy), outcome="won", details={"from_player_id": p.id},
                   duration=self.rng.uniform(0.4, 1.2))
        self._change_possession(1 - i, ox, oy, rec, kind)

    def _a_through_ball(self, i, p, x, y, up, edge):
        ts = self.ts[i]
        runners = [q for q in ts.on_pitch if POSITION_GROUP[ts.lineup[q.id]] in ("ST", "W", "AM", "CM") and q is not p]
        if not runners:
            return self._a_pass(i, p, x, y, up, edge)
        q = max(self.rng.sample(runners, min(3, len(runners))), key=lambda r: r.a("pace_skill") + self.rng.uniform(0, 28))
        ex = clamp(x + self.rng.uniform(17, 34), x + 9, 112)
        ey = clamp(GOAL_Y + self.rng.gauss(0, 11), 10, 70)
        otac = self.ts[1 - i].tactics
        prob = clamp(0.27 + (p.a("vision") - 70) / 200 + edge * 0.3 + (q.a("pace_skill") - 70) / 300
                     + (otac["line_height"] - 0.5) * 0.12, 0.1, 0.6)
        diff = round(clamp((1 - prob) * 14, 0, 10), 1)
        det = self._pass_details(x, y, ex, ey, q, "through_ball", diff, through_ball=True)
        dur = 1.0 + math.dist((x, y), (ex, ey)) / 17
        r = self.rng.random()
        if r < prob:
            ev = self._emit("pass", i, p, (x, y), (ex, ey), "complete", det, up, dur)
            self._received(ev, q, (ex, ey))
            if ex > 96 and self.rng.random() < 0.6:
                self._take_shot(i, q, ex, ey, False, assist_type="through_ball")
            return
        if r < prob + 0.15 + (otac["line_height"] - 0.5) * 0.1:
            self._emit("pass", i, p, (x, y), (ex, ey), "offside", det, up, dur)
            self._emit("offside", i, q, (ex - 2, ey), duration=self.rng.uniform(8, 18))
            fx, fy = mirror(ex - 2, ey)
            self._set_restart("free_kick", 1 - i, (fx, fy))
            return
        self._failed_pass(i, p, x, y, ex, ey, det, up, dur)

    def _a_carry(self, i, p, x, y, up, edge):
        tac = self.ts[i].tactics
        dist = self.rng.uniform(3, 10) + 11 * tac["tempo"] * self.rng.random() * (0.5 if up else 1)
        ang = self.rng.gauss(0, 0.6)
        ex, ey = clamp(x + dist * math.cos(ang), 1, 118), clamp(y + dist * math.sin(ang), 1, 79)
        if ex > 111:
            ex = 111 - self.rng.uniform(0, 4)
        d = math.dist((x, y), (ex, ey))
        speed = clamp(10 + (p.a("pace_skill") - 40) * 0.25 * self.rng.uniform(0.6, 1.0) + d * 0.2, 8, 36)
        ld = self.load[p.id]
        ld.top_speed_kmh = max(ld.top_speed_kmh, speed)
        self._emit("carry", i, p, (x, y), (ex, ey), "complete", {
            "length": round(d, 1), "avg_speed_kmh": round(speed * 0.85, 1), "max_speed_kmh": round(speed, 1),
            "progressive": bool(ex - x > 10 or (ex > 102 and x <= 102)),
        }, up, d / (speed / 3.6))
        if d > 9:
            self.assist_ev = None          # a long solo carry: the shot is no longer "assisted"
        self.ball = (ex, ey)

    def _a_dribble(self, i, p, x, y, up, edge):
        ox, oy = mirror(x, y)
        d = self._nearest(1 - i, ox, oy)
        prob = clamp(0.47 + (p.a("dribbling") - d.a("tackling")) / 110 + edge * 0.3 - (0.06 if up else 0)
                     + 0.02 * (p.skill_moves - 3), 0.15, 0.85)
        if self.rng.random() < prob:
            self._emit("dribble", i, p, (x, y), outcome="complete",
                       details={"beaten_player_id": d.id, "beaten_player": d.name}, under_pressure=up,
                       duration=self.rng.uniform(1, 2.5))
            self.assist_ev = None
            self._a_carry(i, p, x, y, False, edge)
            return
        self._emit("dribble", i, p, (x, y), outcome="incomplete", details={"defender_id": d.id, "defender": d.name},
                   under_pressure=up, duration=self.rng.uniform(0.8, 2))
        if self.rng.random() < 0.2 * (d.a("aggression") / 70) * (0.3 if (x > 102 and abs(y - GOAL_Y) < 22) else 1.0):
            self._foul(1 - i, d, i, p, x, y)
            return
        self._emit("duel", 1 - i, d, (ox, oy), outcome="won",
                   details={"duel_type": "Tackle", "on_player_id": p.id, "on_player": p.name},
                   duration=self.rng.uniform(0.3, 1))
        self._change_possession(1 - i, ox, oy, d, "tackle")

    def _a_clearance(self, i, p, x, y, up, edge):
        ex, ey = clamp(x + self.rng.uniform(34, 62), 45, 108), clamp(y + self.rng.gauss(0, 17), 3, 77)
        self._emit("clearance", i, p, (x, y), (ex, ey), details={"head": self.rng.random() < 0.35},
                   under_pressure=up, duration=self.rng.uniform(2.5, 4))
        if self.rng.random() < 0.38:
            q = self._nearest(i, ex, ey)
            self._emit("ball_recovery", i, q, (ex, ey), duration=self.rng.uniform(0.5, 1.5))
            self.ball, self.carrier = (ex, ey), q
            self.assist_ev = None
        else:
            ox, oy = mirror(ex, ey)
            q = self._nearest(1 - i, ox, oy)
            self._emit("ball_recovery", 1 - i, q, (ox, oy), duration=self.rng.uniform(0.5, 1.5))
            self._change_possession(1 - i, ox, oy, q, "loose_ball")

    def _a_cross(self, i, p, x, y, up, edge, set_piece=None):
        ts = self.ts[i]
        tac = ts.tactics
        targets = [q for q in ts.on_pitch if q is not p and ts.lineup[q.id] != "GK"]

        # cut-back: from near the byline, a ground pass back to the penalty spot area
        if set_piece is None and x > 106 and self.rng.random() < 0.2:
            ex, ey = self.rng.uniform(100, 108), clamp(GOAL_Y + self.rng.gauss(0, 7), 28, 52)
            q = max(self.rng.sample(targets, min(3, len(targets))), key=lambda z: z.a("finishing") + self.rng.uniform(0, 30))
            prob = clamp(0.5 + (p.a("passing") - 70) / 220 + edge * 0.3, 0.3, 0.75)
            det = self._pass_details(x, y, ex, ey, q, "cut_back", round((1 - prob) * 12, 1), cut_back=True)
            if self.rng.random() < prob:
                ev = self._emit("pass", i, p, (x, y), (ex, ey), "complete", det, up, 1.2)
                self._received(ev, q, (ex, ey))
                if self.rng.random() < 0.6:
                    self._take_shot(i, q, ex, ey, False, assist_type="cut_back")
                return
            self._failed_pass(i, p, x, y, ex, ey, det, up, 1.2)
            return

        # who is in the box for the cross: not only the striker, the late runners too
        in_box = {"ST": 0.9, "W": 0.75, "AM": 0.75, "CM": 0.6, "DM": 0.3, "FB": 0.3,
                  "CB": 0.9 if set_piece else 0.05}
        targets = [q for q in targets if self.rng.random() < in_box.get(POSITION_GROUP[ts.lineup[q.id]], 0.3)] or targets
        ex, ey = self.rng.uniform(102, 116), clamp(GOAL_Y + self.rng.gauss(0, 7), 25, 55)
        prob = clamp(0.29 + (p.a("crossing") - 70) / 230 + edge * 0.3 - (0.04 if up else 0)
                     + (0.06 if set_piece == "corner" else 0) + 0.06 * (tac["box_presence"] - 0.5), 0.08, 0.52)
        q = max(self.rng.sample(targets, min(3, len(targets))),      # who gets to it: timing matters as much as height
                key=lambda z: z.a("heading") + (z.height_cm - 180) * 0.5 + self.rng.uniform(0, 32))
        kind = {"corner": "corner", "free_kick": "free_kick"}.get(set_piece, "cross")
        det = self._pass_details(x, y, ex, ey, q, kind, round(clamp((1 - prob) * 12, 0, 10), 1), "High Pass",
                                 cross=True)
        dur = 1.4 + self.rng.uniform(0, 0.8)
        if self.rng.random() < prob:
            ev = self._emit("pass", i, p, (x, y), (ex, ey), "complete", det, up, dur)
            self._received(ev, q, (ex, ey))
            if self.rng.random() < (0.36 if set_piece else 0.46):
                at = "set_piece" if set_piece else "cross"
                self._take_shot(i, q, ex, ey, self.rng.random() < 0.45, assist_type=at,
                                set_piece=set_piece is not None)
            return
        self._emit("pass", i, p, (x, y), (ex, ey), "incomplete", det, up, dur)
        ox, oy = mirror(ex, ey)
        dfd = self._nearest(1 - i, ox, oy)
        r = self.rng.random()
        opp_gk = self.ts[1 - i].gk
        if r < 0.38:
            self._emit("clearance", 1 - i, dfd, (ox, oy), details={"head": True, "to_corner": True},
                       duration=self.rng.uniform(1, 2))
            self._set_restart("corner", i, (119.5, 0.5 if y < 40 else 79.5))
        elif r < 0.55 and opp_gk:
            self._emit("goalkeeper", 1 - i, opp_gk, (ox, oy), outcome="claim", details={"action": "claim"},
                       duration=self.rng.uniform(1, 3))
            self._change_possession(1 - i, ox, oy, opp_gk, "keeper_claim")
        else:
            self._a_clearance(1 - i, dfd, ox, oy, True, -edge)

    # ----------------------------------------------------------------- shots
    def _a_shot(self, i, p, x, y, up, edge):
        self._take_shot(i, p, x, y, up)

    def _shot_profile(self, at: str, band: str) -> dict:
        by = cal.SHOTS["by_assist"].get(at) or cal.SHOTS["by_assist"]["ground_pass"]
        bands = by["by_band"]
        if band in bands:
            return bands[band]
        order = ["0-12", "12-18", "18-25", "25+"]
        k = order.index(band)
        for off in (1, -1, 2, -2, 3, -3):
            if 0 <= k + off < 4 and order[k + off] in bands:
                return bands[order[k + off]]
        return next(iter(bands.values()))

    def _realistic_shot_spot(self, x, y, assist_type):
        """Keep the engine's distance band but draw the exact distance and how central the
        shooter is from real PL shots with the same assist type and band (the shooter
        takes a touch to set the shot up)."""
        from .freeze import sample_quantiles
        band = dist_band(shot_distance(x, y))
        lo_hi = {"0-12": (1.5, 11.99), "12-18": (12, 17.99), "18-25": (18, 24.99), "25+": (25, 45)}[band]
        qd = cal.SHOTS["distance_q"].get(f"{assist_type}|{band}") or cal.SHOTS["distance_q"][f"any|{band}"]
        d = clamp(sample_quantiles(self.rng, qd, lo=1.5), *lo_hi)
        q = cal.SHOTS["lateral_q"].get(f"{assist_type}|{band}") or cal.SHOTS["lateral_q"][f"any|{band}"]
        dy = min(sample_quantiles(self.rng, q, lo=0.0), d * 0.97)
        sign = 1 if y >= GOAL_Y else -1
        nx = GOAL_X - math.sqrt(max(0.5, d * d - dy * dy))
        return clamp(nx, 60, 119), clamp(GOAL_Y + sign * dy, 0.5, 79.5)

    def _take_shot(self, i, p, x, y, up, *, assist_type=None, one_on_one=None, shot_type="Open Play",
                   set_piece=False):
        rng = self.rng
        ts, opp = self.ts[i], self.ts[1 - i]
        assist = self.assist_ev if (self.assist_ev and self.assist_ev["possession_id"] == self.possession_id
                                    and self.assist_ev["details"].get("recipient_id") == p.id) else None
        if assist_type is None:
            if assist is None or shot_type != "Open Play":
                assist_type = "no_assist"
            else:
                d = assist["details"]
                if d["pass_type"] in ("corner", "free_kick", "throw_in"):
                    assist_type = "set_piece"
                elif d.get("through_ball"):
                    assist_type = "through_ball"
                elif d.get("cut_back"):
                    assist_type = "cut_back"
                elif d.get("cross"):
                    assist_type = "cross"
                elif d["height"] == "High Pass":
                    assist_type = "high_pass"
                else:
                    assist_type = "ground_pass"
        if assist_type == "no_assist":
            assist = None
        if shot_type == "Open Play":
            x, y = self._realistic_shot_spot(x, y, assist_type)
        x, y = round(x, 1), round(y, 1)          # exactly what the event will carry
        band = dist_band(shot_distance(x, y))
        prof = self._shot_profile(assist_type, band)

        # body part: header probability from real data, scaled by the player's aerial ability
        if shot_type in ("Penalty", "Free Kick"):
            head = False
        else:
            ph = prof["head"] * clamp(0.45 + (p.a("aerial") - 55) / 30 + (p.height_cm - 182) / 40, 0.3, 1.6)
            head = rng.random() < min(0.95, ph)
        if head:
            body = "Head"
            technique = rng.choices(list(prof["technique_head"]), weights=list(prof["technique_head"].values()))[0]
            first_time = rng.random() < prof.get("first_time_head", 0.0)
            duel = prof["aerial_won_head"] * clamp(0.7 + (p.a("aerial") - 60) / 50, 0.4, 1.4)
            aerial_won = rng.random() < min(0.95, duel)
        else:
            weak_share = {1: 0.04, 2: 0.10, 3: 0.19, 4: 0.30, 5: 0.45}[p.weak_foot]
            strong = p.preferred_foot
            weak = "Left" if strong == "Right" else "Right"
            body = f"{weak if rng.random() < weak_share else strong} Foot"
            if shot_type == "Open Play":
                technique = rng.choices(list(prof["technique_foot"]), weights=list(prof["technique_foot"].values()))[0]
                if technique in ("Backheel", "Overhead Kick") and p.skill_moves <= 2 and rng.random() < 0.6:
                    technique = "Volley" if technique == "Overhead Kick" else "Normal"
                first_time = rng.random() < prof["first_time_foot"]
            else:
                technique, first_time = "Normal", False
            aerial_won = False
        if one_on_one is None:
            one_on_one = rng.random() < prof["one_on_one"] and shot_type == "Open Play"
        up = shot_type == "Open Play" and rng.random() < prof["under_pressure"]
        if up and self.events and self.events[-1]["type"] != "pressure":
            presser = self._nearest(1 - i, *mirror(x, y))
            self._emit("pressure", 1 - i, presser, mirror(x + rng.uniform(-1.5, 1.5), y + rng.uniform(-1.5, 1.5)),
                       details={"on_player_id": p.id, "on_player": p.name, "intensity": round(rng.uniform(0.6, 1), 2)})
        if shot_type != "Open Play":
            up = False

        # synthetic freeze frame and xG
        attackers = [(q, ts.lineup[q.id]) for q in ts.on_pitch if q is not p]
        defenders = [(q, opp.lineup[q.id]) for q in opp.on_pitch]
        frame = build_freeze_frame(rng, (x, y), attackers, defenders, assist_type=assist_type, under_pressure=up,
                                   one_on_one=one_on_one, defending_tactics=opp.tactics,
                                   counter_attack=self._is_counter(), set_piece=set_piece)
        shot = {"location": [x, y], "freeze_frame": frame, "body_part": body, "shot_type": shot_type,
                "technique": technique, "under_pressure": up, "first_time": first_time,
                "one_on_one": one_on_one, "aerial_won": aerial_won, "assist_type": assist_type}
        if self.xg_model is not None:
            xg, feats, explanation = self.xg_model.score_shot(shot)
        else:
            feats = shot_features(shot)
            xg = 0.76 if shot_type == "Penalty" else fallback_xg(feats)
            explanation = []

        # finishing skill vs goalkeeper: real finishers beat their xG, great keepers deny it
        gk = opp.gk
        keep = gk.a("keeping") if gk else 35
        if shot_type == "Penalty":
            skill = p.a("penalties") * 0.6 + p.a("composure") * 0.4
            z = logit(cal.OUTCOMES["penalty_conversion"]) + 0.03 * (skill - 77) - 0.025 * (keep - 75)
        else:
            skill = p.a("heading_accuracy") if head else p.a("finishing_skill")
            z = logit(xg) + 0.028 * (skill - 75) - 0.024 * (keep - 75) + 0.15 * ("Clinical finisher" in p.traits)
            if not head and body.split()[0] != p.preferred_foot:
                z -= 0.08 * (3 - p.weak_foot)
        p_goal = sigmoid(z)
        cone = feats["n_defenders_in_cone"] or 0
        if rng.random() < p_goal:
            outcome = "Goal"
        elif shot_type == "Penalty":
            table = cal.OUTCOMES["penalty_non_goal"]
            outcome = rng.choices(list(table), weights=list(table.values()))[0]
        else:
            key = f"{'head' if head else 'foot'}|{band}|{min(cone, 2)}"
            table = cal.OUTCOMES["non_goal"].get(key) or cal.OUTCOMES["non_goal_fallback"]
            outcome = rng.choices(list(table), weights=list(table.values()))[0]

        if head:
            speed = rng.uniform(40, 72)
        elif shot_type == "Penalty":
            speed = rng.uniform(88, 112)
        else:
            speed = clamp(rng.gauss(84, 12) + 0.25 * (p.a("shot_power") - 75) + 0.5 * (feats["distance"] - 16), 40, 135)
        on_target = outcome in ("Goal", "Saved", "Saved to Post")
        spread = 2.6 if on_target else 7
        end = (L, clamp(GOAL_Y + rng.gauss(0, spread), 25, 55))
        details = {
            "xg": round(xg, 3), "xg_explanation": explanation, "assist_type": assist_type,
            "body_part": body, "shot_type": shot_type, "technique": technique, "first_time": first_time,
            "one_on_one": one_on_one, "aerial_won": aerial_won,
            "distance": round(feats["distance"], 1), "angle_deg": round(feats["angle"], 1),
            "nearest_defender_dist": round(feats["nearest_defender_dist"], 2) if feats["nearest_defender_dist"] is not None else None,
            "n_defenders_in_cone": feats["n_defenders_in_cone"],
            "gk_distance_to_goal": round(feats["gk_distance_to_goal"], 2) if feats["gk_distance_to_goal"] is not None else None,
            "big_chance": bool(xg >= 0.3), "speed_kmh": round(speed, 1), "on_target": on_target,
            "counter_attack": self._is_counter(),
            "goalkeeper_id": gk.id if gk else None, "goalkeeper": gk.name if gk else None,
            "key_pass_id": assist["event_id"] if assist else None,
            "assist_player_id": assist["player_id"] if assist else None,
            "assist_player": assist["player"] if assist else None,
            "freeze_frame": frame,
        }
        shot_ev = self._emit("shot", i, p, (x, y), end, outcome, details, up, rng.uniform(0.4, 1.0),
                             related=[assist["event_id"]] if assist else None)
        ts.shot_log.append((self.match_seconds, xg))
        ts.momentum = clamp(ts.momentum + 0.02 + 0.08 * xg, -0.6, 0.6)
        self._shot_aftermath(i, p, x, y, outcome, end, shot_ev, assist, head)

    def _shot_aftermath(self, i, p, x, y, outcome, end, shot_ev, assist, head):
        rng = self.rng
        ts, opp = self.ts[i], self.ts[1 - i]
        gk = opp.gk
        if outcome == "Goal":
            before = ts.score - opp.score
            ts.score += 1
            after = ts.score - opp.score
            state = ("equaliser" if after == 0 else "go_ahead" if after == 1 and before == 0
                     else "extends_lead" if after > 1 else "pulls_one_back")
            ts.momentum = clamp(ts.momentum + 0.04, -0.6, 0.6)
            opp.momentum = clamp(opp.momentum + 0.08, -0.6, 0.6)
            self._emit("goal", i, p, (x, y), details={
                "scorer": p.name, "scorer_id": p.id, "assist": shot_ev["details"]["assist_player"],
                "assist_id": shot_ev["details"]["assist_player_id"], "xg": shot_ev["details"]["xg"],
                "xg_explanation": shot_ev["details"]["xg_explanation"], "assist_type": shot_ev["details"]["assist_type"],
                "body_part": shot_ev["details"]["body_part"], "shot_type": shot_ev["details"]["shot_type"],
                "technique": shot_ev["details"]["technique"], "game_state": state,
                "new_score": {"home": self.ts[0].score, "away": self.ts[1].score},
            }, duration=rng.uniform(45, 80), related=[shot_ev["event_id"]])
            if self.period == 2 or self.minute >= 30:
                self.pending_triggers.append((1 - i, "conceded"))
            self._set_restart("kick_off", 1 - i, (60, 40))
            return
        if outcome in ("Saved", "Saved Off Target", "Saved to Post"):
            if gk:
                self._emit("goalkeeper", 1 - i, gk, (2, mirror(*end)[1]), outcome="save",
                           details={"action": "save", "shot_event_id": shot_ev["event_id"],
                                    "xg_faced": shot_ev["details"]["xg"]}, duration=rng.uniform(1.5, 3))
            r = rng.random()
            if outcome == "Saved Off Target" or r < 0.35:
                self._set_restart("corner", i, (119.5, 0.5 if rng.random() < 0.5 else 79.5))
            elif outcome == "Saved to Post" or r < 0.47:
                self._rebound(i, x, y)
            else:
                self._change_possession(1 - i, 5, 40, gk, "save")
            return
        if outcome == "Blocked":
            ox, oy = mirror(x + 2, y)
            blk = self._nearest(1 - i, ox, oy)
            self._emit("block", 1 - i, blk, (ox, oy), details={"shot_event_id": shot_ev["event_id"]},
                       duration=rng.uniform(0.5, 1.5))
            r = rng.random()
            if r < 0.38:
                self._set_restart("corner", i, (119.5, 0.5 if y < 40 else 79.5))
            elif r < 0.62:
                self._rebound(i, x - rng.uniform(4, 10), y)
            else:
                self._change_possession(1 - i, ox - 4, oy, blk, "block")
            return
        if outcome == "Post":
            if rng.random() < 0.3:
                self._rebound(i, rng.uniform(106, 114), 40 + rng.gauss(0, 6))
            elif gk:
                self._emit("ball_recovery", 1 - i, gk, (6, 40), details={"after": "hit_woodwork"},
                           duration=rng.uniform(1.5, 3))
                self._change_possession(1 - i, 6, 40, gk, "rebound")
            return
        self._set_restart("goal_kick", 1 - i, (6, 40))

    def _rebound(self, i, x, y):
        """Loose ball after a save / block: a teammate may pounce for a second shot."""
        rng = self.rng
        x, y = clamp(x, 85, 115), clamp(y, 15, 65)
        q = self._nearest(i, x, y)
        self._emit("ball_recovery", i, q, (x, y), details={"after": "rebound"}, duration=rng.uniform(0.5, 1.5))
        self.ball, self.carrier = (x, y), q
        self.assist_ev = None
        if rng.random() < 0.33:
            self._take_shot(i, q, x, y, rng.random() < 0.5, assist_type="no_assist")

    # ------------------------------------------------------------ set pieces
    def _foul(self, fouler_team, fouler, victim_team, victim, x, y):
        """x, y in the victim (attacking) team frame."""
        ox, oy = mirror(x, y)
        in_box = x > 102 and abs(y - GOAL_Y) < 22
        card = None
        r = self.rng.random()
        ts = self.ts[fouler_team]
        aggression = fouler.a("aggression")
        if r < 0.004 + (0.01 if in_box else 0):
            card = "red"
        elif r < (0.10 + (0.05 if x > 80 else 0)) * (0.7 + aggression / 160):
            card = "yellow"
            ts.yellow[fouler.id] = ts.yellow.get(fouler.id, 0) + 1
            if ts.yellow[fouler.id] == 2:
                card = "second_yellow"
        self._emit("foul", fouler_team, fouler, (ox, oy), details={
            "on_player_id": victim.id, "on_player": victim.name, "in_box": in_box, "card": card,
        }, duration=self.rng.uniform(6, 14))
        if card:
            self._emit("card", fouler_team, fouler, (ox, oy), outcome=card, details={"card": card, "reason": "foul"},
                       duration=self.rng.uniform(15, 30))
            if card in ("red", "second_yellow") and fouler in ts.on_pitch:
                self._send_off(fouler_team, fouler)
        if in_box:
            self._set_restart("penalty", victim_team, (108, 40))
        else:
            self._set_restart("free_kick", victim_team, (x, y))
        self.carrier = victim

    def _send_off(self, k, player):
        ts = self.ts[k]
        was_gk = ts.lineup.get(player.id) == "GK"
        ts.on_pitch.remove(player)
        ts.lineup.pop(player.id, None)
        ts.sent_off.append(player.id)
        if was_gk:
            if not self._bring_on_keeper(k):
                stand_in = max(ts.on_pitch, key=lambda p: p.a("keeping"))
                ts.lineup[stand_in.id] = "GK"
        self.pending_triggers.append((k, "red_card_own"))
        self.pending_triggers.append((1 - k, "red_card_opponent"))

    def _bring_on_keeper(self, k) -> bool:
        ts = self.ts[k]
        gks = [p for p in ts.bench if p.group == "GK"]
        outfield = [p for p in ts.on_pitch if ts.lineup[p.id] != "GK"]
        if not gks or ts.subs_used >= 5 or not outfield:
            return False
        off = min(outfield, key=lambda p: (POSITION_GROUP[ts.lineup[p.id]] not in ATTACKING_GROUPS, p.overall))
        on = gks[0]
        ts.bench.remove(on)
        ts.on_pitch[ts.on_pitch.index(off)] = on
        del ts.lineup[off.id]
        ts.lineup[on.id] = "GK"
        ts.subs_used += 1
        ts.used_players.add(on.id)
        self._emit("substitution", k, off, details={
            "player_off": off.name, "player_off_id": off.id, "player_on": on.name, "player_on_id": on.id,
            "slot": "GK", "position": "Goalkeeper", "reason": "goalkeeper_sent_off",
            "subs_used": ts.subs_used, "windows_used": ts.sub_windows_used}, duration=30)
        return True

    def _set_restart(self, kind, team_idx, loc):
        self.restart = (kind, team_idx, loc)

    def _do_restart(self):
        kind, team_idx = self.restart[0], self.restart[1]
        loc = self.restart[2] if len(self.restart) > 2 else (60, 40)
        self.restart = None
        edge = self._edge(team_idx)
        x, y = loc
        if team_idx != self.poss or kind == "kick_off":
            self.poss = team_idx
            self.possession_id += 1
            self.chain = 0
            self.poss_start = (x, self.match_seconds)
        self.assist_ev = None
        ts = self.ts[team_idx]
        if kind == "kick_off":
            self.ball = (60, 40)
            p = next((q for q in ts.on_pitch if ts.lineup[q.id] in FORWARD_SLOTS + ("CAM",)), ts.on_pitch[-1])
            q = self._nearest(team_idx, 52, 40, exclude=(p.id,))
            self._emit("kick_off", team_idx, p, (60, 40), (52, 40), "complete",
                       {"recipient_id": q.id, "recipient": q.name}, duration=self.rng.uniform(1, 2))
            self.ball, self.carrier = (52, 40), q
            return
        delay = {"throw_in": (11, 24), "goal_kick": (18, 32), "corner": (24, 42),
                 "free_kick": (20, 40), "penalty": (45, 80)}[kind]
        self._advance(self.rng.uniform(*delay))
        takers = ts.team.set_piece_takers
        on = {p.id: p for p in ts.on_pitch}
        outfield = [p for p in ts.on_pitch if ts.lineup[p.id] != "GK"]
        if kind == "penalty":
            taker = on.get(takers["penalties"]) or max(outfield, key=lambda z: z.a("penalties") + z.a("composure"))
            self._take_shot(team_idx, taker, 108, 40, False, assist_type="no_assist", shot_type="Penalty")
            return
        if kind == "goal_kick":
            gk = ts.gk or ts.on_pitch[0]
            short = self.rng.random() < (0.75 - 0.5 * ts.tactics["directness"])
            self.ball, self.carrier = (6, 40), gk
            self._a_pass(team_idx, gk, 6, 40, False, edge, long=not short)
            return
        if kind == "throw_in":
            p = self._nearest(team_idx, x, y)
            q, (qx, qy) = self._pick_target(team_idx, p, x, y)
            qx, qy = clamp(qx, x - 17, x + 17), clamp(qy, 2, 78)
            ok = self.rng.random() < 0.82
            ev = self._emit("pass", team_idx, p, (x, y), (qx, qy), "complete" if ok else "incomplete",
                            self._pass_details(x, y, qx, qy, q, "throw_in", 2.0), duration=self.rng.uniform(1, 2))
            if ok:
                self._received(ev, q, (qx, qy))
            else:
                ox, oy = mirror(qx, qy)
                r = self._nearest(1 - team_idx, ox, oy)
                self._change_possession(1 - team_idx, ox, oy, r, "throw_in_lost")
            return
        if kind == "corner":
            key = "corners_left" if y < 40 else "corners_right"
            taker = on.get(takers[key]) or max(outfield, key=lambda z: z.a("crossing") + self.rng.uniform(0, 10))
            self.ball, self.carrier = (x, y), taker
            if self.rng.random() < 0.18:
                self._a_pass(team_idx, taker, x, y, False, edge)
            else:
                self._a_cross(team_idx, taker, x, y, False, edge, set_piece="corner")
            return
        if kind == "free_kick":
            taker = on.get(takers["free_kicks"]) or max(outfield, key=lambda z: z.a("fk_accuracy") + self.rng.uniform(0, 10))
            self.ball, self.carrier = (x, y), taker
            dist = shot_distance(x, y)
            if dist < 34 and x > 86 and self.rng.random() < 0.42:
                self._take_shot(team_idx, taker, x, y, False, assist_type="no_assist", shot_type="Free Kick",
                                set_piece=True)
            elif x > 80 and self.rng.random() < 0.55:
                self._a_cross(team_idx, taker, x, y, False, edge, set_piece="free_kick")
            else:
                self._a_pass(team_idx, taker, x, y, False, edge)
            return


def simulate_match(home: Team, away: Team, seed: int | None = None, **kw) -> list[dict]:
    return MatchSimulator(home, away, seed=seed, **kw).run()
