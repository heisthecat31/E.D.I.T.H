"""Her voice lines as Wwise banks, one per line, packed into out/edith_voice.bin for EDITH.dll.

    python -I tools/make_voice_banks.py [--voice out/EdithVoice] [--out out/edith_voice.bin] [--only KEY ...]
    python -I tools/make_voice_banks.py --template-from <extracted game data root>   (once; see below)

Each line (<key>.pcm, int16 mono 24 kHz, from tools/make_voice_pack.py) becomes a bank the game's sound
engine loads from EDITH.dll's memory (AK::SoundEngine::LoadBank, in memory):

    event  FNV("play_edith_<key>") -> Play action -> sound -> media (embedded, Wwise IMA ADPCM)

The sound is built like the game's own 3D sounds (EchoCombat tools/veil_sound.py): the veil sound's
body, given the arc mine's attenuation (copied into each bank: a bank carries what its sounds use) and
positioned in 3D, with no parent, routed to bus 870370818: the bus voice chat mixes to (event
0xf5b8b08d -> switch 991794051 -> actor-mixer 69364446 -> bus 870370818, from the always-loaded Init
bank), so her lines sit where her streamed voice did. The plugin posts the event on her speaker's
game object, which follows her.

Those three pieces of the game's banks (the bank header, the sound body, the attenuation) are kept in
tools/voice_bank_template.json, so building needs no game files. --template-from rewrites it from an
extracted game (the folder holding 6d358eef7bb85a98\\<bank> files, e.g. H:\\pcvr-extracted).

out/edith_voice.bin ("EDVB"): u32 magic, u32 count, then per line (sorted by key) 20 ascii hex key
chars, u32 event id, u32 bank id, u32 offset, u32 size, u32 milliseconds; then the banks, each
16-byte aligned (the engine reads an in-memory bank in place).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TEMPLATE = HERE / "tools" / "voice_bank_template.json"
RATE = 24000
PLUGIN_ADPCM = 0x00020001
VOICE_BUS = 870370818
SOUND_BUS, SOUND_PARENT = 17, 21          # OverrideBusId, DirectParentID in a sound's body
SOUND_PROPS = 26                          # its props count; the ranged-props count and positioning follow
#: the game's banks the template comes from (CWWiseSoundBankResourceWin10 resources)
BANK_TYPE = "6d358eef7bb85a98"
VEIL_BANK, VEIL_SOUND = "3f1464db1fe49b5", 1028260926          # (the extract drops the leading 0)
ATT_BANK, ATTENUATION = "c823e2c9bc0168ad", 686965829         # the arc mine's: silent by 40 m
#: fmt chunk of a mono 24 kHz Wwise IMA ADPCM wem: tag 2, 1 channel, 24000 Hz, 13500 B/s,
#: 36-byte blocks, 4 bits, 6 extra bytes: 64 samples per block, channel config 0x4101 (mono, FC)
#: as the game's own PCM wems write it.
FMT = (b"fmt " + struct.pack("<IHHIIHHH", 0x18, 2, 1, RATE, RATE * 36 // 64, 36, 4, 6)
       + struct.pack("<HI", 64, 0x4101))


# ---- Wwise bank pieces (as EchoCombat tools/veil_sound.py) ----------------------------------------------

def chunks(bank: bytes) -> list:
    """[(tag, payload)] of a Wwise bank (starting at BKHD)."""
    out, o = [], 0
    while o + 8 <= len(bank):
        tag, size = bank[o:o + 4], struct.unpack_from("<I", bank, o + 4)[0]
        out.append((tag, bytes(bank[o + 8:o + 8 + size])))
        o += 8 + size
    if o != len(bank):
        raise ValueError("bank does not parse into chunks")
    return out


def hirc_object(kind: int, oid: int, body: bytes) -> bytes:
    return struct.pack("<BII", kind, 4 + len(body), oid) + body


def hirc_objects(asset: bytes) -> dict:
    """object id -> (kind, body), for every HIRC object of a bank resource (16-byte header, 8-byte tail)."""
    h = dict(chunks(asset[16:-8]))[b"HIRC"]
    p, out = 4, {}
    for _ in range(struct.unpack_from("<I", h, 0)[0]):
        kind, size, oid = struct.unpack_from("<BII", h, p)
        out[oid] = (kind, bytes(h[p + 9:p + 5 + size]))
        p += 5 + size
    return out


def positioned(body: bytes, attenuation: int) -> bytes:
    """A sound body (no props or positioning of its own) given 3D positioning and an attenuation:
    props {AttenuationID (0x46)}, no ranged props, posbits 3, bits3d 10, as the game's 3D sounds."""
    if body[15] or body[SOUND_PROPS:SOUND_PROPS + 3] != bytes(3):
        raise ValueError("sound object already has props or positioning")
    return (body[:SOUND_PROPS] + struct.pack("<BBIB", 1, 0x46, attenuation, 0) + bytes([3, 10])
            + body[SOUND_PROPS + 3:])


def template_from(root: Path):
    """The three pieces from an extracted game -> tools/voice_bank_template.json."""
    veil = (root / BANK_TYPE / VEIL_BANK).read_bytes()
    kind, att = hirc_objects((root / BANK_TYPE / ATT_BANK).read_bytes())[ATTENUATION]
    if kind != 14:
        raise ValueError(f"{ATT_BANK}: object {ATTENUATION} is not an attenuation")
    body = bytearray(positioned(hirc_objects(veil)[VEIL_SOUND][1], ATTENUATION))
    struct.pack_into("<II", body, SOUND_BUS, VOICE_BUS, 0)
    t = {"bkhd": dict(chunks(veil[16:-8]))[b"BKHD"].hex(), "sound": bytes(body).hex(), "attenuation": att.hex(),
         "from": f"{BANK_TYPE}/{VEIL_BANK} sound {VEIL_SOUND}, {BANK_TYPE}/{ATT_BANK} attenuation {ATTENUATION}"}
    TEMPLATE.write_text(json.dumps(t, indent=1) + "\n", encoding="utf-8")
    print(f"{TEMPLATE}: written from {root}")


def templates():
    """(BKHD payload, the 3D voice sound body, the attenuation body)."""
    if not TEMPLATE.exists():
        sys.exit(f"{TEMPLATE} missing: run with --template-from <extracted game data root>")
    t = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    return bytes.fromhex(t["bkhd"]), bytes.fromhex(t["sound"]), bytes.fromhex(t["attenuation"])


# ---- her lines -> banks ---------------------------------------------------------------------------

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
    ap.add_argument("--voice", default=str(HERE / "out" / "EdithVoice"), help="her voice pack (make_voice_pack.py)")
    ap.add_argument("--out", default=str(HERE / "out" / "edith_voice.bin"))
    ap.add_argument("--only", nargs="*", help="just these keys (a test bank)")
    ap.add_argument("--template-from", help="rewrite tools/voice_bank_template.json from an extracted game, then stop")
    a = ap.parse_args()
    if a.template_from:
        template_from(Path(a.template_from))
        return 0
    lib = codec()
    bkhd, sound, att = templates()
    files = sorted(Path(a.voice).glob("*.pcm"))
    if a.only:
        files = [f for f in files if f.stem in a.only]
    files = [f for f in files if len(f.stem) == 20]
    if not files:
        sys.exit(f"no voice lines in {a.voice}")
    rows, blobs, at = [], [], 0
    head = 8 + len(files) * 40
    head += -head % 16
    for f in files:
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
