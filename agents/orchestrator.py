"""Orchestrator: runs the four agents together on a live match.

    match events --> Orchestrator --+--> Narrator          live commentary, per audience
                                    +--> Tactical Analyst  half-time / full-time analysis,
                                    |                      review of every tactical change
                                    +--> Producer          show plans per viewer
                                    |       '--> Stats / Tactical (delegated questions)
                                    +--> Router            viewer questions -> right agent(s)

What the orchestrator adds on top of the agents:
    - triggers: it knows WHEN each agent should speak (key moments, half-time, a tactical
      change 12 minutes ago, full time) and calls only the agents needed;
    - shared memory: what an agent says on air is handed to the others as "studio notes"
      (the tactical half-time analysis reaches the Narrator and the Producer), so the show
      is consistent and nobody repeats or contradicts another agent;
    - routing: a small router agent sends each viewer question to the right specialist(s),
      in parallel when two are needed;
    - fan-out: one model call per distinct audience, not per viewer;
    - resilience: every agent call has a time limit, one retry, a circuit breaker and a
      fallback, so the broadcast never stops when an agent fails;
    - metrics: calls, failures and latency per agent.

Run from the repository root:
    python -m agents.orchestrator
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field

from agents import stats_agent, tactical_agent
from agents.match_tools import MatchContext, match_minute, minute_label
from agents.narrator_agent import Narrator, ViewerSettings, commentary_batches
from agents.narrator_feed import describe
from agents.producer_agent import Producer, ViewerProfile, print_stats_panel
from agents.producer_tools import ProducerTools
from agents.runtime import Agent, connect
from matchsim import build_league, get_team, simulate_match

# ---------------------------------------------------------------- router agent
ROUTER_INSTRUCTIONS = """You are the Router of a live football broadcast. A viewer asks a
question during the match; you decide which agent(s) answer it. You never answer yourself.

Agents:
- "stats": score, goals, a shot's xG and why, a period's box score, a player's statistics
  and rating. Questions about ONE PLAYER ("how is X playing?") go to stats only: the tactical
  agent has no player-level data.
- "tactical": team plans and in-game changes, territory and pressing, when the match turned,
  how a team attacks, the defensive shape on a chance.
- "producer": personalised catch-up or highlights for this viewer ("what did I miss?",
  "show me the best moments").

Return one route, or two when the question clearly needs both a number and an explanation.
For each route, rewrite the question so it stands alone (include the minute if useful) and
keep it open: never put an answer in it. Questions handed over by another agent go through
you too: turn a leading or forced-choice question ("was the 48th or the 67th minute
decisive?", "after the goal, when did they take control?") into an open one ("When did the
match turn, and why?"), keeping the moments it mentions as context, not as the answer.
"""
ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "routes": {"type": "array", "items": {
            "type": "object",
            "properties": {"agent": {"type": "string", "enum": ["stats", "tactical", "producer"]},
                           "question": {"type": "string"}},
            "required": ["agent", "question"], "additionalProperties": False}},
        "reason": {"type": "string"},
    },
    "required": ["routes", "reason"],
    "additionalProperties": False,
}

TIMEOUT_S = {"narrator": 45, "stats": 75, "tactical": 90, "producer": 120, "router": 30, "recap": 120}


# ---------------------------------------------------------------- building blocks
@dataclass
class BroadcastItem:
    """One thing that goes on air: the app renders these in order."""
    minute: str
    kind: str          # commentary, crowd, stats_panel, analysis, show_plan, answer, recap
    agent: str
    audience: str      # who sees it ("all", an audience tag or a viewer id)
    payload: dict
    degraded: bool = False   # produced by a fallback because an agent failed
    id: int = 0              # set when published (the web app uses it, e.g. for audio)


@dataclass
class AgentStats:
    calls: int = 0
    failures: int = 0
    timeouts: int = 0
    fallbacks: int = 0
    seconds: float = 0.0
    streak: int = 0           # consecutive failures (circuit breaker)
    skip: int = 0             # calls to skip while the circuit is open


class Supervisor:
    """Runs every agent call with a time limit, one retry, a circuit breaker and a fallback."""

    def __init__(self, workers: int = 8):
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.stats: dict[str, AgentStats] = defaultdict(AgentStats)

    def run(self, agent: str, fn, fallback=None):
        """Returns (result, ok). On failure, returns (fallback(), False)."""
        s = self.stats[agent]
        if s.skip > 0:                       # circuit open: do not hammer a failing agent
            s.skip -= 1
            s.fallbacks += 1
            return (fallback() if fallback else None), False
        for attempt in (1, 2):
            s.calls += 1
            start = time.perf_counter()
            try:
                result = self.pool.submit(fn).result(timeout=TIMEOUT_S.get(agent, 60))
                s.seconds += time.perf_counter() - start
                s.streak = 0
                return result, True
            except FutureTimeout:
                s.timeouts += 1
                break                        # a timed-out call is not retried (it is slow, not broken)
            except Exception as exc:         # noqa: BLE001 - any agent error must not stop the show
                s.failures += 1
                print(f"   !! {agent} failed (attempt {attempt}): {type(exc).__name__}: {exc}")
                if attempt == 1:
                    time.sleep(2)            # short pause: transient errors often clear
        s.streak += 1
        if s.streak >= 3:
            s.skip, s.streak = 5, 0
        s.fallbacks += 1
        return (fallback() if fallback else None), False

    def report(self) -> list[dict]:
        rows = []
        for name, s in sorted(self.stats.items()):
            ok = s.calls - s.failures - s.timeouts
            rows.append({"agent": name, "calls": s.calls, "ok": ok, "failures": s.failures,
                         "timeouts": s.timeouts, "fallbacks": s.fallbacks,
                         "avg_seconds": round(s.seconds / ok, 1) if ok else None})
        return rows


@dataclass
class SharedMemory:
    """What has been said on air, by whom and when: handed to the next agents."""
    notes: list[dict] = field(default_factory=list)

    def add(self, minute: str, agent: str, text: str) -> None:
        self.notes.append({"minute": minute, "agent": agent, "text": text})

    def recent(self, n: int = 2) -> list[str]:
        return [f"{x['agent']} at {x['minute']}': {x['text']}" for x in self.notes[-n:]]


# ---------------------------------------------------------------- orchestrator
class Orchestrator:
    def __init__(self, project, events: list[dict], viewers: dict[str, ViewerProfile],
                 commentary_window: tuple[int, int] | None = None, echo: bool = True):
        self.ctx = MatchContext(events)
        self.viewers = viewers
        self.window = commentary_window
        self.echo = echo
        self.supervisor = Supervisor()
        self.memory = SharedMemory()
        self.timeline: list[BroadcastItem] = []
        self.teams = {"home": self.ctx.home["name"], "away": self.ctx.away["name"]}
        self.panel_tools = ProducerTools(self.ctx)
        self.reviews: list[tuple[int, dict]] = []     # (minute due, tactical_change event)
        self.panels_done: set[int] = set()
        self.listeners: list = []                     # callbacks: the web server streams items
        self._lock = threading.Lock()
        # Live mode: slow analyses run on this pool so they never hold up the commentary.
        self.background: ThreadPoolExecutor | None = None
        # Live mode: the web app runs the half-time studio itself, right after the
        # half-time segment has been sent, and shares this lock on the match context.
        self.defer_half_time = False
        self.half_time_due = False
        self.ctx_lock = threading.RLock()

        self.stats = stats_agent.build(project, self.ctx, verbose=False)
        self.tactical = tactical_agent.build(project, self.ctx, verbose=False)
        self.narrator = Narrator(project, self.ctx)
        self.producer = Producer(project, self.ctx, verbose=False)
        self.router = Agent(project, "router", ROUTER_INSTRUCTIONS, toolbox=None, schemas=[],
                            verbose=False, reasoning_effort="low", output_schema=ROUTER_SCHEMA)
        self.specialists = {"stats": self.stats, "tactical": self.tactical}

    # ---------- helpers ----------
    @property
    def minute(self) -> str:
        return minute_label(self.ctx.seen[-1]) if self.ctx.seen else "0"

    def rewrites(self) -> dict[str, int]:
        """How many answers each agent had to write again after a Python rule check."""
        return {"narrator": self.narrator.agent.rewrites, "recap": self.narrator.recap_agent.rewrites,
                "stats": self.stats.rewrites, "tactical": self.tactical.rewrites}

    def audiences(self) -> list[ViewerSettings]:
        """Distinct audiences among the viewers: one model call each, shared by all its viewers."""
        return sorted({ViewerSettings(v.language, v.audience, v.favourite_team)
                       for v in self.viewers.values()}, key=lambda s: s.tag())

    def publish(self, item: BroadcastItem) -> None:
        with self._lock:
            item.id = len(self.timeline) + 1
            self.timeline.append(item)
        if self.echo:
            self._print(item)
        for listener in self.listeners:
            listener(item)

    def _print(self, it: BroadcastItem) -> None:
        tag = f"[{it.minute}'] {it.kind.upper()} ({it.agent} -> {it.audience})" + (" [fallback]" if it.degraded else "")
        p = it.payload
        if it.kind == "commentary":
            print(f"{tag} {p['text']}")
        elif it.kind == "crowd":
            print(f"{tag} " + "; ".join(f"{c['kind']} ({c['reason']})" for c in p["cues"]))
        elif it.kind == "stats_panel":
            print(tag)
            print_stats_panel(p)
        elif it.kind == "show_plan":
            print(f"{tag} {p['headline']}")
            if p.get("alert"):
                print(f"      ALERT: {p['alert']}")
            for h in p["highlights"]:
                print(f"      {h['minute']}' {h['title']}")
            print("      overlays: " + ", ".join(o["kind"] for o in p["overlays"]))
        elif it.kind == "answer":
            if p.get("original_question") and p["original_question"] != p["question"]:
                print(f"{tag}\n      Producer asked: {p['original_question']}"
                      f"\n      Router opened it: {p['question']}\n      A: {p['answer']}")
            else:
                print(f"{tag}\n      Q: {p['question']}\n      A: {p['answer']}")
        else:
            print(f"{tag} {p.get('text', '')}")

    def _open_question(self, agent_name: str, question: str, sender: str) -> tuple[str, str]:
        """Questions from another agent go through the router: it keeps them open and may
        send them to a better-suited specialist. Falls back to the original question."""
        raw, ok = self.supervisor.run("router", lambda: self.router.ask(
            f"Minute {self.minute}. Question handed over by the {sender} agent for the {agent_name} "
            f"agent: {question}"))
        try:
            route = json.loads(raw)["routes"][0] if ok else None
        except (json.JSONDecodeError, KeyError, TypeError, IndexError):
            route = None
        if not route or route["agent"] not in self.specialists:
            return agent_name, question
        return route["agent"], route["question"]

    def _ask(self, agent_name: str, question: str, sender: str = "orchestrator") -> tuple[str, bool]:
        agent = self.specialists[agent_name]
        return self.supervisor.run(agent_name, lambda: agent.ask_from(sender, question),
                                   fallback=lambda: "This analysis is not available right now.")

    # ---------- live loop ----------
    def on_batch(self, batch: list[dict]) -> None:
        self.ctx.seen.extend(batch)
        minute = match_minute(batch[-1])
        in_window = self.window is None or self.window[0] <= minute <= self.window[1]
        audiences = self.audiences() if in_window else []
        notes = self.memory.recent(2)

        def fallback():
            # Degraded mode: the factual feed line itself, so viewers still get the facts.
            history = self.narrator.history
            if history and history[-1] is batch[-1]:
                before = history[:-len(batch)]
            else:                                # the narrator never saw this batch
                before = list(history)
                history.extend(batch)
            lines = [l for l in describe(batch, self.teams, before) if not l.startswith("[")]
            return {"fallback": lines[:2]}

        result, ok = self.supervisor.run("narrator", lambda: self.narrator.comment(batch, audiences, notes),
                                         fallback=fallback)
        if ok and result:
            for c in result.values():
                self.publish(BroadcastItem(c.minute, "commentary", "narrator", c.settings.tag(),
                                           {"text": c.text, "speech": c.speech, "excitement": c.excitement}))
            cues = next(iter(result.values())).crowd
            if cues:
                self.publish(BroadcastItem(self.minute, "crowd", "crowd", "all",
                                           {"cues": [c.__dict__ for c in cues]}))
        elif not ok and audiences and result and result["fallback"]:
            for s in audiences:
                self.publish(BroadcastItem(self.minute, "commentary", "narrator", s.tag(),
                                           {"text": " ".join(result["fallback"]), "excitement": 2}, degraded=True))

        for e in batch:
            if e["type"] == "tactical_change":
                self.reviews.append((match_minute(e) + 12, e))
            elif e["type"] == "period_end" and e["details"].get("period") == 1:
                if self.defer_half_time:
                    self.half_time_due = True
                else:
                    self.half_time()
        self._review_tactical_changes(minute)
        self._stats_panel(minute)

    def _stats_panel(self, minute: int) -> None:
        """Every 15 minutes, the stats panel: pure Python, no model call, always exact."""
        for mark in (15, 30, 60, 75):
            if minute >= mark and mark not in self.panels_done:
                self.panels_done.add(mark)
                self.publish(BroadcastItem(self.minute, "stats_panel", "python", "all",
                                           self.panel_tools.match_stats_panel()))

    def _review_tactical_changes(self, minute: int) -> None:
        """12 minutes after a tactical change, the Tactical Analyst judges it (open question)."""
        due = [r for r in self.reviews if r[0] <= minute]
        self.reviews = [r for r in self.reviews if r[0] > minute]
        for _, e in due:
            if self.background:
                self.background.submit(self._review_one, e, minute)
            else:
                self._review_one(e, minute)

    def _review_one(self, e: dict, minute: int) -> None:
        q = (f"{e['team']} made a tactical change at {minute_label(e)}' "
             f"({e['details']['description']}). Has it worked so far?")
        with self.ctx_lock:                   # never while a viewer question rewinds the context
            label = self.minute
            text, ok = self._ask("tactical", q)
        if ok:
            self.memory.add(label, "tactical analyst", text)
        self.publish(BroadcastItem(label, "analysis", "tactical", "all",
                                   {"text": text, "question": q}, degraded=not ok))

    # ---------- show segments ----------
    def _plans(self, moment: str) -> None:
        """One show plan per viewer, in parallel; delegated questions answered once."""
        notes = self.memory.recent(3)
        asked: dict[tuple[str, str], str] = {}

        def one(item):
            vid, viewer = item
            plan, ok = self.supervisor.run(
                "producer", lambda: self.producer.plan(moment, viewer, notes),
                fallback=lambda: {"headline": f"{moment.replace('_', ' ').title()}: "
                                              f"{self.teams['home']} {self.ctx.score['home']}-"
                                              f"{self.ctx.score['away']} {self.teams['away']}",
                                  "highlights": [], "agent_requests": [], "alert": None,
                                  "overlays": [{"kind": "match_stats", "title": "Match stats", "content": "",
                                                "data": self.panel_tools.match_stats_panel()}]})
            return vid, plan, ok

        with ThreadPoolExecutor(max_workers=len(self.viewers)) as pool:
            results = list(pool.map(one, self.viewers.items()))
        for vid, plan, ok in results:
            self.publish(BroadcastItem(self.minute, "show_plan", "producer", vid, plan, degraded=not ok))
            for req in plan.get("agent_requests", []):
                key = (req["agent"], req["question"].strip().lower())
                if key not in asked:                 # the same question is never paid twice
                    agent, question = self._open_question(req["agent"], req["question"], "producer")
                    answer, _ = self._ask(agent, question, sender="producer")
                    asked[key] = (agent, question, answer)
                agent, question, answer = asked[key]
                self.publish(BroadcastItem(self.minute, "answer", agent, vid,
                                           {"question": question, "original_question": req["question"],
                                            "answer": answer, "asked_by": "producer"}))

    def half_time(self) -> None:
        q = "Half-time: what has decided the first half, and is the match following each team's plan?"
        text, ok = self._ask("tactical", q)
        if ok:
            self.memory.add(self.minute, "tactical analyst", text)   # handed to Narrator + Producer
        self.publish(BroadcastItem(self.minute, "analysis", "tactical", "all", {"text": text, "question": q},
                                   degraded=not ok))
        self._plans("HALF_TIME")

    def full_time(self) -> None:
        q = "Full time: when did the match turn, and why?"
        text, ok = self._ask("tactical", q)
        if ok:
            self.memory.add(self.minute, "tactical analyst", text)
        self.publish(BroadcastItem(self.minute, "analysis", "tactical", "all", {"text": text, "question": q},
                                   degraded=not ok))
        for s in {ViewerSettings(v.language, v.audience) for v in self.viewers.values()}:
            recap, ok = self.supervisor.run("recap", lambda s=s: self.narrator.recap(s))
            if ok:
                self.publish(BroadcastItem("FT", "recap", "narrator", s.tag(), {"text": recap.text}))
        self._plans("FULL_TIME")

    # ---------- viewer questions ----------
    def ask(self, viewer_id: str, question: str) -> list[BroadcastItem]:
        """A viewer's question: the router picks the agent(s), which answer in parallel."""
        viewer = self.viewers[viewer_id]
        raw, ok = self.supervisor.run(
            "router", lambda: self.router.ask(f"Minute {self.minute}. Viewer ({viewer.describe()}) asks: {question}"))
        try:
            routes = json.loads(raw)["routes"][:2] if ok else []
        except (json.JSONDecodeError, KeyError, TypeError):
            routes = []
        if not routes:   # fallback routing: numbers -> stats, everything else -> tactical
            numeric = any(w in question.lower() for w in ("xg", "how many", "stats", "score", "rating"))
            routes = [{"agent": "stats" if numeric else "tactical", "question": question}]

        def answer(route):
            if route["agent"] == "producer":
                plan, ok = self.supervisor.run("producer", lambda: self.producer.plan("CATCH_UP", viewer,
                                                                                      self.memory.recent(3)))
                text = plan["headline"] if ok else "Catch-up is not available right now."
                return route, text, ok, plan if ok else None
            text, ok = self._ask(route["agent"], route["question"], sender="router")
            return route, text, ok, None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(answer, routes))
        items = []
        for route, text, ok, plan in results:
            item = BroadcastItem(self.minute, "answer", route["agent"], viewer_id,
                                 {"question": question, "routed_question": route["question"],
                                  "answer": text, "plan": plan}, degraded=not ok)
            self.publish(item)
            items.append(item)
        return items

    # ---------- whole match ----------
    def run(self, questions: dict[int, tuple[str, str]] | None = None) -> None:
        questions = dict(questions or {})
        for batch in commentary_batches(self.ctx.all_events):
            self.on_batch(batch)
            for m in sorted(q for q in questions if q <= match_minute(batch[-1])):
                self.ask(*questions.pop(m))
            if any(e["type"] == "match_end" for e in batch):
                self.full_time()


def main():
    parser = argparse.ArgumentParser(description="Run the four agents together on a live match.")
    parser.add_argument("--from-minute", type=int, default=40, help="commentary window start")
    parser.add_argument("--to-minute", type=int, default=65, help="commentary window end")
    parser.add_argument("--full", action="store_true", help="commentary for the whole match")
    args = parser.parse_args()

    project = connect()
    league = build_league()
    events = simulate_match(get_team(league, "HAR"), get_team(league, "KES"), seed=7)
    viewers = {
        "neutral_fan": ViewerProfile("Neutral fan"),
        "ashworth_fan": ViewerProfile("Harbourne fan following Ashworth", favourite_team="Harbourne Rovers",
                                      followed_player="Jordan Ashworth"),
        "analyst": ViewerProfile("Neutral analyst", audience="analyst"),
    }
    window = None if args.full else (args.from_minute, args.to_minute)
    started = time.perf_counter()
    orch = Orchestrator(project, events, viewers, commentary_window=window)
    print("Agents ready: " + ", ".join(a.label for a in (orch.stats, orch.tactical, orch.narrator.agent,
                                                          orch.producer.agent, orch.router)))
    print(f"Viewers: {', '.join(viewers)} | audiences: {', '.join(s.tag() for s in orch.audiences())}\n")

    orch.run(questions={
        30: ("neutral_fan", "Why is it still 0-0?"),
        62: ("ashworth_fan", "How is Ashworth playing, and was his second goal a good chance?"),
        75: ("analyst", "Did Harbourne's half-time change work?"),
    })

    print(f"\n=== Orchestration report ({time.perf_counter() - started:.0f} s, "
          f"{len(orch.timeline)} items on air) ===")
    print(f"{'agent':<10}{'calls':>6}{'ok':>5}{'fail':>6}{'timeout':>9}{'fallback':>10}{'avg s':>7}")
    for r in orch.supervisor.report():
        print(f"{r['agent']:<10}{r['calls']:>6}{r['ok']:>5}{r['failures']:>6}{r['timeouts']:>9}"
              f"{r['fallbacks']:>10}{str(r['avg_seconds']):>7}")
    kinds = defaultdict(int)
    for it in orch.timeline:
        kinds[it.kind] += 1
    print("Items on air: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    print(f"Shared memory: {len(orch.memory.notes)} notes handed between agents")
    print("Answers sent back for a rewrite by the rule checks: " + ", ".join(
        f"{name} {n}" for name, n in orch.rewrites().items()))


if __name__ == "__main__":
    main()
