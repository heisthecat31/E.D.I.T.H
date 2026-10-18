"""Disassemble live echovr.exe at an RVA: python tools/dis.py <rva> [count] [exe]"""
import sys, capstone, pefile
rva = int(sys.argv[1], 16); n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
exe = sys.argv[3] if len(sys.argv) > 3 else r"H:\ready-at-dawn-echo-arena\bin\win10\echovr.exe"
pe = pefile.PE(exe, fast_load=True)
data = pe.get_memory_mapped_image()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
for i, ins in enumerate(md.disasm(data[rva:rva + n * 16], rva)):
    if i >= n: break
    print(f"{ins.address:#9x}  {ins.mnemonic:8} {ins.op_str}")
