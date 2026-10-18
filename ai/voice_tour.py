"""Hear every English Kokoro voice say the same Cubie line, one after another.

    H:\\SatelliteAI\\venv\\Scripts\\python.exe -I ai/voice_tour.py            # all, played aloud
    ... ai/voice_tour.py af_bella bf_emma                                   # just these
    ... ai/voice_tour.py --save-only                                        # WAVs only, no playback

WAVs land in H:\\SatelliteAI\\kokoro\\samples\\<voice>.wav. Pick one with config.json "voice": "<voice>"
(af = American female, am = American male, bf = British female, bm = British male); the voice cache
is per voice, so a new voice re-renders her lines in the background the next time she starts.
"""
from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

ROOT = Path(r"H:\SatelliteAI")
LINE = "Hi, I'm Cubie. Throw me one more time and you're getting a snowball in the face."
KIND = {"af": "American, female", "am": "American, male", "bf": "British, female", "bm": "British, male"}


def main() -> int:
    import numpy as np
    import onnxruntime as ort
    import pyaudio
    from kokoro_onnx import Kokoro
    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    sess = ort.InferenceSession(str(ROOT / "kokoro" / "kokoro-v1.0.int8.onnx"), so, providers=["CPUExecutionProvider"])
    k = Kokoro.from_session(sess, str(ROOT / "kokoro" / "voices-v1.0.bin"))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    save_only = "--save-only" in sys.argv
    voices = args or [v for v in k.get_voices() if v[:2] in KIND]
    out = ROOT / "kokoro" / "samples"
    out.mkdir(parents=True, exist_ok=True)
    pa = None if save_only else pyaudio.PyAudio()
    for i, v in enumerate(voices, 1):
        a, sr = k.create(LINE, voice=v, speed=1.1, lang="en-gb" if v.startswith("b") else "en-us")
        pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes()
        with wave.open(str(out / f"{v}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm)
        print(f"{i:2}/{len(voices)}  {v:12} {KIND[v[:2]]}", flush=True)
        if pa:
            st = pa.open(format=pyaudio.paInt16, channels=1, rate=sr, output=True)
            st.write(pcm)
            st.close()
            time.sleep(0.8)
    if pa:
        pa.terminate()
    print(f"samples in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
