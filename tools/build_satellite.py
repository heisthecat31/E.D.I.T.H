"""Build a live lobby with the satellite in it as a NEW actor, package it, and (optionally)
launch it offline on the test install.

    python tools/build_satellite.py [--name mpl_lobby_b2_sat] [--donor 8c45e06184aae5ba]
                                    [--offset 3 0 0 | --at x y z] [--model <hash>] [--launch]

1. The live mpl_lobby_b2 is cloned under --name (lone_echo_blender evr_clone_level.py, as
   EchoPorting's play.py --smoke does).
2. A new actor, CSymbol64("echoenh_satellite"), is stamped from --donor: its entry in the
   level's CActorDataResource (echomod clone_actor: signed-sorted header, the donor's
   component memberships and bits) and a copy of every component row the donor owns, with
   the owning actor (row +8) changed: CModelCR (echomod clone_model_entries, optionally with
   its model swapped for --model), CTransformCR (moved by --offset) and the one-table CRs.
3. Packaged as a .kfclvl and installed on H: (EchoPorting play.py), then launched offline
   with the F5 launch line; play.py only kills the echovr it started.
"""
from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoVR-Map-Editor\echo_editor\vendor\authoring")
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoPorting\tools")
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\lone_echo_blender\scripts")
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoCombat\tools")

from le_symbol_names import symbol64                                   # noqa: E402
import conv_cr                                                         # noqa: E402

ACTOR_NAME = "echoenh_satellite"
HER_ACTOR18 = 0x82FCB72C482B322F            # her actor in the 2018 mpl_lobby_b2_xmas
HER_MODEL = "4ab3ff017a2ce803"              # prp_itt_cube_sat_mp_xmas
HER_POSE = (-0.073, 1.239, -0.25)           # her 2018 transform (home waypoint is (0, 1.07, 0))
HER_ROT = (0.0, 0.5, 0.0, 0.866025)         # 60 degrees about Y
PORT_NAME = "echoenh_satellite_ioport"
PORT_ACTOR18 = 0x8AFC20320C9DD6DF           # her I/O port in the 2018 level (parented to her)
PORT_MODEL = "8e23e03db27c66b9"             # prp_itt_io_port_mp_xmas
PORT_OFFSET = (0.057, 0.0, 0.032)
PORT_JOINT = 0xDC009ABAB276ED03              # her root bone (bytes 03ed76b2ba9a00dc): the 2018 port row is attached to it
NCA_TRANSFORM, NCA_MODEL = 0xABFE651C8D260515, 0x38EE951A26FB816A           # 2018: port (-0.016, 1.239, -0.218) - her (-0.073, 1.239, -0.25)
#: the component tables a grabbable, thrown, networked prop has in live (her 2018 equivalents:
#: CPhysicsCR, CR15NetPhysicsCR, CR15TouchInteractCR, CR15NetTouchInteractCR; live adds a net id
#: and sync grab). Their flag words changed since 2018, so they come from a live prop.
PHYSICS_TABLES = ["CPhysicsCRWin10", "CR15NetPhysicsCRWin10", "CR15TouchInteractCRWin10",
                  "CR15NetTouchInteractCRWin10", "CR15NetIdCRWin10"]   # not CR15SyncGrabCR: the disc's own
HER_ASSETS = HERE / "out" / "her_assets"     # tools/port_assets.py output
HER_MODEL_CR18 = HERE / "out" / "xmas2018" / "mpl_lobby_b2_xmas" / "3de813820d0b4719" / "6daa6d98d9354ba5"


def th(name: str) -> str:
    return symbol64(name)


def clone_one_table(blob: bytes, donor: int, new: int) -> tuple[bytes, int]:
    """Copy every row the donor owns (+8 == donor) in a one-table CR; returns (blob, rows added)."""
    st = conv_cr.single_table(blob)
    if not st:
        raise ValueError("not a one-table CR")
    count, stride = st
    rows = [blob[conv_cr.RAD56 + i * stride: conv_cr.RAD56 + (i + 1) * stride] for i in range(count)]
    added = []
    for r in rows:
        if struct.unpack_from("<Q", r, 8)[0] == donor:
            c = bytearray(r)
            struct.pack_into("<Q", c, 8, new)
            added.append(bytes(c))
    return conv_cr.pack_table(rows + added, blob), len(added)


def clone_table_rows(blob: bytes, donor: int, new: int) -> tuple[bytes, int]:
    """Copy the donor's rows in any component table (EchoCombat cr_table layout: a root struct of
    inline array headers). The base array is the first root array whose elements name the
    donor at +8; root arrays of the same count are parallel to it (row i copied, every copy
    of the donor id inside it made `new`); a shorter 8-byte array is a per-row bitfield (the
    donor's bit copied). CAnimationCR: base 24 B, bitfield, 176 B, 8 B, 216 B init."""
    sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoCombat	ools")
    import cr_table as ct
    root = None
    for rs in range(0x38, 0x800, 8):
        try:
            root = ct.parse(blob, rs)
            break
        except Exception:
            continue
    if root is None:
        raise ValueError("not a cr_table layout")
    old_b, new_b = struct.pack("<Q", donor), struct.pack("<Q", new)
    base = next(a for a in root.arrays if a.count and a.esize >= 16 and any(
        struct.unpack_from("<Q", e.raw, 8)[0] == donor for e in a.elems))
    n = base.count
    rows = [i for i, e in enumerate(base.elems) if struct.unpack_from("<Q", e.raw, 8)[0] == donor]

    def repoint(node):
        node.raw[:] = bytes(node.raw).replace(old_b, new_b)
        for a in node.arrays:
            for e in a.elems:
                repoint(e)

    for a in root.arrays:
        if a.count == n:
            for i in rows:
                c = ct.copy(a.elems[i])
                repoint(c)
                a.elems.append(c)
            ct.set_count(root, a)
    m = n + len(rows)
    for a in root.arrays:
        if a.count != n and a.esize == 8 and a.count == (n + 63) // 64:
            words = [struct.unpack_from("<Q", e.raw)[0] for e in a.elems]
            words += [0] * ((m + 63) // 64 - len(words))
            for k, i in enumerate(rows):
                j = n + k
                bit = (words[i // 64] >> (i % 64)) & 1
                words[j // 64] |= bit << (j % 64)
            a.elems = [ct.Node(bytearray(struct.pack("<Q", w))) for w in words]
            ct.set_count(root, a)
    return ct.build(root), len(rows)


def insert_actor(ad, pos: int, donor_index: int, new: int, position, rotation=None, scale=None) -> int:
    """Insert actor `new` at actor-data index `pos`, stamped from `donor_index` (its prefab id,
    pooled count, parent, bits and component memberships), every index >= pos moving up one.

    Why not echomod clone_actor (which appends): the level's CGSceneResource keeps one world
    transform record per actor index for the first N actors (the scene actors; N = 659 in
    live mpl_lobby_b2, 659/659 records == actor r), and the pooled actors follow them. An
    actor appended after the pooled ones has no scene record and is never drawn (agent.md S12)."""
    import bisect
    from echomod.resources.actor_data import ActorDataHeaderEntry, ActorDataTransform
    s64 = lambda v: v - (1 << 64) if v >= 1 << 63 else v
    for h in ad.headers:
        if h.count >= pos:
            h.count += 1
    keys = [s64(h.type_hash) for h in ad.headers]
    ad.headers.insert(bisect.bisect_left(keys, s64(new)), ActorDataHeaderEntry(new, pos))
    t = ad.transforms[donor_index]
    rot = rotation or (t.rotation_x, t.rotation_y, t.rotation_z, t.rotation_w)
    sc = (scale,) * 3 if scale else (t.scale_x, t.scale_y, t.scale_z)
    ad.transforms.insert(pos, ActorDataTransform(*rot, *position, *sc,
                                                 t.pad0, t.pad1))
    ad.nodeids.insert(pos, new)
    ad.names.insert(pos, new)
    ad.prefabids.insert(pos, ad.prefabids[donor_index])
    ad.numpooled.insert(pos, ad.numpooled[donor_index])
    ad.parents.insert(pos, ad.parents[donor_index])
    ad.parents = [p + 1 if p != 0xFFFF and p >= pos and i != pos else p for i, p in enumerate(ad.parents)]
    d_shifted = donor_index + (donor_index >= pos)
    for comp in ad.components:
        had = donor_index in comp.actor_indices
        comp.actor_indices = [i + 1 if i >= pos else i for i in comp.actor_indices]
        if had:
            comp.actor_indices.append(pos)
            comp.actor_indices.sort()
    for k in range(5):
        words = ad.bits[k]
        bits = [(words[i // 64] >> (i % 64)) & 1 for i in range(len(words) * 64)]
        donor_bit = bits[donor_index] if donor_index < len(bits) else 0
        bits.insert(pos, donor_bit)
        nw = max(len(words), (len(ad.nodeids) + 63) // 64)
        bits = (bits + [0] * (nw * 64))[:nw * 64]
        ad.bits[k] = [sum(bits[w * 64 + j] << j for j in range(64)) for w in range(nw)]
    return pos


def _model_sections(data: bytes) -> dict:
    """A CModelCR payload split into its parts (echomod model_cr layout: 360-byte header, base
    24 B, bitfield 0, sceneset 264 B + inline tables, bitfields 1 + 2, model 296 B + inline)."""
    from echomod.resources import model_cr as M
    n = struct.unpack_from("<Q", data, 0x30)[0]
    bf0 = struct.unpack_from("<Q", data, 0x38 + 0x30)[0]
    bf1 = struct.unpack_from("<Q", data, 0xB0 + 0x30)[0]
    bf2 = struct.unpack_from("<Q", data, 0xF0 + 0x30)[0]
    o = 360
    base = [data[o + i * 24:o + (i + 1) * 24] for i in range(n)]
    o += n * 24
    bits0 = data[o:o + bf0 * 8]
    o += bf0 * 8
    ss_flat = o
    pos = ss_flat + n * 264
    ss, ss_in = [], []
    for i in range(n):
        start = pos
        pos = M._walk_entry_inline(data, ss_flat + i * 264, M.SCENESET_CTABLE_OFFSETS,
                                   special_ctable_off=208, start_pos=pos)
        ss.append(data[ss_flat + i * 264:ss_flat + (i + 1) * 264])
        ss_in.append(data[start:pos])
    bits12 = data[pos:pos + (bf1 + bf2) * 8]
    pos += (bf1 + bf2) * 8
    m_flat = pos
    pos = m_flat + n * 296
    md, md_in = [], []
    for i in range(n):
        start = pos
        pos = M._walk_entry_inline(data, m_flat + i * 296, M.MODEL_CTABLE_OFFSETS,
                                   special_ctable_off=240, start_pos=pos)
        md.append(data[m_flat + i * 296:m_flat + (i + 1) * 296])
        md_in.append(data[start:pos])
    return dict(header=data[:360], base=base, bits0=bits0, ss=ss, ss_in=ss_in, bits12=bits12,
                md=md, md_in=md_in, trailing=data[pos:])


def _model_sections_roundtrip(data: bytes) -> bool:
    s = _model_sections(data)
    return data == (s["header"] + b"".join(s["base"]) + s["bits0"] + b"".join(s["ss"]) + b"".join(s["ss_in"])
                    + s["bits12"] + b"".join(s["md"]) + b"".join(s["md_in"]) + s["trailing"])


def _swap_in_new_rows(blob: bytes, actor: int, old: int, new_h: int) -> bytes:
    """In a one-table CR, replace the u64 `old` with `new_h` inside the rows `actor` owns."""
    st = conv_cr.single_table(blob)
    if st is None:                               # multi-array table (CAnimationCR): no model ids
        if struct.pack("<Q", old) in blob:
            raise ValueError("model id in a multi-array table: not handled")
        return blob
    count, stride = st
    out = bytearray(blob)
    for i in range(count):
        o = conv_cr.RAD56 + i * stride
        if struct.unpack_from("<Q", out, o + 8)[0] != actor:
            continue
        row = bytes(out[o:o + stride]).replace(struct.pack("<Q", old), struct.pack("<Q", new_h))
        out[o:o + stride] = row
    return bytes(out)


def transplant_model_rows(dst: bytes, src: bytes, src_actor: int, new_actor: int) -> tuple[bytes, int]:
    """Append the CModelCR rows `src_actor` owns in `src` (another level's table, already in
    live format) to `dst`, owned by `new_actor` (the clone_model_entries recipe across files)."""
    from echomod.resources import model_cr as M
    S, D = _model_sections(src), _model_sections(dst)
    idx = [i for i, b in enumerate(S["base"]) if struct.unpack_from("<Q", b, 8)[0] == src_actor]
    # her rows name her old actor in more places than +8 ("Missing actor with nodeid
    # 0x82FCB72C482B322F" on load): re-point every occurrence in the parts we carry
    old_b, new_b = struct.pack("<Q", src_actor), struct.pack("<Q", new_actor)
    for k in ("base", "ss", "ss_in", "md", "md_in"):
        S[k] = [x.replace(old_b, new_b) for x in S[k]]
    n = len(D["base"]) + len(idx)
    head = bytearray(D["header"])
    M._update_desc(head, 0x00, n, 24)
    M._update_desc(head, 0x78, n, 264)
    M._update_desc(head, 0x130, n, 296)
    for at in (0x70, 0xE8, 0x128):
        struct.pack_into("<Q", head, at, n)
    out = bytearray(head)
    out += b"".join(D["base"])
    for i in idx:
        e = bytearray(S["base"][i])
        struct.pack_into("<Q", e, 8, new_actor)
        out += e
    out += D["bits0"]
    out += b"".join(D["ss"]) + b"".join(S["ss"][i] for i in idx)
    out += b"".join(D["ss_in"]) + b"".join(S["ss_in"][i] for i in idx)
    out += D["bits12"]
    out += b"".join(D["md"]) + b"".join(S["md"][i] for i in idx)
    out += b"".join(D["md_in"]) + b"".join(S["md_in"][i] for i in idx)
    out += D["trailing"]
    return bytes(out), len(idx)


def copy_model_row_bits(blob: bytes, src_actor: int, new_actor: int) -> bytes:
    """Give `new_actor`'s CModelCR rows the per-row bits (bitfields 0, 1, 2) of `src_actor`'s
    first row, and make every copy of `src_actor` in those rows `new_actor`.

    Each bitfield holds one bit per row. Bitfield 1 is set for 81 of live mpl_lobby_b2's 82
    rows (an enabled / visible flag); a row added without its bit is never drawn (agent.md
    S13). clone_model_entries also leaves the donor's id at SInitData +8."""
    S = _model_sections(blob)
    n = len(S["base"])
    owner = [struct.unpack_from("<Q", b, 8)[0] for b in S["base"]]
    src = owner.index(src_actor)
    old_b, new_b = struct.pack("<Q", src_actor), struct.pack("<Q", new_actor)
    bf = [struct.unpack_from("<Q", blob, off + 0x30)[0] for off in (0x38, 0xB0, 0xF0)]
    words = list(struct.unpack_from(f"<{bf[0]}Q", S["bits0"])) + list(
        struct.unpack_from(f"<{bf[1] + bf[2]}Q", S["bits12"]))
    fields = [words[:bf[0]], words[bf[0]:bf[0] + bf[1]], words[bf[0] + bf[1]:]]
    for i in range(n):
        if owner[i] != new_actor:
            continue
        for k in ("ss", "ss_in", "md", "md_in"):
            S[k][i] = S[k][i].replace(old_b, new_b)
        for f in fields:
            if i // 64 >= len(f):
                raise ValueError("bitfield too short for the new row")
            bit = (f[src // 64] >> (src % 64)) & 1
            f[i // 64] = (f[i // 64] & ~(1 << (i % 64))) | (bit << (i % 64))
    S["bits0"] = struct.pack(f"<{bf[0]}Q", *fields[0])
    S["bits12"] = struct.pack(f"<{bf[1] + bf[2]}Q", *(fields[1] + fields[2]))
    return (S["header"] + b"".join(S["base"]) + S["bits0"] + b"".join(S["ss"]) + b"".join(S["ss_in"])
            + S["bits12"] + b"".join(S["md"]) + b"".join(S["md_in"]) + S["trailing"])


def scene_actor_count(blob: bytes) -> int:
    sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\quest_combat_port\tools")
    from resource_io import cgsceneresource as S
    return S.read(blob)["actors"][0]


def add_scene_node(blob: bytes, donor: int, new: int, actor_index: int, position, rotation=None,
                   donor_index: int | None = None, scale=None) -> bytes:
    """Give the new actor a vertex in the scene's node graph.

    The graph's vertices are in signed-sorted actor order and the actor -> vertex lookup's
    value is the entry's own position (measured on live mpl_lobby_b2: 1768/1768); appending
    the vertex at the end broke that and the engine drew other models at the wrong nodes (a
    poster following the camera, 2026-10-17). So the vertex goes in at its sorted position
    and every vertex reference at or after it moves up one: vertex ids, edge vertex handles,
    the root / leaf lists, idxremap (identity), the per-vertex type and name tables, and, for
    a type-0 (model) vertex, the scene's actors table (one 56-byte record per type-0 vertex in
    vertex order) plus the box tree leaves that point at those records. agent.md S9."""
    sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\quest_combat_port\tools")
    from resource_io import cgsceneresource as S
    sc = S.read(blob)
    ng = sc["nodegraph"]
    U32 = 0xFFFFFFFF
    n = ng["verts"][0]
    s64 = lambda v: v - (1 << 64) if v >= 1 << 63 else v

    lk_count, lk, lk_flags = ng["lookup"]
    keys = [struct.unpack_from("<Q", lk, i * 16)[0] for i in range(lk_count)]
    vals = [struct.unpack_from("<Q", lk, i * 16 + 8)[0] for i in range(lk_count)]
    if vals != list(range(lk_count)) or keys != sorted(keys, key=s64):
        raise ValueError("scene lookup is not position-valued and signed-sorted")
    dv = keys.index(donor)
    pos = next((i for i, k in enumerate(keys) if s64(k) > s64(new)), lk_count)
    up = lambda v: v + 1 if v != U32 and v >= pos else v

    keys.insert(pos, new)
    ng["lookup"] = (n + 1, b"".join(struct.pack("<QQ", k, i) for i, k in enumerate(keys)), lk_flags)

    verts = [list(struct.unpack_from("<4I", ng["verts"][1], i * 16)) for i in range(n)]
    verts.insert(pos, [U32, U32, pos, 0])
    for i, v in enumerate(verts):
        v[2] = i
    ng["verts"] = (n + 1, b"".join(struct.pack("<4I", *v) for v in verts))

    for k in ("sedges", "tedges"):                       # (vertex handle, next edge)
        c, b = ng[k]
        e = [struct.unpack_from("<2I", b, i * 8) for i in range(c)]
        ng[k] = (c, b"".join(struct.pack("<2I", up(a), nx) for a, nx in e))

    for k in ("srcleafs", "tgtleafs"):                   # sorted (vertex, -1) lists
        c, b, extra = ng[k]
        e = [struct.unpack_from("<2I", b, i * 8) for i in range(c)]
        e = sorted([(up(a), x) for a, x in e] + [(pos, U32)])
        ng[k] = (c + 1, b"".join(struct.pack("<2I", a, x) for a, x in e), extra)

    c, b = ng["roots"]
    r = sorted([up(v) for v in struct.unpack_from(f"<{c}I", b)] + [pos])
    ng["roots"] = (c + 1, struct.pack(f"<{c + 1}I", *r))

    ng["idxremap"] = (n + 1, struct.pack(f"<{n + 1}I", *range(n + 1)))

    tps = list(struct.unpack_from(f"<{n}I", ng["types"][1]))
    names = list(struct.unpack_from(f"<{n}Q", ng["names"][1]))
    t_new = tps[dv]
    tps.insert(pos, t_new)
    names.insert(pos, names[dv])
    ng["types"] = (n + 1, struct.pack(f"<{n + 1}I", *tps))
    ng["names"] = (n + 1, struct.pack(f"<{n + 1}Q", *names))

    # the scene's actors table: one world-transform record per actor-data index for the scene
    # actors (record r == actor r: 659/659 in live mpl_lobby_b2); hers goes at her index
    ac, ab = sc["actors"]
    if actor_index > ac:
        raise ValueError(f"actor index {actor_index} past the {ac} scene records")
    recs = [ab[i * 56:(i + 1) * 56] for i in range(ac)]
    rec = bytearray(recs[donor_index])
    t = struct.unpack_from("<4f3f", rec, 16)
    struct.pack_into("<4f3f", rec, 16, *(rotation or t[:4]), *position)
    if scale:                                   # record: 2 x u64, quat, pos, scale
        struct.pack_into("<3f", rec, 44, scale, scale, scale)
    recs.insert(actor_index, bytes(rec))
    sc["actors"] = (ac + 1, b"".join(recs))
    print(f"  scene record {actor_index} (template: donor's {donor_index}) at {tuple(round(x, 3) for x in position)}")
    out = S.write(sc)
    print(f"CGSceneResource: vertex {pos} for {new:016x} (donor vertex {dv}, type {t_new}), "
          f"{len(blob)} -> {len(out)} bytes")
    return out


THRUSTER_CR18 = HERE / "out" / "xmas2018" / "mpl_lobby_b2_xmas" / "d8908f2331be77f9" / "6daa6d98d9354ba5"
THRUSTER_EFFECT = 0x1536F4115B2EA1B7        # her jet (out/her_assets, tools/port_assets.py)


def add_thrusters(blob: bytes, template_actor: int, actor18: int, new: int,
                  scale_mul: float = 1.0, joints: bool = True) -> tuple[bytes, list[int]]:
    """Her 8 thruster jets: the 2018 CParticleCRWin7 rows (176 B: name, actor, effect +32, joint
    +56, scale +96) as live CParticleEffectCR rows (152 B: effect +32, joint +48, attach word
    +56 = 0x01000002 for a joint, offset +60, euler +72, scale +84), stamped from the live row
    of `template_actor` (the donor's own particle row: the flag words live expects)."""
    count, stride = conv_cr.single_table(blob)
    rows = [blob[conv_cr.RAD56 + i * stride: conv_cr.RAD56 + (i + 1) * stride] for i in range(count)]
    tmpl = next(r for r in rows if struct.unpack_from("<Q", r, 8)[0] == template_actor)
    b18 = THRUSTER_CR18.read_bytes()
    n18 = struct.unpack_from("<Q", b18, 0x30)[0]
    names, added = [], []
    for i in range(n18):
        r18 = b18[56 + i * 176: 56 + (i + 1) * 176]
        if struct.unpack_from("<Q", r18, 8)[0] != actor18:
            continue
        name, effect, joint = (struct.unpack_from("<Q", r18, o)[0] for o in (0, 32, 56))
        scale = [x * scale_mul for x in struct.unpack_from("<3f", r18, 96)]
        r = bytearray(tmpl)
        struct.pack_into("<QQ", r, 0, name, new)
        struct.pack_into("<Q", r, 32, effect)
        if joints:
            struct.pack_into("<QI", r, 48, joint, 0x01000002)
        else:                                    # (test) on her transform, as the donor row
            struct.pack_into("<QI", r, 48, 0xFFFFFFFFFFFFFFFF, 0x01000000)
        struct.pack_into("<3f3f3f", r, 60, 0, 0, 0, 0, 0, 0, *scale)
        added.append(bytes(r))
        names.append(name)
    return conv_cr.pack_table(rows + added, blob), names


SNOW_DONOR = 0xB2791092FA9CDC6D             # a live grabbable ball (instanced model addb85401ec90c6b, r 0.041 m)
SNOW_MESH = 0x9B6B4F26CEC5F353              # her 2018 snowball (fx_..._snowball_a; tools/conv_instmodel18.py)
SNOW_ASSETS = HERE / "out" / "snow_assets"  # the mesh (2018 -> live), its material, shader sets, streaming
SNOW_PARK = (0.6, -40.0, 0.6)               # where the pool waits (in a row along +x), well under the lobby floor, out of sight


def swap_instance_mesh(blob: bytes, actor: int, mesh: int) -> tuple[bytes, int]:
    """CInstanceModelCR: every full entry (72 B, last array; actor +8, mesh +32) of `actor` names
    `mesh` instead. The live ball has two (component names 76ad752a361ad996 / 105040e0c1ec184c)."""
    from echomod.resources import instancemodel_cr as IMC
    n = struct.unpack_from("<Q", blob, IMC.DYNAMIC_DESC_OFFSETS[9] + 48)[0]
    start = len(blob) - n * 72
    out = bytearray(blob)
    k = 0
    for i in range(n):
        o = start + i * 72
        if struct.unpack_from("<Q", out, o + 8)[0] == actor:
            struct.pack_into("<Q", out, o + 32, mesh)
            k += 1
    return bytes(out), k


def set_instance_mesh(blob: bytes, actor: int, mesh: int) -> tuple[bytes, int]:
    """Make `actor`'s CInstanceModelCR rows draw `mesh`.

    The engine binds each row's mesh by position, not by the hash in its full entry: array 2 is
    the signed-sorted set of the level's instanced meshes (stored at its count: 54 x 8 B in live
    mpl_lobby_b2) and array 3 (u16 per row) is the row's slot in it (219/219 stock rows). So the
    mesh joins the set (payload grows 8 B; every slot at or past it moves up one) and the actor's
    rows point at its slot; the full entries (+32) name it too. Rewriting the set in place without
    growing it broke the level load ("offset is past the end of the stream")."""
    from echomod.resources.instancemodel_cr import InstanceModelCR
    im = InstanceModelCR.from_bytes(blob)
    A = im.array_data
    n = im.main_count
    keys = [struct.unpack_from("<Q", A[2], i * 8)[0] for i in range(len(A[2]) // 8)]
    slots = [struct.unpack_from("<H", A[3], i * 2)[0] for i in range(n)]
    s64 = lambda v: v - (1 << 64) if v >= 1 << 63 else v
    if mesh not in keys:
        if len(keys) >= im.descriptors[2].capacity:
            raise ValueError("CInstanceModelCR mesh set is full")
        at = next((i for i, k in enumerate(keys) if s64(k) > s64(mesh)), len(keys))
        keys.insert(at, mesh)
        slots = [s + 1 if s != 0xFFFF and s >= at else s for s in slots]
    slot = keys.index(mesh)
    rows = [i for i in range(n) if struct.unpack_from("<Q", A[0], i * 24 + 8)[0] == actor]
    full = bytearray(A[9])
    for i in rows:
        slots[i] = slot
        struct.pack_into("<Q", full, i * 72 + 32, mesh)
    A[2] = b"".join(struct.pack("<Q", k) for k in keys)
    A[3] = b"".join(struct.pack("<H", s) for s in slots)
    A[9] = bytes(full)
    out = im.to_bytes()
    assert InstanceModelCR.from_bytes(out).to_bytes() == out
    return out, len(rows)


def _qinv(q):
    return (-q[0], -q[1], -q[2], q[3])


def _rotate(v, q):
    """Vector v rotated by unit quaternion q (x, y, z, w)."""
    x, y, z, w = q
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + y * tz - z * ty, v[1] + w * ty + z * tx - x * tz, v[2] + w * tz + x * ty - y * tx)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="mpl_lobby_b2_sat")
    ap.add_argument("--donor", default="ad268e2881f03045")
    ap.add_argument("--offset", type=float, nargs=3, default=(3.0, 0.0, 0.0))
    ap.add_argument("--at", type=float, nargs=3, help="world position (overrides --offset)")
    ap.add_argument("--model", help="model resource hash to give her instead of the donor's")
    ap.add_argument("--her-model", action="store_true",
                    help="her own model (2018 prp_itt_cube_sat_mp_xmas, out/her_assets) and 2018 pose")
    ap.add_argument("--skip", nargs="*", default=["CScriptCRWin10", "CParticleEffectCRWin10"],
                    help="donor component tables NOT copied to her (default: its script and particles)")
    ap.add_argument("--snowballs", type=int, default=6, help="snowball pool size (0 = none)")
    ap.add_argument("--snow-mesh", action="store_true",
                    help="give them her 2018 snowball mesh (the default keeps the live ball's look, "
                         "which the user chose; the mesh swap still fails the level load, agent.md S21)")
    ap.add_argument("--jet-scale", type=float, default=1.0, help="her jets' 2018 scale (0.1) times this")
    ap.add_argument("--jet-effect", help="(test) a live effect hash for her jets instead of hers; its files ship from the live extract")
    ap.add_argument("--jet-nojoint", action="store_true", help="(test) jets on her transform, no joint")
    ap.add_argument("--no-thrusters", action="store_true", help="leave out her 8 thruster particle rows")
    ap.add_argument("--with-port", action="store_true", help="also add her I/O port (needs --her-model)")
    ap.add_argument("--port-faces", action="store_true",
                    help="also one I/O port per mood face (tools/make_port_faces.py, out/face_assets); "
                         "EDITH.dll shows one at a time")
    ap.add_argument("--physics-donor", default="8825e75eedb08b7e",
                    help="actor whose physics / grab / network rows she gets (live conventions for a "
                         "grabbable networked prop; the lobby disc). '' = none")
    ap.add_argument("--physics-tables", nargs="*", default=PHYSICS_TABLES)
    ap.add_argument("--scale", type=float, help="uniform scale (default: the donor's)")
    ap.add_argument("--rot", type=float, nargs=4, help="rotation quaternion x y z w")
    ap.add_argument("--launch", action="store_true", help="smoke test: launch, screenshot, close")
    ap.add_argument("--view", action="store_true", help="install and start the game, left running")
    ap.add_argument("--base", nargs="*", default=[],
                    help="with --name mpl_lobby_b2: folders (<type>/<hash>) whose lobby files win over stock")
    ap.add_argument("--seconds", type=float, default=240.0)
    ap.add_argument("--shots", type=float, nargs="+", default=[10.0], help="screenshot times (s)")
    a = ap.parse_args()

    from echomod.resources.actor_data import ActorDataResource
    from echomod.resources.model_cr import ModelCR, clone_model_entries
    from echomod.resources.transform_cr import TransformCR
    import evr_clone_level

    donor = int(a.donor, 16)
    new = int(symbol64(ACTOR_NAME), 16)
    lvl = evr_clone_level.rad_hash(a.name)
    staged = HERE / "out" / "build" / a.name
    shutil.rmtree(staged, ignore_errors=True)
    if a.name == "mpl_lobby_b2":
        # in place (the real lobby): no clone / rename. Each of the lobby's resources comes from the
        # first --base folder that has it (e.g. the user's already-modified input-pcvr), else stock.
        roots = [Path(b) for b in a.base] + [Path(r"H:\pcvr-extracted")]
        for td in sorted(Path(r"H:\pcvr-extracted").iterdir()):
            if not (td / lvl).is_file():
                continue
            src = next(r / td.name / lvl for r in roots if (r / td.name / lvl).is_file())
            (staged / td.name).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, staged / td.name / lvl)
            if src.parts[:2] != Path(r"H:\pcvr-extracted").parts[:2] or "input" in str(src):
                print(f"base: {td.name} from {src.parent.parent}")
    else:
        evr_clone_level.main(["mpl_lobby_b2", a.name, "--out", str(staged)])

    def path(t):
        return staged / th(t) / lvl

    def add_one(new, name, actor18, model_hex, at, attach=None):
        """attach = (parent actor id, joint name): parented to that actor's model joint (2018 port)."""
            # actor data
        p = path("CActorDataResourceWin10")
        ad = ActorDataResource.from_bytes(p.read_bytes())
        di = ad.find_actor_index(donor)
        if di is None:
            raise SystemExit(f"donor {donor:016x} not in the actor data")
        dt = ad.transforms[di]
        offset = (at[0] - dt.position_x, at[1] - dt.position_y, at[2] - dt.position_z) if at else a.offset
        pos = (dt.position_x + offset[0], dt.position_y + offset[1], dt.position_z + offset[2])
        scene_actors = scene_actor_count(path("CGSceneResourceWin10").read_bytes())
        ni = insert_actor(ad, scene_actors, di, new, pos, a.rot, a.scale)
        if attach:
            ad.parents[ni] = ad.find_actor_index(attach[0])
        p.write_bytes(ad.to_bytes())
        print(f"actor {new:016x} ({name}) index {ni} (end of the {scene_actors} scene actors), "
              f"from donor {donor:016x} index {di}, at {pos}")

        # model
        p = path("CModelCRWin10")
        mc = ModelCR.from_bytes(p.read_bytes())
        old_models = [mc.model_entries[k].model_resource_hash for k in mc.find_by_entity(donor)]
        if a.her_model:
            src = conv_cr.convert("CModelCR", HER_MODEL_CR18.read_bytes())       # 2018 -> live rows
            if actor18 == PORT_ACTOR18 and model_hex != PORT_MODEL:             # a mood-face port
                src = src.replace(struct.pack("<Q", int(PORT_MODEL, 16)), struct.pack("<Q", int(model_hex, 16)))
            assert _model_sections_roundtrip(p.read_bytes())
            nb, n = transplant_model_rows(p.read_bytes(), src, actor18, new)
            p.write_bytes(nb)
            print(f"CModelCR: {n} row(s) from 2018 actor {actor18:016x} (model {model_hex})")
        else:
            hmap = {h: int(a.model, 16) for h in old_models} if a.model else None
            p.write_bytes(clone_model_entries(p.read_bytes(), donor, new, hmap))
            print(f"CModelCR: {len(old_models)} row(s) cloned, model {[f'{h:016x}' for h in old_models]}"
                  + (f" -> {a.model}" if a.model else ""))

        p.write_bytes(copy_model_row_bits(p.read_bytes(), donor, new))

        # transform
        p = path("CTransformCRWin10")
        tr = TransformCR.from_bytes(p.read_bytes())
        src = tr.find_by_entity(donor)
        for e in src:
            c = e.clone(new)
            c.set_position(e.position_x + offset[0], e.position_y + offset[1], e.position_z + offset[2])
            if a.rot:
                c.set_rotation(*a.rot)
            if a.scale:
                c.set_scale(a.scale)
            if attach:                           # live joint attachment (parenttype 3)
                c.parenttype = 3
                c.parentxf = struct.pack("<QQQ", 0xFFFFFFFFFFFFFFFF, 0, NCA_TRANSFORM)
                c.model = struct.pack("<QQQ", attach[0], 0, NCA_MODEL)
                c.jointorrefpointname = attach[1]
                c.transformoffsettype = 1
            tr.add_entry(c)
        p.write_bytes(tr.to_bytes())
        print(f"CTransformCR: {len(src)} row(s) cloned")

        # every other CR the donor has a row in (one-table CRs only; anything else stops the build)
        done = {th("CActorDataResourceWin10"), th("CModelCRWin10"), th("CTransformCRWin10")}
        for td in sorted(staged.iterdir()):
            f = td / lvl
            if td.name in done or not f.is_file():
                continue
            b = f.read_bytes()
            if struct.pack("<Q", donor) not in b:
                continue
            if td.name == th("CGSceneResourceWin10"):
                f.write_bytes(add_scene_node(b, donor, new, ni, pos, a.rot, di, a.scale))
                continue
            if any(td.name == th(t) for t in a.skip):
                print(f"{td.name}: skipped (--skip)")
                continue
            try:
                nb, n = clone_one_table(b, donor, new)
            except ValueError:
                nb, n = clone_table_rows(b, donor, new)
            if a.her_model:                          # her rows name her model, not the donor's
                for old in old_models:
                    nb = _swap_in_new_rows(nb, new, old, int(model_hex, 16))
            f.write_bytes(nb)
            print(f"{td.name}: {n} row(s) cloned")
        return ni

    if a.her_model:
        # her own 2018 rotation, never the donor's (ad268e2881f03045 is turned 180 deg about X:
        # she came out upside down, agent.md S14)
        a.at, a.rot = a.at or HER_POSE, a.rot or HER_ROT
    her_index = add_one(new, ACTOR_NAME, HER_ACTOR18, HER_MODEL, a.at)
    if a.her_model and a.physics_donor:          # collision, grab and network: a live prop's rows
        pd = int(a.physics_donor, 16)
        for t in a.physics_tables:
            f = path(t)
            if not f.is_file() or struct.pack("<Q", pd) not in f.read_bytes():
                print(f"{t}: no rows of {pd:016x}")
                continue
            b = f.read_bytes()
            try:
                nb, n = clone_one_table(b, pd, new)
            except ValueError:
                nb, n = clone_table_rows(b, pd, new)
            f.write_bytes(nb)
            print(f"{t}: {n} row(s) from {pd:016x}")
    if a.her_model and not a.no_thrusters:       # her 8 jets (EDITH.dll scales them by thrust)
        f = path("CParticleEffectCRWin10")
        nb, names = add_thrusters(f.read_bytes(), donor, HER_ACTOR18, new, a.jet_scale, not a.jet_nojoint)
        if a.jet_effect:                         # A/B test: a live effect on her jets
            je = int(a.jet_effect, 16)
            nb = _swap_in_new_rows(nb, new, THRUSTER_EFFECT, je)
            for tn in ("CGParticleEffectResourceWin10", "CGParticleEffectResourceWin10GPU"):
                src = Path(r"H:\pcvr-extracted") / th(tn) / a.jet_effect
                if src.is_file():
                    (staged / th(tn)).mkdir(exist_ok=True)
                    shutil.copyfile(src, staged / th(tn) / a.jet_effect)
            print(f"  jets use live effect {a.jet_effect}")
        f.write_bytes(nb)
        print(f"CParticleEffectCR: {len(names)} thruster row(s): {' '.join(f'{x:016x}' for x in names)}")
    if a.with_port:                              # her I/O port: its own actor, seated on her
        off = _rotate(_rotate(PORT_OFFSET, _qinv(HER_ROT)), a.rot)   # 2018 world offset -> hers now
        add_one(int(symbol64(PORT_NAME), 16), PORT_NAME, PORT_ACTOR18, PORT_MODEL,
                tuple(x + d for x, d in zip(a.at, off)), attach=(new, PORT_JOINT))

    def add_clone(src: int, new: int, pos) -> int:
        """A new actor that is a full copy of `src` (every row it owns, its scene vertex and
        record), placed at `pos`. For instanced-model props (the snowballs)."""
        from echomod.resources import instancemodel_cr as IMC
        p = path("CActorDataResourceWin10")
        ad = ActorDataResource.from_bytes(p.read_bytes())
        di = ad.find_actor_index(src)
        scene_actors = scene_actor_count(path("CGSceneResourceWin10").read_bytes())
        ni = insert_actor(ad, scene_actors, di, new, pos)
        p.write_bytes(ad.to_bytes())
        p = path("CTransformCRWin10")
        tr = TransformCR.from_bytes(p.read_bytes())
        for e in tr.find_by_entity(src):
            c = e.clone(new)
            c.set_position(*pos)
            tr.add_entry(c)
        p.write_bytes(tr.to_bytes())
        done = {th("CActorDataResourceWin10"), th("CTransformCRWin10")}
        for td in sorted(staged.iterdir()):
            f = td / lvl
            if td.name in done or not f.is_file() or struct.pack("<Q", src) not in f.read_bytes():
                continue
            b = f.read_bytes()
            if td.name == th("CGSceneResourceWin10"):
                f.write_bytes(add_scene_node(b, src, new, ni, pos, None, di))
            elif td.name == th("CInstanceModelCRWin10"):
                f.write_bytes(IMC.clone_instancemodel_cr(b, src, new))
            else:
                try:
                    nb, _ = clone_one_table(b, src, new)
                except ValueError:
                    nb, _ = clone_table_rows(b, src, new)
                f.write_bytes(nb)
        return ni

    snow_first = None
    for k in range(a.snowballs):                 # her snowball pool, parked in a row by her home
        sid = int(symbol64(f"echoenh_snowball_{k}"), 16)
        at = (SNOW_PARK[0] + 0.12 * k, SNOW_PARK[1], SNOW_PARK[2])
        idx = add_clone(SNOW_DONOR, sid, at)
        snow_first = idx if snow_first is None else snow_first
        m = 0
        if a.snow_mesh:                          # (opt-in: the user kept the live ball's look)
            f = path("CInstanceModelCRWin10")
            nb, m = set_instance_mesh(f.read_bytes(), sid, SNOW_MESH)
            f.write_bytes(nb)
        print(f"snowball {k}: actor {sid:016x} index {idx} at {at}"
              + (f", {m} instance row(s) -> {SNOW_MESH:016x}" if m else ", the ball's own look"))
    if a.snowballs and a.snow_mesh:
        # instanced models only load when the level's CArchiveResource (its load manifest of
        # (type, name) pairs) names them -- without it the snowballs drew as the donor ball
        import evr_level_grow as GROW
        n, entries = 0, []
        gpu_types = {th(t) for t in ("CGInstancedModelResourceWin10GPU",)}
        for td in SNOW_ASSETS.iterdir():
            if not td.is_dir():
                continue
            for f in td.iterdir():
                (staged / td.name).mkdir(exist_ok=True)
                shutil.copyfile(f, staged / td.name / f.name)
                n += 1
                if td.name not in gpu_types:
                    entries.append((int(td.name, 16), int(f.name, 16)))
        arc = path("CArchiveResourceWin10")
        arc.write_bytes(GROW.add_manifest_entries(arc.read_bytes(), entries))
        print(f"snow assets: {n} files from {SNOW_ASSETS}, {len(entries)} named in the load manifest")

    face_first = None
    if a.port_faces and a.with_port:             # her mood faces: more ports in the same seat, hidden
        sys.path.insert(0, str(HERE / "tools"))  # by the plugin except the one for her mood
        import make_port_faces as FACES
        off = _rotate(_rotate(PORT_OFFSET, _qinv(HER_ROT)), a.rot)
        for mood, _ in FACES.MOODS:
            model = FACES.names(mood)[0]
            fid = int(symbol64(f"{PORT_NAME}_{mood}"), 16)
            idx = add_one(fid, f"{PORT_NAME}_{mood}", PORT_ACTOR18, f"{model:016x}",
                          tuple(x + d for x, d in zip(a.at, off)), attach=(new, PORT_JOINT))
            face_first = idx if face_first is None else face_first
        n = 0
        for td in FACES.OUT.iterdir():
            for f in td.iterdir():
                (staged / td.name).mkdir(exist_ok=True)
                shutil.copyfile(f, staged / td.name / f.name)
                n += 1
        print(f"port faces: {len(FACES.MOODS)} ports from index {face_first}, {n} files from {FACES.OUT}")

    if a.her_model:                              # her model's resources ship with the level
        n = 0
        for td in HER_ASSETS.iterdir():
            for f in td.iterdir():
                (staged / td.name).mkdir(exist_ok=True)
                shutil.copyfile(f, staged / td.name / f.name)
                n += 1
        print(f"her assets: {n} files from {HER_ASSETS}")
    if not (a.launch or a.view):
        print(f"staged in {staged}")
        return 0
    import play
    ini = play.INSTALL / "bin" / "win10" / "plugins" / "EDITH.ini"   # for plugin/satellite.cpp
    keep = [l for l in (ini.read_text().splitlines() if ini.exists() else [])     # e.g. jets_test=1
            if "=" in l and l.split("=")[0].strip() not in ("index", "x", "y", "z")]
    keep = [l for l in keep if l.split("=")[0].strip() not in ("snow_first", "snow_count")]
    keep = [l for l in keep if l.split("=")[0].strip() not in ("face_first", "face_count")]
    snow = f"snow_first={snow_first}\nsnow_count={a.snowballs}\n" if a.snowballs else ""
    if face_first is not None:
        snow += f"face_first={face_first}\nface_count={len(FACES.MOODS)}\n"
    ini.write_text(f"[satellite]\nindex={her_index}\nx={a.at[0]}\ny={a.at[1]}\nz={a.at[2]}\n" + snow
                   + "".join(l + "\n" for l in keep))
    print(f"wrote {ini} (index {her_index})")
    auth = play.backend()
    pset = play.pset_from_dir(staged, int(lvl, 16))
    kf = play.package(pset, a.name, auth)
    play.install(kf, a.name)
    if a.view:
        import subprocess
        cwd = play.INSTALL / "bin" / "win10"
        # in VR (the user plays her in the headset): never -windowed / -noovr here
        p = subprocess.Popen([str(cwd / "echovr.exe"), "-region", "usc", "-level",
                              a.name, "-gametype", "Social_2.0", "-offline"], cwd=str(cwd),
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        print(f"started echovr (pid {p.pid}), left running")
        return 0
    r = play.launch(a.name, int(lvl, 16), seconds=a.seconds, shots=tuple(a.shots), shot_tag="_sat")
    return 0 if r.get("loaded") and not r.get("fail") else 1


if __name__ == "__main__":
    sys.exit(main())
