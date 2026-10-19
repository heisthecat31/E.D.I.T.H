// Her voice lines as Wwise banks inside EDITH.dll: see edith_voice.h and tools/make_voice_banks.py.
#include "edith_voice.h"

#include <malloc.h>
#include <string.h>
#include <mutex>

namespace {

// AK::SoundEngine (exported by echovr.exe, Wwise 2018)
typedef int (*AkLoadBankMem_t)(const void *, uint32_t, uint32_t *);            // AKRESULT, 1 = success
typedef int (*AkUnloadBankMem_t)(uint32_t, const void *, int32_t *);
typedef uint32_t (*AkPostEvent_t)(uint32_t, uint64_t, uint32_t, void *, void *, uint32_t, void *, uint32_t);
AkLoadBankMem_t LoadBank = nullptr;
AkUnloadBankMem_t UnloadBank = nullptr;
AkPostEvent_t PostEvent = nullptr;
typedef void (*AkStopPlayingID_t)(uint32_t, int32_t, int);                    // id, fade ms, curve
AkStopPlayingID_t StopPlayingID = nullptr;
constexpr int32_t STOP_FADE_MS = 80;
constexpr int CURVE_LINEAR = 4;                                // AkCurveInterpolation_Linear
volatile uint32_t g_playing = 0;                               // the line's playing id (0: none)
HANDLE g_stop = nullptr;                                       // set: cut the line short

#pragma pack(push, 1)
struct Row { char key[20]; uint32_t event, bank, offset, size, ms; };
#pragma pack(pop)

const uint8_t *g_bin = nullptr;
const Row *g_rows = nullptr;
uint32_t g_count = 0;
EdithVoiceLog g_log = nullptr;
std::mutex g_mx;                                               // one line at a time through the engine

const Row *Find(const char *key) {
    if (!key || strlen(key) != 20) return nullptr;
    uint32_t lo = 0, hi = g_count;
    while (lo < hi) {                                          // rows are sorted by key
        uint32_t mid = (lo + hi) / 2;
        int c = memcmp(g_rows[mid].key, key, 20);
        if (!c) return &g_rows[mid];
        if (c < 0) lo = mid + 1; else hi = mid;
    }
    return nullptr;
}

}  // namespace

int Voice_Init(HMODULE self, EdithVoiceLog log) {
    g_log = log;
    HMODULE exe = GetModuleHandleW(nullptr);
    LoadBank = (AkLoadBankMem_t)GetProcAddress(exe, "?LoadBank@SoundEngine@AK@@YA?AW4AKRESULT@@PEBXKAEAK@Z");
    UnloadBank = (AkUnloadBankMem_t)GetProcAddress(exe, "?UnloadBank@SoundEngine@AK@@YA?AW4AKRESULT@@KPEBXPEAJ@Z");
    PostEvent = (AkPostEvent_t)GetProcAddress(exe, "?PostEvent@SoundEngine@AK@@YAKK_KKP6AXW4AkCallbackType@@PEAUAkCallbackInfo@@@ZPEAXKPEAUAkExternalSourceInfo@@K@Z");
    StopPlayingID = (AkStopPlayingID_t)GetProcAddress(exe, "?StopPlayingID@SoundEngine@AK@@YAXKJW4AkCurveInterpolation@@@Z");
    if (!StopPlayingID) log("voice banks: the game's StopPlayingID not found: lines can't be cut short");
    g_stop = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!LoadBank || !UnloadBank || !PostEvent) { log("voice banks: the game's LoadBank / UnloadBank / PostEvent not found"); return 0; }
    HRSRC r = FindResourceW(self, MAKEINTRESOURCEW(101), MAKEINTRESOURCEW(10));   // RT_RCDATA
    HGLOBAL h = r ? LoadResource(self, r) : nullptr;
    const uint8_t *p = h ? (const uint8_t *)LockResource(h) : nullptr;
    DWORD size = r ? SizeofResource(self, r) : 0;
    if (!p || size < 8 || memcmp(p, "EDVB", 4)) { log("voice banks: none embedded"); return 0; }
    uint32_t n;
    memcpy(&n, p + 4, 4);
    if (8 + (uint64_t)n * sizeof(Row) > size) { log("voice banks: bad table"); return 0; }
    g_bin = p;
    g_rows = (const Row *)(p + 8);
    g_count = n;
    log("voice banks: %u line(s) embedded (%lu bytes)", n, size);
    return (int)n;
}

void Voice_Stop() {
    if (g_stop && g_playing) SetEvent(g_stop);
}

int Voice_Ms(const char *key) {
    const Row *r = Find(key);
    return r ? (int)r->ms : -1;
}

bool Voice_Play(const char *key, uint64_t obj) {
    const Row *r = Find(key);
    if (!r) return false;
    std::lock_guard<std::mutex> lk(g_mx);
    // the engine reads an in-memory bank in place until it is unloaded: a 16-byte aligned copy
    void *mem = _aligned_malloc(r->size, 16);
    if (!mem) return false;
    memcpy(mem, g_bin + r->offset, r->size);
    uint32_t bank = 0;
    int rc = LoadBank(mem, r->size, &bank);
    if (rc != 1) {
        g_log("voice banks: LoadBank(%.20s) = %d", r->key, rc);
        _aligned_free(mem);
        return false;
    }
    ResetEvent(g_stop);
    uint32_t playing = PostEvent(r->event, obj, 0, nullptr, nullptr, 0, nullptr, 0);
    if (!playing) g_log("voice banks: PostEvent(%u) on %016llx failed (%.20s)", r->event, obj, r->key);
    else {
        g_playing = playing;
        if (WaitForSingleObject(g_stop, r->ms + 300) == WAIT_OBJECT_0) {   // the line, and a little of its tail
            if (StopPlayingID) StopPlayingID(playing, STOP_FADE_MS, CURVE_LINEAR);   // cut short
            Sleep(STOP_FADE_MS + 120);                         // (faded out before its bank goes)
        }
        g_playing = 0;
    }
    int32_t pool = 0;
    rc = UnloadBank(bank, mem, &pool);
    if (rc != 1) g_log("voice banks: UnloadBank(%.20s) = %d (its memory stays)", r->key, rc);
    else _aligned_free(mem);                                   // (never under a bank still loaded)
    return playing != 0;
}
