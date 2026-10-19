"""Build the player release: release/E.D.I.T.H-<VERSION>.zip.

    python tools/make_release.py [--dll out/plugin/EDITH.dll] [--loader <dbgcore.dll>]

E.D.I.T.H is one DLL now (docs/nevr_plan.md): her voice banks and lobby data are inside EDITH.dll, her
settings are built in, and the same DLL runs under nEVR and under the dbgcore plugin loader.

Inside the zip (one top folder, E.D.I.T.H):
    install.bat, uninstall.bat, README.txt     (release/; written with CRLF line ends)
    files/plugins/EDITH.dll                    (build_voice_banks.bat, then build_satellite_plugin.bat)
    files/loader/dbgcore.dll                   (the plugin loader install.bat adds to a game with neither
                                                nEVR nor a loader; EchoCombat's build_loader.bat)

The loader is found next to this repo (..\\EchoCombat\\out\\dbgcore.dll) unless --loader or the
EDITH_LOADER environment variable says otherwise.
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REL = HERE / "release"
LOADER = Path(os.environ.get("EDITH_LOADER") or (HERE.parent / "EchoCombat" / "out" / "dbgcore.dll"))


def crlf(text: str) -> bytes:
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll", default=str(HERE / "out" / "plugin" / "EDITH.dll"))
    ap.add_argument("--loader", default=str(LOADER))
    a = ap.parse_args()
    version = (HERE / "VERSION").read_text(encoding="utf-8").strip()
    parts = {"EDITH.dll": Path(a.dll), "dbgcore.dll": Path(a.loader)}
    for what, p in parts.items():
        if not p.exists():
            print(f"missing {what}: {p}")
            return 1
    out = REL / f"E.D.I.T.H-{version}.zip"
    top = "E.D.I.T.H"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for bat in ("install.bat", "uninstall.bat", "README.txt"):
            z.writestr(f"{top}/{bat}", crlf((REL / bat).read_text(encoding="utf-8")))
        z.write(parts["EDITH.dll"], f"{top}/files/plugins/EDITH.dll")
        z.write(parts["dbgcore.dll"], f"{top}/files/loader/dbgcore.dll")
    print(f"{out}: {out.stat().st_size / 1e6:.1f} MB (version {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
