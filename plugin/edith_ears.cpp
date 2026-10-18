// E.D.I.T.H's ears and mouth inside the DLL: a port of ai/edith_ears.py (docs/brainplan.md).
// Before this, a player without the Python companion only heard her while someone with it hosted;
// alone, nothing in their game talked to the brain (user, 2026-10-18: "why does he only hear her
// when I'm in the lobby"). Threads:
//   link   WinHTTP WebSocket to the brain (reconnects), a sender and a receiver (as edith_net.cpp)
//   voice  her replies, one at a time: pack file (<plugins>\EdithVoice\<key>.pcm) or streamed render
//   mic    WASAPI shared capture of the default recording device -> 16 kHz mono -> speech by level
//   voip   other players' voice chat (copied on Wwise's thread) -> speech by level, by name
// Speech found by level against a moving noise floor, exactly as the Python companion (30 ms frames,
// 2.5x the floor and over 150, 0.5 s of quiet ends it, 12 s at most, 0.3 s kept from before).
#define WIN32_LEAN_AND_MEAN
#include "edith_ears.h"
#include <windows.h>
#include <winhttp.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <ks.h>
#include <ksmedia.h>
#include <math.h>
#include <stdio.h>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "ole32.lib")

namespace {

EarsHost H;
std::string g_url, g_voice_dir, g_mic = "default";
constexpr const char *BUILD = "ears-dll-1";
constexpr uint32_t RATE = 24000;                    // her voice: int16 mono 24 kHz
constexpr float SPEECH_LEVEL = 2.5f;                // speech = this many times the noise floor
constexpr int SILENCE_MS = 500, MAX_UTTERANCE_S = 12;

#define ELOG(...) do { if (H.log) H.log(__VA_ARGS__); } while (0)

// ---- a small JSON reader (the brain's replies) ------------------------------------------------------
struct J {
    enum T { NUL, BOOL, NUM, STR, ARR, OBJ } t = NUL;
    bool b = false;
    double n = 0;
    std::string s;
    std::vector<J> a;
    std::vector<std::pair<std::string, J>> o;
    const J *get(const char *k) const {
        for (auto &p : o)
            if (p.first == k) return &p.second;
        return nullptr;
    }
    std::string str(const char *k) const { const J *v = get(k); return v && v->t == STR ? v->s : ""; }
};

void Utf8(std::string &out, unsigned v) {
    if (v < 0x80) out += (char)v;
    else if (v < 0x800) { out += (char)(0xc0 | (v >> 6)); out += (char)(0x80 | (v & 0x3f)); }
    else { out += (char)(0xe0 | (v >> 12)); out += (char)(0x80 | ((v >> 6) & 0x3f)); out += (char)(0x80 | (v & 0x3f)); }
}

bool Parse(const char *&p, const char *e, J &v, int depth = 0) {
    while (p < e && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t')) ++p;
    if (p >= e || depth > 32) return false;
    if (*p == '{' || *p == '[') {
        bool obj = *p == '{';
        v.t = obj ? J::OBJ : J::ARR;
        ++p;
        for (;;) {
            while (p < e && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t' || *p == ',')) ++p;
            if (p >= e) return false;
            if (*p == (obj ? '}' : ']')) { ++p; return true; }
            if (obj) {
                J key;
                if (!Parse(p, e, key, depth + 1) || key.t != J::STR) return false;
                while (p < e && (*p == ' ' || *p == ':')) ++p;
                J val;
                if (!Parse(p, e, val, depth + 1)) return false;
                v.o.emplace_back(key.s, std::move(val));
            } else {
                J val;
                if (!Parse(p, e, val, depth + 1)) return false;
                v.a.push_back(std::move(val));
            }
        }
    }
    if (*p == '"') {
        v.t = J::STR;
        for (++p; p < e && *p != '"'; ++p) {
            if (*p != '\\') { v.s += *p; continue; }
            if (++p >= e) return false;
            switch (*p) {
            case 'n': v.s += '\n'; break;
            case 't': v.s += '\t'; break;
            case 'r': break;
            case 'u':
                if (p + 4 < e) { Utf8(v.s, strtoul(std::string(p + 1, 4).c_str(), nullptr, 16)); p += 4; }
                break;
            default: v.s += *p;
            }
        }
        if (p >= e) return false;
        ++p;
        return true;
    }
    if (!strncmp(p, "true", 4)) { v.t = J::BOOL; v.b = true; p += 4; return true; }
    if (!strncmp(p, "false", 5)) { v.t = J::BOOL; p += 5; return true; }
    if (!strncmp(p, "null", 4)) { p += 4; return true; }
    char *end = nullptr;
    v.n = strtod(p, &end);
    if (end == p) return false;
    v.t = J::NUM;
    p = end;
    return true;
}

std::string Esc(const std::string &s) {
    std::string o;
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += (char)c; }
        else if (c < 0x20) { char b[8]; sprintf_s(b, "\\u%04x", c); o += b; }
        else o += (char)c;
    }
    return o;
}

// ---- the brain link ----------------------------------------------------------------------------------
struct Msg { bool binary; std::string data; };
std::mutex g_mx;
std::deque<Msg> g_out;
std::atomic<bool> g_up{ false };
constexpr size_t OUT_MAX = 256;

// renders streamed from the brain: id -> PCM pieces as they arrive (an empty piece = done)
std::mutex g_rmx;
std::condition_variable g_rcv;
std::map<uint32_t, std::deque<std::string>> g_renders;
uint32_t g_next_render = 1;

void Send(bool binary, std::string data) {
    if (!g_up) return;
    std::lock_guard<std::mutex> lk(g_mx);
    if (g_out.size() >= OUT_MAX) g_out.pop_front();
    g_out.push_back({ binary, std::move(data) });
}
void SendJson(const std::string &json) { Send(false, json); }

std::mutex g_vmx;
std::condition_variable g_vcv;
std::deque<J> g_replies;                            // her lines to play
std::atomic<bool> g_speaking{ false };

void Reply(const J &m) {
    // face and orders first (as edith_ears.py apply()), then her line
    const J *f = m.get("face");
    if (f && f->t == J::ARR && f->a.size() == 2 && f->a[0].t == J::STR) {
        char b[96];
        snprintf(b, sizeof b, "face %s %g", f->a[0].s.c_str(), f->a[1].t == J::NUM ? f->a[1].n : 0.0);
        H.order(b);
    }
    const J *o = m.get("orders");
    if (o && o->t == J::ARR) {
        std::string all;
        for (auto &x : o->a)
            if (x.t == J::STR) { H.order(x.s.c_str()); all += (all.empty() ? "" : ", ") + x.s; }
        if (!all.empty()) ELOG("ears: orders %s", all.c_str());
    }
    if (!m.str("say").empty()) {
        std::lock_guard<std::mutex> lk(g_vmx);
        if (g_replies.size() < 8) g_replies.push_back(m);
        g_vcv.notify_one();
    }
}

void Got(bool binary, const std::string &msg) {
    if (binary) {
        if (msg.size() >= 8 && !memcmp(msg.data(), "EDV1", 4)) {
            uint32_t id;
            memcpy(&id, msg.data() + 4, 4);
            std::lock_guard<std::mutex> lk(g_rmx);
            auto it = g_renders.find(id);
            if (it != g_renders.end() && msg.size() > 8) it->second.push_back(msg.substr(8));
            g_rcv.notify_all();
        }
        return;
    }
    J m;
    const char *p = msg.data();
    if (!Parse(p, msg.data() + msg.size(), m) || m.t != J::OBJ) return;
    std::string t = m.str("t");
    if (t == "reply") Reply(m);
    else if (t == "rendered") {
        const J *id = m.get("id");
        std::lock_guard<std::mutex> lk(g_rmx);
        auto it = g_renders.find(id && id->t == J::NUM ? (uint32_t)id->n : 0);
        if (it != g_renders.end()) it->second.push_back(std::string());   // (done)
        g_rcv.notify_all();
    } else if (t == "hi") {
        const J *stt = m.get("stt"), *tts = m.get("tts");
        ELOG("ears: brain connected; voice %s / %s, whisper %s, server voice %s", m.str("voice").c_str(),
             m.str("fallback").c_str(), stt && stt->b ? "on" : "OFF", tts && tts->b ? "on" : "OFF");
    } else if (t == "log") ELOG("ears: brain: %s", m.str("text").c_str());
}

bool CrackUrl(const std::string &url, std::wstring &host, std::wstring &path, INTERNET_PORT &port, bool &secure) {
    std::wstring w(url.begin(), url.end());
    if (w.compare(0, 6, L"wss://") == 0) w = L"https://" + w.substr(6);
    else if (w.compare(0, 5, L"ws://") == 0) w = L"http://" + w.substr(5);
    URL_COMPONENTS uc = {};
    uc.dwStructSize = sizeof uc;
    wchar_t h[256] = {}, pth[1024] = {};
    uc.lpszHostName = h; uc.dwHostNameLength = 255;
    uc.lpszUrlPath = pth; uc.dwUrlPathLength = 1023;
    if (!WinHttpCrackUrl(w.c_str(), 0, 0, &uc)) return false;
    host = h;
    path = pth[0] ? pth : L"/";
    port = uc.nPort;
    secure = uc.nScheme == INTERNET_SCHEME_HTTPS;
    return !host.empty();
}

void Receive(HINTERNET ws, std::atomic<int> *alive) {
    std::vector<uint8_t> buf(65536);
    std::string msg;
    while (*alive) {
        DWORD got = 0;
        WINHTTP_WEB_SOCKET_BUFFER_TYPE type;
        if (WinHttpWebSocketReceive(ws, buf.data(), (DWORD)buf.size(), &got, &type) != ERROR_SUCCESS) break;
        if (type == WINHTTP_WEB_SOCKET_CLOSE_BUFFER_TYPE) break;
        msg.append((const char *)buf.data(), got);
        if (type == WINHTTP_WEB_SOCKET_BINARY_FRAGMENT_BUFFER_TYPE || type == WINHTTP_WEB_SOCKET_UTF8_FRAGMENT_BUFFER_TYPE) {
            if (msg.size() > (4u << 20)) msg.clear();
            continue;
        }
        Got(type == WINHTTP_WEB_SOCKET_BINARY_MESSAGE_BUFFER_TYPE, msg);
        msg.clear();
    }
    *alive = 0;
}

int TzMinutes() {
    TIME_ZONE_INFORMATION tz;
    DWORD r = GetTimeZoneInformation(&tz);
    long bias = tz.Bias + (r == TIME_ZONE_ID_DAYLIGHT ? tz.DaylightBias : r == TIME_ZONE_ID_STANDARD ? tz.StandardBias : 0);
    return (int)-bias;
}

void Link() {
    int backoff = 1000;
    bool said = false;
    for (;;) {
        std::wstring host, path;
        INTERNET_PORT port = 0;
        bool secure = false;
        if (!CrackUrl(g_url, host, path, port, secure)) { ELOG("ears: bad brain url '%s'", g_url.c_str()); return; }
        HINTERNET s = WinHttpOpen(L"EDITH/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
        HINTERNET c = s ? WinHttpConnect(s, host.c_str(), port, 0) : nullptr;
        HINTERNET r = c ? WinHttpOpenRequest(c, L"GET", path.c_str(), nullptr, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
                                             secure ? WINHTTP_FLAG_SECURE : 0) : nullptr;
        HINTERNET ws = nullptr;
        if (r && WinHttpSetOption(r, WINHTTP_OPTION_UPGRADE_TO_WEB_SOCKET, nullptr, 0) &&
            WinHttpSendRequest(r, WINHTTP_NO_ADDITIONAL_HEADERS, 0, WINHTTP_NO_REQUEST_DATA, 0, 0, 0) &&
            WinHttpReceiveResponse(r, nullptr))
            ws = WinHttpWebSocketCompleteUpgrade(r, 0);
        DWORD le = GetLastError();
        if (r) WinHttpCloseHandle(r);
        if (!ws) {
            if (!said) ELOG("ears: can't reach the brain at %s (error %lu); retrying", g_url.c_str(), le);
            said = true;
            if (c) WinHttpCloseHandle(c);
            if (s) WinHttpCloseHandle(s);
            std::this_thread::sleep_for(std::chrono::milliseconds(backoff));
            backoff = backoff * 2 > 30000 ? 30000 : backoff * 2;
            continue;
        }
        said = false;
        backoff = 1000;
        char hello[256];
        snprintf(hello, sizeof hello, "{\"t\":\"hello\",\"v\":1,\"name\":\"%s\",\"tz\":%d,\"build\":\"%s\"}",
                 Esc(H.me ? H.me() : "").c_str(), TzMinutes(), BUILD);
        bool ok = WinHttpWebSocketSend(ws, WINHTTP_WEB_SOCKET_UTF8_MESSAGE_BUFFER_TYPE, hello, (DWORD)strlen(hello)) == ERROR_SUCCESS;
        { std::lock_guard<std::mutex> lk(g_mx); g_out.clear(); }   // (nothing stale from before)
        g_up = ok;
        std::atomic<int> alive(ok ? 1 : 0);
        std::thread rx(Receive, ws, &alive);
        while (alive) {
            std::deque<Msg> out;
            { std::lock_guard<std::mutex> lk(g_mx); out.swap(g_out); }
            for (auto &m : out) {
                if (WinHttpWebSocketSend(ws, m.binary ? WINHTTP_WEB_SOCKET_BINARY_MESSAGE_BUFFER_TYPE : WINHTTP_WEB_SOCKET_UTF8_MESSAGE_BUFFER_TYPE,
                                         (PVOID)m.data.data(), (DWORD)m.data.size()) != ERROR_SUCCESS) { alive = 0; break; }
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        g_up = false;
        WinHttpWebSocketClose(ws, WINHTTP_WEB_SOCKET_SUCCESS_CLOSE_STATUS, nullptr, 0);
        WinHttpCloseHandle(ws);
        rx.join();
        if (c) WinHttpCloseHandle(c);
        if (s) WinHttpCloseHandle(s);
        {                                                       // renders in flight end here
            std::lock_guard<std::mutex> lk(g_rmx);
            for (auto &x : g_renders) x.second.push_back(std::string());
            g_rcv.notify_all();
        }
        ELOG("ears: brain link lost; reconnecting");
        std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    }
}

// ---- her voice -----------------------------------------------------------------------------------------
bool FileOf(const std::string &key, std::string &path, long long &bytes) {
    if (key.size() != 20 || g_voice_dir.empty()) return false;
    for (char ch : key)
        if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'))) return false;
    path = g_voice_dir + key + ".pcm";
    WIN32_FILE_ATTRIBUTE_DATA a;
    if (!GetFileAttributesExA(path.c_str(), GetFileExInfoStandard, &a)) return false;
    bytes = ((long long)a.nFileSizeHigh << 32) | a.nFileSizeLow;
    return true;
}

int Words(const std::string &t) {
    int n = 0;
    bool in = false;
    for (char ch : t) { bool w = ch != ' '; if (w && !in) ++n; in = w; }
    return n ? n : 1;
}

// Her own voice's render of `text`, unless it's a broken F5 blip (as edith_ears.py Voice.broken: under
// half the fallback voice's length, or under 0.12 s a word).
bool Mine(const std::string &text, const std::string &key, const std::string &alt, std::string &path) {
    long long b = 0, rb = 0;
    if (!FileOf(key, path, b)) return false;
    double secs = b / 2.0 / RATE;
    std::string rp;
    if (FileOf(alt, rp, rb) && secs < 0.5 * rb / 2.0 / RATE) return false;
    return secs >= 0.12 * Words(text);
}

struct Item { bool file; std::string path_or_text, key; };

// What to play (edith_ears.py Voice.plan): her whole line, all its sentences in her voice, the fallback
// voice's whole line, the sentences mixed (pack where it has them), or the whole line streamed.
std::vector<Item> Plan(const J &m) {
    std::string say = m.str("say"), key = m.str("key"), alt = m.str("alt"), path;
    long long b;
    std::vector<Item> out;
    if (Mine(say, key, alt, path)) return { { true, path, key } };
    std::vector<std::vector<std::string>> parts;
    const J *ps = m.get("parts");
    if (ps && ps->t == J::ARR)
        for (auto &p : ps->a)
            if (p.t == J::ARR && p.a.size() >= 3)
                parts.push_back({ p.a[0].s, p.a[1].s, p.a[2].s });
    bool all = !parts.empty();
    for (auto &p : parts) all = all && Mine(p[0], p[1], p[2], path);
    if (all) {
        for (auto &p : parts) { Mine(p[0], p[1], p[2], path); out.push_back({ true, path, p[1] }); }
        return out;
    }
    if (FileOf(alt, path, b)) return { { true, path, alt } };
    bool any = false;
    for (auto &p : parts) {
        if (Mine(p[0], p[1], p[2], path)) { out.push_back({ true, path, p[1] }); any = true; }
        else if (FileOf(p[2], path, b)) { out.push_back({ true, path, p[2] }); any = true; }
        else out.push_back({ false, p[0], "" });
    }
    if (any) return out;
    return { { false, say, "" } };                                  // none of it in the pack: one stream
}

// Her speaker takes the PCM (waits for room in its ring; gives up after a few seconds without her).
bool Push(const char *data, size_t bytes) {
    const int16_t *pcm = (const int16_t *)data;
    size_t n = bytes / 2, done = 0;
    int stuck = 0;
    while (done < n) {
        size_t step = n - done < 4800 ? n - done : 4800;          // 0.2 s at a time
        if (H.speaker_push(pcm + done, step)) { done += step; stuck = 0; continue; }
        if (++stuck > 300) return false;                       // 6 s: her speaker isn't playing
        Sleep(20);
    }
    return true;
}

void VoiceThread() {
    for (;;) {
        J m;
        {
            std::unique_lock<std::mutex> lk(g_vmx);
            g_vcv.wait(lk, [] { return !g_replies.empty(); });
            m = g_replies.front();
            g_replies.pop_front();
        }
        std::vector<Item> items = Plan(m);
        std::string how, keys;
        for (auto &it : items) {
            how += how.empty() ? "" : ", ";
            how += it.file ? "pack " + it.key : std::string("stream");
            if (it.file) keys += (keys.empty() ? "" : " ") + it.key;
        }
        ELOG("ears: '%s' <- %s", m.str("say").c_str(), how.c_str());
        g_speaking = true;
        SendJson("{\"t\":\"speaking\",\"on\":true}");
        if (!keys.empty()) H.voice_keys(keys.c_str());          // the other games play the same pack files
        bool ok = true;
        for (auto &it : items) {
            if (!ok) break;
            if (it.file) {
                FILE *f = nullptr;
                if (fopen_s(&f, it.path_or_text.c_str(), "rb") || !f) continue;
                std::vector<char> pcm;
                char buf[65536];
                size_t n;
                while ((n = fread(buf, 1, sizeof buf, f)) > 0) pcm.insert(pcm.end(), buf, buf + n);
                fclose(f);
                ok = Push(pcm.data(), pcm.size());
                continue;
            }
            uint32_t id;                                       // a line the pack lacks: the brain renders it
            {
                std::lock_guard<std::mutex> lk(g_rmx);
                id = g_next_render++;
                g_renders[id];
            }
            if (!g_up) { ELOG("ears: can't voice '%s' (no pack line, no brain)", it.path_or_text.c_str()); continue; }
            SendJson("{\"t\":\"render\",\"id\":" + std::to_string(id) + ",\"text\":\"" + Esc(it.path_or_text) + "\"}");
            ELOG("ears: streaming '%s' (not in the pack)", it.path_or_text.c_str());
            for (;;) {
                std::string piece;
                {
                    std::unique_lock<std::mutex> lk(g_rmx);
                    if (!g_rcv.wait_for(lk, std::chrono::seconds(15), [id] { return !g_renders[id].empty(); })) break;
                    piece = g_renders[id].front();
                    g_renders[id].pop_front();
                }
                if (piece.empty()) break;
                if (!(ok = Push(piece.data(), piece.size()))) break;
            }
            std::lock_guard<std::mutex> lk(g_rmx);
            g_renders.erase(id);
        }
        if (!ok) ELOG("ears: her speaker isn't playing: line dropped");
        for (int k = 0; k < 600 && H.speaker_pending() > 0; ++k) Sleep(20);   // let it play out (12 s at most)
        Sleep(400);                                            // her tail in the room
        g_speaking = false;
        SendJson("{\"t\":\"speaking\",\"on\":false}");
    }
}

// ---- speech found by level (the mic, and each voice on voice chat) ----------------------------------------
struct Vad {
    float noise = 200.0f;
    bool speech = false;
    int quiet = 0;
    std::vector<int16_t> buf;
    std::deque<std::vector<int16_t>> pre;                      // 0.3 s before speech starts
    std::vector<int16_t> rest;                                 // a frame's start, waiting for the rest
    ULONGLONG last = 0;
};

void Upload(const std::string &who, const std::vector<int16_t> &pcm) {
    std::string name = who.substr(0, 48);
    std::string m = "EDA1";
    m += (char)name.size();
    m += name;
    m.append((const char *)pcm.data(), pcm.size() * 2);
    Send(true, std::move(m));
}

// 16 kHz samples in; whole utterances out to the brain as `who` ("" = this PC's mic).
void Feed(Vad &v, const std::string &who, const int16_t *x, size_t n) {
    v.rest.insert(v.rest.end(), x, x + n);
    size_t k = 0;
    for (; k + 480 <= v.rest.size(); k += 480) {
        const int16_t *f = v.rest.data() + k;
        double e = 0;
        for (int i = 0; i < 480; ++i) e += (double)f[i] * f[i];
        float lvl = (float)sqrt(e / 480) + 1e-3f;
        if (!v.speech) {
            v.noise = 0.97f * v.noise + 0.03f * lvl;
            if (lvl > v.noise * SPEECH_LEVEL && lvl > 150) {
                v.speech = true;
                v.quiet = 0;
                v.buf.clear();
                for (auto &p : v.pre) v.buf.insert(v.buf.end(), p.begin(), p.end());
                v.buf.insert(v.buf.end(), f, f + 480);
            } else {
                v.pre.emplace_back(f, f + 480);
                if (v.pre.size() > 10) v.pre.pop_front();
            }
        } else {
            v.buf.insert(v.buf.end(), f, f + 480);
            v.quiet = lvl < v.noise * SPEECH_LEVEL * 0.6f ? v.quiet + 1 : 0;
            if (v.quiet * 30 > SILENCE_MS || v.buf.size() / 480 * 0.03 > MAX_UTTERANCE_S) {
                v.speech = false;
                if (v.buf.size() > 480 * 10) {                 // > 0.3 s
                    Upload(who, v.buf);
                    ELOG("ears: %s %.1f s sent", who.empty() ? "mic" : who.c_str(), v.buf.size() / 16000.0);
                }
                v.buf.clear();
                v.pre.clear();
            }
        }
    }
    v.rest.erase(v.rest.begin(), v.rest.begin() + k);
}

void Reset(Vad &v) { v.speech = false; v.buf.clear(); v.pre.clear(); v.rest.clear(); }

// ---- the mic: WASAPI shared capture -> 16 kHz mono ---------------------------------------------------------
void MicThread() {
    if (g_mic == "off") { ELOG("ears: mic off (EDITH.ini mic=off)"); return; }
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    Vad v;
    bool was_muted = false, said_open = false;
    for (;;) {
        IMMDeviceEnumerator *en = nullptr;
        IMMDevice *dev = nullptr;
        IAudioClient *ac = nullptr;
        IAudioCaptureClient *cap = nullptr;
        WAVEFORMATEX *wf = nullptr;
        HRESULT hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, __uuidof(IMMDeviceEnumerator), (void **)&en);
        if (SUCCEEDED(hr)) hr = en->GetDefaultAudioEndpoint(eCapture, g_mic == "communications" ? eCommunications : eConsole, &dev);
        if (SUCCEEDED(hr)) hr = dev->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void **)&ac);
        if (SUCCEEDED(hr)) hr = ac->GetMixFormat(&wf);
        if (SUCCEEDED(hr)) hr = ac->Initialize(AUDCLNT_SHAREMODE_SHARED, 0, 2000000, 0, wf, nullptr);   // 200 ms
        if (SUCCEEDED(hr)) hr = ac->GetService(__uuidof(IAudioCaptureClient), (void **)&cap);
        if (SUCCEEDED(hr)) hr = ac->Start();
        bool flt = false;
        if (SUCCEEDED(hr)) {
            flt = wf->wFormatTag == WAVE_FORMAT_IEEE_FLOAT ||
                  (wf->wFormatTag == WAVE_FORMAT_EXTENSIBLE && ((WAVEFORMATEXTENSIBLE *)wf)->SubFormat == KSDATAFORMAT_SUBTYPE_IEEE_FLOAT);
            if (!(flt && wf->wBitsPerSample == 32) && !(!flt && wf->wBitsPerSample == 16)) hr = E_FAIL;
        }
        if (FAILED(hr)) {
            if (!said_open) ELOG("ears: can't open the mic (%08lx); retrying", (unsigned long)hr);
            said_open = true;
        } else {
            said_open = false;
            ELOG("ears: mic open (%lu Hz, %u ch, %s)", wf->nSamplesPerSec, wf->nChannels, flt ? "float" : "int16");
            const int ch = wf->nChannels;
            const double step = wf->nSamplesPerSec / 16000.0;  // input samples per output sample
            double acc = 0, pos = 0;
            int cnt = 0;
            std::vector<int16_t> out;
            for (;;) {
                Sleep(10);
                UINT32 pk = 0;
                if (FAILED(cap->GetNextPacketSize(&pk))) break;  // (the device went away: reopen)
                bool lost = false;
                while (pk) {
                    BYTE *data;
                    UINT32 frames;
                    DWORD flags;
                    if (FAILED(cap->GetBuffer(&data, &frames, &flags, nullptr, nullptr))) { lost = true; break; }
                    out.clear();
                    for (UINT32 i = 0; i < frames; ++i) {     // mono, then a box filter down to 16 kHz
                        float s = 0;
                        if (!(flags & AUDCLNT_BUFFERFLAGS_SILENT))
                            for (int c = 0; c < ch; ++c)
                                s += flt ? ((float *)data)[i * ch + c] * 32767.0f : (float)((int16_t *)data)[i * ch + c];
                        acc += s / ch;
                        ++cnt;
                        pos += 1.0;
                        if (pos >= step) {
                            pos -= step;
                            double y = acc / cnt;
                            out.push_back((int16_t)(y > 32767 ? 32767 : y < -32767 ? -32767 : y));
                            acc = 0;
                            cnt = 0;
                        }
                    }
                    cap->ReleaseBuffer(frames);
                    bool muted = H.muted();
                    if (muted != was_muted) { ELOG(muted ? "ears: muted on voice chat: mic not sent" : "ears: mic on"); was_muted = muted; }
                    if (g_speaking || muted || !H.in_lobby() || !g_up) Reset(v);
                    else Feed(v, "", out.data(), out.size());
                    if (FAILED(cap->GetNextPacketSize(&pk))) { lost = true; break; }
                }
                if (lost) break;
            }
            ELOG("ears: mic lost; reopening");
            ac->Stop();
        }
        if (cap) cap->Release();
        if (wf) CoTaskMemFree(wf);
        if (ac) ac->Release();
        if (dev) dev->Release();
        if (en) en->Release();
        Reset(v);
        Sleep(2000);
    }
}

// ---- voice chat: copies from Wwise's audio thread, cut into speech here ------------------------------------
struct VoipChunk { std::string name; uint32_t rate; std::vector<int16_t> pcm; };
std::mutex g_pmx;
std::condition_variable g_pcv;
std::deque<VoipChunk> g_pq;

void VoipThread() {
    std::map<std::string, Vad> st;
    for (;;) {
        std::deque<VoipChunk> got;
        {
            std::unique_lock<std::mutex> lk(g_pmx);
            g_pcv.wait_for(lk, std::chrono::milliseconds(100), [] { return !g_pq.empty(); });
            got.swap(g_pq);
        }
        ULONGLONG now = GetTickCount64();
        for (auto &c : got) {
            Vad &v = st[c.name];
            v.last = now;
            if (H.puppet() || H.has_ears(c.name.c_str()) || !H.in_lobby() || !g_up) { Reset(v); continue; }
            std::vector<int16_t> y;                            // down to 16 kHz (48 kHz: every 3 averaged)
            double step = c.rate / 16000.0, pos = 0, acc = 0;
            int cnt = 0;
            for (int16_t s : c.pcm) {
                acc += s; ++cnt; pos += 1.0;
                if (pos >= step) { pos -= step; y.push_back((int16_t)(acc / cnt)); acc = 0; cnt = 0; }
            }
            Feed(v, c.name, y.data(), y.size());
        }
        for (auto &x : st)                                     // a voice that stopped sending: its speech ends
            if (x.second.speech && now - x.second.last > (ULONGLONG)SILENCE_MS) {
                if (x.second.buf.size() > 480 * 10) { Upload(x.first, x.second.buf); ELOG("ears: %s %.1f s sent", x.first.c_str(), x.second.buf.size() / 16000.0); }
                Reset(x.second);
            }
    }
}

}  // namespace

void Ears_Start(const EarsHost &host, const char *brain_url, const char *voice_dir, const char *mic) {
    H = host;
    g_url = brain_url ? brain_url : "";
    g_voice_dir = voice_dir ? voice_dir : "";
    if (mic && *mic) g_mic = mic;
    ELOG("ears: built in (brain %s, voice pack %s, mic %s)", g_url.c_str(), g_voice_dir.c_str(), g_mic.c_str());
    std::thread(Link).detach();
    std::thread(VoiceThread).detach();
    std::thread(MicThread).detach();
    std::thread(VoipThread).detach();
}

void Ears_Line(const char *line) {
    if (!g_up || !line || !*line) return;
    SendJson("{\"t\":\"dll\",\"line\":\"" + Esc(line) + "\"}");
}

void Ears_Voip(const char *name, uint32_t rate, const int16_t *pcm, size_t n) {
    if (!g_up || !name || !*name || !rate || !n) return;
    std::lock_guard<std::mutex> lk(g_pmx);
    if (g_pq.size() > 400) return;                             // (falling behind: drop, never block Wwise)
    g_pq.push_back({ name, rate, std::vector<int16_t>(pcm, pcm + n) });
    g_pcv.notify_one();
}

bool Ears_Speaking() { return g_speaking; }
bool Ears_Up() { return g_up; }
