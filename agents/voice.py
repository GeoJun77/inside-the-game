"""Spoken commentary with Azure AI Speech (neural text-to-speech).

The Foundry resource is an Azure AI Services resource, so it already includes Speech:
its key and region go in .env as SPEECH_KEY and SPEECH_REGION (never commit them).

What makes a commentator sound like one is not a louder voice, it is the SHAPE of the
line: short bursts, a build-up, then the explosion ("Thibault... clean through... GOAL!"),
with breaths in between. So we:
    1. split the spoken line into phrases,
    2. give each phrase its own delivery (build-up phrases faster, the climax shouted),
    3. put short pauses between phrases,
    4. use the most expressive voice available in the region:
       - "HD" voices (DragonHD) read the emotion from the text by themselves,
       - "styled" voices accept emotional styles such as excited or shouting,
       - "plain" voices only get speed, pitch and volume changes.

Run `python -m agents.voice` to list the expressive voices of your region and to
render the same goal with several voices, then pick the best one by ear.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

# Candidate voices per language, best first. The first one available in the region wins.
CANDIDATES = {
    "English": ["en-US-Andrew:DragonHDLatestNeural", "en-US-Davis:DragonHDLatestNeural",
                "en-US-Brian:DragonHDLatestNeural", "en-US-DavisNeural", "en-US-GuyNeural",
                "en-US-JasonNeural", "en-GB-RyanNeural"],
    "French": ["fr-FR-Remy:DragonHDLatestNeural", "fr-FR-HenriNeural"],
    "Spanish": ["es-ES-Tristan:DragonHDLatestNeural", "es-ES-AlvaroNeural"],
    "German": ["de-DE-Florian:DragonHDLatestNeural", "de-DE-ConradNeural"],
    "Portuguese": ["pt-BR-AntonioNeural"],
    "Italian": ["it-IT-DiegoNeural"],
    "Arabic": ["ar-SA-HamedNeural"],
}

# excitement -> (style for build-up phrases, style for the climax, style degree)
# The same style family on every line, so the voice keeps the same timbre from the first
# second to the last: only the DEGREE of excitement changes (calm lines = low degree).
STYLES = {1: ("excited", "excited", 0.5), 2: ("excited", "excited", 0.8),
          3: ("excited", "excited", 1.3), 4: ("excited", "shouting", 1.6),
          5: ("excited", "shouting", 2)}
# Styles of the voices we know, used if the region's voice list cannot be read.
KNOWN_STYLES = {"en-US-DavisNeural": ("chat", "angry", "cheerful", "excited", "friendly", "hopeful",
                                      "sad", "shouting", "terrified", "unfriendly", "whispering")}
# excitement -> (rate, pitch) for build-up phrases and for the climax
PROSODY = {1: (("-4%", "-2%"), ("-4%", "-2%")), 2: (("+0%", "+0%"), ("+0%", "+2%")),
           3: (("+8%", "+3%"), ("+5%", "+8%")), 4: (("+14%", "+5%"), ("+6%", "+15%")),
           5: (("+18%", "+6%"), ("+8%", "+22%"))}
PAUSE_MS = {1: 250, 2: 220, 3: 180, 4: 150, 5: 130}

# The goal call, stretched like a real commentator ("Gooooooal!"). Writing "GOOOOAL" in
# the text does not work: the voice may spell it out. Instead we slow down ONLY that
# word and give it a pitch contour that rises and holds. Three ways to stretch it,
# compared by ear with `python -m agents.voice goal` (choose with SPEECH_GOAL_STYLE):
#   slow    - the word "Goal" at half speed with a rising contour
#   spelled - "Goooooal" spelled long, at half speed
#   ipa     - phonetic spelling with a long vowel, at half speed
GOAL_WORD = re.compile(r"\b(G+O+A*L+S?)\b|\b(goal)\b(?=!)", re.IGNORECASE)
GOAL_CONTOUR = "(0%,+18%) (35%,+34%) (85%,+34%) (100%,+26%)"
GOAL_PAUSE_MS = 380


@dataclass
class VoiceInfo:
    name: str
    locale: str
    kind: str                 # "hd", "styled" or "plain"
    styles: tuple[str, ...] = ()


def split_phrases(text: str) -> list[str]:
    """'Thibault... clean through... GOAL! Kestrel lead.' -> phrases, punctuation kept."""
    parts = re.split(r"(?<=[.!?…])\s+|(?<=\.\.\.)\s*|\s+[-–—]\s+", text.strip())
    return [p.strip() for p in parts if p and p.strip()]


def is_climax(phrase: str) -> bool:
    """The explosive part of a line: an exclamation, or a word shouted in capitals."""
    return phrase.endswith("!") or bool(re.search(r"\b[A-Z]{3,}\b", phrase))


def phrase_roles(phrases: list[str], excitement: int) -> list[str]:
    """Shape of the line: 'build' (rising) -> 'peak' (the explosion) -> 'after' (comes down).

    Only the first run of climax phrases is the peak: "and he scores! GOAL!" is shouted,
    "Kestrel Vale lead at Quayside Park!" afterwards is excited but not screamed.
    """
    if excitement < 3 or not any(is_climax(p) for p in phrases):
        return ["build"] * len(phrases)
    roles, state, called = [], "build", False
    for p in phrases:
        if state == "build" and is_climax(p):
            state = "peak"
        elif state == "peak" and (called or not (is_climax(p) and len(p) <= 25)):
            state = "after"          # after the goal call, the voice comes down
        roles.append(state)
        called = called or (state == "peak" and bool(GOAL_WORD.search(p)))
    return roles


def goal_call_ssml(style: str = "spelled") -> str:
    """SSML for the stretched goal call."""
    if style == "spelled":
        word = "Goooooooal!"
    elif style == "ipa":
        word = '<phoneme alphabet="ipa" ph="ˈɡoʊːːːl">goal</phoneme>!'
    else:
        word = "Goal!"
    return (f'<prosody rate="-50%" contour="{GOAL_CONTOUR}" volume="x-loud">{word}</prosody>'
            f'<break time="{GOAL_PAUSE_MS}ms"/>')


def _phrase_ssml(phrase: str, voice: VoiceInfo, excitement: int, role: str, step: int,
                 goal_style: str = "spelled") -> str:
    match = GOAL_WORD.search(phrase) if role == "peak" and voice.kind != "hd" else None
    if match and excitement >= 4:
        # split the phrase around the goal call: "and he scores, GOAL! What a strike"
        before, after = phrase[:match.start()].strip(" ,"), phrase[match.end():].strip(" !,")
        parts = []
        if before:
            parts.append(_phrase_ssml(before, voice, excitement, role, step))
        call = goal_call_ssml(goal_style)
        build_up, peak, degree = STYLES[excitement]
        if voice.kind == "styled" and peak in voice.styles:
            call = f'<mstts:express-as style="{peak}" styledegree="{degree}">{call}</mstts:express-as>'
        parts.append(call)
        if after:
            parts.append(_phrase_ssml(after + "!", voice, excitement, role, step))
        return "".join(parts)
    body = escape(phrase)
    if voice.kind == "hd":
        # HD voices infer emotion from the words; prosody tags are not supported.
        return body
    (rate, pitch), (peak_rate, peak_pitch) = PROSODY[excitement]
    if role == "peak":
        rate, pitch = peak_rate, peak_pitch
        volume = "x-loud" if excitement >= 4 else "loud"
    else:
        # build-up rises a little at every phrase; the aftermath settles back
        bump = 2 * step if role == "build" else 0
        pitch = f"{int(pitch.rstrip('%')) + bump:+d}%"
        volume = "loud" if excitement >= 3 else "medium"
    body = f'<prosody rate="{rate}" pitch="{pitch}" volume="{volume}">{body}</prosody>'
    if voice.kind == "styled":
        build_up, peak, degree = STYLES[excitement]
        style = peak if role == "peak" else build_up
        if style and style in voice.styles:
            body = f'<mstts:express-as style="{style}" styledegree="{degree}">{body}</mstts:express-as>'
    return body


def build_ssml(text: str, voice: VoiceInfo, excitement: int = 2, goal_style: str = "spelled") -> str:
    """SSML for a spoken line: phrase by phrase, with pauses between phrases."""
    excitement = max(1, min(5, int(excitement)))
    pause = f'<break time="{PAUSE_MS[excitement]}ms"/>'
    phrases = split_phrases(text) or [text]
    roles = phrase_roles(phrases, excitement)
    inner = pause.join(_phrase_ssml(p, voice, excitement, r, i, goal_style)
                       for i, (p, r) in enumerate(zip(phrases, roles)))
    return ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="{voice.locale}">'
            f'<voice name="{voice.name}">{inner}</voice></speak>')


class Voice:
    def __init__(self, overrides: dict[str, str] | None = None, audio_format: str = "mp3"):
        """overrides: {"English": "en-US-GuyNeural"} to force a voice for a language.
        audio_format: "mp3" for the web app, "wav" (24 kHz 16-bit) to mix with the crowd."""
        load_dotenv()
        self.config = speechsdk.SpeechConfig(subscription=os.environ["SPEECH_KEY"],
                                             region=os.environ["SPEECH_REGION"])
        self.config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm if audio_format == "wav"
            else speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3)
        self.overrides = overrides or {}
        if os.environ.get("SPEECH_VOICE_EN"):
            self.overrides.setdefault("English", os.environ["SPEECH_VOICE_EN"])
        self.goal_style = os.environ.get("SPEECH_GOAL_STYLE", "spelled")
        self._catalogue: dict[str, VoiceInfo] | None = None
        self._lock = threading.RLock()
        self._chosen: dict[str, VoiceInfo] = {}

    def _synthesizer(self):
        # audio_config=None keeps the audio in memory (bytes) instead of playing it.
        return speechsdk.SpeechSynthesizer(speech_config=self.config, audio_config=None)

    def catalogue(self) -> dict[str, VoiceInfo]:
        """Every voice available in the region, with its kind and styles (cached)."""
        if self._catalogue is None:
            result = self._synthesizer().get_voices_async().get()
            self._catalogue = {}
            for v in result.voices:
                styles = tuple(s for s in (v.style_list or []) if s)
                kind = "hd" if "DragonHD" in v.short_name else ("styled" if styles else "plain")
                self._catalogue[v.short_name] = VoiceInfo(v.short_name, v.locale, kind, styles)
        return self._catalogue

    def voice_for(self, language: str) -> VoiceInfo:
        """The voice of a language, chosen ONCE and then used for every line.

        A voice set in .env (SPEECH_VOICE_EN) is always used, even if the region's voice
        list cannot be read: the commentator must never change in the middle of a match.
        The lock makes sure parallel calls all get the same choice.
        """
        with self._lock:
            if language not in self._chosen:
                forced = self.overrides.get(language)
                if forced:
                    try:
                        info = self.catalogue().get(forced)
                    except Exception:
                        info = None
                    self._chosen[language] = info or VoiceInfo(
                        forced, "-".join(forced.split("-")[:2]), "styled",
                        KNOWN_STYLES.get(forced, ("excited", "shouting")))
                else:
                    cat = self.catalogue()
                    names = CANDIDATES.get(language, CANDIDATES["English"])
                    name = next((n for n in names if n in cat), names[-1])
                    self._chosen[language] = cat.get(name) or VoiceInfo(name, "en-US", "plain")
            return self._chosen[language]

    def speak(self, text: str, language: str = "English", excitement: int = 2,
              voice: VoiceInfo | None = None, goal_style: str | None = None) -> bytes:
        """MP3 bytes of the commentary line (a new synthesizer per call: thread-safe)."""
        voice = voice or self.voice_for(language)
        ssml = build_ssml(text, voice, excitement, goal_style or self.goal_style)
        result = self._synthesizer().speak_ssml_async(ssml).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            details = result.cancellation_details
            raise RuntimeError(f"Speech synthesis failed ({voice.name}): "
                               f"{details.reason} {details.error_details}")
        return result.audio_data

    def save(self, text: str, path: str | Path, language: str = "English", excitement: int = 2,
             voice: VoiceInfo | None = None, goal_style: str | None = None) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.speak(text, language, excitement, voice, goal_style))
        return path


def is_configured() -> bool:
    load_dotenv()
    return bool(os.environ.get("SPEECH_KEY") and os.environ.get("SPEECH_REGION"))


def compare_voices():
    """List the expressive English voices of the region and render one goal with each."""
    v = Voice()
    cat = v.catalogue()
    english = [i for i in cat.values() if i.locale.startswith("en-")]
    hd = [i for i in english if i.kind == "hd"]
    styled = [i for i in english if "shouting" in i.styles or "excited" in i.styles]
    print(f"Region: {os.environ['SPEECH_REGION']} | {len(cat)} voices, "
          f"{len(hd)} English HD, {len(styled)} English with excited/shouting styles")
    for i in hd[:8]:
        print(f"  HD      {i.name}")
    for i in styled[:8]:
        print(f"  styled  {i.name}  {', '.join(i.styles)}")

    line = ("Thibault, clean through on goal... he takes it round the keeper... "
            "and he scores! GOAL! Kestrel Vale lead at Quayside Park!")
    picks = hd[:3] + [i for i in styled if i.name in ("en-US-DavisNeural", "en-US-GuyNeural",
                                                      "en-US-JasonNeural", "en-US-TonyNeural")]
    picks.append(cat.get("en-GB-RyanNeural", VoiceInfo("en-GB-RyanNeural", "en-GB", "plain")))
    out = Path("data/audio/compare")
    for i in picks:
        safe = i.name.replace(":", "_")
        try:
            print(f"  -> {v.save(line, out / f'{safe}.mp3', voice=i, excitement=5)}  ({i.kind})")
        except RuntimeError as exc:
            print(f"  !! {i.name}: {exc}")
    print("Listen, then set SPEECH_VOICE_EN=<voice name> in .env to force your favourite.")


def compare_goal_calls():
    """Render the same goal with the chosen voice and the three ways to stretch the call."""
    v = Voice()
    voice = v.voice_for("English")
    line = "Thibault, clean through on goal... he takes it round the keeper... GOAL! Kestrel Vale lead!"
    print(f"Voice: {voice.name} ({voice.kind})")
    for style in ("slow", "spelled", "ipa"):
        try:
            print(f"  -> {v.save(line, f'data/audio/goal_{style}.mp3', excitement=5, goal_style=style)}")
        except RuntimeError as exc:
            print(f"  !! {style}: {exc}")
    print("Listen, then set SPEECH_GOAL_STYLE=<slow|spelled|ipa> in .env (default: spelled).")


if __name__ == "__main__":
    import sys
    compare_goal_calls() if sys.argv[1:] == ["goal"] else compare_voices()
