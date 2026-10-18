"""Edith's lobby data for loose loading (plugin/edith_loose.cpp): from a tools/build_satellite.py
build on STOCK (no --base), keep what she adds or changes, drop what is byte-for-byte stock.

    python tools/make_loose_data.py [--build out/build/mpl_lobby_b2] [--out out/E.D.I.T.H/data] [--install DIR...]

The result is <type>\\<name> files; the DLL serves them from <plugins>\\<dll name>\\data. A lobby
file she changes replaces the player's own version while playing (the user's choice: loose only,
no merge), so only the files that differ from stock go in.
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
STOCK = Path(r"H:\pcvr-extracted")


def zstd_raw(data: bytes) -> bytes:
    """`data` as a zstd frame of raw (stored) blocks: the level archive reads every member through
    zstd ("Unknown frame descriptor" for plain bytes), and raw blocks need no compressor. Header:
    single segment, 8-byte content size, no checksum; blocks of at most 128 KiB."""
    out = bytearray(struct.pack("<IB", 0xFD2FB528, 0xE0) + struct.pack("<Q", len(data)))
    step = 128 * 1024
    chunks = [data[i:i + step] for i in range(0, len(data), step)] or [b""]
    for k, c in enumerate(chunks):
        last = 1 if k == len(chunks) - 1 else 0
        out += (last | (0 << 1) | (len(c) << 3)).to_bytes(3, "little") + c
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default=str(HERE / "out" / "build" / "mpl_lobby_b2"))
    ap.add_argument("--out", default=str(HERE / "out" / "E.D.I.T.H" / "data"))
    ap.add_argument("--install", nargs="*", default=[], help="also copy to these data folders")
    a = ap.parse_args()
    build, out = Path(a.build), Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    new = changed = stock = 0
    for f in sorted(build.glob("*/*")):
        ref = STOCK / f.parent.name / f.name
        if ref.exists() and filecmp.cmp(f, ref, shallow=False):
            stock += 1
            continue
        if ref.exists():
            changed += 1
        else:
            new += 1
        (out / f.parent.name).mkdir(parents=True, exist_ok=True)
        (out / f.parent.name / f.name).write_bytes(zstd_raw(f.read_bytes()))
    size = sum(f.stat().st_size for f in out.glob("*/*"))
    print(f"{out}: {new} new, {changed} changed from stock, {stock} stock left out; {size / 1e6:.1f} MB")
    for d in a.install:
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(out, d)
        print("installed:", d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
