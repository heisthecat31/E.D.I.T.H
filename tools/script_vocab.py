"""What a script DLL talks about, without its PDB: the 64-bit symbol hashes it loads
(mov r64, imm64 = event / property / component / asset names) and the float constants it
reads from .rdata (speeds, timers, ranges).

    script_vocab.py <names.txt>... -- <script.dll>...

Writes nothing; prints per script: named symbols, unnamed symbols, floats (with use count).
"""
from __future__ import annotations

import collections
import os
import struct
import sys

import capstone
import pefile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import level_diff as LD  # noqa: E402


def vocab(path):
    pe = pefile.PE(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    img = pe.get_memory_mapped_image()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    syms, floats = collections.Counter(), collections.Counter()
    for s in pe.sections:
        if not s.Characteristics & 0x20000000:          # executable
            continue
        code = img[s.VirtualAddress:s.VirtualAddress + s.Misc_VirtualSize]
        for i in md.disasm(code, base + s.VirtualAddress):
            if i.mnemonic == "movabs":
                op = i.operands[1]
                if op.type == capstone.x86.X86_OP_IMM:
                    syms[op.imm & 0xFFFFFFFFFFFFFFFF] += 1
            if i.mnemonic in ("movss", "addss", "subss", "mulss", "divss", "comiss", "ucomiss",
                              "minss", "maxss", "cmpss") and "rip" in i.op_str:
                for op in i.operands:
                    if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                        t = i.address + i.size + op.mem.disp - base
                        if 0 <= t < len(img) - 4:
                            floats[round(struct.unpack_from("<f", img, t)[0], 5)] += 1
    return syms, floats


def main() -> int:
    i = sys.argv.index("--")
    names = LD.load_names(sys.argv[1:i])
    for p in sys.argv[i + 1:]:
        syms, floats = vocab(p)
        named = {h: n for h, n in ((h, names.get(h)) for h in syms) if n}
        print(f"=== {os.path.basename(p)} {names.get(int(os.path.basename(p)[:16], 16), '')}")
        print("  named:", ", ".join(f"{named[h]}" + (f"x{syms[h]}" if syms[h] > 1 else "")
                                    for h in sorted(named, key=lambda h: named[h])))
        unnamed = [h for h in syms if h not in named and h > 0xFFFFFFFF]
        print(f"  unnamed ({len(unnamed)}):", " ".join(f"{h:016x}" for h in sorted(unnamed)[:60]))
        print("  floats:", ", ".join(f"{f:g}" + (f"x{c}" if c > 1 else "") for f, c in sorted(floats.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
