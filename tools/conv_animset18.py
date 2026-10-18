"""CAnimSetResource: Christmas 2018 Win7 -> Summer 2019 Win7 (then EchoPorting conv_animset takes
it to live; to_live() chains both).

    python -I tools/conv_animset18.py                 # verify on the 68 twins (+ her set)
    python -I tools/conv_animset18.py <in> <out19> [<outlive>]

2018 is a RAD serialized struct (radstruct frame: inline 56-B array descriptors (ptr, size, mem,
u32 0, u32 flag 4, align 0x20, count, count), data depth first after the root). 2019 is the
fixed CAnimData stream EchoPorting/tools/anim_walk.py walks. Measured on the twins:

| 2018 (root fields, then data in this order)            | 2019 (anim_walk 'w7')                     |
|---------------------------------------------------------|-------------------------------------------|
| +0x00 desc: C x 16 (element name, u64 index)            | header (0,A) (0,B) (0,C)                  |
| +0x38 (0,A) (0,B18) (0,0x140) u32 0 u32 1: inline blob  |                                           |
| +0x80 desc: 8 x 56 (named entries, same in every file)  |                                           |
| +0xc0 desc: C x 944 elements                            |                                           |
| data @0x130: C x 16 name table                          | (dropped: it is the 2019 element order)   |
| A x 112 records                                         | A x 128 records (fields moved, see REC)   |
| B18-byte evaluator trees                                | B19 = B18 + 8 per clip node               |
| 0x140-B block (same in every file)                      | (dropped)                                 |
| align 8, 8 x 56 entries                                 | (dropped)                                 |
| C x 944 elements, in storage order                      | align 8, C x 0x378 in name-table order    |
| per element: 13 2019 payloads, then u32 x 14,           | per element: the 13 payloads (scenes 64 B)|
|   12-B x 14*S, scenes S x 96 B                          |                                           |

- Trees: evaluator ids 0..0x19 name the same classes in both executables (the unpack switch,
  'Invalid evaluator type'). Same words except:
  * clip (1): 2018 u32 1, u64 anim, u64 element, u64 0 (28 B); 2019 inserts the set's own
    name after the anim name (36 B);
  * 0x12 blend: u64 count high word 0xffffffff -> 0 (conv_animset matches 0x12 on that 0);
    each entry's tail f32 1/6, f32 1.0 -> f32 1.0, u32 0 (116/116); an active entry mask with
    words +68/+72/+76 = (2, 5, 0) gets +68/+72 cleared (54/54; (2, 5, 2) is kept, 30/30);
  * 0x13 auto layer: f32 1/6 -> 0 and its n inline (0x0d, u64 name) children dropped (2/2);
  * three-way 0x0a -> 0x08 (16/16; 2018 never uses 8, 2019 never 0x0a).
  Bone-mask structs (440 words) are the same size.
- Records: 2018 u32 tree offset at +8 -> 2019 +12; other u32 fields move (REC). 2019 +120 is
  new: the number of active bone masks (mask u64 header == 1) in the record's tree (711/711).
- Elements: 2019 = 2018 with the two descriptors at +0x2c0/+0x2f8 (u32 x 14 table and the
  12-B table) replaced by the u32 x 14 table inline (56 B) and the u16 table descriptor's align
  word (+0x2a8) 0x20 -> 0. Scenes rows 96 -> 64 B: row[0:8] + row[40:96] (= the skeleton's
  2019 root row; the 32 dropped bytes index the 12-B table, 14 rows per scene).
- Record order is not derivable: 2019 lists records in another fixed order (by source name,
  e.g. ..9e40..9e47, ..9e4c); the converter keeps 2018's, offsets follow.

Twins (65 with a Summer version): 4 byte-exact, 42 same data (record order, uninitialised mask
words in 2019, curve floats within 8 ULP), 19 re-exported for Summer (track tables, channel
quantisation, one skeleton with an extra joint). All 68 walk as w7 and, via to_live, as live.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ECHOPORTING = Path(r"J:\EchoVR-Tools-Launcher\EchoPorting\tools")
sys.path.insert(0, str(ECHOPORTING))
import anim_walk as W  # noqa: E402

TWINS18 = Path(r"J:\EchoVR-Tools-Launcher\E.D.I.T.H\out\twins18_anim\9576db2165a5f779")
SUMMER = Path(r"J:\Summer\9576db2165a5f779")
HER = Path(r"J:\EchoVR-Tools-Launcher\E.D.I.T.H\out\her_assets_src18\9576db2165a5f779\493ad5c876c84fae")

REC18, REC19, ELEM18, ELEM19 = 112, 128, 944, 0x378
F19 = W.FIELDS                                   # 2019 element fields (scenes = 0x2f8)
F18 = W.FIELDS[:-1] + [0x2c0, 0x2f8, 0x330]      # 2018: + u32 x 14, 12-B table, scenes at 0x330
REC = {12: 20, 16: 16, 20: 88, 24: 56, 28: 60, 32: 64, 36: 68, 40: 32, 44: 36, 48: 40, 52: 72,
       56: 24, 60: 28, 64: 76, 68: 80, 72: 84, 76: 44, 80: 48, 84: 112}
# 2018 record u32 at +k -> 2019 +REC[k]. Measured on 711 twin records for k = 12..56, 76..84
# (24 and 52 are both 1 in the one record that sets either, so 24->56 / 52->72 is a guess);
# 32, 48, 60..72, 88..108 are 0 in every 2018 record (the targets for 32..72 are placeholders).
M7, FF = 440, 0xFFFFFFFF                         # bone-mask struct words (conv_animset.M7)


def _q(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def _al(p, a):
    return -(-p // a) * a


def parse18(b: bytes) -> dict:
    """Walk a 2018 set; every byte is accounted for or this raises."""
    c, a, bsz, x, n8 = _q(b, 0x28), _q(b, 0x48), _q(b, 0x58), _q(b, 0x68), _q(b, 0xa8)
    if _q(b, 0xe8) != c or _q(b, 0x08) != 16 * c or _q(b, 0xc8) != ELEM18 * c or _q(b, 0x88) != 56 * n8:
        raise ValueError("not a 2018 CAnimSetResource root")
    p = 0x130
    t = dict(C=c, A=a, B=bsz, names=p)
    p += 16 * c
    t["rec"] = p
    p += REC18 * a
    t["tree"] = p
    p += bsz + x
    p = _al(p, 8) + 56 * n8
    t["e0"] = p = _al(p, 8)
    p += ELEM18 * c
    spans = []
    for k in range(c):
        e = t["e0"] + k * ELEM18
        for f in F18:
            size, cnt = _q(b, e + f + 8), _q(b, e + f + 48)
            if f == 0x20:
                el, al = 1, (8 if size else 1)
            else:
                el = size // cnt if cnt else 0
                al = max(1, min(8, el & -el)) if size else 1
            p = _al(p, al)
            spans.append((k, f, p, size, cnt))
            p += size
    if p != len(b):
        raise ValueError(f"2018 walk ends at {p:#x}, file is {len(b):#x}")
    t["spans"] = spans
    return t


def _is_blend18(w: list[int], i: int) -> bool:
    """0x12 blend node: u32 type, u64 name, u64 n, n x (u64 name, u64, M, u64, f32, f32).
    2018 entries end f32 1/6, f32 1.0 (116/116 twin entries); 2019 f32 1.0, u32 0."""
    n = w[i + 3] if i + 4 < len(w) else 0
    return (w[i] == 0x12 and 0 < n < 64 and i + 5 + n * (M7 + 8) <= len(w)
            and all(w[i + 5 + (e + 1) * (M7 + 8) - 1] == 0x3F800000 for e in range(n)))


def _active_masks(w: list[int]) -> int:
    """Bone masks whose u64 header is 1 (0x12 blend entries and standalone 0x06 masks)."""
    import conv_animset as CA
    i = k = 0
    while i < len(w):
        n = w[i + 3] if i + 4 < len(w) else 0
        if _is_blend18(w, i):
            for e in range(n):
                s = i + 5 + e * (M7 + 8) + 4
                k += w[s] == 1 and w[s + 1] == 0
            i += 5 + n * (M7 + 8)
        elif w[i] != FF and CA._is_mask(w, i):
            k += w[i] == 1 and w[i + 1] == 0
            i += M7
        else:
            i += 1
    return k


def _tree(c: bytes, set_name: int, elems: set[int]) -> tuple[bytes, list[tuple[int, int]]]:
    """2018 tree block -> 2019; returns (block, [(old_byte_off, growth)])."""
    w = list(struct.unpack_from(f"<{len(c) // 4}I", c))
    out, grow, i = [], [], 0
    lo, hi = set_name & FF, set_name >> 32
    while i < len(w):
        n = w[i + 3] if i + 4 < len(w) else 0
        if (w[i] == 1 and i + 7 <= len(w) and (w[i + 3] | w[i + 4] << 32) in elems
                and w[i + 5] == 0 and w[i + 6] == 0):
            out += w[i:i + 3] + [lo, hi] + w[i + 3:i + 7]        # clip: + set name
            grow.append(((i + 3) * 4, 8))
            i += 7
        elif _is_blend18(w, i):
            out += w[i:i + 4] + [0]                                 # u64 count: junk high word
            for e in range(n):
                s = i + 5 + e * (M7 + 8)
                m = w[s + 4:s + 4 + M7]
                if m[0] == 1 and (m[68], m[72], m[76]) == (2, 5, 0):
                    m[68] = m[72] = 0          # 2019 clears this list unless +76 is set (54/54, 30/30)
                out += w[s:s + 4] + m + w[s + 4 + M7:s + M7 + 6] + [w[s + M7 + 7], 0]  # f32 1/6, 1.0 -> 1.0, 0
            i += 5 + n * (M7 + 8)
        elif (w[i] == 0x13 and 0 < n < 64 and w[i + 5] == 0x3E2AAA3B and i + 7 + 3 * n <= len(w)
                and all(w[i + 7 + 3 * j] == 0xD for j in range(n))):
            # 0x13 auto layer: u32 type, u64 name, u32 n, u32, f32 1/6, u32, n x (u32 0xd, u64 name)
            # -> 2019 keeps the head with the f32 0 and drops the n child names (2/2 twin nodes)
            out += w[i:i + 5] + [0, w[i + 6]]
            grow.append(((i + 7) * 4, -12 * n))
            i += 7 + 3 * n
        elif w[i] == 0xA and min(w[i + 1:i + 3], default=0) > 0x10000 and FF not in w[i + 1:i + 3]:
            # three-way node: 2018 uses id 0x0a (16 nodes, never 8), 2019 the same node as 8
            # (never 0x0a); both ids are CThreeWayEvaluator in both executables
            out.append(8)
            i += 1
        else:
            out.append(w[i])
            i += 1
    return struct.pack(f"<{len(out)}I", *out), grow


def to2019(b: bytes, name: int) -> bytes:
    """name = the set's resource name (2019 clip nodes carry it)."""
    t = parse18(b)
    c, a = t["C"], t["A"]
    order = [struct.unpack_from("<QQ", b, t["names"] + 16 * k) for k in range(c)]
    elems = {nm for nm, _ in order}
    tree18 = b[t["tree"]:t["tree"] + t["B"]]
    tree, grow = _tree(tree18, name, elems)
    recs18 = [b[t["rec"] + k * REC18:t["rec"] + (k + 1) * REC18] for k in range(a)]
    offs = sorted({struct.unpack_from("<I", r, 8)[0] for r in recs18}) + [len(tree18)]
    out = bytearray(struct.pack("<6Q", 0, a, 0, len(tree), 0, c))
    for r in recs18:
        o = struct.unpack_from("<I", r, 8)[0]
        nr = bytearray(REC19)
        nr[:8] = r[:8]
        struct.pack_into("<I", nr, 12, o + sum(g for at, g in grow if at < o))
        for k in range(12, REC18, 4):
            v = struct.unpack_from("<I", r, k)[0]
            if v:
                if k not in REC:
                    raise ValueError(f"record field +{k} = {v} has no known 2019 slot")
                struct.pack_into("<I", nr, REC[k], v)
        sub = tree18[o:offs[offs.index(o) + 1]]
        struct.pack_into("<I", nr, 120, _active_masks(list(struct.unpack_from(f"<{len(sub) // 4}I", sub))))
        out += nr
    out += tree
    out += bytes(-len(out) % 8)
    pay = {(k, f): (p, size, cnt) for k, f, p, size, cnt in t["spans"]}
    for _, k in order:
        e = b[t["e0"] + k * ELEM18:t["e0"] + (k + 1) * ELEM18]
        p, size, cnt = pay[(k, 0x2c0)]
        if size != 56:
            raise ValueError(f"element {k}: u32 table is {size} B, 2019 keeps 56 inline")
        ne = bytearray(e[:0x2c0] + b[p:p + 56] + e[0x330:])
        struct.pack_into("<Q", ne, 0x288 + 32, 0)                   # u16 table align word
        s = _q(ne, 0x2f8 + 48)
        struct.pack_into("<Q", ne, 0x2f8 + 8, s * 64)
        out += ne
    for _, k in order:
        for f in F19:
            p, size, cnt = pay[(k, 0x330 if f == 0x2f8 else f)]
            if f == 0x2f8:
                data = b"".join(b[p + i * 96:p + i * 96 + 8] + b[p + i * 96 + 40:p + i * 96 + 96]
                                for i in range(cnt))
                el = 64
            else:
                data = b[p:p + size]
                el = 1 if f == 0x20 else (size // cnt if cnt else 1)
            if data:
                out += bytes(-len(out) % (8 if f == 0x20 else max(1, min(8, el & -el))))
            out += data
    return bytes(out)


def to_live(b: bytes, name: int) -> bytes:
    import conv_animset
    return conv_animset.convert(to2019(b, name))


def _split19(x: bytes) -> dict:
    """2019 set -> {records by name (offset word zeroed) with their subtrees, elements, payloads}."""
    a, bsz, c = _q(x, 8), _q(x, 24), _q(x, 40)
    recs = [x[48 + REC19 * k:48 + REC19 * (k + 1)] for k in range(a)]
    tree = x[48 + REC19 * a:48 + REC19 * a + bsz]
    offs = sorted({struct.unpack_from("<I", r, 12)[0] for r in recs}) + [bsz]
    sub: dict[bytes, list] = {}
    for r in recs:
        o = struct.unpack_from("<I", r, 12)[0]
        sub.setdefault(r[:8], []).append((r[:12] + bytes(4) + r[16:], tree[o:offs[offs.index(o) + 1]]))
    e0 = _al(48 + REC19 * a + bsz, 8)
    _, spans = W.walk(x, "w7")
    return dict(order=[r[:8] for r in recs], sub=sub,
                els=[x[e0 + ELEM19 * k:e0 + ELEM19 * (k + 1)] for k in range(c)],
                pays=[(f, x[p:p + n]) for k, f, p, n, _ in spans])


def _ulps(x: bytes, y: bytes) -> int | None:
    """Largest float32 distance (ULPs) between equal-length blobs; None if lengths differ."""
    if len(x) != len(y):
        return None
    n = len(x) // 4
    o = lambda v: v if v < 1 << 31 else (1 << 31) - v  # noqa: E731
    d = [abs(o(a) - o(b)) for a, b in zip(struct.unpack_from(f"<{n}I", x), struct.unpack_from(f"<{n}I", y))
         if a != b]
    return max(d, default=0) if x[4 * n:] == y[4 * n:] else 1 << 31


def _junk(w: list[int]) -> set[int]:
    """2019 tree words that are uninitialised: entry 0's bone mask of each 0x12 node, and inactive
    (header u64 0) masks, which 2018 writes as zeros and 2019 as stale memory / all-ones."""
    import conv_animset as CA
    out, i = set(), 0
    while i < len(w):
        n = w[i + 3] if i + 4 < len(w) else 0
        if (w[i] == 0x12 and w[i + 4] == 0 and 0 < n < 64 and i + 5 + n * (M7 + 8) <= len(w)
                and all(w[i + 5 + (e + 1) * (M7 + 8) - 2] == 0x3F800000 for e in range(n))):
            for e in range(n):
                m = i + 5 + e * (M7 + 8) + 4
                if e == 0 or (w[m] == 0 and w[m + 1] == 0):
                    out |= set(range(m, m + M7))
            i += 5 + n * (M7 + 8)
        else:
            i += 1
    return out


def explain(o: bytes, y: bytes) -> set[str]:
    """Why converted o differs from twin y (empty set = byte-exact)."""
    if o == y:
        return set()
    a, b, why = _split19(o), _split19(y), set()
    if sorted(a["order"]) != sorted(b["order"]):
        return {"record names differ (re-authored)"}
    if a["order"] != b["order"]:
        why.add("record order")
    for k, lst in a["sub"].items():
        for (r1, t1), (r2, t2) in zip(lst, b["sub"][k]):
            if r1 != r2:
                why.add("record fields (re-authored)")
            if t1 == t2:
                continue
            if len(t1) != len(t2):
                why.add("tree re-authored")
                continue
            w1 = list(struct.unpack_from(f"<{len(t1) // 4}I", t1))
            w2 = list(struct.unpack_from(f"<{len(t2) // 4}I", t2))
            bad = {i for i in range(len(w1)) if w1[i] != w2[i]} - _junk(w2)
            why.add("tree: bone-mask lists re-baked" if bad else "tree: uninitialised mask words")
    blobs = list(zip(a["els"], b["els"])) + [(d1, d2) for (_, d1), (_, d2) in zip(a["pays"], b["pays"])]
    if len(a["els"]) != len(b["els"]):
        why.add("element count differs")
    for d1, d2 in blobs:
        if d1 != d2:
            u = _ulps(d1, d2)
            why.add("float rounding (<= 8 ULP)" if u is not None and u <= 8 else "re-exported tracks")
    return why


def _verify() -> int:
    from collections import Counter
    c, reasons = Counter(), Counter()
    for f in sorted(TWINS18.iterdir()):
        b = f.read_bytes()
        o = to2019(b, int(f.name, 16))
        end, _ = W.walk(o, "w7")
        c["w7 walk EOF" if end == len(o) else "w7 walk MISMATCH"] += 1
        lv = to_live(b, int(f.name, 16))
        end, _ = W.walk(lv, "live")
        c["live walk EOF" if end == len(lv) else "live walk MISMATCH"] += 1
        s = SUMMER / f.name
        if not s.exists():
            c["no Summer twin"] += 1
            continue
        why = explain(o, s.read_bytes())
        c["byte-exact" if not why else ("re-authored" if any("re-" in w for w in why) else
                                        "same data (order / junk / rounding only)")] += 1
        reasons[" + ".join(sorted(why)) or "byte-exact"] += 1
    print(dict(c))
    for k, v in reasons.most_common():
        print(f"  {v:3d}  {k}")
    if HER.exists():
        b = HER.read_bytes()
        o = to2019(b, int(HER.name, 16))
        lv = to_live(b, int(HER.name, 16))
        print("her set:", len(b), "->", len(o), "w7 walk", W.walk(o, "w7")[0] == len(o),
              "->", len(lv), "live walk", W.walk(lv, "live")[0] == len(lv))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        src = Path(sys.argv[1])
        nm = int(src.name, 16)
        Path(sys.argv[2]).write_bytes(to2019(src.read_bytes(), nm))
        if len(sys.argv) > 3:
            Path(sys.argv[3]).write_bytes(to_live(src.read_bytes(), nm))
        sys.exit(0)
    sys.exit(_verify())
