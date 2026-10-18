"""Which component rows of a level mention given hashes (scripts, models, prefabs), and
which actor owns each row. Usage: find_refs.py <dir> <level> <hash>... [--names f...]"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import level_diff as LD  # noqa: E402

args = sys.argv[1:]
names_paths = []
if "--names" in args:
    i = args.index("--names")
    names_paths, args = args[i + 1:], args[:i]
d, lvl, hashes = args[0], args[1], [int(h, 16) for h in args[2:]]
names = LD.load_names(names_paths)
pats = {h: struct.pack("<Q", h) for h in hashes}
for t in sorted(os.listdir(d)):
    p = os.path.join(d, t, lvl)
    if not os.path.isfile(p):
        continue
    blob = open(p, "rb").read()
    for h, pat in pats.items():
        at = blob.find(pat)
        while at >= 0:
            # the row: walk the parsed tables for the one holding this offset
            owner = None
            st = LD.conv_cr.single_table(blob)
            tables = []
            if st and st[1]:
                tables = [(LD.conv_cr.RAD56, st[0], st[1])]
            else:
                fr = LD.conv_cr.frame(blob)
                if fr:
                    tables = [(v["payload"], v["count"], v["stride"]) for v in fr[1] if v["count"]]
            for base, count, stride in tables:
                if base <= at < base + count * stride and stride >= 16:
                    r = (at - base) // stride
                    owner = struct.unpack_from("<Q", blob, base + r * stride + 8)[0], r, at - base - r * stride
            tname = names.get(int(t, 16), t)
            if owner:
                print(f"{names.get(h, f'{h:016x}'):48s} {tname:32s} row {owner[1]:5d} +{owner[2]:<4d} actor {owner[0]:016x} {names.get(owner[0], '')}")
            else:
                print(f"{names.get(h, f'{h:016x}'):48s} {tname:32s} at {at:#x} (not in a parsed row)")
            at = blob.find(pat, at + 1)
