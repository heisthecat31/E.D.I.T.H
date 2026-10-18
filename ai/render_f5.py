"""Render Cubie's lines in her cloned 2017 voice (F5-TTS fine-tuned on her clips) into the voice cache.
Runs in the voiceclone venv, on the GPU, with the game closed.

    J:\\EchoVR-Tools-Launcher\\voiceclone\\Scripts\\python.exe -I ai/render_f5.py --test        # samples per checkpoint
    ... ai/render_f5.py --ckpt model_1200.pt                                                  # every line -> cache

Lines: `satellite_ai.py --list-lines` (run first; written to H:\\SatelliteAI\\lines.txt). Each line is
saved as H:\\SatelliteAI\\voicecache\\<sha1("cubie_f5|<speed>|<text>")[:20]>.pcm (24 kHz mono int16), the
exact key satellite_ai.Voice looks up with config "voice": "cubie_f5". Lines that are her real
recordings are skipped (the recording plays). Existing files are kept, so it can resume.
Model: voiceclone\\Lib\\ckpts\\cubie\\model_*.pt (agent.md S26), reference clip: one of her lines.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

VC = Path(r"J:\EchoVR-Tools-Launcher\voiceclone")
ROOT = Path(r"H:\SatelliteAI")
LIB = Path(__file__).resolve().parent / "library"
VOICE = "cubie_f5"
#: her voice settings, picked by ear (user, 2026-10-18): a relaxed reference line (the excited
#: "stunning" one made every line sound ecstatic), seed 2, 3% lower pitch (resampled)
REF = (VC / "cubie_data" / "wavs" / "cubie_032.wav", "Well, you look festive.")
SEED = 2
PITCH = 0.97
#: other voices: (checkpoint folder, vocab, reference clip, its text, seed, pitch). "hra" = the Echo
#: Combat announcer woman EchoCombat cloned for its gear callouts (memory announcer-callouts)
VOICES = {
    "cubie_f5": ("cubie", "cubie_pinyin", REF[0], REF[1], SEED, PITCH),
    "hra_f5": ("hra", "hra_pinyin", VC / "dataset" / "wavs" / "8120_75941330_594548827.wav", "Return to avoid respawning.", 2, 1.0),
    #: HERA herself, a natural sentence (J:\EchoAudio\vo_2d__bus_1174689782__vo68, user: "this is hera")
    #: (padded with silence: the clip ends mid-sound, and each line's first word bled into it)
    "hera_f5": ("hra", "hra_pinyin", VC / "hera_ref_pad.wav",
                "At the matchmaking terminal ahead, you'll be able to warm up against bots before taking on real players.", 2, 1.0),
}
#: how fast each voice talks (F5 copies the reference's pace; the announcer's is quick: user "very fast")
PACE = {"hra_f5": 0.75, "hera_f5": 0.8}             # hera at 1.0 lost each line's first sentence
#: voices rendered a phrase at a time with real pauses between (user: "no spacing between words")
PHRASED = {"hra_f5"}
#: voices whose lines with short sentences ("Put me down. Right now.") are rendered a sentence at a
#: time, the short ones slower, with a pause between (user: "more spacing in some sentences which are short")
SENTENCED = {"hera_f5"}
SHORT_WORDS, SHORT_PACE, SENTENCE_GAP = 5, 0.6, 0.25
#: per-line takes the user picked by ear (a take can hiccup; another seed fixes it)
SEED_FOR = {"hera_f5": {"Take this! You asked for it.": 11}}
#: a slight machine tone (user: "add a slight robotic filter to them all since she is a robot"):
#: ring modulator mix at `hz`, and a short metallic comb (a copy `ms` later, mixed in)
ROBOT = {"hera_f5": {"ring": 0.12, "hz": 70.0, "comb": 0.3, "ms": 5.0}}


def robot(a, ring: float, hz: float, comb: float, ms: float):
    import numpy as np
    t = np.arange(len(a)) / 24000
    a = (1 - ring) * a + ring * a * np.sin(2 * np.pi * hz * t)
    d = int(24000 * ms / 1000)
    b = a.copy()
    b[d:] += comb * a[:-d]
    return b
TEST_LINES = ["Hey. Try not to bump me today.",
              "Take this! You asked for it.",
              "Sorry i dont quite know that one yet",
              "Echo VR is Ready At Dawn's zero gravity team game. Echo Arena is the disc sport."]


def key(text: str, speed: float) -> str:
    return hashlib.sha1(f"{VOICE}|{speed}|{text}".encode()).hexdigest()[:20]


def use_voice(name: str):
    """Switch every render to another voice (VOICES)."""
    global VOICE, REF, SEED, PITCH, CKDIR, VOCAB
    VOICE = name
    CKDIR, VOCAB, ref, text, SEED, PITCH = VOICES[name]
    REF = (ref, text)


CKDIR, VOCAB = "cubie", "cubie_pinyin"


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def load(ckpt: Path):
    os.environ.setdefault("HF_HOME", str(VC / "hf"))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from f5_tts.api import F5TTS
    return F5TTS(model="F5TTS_v1_Base", ckpt_file=str(ckpt),
                 vocab_file=str(VC / "Lib" / "data" / VOCAB / "vocab.txt"), device="cuda")


#: what the voice model reads, not what the line says (the cache key stays the line): it reads text
#: literally, so "Sorry i dont quite know that one yet" came out with a mangled "dont" (user)
SPOKEN = [(r"\bdont\b", "don't"), (r"\bcant\b", "can't"), (r"\bwont\b", "won't"), (r"\bisnt\b", "isn't"),
          (r"\bdoesnt\b", "doesn't"), (r"\bdidnt\b", "didn't"), (r"\bwasnt\b", "wasn't"), (r"\barent\b", "aren't"),
          (r"\bim\b", "I'm"), (r"\bive\b", "I've"), (r"\byoure\b", "you're"), (r"\bthats\b", "that's"),
          (r"\bwhats\b", "what's"), (r"\btheres\b", "there's"), (r"\bi\b", "I"),
          (r"^Sorry I don't", "Sorry, I don't"),
          (r"\b[Ee]dith\b", "Eedeth")]                          # "Edith" came out "idith"; the user picked this spelling


def spoken(text: str) -> str:
    t = text
    for a, b in SPOKEN:
        t = re.sub(a, b, t)
    return t if re.search(r"[.!?]$", t) else t + "."


def _ref_seconds() -> float:
    import wave
    with wave.open(str(REF[0])) as w:
        return w.getnframes() / w.getframerate()


def _infer(tts, text: str, seed: int | None, pace: float | None = None, min_s: float = 0.0):
    """min_s: at least this long (F5 sizes speech by characters, so short sentences came out rushed)."""
    import numpy as np
    pace = PACE.get(VOICE, 1.0) if pace is None else pace
    fix = None
    if min_s:
        ref = _ref_seconds()
        est = ref / max(1, len(REF[1].encode())) * len(text.encode()) / pace     # F5's own estimate
        fix = ref + max(est, min_s) if min_s > est else None
    wav, sr, _ = tts.infer(str(REF[0]), REF[1], text, nfe_step=32, speed=pace, show_info=lambda *a: None,
                           progress=None, seed=seed, fix_duration=fix)
    a = np.asarray(wav, dtype=np.float32)
    if sr != 24000:
        x = np.arange(0, len(a), sr / 24000)
        a = np.interp(x, np.arange(len(a)), a)
    return a


def _trim(a, floor: float = 0.02):
    """Silence off both ends (each phrase gets its own gap)."""
    import numpy as np
    loud = np.nonzero(np.abs(a) > floor * max(1e-6, float(np.abs(a).max())))[0]
    return a[max(0, loud[0] - 240):loud[-1] + 480] if len(loud) else a


def _widen_breaks(a, text: str, sents: list[str]):
    """The whole line rendered in one go (natural: per-sentence renders dropped words, stretching
    sounded robotic), then SENTENCE_GAP of silence added at each sentence break: the quietest
    20 ms near where that break falls by character count."""
    import numpy as np
    frame = 480
    env = np.array([np.abs(a[i:i + frame]).mean() for i in range(0, max(1, len(a) - frame), frame)])
    cuts, pos = [], 0
    for s in sents[:-1]:
        pos = text.find(s, pos) + len(s)
        if s.endswith(("!", "?")):                     # exclamations flow on ("Take this!" went robotic)
            continue
        c = int(pos / len(text) * len(env))
        lo, hi = max(1, c - len(env) // 8), min(len(env) - 1, c + len(env) // 8)
        if hi > lo:
            cuts.append((lo + int(np.argmin(env[lo:hi]))) * frame + frame // 2)
    out, last = [], 0
    for c in sorted(set(cuts)):
        out += [a[last:c], np.zeros(int(24000 * SENTENCE_GAP), np.float32)]
        last = c
    return np.concatenate(out + [a[last:]])


def speak(tts, text: str, seed: int | None = None, pitch: float | None = None):
    import numpy as np
    seed = SEED_FOR.get(VOICE, {}).get(text, SEED) if seed is None else seed
    pitch = PITCH if pitch is None else pitch
    t = spoken(text)
    if VOICE in PHRASED:                                       # one phrase at a time, gaps between
        parts = [p.strip() for p in re.findall(r"[^.!?,;]+[.!?,;]*", t) if p.strip(" .!?,;")]
        chunks = []
        for i, p in enumerate(parts):
            chunks.append(_trim(_infer(tts, p if re.search(r"[.!?]$", p) else p.rstrip(",;") + ".", seed)))
            if i < len(parts) - 1:
                chunks.append(np.zeros(int(24000 * (0.14 if p.endswith((",", ";")) else 0.3)), np.float32))
        a = np.concatenate(chunks)
    elif VOICE in SENTENCED:
        # one-word sentences ("Wow.", "No.") alone (inside a line F5 swallowed them; alone they
        # survive), the rest in natural runs (longer pieces alone came out garbled), each run's short
        # sentence breaks widened; a pause between pieces
        sents = [s.strip() for s in re.findall(r"[^.!?]+[.!?]*", t) if s.strip(" .!?")] or [t]
        pieces: list[list[str]] = []
        for s in sents:
            if len(s.split()) == 1 or not pieces or len(pieces[-1][-1].split()) == 1:
                pieces.append([s])
            else:
                pieces[-1].append(s)
        chunks = []
        for i, p in enumerate(pieces):
            text = " ".join(p)
            text = text if re.search(r"[.!?]$", text) else text + "."
            a = _trim(_infer(tts, text, seed, SHORT_PACE if len(p) == 1 and len(p[0].split()) == 1 else None))
            if len(p) > 1 and min(len(s.split()) for s in p) <= SHORT_WORDS:
                a = _widen_breaks(a, text, p)
            chunks.append(a)
            if i < len(pieces) - 1:
                chunks.append(np.zeros(int(24000 * SENTENCE_GAP), np.float32))
        a = np.concatenate(chunks)
    else:
        a = _infer(tts, t, seed)
    if pitch != 1.0:                                           # lower: resampled (a touch slower too)
        a = np.interp(np.arange(0, len(a), pitch), np.arange(len(a)), a)
    if VOICE in ROBOT:
        a = robot(a, **ROBOT[VOICE])
    a = a / max(1e-6, float(np.abs(a).max())) * 0.85
    return (a * 32767).astype(np.int16).tobytes()


def main() -> int:
    import wave
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="a few samples per checkpoint -> H:\\SatelliteAI\\f5_test")
    ap.add_argument("--ckpt", default="model_last.pt", help="checkpoint in voiceclone\\Lib\\ckpts\\cubie")
    ap.add_argument("--speed-key", type=float, default=None, help="voice_speed in the cache key (config's)")
    ap.add_argument("--voice", default="cubie_f5", choices=sorted(VOICES))
    ap.add_argument("--sample", help="render these lines (one per line in a file) to H:\SatelliteAI\samples_<voice>")
    ap.add_argument("--extra", help="also render the lines in this file (voicecache/missing_cubie_f5.txt), then empty it")
    a = ap.parse_args()
    use_voice(a.voice)
    ckdir = VC / "Lib" / "ckpts" / CKDIR
    if a.sample:
        out = ROOT / f"samples_{a.voice}"
        out.mkdir(exist_ok=True)
        tts = load(ckdir / a.ckpt)
        for i, t in enumerate(l for l in Path(a.sample).read_text(encoding="utf-8").splitlines() if l.strip()):
            with wave.open(str(out / f"{i + 1:02d}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(speak(tts, t))
            print(f"{i + 1:02d} {t}", flush=True)
        return 0
    if a.test:
        out = ROOT / "f5_test"
        out.mkdir(exist_ok=True)
        for ck in sorted(ckdir.glob("model_[0-9]*.pt"), key=lambda p: int(re.findall(r"\d+", p.stem)[0])):
            tts = load(ck)
            for i, t in enumerate(TEST_LINES, 1):
                pcm = speak(tts, t)
                with wave.open(str(out / f"{ck.stem}_{i}.wav"), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
            print(f"{ck.name}: {len(TEST_LINES)} samples", flush=True)
            del tts
        print(f"samples in {out}")
        return 0
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    speed = a.speed_key if a.speed_key is not None else cfg.get("voice_speed", 1.1)
    lines = [l for l in (ROOT / "lines.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.extra and Path(a.extra).exists():                     # lines she spoke in the fallback voice
        lines = list(dict.fromkeys(lines + [l for l in Path(a.extra).read_text(encoding="utf-8").splitlines() if l.strip()]))
    rec = json.loads((LIB / "recordings.json").read_text(encoding="utf-8"))["lines"]
    recorded = {norm(t) for t in rec} if VOICE == "cubie_f5" else set()   # her 2017 clips: old voice only
    cache = ROOT / "voicecache"
    cache.mkdir(exist_ok=True)
    todo = [l for l in lines if norm(l) not in recorded and not (cache / f"{key(l, speed)}.pcm").exists()]
    print(f"{len(lines)} lines, {len(todo)} to render with {a.ckpt} (speed key {speed})", flush=True)
    tts = load(ckdir / a.ckpt)
    t0 = time.time()
    if a.extra and Path(a.extra).exists():
        Path(a.extra).write_text("", encoding="utf-8")         # taken: they're in this batch
    for i, l in enumerate(todo, 1):
        try:
            (cache / f"{key(l, speed)}.pcm").write_bytes(speak(tts, l))
        except Exception as e:  # noqa: BLE001 -- one bad line doesn't stop the batch
            print(f"  failed: {l!r}: {e}", flush=True)
        if i % 25 == 0 or i == len(todo):
            el = time.time() - t0
            print(f"  {i}/{len(todo)}  {el / i:.2f} s/line, ~{(len(todo) - i) * el / i / 60:.0f} min left", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
