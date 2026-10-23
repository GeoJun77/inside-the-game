"""Fictional league: clubs, managers, tactics and players with FIFA-style attributes.

Everything is invented (clubs, venues, people), so the project never ships
third-party trademarks or real players. The *structure* follows the Premier League:
20 clubs, 25-player squads, matchday squads of 11 starters + 9 substitutes, and
formation frequencies calibrated on StatsBomb's Premier League 2015/16 data.

Coordinates follow the StatsBomb convention: pitch 120 x 80, the team attacks
towards x = 120, y = 0 is the left touchline from the attacker's point of view.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

from .formations import FORMATIONS, FORMATION_WEIGHTS, POSITION_GROUP, POSITION_XY
from .names import COUNTRIES, MANAGER_FIRST, MANAGER_LAST, NATIONALITIES

LEAGUE_NAME = "Albion Football League"
PLAYER_OF_THE_SEASON_AWARD = "The Geoffroy Award"

# --------------------------------------------------------------------------- clubs
# (club name, short code, stadium, city, primary colour, secondary colour, tactical identity)
CLUBS = [
    ("Harbourne Rovers", "HAR", "Quayside Park", "Harbourne", "#1f4e9c", "#ffffff", "tiki_taka"),
    ("Ashcombe Athletic", "ASH", "The Foundry Ground", "Ashcombe", "#b3202c", "#f2c230", "gegenpress"),
    ("Kestrel Vale", "KES", "Moorgate Stadium", "Kestrel", "#2f7d4f", "#ffffff", "low_block_counter"),
    ("Northbridge Albion", "NBA", "Lantern Lane", "Northbridge", "#111111", "#e5e5e5", "vertical_possession"),
    ("Saltmarsh Town", "SAL", "The Estuary", "Saltmarsh", "#f08a24", "#1b1b1b", "wing_play"),
    ("Westholm Wanderers", "WES", "Copperfield Road", "Westholm", "#6a2c91", "#ffd200", "balanced"),
    ("Ironvale Forge", "IRV", "Anvil Park", "Ironvale", "#5b6770", "#d7262e", "gegenpress"),
    ("Brightwater FC", "BRW", "Lido Stadium", "Brightwater", "#00a3c4", "#ffffff", "tiki_taka"),
    ("Thornbury Swifts", "THS", "Hawthorn Fields", "Thornbury", "#c8102e", "#000000", "direct"),
    ("Millhaven Borough", "MIL", "Waterwheel Ground", "Millhaven", "#0c2340", "#c4a35a", "balanced"),
    ("Redcliffe Mariners", "RED", "Lighthouse Stadium", "Redcliffe", "#a6192e", "#00205b", "wing_play"),
    ("Oakhurst Rangers", "OAK", "Acorn Park", "Oakhurst", "#3c6e3c", "#f3e600", "low_block_counter"),
    ("Greywater Celtic", "GRY", "Fenwick Road", "Greywater", "#7a7a7a", "#2e8b57", "direct"),
    ("Pennick Harriers", "PEN", "Highmoor", "Pennick", "#e03a3e", "#ffffff", "balanced"),
    ("Coldstream Victoria", "COL", "Frostgate Arena", "Coldstream", "#86c5e8", "#0b3d91", "vertical_possession"),
    ("Linden Park Rangers", "LIN", "The Arboretum", "Linden", "#004d40", "#ffb300", "wing_play"),
    ("Falconridge FC", "FAL", "Eyrie Stadium", "Falconridge", "#4b0082", "#c0c0c0", "low_block_counter"),
    ("Duncaster Steelmen", "DUN", "Blastfurnace Lane", "Duncaster", "#2b2b2b", "#ff6f00", "direct"),
    ("Whitlock Harbour", "WHI", "Pier Road", "Whitlock", "#ffffff", "#003da5", "balanced"),
    ("Embersby Phoenix", "EMB", "Cinder Park", "Embersby", "#d84315", "#ffd54f", "low_block_counter"),
]

# ------------------------------------------------------------------------ tactics
# Team instructions inspired by the tactics screen of football video games.
# Categorical choices are what a commentator talks about; the numeric sliders
# (0-100) are what the match engine actually uses.
BUILD_UP = ("slow", "balanced", "fast", "long_ball")
CHANCE_CREATION = ("possession", "balanced", "direct_passing", "forward_runs", "wings")
DEFENSIVE_STYLE = ("drop_back", "balanced", "pressure_heavy_touch", "counter_press", "constant_pressure")

IDENTITIES = {
    "tiki_taka": dict(
        label="Tiki-taka", build_up="slow", chance_creation="possession", defensive_style="counter_press",
        defensive_line=72, defensive_width=45, attacking_width=55, players_in_box=4, tempo=45),
    "gegenpress": dict(
        label="Gegenpressing", build_up="fast", chance_creation="direct_passing", defensive_style="constant_pressure",
        defensive_line=75, defensive_width=40, attacking_width=50, players_in_box=5, tempo=80),
    "low_block_counter": dict(
        label="Low block and counter", build_up="fast", chance_creation="forward_runs", defensive_style="drop_back",
        defensive_line=30, defensive_width=35, attacking_width=45, players_in_box=4, tempo=75),
    "vertical_possession": dict(
        label="Vertical possession", build_up="balanced", chance_creation="direct_passing", defensive_style="pressure_heavy_touch",
        defensive_line=62, defensive_width=45, attacking_width=55, players_in_box=5, tempo=65),
    "wing_play": dict(
        label="Wing play", build_up="balanced", chance_creation="wings", defensive_style="balanced",
        defensive_line=50, defensive_width=55, attacking_width=80, players_in_box=6, tempo=60),
    "direct": dict(
        label="Direct football", build_up="long_ball", chance_creation="wings", defensive_style="balanced",
        defensive_line=42, defensive_width=50, attacking_width=65, players_in_box=6, tempo=60),
    "balanced": dict(
        label="Balanced", build_up="balanced", chance_creation="balanced", defensive_style="balanced",
        defensive_line=50, defensive_width=50, attacking_width=55, players_in_box=5, tempo=60),
}


def engine_params(t: dict) -> dict:
    """Translate team instructions into the 0-1 parameters used by the match engine."""
    directness = {"slow": 0.36, "balanced": 0.5, "fast": 0.6, "long_ball": 0.72}[t["build_up"]]
    if t["chance_creation"] == "possession":
        directness -= 0.04
    if t["chance_creation"] in ("direct_passing", "forward_runs"):
        directness += 0.05
    pressing = {"drop_back": 0.25, "balanced": 0.5, "pressure_heavy_touch": 0.62,
                "counter_press": 0.72, "constant_pressure": 0.9}[t["defensive_style"]]
    crossing = 0.3 + 0.5 * (t["attacking_width"] / 100) + (0.2 if t["chance_creation"] == "wings" else 0)
    through_balls = 0.4 + (0.2 if t["chance_creation"] in ("direct_passing", "forward_runs") else 0)
    return {
        "directness": round(min(1, max(0, directness)), 2),
        "pressing": pressing,
        "counter_press": 1.0 if t["defensive_style"] == "counter_press" else 0.0,
        "tempo": t["tempo"] / 100,
        "width": t["attacking_width"] / 100,
        "crossing": round(min(1, crossing), 2),
        "through_balls": round(min(1, through_balls), 2),
        "line_height": t["defensive_line"] / 100,
        "compactness": 1 - t["defensive_width"] / 100,
        "box_presence": t["players_in_box"] / 8,
    }


# ----------------------------------------------------------------------- players
ATTRIBUTES = {
    "pace": ("acceleration", "sprint_speed"),
    "shooting": ("finishing", "shot_power", "long_shots", "positioning", "volleys", "penalties"),
    "passing": ("vision", "crossing", "short_passing", "long_passing", "fk_accuracy", "curve"),
    "dribbling": ("agility", "balance", "ball_control", "dribbling", "reactions", "composure"),
    "defending": ("interceptions", "heading_accuracy", "def_awareness", "standing_tackle", "sliding_tackle"),
    "physical": ("jumping", "stamina", "strength", "aggression"),
    "goalkeeping": ("gk_diving", "gk_handling", "gk_kicking", "gk_positioning", "gk_reflexes"),
}
ALL_ATTRS = [a for group in ATTRIBUTES.values() for a in group]

# Attribute emphasis per position group: offset (in rating points) added to the
# player's level before rescaling. Unlisted attributes get the group default.
POSITION_PROFILE = {
    "GK": dict(_default=-35, gk_diving=4, gk_handling=4, gk_kicking=0, gk_positioning=4, gk_reflexes=5,
               reactions=0, composure=-5, jumping=-10, strength=-10, short_passing=-22, long_passing=-18),
    "CB": dict(_default=-12, interceptions=2, heading_accuracy=4, def_awareness=4, standing_tackle=4,
               sliding_tackle=2, jumping=2, strength=4, aggression=2, short_passing=-6, composure=-4,
               reactions=-4, stamina=-6, finishing=-38, volleys=-38, long_shots=-30, dribbling=-24,
               agility=-20, crossing=-30, curve=-30, fk_accuracy=-34, positioning=-36, penalties=-25,
               gk_diving=-70, gk_handling=-70, gk_kicking=-70, gk_positioning=-70, gk_reflexes=-70),
    "FB": dict(_default=-8, acceleration=2, sprint_speed=2, stamina=2, crossing=-4, standing_tackle=0,
               sliding_tackle=0, interceptions=-2, def_awareness=-3, short_passing=-4, finishing=-30,
               volleys=-30, long_shots=-24, positioning=-22, heading_accuracy=-12, penalties=-25,
               gk_diving=-70, gk_handling=-70, gk_kicking=-70, gk_positioning=-70, gk_reflexes=-70),
    "DM": dict(_default=-8, interceptions=2, def_awareness=0, standing_tackle=0, short_passing=0,
               long_passing=-2, stamina=0, strength=-2, aggression=-2, composure=-2, vision=-4,
               finishing=-25, volleys=-26, positioning=-22, crossing=-18, dribbling=-12, agility=-12,
               acceleration=-14, sprint_speed=-14, gk_diving=-70, gk_handling=-70, gk_kicking=-70,
               gk_positioning=-70, gk_reflexes=-70),
    "CM": dict(_default=-6, short_passing=2, long_passing=0, vision=0, ball_control=0, stamina=0,
               reactions=0, composure=0, dribbling=-4, finishing=-14, positioning=-10, standing_tackle=-14,
               sliding_tackle=-18, interceptions=-12, def_awareness=-14, heading_accuracy=-18,
               gk_diving=-70, gk_handling=-70, gk_kicking=-70, gk_positioning=-70, gk_reflexes=-70),
    "AM": dict(_default=-6, vision=2, short_passing=2, ball_control=2, dribbling=2, agility=0,
               composure=0, positioning=-2, finishing=-4, long_shots=-2, curve=-2, standing_tackle=-36,
               sliding_tackle=-40, interceptions=-32, def_awareness=-34, heading_accuracy=-22,
               strength=-18, jumping=-18, gk_diving=-70, gk_handling=-70, gk_kicking=-70,
               gk_positioning=-70, gk_reflexes=-70),
    "W": dict(_default=-6, acceleration=4, sprint_speed=4, dribbling=2, agility=2, ball_control=0,
              crossing=0, finishing=-6, positioning=-4, standing_tackle=-40, sliding_tackle=-44,
              interceptions=-36, def_awareness=-38, heading_accuracy=-24, strength=-18,
              gk_diving=-70, gk_handling=-70, gk_kicking=-70, gk_positioning=-70, gk_reflexes=-70),
    "ST": dict(_default=-6, finishing=4, positioning=4, shot_power=2, reactions=2, composure=0,
               heading_accuracy=0, volleys=0, ball_control=-2, standing_tackle=-46, sliding_tackle=-50,
               interceptions=-40, def_awareness=-44, vision=-12, crossing=-22, long_passing=-26,
               gk_diving=-70, gk_handling=-70, gk_kicking=-70, gk_positioning=-70, gk_reflexes=-70),
}

# Weights used to compute the overall rating from attributes, per position group.
OVERALL_WEIGHTS = {
    "GK": dict(gk_diving=21, gk_handling=21, gk_kicking=5, gk_positioning=21, gk_reflexes=21, reactions=11),
    "CB": dict(def_awareness=17, standing_tackle=17, sliding_tackle=12, interceptions=12, heading_accuracy=10,
               strength=10, jumping=4, aggression=7, short_passing=5, composure=6),
    "FB": dict(sprint_speed=7, acceleration=5, stamina=8, crossing=9, def_awareness=12, standing_tackle=11,
               sliding_tackle=11, interceptions=12, short_passing=7, ball_control=7, reactions=8, dribbling=3),
    "DM": dict(short_passing=14, long_passing=10, interceptions=14, def_awareness=10, standing_tackle=12,
               ball_control=10, vision=4, reactions=7, stamina=6, strength=5, aggression=4, composure=4),
    "CM": dict(short_passing=17, long_passing=13, vision=13, ball_control=14, dribbling=7, reactions=8,
               stamina=6, interceptions=5, positioning=6, long_shots=4, composure=7),
    "AM": dict(vision=14, short_passing=16, ball_control=15, dribbling=13, agility=4, positioning=9,
               finishing=7, shot_power=4, long_shots=5, reactions=7, composure=6),
    "W": dict(acceleration=7, sprint_speed=6, agility=3, dribbling=16, ball_control=14, crossing=9,
              short_passing=9, vision=6, finishing=10, positioning=9, long_shots=4, reactions=7),
    "ST": dict(finishing=18, positioning=13, heading_accuracy=10, shot_power=10, reactions=8, ball_control=10,
               dribbling=7, acceleration=4, sprint_speed=5, volleys=2, strength=5, composure=8),
}

# Roles: a short scouting label that changes the attribute emphasis and the
# player's tendencies in the match engine. Agents use them in narratives.
ROLES = {
    "GK": {"Shot stopper": dict(gk_reflexes=5, gk_diving=4, gk_kicking=-4),
           "Sweeper keeper": dict(gk_kicking=6, sprint_speed=10, acceleration=10, short_passing=10, gk_positioning=2)},
    "CB": {"Stopper": dict(standing_tackle=4, strength=5, aggression=6, heading_accuracy=3, short_passing=-4),
           "Ball-playing defender": dict(short_passing=10, long_passing=12, composure=8, vision=8, aggression=-3),
           "Aerial dominator": dict(heading_accuracy=7, jumping=8, strength=4, acceleration=-5)},
    "FB": {"Attacking full-back": dict(crossing=8, stamina=6, sprint_speed=4, dribbling=6, def_awareness=-4),
           "Defensive full-back": dict(def_awareness=6, standing_tackle=5, sliding_tackle=5, crossing=-6),
           "Inverted full-back": dict(short_passing=8, vision=8, composure=5, crossing=-4)},
    "DM": {"Ball-winner": dict(standing_tackle=7, sliding_tackle=7, interceptions=6, aggression=8, vision=-5),
           "Deep-lying playmaker": dict(long_passing=10, short_passing=8, vision=10, composure=6, standing_tackle=-6),
           "Anchor": dict(def_awareness=8, strength=6, interceptions=5, dribbling=-6)},
    "CM": {"Box-to-box": dict(stamina=10, shot_power=6, standing_tackle=8, interceptions=6, vision=-3),
           "Playmaker": dict(vision=8, short_passing=6, long_passing=6, curve=6, standing_tackle=-6),
           "Mezzala": dict(dribbling=8, agility=6, finishing=8, positioning=8, def_awareness=-6)},
    "AM": {"Advanced playmaker": dict(vision=8, short_passing=6, curve=6, fk_accuracy=8),
           "Shadow striker": dict(finishing=10, positioning=10, volleys=6, vision=-4)},
    "W": {"Winger": dict(crossing=10, sprint_speed=6, dribbling=4, finishing=-4),
          "Inside forward": dict(finishing=10, long_shots=8, curve=6, positioning=6, crossing=-6)},
    "ST": {"Poacher": dict(finishing=8, positioning=10, reactions=6, short_passing=-6, vision=-6),
           "Target man": dict(heading_accuracy=12, strength=12, jumping=10, acceleration=-10, sprint_speed=-8,
                              agility=-10),
           "Complete forward": dict(short_passing=6, ball_control=6, long_shots=6, shot_power=6),
           "Pressing forward": dict(stamina=12, aggression=12, standing_tackle=14, interceptions=12)},
}

TRAITS_BY_ROLE = {
    "Shot stopper": ["Rushes out of goal"], "Sweeper keeper": ["Comes for crosses", "Long throw-in"],
    "Stopper": ["Power header", "Leadership"], "Ball-playing defender": ["Long passer", "Leadership"],
    "Aerial dominator": ["Power header"], "Attacking full-back": ["Early crosser", "Speed dribbler"],
    "Defensive full-back": ["Solid tackler"], "Inverted full-back": ["Playmaker"],
    "Ball-winner": ["Solid tackler", "Long shot taker"], "Deep-lying playmaker": ["Long passer", "Playmaker"],
    "Anchor": ["Leadership"], "Box-to-box": ["Long shot taker", "Power shot"],
    "Playmaker": ["Playmaker", "Finesse shot"], "Mezzala": ["Finesse shot", "Speed dribbler"],
    "Advanced playmaker": ["Playmaker", "Finesse shot", "Set-piece specialist"],
    "Shadow striker": ["Clinical finisher", "Finesse shot"], "Winger": ["Early crosser", "Speed dribbler"],
    "Inside forward": ["Finesse shot", "Speed dribbler", "Long shot taker"],
    "Poacher": ["Clinical finisher"], "Target man": ["Power header", "Target forward"],
    "Complete forward": ["Clinical finisher", "Power shot", "Long shot taker"],
    "Pressing forward": ["Engine"],
}

WORK_RATES = {
    "GK": ("Medium", "Medium"), "CB": ("Low", "High"), "FB": ("High", "Medium"), "DM": ("Medium", "High"),
    "CM": ("High", "High"), "AM": ("High", "Low"), "W": ("High", "Medium"), "ST": ("High", "Low"),
}

# Squad template (25 players, like a Premier League squad list) by natural position.
SQUAD_TEMPLATE = (["GK"] * 3 + ["CB"] * 4 + ["RB"] * 2 + ["LB"] * 2 + ["CDM"] * 2 + ["CM"] * 3
                  + ["CAM"] * 2 + ["RW"] * 2 + ["LW"] * 2 + ["ST"] * 3)

# Classic shirt numbers for the first-choice player of each natural position.
CLASSIC_NUMBERS = {"GK": [1, 13], "RB": [2], "LB": [3], "CB": [5, 6, 4], "CDM": [4, 16],
                   "CM": [8, 14], "CAM": [10], "RW": [7], "LW": [11], "ST": [9, 19]}

HEIGHT_CM = {"GK": (191, 4), "CB": (188, 4), "FB": (178, 5), "DM": (182, 5), "CM": (179, 5),
             "AM": (176, 5), "W": (175, 5), "ST": (183, 6)}


@dataclass
class Player:
    id: str
    name: str
    short_name: str
    number: int
    position: str              # natural position (StatsBomb-style short code, e.g. "RB", "CAM")
    role: str
    nationality: str
    age: int
    height_cm: int
    weight_kg: int
    preferred_foot: str        # "Right" | "Left"
    weak_foot: int             # 1..5 stars
    skill_moves: int           # 1..5 stars
    work_rate: tuple
    traits: list
    attrs: dict
    overall: int = 0
    face_stats: dict = field(default_factory=dict)

    @property
    def group(self) -> str:
        return POSITION_GROUP[self.position]

    def a(self, key: str) -> float:
        """Attribute lookup with a few composite skills used by the match engine."""
        at = self.attrs
        if key in at:
            return at[key]
        composite = {
            "passing": ("short_passing", "long_passing", "vision"),
            "finishing_skill": ("finishing", "composure", "positioning"),
            "pace_skill": ("acceleration", "sprint_speed"),
            "tackling": ("standing_tackle", "sliding_tackle", "def_awareness"),
            "keeping": ("gk_diving", "gk_handling", "gk_positioning", "gk_reflexes"),
            "heading": ("heading_accuracy", "jumping", "strength"),
            "aerial": ("heading_accuracy", "jumping"),
        }.get(key)
        if composite:
            return sum(at[k] for k in composite) / len(composite)
        return 60.0

    def position_rating(self, slot_position: str) -> float:
        """How good the player is when fielded at `slot_position` (familiarity penalty)."""
        target = POSITION_GROUP[slot_position]
        rating = overall_for_group(self.attrs, target)
        if slot_position == self.position:
            return rating
        side_penalty = 0.0
        s_side, n_side = _side(slot_position), _side(self.position)
        if s_side != "C" and n_side != "C" and s_side != n_side:
            # wrong flank: a left back at right back, a right winger on the left
            side_penalty = 4.0 if target in ("FB", "W") else 1.0
        if target == self.group:
            return rating - 1 - side_penalty
        familiar = {("FB", "W"), ("W", "FB"), ("CM", "DM"), ("DM", "CM"), ("CM", "AM"), ("AM", "CM"),
                    ("AM", "W"), ("W", "AM"), ("W", "ST"), ("ST", "W"), ("AM", "ST"), ("ST", "AM"),
                    ("DM", "CB"), ("CB", "DM"), ("FB", "CB")}
        if (self.group, target) in familiar:
            return rating - 5 - side_penalty
        return rating - 15

    def to_dict(self) -> dict:
        d = asdict(self)
        d["work_rate"] = list(self.work_rate)
        return d


@dataclass
class Team:
    id: str
    name: str
    code: str
    stadium: str
    city: str
    colors: tuple
    manager: str
    identity: str
    instructions: dict          # what the manager set (categorical + 0-100 sliders)
    formation: str              # preferred formation (StatsBomb code, e.g. "4231")
    alt_formations: list        # attacking / defensive alternatives used in-game
    level: float                # target overall of the first XI
    players: list = field(default_factory=list)
    captain_id: str = ""
    set_piece_takers: dict = field(default_factory=dict)

    @property
    def tactics(self) -> dict:
        return engine_params(self.instructions)

    def player(self, pid: str) -> Player:
        return next(p for p in self.players if p.id == pid)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "code": self.code, "stadium": self.stadium, "city": self.city,
            "colors": list(self.colors), "manager": self.manager, "identity": IDENTITIES[self.identity]["label"],
            "instructions": self.instructions, "formation": self.formation, "alt_formations": self.alt_formations,
            "level": round(self.level, 1), "captain_id": self.captain_id, "set_piece_takers": self.set_piece_takers,
            "players": [p.to_dict() for p in self.players],
        }


def _side(code: str) -> str:
    if code in ("GK", "CB", "CDM", "CM", "CAM", "ST", "SS"):
        return "C"
    return "R" if code.startswith("R") else "L" if code.startswith("L") else "C"


# ---------------------------------------------------------------- rating helpers
def overall_for_group(attrs: dict, group: str) -> float:
    w = OVERALL_WEIGHTS[group]
    return sum(attrs[k] * v for k, v in w.items()) / sum(w.values())


def face_stats(attrs: dict) -> dict:
    """The six headline numbers shown on a player card."""
    a = attrs
    return {
        "PAC": round(0.45 * a["acceleration"] + 0.55 * a["sprint_speed"]),
        "SHO": round(0.45 * a["finishing"] + 0.2 * a["shot_power"] + 0.2 * a["long_shots"]
                     + 0.05 * a["volleys"] + 0.05 * a["penalties"] + 0.05 * a["positioning"]),
        "PAS": round(0.35 * a["short_passing"] + 0.2 * a["long_passing"] + 0.2 * a["vision"]
                     + 0.15 * a["crossing"] + 0.05 * a["curve"] + 0.05 * a["fk_accuracy"]),
        "DRI": round(0.5 * a["dribbling"] + 0.35 * a["ball_control"] + 0.1 * a["agility"] + 0.05 * a["balance"]),
        "DEF": round(0.3 * a["def_awareness"] + 0.3 * a["standing_tackle"] + 0.2 * a["interceptions"]
                     + 0.1 * a["sliding_tackle"] + 0.1 * a["heading_accuracy"]),
        "PHY": round(0.5 * a["strength"] + 0.25 * a["stamina"] + 0.2 * a["aggression"] + 0.05 * a["jumping"]),
    }


def _clamp(v: float, lo: int = 20, hi: int = 99) -> int:
    return int(max(lo, min(hi, round(v))))


# ------------------------------------------------------------- player generation
def _pick_nationality(rng: random.Random) -> str:
    names = list(NATIONALITIES)
    return rng.choices(names, weights=[NATIONALITIES[n][0] for n in names])[0]


def _unique_name(rng, pool, used, club_surnames):
    """A name unique in the league, with a surname unique in the club (clear commentary)."""
    _, firsts, lasts = NATIONALITIES[pool]
    for _ in range(400):
        first, last = rng.choice(firsts), rng.choice(lasts)
        if (first, last) not in used and last not in club_surnames:
            used.add((first, last))
            club_surnames.add(last)
            return first, last
    raise RuntimeError("name pool exhausted")


def make_player(rng: random.Random, club_code: str, idx: int, position: str, level: float,
                used_names: set, club_surnames: set | None = None) -> Player:
    group = POSITION_GROUP[position]
    pool = _pick_nationality(rng)
    first, last = _unique_name(rng, pool, used_names, club_surnames if club_surnames is not None else set())
    nationality = rng.choice(COUNTRIES[pool])
    role = rng.choice(list(ROLES[group]))

    # attribute generation: level + position emphasis + role emphasis + noise, then
    # shift so the position overall hits the target level exactly.
    profile = POSITION_PROFILE[group]
    role_bonus = ROLES[group][role]
    attrs = {}
    for k in ALL_ATTRS:
        base = level + profile.get(k, profile["_default"]) + role_bonus.get(k, 0) + rng.gauss(0, 4.5)
        attrs[k] = base
    target = level
    for _ in range(3):
        diff = target - overall_for_group({k: _clamp(v) for k, v in attrs.items()}, group)
        for k in OVERALL_WEIGHTS[group]:
            attrs[k] += diff
    attrs = {k: _clamp(v, 15 if k.startswith("gk_") else 20) for k, v in attrs.items()}

    side = "Left" if position in ("LB", "LW", "LWB", "LM") else ("Right" if position in ("RB", "RW", "RWB", "RM") else "")
    if group == "W" and role == "Inside forward":
        left_prob = 0.85 if side == "Right" else 0.15      # inverted wingers cut inside on their strong foot
    elif side == "Left":
        left_prob = 0.75
    elif side == "Right":
        left_prob = 0.08
    else:
        left_prob = 0.2
    foot = "Left" if rng.random() < left_prob else "Right"
    weak_foot = rng.choices([1, 2, 3, 4, 5], weights=[2, 18, 50, 24, 6])[0]
    skill_base = {"GK": 1, "CB": 2, "FB": 2.6, "DM": 2.4, "CM": 3, "AM": 3.6, "W": 3.9, "ST": 3.3}[group]
    skill_moves = int(max(1, min(5, round(skill_base + rng.gauss(0, 0.6) + (level - 75) / 12))))

    mu, sd = HEIGHT_CM[group]
    if role == "Target man":
        mu += 6
    height = int(round(rng.gauss(mu, sd)))
    weight = int(round(height - 105 + rng.gauss(0, 4) + attrs["strength"] / 20))
    attrs["jumping"] = _clamp(attrs["jumping"] + (height - 182) * 0.6)
    attrs["heading_accuracy"] = _clamp(attrs["heading_accuracy"] + (height - 182) * 0.3)
    age = int(max(17, min(36, round(rng.gauss(28 if group == "GK" else 26, 3.8)))))

    traits = [t for t in TRAITS_BY_ROLE.get(role, []) if rng.random() < 0.55]
    if attrs["fk_accuracy"] > 80 and "Set-piece specialist" not in traits:
        traits.append("Set-piece specialist")
    if weak_foot == 5:
        traits.append("Two-footed")

    p = Player(
        id=f"{club_code}-{idx:02d}", name=f"{first} {last}", short_name=last, number=0, position=position,
        role=role, nationality=nationality, age=age, height_cm=height, weight_kg=weight,
        preferred_foot=foot, weak_foot=weak_foot, skill_moves=skill_moves, work_rate=WORK_RATES[group],
        traits=traits, attrs=attrs,
    )
    p.overall = int(round(overall_for_group(attrs, group)))
    p.face_stats = face_stats(attrs)
    return p


def _assign_numbers(rng, players):
    taken = set()
    by_pos: dict = {}
    for p in sorted(players, key=lambda q: -q.overall):
        by_pos.setdefault(p.position, []).append(p)
    for pos, plist in by_pos.items():
        for p, num in zip(plist, CLASSIC_NUMBERS.get(pos, [])):
            if num not in taken:
                p.number = num
                taken.add(num)
    free = [n for n in range(2, 46) if n not in taken]
    rng.shuffle(free)
    for p in players:
        if p.number == 0:
            p.number = free.pop()


def build_league(seed: int = 2026) -> list[Team]:
    """Deterministically build the 20-club fictional league."""
    rng = random.Random(seed)
    used_names: set = set()
    teams = []
    club_formations = _allocate_formations(len(CLUBS), rng)
    for i, (name, code, stadium, city, c1, c2, identity) in enumerate(CLUBS):
        # Premier League-like spread: a few elite clubs, a long middle, a few strugglers.
        level = 81.5 - i * 0.42 + rng.gauss(0, 0.8)
        ident = IDENTITIES[identity]
        instructions = {k: v for k, v in ident.items() if k != "label"}
        for k in ("defensive_line", "defensive_width", "attacking_width", "tempo"):
            instructions[k] = int(max(10, min(95, instructions[k] + rng.gauss(0, 5))))
        formation = club_formations[i]
        team = Team(
            id=code, name=name, code=code, stadium=stadium, city=city, colors=(c1, c2),
            manager=f"{rng.choice(MANAGER_FIRST)} {rng.choice(MANAGER_LAST)}", identity=identity,
            instructions=instructions, formation=formation, alt_formations=[], level=level,
        )
        team.alt_formations = alternative_formations(formation)
        club_surnames: set = set()
        for j, pos in enumerate(SQUAD_TEMPLATE):
            # first choices near the club level, squad players a bit below, a few prospects
            depth_rank = SQUAD_TEMPLATE[:j].count(pos)
            player_level = level - [0, 3.5, 7][min(depth_rank, 2)] + rng.gauss(0, 1.8)
            if rng.random() < 0.08:
                player_level += 4  # a standout player
            team.players.append(make_player(rng, code, j + 1, pos, player_level, used_names, club_surnames))
        _assign_numbers(rng, team.players)
        outfield = [p for p in team.players if p.group != "GK"]
        team.captain_id = max(outfield, key=lambda p: p.overall + p.age / 3 + ("Leadership" in p.traits) * 5).id
        team.set_piece_takers = {
            "penalties": max(outfield, key=lambda p: p.a("penalties") + p.a("composure") / 2).id,
            "free_kicks": max(outfield, key=lambda p: p.a("fk_accuracy") + p.a("curve") / 2).id,
            "corners_left": max(outfield, key=lambda p: p.a("crossing") + p.a("curve") + (p.preferred_foot == "Right") * 8).id,
            "corners_right": max(outfield, key=lambda p: p.a("crossing") + p.a("curve") + (p.preferred_foot == "Left") * 8).id,
        }
        teams.append(team)
    return teams


def _allocate_formations(n_clubs: int, rng: random.Random) -> list:
    """Give each club a starting formation so the league mirrors real PL frequencies
    (largest-remainder allocation of FORMATION_WEIGHTS, then shuffled)."""
    raw = {f: w * n_clubs for f, w in FORMATION_WEIGHTS.items()}
    counts = {f: int(v) for f, v in raw.items()}
    for f in sorted(raw, key=lambda f: raw[f] - counts[f], reverse=True)[: n_clubs - sum(counts.values())]:
        counts[f] += 1
    pool = [f for f, c in counts.items() for _ in range(c)]
    rng.shuffle(pool)
    return pool


def alternative_formations(formation: str) -> list:
    """Formations a manager typically switches to: [attacking option, defensive option]."""
    attacking = {"4231": "4411", "433": "4231", "442": "4231", "4141": "433", "4411": "442",
                 "352": "343", "3421": "343", "343": "3421", "451": "4231", "4321": "433",
                 "41212": "442", "532": "352", "541": "532", "4222": "442", "3412": "343"}
    defensive = {"4231": "4141", "433": "4141", "442": "451", "4141": "541", "4411": "451",
                 "352": "532", "3421": "541", "343": "532", "451": "541", "4321": "4141",
                 "41212": "4141", "532": "541", "541": "541", "4222": "4141", "3412": "532"}
    return [attacking.get(formation, "442"), defensive.get(formation, "541")]


# ------------------------------------------------------------- squad selection
def select_matchday_squad(team: Team, formation: str | None = None, unavailable: set | None = None,
                          fitness: dict | None = None, rng: random.Random | None = None):
    """Pick the starting XI for a formation and 9 substitutes (Premier League rules).

    Returns (lineup, bench) where lineup is a list of (Player, slot_position).
    Tired players (fitness < 80) are rotated out when a decent alternative exists.
    """
    formation = formation or team.formation
    unavailable = unavailable or set()
    fitness = fitness or {}
    slots = FORMATIONS[formation]
    pool = [p for p in team.players if p.id not in unavailable]

    def score(p, slot):
        s = p.position_rating(slot)
        f = fitness.get(p.id, 100)
        if f < 80:
            s -= (80 - f) * 0.6
        if rng is not None:
            s += rng.gauss(0, 0.4)
        return s

    lineup, used = [], set()
    # fill the most specialised slots first (GK, then centre-backs, then the rest)
    order = sorted(range(len(slots)), key=lambda k: {"GK": 0, "CB": 1, "FB": 2, "ST": 3}.get(POSITION_GROUP[slots[k]], 4))
    chosen = {}
    for k in order:
        slot = slots[k]
        cands = [p for p in pool if p.id not in used]
        if POSITION_GROUP[slot] != "GK":
            cands = [p for p in cands if p.group != "GK"]
        best = max(cands, key=lambda p: score(p, slot))
        used.add(best.id)
        chosen[k] = (best, slot)
    lineup = [chosen[k] for k in range(len(slots))]

    rest = [p for p in pool if p.id not in used]
    bench = []
    gks = sorted([p for p in rest if p.group == "GK"], key=lambda p: -p.overall)
    if gks:
        bench.append(gks[0])
    need = {"DEF": 2, "MID": 3, "ATT": 3}
    coarse = {"CB": "DEF", "FB": "DEF", "DM": "MID", "CM": "MID", "AM": "MID", "W": "ATT", "ST": "ATT"}
    outfield = sorted([p for p in rest if p.group != "GK"], key=lambda p: -(p.overall + fitness.get(p.id, 100) / 20))
    for p in outfield:
        if need.get(coarse[p.group], 0) > 0:
            bench.append(p)
            need[coarse[p.group]] -= 1
    for p in outfield:
        if len(bench) >= 9:
            break
        if p not in bench:
            bench.append(p)
    return lineup, bench[:9]


def get_team(teams: list[Team], key: str) -> Team:
    k = key.lower()
    for t in teams:
        if k in (t.code.lower(), t.name.lower(), t.id.lower()):
            return t
    raise KeyError(f"Unknown club '{key}'. Options: {', '.join(t.code for t in teams)}")
