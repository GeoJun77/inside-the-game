"""Inside the Game - web server.

    python -m app.server            then open http://localhost:8000

Endpoints:
    GET  /                      the web app
    GET  /api/teams             the 20 clubs of the league
    POST /api/session           create a match session (home, away, seed, speed)
    POST /api/join              a viewer joins with a profile -> viewer id + match info
    POST /api/kickoff           start the match
    GET  /api/stream?viewer=..  live stream (Server-Sent Events): pitch events, items on air
    POST /api/ask               a viewer question, routed to the right agent(s)
    GET  /api/audio/{item_id}   the commentator's voice for a commentary item (MP3)
    GET  /api/crowd/{name}      stadium sound samples (WAV)
    GET  /api/metrics           calls, failures and latency per agent
"""
from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
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

app = FastAPI(title="Inside the Game")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

STATE = {"project": None, "session": None}
LOCK = threading.Lock()


def project():
    if STATE["project"] is None:
        STATE["project"] = connect()
    return STATE["project"]


def session() -> LiveSession:
    if STATE["session"] is None:
        raise HTTPException(404, "No match session. Create one first.")
    return STATE["session"]


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
}


def build_crowd_samples() -> None:
    CROWD_DIR.mkdir(parents=True, exist_ok=True)
    for name, make in CROWD_SAMPLES.items():
        path = CROWD_DIR / f"{name}.wav"
        if not path.exists():
            x = make()
            crowd.save_wav(x * (0.9 / (abs(x).max() + 1e-9)), path)


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=build_crowd_samples, daemon=True).start()


# ---------- pages ----------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "session": STATE["session"].id if STATE["session"] else None}


@app.get("/api/teams")
def teams():
    return [{"code": t.code, "name": t.name, "colors": list(t.colors), "manager": t.manager,
             "identity": getattr(t, "identity_label", None) or str(getattr(t, "identity", "")),
             "stadium": t.stadium, "formation": t.formation} for t in build_league()]


class SessionRequest(BaseModel):
    home: str = "HAR"
    away: str = "KES"
    seed: int = 7
    speed: float = 25.0


@app.post("/api/session")
def create_session(req: SessionRequest):
    with LOCK:
        if STATE["session"]:
            STATE["session"].stop()
        STATE["session"] = LiveSession(project(), req.home, req.away, req.seed, req.speed)
    s = STATE["session"]

    def squad(side):
        info = s.start_info[side]
        return {"team": info["team"], "formation": info["formation"],
                "players": [{"id": p["id"], "name": p["name"], "number": p["number"]}
                            for p in info["starting_xi"] + info["bench"]]}
    return {"session": s.id, "home": squad("home"), "away": squad("away"), "venue": s.start_info["venue"]}


class JoinRequest(BaseModel):
    name: str = "Viewer"
    language: str = "English"
    audience: str = "fan"
    favourite_team: str | None = None
    followed_player: str | None = None


@app.post("/api/join")
def join(req: JoinRequest):
    s = session()
    vid = s.join(req.model_dump())
    return s.init_payload(vid)


@app.post("/api/kickoff")
def kickoff():
    session().start()
    return {"status": session().status}


@app.get("/api/stream")
def stream(viewer: str):
    s = session()
    if viewer not in s.subscribers:
        raise HTTPException(404, "Unknown viewer")
    q = s.subscribers[viewer]

    def events():
        yield "retry: 2000\n\n"
        while True:
            try:
                msg = q.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class AskRequest(BaseModel):
    viewer: str
    question: str


@app.post("/api/ask")
def ask(req: AskRequest):
    s = session()
    if req.viewer not in s.viewers:
        raise HTTPException(404, "Unknown viewer")
    if not req.question.strip():
        raise HTTPException(400, "Empty question")
    return {"items": s.ask(req.viewer, req.question.strip()[:400])}


@app.get("/api/audio/{item_id}")
def audio(item_id: int):
    data = session().audio(item_id)
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
def metrics():
    s = session()
    return {"agents": s.orch.supervisor.report(), "items_on_air": len(s.orch.timeline),
            "memory_notes": len(s.orch.memory.notes), "status": s.status}


if __name__ == "__main__":
    uvicorn.run("app.server:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
