"""A fake second player for the Edith relay (docs/networkplan.md, phases 1-2), so no second headset
is needed. Your EDITH.ini needs `debug_roster=FakeBob` so your client lists this one in its match.

    python tools/fake_player.py host   [--me he_is_the_cat] [--relay ws://127.0.0.1:8765/edith/ws]
        claims the host (ai=true, connect it BEFORE the game reaches the lobby) and sends her state:
        a 1.5 m circle round her home, facing where she flies, a new face every 4 s. Your client
        should log "puppet: following the host's state" and she flies the circle on her own.
    python tools/fake_player.py listen [--me ...]
        ai=false, so your client is host: prints the EDS1 state it receives (rate, position, face).

While it runs, it takes actions on UDP 127.0.0.1:47330 (one per datagram), as a real puppet's
plugin would send them (phases 3 and 5):
    say edith come here          -> {"t":"heard","text":...}   (what their companion heard)
    grab | release [speed]       -> {"t":"touch","what":"grabbed"|"released","vel":[..]}
    headbutt | bump              -> {"t":"touch","what":"hit","kind":..,"vel":[..]}
    python tools/fake_player.py do "say edith spin"     sends one (exits)
Any ctl aimed at it ({"t":"ctl","to":"FakeBob",...}) is printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import struct
import time

import websockets

FACES = ["happy", "angry", "dizzy", "surprised", "hurt", "annoyed"]
MODES = ["follow", "tumble", "stare"]


def eds1(seq: int, p, q, v, w, face: int, mode: int = 0, flags: int = 0, owner: int = 0) -> bytes:
    return b"EDS1" + struct.pack("<IB3f4f3f3fBBB", seq, owner, *p, *q, *v, *w, face, mode, flags)


def unpack(body: bytes):
    seq, owner, *f = struct.unpack("<IB3f4f3f3fBBB", body[4:64])
    return seq, owner, f[0:3], f[3:7], f[7:10], f[10:13], f[13], f[14], f[15]


async def host(ws, a):
    home = (a.x, a.y, a.z)
    r, period = 1.5, 12.0
    om = 2 * math.pi / period
    seq, t0 = 0, time.monotonic()
    while True:
        t = time.monotonic() - t0
        ang = om * t
        p = (home[0] + r * math.cos(ang), home[1] + 0.3 * math.sin(ang * 2), home[2] + r * math.sin(ang))
        v = (-r * om * math.sin(ang), 0.6 * om * math.cos(ang * 2), r * om * math.cos(ang))
        yaw = math.atan2(v[0], v[2])                          # her front is local +Z: face along v
        q = (0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2))
        dyaw = om                                             # yaw rate (rad/s) round +Y
        seq += 1
        await ws.send(eds1(seq, p, q, v, (0.0, dyaw, 0.0), int(t // 4) % len(FACES)))
        if seq % 150 == 0:
            print(f"sent {seq} states, her at ({p[0]:.2f} {p[1]:.2f} {p[2]:.2f}) face {FACES[int(t // 4) % len(FACES)]}")
        await asyncio.sleep(1 / 30)


async def receive(ws):
    n, last, t_last = 0, None, time.monotonic()
    async for msg in ws:
        if isinstance(msg, str):
            print("<-", msg)
            continue
        if msg[:4] != b"EDR1":
            print("<- binary", msg[:8])
            continue
        ln = msg[4]
        sender, body = msg[5:5 + ln].decode(), msg[5 + ln:]
        if body[:4] != b"EDS1":
            print(f"<- {sender}: {body[:4]}")
            continue
        last = (sender, unpack(body))
        n += 1
        now = time.monotonic()
        if now - t_last >= 2.0:
            seq, owner, p, q, v, w, face, mode, flags = last[1]
            print(f"{n / (now - t_last):.1f}/s from {sender}: seq {seq} owner {owner} pos ({p[0]:.2f} {p[1]:.2f} {p[2]:.2f}) "
                  f"v ({v[0]:.2f} {v[1]:.2f} {v[2]:.2f}) |w| {math.hypot(*w):.2f} face {FACES[face] if face < 6 else face} "
                  f"mode {MODES[mode] if mode < 3 else mode} held {flags & 1}")
            n, t_last = 0, now


CONTROL = ("127.0.0.1", 47330)


def action(line: str) -> dict | None:
    """A control line -> the relay message a real puppet would send."""
    words = line.strip().split(" ", 1)
    verb, rest = words[0].lower(), (words[1] if len(words) > 1 else "")
    if verb == "say" and rest:
        return {"t": "heard", "text": rest}
    if verb == "grab":
        return {"t": "touch", "what": "grabbed"}
    if verb == "release":
        sp = float(rest or 3.0)
        return {"t": "touch", "what": "released", "vel": [sp, 1.0, 0.0]}
    if verb in ("headbutt", "bump"):
        return {"t": "touch", "what": "hit", "kind": verb, "vel": [2.5, 0.5, 0.0]}
    return None


async def control(ws):
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    class Proto(asyncio.DatagramProtocol):
        def datagram_received(self, data, addr):
            q.put_nowait(data.decode("utf-8", "replace"))
    await loop.create_datagram_endpoint(Proto, local_addr=CONTROL)
    print(f"actions on udp {CONTROL[0]}:{CONTROL[1]}")
    while True:
        line = await q.get()
        msg = action(line)
        if msg is None:
            print("?? unknown action:", line)
            continue
        await ws.send(json.dumps(msg))
        print("->", json.dumps(msg))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["host", "listen", "do"])
    ap.add_argument("line", nargs="?", default="", help="do: the action to send")
    ap.add_argument("--name", default="FakeBob")
    ap.add_argument("--me", default="he_is_the_cat", help="your display name (the real client)")
    ap.add_argument("--relay", default="ws://127.0.0.1:8765/edith/ws")
    ap.add_argument("--x", type=float, default=0.0)
    ap.add_argument("--y", type=float, default=2.3)
    ap.add_argument("--z", type=float, default=0.0)
    a = ap.parse_args()
    if a.mode == "do":
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(a.line.encode(), CONTROL)
        return
    async with websockets.connect(a.relay, max_size=1 << 16) as ws:
        await ws.send(json.dumps({"v": 1, "t": "hello", "name": a.name, "roster": [a.me],
                                  "ai": a.mode == "host", "build": "fake-2"}))
        print(f"{a.name} connected to {a.relay} as {a.mode}")
        tasks = [asyncio.create_task(receive(ws)), asyncio.create_task(control(ws))]
        if a.mode == "host":
            tasks.append(asyncio.create_task(host(ws, a)))
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
