"""Kokoro voice blends and satellite effects, as samples to choose from.

    H:\\SatelliteAI\\venv\\Scripts\\python.exe -I ai/voice_mix.py          # render the set below + play them

A blend mixes voice style vectors (voices-v1.0.bin holds one per voice); an effect is post-processing
(pitch up by resampling, a soft ring modulator for a small-machine tone, a radio band-pass). Samples
land in H:\\SatelliteAI\\kokoro\\samples\\mix_*.wav. A chosen recipe goes in config.json as
"voice": "af_heart:0.6+af_bella:0.4" and "voice_fx": {"pitch": 1.12, "ring": 0.15} (Voice applies it).
"""
from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(r"H:\SatelliteAI")
LINE = "Hi, I'm Cubie. Throw me one more time and you're getting a snowball in the face."

#: name -> (voice recipe, effects)
SAMPLES = {
    "heart_bella":       ("af_heart:0.6+af_bella:0.4", {}),
    "heart_nicole":      ("af_heart:0.5+af_nicole:0.5", {}),
    "jessica_sky":       ("af_jessica:0.6+af_sky:0.4", {}),
    "heart_pitch":       ("af_heart", {"pitch": 1.12}),
    "jessica_pitch":     ("af_jessica", {"pitch": 1.15}),
    "heart_robot":       ("af_heart", {"pitch": 1.08, "ring": 0.18}),
    "heart_bella_robot": ("af_heart:0.6+af_bella:0.4", {"pitch": 1.1, "ring": 0.12}),
    "heart_radio":       ("af_heart", {"pitch": 1.06, "radio": True}),
}


def style(k, recipe: str):
    """'af_heart:0.6+af_bella:0.4' -> a blended style array (or the voice name when unblended)."""
    parts = [p.split(":") for p in recipe.split("+")]
    if len(parts) == 1 and len(parts[0]) == 1:
        return parts[0][0]
    vs = k.voices
    total = sum(float(w) for _, w in parts)
    return sum(vs[n] * (float(w) / total) for n, w in parts)


def fx(a: np.ndarray, sr: int, e: dict) -> np.ndarray:
    if e.get("pitch", 1.0) != 1.0:                     # higher and a little faster: a smaller speaker
        p = e["pitch"]
        x = np.arange(0, len(a) - 1, p)
        a = np.interp(x, np.arange(len(a)), a)
    if e.get("ring"):                                  # ring modulator mixed in: a machine tone
        t = np.arange(len(a)) / sr
        a = (1 - e["ring"]) * a + e["ring"] * a * np.sin(2 * np.pi * 55 * t)
    if e.get("radio"):                                 # telephone / radio band, ~300 Hz - 3.4 kHz
        f = np.fft.rfft(a)
        freqs = np.fft.rfftfreq(len(a), 1 / sr)
        f[(freqs < 300) | (freqs > 3400)] *= 0.08
        a = np.fft.irfft(f, len(a)) * 1.6
    return np.clip(a, -1, 1)


def main() -> int:
    import onnxruntime as ort
    import pyaudio
    from kokoro_onnx import Kokoro
    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    sess = ort.InferenceSession(str(ROOT / "kokoro" / "kokoro-v1.0.int8.onnx"), so, providers=["CPUExecutionProvider"])
    k = Kokoro.from_session(sess, str(ROOT / "kokoro" / "voices-v1.0.bin"))
    out = ROOT / "kokoro" / "samples"
    out.mkdir(parents=True, exist_ok=True)
    play = "--save-only" not in sys.argv
    pa = pyaudio.PyAudio() if play else None
    for i, (name, (recipe, e)) in enumerate(SAMPLES.items(), 1):
        a, sr = k.create(LINE, voice=style(k, recipe), speed=1.1, lang="en-us")
        a = fx(a, sr, e)
        pcm = (a * 32767).astype(np.int16).tobytes()
        with wave.open(str(out / f"mix_{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm)
        print(f"{i}. mix_{name}: {recipe} {e}", flush=True)
        if pa:
            st = pa.open(format=pyaudio.paInt16, channels=1, rate=sr, output=True)
            st.write(pcm)
            st.close()
            time.sleep(0.8)
    if pa:
        pa.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
