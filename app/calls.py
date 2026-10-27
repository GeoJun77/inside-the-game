"""Play-by-play calls: the short lines a commentator says as the action happens.

"Pickering for Thibault." "Thibault shoots!" "Saved by Fairclough!" They are written by
Python from the match events (no model call, so they are instant and always right), spoken
by the same voice as the Narrator, and timed by the browser on the action itself. The
Narrator's own line then adds the colour: what it means, who is playing well.

Each call has its subtitle in the six languages of the app.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_CALLS = 5          # per segment of highlights: enough to follow the play, not a running list
FULL_MATCH_CALLS = 12  # per segment of the full match (about one every 15 seconds)

# English (spoken) and the subtitles. {a} actor, {b} receiver, {g} goalkeeper, {t} team.
TEMPLATES: dict[str, dict[str, list[str] | str]] = {
    "pass":  {"English": ["{a} for {b}.", "{a} finds {b}.", "{a}, into {b}."],
              "French": "{a} pour {b}.", "Spanish": "{a} para {b}.", "Portuguese": "{a} para {b}.",
              "German": "{a} auf {b}.", "Italian": "{a} per {b}."},
    "through": {"English": ["{a} slides it through for {b}!", "{a}, through ball, {b} is in!"],
                "French": "{a} lance {b} en profondeur !", "Spanish": "¡{a} filtra el pase para {b}!",
                "Portuguese": "{a} lança {b} em profundidade!", "German": "{a} steckt durch auf {b}!",
                "Italian": "{a} verticalizza per {b}!"},
    "cross": {"English": ["{a} crosses.", "In comes the cross from {a}."],
              "French": "Centre de {a}.", "Spanish": "Centro de {a}.", "Portuguese": "Cruzamento de {a}.",
              "German": "Flanke von {a}.", "Italian": "Cross di {a}."},
    "shot":  {"English": ["{a} shoots!", "{a}, the shot!"],
              "French": "{a} frappe !", "Spanish": "¡Dispara {a}!", "Portuguese": "{a} chuta!",
              "German": "{a} zieht ab!", "Italian": "{a} calcia!"},
    "header": {"English": ["{a} heads it!", "{a}, the header!"],
               "French": "{a} de la tête !", "Spanish": "¡Remata de cabeza {a}!", "Portuguese": "{a} de cabeça!",
               "German": "{a} köpft!", "Italian": "{a} di testa!"},
    "penalty_shot": {"English": ["{a} steps up..."],
                     "French": "{a} s'élance...", "Spanish": "{a} toma carrerilla...", "Portuguese": "{a} parte para a bola...",
                     "German": "{a} läuft an...", "Italian": "{a} prende la rincorsa..."},
    "fk_shot": {"English": ["{a} goes for goal from the free kick!"],
                "French": "{a} tente sa chance sur coup franc !", "Spanish": "¡{a} busca la portería de falta!",
                "Portuguese": "{a} arrisca de livre!", "German": "{a} versucht es direkt!",
                "Italian": "{a} ci prova su punizione!"},
    "save":  {"English": ["Saved by {g}!", "{g} saves!"],
              "French": "Arrêt de {g} !", "Spanish": "¡Para {g}!", "Portuguese": "Defesa de {g}!",
              "German": "{g} hält!", "Italian": "Para {g}!"},
    "offside": {"English": ["Flag's up, offside."],
                "French": "Le drapeau se lève, hors-jeu.", "Spanish": "Bandera arriba, fuera de juego.",
                "Portuguese": "Bandeira no ar, impedimento.", "German": "Die Fahne ist oben, Abseits.",
                "Italian": "Bandierina alzata, fuorigioco."},
    "corner": {"English": ["Corner to {t}."],
               "French": "Corner pour {t}.", "Spanish": "Córner para {t}.", "Portuguese": "Escanteio para {t}.",
               "German": "Ecke für {t}.", "Italian": "Calcio d'angolo per {t}."},
    "foul":  {"English": ["Foul by {a}.", "{a} brings him down."],
              "French": "Faute de {a}.", "Spanish": "Falta de {a}.", "Portuguese": "Falta de {a}.",
              "German": "Foul von {a}.", "Italian": "Fallo di {a}."},
    "penalty": {"English": ["Penalty!"],
                "French": "Penalty !", "Spanish": "¡Penalti!", "Portuguese": "Pênalti!",
                "German": "Elfmeter!", "Italian": "Rigore!"},
    "yellow": {"English": ["Yellow card for {a}."],
               "French": "Carton jaune pour {a}.", "Spanish": "Tarjeta amarilla para {a}.",
               "Portuguese": "Cartão amarelo para {a}.", "German": "Gelbe Karte für {a}.",
               "Italian": "Cartellino giallo per {a}."},
    "red":   {"English": ["Red card! {a} is off!"],
              "French": "Carton rouge ! {a} est expulsé !", "Spanish": "¡Tarjeta roja! ¡{a} se va a la calle!",
              "Portuguese": "Cartão vermelho! {a} está expulso!", "German": "Rote Karte! {a} muss runter!",
              "Italian": "Cartellino rosso! {a} è espulso!"},
    "tackle": {"English": ["Good tackle by {a}.", "{a} wins it back."],
               "French": "Beau tacle de {a}.", "Spanish": "Buena entrada de {a}.", "Portuguese": "Boa desarmada de {a}.",
               "German": "Starkes Tackling von {a}.", "Italian": "Bel contrasto di {a}."},
    "interception": {"English": ["{a} cuts it out.", "Intercepted by {a}."],
                     "French": "{a} intercepte.", "Spanish": "Intercepta {a}.", "Portuguese": "{a} intercepta.",
                     "German": "{a} fängt ab.", "Italian": "Intercetta {a}."},
}

# how much each kind of call matters: the most important ones are kept, and a big call may
# cut a smaller one in the browser (priority 2 beats 1; the goal call itself is 3)
WEIGHT = {"shot": 10, "header": 10, "penalty_shot": 10, "fk_shot": 10, "save": 9, "red": 9, "penalty": 9,
          "offside": 7, "yellow": 7, "corner": 6, "through": 5, "cross": 4, "foul": 2.5, "pass": 3,
          "interception": 2, "tackle": 1}
BIG = {"shot", "header", "penalty_shot", "fk_shot", "save", "red", "penalty"}


@dataclass
class Call:
    idx: int                     # the event it belongs to
    kind: str
    names: dict
    variant: int

    @property
    def key(self) -> str:
        return f"call-{self.idx}"

    def text(self, language: str = "English") -> str:
        t = TEMPLATES[self.kind].get(language) or TEMPLATES[self.kind]["English"]
        if isinstance(t, list):
            t = t[self.variant % len(t)]
        return t.format(**self.names)

    @property
    def priority(self) -> int:
        return 2 if self.kind in BIG else 1

    @property
    def excitement(self) -> int:
        return 4 if self.kind in BIG else 2


def calls_for(batch: list[dict], start: int, short: dict[str, str], teams: dict[str, str],
              hidden: set[int], max_calls: int = MAX_CALLS) -> list[Call]:
    """The calls of one segment, from its shown events, most important first, then in order."""
    out: list[Call] = []
    name = lambda pid, full: short.get(pid) or (full or "").split(" ")[-1]
    for off, e in enumerate(batch):
        idx = start + off
        if idx in hidden:
            continue
        d = e.get("details") or {}
        a = name(e.get("player_id"), e.get("player"))
        kind, names = None, {"a": a}
        if e["type"] == "shot":
            st, body = d.get("shot_type"), str(d.get("body_part") or "")
            kind = "penalty_shot" if st == "Penalty" else "fk_shot" if st == "Free Kick" else \
                "header" if "Head" in body else "shot"
        elif e["type"] == "goalkeeper" and e["outcome"] == "save":
            kind, names = "save", {"g": a}
        elif e["type"] == "offside":
            kind = "offside"
        elif e["type"] == "card":
            kind = "yellow" if e["outcome"] == "yellow" else "red"     # second yellow or straight red
        elif e["type"] == "foul":
            kind = "penalty" if d.get("in_box") else "foul"
        elif e["type"] == "pass":
            pt = d.get("pass_type")
            b = name(d.get("recipient_id"), d.get("recipient"))
            if pt == "corner":
                kind, names = "corner", {"t": e["team"]}
            elif pt in ("free_kick", "throw_in", "goal_kick"):
                kind = None
            elif (d.get("through_ball") or pt == "through_ball") and b:
                kind, names = "through", {"a": a, "b": b}
            elif d.get("cross") or pt == "cross":
                kind = "cross"
            elif (d.get("cut_back") or pt == "cut_back") and b:
                kind, names = "pass", {"a": a, "b": b}
            elif (d.get("into_final_third") or d.get("into_box")) and e["outcome"] == "complete" and b:
                kind, names = "pass", {"a": a, "b": b}
        elif e["type"] == "interception":
            kind = "interception"
        elif e["type"] == "duel" and e["outcome"] == "won" and d.get("duel_type") == "Tackle":
            kind = "tackle"
        if kind:
            out.append(Call(idx, kind, names, variant=idx))
    # keep the most important ones, then put them back in match order
    keep = sorted(out, key=lambda c: (-WEIGHT[c.kind], c.idx))[:max_calls]
    return sorted(keep, key=lambda c: c.idx)
