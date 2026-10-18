"""Port 2018 (Christmas 2018, rad15 Win7) resources to the live build's Win10 formats with
EchoPorting's converters (build_port.convert_one), into a <type10>/<name> tree.

    port_assets.py <out dir> <name hash>...       # every resource of those names, plus GPU siblings

Names live already has under the same type are skipped (the live copy is used). Resources a
converter refuses are reported and left out.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoPorting\tools")
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoCombat\tools")
from le_symbol_names import symbol64                                   # noqa: E402

EVRTOOL = r"J:\EchoVR-Tools-Launcher\EchoCombat\evrtool\evrtool.exe"
DATA18 = r"J:\echo-summer-dist\Echo VR Christmas 2018\_data\5868485946\rad15\win7"
LIVE = r"C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena\_data\5932408047\rad15\win10"
TYPE_NAMES = HERE / "out" / "xmas2017" / "type_names.txt"            # Win7 type hash -> name


#: types the 2017 Christmas lobby didn't carry, so they aren't in TYPE_NAMES
EXTRA_TYPES = ("CGParticleEffectResourceWin7", "CGParticleEffectResourceWin7GPU",
               "CGParticleGraphResourceWin7", "CGParticleGraphResourceWin7GPU", "RawTexturePackfileWin7")


def win7_types() -> dict[int, str]:
    out = {}
    for line in TYPE_NAMES.read_text(encoding="utf-8").splitlines():
        h, n = line.split(" ", 1)
        out[int(h, 16)] = n
    for n in EXTRA_TYPES:
        out[int(symbol64(n), 16)] = n
    return out


def adapt_2018(tn7: str, blob: bytes) -> bytes:
    """2018 Win7 -> the 2019 Win7 shape EchoPorting's converters were measured on (agent.md S10):
    a scene carries 8 more zero bytes at its end (31/40 twins: 2018 == 2019 + 8 x 00); a mesh
    list lacks 2019's leading u64 flag (0 or 1; 0 on most twins)."""
    if tn7 == "CGSceneResourceWin7" and blob.endswith(bytes(8)):
        return blob[:-8]
    if tn7 == "CGMeshListResourceWin7":
        return bytes(8) + blob
    return blob


def find(data_dir: str, names: list[str]) -> list[tuple[str, str]]:
    r = subprocess.run([EVRTOOL, "find", data_dir, *names], capture_output=True, text=True, check=True)
    return [tuple(l.split()[0].split("/")) for l in r.stdout.splitlines() if l.strip()]


def port(out: Path, names: list[str]) -> dict:
    os.environ.setdefault("PORT_SI_LOADSETS", "0")      # Summer-only static-set binding: off
    import build_port
    t7 = win7_types()
    found = find(DATA18, names)
    live = {(t, n) for t, n in find(LIVE, names)}
    work = out.parent / (out.name + "_src18")
    lst = work / "get.txt"
    work.mkdir(parents=True, exist_ok=True)
    lst.write_text("\n".join(f"{t}/{n}" for t, n in found))
    subprocess.run([EVRTOOL, "get", DATA18, str(lst), str(work)], check=True, capture_output=True)
    ctx = build_port.Ctx()
    report = {"ported": [], "live": [], "refused": [], "unknown": []}
    for t, n in found:
        tn7 = t7.get(int(t, 16))
        if not tn7:
            report["unknown"].append((t, n))
            continue
        if tn7.endswith("GPU"):
            continue                                     # handled with its descriptor
        tn10 = tn7[:-4] + "Win10"
        h10 = symbol64(tn10)
        if (h10, n) in live:
            report["live"].append((tn10, n))
            continue
        blob = adapt_2018(tn7, (work / t / n).read_bytes())
        g7 = symbol64(tn7 + "GPU")
        gpu = (work / g7 / n).read_bytes() if (work / g7 / n).exists() else None
        ctx.current_name = n
        try:
            d, g = build_port.convert_one(ctx, tn10, h10, blob, gpu)
        except Exception as e:                           # noqa: BLE001 -- report every refusal
            report["refused"].append((tn10, n, f"{type(e).__name__}: {e}"[:160]))
            continue
        (out / h10).mkdir(parents=True, exist_ok=True)
        (out / h10 / n).write_bytes(d)
        if g is not None:
            hg = symbol64(tn10 + "GPU")
            (out / hg).mkdir(parents=True, exist_ok=True)
            (out / hg / n).write_bytes(g)
        report["ported"].append((tn10, n))
    return report


if __name__ == "__main__":
    r = port(Path(sys.argv[1]), sys.argv[2:])
    for k, v in r.items():
        print(f"{k}: {len(v)}")
        for x in v:
            print("   ", *x)
