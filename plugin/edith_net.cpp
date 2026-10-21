// Edith networking: a WinHTTP WebSocket client to the relay (E.D.I.T.H-AI edith_relay.py, edith.echovr.de).
// The same shape as EchoXR-Hands' htv_net.cpp: one thread connects and sends, a second receives,
// both stop on error and the first reconnects with backoff. WinHTTP ships with Windows.
//
//   -> text   {"v":1,"t":"hello","name":"<me>","roster":[...],"ai":true,"build":"..."}
//   <- text   {"t":"room","host":"<name>","members":[...],"ai":[...]}   (kept here: EdithNet_Room)
//   <-> everything else is passed through (EdithNet_SendText / SendBinary / Take).

#define WIN32_LEAN_AND_MEAN
#include "edith_net.h"
#include <windows.h>
#include <winhttp.h>
#include <atomic>
#include <chrono>
#include <deque>
#include <mutex>
#include <thread>

#pragma comment(lib, "winhttp.lib")

static void (*g_log)(const char *, ...) = nullptr;
#define NLOG(...) do { if (g_log) g_log(__VA_ARGS__); } while (0)

static std::mutex g_mx;
static std::string g_url;
static int g_url_version = 0;
static std::string g_hello;                  // the hello JSON to send (rebuilt on change)
static int g_hello_version = 0;
static std::deque<EdithMsg> g_out, g_in;
static EdithRoom g_room;
static constexpr size_t OUT_MAX = 128, IN_MAX = 256;

static std::string Esc(const std::string &s) {
    std::string o;
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += (char)c; }
        else if (c < 0x20) { char b[8]; sprintf_s(b, "\\u%04x", c); o += b; }
        else o += (char)c;
    }
    return o;
}

// A JSON string starting at s[i] == '"' -> its value; i ends past the closing quote.
static bool JsonString(const std::string &s, size_t &i, std::string &out) {
    if (i >= s.size() || s[i] != '"') return false;
    out.clear();
    for (++i; i < s.size(); ++i) {
        char c = s[i];
        if (c == '"') { ++i; return true; }
        if (c == '\\' && i + 1 < s.size()) {
            char e = s[++i];
            if (e == 'u' && i + 4 < s.size()) {                 // \uXXXX (BMP) -> UTF-8
                unsigned v = strtoul(s.substr(i + 1, 4).c_str(), nullptr, 16);
                i += 4;
                if (v < 0x80) out += (char)v;
                else if (v < 0x800) { out += (char)(0xc0 | (v >> 6)); out += (char)(0x80 | (v & 0x3f)); }
                else { out += (char)(0xe0 | (v >> 12)); out += (char)(0x80 | ((v >> 6) & 0x3f)); out += (char)(0x80 | (v & 0x3f)); }
            } else out += e == 'n' ? '\n' : e == 't' ? '\t' : e;
        } else out += c;
    }
    return false;
}

static size_t Key(const std::string &s, const char *key) {
    std::string k = std::string("\"") + key + "\":";
    size_t p = s.find(k);
    return p == std::string::npos ? p : p + k.size();
}

// {"t":"room","host":"..","members":[..]} -> g_room; true if it was a room message
static bool TakeRoom(const std::string &s) {
    size_t t = Key(s, "t");
    std::string v;
    if (t == std::string::npos || !JsonString(s, t, v) || v != "room") return false;
    EdithRoom r;
    r.connected = true;
    size_t h = Key(s, "host");
    if (h != std::string::npos) JsonString(s, h, r.host);
    for (int list = 0; list < 2; ++list) {                    // "members": [..], "ai": [..]
        size_t m = Key(s, list ? "ai" : "members");
        auto &out = list ? r.ai : r.members;
        if (m == std::string::npos || m >= s.size() || s[m] != '[') continue;
        ++m;
        while (m < s.size() && s[m] != ']') {
            if (s[m] == '"') { std::string n; if (!JsonString(s, m, n)) break; out.push_back(n); }
            else ++m;
        }
    }
    std::lock_guard<std::mutex> lk(g_mx);
    g_room = r;
    return true;
}

static void Receive(HINTERNET ws, std::atomic<int> *alive) {
    uint8_t buf[4096];
    std::string msg;
    while (*alive) {
        DWORD got = 0;
        WINHTTP_WEB_SOCKET_BUFFER_TYPE type;
        if (WinHttpWebSocketReceive(ws, buf, sizeof buf, &got, &type) != ERROR_SUCCESS) break;
        if (type == WINHTTP_WEB_SOCKET_CLOSE_BUFFER_TYPE) break;
        msg.append((const char *)buf, got);
        if (type == WINHTTP_WEB_SOCKET_BINARY_FRAGMENT_BUFFER_TYPE || type == WINHTTP_WEB_SOCKET_UTF8_FRAGMENT_BUFFER_TYPE) {
            if (msg.size() > 65536) msg.clear();
            continue;
        }
        bool binary = type == WINHTTP_WEB_SOCKET_BINARY_MESSAGE_BUFFER_TYPE;
        if (binary || !TakeRoom(msg)) {
            std::lock_guard<std::mutex> lk(g_mx);
            if (g_in.size() >= IN_MAX) g_in.pop_front();
            g_in.push_back({ binary, msg });
        }
        msg.clear();
    }
    *alive = 0;
}

static bool CrackUrl(const std::string &url, std::wstring &host, std::wstring &path, INTERNET_PORT &port, bool &secure) {
    std::wstring w(url.begin(), url.end());
    if (w.compare(0, 6, L"wss://") == 0) w = L"https://" + w.substr(6);
    else if (w.compare(0, 5, L"ws://") == 0) w = L"http://" + w.substr(5);
    URL_COMPONENTS uc = {};
    uc.dwStructSize = sizeof uc;
    wchar_t h[256] = {}, p[1024] = {};
    uc.lpszHostName = h; uc.dwHostNameLength = 255;
    uc.lpszUrlPath = p; uc.dwUrlPathLength = 1023;
    if (!WinHttpCrackUrl(w.c_str(), 0, 0, &uc)) return false;
    host = h;
    path = p[0] ? p : L"/";
    port = uc.nPort;
    secure = uc.nScheme == INTERNET_SCHEME_HTTPS;
    return !host.empty();
}

static void Main() {
    int backoff = 1000;
    for (;;) {
        std::string url;
        int urlv;
        {
            std::lock_guard<std::mutex> lk(g_mx);
            url = g_url; urlv = g_url_version;
        }
        if (url.empty()) { std::this_thread::sleep_for(std::chrono::milliseconds(500)); continue; }
        std::wstring host, path;
        INTERNET_PORT port = 0;
        bool secure = false;
        if (!CrackUrl(url, host, path, port, secure)) {
            NLOG("edith net: bad relay url '%s'", url.c_str());
            std::this_thread::sleep_for(std::chrono::seconds(5));
            continue;
        }
        HINTERNET s = WinHttpOpen(L"EdithSatellite/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME,
                                  WINHTTP_NO_PROXY_BYPASS, 0);
        HINTERNET c = s ? WinHttpConnect(s, host.c_str(), port, 0) : nullptr;
        HINTERNET r = c ? WinHttpOpenRequest(c, L"GET", path.c_str(), nullptr, WINHTTP_NO_REFERER,
                                             WINHTTP_DEFAULT_ACCEPT_TYPES, secure ? WINHTTP_FLAG_SECURE : 0) : nullptr;
        HINTERNET ws = nullptr;
        if (r && WinHttpSetOption(r, WINHTTP_OPTION_UPGRADE_TO_WEB_SOCKET, nullptr, 0) &&
            WinHttpSendRequest(r, WINHTTP_NO_ADDITIONAL_HEADERS, 0, WINHTTP_NO_REQUEST_DATA, 0, 0, 0) &&
            WinHttpReceiveResponse(r, nullptr))
            ws = WinHttpWebSocketCompleteUpgrade(r, 0);
        DWORD le = GetLastError();
        if (r) WinHttpCloseHandle(r);
        if (!ws) {
            NLOG("edith net: could not connect to %s (error %lu), retrying in %d s", url.c_str(), le, backoff / 1000);
            if (c) WinHttpCloseHandle(c);
            if (s) WinHttpCloseHandle(s);
            std::this_thread::sleep_for(std::chrono::milliseconds(backoff));
            backoff = backoff * 2 > 30000 ? 30000 : backoff * 2;
            continue;
        }
        NLOG("edith net: connected to %s", url.c_str());
        backoff = 1000;
        {
            std::lock_guard<std::mutex> lk(g_mx);
            g_out.clear();                                       // stale while we were away
            g_room = EdithRoom();
            g_room.connected = true;
        }
        std::atomic<int> alive(1);
        std::thread rx(Receive, ws, &alive);
        int sent_hello = -1;
        while (alive) {
            std::string hello;
            std::deque<EdithMsg> out;
            {
                std::lock_guard<std::mutex> lk(g_mx);
                if (g_url_version != urlv) { alive = 0; break; }
                if (g_hello_version != sent_hello && !g_hello.empty()) { hello = g_hello; sent_hello = g_hello_version; }
                out.swap(g_out);
            }
            bool ok = true;
            if (!hello.empty()) {
                ok = WinHttpWebSocketSend(ws, WINHTTP_WEB_SOCKET_UTF8_MESSAGE_BUFFER_TYPE, (PVOID)hello.data(),
                                          (DWORD)hello.size()) == ERROR_SUCCESS;
                if (ok) NLOG("edith net: hello %s", hello.c_str());
            }
            for (auto &m : out) {
                if (!ok) break;
                ok = WinHttpWebSocketSend(ws, m.binary ? WINHTTP_WEB_SOCKET_BINARY_MESSAGE_BUFFER_TYPE : WINHTTP_WEB_SOCKET_UTF8_MESSAGE_BUFFER_TYPE,
                                          (PVOID)m.data.data(), (DWORD)m.data.size()) == ERROR_SUCCESS;
            }
            if (!ok) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        alive = 0;
        WinHttpWebSocketClose(ws, WINHTTP_WEB_SOCKET_SUCCESS_CLOSE_STATUS, nullptr, 0);
        WinHttpCloseHandle(ws);                                  // unblocks the receiver
        rx.join();
        if (c) WinHttpCloseHandle(c);
        if (s) WinHttpCloseHandle(s);
        {
            std::lock_guard<std::mutex> lk(g_mx);
            g_room = EdithRoom();
        }
        NLOG("edith net: disconnected");
        std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    }
}

void EdithNet_Start(void (*log)(const char *fmt, ...)) {
    g_log = log;
    std::thread(Main).detach();
}

void EdithNet_Configure(const std::string &url) {
    std::lock_guard<std::mutex> lk(g_mx);
    if (url != g_url) { g_url = url; ++g_url_version; }
}

void EdithNet_SetHello(const std::string &me, const std::vector<std::string> &others, bool ai, const char *build) {
    std::string h = "{\"v\":1,\"t\":\"hello\",\"name\":\"" + Esc(me) + "\",\"roster\":[";
    for (size_t i = 0; i < others.size(); ++i) h += (i ? ",\"" : "\"") + Esc(others[i]) + "\"";
    h += std::string("],\"ai\":") + (ai ? "true" : "false") + ",\"build\":\"" + Esc(build ? build : "") + "\"}";
    std::lock_guard<std::mutex> lk(g_mx);
    if (h != g_hello) { g_hello = h; ++g_hello_version; }
}

static void Queue(bool binary, std::string data) {
    std::lock_guard<std::mutex> lk(g_mx);
    if (!g_room.connected) return;
    if (g_out.size() >= OUT_MAX) g_out.pop_front();
    g_out.push_back({ binary, std::move(data) });
}

void EdithNet_SendText(const std::string &json) { Queue(false, json); }
void EdithNet_SendBinary(const void *data, size_t size) { Queue(true, std::string((const char *)data, size)); }

std::vector<EdithMsg> EdithNet_Take() {
    std::lock_guard<std::mutex> lk(g_mx);
    std::vector<EdithMsg> v(g_in.begin(), g_in.end());
    g_in.clear();
    return v;
}

EdithRoom EdithNet_Room() {
    std::lock_guard<std::mutex> lk(g_mx);
    return g_room;
}
