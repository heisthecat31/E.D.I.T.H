"""Build the player release: release/E.D.I.T.H-<VERSION>.zip.

    python tools/make_release.py [--loader <path to dbgcore.dll>]

Inside the zip (one top folder, E.D.I.T.H):
    install.bat, uninstall.bat, README.txt                  (release/; written with CRLF line ends)
    files/plugins/EDITH.dll                                 (out/plugin, build_satellite_plugin.bat)
    files/plugins/EDITH.ini                                 (the player defaults below)
    files/plugins/EDITH/mpl_lobby_b2.edith                  (out/E.D.I.T.H, tools/make_edith_pack.py on stock)
    files/plugins/EdithVoice/*.pcm                          (out/EdithVoice, tools/make_voice_pack.py)
    files/loader/dbgcore.dll                                (the plugin loader install.bat adds when a game has none)
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REL = HERE / "release"
LOADER = Path(r"C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena\bin\win10\dbgcore.dll")

#: player defaults: her actors in the lobby (tools/build_satellite.py), local=1 so a client on a
#: public lobby (its server doesn't run her) steers her, the shared relay for one Edith per match
INI = """[satellite]
index=659
x=0.0
y=2.3
z=0.0
snow_first=661
snow_count=6
face_first=667
face_count=5
local=1
network=1
"""


def crlf(text: str) -> bytes:
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loader", default=str(LOADER))
    a = ap.parse_args()
    version = (HERE / "VERSION").read_text(encoding="utf-8").strip()
    parts = {
        "EDITH.dll": HERE / "out" / "plugin" / "EDITH.dll",
        "mpl_lobby_b2.edith": HERE / "out" / "E.D.I.T.H" / "mpl_lobby_b2.edith",
        "EdithVoice": HERE / "out" / "EdithVoice",
        "dbgcore.dll": Path(a.loader),
    }
    for what, p in parts.items():
        if not p.exists():
            print(f"missing {what}: {p}")
            return 1
    voice = sorted(parts["EdithVoice"].glob("*"))
    out = REL / f"E.D.I.T.H-{version}.zip"
    top = "E.D.I.T.H"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for bat in ("install.bat", "uninstall.bat", "README.txt"):
            z.writestr(f"{top}/{bat}", crlf((REL / bat).read_text(encoding="utf-8")))
        z.write(parts["EDITH.dll"], f"{top}/files/plugins/EDITH.dll")
        z.writestr(f"{top}/files/plugins/EDITH.ini", crlf(INI))
        z.write(parts["mpl_lobby_b2.edith"], f"{top}/files/plugins/EDITH/mpl_lobby_b2.edith")
        for f in voice:
            if f.is_file():
                z.write(f, f"{top}/files/plugins/EdithVoice/{f.name}")
        z.write(parts["dbgcore.dll"], f"{top}/files/loader/dbgcore.dll")
    print(f"{out}: {out.stat().st_size / 1e6:.1f} MB (version {version}, {len(voice)} voice files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
