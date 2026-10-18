"""Edith's lobby data as one .edith file (no repack of the game's _data; user, 2026-10-18).

    python tools/make_edith_pack.py [--build out/build/mpl_lobby_b2] [--out out/E.D.I.T.H/mpl_lobby_b2.edith]
                                    [--install <plugins>\\E.D.I.T.H ...]

What she adds to or changes in the lobby (tools/build_satellite.py on STOCK, no --base; files
byte-for-byte stock are left out) is packed the way the map editor packs a .kfclvl's package
(EchoVR-Map-Editor vendor rad_archive_tool.repack_archive: manifests/<H> + packages/<H>_N, zstd
frames), then both files go into one .edith container. EDITH.dll (plugin/edith_pack.cpp)
unpacks it next to itself, redirects the engine's open of manifests/<H> and packages/<H>_N there,
and mounts it with AddManifestPackage when the lobby loads, as echo_editor_loader.dll mounts a map.

.edith layout (little endian), version 2:
    "EDITH\\x02\\0\\0"  u64 package hash H  u64 level hash  u32 file count
    per file: u16 name length, name (utf-8, "manifests/<h>" or "packages/<h>_<n>"), u64 size
    u32 key count, then per resource in the package: u64 type hash, u64 name hash
    then the files' bytes, in order.
The key list lets the plugin keep other loaders (echo_editor_loader.dll's loose maps) off her
resources: their raw bytes where her package frames are expected crash the game (agent.md S29).
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
STOCK = Path(r"H:\pcvr-extracted")
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoVR-Map-Editor\echo_editor\vendor\authoring")
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoPorting\tools")
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\lone_echo_blender\scripts")

LEVEL = 0xD09AFD15B1C75C04          # mpl_lobby_b2
PACKAGE = "e.d.i.t.h_mpl_lobby_b2"  # its CSymbol64 names her package


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default=str(HERE / "out" / "build" / "mpl_lobby_b2"))
    ap.add_argument("--out", default=str(HERE / "out" / "E.D.I.T.H" / "mpl_lobby_b2.edith"))
    ap.add_argument("--install", nargs="*", default=[], help="plugin folders (<plugins>\\E.D.I.T.H) to copy it to")
    a = ap.parse_args()
    from le_symbol_names import symbol64
    import rad_archive_tool
    h = int(symbol64(PACKAGE), 16)
    build = Path(a.build)
    work = Path(tempfile.mkdtemp(prefix="edithpack"))
    stage = work / "stage" / f"0x{h:016X}"
    new = changed = 0
    keys = []                                           # (type, name) of every packed resource
    for f in sorted(build.glob("*/*")):
        ref = STOCK / f.parent.name / f.name
        if ref.exists() and filecmp.cmp(f, ref, shallow=False):
            continue
        keys.append((int(f.parent.name, 16), int(f.name, 16)))
        changed += ref.exists()
        new += not ref.exists()
        d = stage / f"0x{int(f.parent.name, 16):016X}"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, d / f"0x{int(f.name, 16):016X}.bin")
    rad_archive_tool.repack_archive(str(work / "stage"), str(work / "datadir"), None)
    win10 = work / "datadir" / "rad15" / "win10"
    files = []                                          # (engine name, path)
    for sub in ("manifests", "packages"):
        for p in sorted((win10 / sub).iterdir()):
            stem, _, part = p.name.partition("_")
            name = f"{int(stem, 16):016x}" + (f"_{part}" if part else "")   # what the engine opens
            if (sub, name) not in [(s, n) for s, n, _ in files]:
                files.append((sub, name, p))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as o:
        o.write(b"EDITH\x02\0\0" + struct.pack("<QQI", h, LEVEL, len(files)))
        for sub, name, p in files:
            n = f"{sub}/{name}".encode()
            o.write(struct.pack("<H", len(n)) + n + struct.pack("<Q", p.stat().st_size))
        o.write(struct.pack("<I", len(keys)) + b"".join(struct.pack("<QQ", t, n) for t, n in keys))
        for _, _, p in files:
            o.write(p.read_bytes())
    shutil.rmtree(work, ignore_errors=True)
    print(f"{out}: package {h:016x} for level {LEVEL:016x}, {new} new + {changed} changed resources, "
          f"{len(files)} files ({', '.join(f'{s}/{n}' for s, n, _ in files)}), {out.stat().st_size / 1e6:.1f} MB")
    for d in a.install:
        Path(d).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, Path(d) / out.name)
        print("installed:", Path(d) / out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
