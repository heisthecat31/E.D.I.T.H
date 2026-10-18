"""CPhysicsResource with bone-attached shapes: Christmas 2018 Win7 -> 2019 Win7 -> live.

    python tools/conv_physics18.py                  # verify on the twins
    python tools/conv_physics18.py <in18> <out>     # 2018 file -> live

EchoPorting conv_physics handles bone count 0 only. CPhData = 36 B header (u32 bone count,
u32 from level, 6 f32 zone, u32 body count), the bodies (u64 geo flag + SPhGeoFull + 800 B
scalar + transform), then one 192-byte shape record per bone (Win7), then the trailer.

2018 -> 2019 (twin prp_itt_cube_sat, 2018 19640 B vs J:\\Summer 19648 B):
  * the header has one more u64 at +8 (ffff...): dropped
  * a body's transform is 64 B in 2018, 80 B in 2019: a scale (1, 1, 1, 0) goes in at +32
  * shape record +64: u16 0xb2 in 2018, 0x1dd in 2019 (live writes 0 there, see below)
2019 -> live (30 Summer/live twins with bones):
  * bodies: conv_physics (a new tree array per body)
  * each shape record: +64 u16 -> 0, 24 zero bytes at +186 (192 -> 216 B)
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoPorting\tools")
import conv_physics as CP                                      # noqa: E402

HDR = 36
REC7, REC10 = 192, 216
TAIL7_18, TAIL7 = 800 + 64, 800 + 80


def _bodies_end(blob: bytes, off: int, n: int, tail: int) -> list[tuple[int, int]]:
    """(start, end) of each Win7 body from `off`; `tail` = scalar + transform bytes."""
    spans = []
    for _ in range(n):
        if struct.unpack_from("<Q", blob, off)[0] != 1:
            raise ValueError(f"body at {off:#x} is not a geo body")
        g = off + 8
        o = g + CP.GEO7
        for cf, st in CP.W7_ORDER:
            o += struct.unpack_from("<Q", blob, g + cf)[0] * st
        spans.append((off, o + tail))
        off = o + tail
    return spans


def to2019(b18: bytes) -> bytes:
    head = b18[:8] + b18[16:44]
    n = struct.unpack_from("<I", head, 32)[0]
    out = bytearray(head)
    spans = _bodies_end(b18, 44, n, TAIL7_18)
    for s, e in spans:
        t = e - 64                                            # the 2018 transform
        out += b18[s:t + 32] + struct.pack("<4f", 1.0, 1.0, 1.0, 0.0) + b18[t + 32:e]
    rest = bytearray(b18[spans[-1][1] if spans else 44:])
    bones = struct.unpack_from("<I", head, 0)[0]
    if len(rest) < bones * REC7 + 36:
        bones = 0
    for i in range(bones):
        if struct.unpack_from("<H", rest, i * REC7 + 64)[0] == 0xB2:
            struct.pack_into("<H", rest, i * REC7 + 64, 0x1DD)
    return bytes(out + rest)


def to_live(b19: bytes) -> bytes:
    bones = struct.unpack_from("<I", b19, 0)[0]
    n = struct.unpack_from("<I", b19, 32)[0]
    spans = _bodies_end(b19, HDR, n, TAIL7)
    end = spans[-1][1] if spans else HDR
    # bodies: conv_physics on a copy that claims no bones and stops at the bodies
    plain = bytearray(b19[:end])
    struct.pack_into("<I", plain, 0, 0)
    body10 = bytearray(CP.convert(bytes(plain)))
    struct.pack_into("<I", body10, 0, bones)
    out = body10
    rest = b19[end:]
    if len(rest) < bones * REC7 + 36:                         # bone count but no shape records
        bones = 0
    for i in range(bones):
        r = bytearray(rest[i * REC7:(i + 1) * REC7])
        struct.pack_into("<H", r, 64, 0)
        out += r[:186] + bytes(24) + r[186:]
    return bytes(out + rest[bones * REC7:])


def _verify() -> int:
    S, L = Path(r"J:\Summer\658c83d9da327c17"), Path(r"H:\pcvr-extracted\b7d338793fa37832")
    live = {f.name.lstrip("0"): f for f in L.iterdir()}
    ok = bad = 0
    for f in sorted(S.iterdir()):
        b = f.read_bytes()
        if len(b) < HDR or not struct.unpack_from("<I", b, 0)[0] or f.name.lstrip("0") not in live:
            continue
        want = live[f.name.lstrip("0")].read_bytes()
        try:
            got = to_live(b)
        except Exception as e:                                # noqa: BLE001
            print(f"  {f.name}: {e}")
            bad += 1
            continue
        if got == want:
            ok += 1
        else:
            bad += 1
            d = sum(x != y for x, y in zip(got, want))
            print(f"  {f.name}: {len(got)} vs {len(want)} B, {d} differ")
    print(f"2019 -> live: {ok} exact, {bad} not")
    here = Path(__file__).resolve().parent.parent
    t18 = (here / "out/her_assets_src18/658c83d9da327c17/493ad5c876c84fae").read_bytes()
    t19 = (S / "493ad5c876c84fae").read_bytes()
    got = to2019(t18)
    print(f"2018 -> 2019 twin: {len(got)} vs {len(t19)} B, {sum(x != y for x, y in zip(got, t19))} differ")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3:
        Path(sys.argv[2]).write_bytes(to_live(to2019(Path(sys.argv[1]).read_bytes())))
        sys.exit(0)
    sys.exit(_verify())
