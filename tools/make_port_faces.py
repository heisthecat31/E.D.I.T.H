"""Her mood faces: one I/O port model per face, each with its own glass texture, for
build_satellite.py --port-faces (EDITH.dll shows one port at a time, by mood).

    python tools/make_port_faces.py          # -> out/face_assets/<type>/<hash>

The faces are the user's CubeSat face sheet (24 faces, out/cubesat_faces/face_NN.png, drawn white
on black at her own face's size and spot). Picks (user, 2026-10-18): angry 17, dizzy 14,
surprised 13, hurt 16, annoyed 7; happy is her own port (prp_itt_io_port_mp_xmas), unchanged.

Per face: a copy of the port model (every 8e23e03db27c66b9 resource, renamed), of its glass shader
set 8348d8fe307ef54f (the CGShaderSetResource that names the glass texture) and of the glass
texture 3bfeb8c3e1d718a3 (BC1 sRGB 512x512, 10 mips: the two biggest are RawTexturePackfile
chunks named at low-file +40h, the other 8 follow the DDS header in the low file at +100h).
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoCombat\tools")
from le_symbol_names import symbol64                                   # noqa: E402

ASSETS = HERE / "out" / "her_assets"
OUT = HERE / "out" / "face_assets"
FACES = HERE / "out" / "cubesat_faces"
TEXCONV = Path(r"J:\EchoVR-Tools-Launcher\Settings\ms_texconv.exe")

PORT_MODEL = 0x8E23E03DB27C66B9          # prp_itt_io_port_mp_xmas
GLASS_SET = 0x8348D8FE307EF54F           # its glass shader set
GLASS_TEX = 0x3BFEB8C3E1D718A3           # its glass texture (her happy face)
TEX, TEX_GPU, RAW = "4a4c32c49300b8a0", "beac1969cb7b8861", "ae49fad43254367a"
SET_TYPES = ("4984e2bbb2ddb256", "43ddbd692282a6a7")                   # CGShaderSetResource Win10 / GPU
#: mood -> face sheet number (the order is the plugin's face index: 0 = happy, her own port)
MOODS = [("angry", 17), ("dizzy", 14), ("surprised", 13), ("hurt", 16), ("annoyed", 7)]


def names(mood: str) -> tuple[int, int, int]:
    """(model, shader set, texture) hashes for a mood's port."""
    return tuple(int(symbol64(f"echoenh_port_face_{mood}{s}"), 16) for s in ("", "_glass", "_glass_emi"))


def q(h: int) -> bytes:
    return struct.pack("<Q", h)


def bc1_mips(png: Path) -> list[bytes]:
    """512x512 PNG -> its 10 BC1 sRGB mips, biggest first (ms_texconv = DirectXTex texconv)."""
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([str(TEXCONV), "-nologo", "-y", "-f", "BC1_UNORM_SRGB", "-m", "10", "-w", "512", "-h", "512",
                        "-dx10", "-o", td, str(png)], check=True, capture_output=True)
        d = (Path(td) / (png.stem + ".dds")).read_bytes()
    assert d[:4] == b"DDS " and d[84:88] == b"DX10", png
    data, out, side = d[148:], [], 512
    for _ in range(10):
        n = max(1, side // 4) ** 2 * 8
        out.append(data[:n])
        data, side = data[n:], side // 2
    assert not data and len(out[0]) == 131072
    return out


def make_texture(png: Path, tex: int) -> dict[str, bytes]:
    """The glass texture's files with `png`'s pixels: {"<type>/<hash>": bytes}."""
    low = bytearray((ASSETS / TEX / f"{GLASS_TEX:016x}").read_bytes())
    old = [struct.unpack_from("<Q", low, 0x40 + 8 * i)[0] for i in range(2)]
    assert low[0x50:0x58] == b"\xff" * 8 and low[0x100:0x104] == b"DDS ", "glass texture layout changed"
    mips = bc1_mips(png)
    chunk = [tex ^ 0x5A5A0000_00000000 ^ i for i in range(2)]            # smallest first, like old
    for i, h in enumerate(chunk):
        struct.pack_into("<Q", low, 0x40 + 8 * i, h)
    body = b"".join(mips[2:])
    assert len(low) == 0x194 + len(body), (len(low), len(body))
    low[0x194:] = body
    return {f"{TEX}/{tex:016x}": bytes(low),
            f"{TEX_GPU}/{tex:016x}": (ASSETS / TEX_GPU / f"{GLASS_TEX:016x}").read_bytes(),
            f"{RAW}/{chunk[0]:016x}": mips[1],                               # 256 (old[0] was 32768 B)
            f"{RAW}/{chunk[1]:016x}": mips[0]}                               # 512


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    files: dict[str, bytes] = {}
    for mood, n in MOODS:
        model, gset, tex = names(mood)
        files.update(make_texture(FACES / f"face_{n:02d}.png", tex))
        swap = [(q(PORT_MODEL), q(model)), (q(GLASS_SET), q(gset)), (q(GLASS_TEX), q(tex))]
        for td in ASSETS.iterdir():                  # the port model's resources, renamed
            for src, h in ((td / f"{PORT_MODEL:016x}", model), (td / f"{GLASS_SET:016x}", gset)):
                if not src.is_file() or (src.stem == f"{GLASS_SET:016x}" and td.name not in SET_TYPES):
                    continue
                b = src.read_bytes()
                for a, z in swap:
                    b = b.replace(a, z)
                files[f"{td.name}/{h:016x}"] = b
        print(f"{mood:9s} face {n:2d}: model {model:016x} glass set {gset:016x} texture {tex:016x}")
    for k, b in files.items():
        p = OUT / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    print(f"{len(files)} files in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
