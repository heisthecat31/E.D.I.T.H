"""Her voice pack: the rendered lines in H:\\SatelliteAI\\voicecache -> out/EdithVoice, minus broken
cloned-voice renders (docs/brainplan.md). Ships as plugins\\EdithVoice\\<key>.pcm; the companion
(ai/edith_ears.py) plays a reply's line from it by key, and only streams what it lacks.

    H:\\SatelliteAI\\venv\\Scripts\\python.exe -I tools/make_voice_pack.py [--out DIR] [--install]
        --install    also copy it into the game's plugins folder (both installs, when present)

Keys are the brain's (Railway/SparkAPI/edith_brain.py voice_key: sha1 of voice|speed|text): every
line in her live library (Railway/SparkAPI/edith_library), its sentences, what she was taught
(H:\\SatelliteAI\\memory.json), and H:\\SatelliteAI\\lines.txt, in her voice and the fallback voice.
A cache file no known line maps to is left out (old voices, old speeds); --unmapped keeps them.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SPARK = HERE.parent / "Railway" / "SparkAPI"
ROOT = Path(os.environ.get("SATELLITE_AI", r"H:\SatelliteAI"))
GAMES = [Path(r"C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena\bin\win10\plugins"),
         Path(r"H:\ready-at-dawn-echo-arena\bin\win10\plugins")]
RATE = 24000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / "voicecache"))
    ap.add_argument("--out", default=str(HERE / "out" / "EdithVoice"))
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--unmapped", action="store_true")
    a = ap.parse_args()

    os.environ.update(EDITH_STT="0", EDITH_TTS="0", DATA_DIR=tempfile.mkdtemp(prefix="edithpack"),
                      EDITH_LIBRARY=str(SPARK / "edith_library"))
    sys.path.insert(0, str(SPARK))
    import edith_brain as b                                       # noqa: E402

    lib = b.LIB.get()
    cfg = lib.cfg
    voice, fb, speed = cfg["voice"], cfg["fallback_voice"], cfg["voice_speed"]
    raw = lib.all_lines(knowledge=True) + [cfg["unknown"]]
    try:
        raw += [x for e in json.loads((ROOT / "memory.json").read_text(encoding="utf-8")).get("learned", []) for x in e["a"]]
    except (OSError, ValueError):
        pass
    for f in (ROOT / "lines.txt", Path(a.cache) / f"missing_{voice}.txt"):
        if f.exists():
            raw += f.read_text(encoding="utf-8").splitlines()
    texts = set()
    for line in raw:
        if "{time}" in line or "{date}" in line:
            continue
        t = b.say_clean(b.drop_name(line).replace("{me}", cfg["name"]))
        if t:
            texts.add(t)
            texts.update(b.sentences(t))
    keys = {}                                                     # key -> (voice, text)
    for t in texts:
        keys[b.voice_key(voice, speed, t)] = (voice, t)
        keys[b.voice_key(fb, speed, t)] = (fb, t)

    cache, out = Path(a.cache), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    have = {f.stem: f for f in cache.glob("*.pcm")}
    n = {"copied": 0, "broken": 0, "unmapped": 0, "same": 0}
    size = 0
    for key, f in have.items():
        hit = keys.get(key)
        if hit is None and not a.unmapped:
            n["unmapped"] += 1
            continue
        if hit and hit[0] == voice and voice != fb:               # her cloned voice: a blip?
            secs = f.stat().st_size / 2 / RATE
            ref = have.get(b.voice_key(fb, speed, hit[1]))
            if (ref and secs < 0.5 * ref.stat().st_size / 2 / RATE) or secs < 0.12 * max(len(hit[1].split()), 1):
                n["broken"] += 1
                (out / f.name).unlink(missing_ok=True)
                continue
        dst = out / f.name
        size += f.stat().st_size
        if dst.exists() and dst.stat().st_size == f.stat().st_size:
            n["same"] += 1
            continue
        shutil.copyfile(f, dst)
        n["copied"] += 1
    mine = sum(1 for k in have if keys.get(k, ("",))[0] == voice)
    print(f"{len(texts)} lines known; cache {len(have)} files ({mine} in {voice})")
    print(f"pack {out}: {n['copied']} copied, {n['same']} already there, {n['broken']} broken {voice} renders left out, "
          f"{n['unmapped']} unmapped left out; {size / 1e6:.0f} MB")
    (out / "pack.json").write_text(json.dumps({"voice": voice, "fallback": fb, "speed": speed}), encoding="utf-8")
    if a.install:
        for g in GAMES:
            if g.is_dir():
                dst = g / "EdithVoice"
                shutil.copytree(out, dst, dirs_exist_ok=True)
                print("installed:", dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
