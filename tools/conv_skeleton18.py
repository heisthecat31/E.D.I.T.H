"""CSkeletonResource: Christmas 2018 Win7 -> Summer 2019 Win7 (then EchoPorting conv_skeleton
takes it to live).

    python tools/conv_skeleton18.py                 # verify on the twin (base prp_itt_cube_sat)
    python tools/conv_skeleton18.py <in> <out>      # convert one file

Measured on the twin `prp_itt_cube_sat` (493ad5c876c84fae), 2018 (4420 B) vs J:\\Summer (3564 B),
N bones, K = the small key tables' row count (17 and 3 there). Every table starts 8-aligned.

| 2018 (header 0x688, payloads in this order) | 2019 (header 1512 B, payloads in this order) |
|---|---|
| K x 4 (desc 0x48)                           | root 1 x 64 (desc 0x40) = 2018 root           |
| N x 32 A (desc 0x80)                        | K x 4 (0x80)                                  |
| root 1 x 64 (desc 0x128)                    | N x 32 A (0xb8)                               |
| hierarchy N x 32 (desc 0x160)               | hierarchy N x 24 (0x160) = 2018 row[:24] (the 8 more are 0) |
| N x 32 B (2018 only: a second pose)         | K x 24 (0x208): 2018 row = name, 0, u32 K, u32 i -> name, 0, u32 i, u32 0 |
| N x 32 block (inverse bind, = 2019's)       | N x 16 name map (0x358)                       |
| K x 24                                      | N x 32 block (raw, size at 0x470)             |
| N x 16 name map                             | K x 16, K x 16, K x 8, K x 4 (0x488.. 0x540)  |
| 1 x 16 (2018 only: name, 0)                 |                                               |
| K x 16, K x 16, K x 8, K x 4                |                                               |

Twin result: identical except float rounding in table A and the order of entries in the
small key tables (hash order; each file is self-consistent).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

TEMPLATE = Path(r"J:\Summer\202d89353292d63d\493ad5c876c84fae")   # 2019 base skeleton (header)
H18, H19 = 0x688, 1512


def _al(x: int) -> int:
    return (x + 7) & ~7


def split18(b: bytes) -> dict:
    k = struct.unpack_from("<Q", b, 0x48 + 48)[0]
    n = struct.unpack_from("<Q", b, 0x80 + 48)[0]
    if struct.unpack_from("<Q", b, 0x128 + 48)[0] != 1:
        raise ValueError("root table is not one row")
    t, pos = {}, H18
    for name, ln in (("k4", 4 * k), ("A", 32 * n), ("root", 64), ("hier", 32 * n), ("B", 32 * n),
                     ("block", 32 * n), ("k24", 24 * k), ("names", 16 * n), ("x16", 16),
                     ("k16a", 16 * k), ("k16b", 16 * k), ("k8", 8 * k), ("k4b", 4 * k)):
        pos = _al(pos)
        t[name] = b[pos:pos + ln]
        pos += ln
    if pos != len(b):
        raise ValueError(f"2018 walk ended at {pos:#x}, file is {len(b):#x}")
    t["n"], t["k"] = n, k
    return t


def _desc(head: bytearray, at: int, count: int, row: int) -> None:
    struct.pack_into("<Q", head, at + 8, count * row)
    struct.pack_into("<QQ", head, at + 40, count, count)


def convert(b: bytes) -> bytes:
    t = split18(b)
    n, k = t["n"], t["k"]
    head = bytearray(TEMPLATE.read_bytes()[:H19])
    head[0:8] = b[0:8]                                  # the skeleton's own name
    for at, cnt, row in ((0x40, 1, 64), (0x80, k, 4), (0xb8, n, 32), (0x160, n, 24), (0x208, k, 24),
                         (0x358, n, 16), (0x488, k, 16), (0x4c8, k, 16), (0x508, k, 8), (0x540, k, 4)):
        _desc(head, at, cnt, row)
    struct.pack_into("<Q", head, 0x470, 32 * n)        # the raw block's size
    hier = b"".join(t["hier"][i * 32:i * 32 + 24] for i in range(n))
    k24 = b"".join(r[:16] + r[20:24] + b"\0" * 4 for r in (t["k24"][i * 24:(i + 1) * 24] for i in range(k)))
    out = bytearray(head)
    for part in (t["root"], t["k4"], t["A"], hier, k24, t["names"], t["block"],
                 t["k16a"], t["k16b"], t["k8"], t["k4b"]):
        out += b"\0" * (_al(len(out)) - len(out))
        out += part
    return bytes(out)


def _verify() -> int:
    src = Path(__file__).resolve().parent.parent / "out" / "her_assets_src18" / "202d89353292d63d" / "493ad5c876c84fae"
    got, want = convert(src.read_bytes()), TEMPLATE.read_bytes()
    print(f"twin: {len(got)} vs {len(want)} bytes, {sum(x != y for x, y in zip(got, want))} differ")
    runs, last = [], None
    for i, (x, y) in enumerate(zip(got, want)):
        if x != y:
            if last is not None and i - last <= 8:
                runs[-1][1] = i
            else:
                runs.append([i, i])
            last = i
    for s, e in runs[:20]:
        print(f"  {s:#x}..{e:#x}")
    return 0 if len(got) == len(want) else 1


if __name__ == "__main__":
    if len(sys.argv) == 3:
        Path(sys.argv[2]).write_bytes(convert(Path(sys.argv[1]).read_bytes()))
        sys.exit(0)
    sys.exit(_verify())
