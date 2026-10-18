"""List every sub-resource of a 2017 CArchiveResourceWin7 level archive and save the
decompressed streams. Usage: xmas_list.py <level hash> <out dir> <names.txt>
Env: LONE_ECHO_DATA_ROOT (the build's _data/5828984418/win7), LONE_ECHO_OODLE_DLL (an
isolated Oodle copy)."""
import os, struct, sys
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\lone_echo_blender\scripts")
from le_oodle import load_decompressed
from le_archive_decode import ARCHIVE_PRIMARY, ARCHIVE_GPU, archive_offsets, parse_header, entry_at

h, out, names_path = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out, exist_ok=True)
primary = load_decompressed(ARCHIVE_PRIMARY / h)
gpu = load_decompressed(ARCHIVE_GPU / h)
open(os.path.join(out, "primary.bin"), "wb").write(primary)
open(os.path.join(out, "gpu.bin"), "wb").write(gpu)
psize, gsize, data_off, h0off = archive_offsets(primary, gpu)
h0 = parse_header(primary, h0off)
h1 = parse_header(primary, h0.end)

rows = []
for which, hd, base in ((0, h0, data_off), (1, h1, 0)):
    for i in range(hd.contents.count):
        t, n, v = struct.unpack_from("<QQQ", primary, hd.contents.off + i * 24)
        if v >= hd.entries.count:
            continue
        pos, size = entry_at(primary, hd, v)
        rows.append((which, t, n, base + pos, size))

want = {t for _, t, n, _, _ in rows} | {n for _, t, n, _, _ in rows}
names = {}
with open(names_path, encoding="utf-8") as f:
    for line in f:
        k = int(line[:16], 16)
        if k in want:
            names[k] = line[17:].rstrip("\n")

with open(os.path.join(out, "contents.tsv"), "w", encoding="utf-8") as f:
    for which, t, n, off, size in rows:
        f.write(f"{'P' if which == 0 else 'G'}\t{t:016x}\t{names.get(t, '?')}\t{n:016x}\t{names.get(n, '?')}\t{off:#x}\t{size}\n")
types = {}
for which, t, n, off, size in rows:
    types.setdefault(t, [0, 0])
    types[t][0] += 1
    types[t][1] += size
for t, (c, s) in sorted(types.items(), key=lambda kv: -kv[1][1]):
    print(f"{t:016x} {names.get(t, '?'):45s} {c:6d} {s:>12d}")
print(len(rows), "sub-resources; primary", len(primary), "gpu", len(gpu))
