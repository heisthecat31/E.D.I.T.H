"""Her real 2017 recordings: copy the clips next to the library (24 kHz mono raw PCM, the voice cache's
format), write recordings.json (exact line text -> clip files, one per take), and put each line into
the lists it fits (reactions, small talk, the chat bank's generated JSON is left alone: chat lines
are added in chat_5_original.py). Safe to run again: nothing is added twice.

    python ai/library/add_recordings.py

Source: Echo VR Christmas 2017 (mpl_lobby_a_xmas bank 7ccf82aba6bc50a2), decoded with vgmstream,
transcribed with Whisper and checked by ear (out/xmas2017/vo/dataset, agent.md S26). The voice player
(satellite_ai.Voice) plays the real clip whenever she says one of these lines word for word.
"""
from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SRC = HERE.parent.parent / "out" / "xmas2017" / "vo" / "dataset"
OUT = HERE / "recordings"

#: where each of her lines goes: reaction event/tier, or small talk intent (replies)
PLACES = {
    "Hey, I'm not a snow globe.": [("grabbed", "first"), ("grabbed", "again"), ("thrown", "first")],
    "What? Hey!": [("bumped", "first"), ("headbutt", "first")],
    "Hey!": [("bumped", "first"), ("bumped", "again"), ("headbutt", "again")],
    "Hey, come on!": [("bumped", "again"), ("thrown", "again"), ("headbutt", "again")],
    "Oh my.": [("released", "first"), ("hit wall", "first")],
    "Think fast.": [("threw snowball", "first"), ("threw snowball", "again")],
    "I'll just leave this here.": [("threw snowball", "first"), ("threw snowball", "lots")],
    "Chill out.": [("threw snowball", "again"), ("angry push", None)],
    "Hello!": [("intent", "hello")],
    "Oh hi!": [("intent", "hello")],
    "Hi, how's it going?": [("intent", "hello")],
    "Oh, uh, hi.": [("intent", "hello")],
    "Welcome. Happy holidays.": [("intent", "hello"), ("intent", "christmas")],
    "Nice to meet you.": [("intent", "hello")],
    "Aww, you look great!": [("intent", "compliment"), ("intent", "cute")],
    "Well, you look festive.": [("intent", "christmas")],
    "Ooh, I give it a ten.": [("intent", "good_job"), ("intent", "wow")],
    "Very nice.": [("intent", "good_job"), ("intent", "wow")],
    "What sport do you play after wrapping presents? Boxing!": [("intent", "joke")],
    "What do you call a snowman by a fireplace? A puddle!": [("intent", "joke")],
    "Are you ready to deck some halls?": [("intent", "christmas")],
    "Who wants snow cones?": [("intent", "christmas")],
    "Mmm, frosty.": [("intent", "happy")],
    "Ooh, so cozy.": [("intent", "happy")],
}


def to_pcm24(path: Path) -> bytes:
    w = wave.open(str(path))
    sr, ch = w.getframerate(), w.getnchannels()
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    w.close()
    if ch > 1:
        a = a.reshape(-1, ch).mean(1)
    if sr != 24000:
        x = np.arange(0, len(a), sr / 24000)
        a = np.interp(x, np.arange(len(a)), a)
    a = a / max(1e-6, float(np.abs(a).max())) * 0.85
    return (a * 32767).astype(np.int16).tobytes()


def main() -> int:
    meta = json.loads((SRC / "metadata.json").read_text())
    OUT.mkdir(exist_ok=True)
    rec: dict[str, list[str]] = {}
    for m in meta:
        f = OUT / (Path(m["file"]).stem + ".pcm")
        f.write_bytes(to_pcm24(SRC / m["file"]))
        rec.setdefault(m["text"], []).append(f.name)
    (HERE / "recordings.json").write_text(json.dumps(
        {"_about": "Her real 2017 lines: text -> takes (recordings/*.pcm, 24 kHz mono int16). Made by "
                   "add_recordings.py; the voice plays these instead of the synthesized voice.",
         "lines": rec}, indent=1), encoding="utf-8")
    r = json.loads((HERE / "reactions.json").read_text(encoding="utf-8"))
    s = json.loads((HERE / "smalltalk.json").read_text(encoding="utf-8"))
    intents = {i["id"]: i for i in s["intents"]}
    added = 0
    for line, places in PLACES.items():
        assert line in rec, line
        for kind, tier in places:
            if kind == "intent":
                lst = intents[tier]["replies"]
            elif tier is None:
                lst = r[kind]
            else:
                lst = r["events"][kind].setdefault(tier, [])
            if line not in lst:
                lst.append(line)
                added += 1
    (HERE / "reactions.json").write_text(json.dumps(r, indent=1, ensure_ascii=True), encoding="utf-8")
    (HERE / "smalltalk.json").write_text(json.dumps(s, indent=1, ensure_ascii=True), encoding="utf-8")
    print(f"{len(rec)} recorded lines ({sum(len(v) for v in rec.values())} takes), {added} placements added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
