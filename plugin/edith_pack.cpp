// Edith's lobby data from .edith files: no repack of the game's _data (user, 2026-10-18).
//
// Done the way EchoVR-Map-Editor's echo_editor_loader.dll serves a .kfclvl map (see its
// loader/echo_editor_loader.cpp, Hooks C and LevelDetect, for the reverse engineering):
//   - a .edith file (tools/make_edith_pack.py) holds an engine package: manifests/<H> and
//     packages/<H>_N (zstd frames), plus the level it belongs to. At start it is unpacked into
//     <plugins>\<this dll's name>\cache\<H> (only when changed);
//   - the engine's FileExists / FileOpen of ...\manifests\<H> and ...\packages\<H>_N are
//     redirected there;
//   - when that level loads (sub_1404FE050, before its resources are read), AddManifestPackage
//     (sub_140FA1680 on the aggregator qword_1420A2AB8) merges the package into the engine's
//     index, so its resources (her new ones, and the lobby files she changes) are read from it.
// Serving lobby resources as loose files does not work: the level archive reads its members
// through zstd at their manifest positions ("Unknown frame descriptor"), hence a real package.
//
// Other loaders: echo_editor_loader.dll answers the resource request (sub_140FA1FE0) with RAW
// bytes for any key an installed, not yet mounted .kfclvl map owns. A map sharing one of her keys
// (an old satellite test map, the Summer lobby's CubeSat textures) then feeds raw bytes where her
// package frames are expected: zstd "Unknown frame descriptor", crash. So once her package is
// mounted, if another hook (a 5-byte jmp) sits on that request, a guard goes in front of it:
// requests for her keys (listed in the .edith, v2) go straight to the engine's own code through a
// trampoline built from its original first 15 bytes; every other request goes on to that hook.
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>
#include <atomic>
#include <unordered_set>
#include <detours.h>

#include "edith_pack.h"

namespace {

constexpr uintptr_t FILE_EXISTS_RVA = 0xE0CD0, FILE_OPEN_RVA = 0xE15E0, LEVEL_LOAD_RVA = 0x4FE050,
                    ADD_PACKAGE_RVA = 0xFA1680, AGGREGATOR_RVA = 0x20A2AB8;
const uint8_t FILE_EXISTS_BYTES[] = { 0x48, 0x81, 0xEC, 0x28, 0x04, 0x00, 0x00 };
const uint8_t FILE_OPEN_BYTES[] = { 0x40, 0x53, 0x57, 0x41, 0x54, 0x41, 0x55 };
const uint8_t LEVEL_LOAD_BYTES[] = { 0x48, 0x8B, 0xC4, 0x48, 0x89, 0x58, 0x08 };
const uint8_t ADD_PACKAGE_BYTES[] = { 0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x74, 0x24, 0x10, 0x57, 0x48 };

typedef bool(__fastcall *file_exists_fn)(const char *path);
typedef __int64(__fastcall *file_open_fn)(const void *path, int mode, void *out);
typedef __int64(__fastcall *level_load_fn)(void *a1, uint64_t level, void *a3);
typedef __int64(__fastcall *add_package_fn)(void *aggr, uint64_t package, uint64_t a3, void *a4, void *a5, void *a6);
file_exists_fn Real_FileExists = nullptr;
file_open_fn Real_FileOpen = nullptr;
level_load_fn Real_LevelLoad = nullptr;
add_package_fn AddPackage = nullptr;
uint8_t *g_base = nullptr;
EdithPackLog g_log = nullptr;

struct Pack {
    uint64_t package, level;
    std::string dir;                                           // cache\<H> (has manifests\, packages\)
    std::string name;                                          // the .edith file, for the log
    std::vector<std::pair<uint64_t, uint64_t>> keys;           // (type, name) it holds (v2)
    std::atomic<bool> mounted{false};
};
std::vector<Pack *> g_packs;

// --- the guard in front of other loaders' request hooks ----------------------------------------
constexpr uintptr_t IO_REQUEST_RVA = 0xFA1FE0;
//: its original first 15 bytes: mov [rsp+8],rbx / mov [rsp+18h],r8 / mov [rsp+10h],rdx (no
//: rip-relative operands, so they run anywhere); a 5-byte jmp hook leaves bytes 5..14 as they are
const uint8_t IO_REQUEST_ORIG[15] = { 0x48, 0x89, 0x5C, 0x24, 0x08, 0x4C, 0x89, 0x44, 0x24, 0x18,
                                      0x48, 0x89, 0x54, 0x24, 0x10 };
typedef __int64(__fastcall *io_request_fn)(void *rm, uint64_t type, uint64_t name, void *a4, void *a5, void *a6,
                                           void *a7, uint8_t *req);
io_request_fn g_engine_request = nullptr;                      // the engine's own code (our trampoline)
io_request_fn g_next_request = nullptr;                        // whoever hooked it before us
struct KeyHash {
    size_t operator()(const std::pair<uint64_t, uint64_t> &k) const { return (size_t)(k.first * 0x9E3779B97F4A7C15ull ^ k.second); }
};
std::unordered_set<std::pair<uint64_t, uint64_t>, KeyHash> g_keys;   // keys of her mounted packages
std::atomic<int> g_guarded{0};

__int64 __fastcall Guard_IoRequest(void *rm, uint64_t type, uint64_t name, void *a4, void *a5, void *a6, void *a7,
                                   uint8_t *req) {
    if (g_keys.count({ type, name })) {
        if (g_guarded.fetch_add(1) < 3)
            g_log("pack: %016llx/%016llx is hers: read from her package, past the other loader",
                  (unsigned long long)type, (unsigned long long)name);
        return g_engine_request(rm, type, name, a4, a5, a6, a7, req);
    }
    return g_next_request(rm, type, name, a4, a5, a6, a7, req);
}

// Executable memory within 2 GB of `target` (a 5-byte jmp reaches it).
uint8_t *AllocNear(uint8_t *target, size_t size) {
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    uintptr_t gran = si.dwAllocationGranularity, start = (uintptr_t)target;
    for (uintptr_t d = gran; d < 0x70000000; d += gran)
        for (int s = -1; s <= 1; s += 2) {
            uintptr_t at = (start & ~(gran - 1)) + (s < 0 ? -(intptr_t)d : (intptr_t)d);
            if (void *p = VirtualAlloc((void *)at, size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)) return (uint8_t *)p;
        }
    return nullptr;
}

void WriteAbsJmp(uint8_t *at, const void *to) {                // FF 25 00000000 <abs64>
    at[0] = 0xFF; at[1] = 0x25; memset(at + 2, 0, 4);
    memcpy(at + 6, &to, 8);
}

// Only when another loader hooked the request (a jmp at its start, bytes 5..14 untouched).
void InstallGuard() {
    uint8_t *fn = g_base + IO_REQUEST_RVA;
    if (fn[0] != 0xE9) { g_log("pack: nothing else on the resource request: no guard needed"); return; }
    if (memcmp(fn + 5, IO_REQUEST_ORIG + 5, 10) || ((uintptr_t)fn & 7)) {
        g_log("pack: the resource request is hooked in a way I don't know: no guard (other maps may clash)");
        return;
    }
    uint8_t *mem = AllocNear(fn, 64);
    if (!mem) { g_log("pack: no memory near the game for the guard"); return; }
    uint8_t *tramp = mem, *stub = mem + 32;
    memcpy(tramp, IO_REQUEST_ORIG, 15);                         // the engine's first 15 bytes
    WriteAbsJmp(tramp + 15, fn + 15);                           // then on into the engine
    WriteAbsJmp(stub, (const void *)Guard_IoRequest);
    g_engine_request = (io_request_fn)tramp;
    g_next_request = (io_request_fn)(fn + 5 + *(int32_t *)(fn + 1));   // the other loader's hook
    int64_t rel = (int64_t)(stub - (fn + 5));
    uint8_t patch[8];
    memcpy(patch, fn, 8);
    patch[0] = 0xE9;
    int32_t r32 = (int32_t)rel;
    memcpy(patch + 1, &r32, 4);
    DWORD old;
    VirtualProtect(fn, 8, PAGE_EXECUTE_READWRITE, &old);
    InterlockedExchange64((volatile LONG64 *)fn, *(LONG64 *)patch);   // one aligned write: no half jmp
    VirtualProtect(fn, 8, old, &old);
    FlushInstructionCache(GetCurrentProcess(), fn, 8);
    g_log("pack: guard in front of the other loader's resource hook (%zu keys of hers)", g_keys.size());
}

bool ReadAll(HANDLE h, void *dst, uint64_t n) {
    auto p = (uint8_t *)dst;
    while (n) {
        DWORD k = (DWORD)(n > (1u << 30) ? (1u << 30) : n), got = 0;
        if (!ReadFile(h, p, k, &got, nullptr) || got != k) return false;
        p += k;
        n -= k;
    }
    return true;
}

// Unpack one .edith into cache\<H>; files already there with the right size are kept.
Pack *Unpack(const std::string &file, const std::string &cache) {
    HANDLE h = CreateFileA(file.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) return nullptr;
    struct Entry { std::string name; uint64_t size; };
    std::vector<Entry> entries;
    char magic[8];
    uint64_t package = 0, level = 0;
    uint32_t count = 0;
    bool ok = ReadAll(h, magic, 8) && !memcmp(magic, "EDITH", 5) && (magic[5] == 1 || magic[5] == 2) && !magic[6] && !magic[7] &&
              ReadAll(h, &package, 8) && ReadAll(h, &level, 8) && ReadAll(h, &count, 4) && count < 64;
    int version = ok ? magic[5] : 0;
    for (uint32_t i = 0; ok && i < count; ++i) {
        uint16_t n = 0;
        char name[256];
        uint64_t size = 0;
        ok = ReadAll(h, &n, 2) && n < sizeof name && ReadAll(h, name, n) && ReadAll(h, &size, 8);
        name[ok ? n : 0] = 0;
        for (char *c = name; *c; ++c) if (*c == '/') *c = '\\';
        if (ok && (strstr(name, "..") || (strncmp(name, "manifests\\", 10) && strncmp(name, "packages\\", 9)))) ok = false;
        entries.push_back({ name, size });
    }
    std::vector<std::pair<uint64_t, uint64_t>> keys;           // v2: (type, name) of each resource
    uint32_t nkeys = 0;
    if (ok && version >= 2) ok = ReadAll(h, &nkeys, 4) && nkeys < 100000;
    if (ok && nkeys) {
        keys.resize(nkeys);
        ok = ReadAll(h, keys.data(), (uint64_t)nkeys * 16);
    }
    char hex[17];
    snprintf(hex, sizeof hex, "%016llx", (unsigned long long)package);
    std::string dir = cache + "\\" + hex;
    std::vector<uint8_t> buf;
    for (size_t i = 0; ok && i < entries.size(); ++i) {
        std::string out = dir + "\\" + entries[i].name;
        CreateDirectoryA(cache.c_str(), nullptr);
        CreateDirectoryA(dir.c_str(), nullptr);
        CreateDirectoryA((dir + "\\manifests").c_str(), nullptr);
        CreateDirectoryA((dir + "\\packages").c_str(), nullptr);
        WIN32_FILE_ATTRIBUTE_DATA fa;
        bool same = GetFileAttributesExA(out.c_str(), GetFileExInfoStandard, &fa) &&
                    (((uint64_t)fa.nFileSizeHigh << 32) | fa.nFileSizeLow) == entries[i].size;
        if (same) {                                            // (skip its bytes)
            LARGE_INTEGER d;
            d.QuadPart = (LONGLONG)entries[i].size;
            ok = SetFilePointerEx(h, d, nullptr, FILE_CURRENT) != 0;
            continue;
        }
        buf.resize((size_t)entries[i].size);
        ok = ReadAll(h, buf.data(), entries[i].size);
        HANDLE o = ok ? CreateFileA(out.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, 0, nullptr) : INVALID_HANDLE_VALUE;
        DWORD wrote = 0;
        ok = o != INVALID_HANDLE_VALUE && WriteFile(o, buf.data(), (DWORD)buf.size(), &wrote, nullptr) && wrote == buf.size();
        if (o != INVALID_HANDLE_VALUE) CloseHandle(o);
    }
    CloseHandle(h);
    if (!ok) {
        g_log("pack: %s is damaged or not a .edith file: skipped", file.c_str());
        return nullptr;
    }
    auto p = new Pack;
    p->package = package;
    p->level = level;
    p->dir = dir;
    p->name = file.substr(file.find_last_of('\\') + 1);
    p->keys = std::move(keys);
    return p;
}

// ...\manifests\<h> or ...\packages\<h>_<n> of one of ours -> its cache copy.
bool Redirect(const char *path, std::string *out) {
    if (!path || g_packs.empty()) return false;
    const char *last = nullptr, *prev = nullptr;
    for (const char *c = path; *c; ++c)
        if (*c == '\\' || *c == '/') { prev = last; last = c; }
    if (!last || !prev) return false;
    size_t kind = (size_t)(last - prev - 1);
    const char *sub = kind == 9 && !_strnicmp(prev + 1, "manifests", 9) ? "manifests" :
                      kind == 8 && !_strnicmp(prev + 1, "packages", 8) ? "packages" : nullptr;
    if (!sub) return false;
    const char *file = last + 1;
    for (Pack *p : g_packs) {
        char hex[17];
        snprintf(hex, sizeof hex, "%016llx", (unsigned long long)p->package);
        if (_strnicmp(file, hex, 16) || (file[16] && file[16] != '_')) continue;
        *out = p->dir + "\\" + sub + "\\" + file;
        for (char &c : *out) if (c >= 'A' && c <= 'F') c = (char)(c - 'A' + 'a');
        return GetFileAttributesA(out->c_str()) != INVALID_FILE_ATTRIBUTES;
    }
    return false;
}

bool __fastcall Hooked_FileExists(const char *path) {
    std::string r;
    return Real_FileExists(Redirect(path, &r) ? r.c_str() : path);
}

__int64 __fastcall Hooked_FileOpen(const void *path, int mode, void *out) {
    std::string r;
    if (Redirect((const char *)path, &r)) {
        g_log("pack: %s -> %s", strrchr((const char *)path, '\\') ? strrchr((const char *)path, '\\') + 1 : (const char *)path, r.c_str());
        return Real_FileOpen(r.c_str(), mode, out);
    }
    return Real_FileOpen(path, mode, out);
}

// The level is loading (the engine is ready; its resources are read inside this call): mount ours.
__int64 __fastcall Hooked_LevelLoad(void *a1, uint64_t level, void *a3) {
    for (Pack *p : g_packs) {
        if (p->level != level || p->mounted.exchange(true)) continue;
        void *aggr = *(void **)(g_base + AGGREGATOR_RVA);
        if (!aggr) { g_log("pack: %s: the package system isn't up yet", p->name.c_str()); p->mounted = false; continue; }
        __int64 rc = AddPackage(aggr, p->package, 0, nullptr, nullptr, nullptr);
        g_log("pack: %s mounted for level %016llx: AddManifestPackage(%016llx) = %lld%s", p->name.c_str(),
              (unsigned long long)level, (unsigned long long)p->package, (long long)rc, rc ? " (FAILED)" : "");
        if (rc) continue;
        static bool guarded = false;                           // her keys win over other loaders' maps
        bool first = g_keys.empty();
        for (auto &k : p->keys) g_keys.insert(k);
        if (!guarded && first && !g_keys.empty()) { guarded = true; InstallGuard(); }
        else if (p->keys.empty()) g_log("pack: %s is an old .edith (no key list): other maps sharing her resources can still clash", p->name.c_str());
    }
    return Real_LevelLoad(a1, level, a3);
}

// Our prologue, or another plugin's hook already there (a jmp: echo_editor_loader.dll's MinHook).
bool Hookable(uintptr_t rva, const uint8_t *bytes, size_t n) {
    return g_base[rva] == 0xE9 || !memcmp(g_base + rva, bytes, n);
}

}  // namespace

int EdithPack_Install(HMODULE self, EdithPackLog log) {
    g_log = log;
    char path[MAX_PATH];
    DWORD n = GetModuleFileNameA(self, path, MAX_PATH);
    if (!n || n >= MAX_PATH) return 0;
    std::string root(path);
    size_t dot = root.find_last_of('.');
    if (dot != std::string::npos && dot > root.find_last_of('\\')) root.resize(dot);   // ...\plugins\EDITH
    WIN32_FIND_DATAA fd;
    HANDLE f = FindFirstFileA((root + "\\*.edith").c_str(), &fd);
    if (f == INVALID_HANDLE_VALUE) { log("pack: no .edith files in %s", root.c_str()); return 0; }
    do {
        if (Pack *p = Unpack(root + "\\" + fd.cFileName, root + "\\cache")) {
            g_packs.push_back(p);
            log("pack: %s: package %016llx for level %016llx", p->name.c_str(), (unsigned long long)p->package,
                (unsigned long long)p->level);
        }
    } while (FindNextFileA(f, &fd));
    FindClose(f);
    if (g_packs.empty()) return 0;
    g_base = (uint8_t *)GetModuleHandleW(nullptr);
    if (!Hookable(FILE_EXISTS_RVA, FILE_EXISTS_BYTES, sizeof FILE_EXISTS_BYTES) ||
        !Hookable(FILE_OPEN_RVA, FILE_OPEN_BYTES, sizeof FILE_OPEN_BYTES) ||
        !Hookable(LEVEL_LOAD_RVA, LEVEL_LOAD_BYTES, sizeof LEVEL_LOAD_BYTES) ||
        memcmp(g_base + ADD_PACKAGE_RVA, ADD_PACKAGE_BYTES, sizeof ADD_PACKAGE_BYTES)) {
        log("pack: the game's file / level / package functions aren't as expected: her lobby data is NOT loaded");
        return 0;
    }
    AddPackage = (add_package_fn)(g_base + ADD_PACKAGE_RVA);
    Real_FileExists = (file_exists_fn)(g_base + FILE_EXISTS_RVA);
    Real_FileOpen = (file_open_fn)(g_base + FILE_OPEN_RVA);
    Real_LevelLoad = (level_load_fn)(g_base + LEVEL_LOAD_RVA);
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_FileExists, Hooked_FileExists);
    DetourAttach(&(PVOID &)Real_FileOpen, Hooked_FileOpen);
    DetourAttach(&(PVOID &)Real_LevelLoad, Hooked_LevelLoad);
    LONG rc = DetourTransactionCommit();
    log("pack: %zu package(s) ready, hooks %ld", g_packs.size(), rc);
    return (int)g_packs.size();
}
