"""Her voice lines as Wwise banks, one per line, packed into out/edith_voice.bin for EDITH.dll.

    python -I tools/make_voice_banks.py [--voice <EdithVoice dir>] [--out out/edith_voice.bin] [--only KEY ...]

Each line (<key>.pcm, int16 mono 24 kHz, tools/make_voice_pack.py) becomes a bank the game's
sound engine loads from EDITH.dll's memory (AK::SoundEngine::LoadBank, in memory):

    event  FNV("play_edith_<key>") -> Play action -> sound -> media (embedded, Wwise IMA ADPCM)

The sound is built like the game's own 3D sounds (EchoCombat tools/veil_sound.py): the veil
sound's body, given the arc mine's attenuation (copied into each bank: a bank carries what its
sounds use) and positioned in 3D, with no parent, routed to bus 870370818: the bus voice chat
mixes to (event 0xf5b8b08d -> switch 991794051 -> actor-mixer 69364446 -> bus 870370818, from the
always-loaded Init bank), so her lines sit where her streamed voice did. The plugin posts the event
on her speaker's game object, which follows her.

out/edith_voice.bin ("EDVB"): u32 magic, u32 count, then per line (sorted by key) 20 ascii hex key
chars, u32 event id, u32 bank id, u32 offset, u32 size, u32 milliseconds; then the banks, each
16-byte aligned (the engine reads an in-memory bank in place).
"""
from __future__ import annotations

import argparse
import ctypes
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, r"J:\EchoVR-Tools-Launcher\EchoCombat\tools")
from veil_sound import (ATT_SRC_BANK, ATTENUATION, BANK, BANK_TYPE, SOUND, chunks,  # noqa: E402
                        hirc_object, hirc_objects, positioned)

STOCK = Path(r"H:\pcvr-extracted") / BANK_TYPE
VOICE = Path(r"C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena\bin\win10\plugins\EdithVoice")
RATE = 24000
PLUGIN_ADPCM = 0x00020001
VOICE_BUS = 870370818
SOUND_BUS, SOUND_PARENT = 17, 21          # OverrideBusId, DirectParentID in a sound's body
#: fmt chunk of a mono 24 kHz Wwise IMA ADPCM wem: tag 2, 1 channel, 24000 Hz, 13500 B/s,
#: 36-byte blocks, 4 bits, 6 extra bytes: 64 samples per block, channel config 0x4101 (mono, FC)
#: as the game's own PCM wems write it.
FMT = (b"fmt " + struct.pack("<IHHIIHHH", 0x18, 2, 1, RATE, RATE * 36 // 64, 36, 4, 6)
       + struct.pack("<HI", 64, 0x4101))


def fnv(name: str) -> int:
    """Wwise's id for a name: FNV-1 32-bit of the lowercase name."""
    h = 2166136261
    for c in name.lower().encode():
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= c
    return h


def codec():
    dll = HERE / "out" / "tools" / "adpcm_tool.dll"
    if not dll.exists():
        sys.exit(f"{dll} missing: run build_voice_banks.bat")
    lib = ctypes.CDLL(str(dll))
    lib.edith_encode.restype = ctypes.c_size_t
    lib.edith_encode.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]
    lib.edith_decode.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p]
    return lib


def adpcm_wem(lib, pcm: bytes) -> bytes:
    n = len(pcm) // 2
    out = ctypes.create_string_buffer((n + 63) // 64 * 36)
    size = lib.edith_encode(pcm, n, out)
    body = b"WAVE" + FMT + b"data" + struct.pack("<I", size) + out.raw[:size]
    return b"RIFF" + struct.pack("<I", len(body)) + body


def templates():
    """(BKHD payload, the 3D voice sound body, the attenuation body) from the game's banks."""
    veil = (STOCK / BANK).read_bytes()
    bkhd = dict(chunks(veil[16:-8]))[b"BKHD"]
    kind, att = hirc_objects((STOCK / ATT_SRC_BANK).read_bytes())[ATTENUATION]
    assert kind == 14
    body = bytearray(positioned(hirc_objects(veil)[SOUND][1], ATTENUATION))
    struct.pack_into("<II", body, SOUND_BUS, VOICE_BUS, 0)
    return bytes(bkhd), bytes(body), att


def line_bank(key: str, wem: bytes, bkhd: bytes, sound: bytes, att: bytes):
    bank_id, media = fnv(f"edith_{key}"), fnv(f"edith_media_{key}")
    sound_id, action, event = fnv(f"edith_sound_{key}"), fnv(f"edith_action_{key}"), fnv(f"play_edith_{key}")
    head = bytearray(bkhd)
    struct.pack_into("<I", head, 4, bank_id)
    body = bytearray(sound)
    struct.pack_into("<IBII", body, 0, PLUGIN_ADPCM, 0, media, len(wem))
    objs = [hirc_object(14, ATTENUATION, att), hirc_object(2, sound_id, bytes(body)),
            hirc_object(3, action, struct.pack("<HIB", 0x0403, sound_id, 0) + bytes([0, 0, 4])
                        + struct.pack("<I", bank_id)),
            hirc_object(4, event, bytes([1]) + struct.pack("<I", action))]
    hirc = struct.pack("<I", len(objs)) + b"".join(objs)
    parts = [(b"BKHD", bytes(head)), (b"DIDX", struct.pack("<3I", media, 0, len(wem))),
             (b"DATA", wem), (b"HIRC", hirc)]
    return event, bank_id, b"".join(t + struct.pack("<I", len(c)) + c for t, c in parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default=str(VOICE))
    ap.add_argument("--out", default=str(HERE / "out" / "edith_voice.bin"))
    ap.add_argument("--only", nargs="*", help="just these keys (a test bank)")
    a = ap.parse_args()
    lib = codec()
    bkhd, sound, att = templates()
    files = sorted(Path(a.voice).glob("*.pcm"))
    if a.only:
        files = [f for f in files if f.stem in a.only]
    rows, blobs, at = [], [], 0
    head = 8 + len(files) * 40
    head += -head % 16
    for f in files:
        if len(f.stem) != 20:
            continue
        pcm = f.read_bytes()
        event, bank_id, bank = line_bank(f.stem, adpcm_wem(lib, pcm), bkhd, sound, att)
        rows.append((f.stem.encode(), event, bank_id, head + at, len(bank), len(pcm) * 1000 // (2 * RATE)))
        blobs.append(bank + bytes(-len(bank) % 16))
        at += len(blobs[-1])
    out = bytearray(struct.pack("<4sI", b"EDVB", len(rows)))
    for r in rows:
        out += struct.pack("<20s5I", *r)
    out += bytes(head - len(out))
    for b in blobs:
        out += b
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_bytes(out)
    pcm_total = sum(f.stat().st_size for f in files)
    print(f"{a.out}: {len(rows)} line(s), {len(out):,} bytes (PCM was {pcm_total:,})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
