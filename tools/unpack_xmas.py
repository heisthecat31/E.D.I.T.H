"""Decompress every COMPRESS file under <src> into <dst> (same relative paths) and
report printable strings matching a pattern. Usage: unpack_xmas.py <src> <dst> [regex]"""
import os, re, sys
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\lone_echo_blender\app\extract\pyoodle")
import pyoodle

# a copy alone in its own folder: next to the game, its dbghelp.dll (the EchoRelay patch) loads too
pyoodle.set_dll_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "oodle", "oodle_11_win64.dll"))
src, dst = sys.argv[1], sys.argv[2]
pat = re.compile(sys.argv[3].encode(), re.I) if len(sys.argv) > 3 else None
n = 0
for root, _, files in os.walk(src):
    for f in files:
        p = os.path.join(root, f)
        out = os.path.join(dst, os.path.relpath(p, src))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        data = pyoodle.decompress(open(p, "rb").read())
        if data is None:
            print("FAILED", p)
            continue
        open(out, "wb").write(data)
        n += 1
        if pat:
            hits = {m.group() for m in re.finditer(rb"[\x20-\x7e]{4,80}", data) if pat.search(m.group())}
            if hits:
                print(os.path.relpath(p, src), len(data), sorted(hits)[:8])
print(n, "files")
