"""CGDynamicInstanceResource (Christmas 2018 Win7) -> CGInstancedModelResource (Summer 2019 Win7),
which EchoPorting's conv_instmodel then takes to live.

    python tools/conv_instmodel18.py                 # check every 2018 / Summer twin, table by table
    python tools/conv_instmodel18.py <in> <out>      # convert one descriptor

2018 renamed nothing but the type: 54 of the 2018 build's 73 dynamic instances are Summer
instanced models of the same name (the GPU sidecar keeps its size). The 2018 descriptor is a
packed stream of the same records Summer keeps in rad56 tables, each table as a u32 count then
its rows:

    u32 n, n x mesh 128 | u32 n, n x render pass 104 | u32 n, n x vertex buffer 304 |
    u32 0 (vb2) | u32 0 | u32 n, n x index buffer 16 | u32 0 | u32 0 | u64 a | u64 gpu size |
    u32 n, n x material name 8 | u32 n, n x shader set 24 | u32 n, n x LOD 20 |
    u64 -1 | u64 content hash

Summer (conv_instmodel.parse_w7): u64 0, 8 x rad56 (mesh, rp, vb, vb2, -, ib, -, -), u64 a,
u64 gpu size, 4 x rad56 (material names, shader sets, LOD 24, texture overrides 8), trailer
[u64 1][u64 -1][u64 content hash], payloads in that order.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

RAD56 = 56
SUMMER = Path(r"J:\Summer")
T_DESC19, T_GPU19 = "1a8ef93542db7fd7", "39a43c1af5440f9"       # (Summer's folder drops the leading 0)


class ConvertError(ValueError):
    pass


def parse18(b: bytes) -> dict:
    o = 0

    def table(stride: int) -> list[bytes]:
        nonlocal o
        n = struct.unpack_from("<I", b, o)[0]
        o += 4
        if n > 100000:
            raise ConvertError(f"count {n} at {o - 4}")
        rows = [b[o + i * stride:o + (i + 1) * stride] for i in range(n)]
        o += n * stride
        return rows

    t = {}
    t["mesh"], t["rp"], t["vb"] = table(128), table(104), table(304)
    t["vb2"], t["e4"] = table(304), table(0)
    t["ib"] = table(16)
    t["d6"], t["d7"] = table(0), table(0)
    t["a"], t["gpusize"] = struct.unpack_from("<QQ", b, o)
    o += 16
    t["matn"], t["ssets"], t["lod"] = table(8), table(24), table(20)
    neg, t["chash"] = struct.unpack_from("<QQ", b, o)
    o += 16
    if neg != 0xFFFFFFFFFFFFFFFF or o != len(b):
        raise ConvertError(f"stream ended at {o:#x} of {len(b):#x} (marker {neg:#x})")
    if t["vb2"] or t["e4"] or t["d6"] or t["d7"]:
        raise ConvertError("data in a table Summer keeps empty")
    return t


# ---- record rules (measured on the twins; see check()) -------------------------------------

def mesh19(r: bytes) -> bytes:
    """2018 mesh record -> Summer: flag byte +76 gains 0x08 (0x01 -> 0x09)."""
    r = bytearray(r)
    r[76] |= 0x08
    return bytes(r)


def rp19(r: bytes) -> bytes:
    """2018 render pass -> Summer: the flag word at +76: 0x9008 -> 0x3008 (bit 15 -> bit 13)."""
    r = bytearray(r)
    f = struct.unpack_from("<I", r, 76)[0]
    if f & 0x8000:
        f = (f & ~0x8000) | 0x2000
    struct.pack_into("<I", r, 76, f)
    return bytes(r)


FILL = bytes.fromhex("0bffffffffffffff")


def vb19(r: bytes) -> bytes:
    """2018 vertex buffer -> Summer: 36 element slots (8 B: stream, offset, format, usage,
    usage index, ...) + count at +288. Summer:
    - texcoords (format 0x08, usage 0x02) always run to index 3: the missing ones repeat
      texcoord 0 (its offset), placed after the last real texcoord;
    - format-0x01 usage-0x04 elements come as a pair: the first gets usage index 1, the second 0;
      a lone one is followed by a copy of itself (same offset) as index 0."""
    n = struct.unpack_from("<I", r, 288)[0]
    els = [bytearray(r[i * 8:(i + 1) * 8]) for i in range(n)]
    u4 = [i for i, e in enumerate(els) if e[2] == 0x01 and e[3] == 0x04]
    if u4:
        els[u4[0]][4] = 1
        if len(u4) >= 2:
            els[u4[1]][4] = 0
        else:
            dup = bytearray(els[u4[0]])
            dup[4] = 0
            els.insert(u4[0] + 1, dup)
    tc = [i for i, e in enumerate(els) if e[2:4] == bytes([0x08, 0x02])]
    out = [bytes(e) for e in els]
    if tc:
        have = {els[i][4] for i in tc}
        tc0 = next((els[i] for i in tc if els[i][4] == 0), els[tc[0]])
        extra = [bytes(tc0[:4]) + bytes([k]) + bytes(tc0[5:]) for k in range(4) if k not in have]
        out = out[:tc[-1] + 1] + extra + out[tc[-1] + 1:]
    if len(out) > 36:
        raise ConvertError("too many vertex elements")
    body = b"".join(out) + FILL * (36 - len(out))
    return body + struct.pack("<I", len(out)) + r[292:304]


def lod19(r: bytes) -> bytes:
    first, cnt = struct.unpack_from("<HH", r, 0)
    return struct.pack("<II", first, cnt) + r[4:20]


def convert_gpu(b18: bytes, gpu: bytes) -> bytes:
    """2018 GPU sidecar -> Summer: where a vertex buffer has the format-0x01 usage-0x04 pair, the
    two 4-byte fields swap places in every vertex (with vb19's index swap the meaning is kept).
    Vertex buffer record: offset u32 +296, vertex count u32 +300; stride from conv_meshlist."""
    sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoPorting\tools")
    import conv_meshlist as ML
    g = bytearray(gpu)
    for r in parse18(b18)["vb"]:
        n = struct.unpack_from("<I", r, 288)[0]
        u4 = [r[i * 8 + 1] for i in range(n) if r[i * 8 + 2] == 0x01 and r[i * 8 + 3] == 0x04]
        if len(u4) < 2:
            continue
        a, b = u4[:2]
        off, nv = struct.unpack_from("<II", r, 296)
        stride = ML.vertex_plan(vb19(r))["stride7"]
        for v in range(nv):
            p = off + v * stride
            g[p + a:p + a + 4], g[p + b:p + b + 4] = g[p + b:p + b + 4], g[p + a:p + a + 4]
    return bytes(g)


SSET_MAP: dict[int, int] = {}       # 2018 shader set -> Summer's (filled by load_sset_map())


def rad56(size: int, count: int, p_base: int = 32) -> bytes:
    return struct.pack("<7Q", 0, size, 0, 0x0000000100000000, p_base, count, count)


def convert(b18: bytes, sset_map: dict[int, int] | None = None) -> bytes:
    t = parse18(b18)
    smap = SSET_MAP if sset_map is None else sset_map
    mesh = b"".join(mesh19(r) for r in t["mesh"])
    rp = b"".join(rp19(r) for r in t["rp"])
    vb = b"".join(vb19(r) for r in t["vb"])
    ib = b"".join(t["ib"])
    matn = b"".join(t["matn"])
    ss = []
    for r in t["ssets"]:
        h = struct.unpack_from("<Q", r, 0)[0]
        ss.append(struct.pack("<Q", smap.get(h, h)) + r[8:])
    ssets = b"".join(ss)
    lod = b"".join(lod19(r) for r in t["lod"])
    texo = bytes(8)
    out = bytearray(bytes(8))
    for payload, stride in ((mesh, 128), (rp, 104), (vb, 304), (b"", 0), (b"", 0), (ib, 16), (b"", 0), (b"", 0)):
        out += rad56(len(payload), len(payload) // stride if stride else 0)
    out += struct.pack("<QQ", t["a"], t["gpusize"])
    out += rad56(len(matn), len(matn) // 8)
    out += rad56(len(ssets), len(ssets) // 24, p_base=1)
    out += rad56(len(lod), len(lod) // 24)
    out += rad56(8, 1)
    out += struct.pack("<QQQ", len(t["mesh"]), 0xFFFFFFFFFFFFFFFF, t["chash"])   # first word = mesh count
    out += mesh + rp + vb + ib + matn + ssets + lod + texo
    return bytes(out)


# ---- twin check ------------------------------------------------------------------------------

def twins(dir18: Path) -> list[tuple[str, bytes, bytes]]:
    out = []
    for f in sorted((dir18 / "485e2b116301fd47").iterdir()):
        s = SUMMER / T_DESC19 / f.name
        if s.exists():
            out.append((f.name, f.read_bytes(), s.read_bytes()))
    return out


def load_sset_map(dir18: Path) -> dict[int, int]:
    """2018 shader set -> Summer shader set, from the twins (same row position, same material)."""
    sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoPorting\tools")
    import conv_instmodel as IM
    m: dict[int, set] = {}
    for _, a, b in twins(dir18):
        try:
            t, s = parse18(a), IM.parse_w7(b)
        except Exception:
            continue
        p = s["payloads"][9]
        for i, r in enumerate(t["ssets"]):
            if i * 24 + 24 <= len(p) and r[8:16] == p[i * 24 + 8:i * 24 + 16]:
                m.setdefault(struct.unpack_from("<Q", r, 0)[0], set()).add(struct.unpack_from("<Q", p, i * 24)[0])
    return {k: next(iter(v)) for k, v in m.items() if len(v) == 1}


def check(dir18: Path) -> int:
    sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoPorting\tools")
    import conv_instmodel as IM
    smap = load_sset_map(dir18)
    names = "mesh rp vb vb2 e4 ib d6 d7 matn ssets lod texo".split()
    bad: dict[str, int] = {}
    exact = 0
    tw = twins(dir18)
    for n, a, b in tw:
        try:
            c = convert(a, smap)
        except ConvertError as e:
            print(f"{n}: refused: {e}")
            bad["refused"] = bad.get("refused", 0) + 1
            continue
        exact += c == b
        if c == b:
            continue
        mc, ms = IM.parse_w7(c), IM.parse_w7(b)
        diff = [k for k, x, y in zip(names, mc["payloads"], ms["payloads"]) if x != y]
        if mc["chash"] != ms["chash"]:
            diff.append("chash")
        for k in diff:
            bad[k] = bad.get(k, 0) + 1
        if len(diff) and sum(bad.values()) < 12:
            print(f"{n}: differs in {diff}")
            for k in diff[:2]:
                if k in names:
                    i = names.index(k)
                    print(f"   ours   {mc['payloads'][i][:160].hex()}\n   summer {ms['payloads'][i][:160].hex()}")
    print(f"{exact}/{len(tw)} byte-exact; tables that differ: {bad}; shader-set map {len(smap)} entries")
    return 0


if __name__ == "__main__":
    D18 = Path(os.environ.get("DYN18", r"J:\TMP\claude\J--EchoVR-Tools-Launcher-EchoCombat\c845b6b3-86b4-46de-8eb7-93e2036b6785\scratchpad\dyn18"))
    if len(sys.argv) == 3:
        SSET_MAP.update(load_sset_map(D18))
        Path(sys.argv[2]).write_bytes(convert(Path(sys.argv[1]).read_bytes()))
    else:
        sys.exit(check(D18))


def to_live(b18: bytes, gpu18: bytes) -> tuple[bytes, bytes]:
    """2018 dynamic instance -> live CGInstancedModelResourceWin10 (+GPU): this file's 2018 ->
    2019 step, then EchoPorting's conv_instmodel (2019 -> live)."""
    sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoPorting\tools")
    import conv_instmodel as IM
    return IM.convert(convert(b18), convert_gpu(b18, gpu18))
