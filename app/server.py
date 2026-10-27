"""Inside the Game - web server.

    python -m app.server            then open http://localhost:8000

Endpoints:
    GET  /                      the web app
    GET  /api/teams             the 20 clubs of the league
    POST /api/session           create a match session (home, away, seed, speed)
    POST /api/join              a viewer joins with a profile -> viewer id + match info
    POST /api/kickoff           start the match
    GET  /api/stream?viewer=..  live stream (Server-Sent Events): ready segments, items on air
    POST /api/ask               a viewer question, routed to the right agent(s)
    POST /api/subtitles         switch the subtitles language during the match
    POST /api/progress          how far the browser has played (the director stays just ahead)
    GET  /api/audio/{key}       the commentator's voice for an item, or "intro-<viewer>" (MP3)
    GET  /api/crowd/{name}      stadium sound samples (WAV)
    GET  /api/metrics           calls, failures and latency per agent
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import random
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents import crowd
from agents.runtime import connect
from app.live import LiveSession
from matchsim import build_league

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
CROWD_DIR = ROOT.parent / "data" / "audio" / "web"

@asynccontextmanager
async def lifespan(_app):
    # the stadium sounds (already built into the container image; made here when run locally)
    threading.Thread(target=build_crowd_samples, daemon=True).start()
    yield


app = FastAPI(title="Inside the Game", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# Several matches can run at once (one per visitor), each with its own id. The number is
# capped to protect the Foundry quota; a finished or abandoned match frees its slot.
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", 3))
SESSION_TTL_S = 25 * 60
STATE: dict = {"project": None, "sessions": {}}
LOCK = threading.Lock()


def project():
    if STATE["project"] is None:
        STATE["project"] = connect()
    return STATE["project"]


def session(request: Request) -> LiveSession:
    """The match of this browser: its id comes in the X-Session header (or ?s= for
    the live stream and the audio, which the browser fetches by URL)."""
    sid = request.headers.get("x-session") or request.query_params.get("s")
    s = STATE["sessions"].get(sid or "")
    if s is None:
        raise HTTPException(404, "This match has ended or does not exist. Set up a new one.")
    return s


def _free_slots() -> None:
    """Close the matches that are over or too old."""
    now = time.time()
    for sid, s in list(STATE["sessions"].items()):
        if (s.status == "full_time" and now - s.created > 120) or now - s.created > SESSION_TTL_S:
            s.stop()
            del STATE["sessions"][sid]


# ---------- stadium sounds, generated once ----------
CROWD_SAMPLES = {
    "murmur": lambda: crowd.murmur(40),
    "roar_low_1": lambda: crowd.roar(0.35), "roar_low_2": lambda: crowd.roar(0.4),
    "roar_mid_1": lambda: crowd.roar(0.65), "roar_mid_2": lambda: crowd.roar(0.7),
    "roar_high_1": lambda: crowd.roar(0.95), "roar_high_2": lambda: crowd.roar(1.0),
    "celebration_1": crowd.celebration, "celebration_2": crowd.celebration,
    "ooh_low_1": lambda: crowd.ooh(0.4), "ooh_low_2": lambda: crowd.ooh(0.45),
    "ooh_high_1": lambda: crowd.ooh(0.85), "ooh_high_2": lambda: crowd.ooh(0.95),
    "boo_low_1": lambda: crowd.boo(0.4), "boo_low_2": lambda: crowd.boo(0.45),
    "boo_high_1": lambda: crowd.boo(0.8), "boo_high_2": lambda: crowd.boo(1.0),
    "applause_1": lambda: crowd.applause(0.4), "applause_2": lambda: crowd.applause(0.7),
    "anticipation_1": lambda: crowd.anticipation(0.5), "anticipation_2": lambda: crowd.anticipation(0.6),
    # the referee: a foul or an offside, the kick-off, half-time (two blasts), full time (three)
    "ref_short": lambda: crowd.referee_whistle((0.32,)),
    "ref_kickoff": lambda: crowd.referee_whistle((0.75,)),
    "ref_half": lambda: crowd.referee_whistle((0.45, 1.1), gap=0.22),
    "ref_full": lambda: crowd.referee_whistle((0.45, 0.45, 1.4), gap=0.22),
}


def build_crowd_samples() -> None:
    CROWD_DIR.mkdir(parents=True, exist_ok=True)
    for name, make in CROWD_SAMPLES.items():
        path = CROWD_DIR / f"{name}.wav"
        if not path.exists():
            x = make()
            crowd.save_wav(x * (0.9 / (abs(x).max() + 1e-9)), path)


# ---------- pages ----------
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


@app.get("/")
def index():
    """The page, with its script and style versioned by their content: after an update the
    browser always loads the new ones (never a stale app.js from its cache)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "style.css"):
        version = hashlib.md5((STATIC / name).read_bytes()).hexdigest()[:10]
        html = html.replace(f"/static/{name}\"", f"/static/{name}?v={version}\"")
    return Response(content=html, media_type="text/html", headers=NO_CACHE)


@app.middleware("http")
async def no_stale_static(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers.update(NO_CACHE)
    return response


@app.get("/api/health")
def health():
    return {"ok": True, "matches": len(STATE["sessions"]), "max": MAX_SESSIONS}


@app.get("/api/teams")
def teams():
    return [{"code": t.code, "name": t.name, "colors": list(t.colors), "manager": t.manager,
             "identity": getattr(t, "identity_label", None) or str(getattr(t, "identity", "")),
             "stadium": t.stadium, "formation": t.formation} for t in build_league()]


class SessionRequest(BaseModel):
    home: str = "HAR"
    away: str = "KES"
    seed: int | None = None          # None: a new match, drawn at random
    speed: float = 1.0


@app.post("/api/session")
def create_session(req: SessionRequest):
    with LOCK:
        _free_slots()
        if len(STATE["sessions"]) >= MAX_SESSIONS:
            raise HTTPException(503, f"All {MAX_SESSIONS} match slots are in use. Try again in a few minutes.")
        seed = req.seed or random.randint(1, 99999)
        s = LiveSession(project(), req.home, req.away, seed, req.speed)
        s.seed = seed
        STATE["sessions"][s.id] = s

    def squad(side):
        info = s.start_info[side]
        return {"team": info["team"], "formation": info["formation"],
                "players": [{"id": p["id"], "name": p["name"], "number": p["number"]}
                            for p in info["starting_xi"] + info["bench"]]}
    return {"session": s.id, "seed": s.seed, "home": squad("home"), "away": squad("away"),
            "venue": s.start_info["venue"]}


class JoinRequest(BaseModel):
    name: str = "Viewer"
    language: str = "English"
    audience: str = "fan"
    favourite_team: str | None = None
    followed_player: str | None = None


@app.post("/api/join")
def join(req: JoinRequest, request: Request):
    s = session(request)
    vid = s.join(req.model_dump())
    return s.init_payload(vid)


@app.post("/api/kickoff")
def kickoff(request: Request):
    s = session(request)
    s.start()
    return {"status": s.status}


@app.get("/api/stream")
def stream(viewer: str, request: Request):
    s = session(request)
    if viewer not in s.subscribers:
        raise HTTPException(404, "Unknown viewer")
    q = s.subscribers[viewer]

    def events():
        yield "retry: 2000\n\n"
        while True:
            try:
                msg = q.get(timeout=15)
            except queue.Empty:
                if s.stop_flag.is_set():           # the match was closed: end the stream
                    return
                yield ": keep-alive\n\n"
                continue
            yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class AskRequest(BaseModel):
    viewer: str
    question: str


@app.post("/api/ask")
def ask(req: AskRequest, request: Request):
    s = session(request)
    if req.viewer not in s.viewers:
        raise HTTPException(404, "Unknown viewer")
    if not req.question.strip():
        raise HTTPException(400, "Empty question")
    return {"items": s.ask(req.viewer, req.question.strip()[:400])}


class SubtitlesRequest(BaseModel):
    viewer: str
    language: str


@app.post("/api/subtitles")
def subtitles(req: SubtitlesRequest, request: Request):
    """Switch the commentator's subtitles to another language during the match."""
    session(request).set_subtitles(req.viewer, req.language)
    return {"ok": True}


class ProgressRequest(BaseModel):
    viewer: str
    seq: int
    idx: int


@app.post("/api/progress")
def progress(req: ProgressRequest, request: Request):
    """The browser says how far it has played: the director stays just ahead of it."""
    session(request).report_progress(req.viewer, req.seq, req.idx)
    return {"ok": True}


@app.get("/api/audio/{key}")
def audio(key: str, request: Request):
    data = session(request).audio(key)
    if not data:
        raise HTTPException(404, "No audio for this item")
    return Response(content=data, media_type="audio/mpeg", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/crowd/{name}")
def crowd_sample(name: str):
    path = CROWD_DIR / f"{name}.wav"
    if name not in CROWD_SAMPLES or not path.exists():
        raise HTTPException(404, "Sample not ready")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/metrics")
def metrics(request: Request):
    s = session(request)
    return {"agents": s.orch.supervisor.report(), "items_on_air": len(s.orch.timeline),
            "memory_notes": len(s.orch.memory.notes), "status": s.status,
            "rewrites": s.orch.rewrites()}


if __name__ == "__main__":
    uvicorn.run("app.server:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
