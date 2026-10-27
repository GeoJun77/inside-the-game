"""Stadium atmosphere, synthesised in Python and driven by the match events.

A crowd is thousands of voices at once. We imitate it by adding up many "voices"
(buzzing tones at random pitches, filtered through vowel resonances: "aah" for a roar,
"ooh" for a near miss, a low "uuu" for boos) plus voice-shaped noise, then shaping the
level over time. Every sound is regenerated with fresh randomness, so no two reactions
are identical.

The crowd has a side: about 85% of the stadium supports the home team. A home goal makes
the whole ground explode; an away goal only lifts the away end while the rest groans.

    reactions_for(events, teams)  -> the crowd cues of a batch of events
    mix_commentary(lines)         -> commentary + murmur + reactions, with ducking

    python -m agents.crowd        writes data/audio/crowd_*.wav samples
"""
from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 24_000                       # same sample rate as the commentary voice
HOME_SHARE = 0.85                 # share of the stadium supporting the home team
_seed = iter(range(10_000, 10**9))

VOWELS = {"aah": [(750, 1.0), (1200, 0.6), (2600, 0.25)],
          "ooh": [(320, 1.0), (800, 0.45), (2300, 0.12)],
          "uuu": [(280, 1.0), (650, 0.35), (2200, 0.08)],
          "eh": [(550, 1.0), (1800, 0.5), (2500, 0.2)]}


def _rng() -> np.random.Generator:
    """A new random generator per sound: every reaction is different."""
    return np.random.default_rng(next(_seed))


# ---------- building blocks ----------
def _bandpass(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    soft = np.clip((freqs - lo * 0.7) / (lo * 0.3 + 1e-9), 0, 1) * np.clip((hi * 1.3 - freqs) / (hi * 0.3), 0, 1)
    return np.fft.irfft(spec * soft, len(x))


def _formants(x: np.ndarray, vowel: str, width: float = 90) -> np.ndarray:
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    shape = sum(g * np.exp(-0.5 * ((freqs - f) / (width + f * 0.08)) ** 2) for f, g in VOWELS[vowel])
    return np.fft.irfft(spec * shape, len(x))


def _drift(rng, n: int, rate_hz: float, depth: float) -> np.ndarray:
    """A random level that wanders slowly (the crowd breathing)."""
    knots = max(4, int(n / SR * rate_hz) + 2)
    curve = np.interp(np.arange(n), np.linspace(0, n, knots), rng.normal(0, 1, knots))
    return 1 + depth * np.tanh(curve)


def _rms(x: np.ndarray, target: float) -> np.ndarray:
    return x * (target / (np.std(x) + 1e-9))


def _voices(rng, seconds: float, n_voices: int, pitch: tuple[float, float], vowel: str,
            glide: float = 0.0, spread: float = 0.25, noise: float = 0.35) -> np.ndarray:
    """Many people shouting the same vowel, each at their own pitch and timing."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for _ in range(n_voices):
        f0 = rng.uniform(*pitch)
        f = f0 * (1 + glide * t / seconds) * (1 + 0.02 * np.sin(2 * np.pi * rng.uniform(4, 7) * t))
        phase = 2 * np.pi * np.cumsum(f) / SR
        buzz = sum(np.sin(k * phase) / k for k in range(1, 9))
        start = rng.uniform(0, spread)
        out += buzz * np.clip((t - start) / 0.15, 0, 1) * rng.uniform(0.5, 1.0)
    out = _formants(out, vowel)
    return out + noise * _bandpass(rng.normal(0, 1, n), 300, 3500) * np.std(out)


def _envelope(t: np.ndarray, attack: float, hold: float, release: float) -> np.ndarray:
    rise = np.clip(t / max(attack, 1e-3), 0, 1) ** 0.6
    fall = np.where(t < attack + hold, 1.0, np.exp(-(t - attack - hold) / max(release, 1e-3)))
    return rise * fall


# ---------- crowd sounds (all randomised) ----------
def murmur(seconds: float) -> np.ndarray:
    """The constant background of a full stadium."""
    rng, n = _rng(), int(seconds * SR)
    x = _bandpass(np.cumsum(rng.normal(0, 1, n)) * 0.02 + rng.normal(0, 1, n), 180, 3000)
    x = _formants(x, "aah", width=260) * 0.6 + x * 0.4
    return _rms(x * _drift(rng, n, 0.6, 0.35), 0.12)


def roar(intensity: float = 1.0) -> np.ndarray:
    """A goal: the stadium explodes, holds, and settles. Bigger and longer with intensity."""
    rng = _rng()
    seconds = 4.5 + 3.5 * intensity + rng.uniform(-0.5, 0.5)
    t = np.arange(int(seconds * SR)) / SR
    body = _voices(rng, seconds, int(80 + 80 * intensity), (170, 430), "aah",
                   glide=rng.uniform(0.0, 0.06), noise=0.6)
    env = _envelope(t, rng.uniform(0.25, 0.45), 1.5 + 2.0 * intensity, 1.2 + intensity)
    return _rms(body * env * _drift(rng, len(t), 2.0, 0.15), 0.16 * (0.5 + 0.5 * intensity))


def celebration(seconds: float = 9.0) -> np.ndarray:
    """After a home goal: the noise stays high, with chants pulsing in the stands."""
    rng = _rng()
    t = np.arange(int(seconds * SR)) / SR
    chant = _voices(rng, seconds, 70, (180, 320), rng.choice(["ooh", "aah", "eh"]), spread=0.05)
    beat = rng.uniform(1.6, 2.3)                                # chant rhythm (per second)
    pulse = 0.55 + 0.45 * (np.sin(2 * np.pi * beat * t) > -0.2)
    env = np.clip(t / 1.0, 0, 1) * np.clip((seconds - t) / 2.5, 0, 1)
    return _rms(_bandpass(chant * pulse, 150, 3500) * env, 0.09)


def ooh(intensity: float = 0.6) -> np.ndarray:
    """A near miss: a rising "oooh" that falls away. Louder for a bigger chance."""
    rng = _rng()
    seconds = 1.8 + 1.4 * intensity + rng.uniform(-0.2, 0.3)
    t = np.arange(int(seconds * SR)) / SR
    body = _voices(rng, seconds, int(60 + 70 * intensity), (160, 340), "ooh",
                   glide=-rng.uniform(0.06, 0.16))
    env = np.sin(np.pi * np.clip(t / seconds, 0, 1)) ** rng.uniform(1.0, 1.6)
    return _rms(body * env, 0.07 + 0.08 * intensity)


def boo(intensity: float = 0.6) -> np.ndarray:
    """Disapproval: a low "booo", with jeering whistles when it is strong."""
    rng = _rng()
    seconds = 2.0 + 2.5 * intensity + rng.uniform(-0.3, 0.4)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    body = _voices(rng, seconds, int(60 + 80 * intensity), (95, 190), "uuu", spread=0.4, noise=0.2)
    out = body * _envelope(t, 0.4, seconds * 0.5, seconds * 0.25)
    if intensity >= 0.5:
        out = _rms(out, 1.0) + _rms(whistles(seconds, rng), 0.35 * intensity)
    return _rms(out, 0.07 + 0.08 * intensity)


def whistles(seconds: float, rng=None) -> np.ndarray:
    """Fans whistling at the referee: high tones that slide up and down."""
    rng = rng or _rng()
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for _ in range(int(rng.integers(5, 12))):
        start, length = rng.uniform(0, seconds * 0.6), rng.uniform(0.4, 1.4)
        f = rng.uniform(1800, 3200) * (1 + rng.uniform(-0.15, 0.15) * np.sin(2 * np.pi * rng.uniform(1, 3) * t))
        tone = np.sin(2 * np.pi * np.cumsum(f) / SR)
        out += tone * np.clip(1 - np.abs(t - start - length / 2) / (length / 2), 0, 1) ** 0.5
    return out


def referee_whistle(blasts: tuple[float, ...] = (0.35,), gap: float = 0.18) -> np.ndarray:
    """The referee's pea whistle: a bright tone near 3 kHz, warbled about 30 times a second
    by the pea inside, with a sharp start and a short tail. blasts: seconds of each blast."""
    rng = _rng()
    parts = []
    for i, length in enumerate(blasts):
        n = int(length * SR)
        t = np.arange(n) / SR
        f0 = rng.uniform(2900, 3200)
        trill = 1 + 0.035 * np.sin(2 * np.pi * rng.uniform(26, 34) * t)            # the pea
        phase = 2 * np.pi * np.cumsum(f0 * trill) / SR
        tone = np.sin(phase) + 0.35 * np.sin(2 * phase) + 0.12 * np.sin(3 * phase)
        am = 0.75 + 0.25 * np.sin(2 * np.pi * rng.uniform(26, 34) * t)
        env = np.minimum(1, t / 0.015) * np.minimum(1, (length - t) / 0.06)
        breath = 0.04 * rng.standard_normal(n)
        parts.append((tone * am + breath) * np.clip(env, 0, 1))
        if i < len(blasts) - 1:
            parts.append(np.zeros(int(gap * SR)))
    return np.concatenate(parts) * 0.7


def applause(intensity: float = 0.5, seconds: float | None = None) -> np.ndarray:
    """Clapping: thousands of short bursts of noise at random times."""
    rng = _rng()
    seconds = seconds or 2.5 + 2.5 * intensity
    n = int(seconds * SR)
    out = np.zeros(n)
    clap = _bandpass(rng.normal(0, 1, 600), 800, 5000) * np.exp(-np.arange(600) / 90)
    for i in rng.integers(0, n - 600, int((900 + 2500 * intensity) * seconds)):
        out[i:i + 600] += clap * rng.uniform(0.3, 1.0)
    t = np.arange(n) / SR
    return _rms(out * _envelope(t, 0.3, seconds * 0.55, seconds * 0.2), 0.05 + 0.06 * intensity)


def anticipation(intensity: float = 0.5) -> np.ndarray:
    """The ball goes into the box: the noise swells as the crowd rises."""
    rng = _rng()
    seconds = 1.6 + rng.uniform(0, 0.8)
    t = np.arange(int(seconds * SR)) / SR
    swell = _voices(rng, seconds, 50, (150, 300), "aah", glide=0.1, spread=0.6, noise=0.8)
    return _rms(swell * (t / seconds) ** 1.6, 0.04 + 0.05 * intensity)


SOUNDS = {"roar": roar, "celebration": lambda i: celebration(), "ooh": ooh, "boo": boo,
          "applause": applause, "anticipation": anticipation}


# ---------- which reaction for which event ----------
@dataclass
class Cue:
    kind: str           # roar, celebration, ooh, boo, applause, anticipation
    intensity: float    # 0-1
    reason: str         # for logs and the UI


def reactions_for(events: list[dict], teams: dict, rng=None) -> list[Cue]:
    """The crowd's reactions to a batch of events, in order, from the home fans' point of view."""
    rng = rng or _rng()
    cues: list[Cue] = []
    seen_box = set()
    score = dict(events[0]["score"]) if events else {"home": 0, "away": 0}

    def home(e):
        return e.get("team") == teams["home"]

    for e in events:
        t, d = e["type"], e.get("details") or {}
        if t == "pass" and d.get("into_box") and e["outcome"] == "complete" and home(e) \
                and e["possession_id"] not in seen_box:
            seen_box.add(e["possession_id"])
            cues.append(Cue("anticipation", 0.5, "home attack into the box"))
        elif t == "shot" and e["outcome"] == "Goal":
            side = "home" if home(e) else "away"
            before = score[side] - score["away" if side == "home" else "home"]
            score[side] += 1
            big = 0.25 * (before in (-1, 0)) + 0.15 * (e["minute"] >= 80)   # equaliser / winner / late
            if side == "home":
                cues += [Cue("roar", min(1.0, 0.8 + big), f"home goal by {e['player']}"),
                         Cue("celebration", 1.0, "home fans celebrate")]
            else:
                cues += [Cue("roar", 0.3 + big * 0.5, f"away end celebrates {e['player']}"),
                         Cue("ooh", 0.35, "home fans groan")]
        elif t == "shot":
            xg, mine = d["xg"], home(e)
            woodwork = e["outcome"] in ("Post", "Saved to Post")
            if woodwork:
                cues.append(Cue("ooh", 1.0 if mine else 0.55, "off the woodwork"))
            elif e["outcome"] in ("Saved", "Off T", "Wayward") and xg >= 0.08:
                cues.append(Cue("ooh", min(1.0, 0.35 + 1.6 * xg) * (1 if mine else 0.5), f"{e['player']} misses"))
                if e["outcome"] == "Saved" and not mine and xg >= 0.15:
                    cues.append(Cue("applause", 0.6, f"home keeper saves from {e['player']}"))
            elif e["outcome"] == "Blocked" and xg >= 0.15 and mine:
                cues.append(Cue("ooh", 0.4, "shot blocked"))
        elif t == "card":
            red = e["outcome"] in ("red", "second_yellow")
            if home(e):
                cues.append(Cue("boo", 1.0 if red else 0.65, f"card for home player {e['player']}"))
            elif red:
                cues.append(Cue("roar", 0.6, f"away player {e['player']} sent off"))
            else:
                cues.append(Cue("applause", 0.35, f"booking for away player {e['player']}"))
        elif t == "foul" and not home(e) and (d.get("in_box") or rng.random() < 0.35):
            cues.append(Cue("boo", 0.8 if d.get("in_box") else 0.4, f"foul on {d.get('on_player')}"))
        elif t == "offside" and home(e):
            cues.append(Cue("boo", 0.45, "offside against the home side"))
        elif t == "substitution" and home(e) and d.get("reason") != "injury":
            cues.append(Cue("applause", 0.55, f"applause for {d['player_off']}"))
        elif t == "injury" and home(e):
            cues.append(Cue("applause", 0.3, f"encouragement for {e['player']}"))
        elif t == "period_end":
            diff = e["score"]["home"] - e["score"]["away"]
            final = d.get("period") == 2
            if diff > 0:
                cues.append(Cue("roar" if final else "applause", 0.8 if final else 0.6, "the home side lead"))
            elif diff < 0:
                cues.append(Cue("boo", 0.8 if final else 0.5, "the home side are losing"))
            else:
                cues.append(Cue("applause", 0.45, "level at the whistle"))
    return cues[-4:]          # a crowd reacts to the last few things, not to everything


# ---------- mixing ----------
def _place(track: np.ndarray, clip: np.ndarray, at_s: float, gain: float = 1.0) -> None:
    i = max(0, int(at_s * SR))
    j = min(len(track), i + len(clip))
    if i < len(track):
        track[i:j] += clip[: j - i] * gain


def _schedule(cues: list[Cue]) -> list[tuple[Cue, float]]:
    """Time of each cue relative to the commentator's line (negative = before it).

    The crowd reacts first and the commentator speaks over the reaction; celebrations
    and applause carry on under the line.
    """
    out, t = [], -0.6
    for cue in reversed(cues):
        if cue.kind == "celebration":
            out.append((cue, 2.5))          # the chants start once the roar settles
            continue
        out.append((cue, t))
        t -= 1.6 if cue.kind in ("ooh", "boo", "anticipation") else 1.0
    return list(reversed(out))


def mix_commentary(lines: list[tuple[np.ndarray, list[Cue]]], gap_s: float = 1.2,
                   voice_rms: float = 0.10, bed_gain: float = 0.30, crowd_gain: float = 0.55,
                   duck: float = 0.40) -> np.ndarray:
    """Commentary lines (audio, crowd cues) one after the other, with the stadium underneath.

    Levels are set by average loudness (RMS), like a broadcast mix:
      - every commentary line is brought to the same loudness (voice_rms, about -20 dB),
      - the murmur sits well below it, the reactions above the murmur,
      - the whole crowd dips (duck) while the commentator speaks, so he stays clear,
      - a soft limiter tames the loudest peaks instead of turning the whole mix down.
    """
    plans, t = [], 1.0
    for audio, cues in lines:
        sched = _schedule(cues)
        lead = max([0.0] + [-at for _, at in sched])
        start = t + lead
        plans.append((audio * (voice_rms / (np.std(audio) + 1e-9)), sched, start))
        t = start + len(audio) / SR + gap_s
    total = int((t + 4.0) * SR)
    voice, crowd, speaking = np.zeros(total), np.zeros(total), np.zeros(total)
    for audio, sched, start in plans:
        for cue, at in sched:
            _place(crowd, SOUNDS[cue.kind](cue.intensity), start + at, crowd_gain)
        _place(voice, audio, start)
        i = int(start * SR)
        speaking[i:i + len(audio)] = 1.0
    k = int(0.25 * SR)
    smooth = np.convolve(speaking, np.ones(k) / k, mode="same")
    out = voice + (murmur(total / SR) * bed_gain + crowd) * (1 - (1 - duck) * smooth)
    return _limit(out)


def _limit(x: np.ndarray, ceiling: float = 0.95) -> np.ndarray:
    """Soft limiter: quiet parts untouched, peaks above ~0.5 rounded off smoothly."""
    knee = 0.5
    over = np.abs(x) > knee
    y = x.copy()
    y[over] = np.sign(x[over]) * (knee + (ceiling - knee) * np.tanh((np.abs(x[over]) - knee) / (ceiling - knee)))
    return y


# ---------- files ----------
def to_array(wav_bytes: bytes) -> np.ndarray:
    """16-bit mono WAV bytes (from the voice) -> float array."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768


def save_wav(x: np.ndarray, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def _norm(x):
    return x * (0.9 / (np.max(np.abs(x)) + 1e-9))


if __name__ == "__main__":
    samples = {"murmur": murmur(10), "roar_home_goal": roar(1.0), "roar_away_end": roar(0.3),
               "celebration": celebration(), "ooh_big_chance": ooh(0.9), "ooh_small": ooh(0.4),
               "boo_card": boo(0.65), "boo_red_card": boo(1.0), "applause": applause(0.6),
               "anticipation": anticipation(0.5)}
    for name, sound in samples.items():
        print(save_wav(_norm(sound), f"data/audio/crowd_{name}.wav"))
