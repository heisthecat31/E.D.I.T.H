"""Replace one of her textures' pixels with a PNG, same format and mip layout (out/her_assets).

    python tools/retexture.py <texture hash> <png> [<texture hash> <png> ...]

A texture is a low file (CGTextureResourceWin10: 256-byte header with the high chunks' hashes at
+40h, smallest first, then a DDS + DX10 header at +100h and the small mips) plus one
RawTexturePackfile chunk per big mip. The PNG is encoded with Settings\ms_texconv (DirectXTex) to the
same DXGI format with every mip, then split back the same way; every file must keep its size.
The originals are copied to out/her_assets_backup/ first (once).
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ASSETS = HERE / "out" / "her_assets"
BACKUP = HERE / "out" / "her_assets_backup"
TEXCONV = Path(r"J:\EchoVR-Tools-Launcher\Settings\ms_texconv.exe")
LOW, RAW = "4a4c32c49300b8a0", "ae49fad43254367a"
FORMATS = {71: ("BC1_UNORM", 8), 72: ("BC1_UNORM_SRGB", 8), 74: ("BC2_UNORM", 16), 77: ("BC3_UNORM", 16),
           78: ("BC3_UNORM_SRGB", 16), 80: ("BC4_UNORM", 8), 83: ("BC5_UNORM", 16), 98: ("BC7_UNORM", 16),
           99: ("BC7_UNORM_SRGB", 16)}


def mip_size(side: int, bpb: int) -> int:
    return max(1, side // 4) ** 2 * bpb


def retexture(tex: str, png: Path) -> None:
    low_p = ASSETS / LOW / tex
    low = bytearray(low_p.read_bytes())
    dds = low[0x100:]
    assert dds[:4] == b"DDS " and dds[84:88] == b"DX10", f"{tex}: not a DX10 texture"
    fmt = struct.unpack_from("<I", dds, 128)[0]
    name, bpb = FORMATS[fmt]
    low_side = struct.unpack_from("<I", dds, 16)[0]
    low_mips = struct.unpack_from("<I", dds, 28)[0]
    highs = []
    for o in range(0x40, 0x100, 8):
        if low[o:o + 8] == b"\xff" * 8:
            break
        highs.append(f"{struct.unpack_from('<Q', low, o)[0]:016x}")
    full = low_side << len(highs)
    mips = len(highs) + low_mips
    with tempfile.TemporaryDirectory() as td:
        srgb = ["-srgb"] if name.endswith("_SRGB") else []    # the PNG is already sRGB: no gamma change
        subprocess.run([str(TEXCONV), "-nologo", "-y", "-f", name, "-m", str(mips), "-w", str(full), "-h", str(full),
                        "-dx10", *srgb, "-o", td, str(png)], check=True, capture_output=True)
        out = (Path(td) / (png.stem + ".dds")).read_bytes()
    assert out[84:88] == b"DX10" and struct.unpack_from("<I", out, 128)[0] == fmt, f"{tex}: texconv wrote another format"
    data, side, parts = out[148:], full, []
    for _ in range(mips):
        n = mip_size(side, bpb)
        parts.append(data[:n])
        data, side = data[n:], side // 2
    assert not data, f"{tex}: unexpected mip data left"
    for i, h in enumerate(reversed(highs)):                   # the biggest mip is the last hash
        p = ASSETS / RAW / h
        assert p.stat().st_size == len(parts[i]), f"{tex}: chunk {h} {p.stat().st_size} != {len(parts[i])}"
    body = b"".join(parts[len(highs):])
    assert len(body) == len(low) - 0x194, f"{tex}: low mips {len(body)} != {len(low) - 0x194}"
    for d, h in [(LOW, tex)] + [(RAW, h) for h in highs]:      # backup once
        b = BACKUP / d / h
        if not b.exists():
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ASSETS / d / h, b)
    for i, h in enumerate(reversed(highs)):
        (ASSETS / RAW / h).write_bytes(parts[i])
    low[0x194:] = body
    low_p.write_bytes(bytes(low))
    print(f"{tex}: {name} {full}x{full}, {mips} mips ({len(highs)} chunks + {low_mips} in the low file) <- {png.name}")


if __name__ == "__main__":
    args = sys.argv[1:]
    for i in range(0, len(args), 2):
        retexture(args[i], Path(args[i + 1]))
