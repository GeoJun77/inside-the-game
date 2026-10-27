"""Voice-over for the demo video, made with Azure AI Speech (the key stays in .env).

    python tools/voiceover.py

Writes video/vo_01.wav ... video/vo_09.wav, one file per shot of the demo script, with a
narrator voice different from the match commentator. The key is read from .env and never
printed.
"""
from __future__ import annotations

import os
from pathlib import Path

import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "video"
VOICE = "en-GB-RyanNeural"          # the narrator of the video (the match voice is Davis)

LINES = [
    "This is a live football broadcast, run entirely by five Microsoft Foundry agents, "
    "on a synthetic match calibrated on real Premier League data.",
    "The match plays at real football speed. A play-by-play caller says the actions as they "
    "happen, and our Narrator agent adds the colour, voiced by Azure AI Speech.",
    "Goals land on the right frame: the agents prepare the broadcast ahead, and the browser "
    "plays voice, crowd and action on one clock.",
    "Subtitles in six languages, switchable live.",
    "Every number is computed in Python from the event stream: the stats, the expected goals "
    "from our own model trained on StatsBomb data, and live player ratings.",
    "Viewers ask questions. A Router agent sends them to the right analyst, who answers with "
    "the match as you have seen it. No spoilers.",
    "At half-time, a Producer agent builds each viewer's own show.",
    "Behind the scenes: a supervisor with time limits, retries and backups, and a rule checker "
    "that sends answers back when they guess or invent. The show never stops.",
    "Deployed on Azure Container Apps, with a managed identity. Try it live.",
]


def main() -> None:
    load_dotenv(ROOT / ".env")
    key, region = os.environ.get("SPEECH_KEY"), os.environ.get("SPEECH_REGION")
    if not key or not region:
        raise SystemExit("SPEECH_KEY and SPEECH_REGION are needed in .env")
    OUT.mkdir(exist_ok=True)
    config = speechsdk.SpeechConfig(subscription=key, region=region)
    config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm)
    for n, text in enumerate(LINES, 1):
        path = OUT / f"vo_{n:02d}.wav"
        ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-GB">'
                f'<voice name="{VOICE}"><prosody rate="-4%">{text}</prosody></voice></speak>')
        synth = speechsdk.SpeechSynthesizer(speech_config=config,
                                            audio_config=speechsdk.audio.AudioOutputConfig(filename=str(path)))
        result = synth.speak_ssml_async(ssml).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise SystemExit(f"line {n} failed: {result.reason}")
        print(f"{path.name}  ({result.audio_duration.total_seconds():.1f} s)")
    print(f"Done: {len(LINES)} files in {OUT}")


if __name__ == "__main__":
    main()
