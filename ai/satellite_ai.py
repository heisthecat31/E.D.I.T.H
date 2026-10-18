"""The satellite's local AI: she hears you, remembers what you do, and acts on what you say.

    H:\\SatelliteAI\\venv\\Scripts\\python.exe ai/satellite_ai.py            # run alongside the game
    ... ai/satellite_ai.py --text "edith, come here"                     # no mic: one line, for testing
    ... ai/satellite_ai.py --setup                                       # fetch the models only

Everything runs on this PC and lives in H:\\SatelliteAI (agent.md S22, S23):
  mic (PyAudio, 16 kHz) -> speech found by level (adaptive noise floor) -> Whisper base.en
  (faster-whisper) -> wake word (her name) -> answers from her library only, no live model (ai/library:
  places, memory, orders, small talk, Echo VR / Lone Echo knowledge, the chat bank; anything else gets
  "Sorry i dont quite know that one yet", logged to H:\\SatelliteAI\\unknown.txt) -> orders to
  EDITH.dll over UDP 127.0.0.1:47321 -> her reply (every line pre-rendered in the voice cache)
  spoken by Kokoro, out of HER speaker in game (EDITH.dll, UDP 127.0.0.1:47323: Echo's own
  3D sound, from where she is) or, without it, through the default output.
EDITH.dll sends events (grabbed, thrown, headbutt, bumped, snowballs, a state line every 2 s) to
127.0.0.1:47322: she reacts out loud (ai/library/reactions.json), and the notable ones and what you
tell her go into H:\\SatelliteAI\\memory.json, which is in every prompt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import random
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))      # (-I leaves the script folder out)
from library import Library                                     # noqa: E402

ROOT = Path(os.environ.get("SATELLITE_AI", r"H:\SatelliteAI"))
CONFIG = ROOT / "config.json"
MEMORY = ROOT / "memory.json"
VOICE_CACHE = ROOT / "voicecache"
DEFAULTS = {
    "name": "Edith",
    # her name (user, 2026-10-17: Edith, was Cubie) and Whisper's likely spellings of it
    "wake_words": ["edith", "edit", "edyth", "edeth", "eadith", "eddith", "editha", "edie", "eadie", "satellite"],
    "follow_up_seconds": 8,               # after she answers, no name needed for this long
    "whisper": "base.en",                 # 0.8 s per 3 s clip on the CPU (small.en: 2.7 s)
    "whisper_device": "cpu",              # cpu | cuda | auto (the GPU is the game's: cpu by default)
    "cpu_threads": 4,                     # of 16: leave the rest to the game
    "player_name": "",                    # your in-game name; "" = read it from the game's log
    "game_logs": [r"H:\ready-at-dawn-echo-arena\_local\r14logs",
                  r"C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena\_local\r14logs"],
    "voice": "af_heart",                  # Kokoro voice (samples in H:\\SatelliteAI\\kokoro)
    "voice_speed": 1.1,
    "voice_out": "auto",                  # auto (her speaker in game when it's on, else local) | game | local
    "react": True,                        # she says something when bumped, grabbed, thrown, ...
    "mean": True,                         # she gets angry: shoves you, and shuts your echo unit down
    "push_after": 2,                      # every 2 grabs / throws she shoves you (user, 2026-10-18)
    "shutdown_after": 5,                  # the 5th attack (grab, throw, headbutt) shuts your unit down
    "attack_forget_s": 120,               # this long without an attack and she forgets the count
    # who she listens to (user, 2026-10-18; docs/networkplan.md): everyone, the nicest first
    "ignore_below": 5.0,                  # score -N: with someone nicer around, their orders are refused
    "cancel_after": 3,                    # this many bad things in a row wipe someone's nice points
    "mean_fade_s": 90,                    # one mean point fades this often (nice points are kept)
    "order_hold_s": 60,                   # an order holds this long against someone meaner
    "hear_voip": True,                    # hear other players on voice chat (EDITH.dll, UDP 47324)
    "mic_device": None,                   # PyAudio input index; None = default
    "speech_level": 2.5,                  # speech = this many times the noise floor
    "silence_ms": 500,
    "max_utterance_s": 12,
    "unknown": "Sorry i dont quite know that one yet",   # what she says to anything not in her library
}
CMD = ("127.0.0.1", 47321)
EVENTS = ("127.0.0.1", 47322)
SPEAKER = ("127.0.0.1", 47323)
ORDERS = {"follow", "come", "stay", "look", "home", "spin", "flip", "stop", "push", "shutdown", "throw", "goto", "mark"}


def cfg() -> dict:
    c = dict(DEFAULTS)
    if CONFIG.exists():
        c.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    else:
        CONFIG.write_text(json.dumps(c, indent=2), encoding="utf-8")
    return c


def log(*a):
    line = " ".join([time.strftime("[%H:%M:%S]")] + [str(x) for x in a])
    print(line, flush=True)
    try:
        with open(ROOT / "satellite_ai.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def say_clean(text: str) -> str:
    """What she may say: no emoji or other symbols, no stage directions, never the word
    "coming" (user, 2026-10-17)."""
    t = re.sub(r"\*[^*]*\*|\([^)]*\)|\[[^\]]*\]", " ", text)           # *waves*, (laughs), [beep]
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("_", " ").replace("\u2014", ", ").replace("\u2013", ", ").replace("\u2026", "...")
    t = "".join(ch for ch in t if ch.isascii() and (ch.isalnum() or ch in " .,!?'\"-:;"))
    t = re.sub(r"\b[Cc]oming\b", lambda m: "on my way" if m.group(0)[0] == "c" else "On my way", t)
    t = re.sub(r"\s+([.,!?])", r"\1", re.sub(r"\s+", " ", t)).strip(" ,;:-")
    return t


# ---- memory ------------------------------------------------------------------------------------

def you_form(text: str) -> str:
    """What the player said about themself, as she'd say it back: "my dog" -> "your dog"."""
    swaps = {"i": "you", "i'm": "you're", "im": "you're", "i've": "you've", "i'll": "you'll", "i'd": "you'd",
             "me": "you", "my": "your", "mine": "yours", "myself": "yourself", "am": "are", "was": "were"}
    return " ".join(swaps.get(w.lower(), w) for w in text.split())


class Person:
    """One player as she sees them: points (user, 2026-10-18; docs/networkplan.md "Who she listens
    to"). +1 nice for each kind thing they say to or about her (or do: a gentle hold, when they're
    nice), +1 mean for each mean thing said or done (an insult, a throw, a headbutt, a grab from
    someone who isn't nice). Their score is nice - mean. Mean points fade (1 per `mean_fade_s`);
    nice ones are kept, until `cancel_after` bad things in a row wipe them: then she's mean back.
    Kept per player, so one person's bullying never gets someone else shoved."""

    def __init__(self, name: str):
        self.name = name
        self.nice, self.mean = 0, 0.0
        self.streak = 0                                                # bad things in a row
        self.mean_at = time.time()                                     # (mean points fade from here)
        self.bad_acts = 0                                              # bad actions since her last shove
        self.last_spoke = 0.0
        self.awake_until = 0.0                                         # their follow-up window (no name needed)
        self.asked, self.asked_at = "", 0.0                            # an order she was stubborn about
        self.last_snow = 0.0

    fade_s = 90.0                                                  # (config mean_fade_s, set in main)

    def _fade(self):
        now = time.time()
        self.mean = max(0.0, self.mean - (now - self.mean_at) / self.fade_s)
        self.mean_at = now

    def score(self) -> float:
        self._fade()
        return self.nice - self.mean

    def good(self, why: str):
        self._fade()
        self.nice += 1
        self.streak = 0
        log(f"  {self.name}: +1 nice ({why}) -> nice {self.nice}, mean {self.mean:.1f}, score {self.score():+.1f}")

    def bad(self, why: str, cancel_after: int = 3) -> bool:
        """+1 mean. True when this made `cancel_after` in a row and wiped their nice points."""
        self._fade()
        self.mean += 1
        self.streak += 1
        wiped = self.streak >= cancel_after and self.nice > 0
        if wiped:
            self.nice, self.streak = 0, 0
        log(f"  {self.name}: +1 mean ({why}) -> nice {self.nice}, mean {self.mean:.1f}, score {self.score():+.1f}"
            + (" -- nice points wiped" if wiped else ""))
        return wiped


class Memory:
    """facts: things worth keeping (model-picked); profile: what you told her about yourself
    (nickname, likes, dislikes, favorites, notes); events: what happened (from the game and the
    conversation), newest last, capped; places: saved spots; state: her latest state line."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"facts": [], "events": [], "turns": [], "places": {},
                     "profile": {"nickname": "", "likes": [], "dislikes": [], "favorites": {}, "notes": []},
                     "learned": []}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except ValueError:
                pass
        p = self.data.setdefault("profile", {})
        for k, v in (("nickname", ""), ("likes", []), ("dislikes", []), ("favorites", {}), ("notes", [])):
            p.setdefault(k, v)
        for f in list(self.data.get("facts", [])):                    # old "likes X" facts -> profile
            m = re.match(r"likes? (.+)", f)
            if m and m.group(1) not in p["likes"]:
                p["likes"].append(m.group(1))
        self.state, self.state_time = "", 0.0
        self.quiet_until = 0.0                                         # "be quiet": no reactions till then
        self.last_push = self.last_shutdown = 0.0
        self.last_unknown, self.last_unknown_at = "", 0.0              # what she couldn't answer (to be taught)
        self.last_move = "spin"                                        # what "keep going" keeps doing
        self.spinning = False                                          # an endless spin / flip is on
        # the match (EDITH.dll's state line): you, everyone in her room, and her role there
        self.me, self.members, self.role = "", [], ""
        self.people: dict[str, Person] = {}
        for n, v in (self.data.get("points") or {}).items():          # her points from last time
            p = self.people[n] = Person(n)
            p.nice, p.mean, p.mean_at = int(v.get("nice", 0)), float(v.get("mean", 0)), float(v.get("at", time.time()))
        self.order_by, self.order_at = "", 0.0                         # who gave the order she's carrying out
        self.favour, self.favour_at = None, 0.0                        # her favourite, as last told to the DLL
        self.forwarded: dict[str, float] = {}                          # name -> last speech their own companion sent
        self.with_ai: set[str] = set()                                 # members whose own companion runs (the relay's room)
        self.muted, self.muted_at = False, 0.0                         # you, muted on Echo's voice chat (EDITH.dll)
        self.client_speaker, self.client_speaker_at = False, 0.0       # her speaker in your own game (the client's)

    def person(self, who: str | None = None) -> Person:
        """A player by name; None is you (this machine's player)."""
        who = who or self.me or "you"
        p = self.people.get(who)
        if p is None:
            p = self.people[who] = Person(who)
        return p

    def score(self, who: str | None = None) -> float:
        """`who`'s points with her (nice - mean; you by default)."""
        return self.person(who).score()

    def is_me(self, who: str | None) -> bool:
        return not who or who == self.me or (not self.me and who == "you")

    def save(self):
        with self.lock:
            self.data["points"] = {n: {"nice": p.nice, "mean": round(p.mean, 2), "at": p.mean_at}
                                   for n, p in self.people.items()}   # (kept across restarts)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    def event(self, text: str):
        with self.lock:
            self.data["events"].append(f"{time.strftime('%Y-%m-%d %H:%M')} {text}")
            self.data["events"] = self.data["events"][-500:]
        self.save()

    def count_today(self, prefix: str) -> int:
        today = time.strftime("%Y-%m-%d")
        with self.lock:
            return sum(1 for e in self.data["events"] if e.startswith(today) and e[17:].startswith(prefix))

    def fact(self, text: str):
        text = text.strip()
        if not text:
            return
        with self.lock:
            if text not in self.data["facts"]:
                self.data["facts"].append(text)
                self.data["facts"] = self.data["facts"][-300:]
        self.save()

    def profile(self) -> dict:
        return self.data["profile"]

    def add(self, kind: str, item: str):
        item = item.strip(" .!?,")
        if not item:
            return
        with self.lock:
            lst = self.data["profile"][kind]
            if item.lower() not in [x.lower() for x in lst]:
                lst.append(item)
                del lst[:-100]
            other = {"likes": "dislikes", "dislikes": "likes"}.get(kind)
            if other:                                                  # you changed your mind
                self.data["profile"][other] = [x for x in self.data["profile"][other] if x.lower() != item.lower()]
        self.save()

    def forget(self, what: str) -> int:
        w = set(re.findall(r"[a-z0-9]+", what.lower())) - {"the", "a", "that", "my", "i", "about"}
        if not w:
            return 0
        n = 0
        with self.lock:
            p = self.data["profile"]
            for kind in ("likes", "dislikes", "notes"):
                keep = [x for x in p[kind] if not (w & set(re.findall(r"[a-z0-9]+", x.lower())))]
                n += len(p[kind]) - len(keep)
                p[kind] = keep
            for k in [k for k in p["favorites"] if w & set(k.split())]:
                del p["favorites"][k]
                n += 1
            facts = [f for f in self.data["facts"] if not (w & set(re.findall(r"[a-z0-9]+", f.lower())))]
            n += len(self.data["facts"]) - len(facts)
            self.data["facts"] = facts
        self.save()
        return n

    def recall(self, about: str, need: int = 1) -> str | None:
        """A note / like / favorite that shares words with `about`."""
        w = set(re.findall(r"[a-z0-9]+", about.lower())) - {"the", "a", "that", "my", "i", "about", "what", "remember"}
        p = self.data["profile"]
        best, hit = 0, None
        for kind, items in (("note", p["notes"]), ("like", p["likes"]), ("dislike", p["dislikes"]),
                            ("fact", self.data["facts"])):
            for x in items:
                s = len(w & set(re.findall(r"[a-z0-9]+", x.lower())))
                if s > best:
                    best, hit = s, (kind, x)
        for k, v in p["favorites"].items():
            s = len(w & set(k.split())) + len(w & set(v.lower().split()))
            if s > best:
                best, hit = s, ("favorite", f"your favorite {k} is {v}")
        if not hit or best < need:
            return None
        kind, x = hit
        return {"like": f"you like {x}", "dislike": f"you don't like {x}"}.get(kind, x)

    def turn(self, who: str, text: str):
        with self.lock:
            self.data["turns"].append([who, text])
            self.data["turns"] = self.data["turns"][-16:]
        self.save()

    def player_pos(self) -> list[float] | None:
        m = re.search(r"player=([-\d.]+),([-\d.]+),([-\d.]+)", self.state)
        return [float(m.group(i)) for i in (1, 2, 3)] if m else None

    def in_lobby(self) -> bool:
        """EDITH.dll's state line is fresh: she is loaded in this lobby and steered here."""
        return time.time() - self.state_time < 6.0

    def speaker_on(self) -> bool:
        """Her speaker plays in your game: your client says so (when a server steers her), or the
        state line does (when she's steered here)."""
        if time.time() - self.client_speaker_at < 6.0:
            return self.client_speaker
        return "speaker=1" in self.state and time.time() - self.state_time < 6.0

    def mark(self, place: str) -> bool:
        """Save where the player is now as `place`."""
        pos = self.player_pos()
        if not pos or not place.strip():
            return False
        with self.lock:
            places = self.data.setdefault("places", {})
            places.pop(place.strip().lower(), None)           # (saved again: it's the last one now)
            places[place.strip().lower()] = pos
        self.save()
        return True

    def forget_place(self, name: str) -> str | None:
        hit = self.place(name)
        if not hit:
            return None
        with self.lock:
            self.data["places"].pop(hit[0], None)
        self.save()
        return hit[0]

    # -- what you teach her: her memory bank grows (user, 2026-10-18) --
    def teach(self, said: str, answer: str) -> dict:
        """Remember `answer` for `said` (and things like it). The same question again adds an answer."""
        said, answer = said.strip(" .!?,"), answer.strip(" ,")
        key = re.sub(r"[^a-z0-9 ]", "", said.lower()).strip()
        with self.lock:
            for e in self.data.setdefault("learned", []):
                if key in [re.sub(r"[^a-z0-9 ]", "", q.lower()).strip() for q in e["q"]]:
                    if answer not in e["a"]:
                        e["a"].append(answer)
                    break
            else:
                e = {"id": f"learned_{len(self.data['learned']) + 1}", "q": [said], "a": [answer],
                     "at": time.strftime("%Y-%m-%d")}
                self.data["learned"].append(e)
        self.save()
        return e

    def unlearn(self, about: str) -> int:
        w = set(re.findall(r"[a-z0-9]+", about.lower())) - {"the", "a", "to", "what", "you", "say", "i"}
        with self.lock:
            before = len(self.data.get("learned", []))
            self.data["learned"] = [e for e in self.data.get("learned", [])
                                    if not any(w and w <= set(re.findall(r"[a-z0-9]+", q.lower())) for q in e["q"])]
            n = before - len(self.data["learned"])
        self.save()
        return n

    def place(self, name: str) -> tuple[str, list[float]] | None:
        """A saved place by name (loose: 'cosmetics' finds 'the cosmetic area')."""
        n = re.sub(r"\b(the|area|spot|place|room)\b", "", name.lower()).strip(" .,!?")
        with self.lock:
            places = dict(self.data.get("places", {}))
        if n in ("", "there", "that", "it", "my", "our", "same", "that same", "last") and places:
            k = list(places)[-1]                               # "go back to the spot": the one saved last
            return k, places[k]
        for k, v in places.items():
            kk = re.sub(r"\b(the|area|spot|place|room)\b", "", k).strip()
            if n and (n == kk or n.rstrip("s") == kk.rstrip("s") or (len(n) >= 4 and (n in kk or kk in n))):
                return k, v
        import difflib                                         # misheard: "cosmetic abia", "cosmetric"
        best = max(places, key=lambda k: difflib.SequenceMatcher(None, name.lower(), k).ratio(), default=None)
        if best and difflib.SequenceMatcher(None, name.lower().strip(" .,!?"), best).ratio() >= 0.75:
            return best, places[best]
        return None

    def summary(self) -> str:
        """What happened lately, counted: 'you threw her 3 times today' is what she should know."""
        with self.lock:
            ev = list(self.data["events"])
        today = time.strftime("%Y-%m-%d")
        kinds = {}
        for e in ev:
            if e.startswith(today):
                k = e[17:].split(" speed")[0]
                kinds[k] = kinds.get(k, 0) + 1
        counts = ", ".join(f"{k} x{n}" for k, n in sorted(kinds.items(), key=lambda x: -x[1])[:8])
        return f"today: {counts or 'nothing yet'}\nlatest: " + "; ".join(e[11:] for e in ev[-8:])

    def about_player(self) -> str:
        p = self.data["profile"]
        parts = []
        if p["nickname"]:
            parts.append(f"wants to be called {p['nickname']}")
        if p["likes"]:
            parts.append("likes " + ", ".join(p["likes"][-8:]))
        if p["dislikes"]:
            parts.append("dislikes " + ", ".join(p["dislikes"][-6:]))
        if p["favorites"]:
            parts.append("; ".join(f"favorite {k}: {v}" for k, v in list(p["favorites"].items())[-6:]))
        if p["notes"]:
            parts.append("; ".join(p["notes"][-8:]))
        return "\n".join(f"- {x}" for x in parts + [f for f in self.data["facts"][-10:]]) or "- (nothing yet)"


# ---- game events: she reacts ---------------------------------------------------------------------

#: EDITH.dll event -> (reaction name, memory text); released carries "thrown" or "bump"
def classify(text: str) -> tuple[str | None, str]:
    if text == "grabbed":
        return "grabbed", "you grabbed her"
    if text.startswith("released"):
        if text.endswith("thrown"):
            return "thrown", "you threw her"
        return "released", "you let her go"
    if text == "headbutt":
        return "headbutt", "you headbutted her"
    if text == "bumped":
        return "bumped", "she got bumped"
    if text == "hit wall":                                   # her own fault: just "ow", no anger
        return "hit wall", ""
    if text.startswith("threw snowball (revenge)"):
        return "threw snowball", "she threw a snowball at you"
    if text.startswith("threw snowball"):
        return None, "she threw a snowball at you (you asked)"
    if text.startswith("pushed player"):
        return None, "she shoved you"
    if text.startswith("shut player down"):
        return None, "she shut your echo unit down"
    if text.startswith("dizzy") or text.startswith("stopped spinning"):
        return None, ""
    return None, text


def say_async(voice: "Voice | None", line: str):
    if voice and line:
        threading.Thread(target=voice.say, args=(line,), daemon=True).start()


#: her face for each reaction (EDITH.dll "face <mood> <seconds>": a port per mood face, user's
#: picks from the CubeSat face sheet, 2026-10-18); she goes back to happy after the seconds
FACES = {"grabbed": ("surprised", 4), "thrown": ("hurt", 5), "headbutt": ("dizzy", 6), "bumped": ("annoyed", 4),
         "hit wall": ("hurt", 3), "released": ("happy", 0), "threw snowball": ("angry", 4)}


def show_face(mood: str, seconds: float = 0):
    send_order(f"face {mood} {seconds:g}")


#: what she does when someone is mean (no names, ever)
MEAN_BACK = ["That's it. We're done being friends.", "Wow. And I liked you.", "Okay. You asked for this.",
             "All those nice points? Gone."]
NICE_HOLD = ["Hehe. Okay, you can hold me.", "Careful with me.", "Ooh, a lift.", "Fine, but no throwing."]


def judge_act(c: dict, mem: "Memory", lib: Library, voice: "Voice | None", react: str, who: str | None) -> bool:
    """Points for what someone did to her, and her answer when it's bad. A throw or a headbutt is
    always mean, and so is a bump (a knock from their hand or body); a grab only from someone who isn't nice (nice people may hold her); her
    own walls are nothing. Three bad things in a row wipe their nice points and she's mean back (a
    snowball); while their score is below 0 she shoves them every `push_after` bad actions and
    shuts their echo unit down at -`shutdown_after`. True if she answered (no stock reaction)."""
    p = mem.person(who)
    to = f" to={p.name}" if p.name != "you" else ""
    if react == "grabbed" and p.score() > 0:
        if voice and not voice.speaking.is_set():
            line = random.choice(NICE_HOLD)
            log(f"{c['name']} (held by a friend, {p.name}): {line!r}")
            show_face("happy", 4)
            say_async(voice, line)
        return True
    if react not in ("thrown", "headbutt", "grabbed", "bumped"):   # (bumps too: "hit her with things", user)
        return False
    wiped = p.bad(react, c.get("cancel_after", 3))
    tell_favourite(mem)
    mem.save()
    if not c.get("mean", True):
        return False
    now = time.time()
    p.bad_acts += 1
    if p.score() <= -c.get("shutdown_after", 5):
        p.bad_acts = 0
        p.mean = max(0.0, p.mean - 3)                          # (one shutdown, not one per hit)
        mem.last_shutdown = now
        send_order("shutdown" + to)
        show_face("angry", 10)
        line = fill(c, mem, lib.mood("angry shutdown") or "")
        log(f"{c['name']} ({p.name} at {p.score():+.1f}: shutdown): {line!r}")
        say_async(voice, line)
        return True
    if wiped:                                                  # nice and mean out of step: mean back
        p.last_snow = now
        send_order("throw" + to)
        show_face("angry", 8)
        line = random.choice(MEAN_BACK)
        log(f"{c['name']} ({p.name}'s nice points wiped: snowball): {line!r}")
        say_async(voice, line)
        return True
    if p.score() < 0 and p.bad_acts >= c.get("push_after", 2):
        p.bad_acts = 0
        mem.last_push = now
        send_order("push 9" + to)
        show_face("angry", 8)
        line = fill(c, mem, lib.mood("angry push") or "")
        log(f"{c['name']} ({p.name} at {p.score():+.1f}: push): {line!r}")
        say_async(voice, line)
        return True
    return False


def as_who(mem: "Memory", text: str, who: str | None) -> str:
    """A memory line about you, about someone else instead: "you threw her" -> "Bob threw her"."""
    return text if mem.is_me(who) or not text else re.sub(r"\byou\b", who, text)


def favourite(mem: "Memory") -> str:
    """Who she likes best right now: the one in her room with the most points; a tie goes to whoever
    talked to her last, then you (docs/networkplan.md "Who she listens to")."""
    names = [n for n in mem.members if n] or [mem.me or "you"]
    return min(names, key=lambda n: (-round(mem.score(n), 1), -mem.person(n).last_spoke, not mem.is_me(n)))


def tell_favourite(mem: "Memory"):
    """The DLL follows / looks at her favourite when no order names someone: tell it on a change
    (and every 10 s, in case the game restarted)."""
    if not mem.me:
        return
    f = favourite(mem)
    if f != mem.favour or time.time() - mem.favour_at > 10:
        if f != mem.favour:
            log(f"favourite: {f} ({', '.join(f'{n} {mem.score(n):+.1f}' for n in (mem.members or [f]))})")
        send_order(f"favour {f if f != 'you' else ''}".strip())
        mem.favour, mem.favour_at = f, time.time()


def read_state(mem: "Memory", line: str):
    mem.state, mem.state_time = line, time.time()
    m = re.search(r"\bme=(\S*)", line)
    if m and m.group(1):
        mem.me = _ME["name"] = m.group(1)
    m = re.search(r"\bnet=(\S*)", line)
    mem.role = m.group(1) if m else ""
    m = re.search(r"\bmembers=(\S*)", line)
    mem.members = [n for n in (m.group(1).split(",") if m else []) if n]
    m = re.search(r"\bai=(\S*)", line)
    mem.with_ai = {n for n in (m.group(1).split(",") if m else []) if n}


def listen_events(c: dict, mem: Memory, lib: Library, voice: "Voice | None", stop: threading.Event, heard_q: queue.Queue):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(EVENTS)
    s.settimeout(0.5)
    while not stop.is_set():
        try:
            msg = s.recv(2048).decode("utf-8", "replace")
        except socket.timeout:
            continue
        if msg.startswith("state "):
            read_state(mem, msg[6:])
            tell_favourite(mem)
        elif msg.startswith("mute "):                          # muted in game: she doesn't hear your mic
            m = re.search(r"\bme=(\S+)", msg)                  # (your client says who you are: a server's
            if m:                                              #  state lines don't know)
                mem.me = _ME["name"] = m.group(1)
            m = re.search(r"\bspeaker=(\d)", msg)              # her speaker in YOUR game (the client's)
            if m:
                mem.client_speaker, mem.client_speaker_at = m.group(1) == "1", time.time()
            muted = msg[5:].split()[0] == "1"
            if muted != mem.muted:
                log("you're muted on voice chat: not listening to your mic" if muted else "you're unmuted: listening to your mic")
            mem.muted, mem.muted_at = muted, time.time()
        elif msg.startswith("heard "):                         # another player's companion heard them
            parts = msg[6:].split(" ", 1)
            if len(parts) == 2 and parts[0]:
                mem.forwarded[parts[0]] = time.time()          # (their voice chat is then not needed)
                heard_q.put(("text", parts[1], parts[0], time.time()))
        elif msg.startswith("event "):
            text = msg[6:]
            m = re.search(r"\s+by=(\S*)", text)
            who = (m.group(1) or None) if m else None
            text = re.sub(r"\s+(?:by|to)=\S*", "", text).strip()
            log("game:", text, f"(by {who})" if who else "")
            react, remember = classify(text)
            if remember:
                mem.event(as_who(mem, remember, who))
            m = re.match(r"(dizzy|stopped spinning) t=(\d+)", text)
            if m:
                show_face("dizzy", 4)
            elif react in FACES:                                   # in the red: angry, not just hurt
                show_face(*(("angry", 6) if react in ("thrown", "headbutt") and mem.score(who) < 0 else FACES[react]))
            if m and voice and not voice.speaking.is_set() and time.time() > mem.quiet_until:
                line = lib.dizzy_line(int(m.group(2))) if m.group(1) == "dizzy" else lib.mood("stopped spinning")
                if line:
                    line = fill(c, mem, line)
                    log(f"{c['name']} ({text}): {line!r}")
                    say_async(voice, line)
                continue
            if judge_act(c, mem, lib, voice, react or "", who):
                continue
            if react and voice and c.get("react", True) and not voice.speaking.is_set() and time.time() > mem.quiet_until:
                line = lib.reaction(react, mem.count_today(as_who(mem, remember, who)))
                if line:
                    line = fill(c, mem, line)
                    log(f"{c['name']} (reacts to {react}): {line!r}")
                    threading.Thread(target=voice.say, args=(line,), daemon=True).start()


def carry_out(mem: "Memory", acts: list[str], place: str = "", who: str | None = None) -> list[str]:
    """Orders to EDITH.dll; mark / goto resolved here (places live in memory.json). Orders about
    a player are aimed at `who` (the one who asked)."""
    done = []
    for a in acts:
        if a == "mark":
            if mem.mark(place):
                done.append(f"mark {place}")
                mem.event(as_who(mem, f"you showed her the {place}", who))
        elif a == "goto":
            hit = mem.place(place)
            if hit:
                send_order("goto %.2f %.2f %.2f" % tuple(hit[1]))
                done.append(f"goto {hit[0]}")
        else:
            send_order(aim(mem, a, who))
            done.append(a)
            if a.startswith(("spin", "flip")):
                mem.last_move = a
    return done


def aim(mem: "Memory", order: str, who: str | None) -> str:
    """The order about the player who asked: "follow" -> "follow Bob", "push 9" -> "push 9 to=Bob".
    Your own orders name you too once the DLL knows your name (then a favourite doesn't steal them)."""
    name = who or mem.me
    if not name or name == "you" or "to=" in order:
        return order
    if order in ("follow", "come"):
        return f"{order} {name}"
    if order.split()[0] in ("throw", "push", "shutdown"):
        return f"{order} to={name}"
    return order


#: what she says when she won't do what someone asks (no names, ever)
STUBBORN = ["Make me.", "Hmm. No.", "Ask nicer.", "Why should I?", "Say please."]
GRUDGING = ["Ugh. Fine.", "Fine. But I'm not happy about it.", "Okay, okay. Only because you asked twice.",
            "Fine. You owe me."]
REFUSE_BUSY = ["I'm busy with someone nicer.", "Someone nicer asked first.", "Nope. I'm with the nice one."]
REFUSE_MEAN = ["Not for you.", "You lost listening privileges.", "Be nicer first."]


def refusal(c: dict, mem: "Memory", who: str | None, order: str = "", said: str = "") -> tuple[str | None, str | None]:
    """She takes orders from everyone, but not equally (user, 2026-10-18). Someone nicer than whoever
    asks keeps her: their order holds `order_hold_s` against a meaner one, and with others in her
    room someone very mean (score <= -`ignore_below`) is refused outright. Alone with someone mean
    she still listens, just stubborn: the first ask is refused, the same ask again (or one with
    "please") is done, grumbling. Returns (refusal line, grumble line): (None, None) obeys gladly."""
    p = mem.person(who)
    sc = p.score()
    now = time.time()
    ob = mem.order_by
    if ob and ob != p.name and now - mem.order_at < c.get("order_hold_s", 60) and mem.score(ob) > sc:
        log(f"  refused {p.name} ({sc:+.1f}): busy with {ob} ({mem.score(ob):+.1f})")
        return random.choice(REFUSE_BUSY), None
    others = [n for n in mem.members if n and n != p.name]
    if others and sc <= -c.get("ignore_below", 5.0) and any(mem.score(n) > sc for n in others):
        log(f"  refused {p.name} ({sc:+.1f}): too mean, and someone nicer is here")
        return random.choice(REFUSE_MEAN), None
    if sc < 0:
        if (p.asked == order and now - p.asked_at < 20) or re.search(r"\bplease\b", said, re.I):
            p.asked = ""
            log(f"  {p.name} ({sc:+.1f}) asked again: done, grumbling")
            return None, random.choice(GRUDGING)
        p.asked, p.asked_at = order, now
        log(f"  stubborn with {p.name} ({sc:+.1f}): ask again")
        return random.choice(STUBBORN), None
    return None, None


def obey(mem: "Memory", who: str | None):
    mem.order_by, mem.order_at = mem.person(who).name, time.time()


SELF = ("127.0.0.1", 47325)                                    # your own client: push / shutdown YOUR body
_ME = {"name": ""}                                             # (your name, from the state line)


def send_order(order: str):
    """An order to EDITH.dll. A push or shutdown aimed at you goes to your own client (SELF):
    online only your client moves your body; whoever steers her (a server) can't."""
    words = order.split()
    to = next((w[3:] for w in words if w.startswith("to=")), "")
    at_you = words and words[0] in ("push", "shutdown") and (not to or to == _ME["name"] or to == "you")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(" ".join(w for w in words if not w.startswith("to=")).encode() if at_you else order.encode(),
                 SELF if at_you else CMD)


# ---- names ---------------------------------------------------------------------------------------

def player_name(c: dict) -> str:
    """The player's in-game name: config "player_name", else the newest game log's login line
    ("displayname":"NAME [ip]" -> NAME); "" when only the offline demo account is there."""
    if c.get("player_name"):
        return c["player_name"]
    logs = []
    for d in c.get("game_logs", []):                          # each folder's newest 30 (offline
        try:                                                    # test runs only log "demo")
            logs += sorted(Path(d).glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)[:30]
        except OSError:
            pass
    for f in sorted(logs, key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            names = re.findall(r'"displayname":"([^"]+)"', f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for n in reversed(names):
            n = re.sub(r"\s*\[[^\]]*\]$", "", n).strip()
            if n and n.lower() not in ("demo", "accountname"):     # offline demo / server placeholder
                return n
    return ""


_NAME = {"name": None, "at": 0.0}


def call_name(c: dict, mem: Memory) -> str:
    """What she calls you: the nickname you gave her, else your in-game name (cached 60 s)."""
    if mem.profile()["nickname"]:
        return mem.profile()["nickname"]
    if _NAME["name"] is None or time.time() - _NAME["at"] > 60:
        _NAME["name"], _NAME["at"] = player_name(c), time.time()
    return _NAME["name"] or ""


def drop_name(line: str) -> str:
    """She never says anyone's name, she just talks to you (user, 2026-10-18): "{name}" goes, with
    its comma: "Hey {name}!" -> "Hey!", "{name}, you're back" -> "You're back", "Go {name}!" -> "Go!"."""
    t = re.sub(r",\s*\{name\}(?=[\s.!?,]|$)", "", line)              # "Good night, {name}."
    t = re.sub(r"(^|(?<=[.!?]\s))\{name\},?\s*(\w)", lambda m: m.group(1) + m.group(2).upper(), t)
    t = re.sub(r"\s*\{name\}", "", t)                                 # "Hey {name}!", "Go {name}!"
    return re.sub(r"\s+([.!?,])", r"\1", t).strip()


def fill(c: dict, mem: Memory, line: str) -> str:
    line = drop_name(line).replace("{me}", c["name"])
    line = line.replace("{time}", time.strftime("%I:%M %p").lstrip("0")).replace("{date}", time.strftime("%A, %B %d").replace(" 0", " "))
    return line


# ---- ears --------------------------------------------------------------------------------------

def load_whisper(c: dict):
    from faster_whisper import WhisperModel
    import numpy as np
    root = str(ROOT / "whisper")
    if c["whisper_device"] in ("auto", "cuda"):
        try:
            where = cuda_dlls()
            m = WhisperModel(c["whisper"], device="cuda", compute_type="int8_float16", download_root=root)
            list(m.transcribe(np.zeros(16000, dtype=np.float32), language="en")[0])   # really runs?
            log("whisper on CUDA (DLLs from", where, ")")
            return m
        except Exception as e:  # noqa: BLE001 -- no CUDA runtime for ctranslate2: use the CPU
            log("whisper on CUDA failed, CPU instead:", str(e)[:120])
    return WhisperModel(c["whisper"], device="cpu", compute_type="int8", cpu_threads=c["cpu_threads"],
                        download_root=root)


def cuda_dlls():
    """ctranslate2 (Whisper) needs CUDA 12's cuBLAS and cuDNN 9 DLLs: cuBLAS from Ollama's folder,
    cuDNN from a CUDA PyTorch install if there is one (config "cuda_dll_dirs" adds more)."""
    dirs = [d.parent for d in sorted((ROOT / "ollama").rglob("cublas64_12.dll"))[:1]]
    try:
        for base in [Path(sys.base_prefix) / "Lib" / "site-packages" / "torch" / "lib"] + \
                    [Path(p) for p in cfg().get("cuda_dll_dirs", [])]:
            if (base / "cudnn64_9.dll").exists():
                dirs.append(base)
    except Exception:  # noqa: BLE001
        pass
    for d in dirs:
        os.add_dll_directory(str(d))
        os.environ["PATH"] = str(d) + os.pathsep + os.environ["PATH"]
    return [str(d) for d in dirs] or None


def utterances(c: dict, out: queue.Queue, stop: threading.Event, mute: threading.Event | None = None):
    """Mic -> chunks of speech (16 kHz float32), found by level against a moving noise floor."""
    import numpy as np
    import pyaudio
    pa = pyaudio.PyAudio()
    rate, frame = 16000, 480                                   # 30 ms frames
    st = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, input=True, frames_per_buffer=frame,
                 input_device_index=c["mic_device"])
    import collections
    noise, speech, quiet, buf = 200.0, False, 0, []
    pre = collections.deque(maxlen=10)                         # 0.3 s before speech starts
    while not stop.is_set():
        x = np.frombuffer(st.read(frame, exception_on_overflow=False), dtype=np.int16).astype(np.float32)
        if mute is not None and mute.is_set():             # she is talking: don't hear herself
            speech, buf = False, []
            pre.clear()
            continue
        lvl = float(np.sqrt(np.mean(x * x)) + 1e-3)
        if not speech:
            noise = 0.97 * noise + 0.03 * lvl
            if lvl > noise * c["speech_level"] and lvl > 150:
                speech, quiet, buf = True, 0, list(pre) + [x]
            else:
                pre.append(x)
        else:
            buf.append(x)
            quiet = quiet + 1 if lvl < noise * c["speech_level"] * 0.6 else 0
            if quiet * 30 > c["silence_ms"] or len(buf) * 0.03 > c["max_utterance_s"]:
                speech = False
                if len(buf) > 10:                              # > 0.3 s
                    out.put(("audio", np.concatenate(buf) / 32768.0, None, time.time()))   # (None: you)


VOIP = ("127.0.0.1", 47324)


def voip_utterances(c: dict, mem: "Memory", out: queue.Queue, stop: threading.Event):
    """Her ears on voice chat (EDITH.dll copies each remote player's voice: "VOIP" + rate u32 +
    name length u8 + name + int16 mono) -> each player's speech, found by level like the mic's, as
    ("audio", 16 kHz float32, name). Not on a puppet (the host hears everyone), and not for a player
    whose own companion runs (the room's ai list) or forwarded speech lately: they're heard through
    it (their own mic, which follows their in-game mute), so no double answers."""
    import numpy as np
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(VOIP)
    except OSError:
        log("voice chat: port 47324 busy: she can't hear voice chat")
        return
    s.settimeout(0.1)
    streams: dict[str, dict] = {}
    seen: set[str] = set()

    def finish(name: str, st: dict):
        st["speech"] = False
        if len(st["buf"]) > 10:                                # > 0.3 s
            out.put(("audio", np.concatenate(st["buf"]) / 32768.0, name, time.time()))
        st["buf"] = []

    while not stop.is_set():
        now = time.time()
        for name, st in streams.items():                       # a voice that just stopped sending: done
            if st["speech"] and now - st["last"] > c["silence_ms"] / 1000:
                finish(name, st)
        try:
            pkt = s.recv(65536)
        except socket.timeout:
            continue
        if len(pkt) < 9 or pkt[:4] != b"VOIP":
            continue
        rate, n = int.from_bytes(pkt[4:8], "little"), pkt[8]
        name = pkt[9:9 + n].decode("utf-8", "replace") or "someone"
        if name not in seen:
            seen.add(name)
            log(f"voice chat: hearing {name} ({rate} Hz)")
        # a player with their own companion is heard through it, never here (no double answers)
        if mem.role == "puppet" or name in mem.with_ai or now - mem.forwarded.get(name, 0) < 30:
            continue
        x = np.frombuffer(pkt[9 + n:], dtype=np.int16).astype(np.float32)
        if rate and rate != 16000 and len(x):
            x = np.interp(np.arange(0, len(x), rate / 16000), np.arange(len(x)), x)
        st = streams.setdefault(name, {"noise": 200.0, "speech": False, "quiet": 0, "buf": [], "pre": [], "rest": np.zeros(0, np.float32)})
        st["last"] = now
        x = np.concatenate([st["rest"], x])
        k = 0
        while k + 480 <= len(x):                               # 30 ms frames, as the mic
            f = x[k:k + 480]
            k += 480
            lvl = float(np.sqrt(np.mean(f * f)) + 1e-3)
            if not st["speech"]:
                st["noise"] = 0.97 * st["noise"] + 0.03 * lvl
                if lvl > st["noise"] * c["speech_level"] and lvl > 150:
                    st["speech"], st["quiet"], st["buf"] = True, 0, st["pre"] + [f]
                else:
                    st["pre"] = (st["pre"] + [f])[-10:]
            else:
                st["buf"].append(f)
                st["quiet"] = st["quiet"] + 1 if lvl < st["noise"] * c["speech_level"] * 0.6 else 0
                if st["quiet"] * 30 > c["silence_ms"] or len(st["buf"]) * 0.03 > c["max_utterance_s"]:
                    finish(name, st)
        st["rest"] = x[k:]


# ---- voice -------------------------------------------------------------------------------------

class Voice:
    """Kokoro (82M, int8 ONNX, CPU) in H:\\SatelliteAI\\kokoro, 24 kHz mono. Every line rendered is
    kept in memory and on disk (H:\\SatelliteAI\\voicecache), and the stock lines (orders, small talk,
    reactions, knowledge answers) are rendered at start in the background, so they play at once.
    Longer lines are spoken sentence by sentence: the first plays while the rest renders.
    Out: her speaker in game (EDITH.dll, UDP 47323, Echo's 3D sound from where she is) when the
    plugin reports it on, else the default output device."""

    RATE = 24000

    def __init__(self, c: dict, mem: Memory):
        from kokoro_onnx import Kokoro
        import onnxruntime as ort
        so = ort.SessionOptions()                              # 2 threads: Whisper, Qwen and the game
        so.intra_op_num_threads = int(c.get("voice_threads", 2))   # keep the rest (all cores made
        so.inter_op_num_threads = 1                            # the model 10x slower while warming)
        sess = ort.InferenceSession(str(ROOT / "kokoro" / "kokoro-v1.0.int8.onnx"), so,
                                    providers=["CPUExecutionProvider"])
        self.k = Kokoro.from_session(sess, str(ROOT / "kokoro" / "voices-v1.0.bin"))
        self.busy = threading.Event()                          # hearing / thinking: warming waits
        self.voice, self.speed = c["voice"], c.get("voice_speed", 1.0)
        # a voice Kokoro doesn't have (cubie_f5: her cloned 2017 voice) is pre-rendered offline into
        # the cache (ai/render_f5.py); a line it lacks is spoken in the Kokoro fallback voice, cached
        # under that voice's own key, and listed in voicecache/missing_<voice>.txt for the next batch
        self.kokoro_voice = self.voice if self.voice in self.k.get_voices() else c.get("fallback_voice", "af_heart")
        # her real 2017 recordings (ai/library/recordings.json): played whenever a sentence is one of them
        self.recordings: dict[str, list[Path]] = {}
        rf = Path(__file__).resolve().parent / "library" / "recordings.json"
        if rf.exists() and self.voice in c.get("recordings_for", ["cubie_f5"]):   # her old voice only
            for line, takes in json.loads(rf.read_text(encoding="utf-8"))["lines"].items():
                self.recordings[self._key(line)] = [rf.parent / "recordings" / t for t in takes]
        self.out = c.get("voice_out", "auto")
        self.mem = mem
        self.cache: dict[str, bytes] = {}
        self.speaking = threading.Event()
        self.lock = threading.Lock()
        self.render_lock = threading.Lock()
        VOICE_CACHE.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(text: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()

    def _file(self, text: str, voice: str | None = None) -> Path:
        h = hashlib.sha1(f"{voice or self.voice}|{self.speed}|{text}".encode()).hexdigest()[:20]
        return VOICE_CACHE / f"{h}.pcm"

    def recorded(self, text: str) -> bytes | None:
        takes = self.recordings.get(self._key(text))
        return random.choice(takes).read_bytes() if takes else None

    def broken(self, f: Path, text: str) -> bool:
        """A cloned-voice render that came out as a blip (F5 fails on short lines: "On my way!" was
        0.13 s, a noise, against 0.9 s in af_heart; 27 of 501 lines, 2026-10-18): under half the
        Kokoro voice's length, or under 0.12 s a word."""
        if self.kokoro_voice == self.voice or not f.exists():
            return False
        secs = f.stat().st_size / 2 / self.RATE
        ref = self._file(text, self.kokoro_voice)
        if ref.exists() and secs < 0.5 * ref.stat().st_size / 2 / self.RATE:
            return True
        return secs < 0.12 * max(len(text.split()), 1)

    def ready(self, text: str) -> bool:
        """Playable at once: a recording, cached in memory, or pre-rendered in her voice."""
        f = self._file(text)
        return self._key(text) in self.recordings or text in self.cache or (f.exists() and not self.broken(f, text))

    def render(self, text: str) -> bytes:
        import numpy as np
        rec = self.recorded(text)
        if rec is not None:
            return rec
        if text in self.cache:
            return self.cache[text]
        f = self._file(text)
        bad = self.broken(f, text)                             # a blip: the fallback voice says it (and
        if bad:                                                # it isn't queued again: F5 would fail again)
            log(f"voice: her render of {text!r} is broken ({f.stat().st_size / 2 / self.RATE:.2f} s): {self.kokoro_voice} instead")
        if (bad or not f.exists()) and self.kokoro_voice != self.voice:     # not pre-rendered in her voice
            f = self._file(text, self.kokoro_voice)
            if not f.exists() and not bad:
                try:
                    with open(VOICE_CACHE / f"missing_{self.voice}.txt", "a", encoding="utf-8") as m:
                        m.write(text + "\n")
                except OSError:
                    pass
        if f.exists():
            pcm = f.read_bytes()
        else:
            with self.render_lock:                             # one Kokoro run at a time
                a, sr = self.k.create(text, voice=self.kokoro_voice, speed=self.speed, lang="en-us")
            if sr != self.RATE:                                # (Kokoro is 24 kHz; just in case)
                x = np.linspace(0, len(a) - 1, int(len(a) * self.RATE / sr))
                a = np.interp(x, np.arange(len(a)), a)
            pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes()
            try:
                f.write_bytes(pcm)
            except OSError:
                pass
        if len(self.cache) < 1500:
            self.cache[text] = pcm
        return pcm

    def warm(self, lines: list[str]):
        """Render (or load from disk) every stock line, quietly, in the background."""
        t0, n = time.time(), 0
        for t in lines:
            try:
                if self.ready(t) or self._file(t, self.kokoro_voice).exists():
                    if t not in self.cache and self._key(t) not in self.recordings:
                        self.render(t)                         # just load it
                    continue
                while self.busy.is_set() or self.speaking.is_set():
                    time.sleep(0.2)                            # you come first
                n += 1
                self.render(t)
                time.sleep(0.05)
            except Exception:  # noqa: BLE001
                pass
        log(f"voice: {len(lines)} stock lines ready ({n} newly rendered, {time.time() - t0:.0f} s)")

    def to_game(self) -> bool:
        return self.out == "game" or (self.out == "auto" and self.mem.speaker_on())

    def say(self, text: str):
        text = say_clean(text)
        if not text:
            return
        sentences = [p for p in re.split(r"(?<=[.!?])\s+", text) if p]
        # whole when it's ready (or short); else sentence by sentence, so a sentence that is one of her
        # real recordings plays as the recording and the next renders while one plays
        split = len(sentences) > 1 and (len(text) >= 60 or any(self._key(x) in self.recordings for x in sentences))
        parts = [text] if self.ready(text) or not split else sentences
        with self.lock:
            self.speaking.set()
            try:
                if self.to_game():
                    self._game(parts)
                else:
                    self._local(parts)
            finally:
                time.sleep(0.4)                                # her tail in the room
                self.speaking.clear()

    def _rendered(self, parts: list[str]):
        """Each part's PCM, the next one rendering while the current one plays."""
        nxt: list = [None]

        def bg(p, box):
            box[0] = self.render(p)
        for i, p in enumerate(parts):
            pcm = nxt[0] if nxt[0] is not None else self.render(p)
            nxt = [None]
            th = None
            if i + 1 < len(parts):
                th = threading.Thread(target=bg, args=(parts[i + 1], nxt), daemon=True)
                th.start()
            yield pcm
            if th:
                th.join()

    def _local(self, parts: list[str]):
        import pyaudio
        pa = pyaudio.PyAudio()
        st = pa.open(format=pyaudio.paInt16, channels=1, rate=self.RATE, output=True)
        try:
            for pcm in self._rendered(parts):
                st.write(pcm)
        finally:
            st.close()
            pa.terminate()

    def _game(self, parts: list[str]):
        """Stream to EDITH.dll: 0.1 s datagrams, 0.4 s ahead of real time (it plays after a
        120 ms prebuffer), then wait for the rest to play out."""
        chunk = self.RATE // 10 * 2                            # 0.1 s of int16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            t0, sent = time.time(), 0.0
            for pcm in self._rendered(parts):
                for i in range(0, len(pcm), chunk):
                    s.sendto(pcm[i:i + chunk], SPEAKER)
                    sent += len(pcm[i:i + chunk]) / 2 / self.RATE
                    ahead = sent - (time.time() - t0)
                    if ahead > 0.4:
                        time.sleep(ahead - 0.4)
            left = sent - (time.time() - t0) + 0.15
            if left > 0:
                time.sleep(left)


# ---- what you say: instant answers first --------------------------------------------------------

#: short commands she carries out at once (no model): (order, pattern, her stock lines)
INSTANT = [
    ("follow", r"\b(follow\w*|come with me|with me)\b", ["Right behind you!", "Following!", "Lead the way!"]),
    ("come", r"\b(come (here|over|back|to me)|over here|get over here|come)\b", ["On my way!", "Zoom zoom!", "Here I come!"]),
    ("home", r"\b(go home|home|spawn|go back to (the )?(start|middle|centre|center))\b", ["Heading home!", "Back to base!"]),
    ("stay", r"\b(stay|stop|wait|hold on|freeze|stay there)\b", ["Staying put.", "Hovering here.", "Okay, I'll wait."]),
    ("spin", r"\b(spin|twirl|barrel roll|do a flip)\b", ["Wheee!", "Spinny time!"]),
    ("throw", r"\b(throw|snowball|hit me|balls?)\b", ["Incoming!", "Catch!", "Take this!"]),
]


def instant(text: str) -> tuple[str, list[str]] | None:
    """A short line (up to 6 words) asking for exactly one order -> (order, lines)."""
    t = text.lower().strip(" .!?,")
    if len(t.split()) > 8 or "?" in text:
        return None
    hits = [(o, lines) for o, pat, lines in INSTANT if re.search(pat, t)]
    if len(hits) > 1:                                          # "follow ball": the order said first
        hits.sort(key=lambda h: re.search(next(p for o, p, _ in INSTANT if o == h[0]), t).start())
        return hits[0]
    return hits[0] if hits else None


NUMBERS = {"one": 1, "once": 1, "two": 2, "twice": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10}
MOVE_LINES = {
    "spin": ["Wheee!", "Spinny time!", "Round I go!"],
    "flip front": ["Front flip!", "Watch this!", "Hup!"],
    "flip back": ["Back flip!", "Nailed it!", "Backwards, wheee!"],
    "flip left": ["Barrel roll!", "Roll!"],
    "flip right": ["Barrel roll!", "Roll the other way!"],
    "keep": ["Okay, I'll keep going till you say stop.", "Fine, but you'd better say stop.", "Forever? Okay. Your funeral."],
    "stop": ["Stopping. Whoa.", "Phew. Okay.", "Finally."],
}


def move_instant(c: dict, mem: "Memory", lib: Library, text: str) -> tuple[str, str] | None:
    """Spins, flips, keep going, stop, push and shutdown, without the model -> (order, her line)."""
    t = text.lower().strip(" .!?,")
    if len(t.split()) > 12:
        return None
    keep = bool(re.search(r"\b(keep (going|spinning|flipping|back ?flipping|front ?flipping|doing (it|that)|it up)|"
                          r"don'?t stop|until i (say|tell you)|till i (say|tell you)|"
                          r"forever|non ?stop|endless(ly)?)\b", t))
    if re.search(r"^(ok(ay)? |alright |now )?(stop|enough|that'?s enough|you can stop|stop (it|spinning|flipping|now)|quit it)$", t) \
            or (mem.spinning and not keep and re.search(r"\b(stop|enough|halt)\b", t)):
        if mem.spinning:
            mem.spinning = False
            return "stop", lib.pick("move/stop", MOVE_LINES["stop"])
        return None
    move = None
    if re.search(r"\b(back ?flip(s|ping)?|backwards flips?|backflood)\b", t):
        move = "flip back"
    elif re.search(r"\b(front ?flip(s|ping)?|forward flips?|flip(s|ping)?)\b", t):
        move = "flip front"
    elif re.search(r"\b(barrel roll|side ?flips?|cartwheels?|roll)\b", t):
        move = "flip right" if "right" in t else "flip left"
    elif re.search(r"\b(spin|spinning|twirl)\b", t):
        move = "spin"
    elif keep and re.search(r"\b(going|doing (it|that)|it up|until|till)\b", t):
        move = mem.last_move                                        # "keep going until I say so"
    if move:
        n = re.search(r"\b(\d+|one|once|two|twice|three|four|five|six|ten)\b", t)
        turns = (int(n.group(1)) if n.group(1).isdigit() else NUMBERS[n.group(1)]) if n else 1
        mem.last_move = move
        mem.spinning = keep
        order = f"{move} keep" if keep else (f"{move} {turns}" if turns > 1 else move)
        return order, lib.pick("move/keep" if keep else "move/" + move, MOVE_LINES["keep" if keep else move])
    if re.search(r"\b(shut (me|my (echo )?unit|my echo) down|shoot me down|shutdown|shut down|kill me|respawn me|reset me|"
                 r"power me (off|down))\b", t):
        # asking to be killed only gets you shoved (user): shutdowns are her temper's (judge_act)
        mem.last_push = time.time()
        return "push", fill(c, mem, lib.mood("asked shutdown") or "")
    throw_me = re.search(r"\bthrow me\b", t) and not re.search(r"\bthrow me (a|an|one|some|your|another|that|this)\b|snow", t)
    if re.search(r"\b(push|shove|knock|launch|yeet|fling|bump|toss) me\b", t) or throw_me:
        hard = re.search(r"\b(hard|harder|really|far|max)\b", t)
        mem.last_push = time.time()
        return ("push 12" if hard else "push"), fill(c, mem, lib.mood("asked push") or "")
    return None


def is_question(text: str) -> bool:
    """Asked, not just said: a stock fact only answers a question ("Hit." got the stun tip)."""
    t = text.lower().strip()
    return "?" in t or bool(re.match(r"(what|whats|what's|who|whos|who's|how|when|where|why|which|is|are|was|were|do|does|did|"
                                      r"can|could|tell me|explain|describe|define)\b", t))


#: "remember this spot AS / TO BE / CALLED / NAMED / IS the lone echo" (user said "to be": it became a note)
SPOT_NAMED = r"\b(?:as|to be|called|named|is)\b"


def memory_instant(c: dict, mem: Memory, text: str) -> str | None:
    """Remember / recall without the model. Returns her reply, or None."""
    t = re.sub(r"^((?:cubie|edith),?\s*|hey\s+|please\s+|can you\s+|could you\s+)+", "", text.strip(), flags=re.I).strip(" .!?,")
    lo = t.lower()
    p = mem.profile()
    # -- what you tell her --
    m = re.match(r"(?:call me|my name is|i'm called|im called|you can call me)\s+(.+)$", lo)
    if m:
        nick = t[-len(m.group(1)):].strip(" .!?,").title()
        p["nickname"] = nick
        mem.save()
        mem.event(f"you told her to call you {nick}")
        return random.choice(["Noted. I'm still not saying it out loud. I don't do names.",
                              "Got it. Names aren't my thing, but I'll know it's you."])
    m = re.match(r"my (?:favou?rite|fave) ([a-z ]{2,30}?) (?:is|are) (.+)$", lo)
    if m:
        thing, val = m.group(1).strip(), t[-len(m.group(2)):].strip(" .!?,")
        p["favorites"][thing] = val
        mem.save()
        return f"{val}, your favorite {thing}. Got it!"
    m2 = re.match(r"(.+?),?\s+(?:remember that|remember it|don'?t forget (?:that|it)|got it)$", lo)
    if m2 and not re.search(r"\b(this|here|spot|place)\b", m2.group(1)):   # "the capital of france is paris, remember that"
        note = you_form(t[:len(m2.group(1))].strip(" .!?,"))
        mem.add("notes", note)
        return f"Got it: {note}."
    if re.match(r"(what'?s|what is|what was) the first thing you (said|told me)$", lo):
        with mem.lock:
            first = next((x for w, x in mem.data.get("turns", []) if w == "her"), None)
        return f"First thing I said? {first}" if first else "I don't remember. I talk a lot."
    m = re.match(r"(?:remember|don't forget|dont forget|note) (?:that )?(.+)$", lo)
    if m and not re.search(r"\b(this|here|spot|place)\b.*" + SPOT_NAMED, lo):
        note = you_form(t[-len(m.group(1)):].strip(" .!?,"))
        mem.add("notes", note)
        return f"Got it: {note}."
    m = re.match(r"i (?:really )?(?:like|love|enjoy|adore) (?!you\b)(.+)$", lo)
    if m and len(m.group(1).split()) <= 6:
        thing = t[-len(m.group(1)):].strip(" .!?,")
        mem.add("likes", thing)
        return random.choice([f"You like {thing}? Noted.", f"{thing}, good taste.", f"I'll remember you like {thing}."])
    m = re.match(r"i (?:really )?(?:hate|don't like|dont like|can't stand|cant stand|dislike) (?!you\b)(.+)$", lo)
    if m and len(m.group(1).split()) <= 6:
        thing = t[-len(m.group(1)):].strip(" .!?,")
        mem.add("dislikes", thing)
        return random.choice([f"No {thing} then. Noted.", f"Got it, you don't like {thing}."])
    m = re.match(r"forget (?:that |about )?(.+)$", lo)
    if m:
        what = m.group(1)
        if what in ("everything", "everything about me", "all of it"):
            mem.data["profile"] = {"nickname": "", "likes": [], "dislikes": [], "favorites": {}, "notes": []}
            mem.data["facts"] = []
            mem.save()
            return "Done. Who are you again? Kidding. Mostly."
        n = mem.forget(what)
        return "Forgotten." if n else "I didn't have anything about that."
    # -- what you ask her --
    if re.match(r"(what's|whats|what is|do you know|say) my name\??$", lo):
        n = call_name(c, mem)
        return random.choice(["I don't do names. You're you, and that's plenty.",
                              "Names? Not my thing. I know who you are though."])
    if re.match(r"(what do you (know|remember)( about me)?|what have you learned about me|what do you remember)$", lo):
        bits = []
        if p["likes"]:
            bits.append("you like " + ", ".join(p["likes"][-3:]))
        if p["dislikes"]:
            bits.append("you don't like " + p["dislikes"][-1])
        if p["favorites"]:
            k, v = list(p["favorites"].items())[-1]
            bits.append(f"your favorite {k} is {v}")
        if p["notes"]:
            bits.append(p["notes"][-1])
        return ("I know " + "; ".join(bits[:4]) + ".") if bits else "Not much yet. Tell me things!"
    if re.match(r"what do i (like|love|enjoy)$", lo):
        return ("You like " + ", ".join(p["likes"][-5:]) + ".") if p["likes"] else "You haven't told me yet."
    if re.match(r"what do i (hate|dislike|not like)$", lo):
        return ("You don't like " + ", ".join(p["dislikes"][-5:]) + ".") if p["dislikes"] else "Nothing, apparently. Except bad throws."
    m = re.match(r"(?:what's|whats|what is) my (?:favou?rite|fave) (.+)$", lo)
    if m:
        k = m.group(1).strip()
        for fk, v in p["favorites"].items():
            if fk == k or fk in k or k in fk:
                return f"Your favorite {fk} is {v}."
        return f"You never told me your favorite {k}."
    m = re.match(r"do you remember (.+)$", lo)
    if m:
        hit = mem.recall(m.group(1))
        return f"Of course: {hit}." if hit else "Hmm, no. Tell me again?"
    m = re.match(r"how many times (?:did|have) (?:i|you) (?:been )?(throw|thrown|threw|bump|bumped|grab|grabbed|headbutt|headbutted)(?: you| me)?(?: today)?$", lo)
    if m:
        key = {"throw": "you threw her", "thrown": "you threw her", "threw": "you threw her", "bump": "she got bumped",
               "bumped": "she got bumped", "grab": "you grabbed her", "grabbed": "you grabbed her",
               "headbutt": "you headbutted her", "headbutted": "you headbutted her"}[m.group(1)]
        n = mem.count_today(key)
        return f"{n} times today. I'm counting." if n != 1 else "Once today. I'm counting."
    if re.match(r"what (did we do|happened|have we done)( today)?$", lo):
        today = time.strftime("%Y-%m-%d")
        kinds = {}
        with mem.lock:
            for e in mem.data["events"]:
                if e.startswith(today):
                    k = e[17:].split(" speed")[0]
                    if not k.startswith("you said"):
                        kinds[k] = kinds.get(k, 0) + 1
        if not kinds:
            return "Not much yet. Let's do something!"
        top = sorted(kinds.items(), key=lambda x: -x[1])[:3]
        times = lambda n: "once" if n == 1 else "twice" if n == 2 else f"{n} times"
        mine = lambda k: re.sub(r"\b(her|she)\b", lambda w: "me" if w.group(1) == "her" else "I", k)
        return "Today " + ", ".join(f"{mine(k)} {times(n)}" for k, n in top) + "."
    if re.match(r"(what|which) places do you know$|where can you go$", lo):
        names = list(mem.data.get("places", {}))
        return ("I know the " + ", the ".join(names[-5:]) + ".") if names else "No saved places yet. Say remember this spot as, and a name."
    return None


def prime(c: dict) -> str:
    n = c["name"]
    return (f"{n}, throw a ball at me. {n}, follow me. Come here, {n}. Stay there. Spin. Keep spinning until I say so. "
            f"Do a front flip. Do a back flip. Stop. Push me. Shut me down. "
            f"Go back to spawn. Go home. Throw a snowball. {n}, what are you doing? Echo Arena, Echo Combat, "
            f"Lone Echo, joust, regrab, stun.")


def strip_wake(c: dict, text: str) -> str | None:
    t = text.lower()
    for w in c["wake_words"]:
        m = re.search(rf"\b{re.escape(w)}\b[\s,.!?]*", t)
        if m:
            return (text[:m.start()] + text[m.end():]).strip(" ,.!?") or "hi"
    return None


def speak(c: dict, mem: Memory, voice: Voice | None, say: str, how: str, t_heard: float):
    say = say_clean(fill(c, mem, say))
    log(f"{c['name']} ({how}, {time.time() - t_heard:.2f} s after you stopped): {say!r}")
    mem.turn("her", say)
    if voice and say:
        voice.say(say)


TEACH = re.compile(r"^(?:when|if|whenever) (?:i|someone|anyone|somebody|people|a player|they|he|she) "
                   r"(?:say|says|ask|asks|tell|tells)(?: you)? (.+?),? (?:then )?(?:you )?(?:should |can |could )?"
                   r"(?:say|answer|reply|respond|tell (?:them|me|him|her))(?: with)? (.+)$", re.I)
ANSWER = re.compile(r"^(?:you (?:should|could|can) (?:say|answer|reply|respond)(?: with)?|(?:just )?say|the answer is|"
                    r"answer(?: with)?|reply(?: with)?|respond with|tell (?:them|me|him|her)) (.+)$", re.I)
UNLEARN = re.compile(r"^(?:forget|unlearn) (?:what you say (?:to|when (?:i|someone) (?:say|says|ask|asks))|"
                     r"the answer (?:to|for)|your answer (?:to|for)) (.+)$", re.I)


def teach_instant(c: dict, mem: Memory, lib: Library, heard: str) -> str | None:
    """Teaching her (her memory bank grows): "when someone says X, say Y"; right after she didn't
    know something, "the answer is Y" / "you should say Y"; "forget what you say to X"; "what have
    you learned"; "forget the X spot". Returns her reply, or None."""
    t = re.sub(r"^(?:(?:cubie|edith),?\s*|hey\s+|okay\s+|ok\s+|so\s+)+", "", heard.strip(), flags=re.I).strip(" .!?")
    m = TEACH.match(t)
    if m:
        e = mem.teach(m.group(1), m.group(2))
        lib.learn(mem.data["learned"])
        mem.event(f"you taught her to answer \"{m.group(1)[:40]}\"")
        return random.choice(["Got it. I'll remember that one.", "Learned. Ask me again sometime.", "Noted. I'm getting smarter."])
    m = ANSWER.match(t)
    if m and mem.last_unknown and time.time() - mem.last_unknown_at < 60:
        mem.teach(mem.last_unknown, m.group(1))
        lib.learn(mem.data["learned"])
        mem.event(f"you taught her to answer \"{mem.last_unknown[:40]}\"")
        mem.last_unknown = ""
        return random.choice(["Ooh. Now I know that one.", "Got it. Next time I'll know.", "Learned. Thanks."])
    m = UNLEARN.match(t)
    if m:
        n = mem.unlearn(m.group(1))
        lib.learn(mem.data["learned"])
        return "Forgotten." if n else "I wasn't taught anything about that."
    if re.match(r"^what (?:have you|did you|else have you) learn(?:ed|t)?(?: so far| from me)?$", t, re.I):
        lr = mem.data.get("learned", [])
        if not lr:
            return "Nothing yet. Teach me! Say when someone says this, say that."
        last = lr[-1]["q"][0]
        return f"{len(lr)} things so far. The newest: what to say to {last}." if len(lr) > 1 else f"One thing: what to say to {last}."
    m = re.match(r"^(?:forget|delete|remove) (?:the |that )?(?:place |spot )?(?:called |named )?(.+?)(?: (?:place|spot|area))?$", t, re.I)
    if m and mem.place(m.group(1)):
        name = mem.forget_place(m.group(1))
        return f"The {name}? Gone from my map."
    return None


#: kind and mean words (user, 2026-10-18: points for what people say to or about her), from
#: ai/library/sentiment.json (grow it there); longest first, so "a piece of shit" beats "shit"
def _alts(items: list[str]) -> str:
    return "|".join(sorted(items, key=len, reverse=True))


_SENT = json.loads((Path(__file__).resolve().parent / "library" / "sentiment.json").read_text(encoding="utf-8"))
NICE_WORDS, MEAN_WORDS = _alts(_SENT["nice_words"]), _alts(_SENT["mean_words"])
NICE_PHRASES = r"\b(" + _alts(_SENT["nice_phrases"]) + r")\b"
MEAN_PHRASES = r"\b(" + _alts(_SENT["mean_phrases"]) + r")\b"
#: who a remark is about: her by name, "you" (said to her), or her as she / this robot when overheard
TO_HER = r"\b(you|you'?re|youre|your|u|ur|ya)\b"
ABOUT_HER = r"\b(she|she'?s|shes|her|edith|edie|cubie|(this|that|the|dumb|stupid|cute) (thing|robot|bot|drone|satellite|cube|cubesat|sat))\b"


def sentiment(text: str, addressed: bool) -> int:
    """+1 kind, -1 mean, 0 neither: about her ("you're cute" when said to her; "she's annoying",
    "this robot sucks" when overheard). "not" / "never" before the word flips it ("you're not dumb")."""
    t = " " + re.sub(r"[^a-z' ]", " ", text.lower()) + " "
    about = re.search(ABOUT_HER, t) or (addressed and (re.search(TO_HER, t) or len(t.split()) <= 3))
    if addressed or about:                                     # (said to her, a whole phrase is enough:
        if re.search(MEAN_PHRASES, t):                         #  "shut the fuck up")
            return -1
        if re.search(NICE_PHRASES, t):
            return 1
    if not about or len(t.split()) > 12:                       # (a long explanation to a friend isn't name-calling)
        return 0
    for words, sign in ((MEAN_WORDS, -1), (NICE_WORDS, 1)):
        m = re.search(rf"\b(?:(not|never|isn'?t|aren'?t|ain'?t|no)\s+(?:\w+\s+)?)?"
                      rf"(?:(?:so|really|very|such|super|fucking|freaking|totally|absolutely|literally|kinda|actually) )*"
                      rf"(?:such a |a |an |the )?({words})\b", t)
        if m:
            return -sign if m.group(1) else sign
    return 0


NICE_REPLY = ["Aww. Thank you.", "Stop it, my thrusters are blushing.", "You're not so bad yourself.", "I know. But keep going."]
MEAN_REPLY = ["Rude. Noted.", "Say that again and see what happens.", "Bold words for someone in shoving range.",
              "Wow. Okay.", "You just made my list."]
OVERHEARD_NICE = ["Aww, I heard that.", "I heard that. Thank you.", "Talking about me? Keep going."]
OVERHEARD_MEAN = ["I heard that.", "Excuse me? I'm right here.", "Say it to my face.", "I can hear you, you know."]


def remark(c: dict, mem: Memory, lib: Library, voice: "Voice | None", who: str | None, tone: int, heard: str,
           t_heard: float, line: str | None = None, overheard: bool = False):
    """A kind or mean thing said to or about her: a point, and her answer. Mean words while someone
    is in the red, or the third bad thing in a row, get a snowball back (retaliation)."""
    p = mem.person(who)
    mem.event(as_who(mem, f"you said {'nice' if tone > 0 else 'mean'} things {'about' if overheard else 'to'} her: "
                          f"\"{heard[:50]}\"", who))
    now = time.time()
    if tone > 0:
        p.good("overheard kindness" if overheard else "kind words")
        mem.save()
        show_face("happy", 4)
        tell_favourite(mem)
        return speak(c, mem, voice, line or random.choice(OVERHEARD_NICE if overheard else NICE_REPLY), "kind words", t_heard)
    wiped = p.bad("overheard meanness" if overheard else "mean words", c.get("cancel_after", 3))
    mem.save()
    tell_favourite(mem)
    to = f" to={p.name}" if p.name != "you" else ""
    if c.get("mean", True) and (wiped or (p.score() <= -2 and now - p.last_snow > 20)):
        p.last_snow = now
        send_order("throw" + to)                               # mean back: a snowball at them
        show_face("angry", 8)
        return speak(c, mem, voice, random.choice(MEAN_BACK) if wiped else (line or random.choice(MEAN_REPLY)),
                     "mean back (snowball)", t_heard)
    show_face("annoyed", 6)
    return speak(c, mem, voice, line or random.choice(OVERHEARD_MEAN if overheard else MEAN_REPLY), "mean words", t_heard)


def handle(c: dict, mem: Memory, lib: Library, voice: Voice | None, heard: str, t_heard: float, who: str | None = None):
    """What `who` said to her: you (this machine's mic) by default, or another player in her room
    (their voice chat, or their own companion through the relay). She answers everyone, but orders
    go through refusal(): the meaner someone has been, the less she does what they say. Teaching
    her and what she remembers about you (the profile) are yours only."""
    me = mem.is_me(who)
    p = mem.person(who)
    p.last_spoke = time.time()
    log(f"{'you' if me else p.name}:", heard)
    mem.turn("player" if me else p.name, heard)
    said = lambda text: mem.event(as_who(mem, text, who))      # a memory line about whoever spoke

    def order(text: str, how: str, do, line: str):
        """An order: refused or put off (no names), or done and remembered as theirs."""
        no, grumble = refusal(c, mem, who, text, heard)
        if no:
            said(f"you told her to {text} (she refused)")
            show_face("annoyed", 4)
            return speak(c, mem, voice, no, f"refused {how}", t_heard)
        obey(mem, who)
        do()
        said(f"you told her to {text}")
        if grumble:
            show_face("annoyed", 4)
        return speak(c, mem, voice, grumble or line, how + (" (grumbling)" if grumble else ""), t_heard)

    if me:
        t = teach_instant(c, mem, lib, heard)                 # you teach her: her memory grows
        if t:
            return speak(c, mem, voice, t, "taught", t_heard)
    tg = lib.taught(heard)                                     # what you taught her beats her own lines
    if tg:
        said(f"you said \"{heard[:60]}\"")
        return speak(c, mem, voice, tg[2], f"learned {tg[1]} {tg[0]:.2f}", t_heard)
    m = re.search(r"\b(?:remember|save|mark|call)\b.*?\b(?:this|here|spot|place)\b.*?" + SPOT_NAMED + r"\s+(?:the\s+)?(.+)$",
                  heard, re.I) if me else None
    g = re.search(r"\b(?:go|fly|head)\s+(?:back\s+)?to\s+(?:the\s+)?(.+)$", heard, re.I)
    bare = re.sub(r"\b(now|please|go|the|to|back)\b", "", heard.lower()).strip(" .,!?")
    if not m and not g and len(bare) >= 4 and len(bare.split()) <= 3 and mem.place(bare):   # just a place: "Cosmetic area."
        g = re.match(r"(.+)", bare)
    if g and not m and not mem.place(g.group(1)) and not instant(heard) and \
            not re.search(r"\b(spawn|home|start|middle|cent(er|re)|me|you|sleep|bed|hell)\b", g.group(1), re.I):
        want = g.group(1).strip(" .,!?")
        said(f"you asked her to go to {want} (she didn't know it)")
        return speak(c, mem, voice, f"I don't know where {want} is. Stand there and say, remember this spot as {want}.",
                     "unknown place", t_heard)
    if m or (g and mem.place(g.group(1))):                     # places, no model needed
        if m:
            name = m.group(1).strip(" .!?,").lower()
            ok = bool(carry_out(mem, ["mark"], name))
            return speak(c, mem, voice, f"Got it, the {name}!" if ok else "I can't see where you are right now.", "place", t_heard)
        hit = mem.place(g.group(1))
        return order(f"go to the {hit[0]}", "place", lambda: carry_out(mem, ["goto"], g.group(1)), f"Off to the {hit[0]}!")
    st = lib.smalltalk(heard)
    tone = {"compliment": 1, "love": 1, "insult": -1}.get(st[0], 0) if st else 0
    if not tone and not move_instant(c, mem, lib, heard) and not instant(heard):
        tone = sentiment(heard, addressed=True)                # (an order with a "please" isn't a remark)
    if tone:                                                   # "i like you" is chat, not a like
        return remark(c, mem, lib, voice, who, tone, heard, t_heard, st[1] if st and st[0] in ("compliment", "love", "insult") else None)
    if me:
        t = memory_instant(c, mem, heard)                      # remember / recall (your profile)
        if t:
            said(f"you said \"{heard[:60]}\"")
            return speak(c, mem, voice, t, "memory", t_heard)
    if re.search(r"\b(i never said|i didn'?t say|i did not say|that'?s not what i said|you misheard)\b", heard, re.I):
        said(f"you said \"{heard[:60]}\"")
        return speak(c, mem, voice, random.choice(["Oops. My microphone is a cube.", "My bad. Say it again?",
                                                   "Hm. Try that one more time.", "Sorry. Space static."]), "misheard", t_heard)
    if re.search(r"\b(change (your |ur )?face|make a face|(new|different|another) face|pull a face)\b", heard, re.I):
        mood = random.choice(["angry", "dizzy", "surprised", "hurt", "annoyed"])
        show_face(mood, 5)
        return speak(c, mem, voice, random.choice(["Like this?", "How's this one?", "Behold.", "Better?"]), f"face {mood}", t_heard)
    mv = move_instant(c, mem, lib, heard)
    if mv:                                                     # spins, flips, stop, push, shutdown
        return order(mv[0].replace(" keep", " and keep going"), f"instant {mv[0]}",
                     lambda: send_order(aim(mem, mv[0], who)), mv[1])
    fast = instant(heard)
    if fast:                                                   # no model: act and answer at once
        o, lines = fast
        return order(o, f"instant {o}", lambda: send_order(aim(mem, o, who)), lib.pick("order/" + o, lines))
    if st:                                                     # small talk
        if st[0] == "be_quiet" and me:
            mem.quiet_until = time.time() + 120                 # no reactions for a while
        if st[0] == "sorry":                                  # an apology takes one mean point back
            p.mean = max(0.0, p.mean - 1)
            log(f"  {p.name} said sorry: score {p.score():+.1f}")
            tell_favourite(mem)
        said(f"you said \"{heard[:60]}\"")
        return speak(c, mem, voice, st[1], f"small talk {st[0]}", t_heard)
    ch = lib.chat(heard)                                      # the big chat bank (ai/library/chat.json)
    # Echo / Lone Echo knowledge for questions, unless the chat bank has a strong match ("why are you
    # called edith" got the Echo Arena rename fact)
    ans = lib.answer(heard) if is_question(heard) and not (ch and ch[0] >= 0.85) else None
    if ans:
        said(f"you asked about {ans[1].replace('_', ' ')}")
        return speak(c, mem, voice, ans[2], f"knowledge {ans[1]} {ans[0]:.0f}", t_heard)
    if ch:
        score, cid, line, o = ch
        if o:
            return order(o, f"chat {cid} {score:.2f}", lambda: carry_out(mem, [o], who=who), line)
        said(f"you said \"{heard[:60]}\"")
        return speak(c, mem, voice, line, f"chat {cid} {score:.2f}", t_heard)
    if is_question(heard):                                     # something you told her to remember?
        hit = mem.recall(heard, need=2)
        if hit:
            said(f"you asked about \"{heard[:50]}\"")
            return speak(c, mem, voice, f"You told me: {hit}.", "recalled", t_heard)
    if len(re.findall(r"[a-z']+", heard.lower())) <= 2:        # "now", "oh", "well": not worth a "don't know"
        return speak(c, mem, voice, random.choice(["Hm?", "Yes?", "What?", "Mhm."]), "filler", t_heard)
    if not is_question(heard) and len(heard.split()) > 5:      # talk, not a question: nod along (and log it)
        with open(ROOT / "unknown.txt", "a", encoding="utf-8") as f:
            f.write(heard + "\n")
        return speak(c, mem, voice, random.choice(["Uh huh.", "Interesting.", "Okay.", "Sure.", "If you say so."]), "nod", t_heard)
    said(f"you said \"{heard[:60]}\" (she didn't know)")
    if me:
        mem.last_unknown, mem.last_unknown_at = heard, time.time()   # "the answer is ..." teaches her this
    with open(ROOT / "unknown.txt", "a", encoding="utf-8") as f:   # what to add to the library next
        f.write(heard + "\n")
    return speak(c, mem, voice, c["unknown"], "unknown", t_heard)


def grow_voice(c: dict):
    """With the game closed (GPU free): any line she has spoken in the fallback voice (taught answers,
    new library lines) is rendered in her cloned voice by ai/render_f5.py, detached, low priority."""
    voice = c.get("voice", "")
    if not voice.endswith("_f5") or not c.get("grow_voice", True):   # off: the user kept the HERA / af_heart mix
        return
    py = Path(c.get("clone_python", r"J:\EchoVR-Tools-Launcher\voiceclone\Scripts\python.exe"))
    missing = VOICE_CACHE / f"missing_{voice}.txt"
    if not py.exists() or not missing.exists() or not missing.read_text(encoding="utf-8").strip():
        return
    here = Path(__file__).resolve().parent
    subprocess.run([sys.executable, "-I", str(here / "satellite_ai.py"), "--no-voice", "--list-lines", str(ROOT / "lines.txt")],
                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=120)
    log("game closed: rendering her new lines in her own voice")
    subprocess.Popen([str(py), "-I", str(here / "render_f5.py"), "--voice", voice, "--ckpt", c.get("clone_ckpt", "model_1200.pt"), "--extra",
                      str(missing)], stdout=open(ROOT / "render_f5.log", "ab"), stderr=subprocess.STDOUT,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", help="one line instead of the mic (wake word optional)")
    ap.add_argument("--setup", action="store_true", help="fetch Whisper, then exit")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--warm", action="store_true", help="render every stock line into the voice cache, then exit")
    ap.add_argument("--list-lines", metavar="FILE", help="write every line she can say to FILE, then exit")
    ap.add_argument("--with-echo", type=int, metavar="PID",
                    help="started by EDITH.dll in that game: close when it closes")
    a = ap.parse_args()

    def follow_game(pid: int):
        """EDITH.dll started us in game `pid`: exit when that game exits."""
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x00100000, False, pid)              # SYNCHRONIZE
        if not h:
            log(f"game {pid} already gone: closing")
        else:
            k.WaitForSingleObject(h, 0xFFFFFFFF)
            log(f"game {pid} closed: closing")
            try:
                grow_voice(cfg())
            except Exception as e:  # noqa: BLE001
                log("grow voice:", e)
        os._exit(0)

    if a.with_echo:
        threading.Thread(target=follow_game, args=(a.with_echo,), daemon=True).start()
    c = cfg()
    Person.fade_s = float(c.get("mean_fade_s", 90))
    ROOT.mkdir(parents=True, exist_ok=True)
    lib = Library()
    mem = Memory(MEMORY)
    lib.learn(mem.data.get("learned", []))
    try:                                                       # the game first
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:  # noqa: BLE001
        pass
    log("player:", call_name(c, mem) or "(unknown: set player_name in config.json)")
    log(f"library: {len(lib.entries)} knowledge entries, {len(lib.intents)} small talk intents, "
        f"{len(lib.reactions)} reactions")
    voice = None if a.no_voice else Voice(c, mem)
    # pre-voiced at start: the short lines (orders, small talk, reactions); knowledge answers are
    # voiced the first time they're used and cached on disk from then on (--warm does them all)
    stock = [fill(c, mem, l) for l in [l for _, _, ls in INSTANT for l in ls] + [l for ls in MOVE_LINES.values() for l in ls]
             + REFUSE_MEAN + REFUSE_BUSY + STUBBORN + GRUDGING + MEAN_BACK + NICE_HOLD + NICE_REPLY + MEAN_REPLY
             + OVERHEARD_NICE + OVERHEARD_MEAN + ["Hm?", "Yes?", "What?", "Mhm.", "Like this?", "How's this one?", "Behold.",
                                                  "Better?", "Uh huh.", "Interesting.", "Okay.", "Sure.", "If you say so.", "Oops. My microphone is a cube.",
                                                  "My bad. Say it again?", "Hm. Try that one more time.", "Sorry. Space static."]
             + lib.all_lines(knowledge=a.warm)]
    stock = list(dict.fromkeys(say_clean(l) for l in stock if "{" not in l))
    if a.list_lines:                                           # for ai/render_f5.py (her cloned voice)
        raw = [l for _, _, ls in INSTANT for l in ls] + [l for ls in MOVE_LINES.values() for l in ls] + lib.all_lines(knowledge=True) \
            + [a for e in mem.data.get("learned", []) for a in e["a"]]
        lines = list(dict.fromkeys(say_clean(fill(c, mem, l)) for l in raw if "{time}" not in l and "{date}" not in l))
        Path(a.list_lines).write_text("\n".join(l for l in lines if l) + "\n", encoding="utf-8")
        log(f"{len(lines)} lines -> {a.list_lines} (speed key {c.get('voice_speed', 1.0)})")
        return 0
    if a.warm and voice:
        voice.warm(stock)
        return 0
    if a.setup:
        load_whisper(c)
        log("setup done")
        return 0
    stop = threading.Event()
    q: queue.Queue = queue.Queue()                             # ("audio" | "text", data, who, when)
    threading.Thread(target=listen_events, args=(c, mem, lib, voice, stop, q), daemon=True).start()
    if a.text:
        time.sleep(0.3)                                        # a state line, if the game is running
        handle(c, mem, lib, voice, strip_wake(c, a.text) or a.text, time.time())
        return 0
    if voice:                                                  # her stock lines, ready to play
        threading.Thread(target=voice.warm, args=(stock,), daemon=True).start()
    stt = load_whisper(c)
    threading.Thread(target=utterances, args=(c, q, stop, voice.speaking if voice else None), daemon=True).start()
    if c.get("hear_voip", True):                               # other players, on voice chat
        threading.Thread(target=voip_utterances, args=(c, mem, q, stop), daemon=True).start()
    log(f"listening -- say \"{c['name']}, ...\" (Ctrl+C to stop)")
    was_in = None
    try:
        while True:
            kind, data, who, t_heard = q.get()
            mine = who is None                                 # this machine's mic
            # only in the lobby: EDITH.dll sends her state line (every 2 s) only while she is
            # loaded and steered here; anywhere else she ignores the mic entirely
            here = mem.in_lobby()
            if here != was_in:
                log("in the lobby with her: listening" if here else "not in her lobby: doing nothing")
                was_in = here
            if not here:
                continue
            if mine and voice and voice.speaking.is_set():
                continue                                       # her own voice through the speakers
            if mine and mem.muted and time.time() - mem.muted_at < 6:
                continue                                       # muted in game: muted for her too
            if voice:
                voice.busy.set()                               # warming waits while she listens / thinks
            try:
                if kind == "audio":
                    segs, _ = stt.transcribe(data, language="en", beam_size=1, vad_filter=False,
                                             hotwords=c["name"], initial_prompt=prime(c))
                    text = " ".join(s.text for s in segs).strip()
                else:
                    text = data.strip()
                if not text or len(text) < 2:
                    continue
                p = mem.person(who)
                cmd = strip_wake(c, text)
                named = cmd is not None
                if cmd is None and time.time() < p.awake_until and len(text.split()) <= 10:
                    cmd = text                                 # one quick follow-up, no name needed
                if cmd is None:
                    tone = sentiment(text, addressed=False)        # about her, not to her: she still hears it
                    if tone and not (mine and mem.role == "puppet") and time.time() - p.last_spoke > 5:
                        log(f"(about her{'' if mine else ', ' + p.name})", text)
                        p.last_spoke = time.time()
                        remark(c, mem, lib, voice, who, tone, text, t_heard, overheard=True)
                    else:
                        log(f"(not for her{'' if mine else ', ' + p.name})", text)
                    continue
                # only a reply to her name opens the follow-up window (and only once)
                p.awake_until = time.time() + c["follow_up_seconds"] if named else 0.0
                if mine and mem.role == "puppet":              # the host's Edith answers: send it there
                    send_order(f"heard {text}")
                    log(f"  -> host ({mem.state.split('host=')[-1].split()[0] if 'host=' in mem.state else '?'}): {text}")
                    continue
                log(f"  heard{'' if mine else ' ' + p.name} in {time.time() - t_heard:.2f} s")
                handle(c, mem, lib, voice, cmd, t_heard, who)
            finally:
                if voice:
                    voice.busy.clear()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
