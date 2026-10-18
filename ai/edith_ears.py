"""Edith's ears and mouth on this PC: the thin companion. Her brain runs on the server
(Railway/SparkAPI/edith_brain.py; docs/brainplan.md).

    H:\\SatelliteAI\\venv\\Scripts\\python.exe -I ai/edith_ears.py            # run alongside the game
    ... ai/edith_ears.py --text "edith, come here"                         # no mic: one line, for testing
    ... ai/edith_ears.py --brain ws://127.0.0.1:8766/edith/brain           # another brain (config "brain")

What stays here:
  mic (PyAudio, 16 kHz) -> speech found by level (adaptive noise floor) -> uploaded as int16 to the
  brain (not while muted on Echo's voice chat, EDITH.dll "mute 1", nor while she talks);
  other players' voice chat (EDITH.dll, UDP 47324) the same way, by name;
  EDITH.dll's events (UDP 47322: state, grabbed / thrown ... by=, heard, mute) -> the brain;
  the brain's replies -> her face and orders (UDP 47321) and her line: from the voice pack
  (plugins\\EdithVoice\\<key>.pcm, 24 kHz mono int16) or, for a line the pack lacks, streamed from
  the brain (Kokoro), out of her speaker in game (UDP 47323) or the default output without it.
Needs numpy, PyAudio and websockets only.
"""
from __future__ import annotations

import argparse
import collections
import ctypes
import datetime
import json
import os
import queue
import re
import socket
import struct
import sys
import threading
import time
from pathlib import Path

ROOT = Path(os.environ.get("SATELLITE_AI", r"H:\SatelliteAI"))
CONFIG = ROOT / "config.json"
BUILD = "ears-1"
DEFAULTS = {
    "brain": "wss://sparkapi-production-e6df.up.railway.app/edith/brain",
    "voice_pack": "",                     # "" = the game's plugins\EdithVoice (else H:\SatelliteAI\voicecache)
    "voice_out": "auto",                  # auto (her speaker in game when it's on, else local) | game | local
    "hear_voip": True,                    # other players on voice chat (EDITH.dll, UDP 47324)
    "mic_device": None,                   # PyAudio input index; None = default
    "speech_level": 2.5,                  # speech = this many times the noise floor
    "silence_ms": 500,
    "max_utterance_s": 12,
}
CMD = ("127.0.0.1", 47321)
EVENTS = ("127.0.0.1", 47322)
SPEAKER = ("127.0.0.1", 47323)
VOIP = ("127.0.0.1", 47324)
RATE = 24000                              # her voice: 24 kHz mono int16


def cfg() -> dict:
    c = dict(DEFAULTS)
    try:
        c.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return c


def log(*a):
    line = " ".join([time.strftime("[%H:%M:%S]")] + [str(x) for x in a])
    print(line, flush=True)
    try:
        with open((ROOT if ROOT.exists() else Path(__file__).resolve().parent) / "edith_ears.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


SELF = ("127.0.0.1", 47325)               # your own client: push / shutdown YOUR body
_ME = {"name": ""}                         # (your name: the state line's or the client's mute line's me=)


def send_order(order: str):
    """An order to EDITH.dll. A push or shutdown aimed at you goes to your own client (SELF),
    without to=: online only your client moves your body; whoever steers her (a server) can't."""
    words = order.split()
    to = next((w[3:] for w in words if w.startswith("to=")), "")
    at_you = bool(words) and words[0] in ("push", "shutdown") and (not to or to == _ME["name"] or to == "you")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(" ".join(w for w in words if not w.startswith("to=")).encode() if at_you else order.encode(),
                 SELF if at_you else CMD)


# ---- the game, as EDITH.dll reports it ---------------------------------------------------------

class Game:
    def __init__(self):
        self.state, self.state_time = "", 0.0
        self.muted, self.muted_at = False, 0.0
        self.speaking = threading.Event()                      # her line is playing: the mic is deaf
        self.client_speaker, self.client_speaker_at = False, 0.0   # her speaker in YOUR game (the client's)

    def read(self, line: str):
        self.state, self.state_time = line, time.time()
        if self.field("me"):
            _ME["name"] = self.field("me")

    def read_mute(self, line: str):
        """"mute 0|1 me=<name> speaker=0|1" from your own client."""
        self.muted, self.muted_at = line[5:].split()[:1] == ["1"], time.time()
        m = re.search(r"\bme=(\S+)", line)
        if m:
            _ME["name"] = m.group(1)
        m = re.search(r"\bspeaker=(\d)", line)
        if m:
            self.client_speaker, self.client_speaker_at = m.group(1) == "1", time.time()

    def field(self, k: str) -> str:
        m = re.search(rf"\b{k}=(\S*)", self.state)
        return m.group(1) if m else ""

    def in_lobby(self) -> bool:
        return time.time() - self.state_time < 6.0

    def speaker_on(self) -> bool:
        """Her speaker plays in your game: your client says so (when a server steers her), or the
        state line does (when she's steered here)."""
        if time.time() - self.client_speaker_at < 6.0:
            return self.client_speaker
        return "speaker=1" in self.state and self.in_lobby()


# ---- the brain link --------------------------------------------------------------------------------

class Brain:
    """One WebSocket to the brain, reconnecting. Sends go through one thread (a queue); replies go
    to `on_reply`, streamed renders to their waiting player."""

    def __init__(self, url: str, game: Game, on_reply):
        self.url, self.game, self.on_reply = url, game, on_reply
        self.out: queue.Queue = queue.Queue(maxsize=256)
        self.up = threading.Event()
        self.hi: dict = {}
        self.renders: dict[int, queue.Queue] = {}
        self.next_id = 1
        self.lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, msg):
        if not self.up.is_set():
            return False
        try:
            self.out.put_nowait(msg)
            return True
        except queue.Full:
            return False

    def render(self, text: str) -> queue.Queue | None:
        """Ask the brain to voice a line: its PCM arrives on the returned queue, then None."""
        with self.lock:
            rid = self.next_id
            self.next_id += 1
        q: queue.Queue = queue.Queue()
        self.renders[rid] = q
        if not self.send({"t": "render", "id": rid, "text": text}):
            self.renders.pop(rid, None)
            return None
        return q

    def _run(self):
        from websockets.sync.client import connect
        wait = 1.0
        while True:
            try:
                with connect(self.url, max_size=None, open_timeout=10, ping_interval=20, ping_timeout=20) as ws:
                    tz = int(datetime.datetime.now().astimezone().utcoffset().total_seconds() // 60)
                    ws.send(json.dumps({"t": "hello", "v": 1, "name": _ME["name"], "tz": tz, "build": BUILD}))
                    while not self.out.empty():                    # (nothing stale from before)
                        self.out.get_nowait()
                    self.up.set()
                    wait = 1.0
                    stop = threading.Event()
                    th = threading.Thread(target=self._sender, args=(ws, stop), daemon=True)
                    th.start()
                    try:
                        for msg in ws:
                            self._got(msg)
                    finally:
                        stop.set()
                        self.up.clear()
                        th.join(2)
            except Exception as e:  # noqa: BLE001
                if self.up.is_set() or wait == 1.0:
                    log(f"brain: no link ({type(e).__name__}: {str(e)[:120]}); retrying")
                self.up.clear()
            for q in list(self.renders.values()):
                q.put(None)
            self.renders.clear()
            time.sleep(wait)
            wait = min(wait * 2, 30.0)

    def _sender(self, ws, stop: threading.Event):
        while not stop.is_set():
            try:
                msg = self.out.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                ws.send(msg if isinstance(msg, bytes) else json.dumps(msg))
            except Exception:  # noqa: BLE001
                return

    def _got(self, msg):
        if isinstance(msg, bytes):
            if msg[:4] == b"EDV1" and len(msg) >= 8:
                q = self.renders.get(struct.unpack_from("<I", msg, 4)[0])
                if q:
                    q.put(msg[8:])
            return
        try:
            m = json.loads(msg)
        except ValueError:
            return
        t = m.get("t")
        if t == "hi":
            self.hi = m
            log(f"brain: connected ({self.url}); voice {m.get('voice')} / {m.get('fallback')} at {m.get('speed')}, "
                f"whisper {'on' if m.get('stt') else 'OFF'}, server voice {'on' if m.get('tts') else 'OFF'}")
        elif t == "reply":
            self.on_reply(m)
        elif t == "rendered":
            q = self.renders.pop(int(m.get("id") or 0), None)
            if q:
                q.put(None)
        elif t == "log":
            log("  brain:", m.get("text", ""))


# ---- her voice ---------------------------------------------------------------------------------------

def game_plugins(pid: int | None) -> Path | None:
    """The plugins folder of the game that started us (its exe's folder + plugins)."""
    if not pid:
        return None
    try:
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)                  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.c_ulong(1024)
        ok = k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
        k.CloseHandle(h)
        return Path(buf.value).parent / "plugins" if ok else None
    except Exception:  # noqa: BLE001
        return None


class Voice:
    """Plays the brain's replies, one at a time: the voice pack first (her voice, then the fallback
    voice's render), else the brain streams it. Out: her speaker in game (EDITH.dll, UDP 47323)
    when the plugin reports it on, else the default output device."""

    def __init__(self, c: dict, game: Game, pack: Path):
        self.c, self.game, self.pack = c, game, pack
        self.brain: Brain | None = None
        self.q: queue.Queue = queue.Queue()
        self.done = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def file(self, key: str | None) -> Path | None:
        f = self.pack / f"{key}.pcm" if key else None
        return f if f and f.exists() else None

    @staticmethod
    def broken(f: Path, text: str, ref: Path | None) -> bool:
        """A cloned-voice render that came out as a blip (as satellite_ai.py Voice.broken): under
        half the fallback voice's length, or under 0.12 s a word."""
        secs = f.stat().st_size / 2 / RATE
        if ref and secs < 0.5 * ref.stat().st_size / 2 / RATE:
            return True
        return secs < 0.12 * max(len(text.split()), 1)

    def mine(self, text: str, key: str, alt: str) -> Path | None:
        """Her own voice's render, unless it's broken."""
        f = self.file(key)
        return f if f and not self.broken(f, text, self.file(alt)) else None

    def plan(self, m: dict) -> list:
        """What to play: pack files (Path) or lines to stream (str)."""
        say, key, alt = m["say"], m.get("key"), m.get("alt")
        parts = m.get("parts") or []
        whole = self.mine(say, key, alt)
        if whole:
            return [whole]
        if parts and all(self.mine(*p) for p in parts):
            return [self.mine(*p) for p in parts]
        if self.file(alt):
            return [self.file(alt)]
        mixed = [self.mine(*p) or self.file(p[2]) or p[0] for p in parts]
        if any(isinstance(x, Path) for x in mixed):
            return mixed
        return [say]                                           # none of it in the pack: one stream

    def say(self, m: dict):
        self.q.put(m)

    def _pcm(self, items: list):
        """Each item's PCM, in pieces (streamed lines as they arrive)."""
        for it in items:
            if isinstance(it, Path):
                yield it.read_bytes()
                continue
            rq = self.brain.render(it) if self.brain else None
            if rq is None:
                log(f"voice: can't voice {it!r} (no pack line, no brain)")
                continue
            log(f"voice: streaming {it!r} (not in the pack)")
            while True:
                try:
                    chunk = rq.get(timeout=15)
                except queue.Empty:
                    break
                if chunk is None:
                    break
                yield chunk

    def _run(self):
        while True:
            m = self.q.get()
            items = self.plan(m)
            log(f"voice: {m['say']!r} <- " + ", ".join(f"pack {p.stem}" if isinstance(p, Path) else "stream" for p in items))
            self.game.speaking.set()
            if self.brain:
                self.brain.send({"t": "speaking", "on": True})
            try:
                out = self.c.get("voice_out", "auto")
                if out == "none":                              # (tests: fetch it, play nothing)
                    log(f"voice: {sum(len(p) for p in self._pcm(items)) / 2 / RATE:.2f} s, not played")
                elif out == "game" or (out == "auto" and self.game.speaker_on()):
                    self._game(items)
                else:
                    self._local(items)
            except Exception as e:  # noqa: BLE001
                log("voice: failed:", e)
            finally:
                time.sleep(0.4)                                # her tail in the room
                self.game.speaking.clear()
                if self.brain:
                    self.brain.send({"t": "speaking", "on": False})
                if self.q.empty():
                    self.done.set()

    def _game(self, items: list):
        """Stream to EDITH.dll: 0.1 s datagrams, 0.4 s ahead of real time, then wait it out."""
        chunk = RATE // 10 * 2
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            t0, sent, rest = time.time(), 0.0, b""
            for pcm in self._pcm(items):
                pcm = rest + pcm
                n = len(pcm) // chunk * chunk
                pcm, rest = pcm[:n], pcm[n:]
                for i in range(0, len(pcm), chunk):
                    if sent < time.time() - t0:                # (a streamed line fell behind: catch up)
                        t0 = time.time() - sent
                    s.sendto(pcm[i:i + chunk], SPEAKER)
                    sent += chunk / 2 / RATE
                    ahead = sent - (time.time() - t0)
                    if ahead > 0.4:
                        time.sleep(ahead - 0.4)
            if rest:
                s.sendto(rest[: len(rest) // 2 * 2], SPEAKER)
                sent += len(rest) / 2 / RATE
            left = sent - (time.time() - t0) + 0.15
            if left > 0:
                time.sleep(left)

    def _local(self, items: list):
        import pyaudio
        pa = pyaudio.PyAudio()
        st = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, output=True)
        try:
            for pcm in self._pcm(items):
                st.write(pcm[: len(pcm) // 2 * 2])
        finally:
            st.close()
            pa.terminate()


# ---- ears ---------------------------------------------------------------------------------------------

def upload(brain: Brain, pcm: bytes, who: str = ""):
    name = who.encode("utf-8")[:48]
    brain.send(b"EDA1" + bytes([len(name)]) + name + pcm)


def mic(c: dict, game: Game, brain: Brain):
    """Mic -> utterances (int16 16 kHz), found by level against a moving noise floor -> the brain.
    Only in her lobby, not while muted in game, not while she talks."""
    import numpy as np
    import pyaudio
    pa = pyaudio.PyAudio()
    rate, frame = 16000, 480                                   # 30 ms frames
    st = pa.open(format=pyaudio.paInt16, channels=1, rate=rate, input=True, frames_per_buffer=frame,
                 input_device_index=c["mic_device"])
    noise, speech, quiet, buf = 200.0, False, 0, []
    pre: collections.deque = collections.deque(maxlen=10)      # 0.3 s before speech starts
    was_muted = None
    while True:
        raw = st.read(frame, exception_on_overflow=False)
        muted = game.muted and time.time() - game.muted_at < 6
        if muted != was_muted:
            log("muted on voice chat: mic not sent" if muted else "mic on")
            was_muted = muted
        if game.speaking.is_set() or muted or not game.in_lobby() or not brain.up.is_set():
            speech, buf = False, []
            pre.clear()
            continue
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        lvl = float(np.sqrt(np.mean(x * x)) + 1e-3)
        if not speech:
            noise = 0.97 * noise + 0.03 * lvl
            if lvl > noise * c["speech_level"] and lvl > 150:
                speech, quiet, buf = True, 0, list(pre) + [raw]
            else:
                pre.append(raw)
        else:
            buf.append(raw)
            quiet = quiet + 1 if lvl < noise * c["speech_level"] * 0.6 else 0
            if quiet * 30 > c["silence_ms"] or len(buf) * 0.03 > c["max_utterance_s"]:
                speech = False
                if len(buf) > 10:                              # > 0.3 s
                    upload(brain, b"".join(buf))
                    log(f"mic: {len(buf) * 0.03:.1f} s sent")


def voip(c: dict, game: Game, brain: Brain):
    """Other players' voices on voice chat (EDITH.dll: "VOIP" + rate u32 + name len u8 + name +
    int16 mono) -> each player's utterances -> the brain, by name. Not on a puppet (the host hears
    everyone), and not for a player whose own companion runs (the room's ai list)."""
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
        if len(st["buf"]) > 10:
            upload(brain, np.concatenate(st["buf"]).astype(np.int16).tobytes(), name)
        st["buf"] = []

    while True:
        now = time.time()
        for name, st in streams.items():
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
        if game.field("net") == "puppet" or name in game.field("ai").split(","):
            continue
        x = np.frombuffer(pkt[9 + n:], dtype=np.int16).astype(np.float32)
        if rate and rate != 16000 and len(x):
            x = np.interp(np.arange(0, len(x), rate / 16000), np.arange(len(x)), x)
        st = streams.setdefault(name, {"noise": 200.0, "speech": False, "quiet": 0, "buf": [], "pre": [],
                                       "rest": np.zeros(0, np.float32)})
        st["last"] = now
        x = np.concatenate([st["rest"], x])
        k = 0
        while k + 480 <= len(x):
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


def events(game: Game, brain: Brain):
    """EDITH.dll's event port -> the brain (every line as is); state and mute read here too."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(EVENTS)
    was_in = None
    while True:
        msg = s.recv(4096).decode("utf-8", "replace")
        if msg.startswith("state "):
            game.read(msg[6:])
        elif msg.startswith("mute "):
            game.read_mute(msg)
        elif msg.startswith("event "):
            log("game:", msg[6:])
        here = game.in_lobby()
        if here != was_in:
            log("in the lobby with her: listening" if here else "not in her lobby: doing nothing")
            was_in = here
        brain.send({"t": "dll", "line": msg})


def apply(m: dict):
    """A reply's face and orders to EDITH.dll."""
    if m.get("face"):
        mood, secs = m["face"]
        send_order(f"face {mood} {float(secs):g}")
    for o in m.get("orders") or []:
        send_order(str(o))
    if m.get("orders"):
        log("orders:", ", ".join(m["orders"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", help="one line instead of the mic")
    ap.add_argument("--brain", help="the brain's WebSocket URL (config \"brain\")")
    ap.add_argument("--pack", help="the voice pack folder (config \"voice_pack\")")
    ap.add_argument("--with-echo", type=int, metavar="PID", help="started by EDITH.dll in that game: close when it closes")
    ap.add_argument("--silent", action="store_true", help="fetch her lines but play nothing (tests)")
    a = ap.parse_args()
    c = cfg()
    if a.silent:
        c["voice_out"] = "none"
    if a.with_echo:
        def follow_game(pid: int):
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x00100000, False, pid)          # SYNCHRONIZE
            if h:
                k.WaitForSingleObject(h, 0xFFFFFFFF)
            log(f"game {pid} closed: closing")
            os._exit(0)
        threading.Thread(target=follow_game, args=(a.with_echo,), daemon=True).start()
    try:                                                       # the game first
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    except Exception:  # noqa: BLE001
        pass
    plugins = game_plugins(a.with_echo)
    packs = [Path(p) for p in (a.pack, c.get("voice_pack")) if p] + \
            ([plugins / "EdithVoice"] if plugins else []) + [Path(__file__).resolve().parent.parent / "out" / "EdithVoice",
                                                              ROOT / "voicecache"]
    pack = next((p for p in packs if p.is_dir()), packs[0])
    log(f"voice pack: {pack} ({sum(1 for _ in pack.glob('*.pcm')) if pack.is_dir() else 0} lines)")
    game = Game()
    voice = Voice(c, game, pack)
    replied = threading.Event()

    def on_reply(m: dict):
        apply(m)
        if m.get("say"):
            voice.done.clear()
            voice.say(m)
            replied.set()
    brain = Brain(a.brain or c["brain"], game, on_reply)
    voice.brain = brain
    if a.text:
        if not brain.up.wait(15):
            log("brain: unreachable")
            return 1
        brain.send({"t": "text", "text": a.text})
        if replied.wait(10):
            voice.done.wait(30)
        return 0
    threading.Thread(target=events, args=(game, brain), daemon=True).start()
    threading.Thread(target=mic, args=(c, game, brain), daemon=True).start()
    if c.get("hear_voip", True):
        threading.Thread(target=voip, args=(c, game, brain), daemon=True).start()
    log(f"listening -- say \"Edith, ...\" (brain: {brain.url}; Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
