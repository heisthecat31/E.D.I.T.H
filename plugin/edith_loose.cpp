// Edith's lobby data, loose: no repack (user, 2026-10-18).
//
// The game asks its resource manager for every resource by (type hash, name hash); that request
// (sub_140FA1FE0, "Hook A" in EchoVR-Map-Editor/loader/echo_editor_loader.cpp, which documents the
// request layout) is detoured here. When <plugins>\<this dll's name>\data\<type>\<name> exists
// (the input-pcvr layout: 16-digit hex folders and files, leading zeros optional), the request is
// answered with that file, read raw (one uncompressed block); anything else goes to the game's own
// packages untouched. Her new files (model, textures, scripts, faces, snowballs) and the lobby
// files she changes (built on stock by tools/build_satellite.py) ship this way.
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unordered_map>
#include <string>
#include <atomic>
#include <detours.h>

#include "edith_loose.h"

namespace {

constexpr uintptr_t IO_REQUEST_RVA = 0xFA1FE0;
const uint8_t IO_REQUEST_BYTES[] = { 0x48, 0x89, 0x5C, 0x24, 0x08, 0x4C, 0x89, 0x44, 0x24, 0x18, 0x48, 0x89 };

typedef __int64(__fastcall *io_request_fn)(void *rm, uint64_t name, uint64_t type, void *a4, void *a5, void *a6, void *a7,
                                           uint8_t *req);
io_request_fn Real_IoRequest = nullptr;
EdithLooseLog g_log = nullptr;

struct KeyHash {
    size_t operator()(const std::pair<uint64_t, uint64_t> &k) const { return (size_t)(k.first * 31 ^ k.second); }
};
std::unordered_map<std::pair<uint64_t, uint64_t>, std::wstring, KeyHash> g_files;   // (type, name) -> path
std::atomic<int> g_served{0};

bool Hex(const wchar_t *s, uint64_t *out) {
    size_t n = wcslen(s);
    if (n == 0 || n > 16) return false;
    uint64_t v = 0;
    for (size_t i = 0; i < n; ++i) {
        wchar_t c = s[i];
        int d = c >= L'0' && c <= L'9' ? c - L'0' : c >= L'a' && c <= L'f' ? c - L'a' + 10 : c >= L'A' && c <= L'F' ? c - L'A' + 10 : -1;
        if (d < 0) return false;
        v = v << 4 | (uint64_t)d;
    }
    *out = v;
    return true;
}

void Index(const std::wstring &root) {
    WIN32_FIND_DATAW td;
    HANDLE h = FindFirstFileW((root + L"\\*").c_str(), &td);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        uint64_t type;
        if (!(td.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || !Hex(td.cFileName, &type)) continue;
        std::wstring dir = root + L"\\" + td.cFileName;
        WIN32_FIND_DATAW fd;
        HANDLE g = FindFirstFileW((dir + L"\\*").c_str(), &fd);
        if (g == INVALID_HANDLE_VALUE) continue;
        do {
            uint64_t name;
            if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && Hex(fd.cFileName, &name))
                g_files[{type, name}] = dir + L"\\" + fd.cFileName;
        } while (FindNextFileW(g, &fd));
        FindClose(g);
    } while (FindNextFileW(h, &td));
    FindClose(h);
}

std::atomic<int> g_requests{0};

__int64 __fastcall Hooked_IoRequest(void *rm, uint64_t name, uint64_t type, void *a4, void *a5, void *a6, void *a7, uint8_t *req) {
    int r = ++g_requests;
    if (g_log && (r <= 3 || r % 500 == 0))
        g_log("loose: request %d (%016llx/%016llx)", r, (unsigned long long)name, (unsigned long long)type);
    // (the arguments are named as echo_editor_loader.cpp names them, but the first is the TYPE:
    //  request 1 is cb3a93530d07fdc5 of type 2a41cf1c1d9e5d32, one of the lobby's types)
    auto it = g_files.find({name, type});
    if (it != g_files.end()) {
        HANDLE h = CreateFileW(it->second.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                               FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
        if (h != INVALID_HANDLE_VALUE) {
            LARGE_INTEGER sz = {};
            GetFileSizeEx(h, &sz);
            uint64_t size = (uint64_t)sz.QuadPart;
            // the request as the engine fills it for a package block, here for one raw block
            *(void **)(req + 0) = a6;
            *(void **)(req + 8) = a7;
            *(HANDLE *)(req + 16) = h;
            *(HANDLE *)(req + 24) = h;                         // read by the block reader
            *(uint64_t *)(req + 1048) = 0;                     // package sub-index (none)
            *(uint64_t *)(req + 1056) = 0;
            *(uint64_t *)(req + 1064) = 0;                     // offset
            *(uint64_t *)(req + 1072) = size;                  // total
            *(uint64_t *)(req + 1080) = size;                  // size
            *(uint64_t *)(req + 1088) = 0;                     // block flags 0 = uncompressed
            *(uint64_t *)(req + 1096) = 0;
            *(uint64_t *)(req + 1104) = 0;
            *(uint64_t *)(req + 1112) = 0;
            *(uint64_t *)(req + 1120) = (uint64_t)a5;
            char id[40];
            _snprintf_s(id, sizeof id, _TRUNCATE, "0x%016llx.0x%016llx", (unsigned long long)type, (unsigned long long)name);
            memcpy(req + 536, id, strlen(id) + 1);
            *(uint32_t *)(req + 1140) = 0;                     // no block header
            *(uint32_t *)(req + 1128) = 1;                     // done
            int n = ++g_served;
            if (g_log && (n <= 3 || n % 50 == 0)) g_log("loose: served %d (latest %016llx/%016llx, %llu bytes)", n,
                                                         (unsigned long long)name, (unsigned long long)type,
                                                         (unsigned long long)size);
            return 0;
        }
        if (g_log) g_log("loose: can't open %ls (error %lu): the game's own copy instead", it->second.c_str(), GetLastError());
    }
    return Real_IoRequest(rm, name, type, a4, a5, a6, a7, req);
}

}  // namespace

int EdithLoose_Install(HMODULE self, EdithLooseLog log) {
    g_log = log;
    wchar_t path[MAX_PATH];
    DWORD n = GetModuleFileNameW(self, path, MAX_PATH);
    if (!n || n >= MAX_PATH) return 0;
    std::wstring root(path);
    size_t dot = root.find_last_of(L'.');
    if (dot != std::wstring::npos && dot > root.find_last_of(L'\\')) root.resize(dot);   // ...\plugins\E.D.I.T.H
    root += L"\\data";
    Index(root);
    if (g_files.empty()) {
        log("loose: nothing in %ls", root.c_str());
        return 0;
    }
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    // another plugin may have hooked it first (echo_editor_loader.dll's MinHook: a jmp); Detours
    // then hooks in front of it, and that plugin's hook still runs for whatever isn't ours
    bool chained = base[IO_REQUEST_RVA] == 0xE9;
    if (!chained && memcmp(base + IO_REQUEST_RVA, IO_REQUEST_BYTES, sizeof IO_REQUEST_BYTES)) {
        log("loose: the resource request isn't as expected: %zu files NOT served (repack instead)", g_files.size());
        return 0;
    }
    if (chained) log("loose: the resource request is already hooked by another plugin: hooking in front of it");
    Real_IoRequest = (io_request_fn)(base + IO_REQUEST_RVA);
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_IoRequest, Hooked_IoRequest);
    LONG rc = DetourTransactionCommit();
    log("loose: %zu files from %ls (hook %ld)", g_files.size(), root.c_str(), rc);
    return (int)g_files.size();
}
