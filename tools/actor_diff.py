"""Actors in level A that level B lacks (both extracted by evrtool: <dir>/<type>/<level>).
Usage: actor_diff.py <dirA> <levelA> <dirB> <levelB> <names...>"""
import os, sys
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\lone_echo_blender\scripts")
import evr_actor_table as AT

ACTOR_DATA = "c165fbf2e77f973d"


def actors(d, lvl):
    t = AT.ActorTable(open(os.path.join(d, ACTOR_DATA, lvl), "rb").read())
    return {h: chain for chain, h in t.r["pairs"] if chain < t.N}, t


a, ta = actors(sys.argv[1], sys.argv[2])
b, tb = actors(sys.argv[3], sys.argv[4])
names = {}
for p in sys.argv[5:]:
    with open(p, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if len(line) > 17 and line[16] == " ":
                try:
                    names.setdefault(int(line[:16], 16), line[17:].rstrip("\n"))
                except ValueError:
                    pass
new = sorted(set(a) - set(b), key=lambda h: names.get(h, "~"))
print(f"A {len(a)} actors, B {len(b)}, only in A: {len(new)}")
for h in new:
    i = a[h]
    print(f"{h:016x} idx {i:5d} prefab {ta.field(i, 'prefab_payload'):016x}  {names.get(h, '?')}  "
          f"(prefab {names.get(ta.field(i, 'prefab_payload'), '?')})")
