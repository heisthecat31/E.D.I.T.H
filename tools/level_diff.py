"""What one level adds over another, by component rows (both extracted by evrtool as
<dir>/<typehash>/<levelhash>, same build).

Every component record row starts with a per-row id (+0) and its owning actor id (+8)
(EchoPorting agent.md F8, tools/conv_cr.py). For each CR table this collects the actors that
own rows; the actors only the first level has, with the component types they own, are what
that level adds.

    level_diff.py <dirA> <levelA> <dirB> <levelB> --names <names.txt>... [--types <contents.tsv>]

--names: "<hex16> <name>" tables for actor / type / asset names. --types: a contents.tsv
(tools/xmas_list.py) whose type names give the Win7 type hashes their names.
"""
from __future__ import annotations

import argparse
import collections
import os
import struct
import sys

sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoPorting\tools")
import conv_cr  # noqa: E402


def load_names(paths):
    names = {}
    for p in paths:
        with open(p, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if len(line) > 17 and line[16] == " ":
                    try:
                        names.setdefault(int(line[:16], 16), line[17:].rstrip("\n"))
                    except ValueError:
                        pass
    return names


def load_types(path, names):
    if not path:
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) > 2 and c[2] != "?":
                names.setdefault(int(c[1], 16), c[2])


def rows_of(blob: bytes):
    """(row id, actor id) per row of every top-level table of a CR payload."""
    out = []
    st = conv_cr.single_table(blob)
    if st:
        count, stride = st
        for r in range(count):
            o = conv_cr.RAD56 + r * stride
            if stride >= 16:
                out.append(struct.unpack_from("<QQ", blob, o))
        return out
    fr = conv_cr.frame(blob)
    if not fr:
        return None
    for v in fr[1]:
        if v["count"] and v["stride"] >= 16:
            for r in range(v["count"]):
                out.append(struct.unpack_from("<QQ", blob, v["payload"] + r * v["stride"]))
    return out


def level_actors(d: str, lvl: str, names):
    by_type = {}
    for t in os.listdir(d):
        p = os.path.join(d, t, lvl)
        if not os.path.isfile(p):
            continue
        tname = names.get(int(t, 16), t)
        if "CR" not in tname:
            continue
        rows = rows_of(open(p, "rb").read())
        if rows is not None:
            by_type[t] = rows
    return by_type


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirA"), ap.add_argument("levelA"), ap.add_argument("dirB"), ap.add_argument("levelB")
    ap.add_argument("--names", nargs="*", default=[])
    ap.add_argument("--types")
    a = ap.parse_args()
    names = load_names(a.names)
    load_types(a.types, names)
    A = level_actors(a.dirA, a.levelA, names)
    B = level_actors(a.dirB, a.levelB, names)
    nm = lambda h: names.get(h, "?")
    actors_b = {act for rows in B.values() for _, act in rows}
    added = collections.defaultdict(list)          # actor -> [(type, row id)]
    print("type                                        rowsA  rowsB  newA")
    for t in sorted(A, key=lambda t: names.get(int(t, 16), t)):
        rows = A[t]
        new = [(rid, act) for rid, act in rows if act not in actors_b]
        for rid, act in new:
            added[act].append((names.get(int(t, 16), t), rid))
        print(f"{names.get(int(t, 16), t):42s} {len(rows):6d} {len(B.get(t, [])):6d} {len(new):5d}")
    print(f"\n{len(added)} actors only in {a.levelA}:")
    for act, comps in sorted(added.items(), key=lambda kv: (nm(kv[0]), kv[0])):
        kinds = collections.Counter(c for c, _ in comps)
        print(f"{act:016x} {nm(act):50s} " + ", ".join(f"{k}x{n}" if n > 1 else k for k, n in sorted(kinds.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
