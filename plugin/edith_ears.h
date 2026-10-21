// E.D.I.T.H's ears and mouth inside the DLL (docs/brainplan.md "Built-in ears"): what
// ai/edith_ears.py does, without Python, so every player's game can host her and talk with her.
//   brain link: one WebSocket to the brain (E.D.I.T.H-AI edith_brain.py, edith.echovr.de/edith/brain)
//   up:   every event line the DLL makes ({"t":"dll"}), your mic's speech and the room's voice chat
//         (EDA1 utterances, int16 mono 16 kHz)
//   down: replies (face, orders, her line) -> the DLL; her line from the voice pack or streamed
//         (EDV1, 24 kHz) into her in-game speaker; lines in her banks play from EDITH.dll
#pragma once
#include <stddef.h>
#include <stdint.h>

struct EarsHost {
    void (*log)(const char *fmt, ...);
    bool (*in_lobby)();                         // she is loaded here (her state is fresh)
    bool (*muted)();                            // you are muted on Echo's voice chat
    bool (*puppet)();                           // another game hosts her (voice chat is theirs to hear)
    bool (*has_ears)(const char *name);         // that player's own game hears them (the room's ai list)
    const char *(*me)();                        // your display name ("" until known)
    void (*order)(const char *order);           // a reply's order / face, into the DLL
    // her line, for the other games: the pack keys it played (older games play those) and the whole
    // line as JSON {"say","key","alt","parts"} (games with built-in ears play it themselves: pack or
    // streamed, so a line the pack lacks reaches them too)
    void (*voice_line)(const char *keys, const char *line_json);
    bool (*speaker_push)(const int16_t *pcm, size_t n);   // into her speaker (false: no room right now)
    size_t (*speaker_pending)();                // samples still queued in her speaker
    int (*bank_ms)(const char *key);            // her bank line's length in ms, -1: no bank has it
    bool (*bank_play)(const char *key);         // plays her bank line at her, waits for its end
    // someone talked over her (barge-in): cut her short
    void (*speaker_flush)();                    // drops what's queued in her speaker
    void (*bank_stop)();                        // fades out the bank line playing now (bank_play returns)
    void (*hush)(const char *by);               // the other games stop her too (the relay)
};

// Starts the threads. brain_url: wss://.../edith/brain. mic: "default" (the default recording device)
// | "communications" | "off".
void Ears_Start(const EarsHost &host, const char *brain_url, const char *mic);

// An event line the DLL made (state, event ... by=, mute, heard, net ...): up to the brain as is.
void Ears_Line(const char *line);

// Another player's voice, as Wwise played it (called on Wwise's audio thread: copies and returns).
void Ears_Voip(const char *name, uint32_t rate, const int16_t *pcm, size_t n);

// The host's line on another game: played here like her own reply (pack, else streamed from the brain).
void Ears_PlayLine(const char *line_json);

// Her line is playing.
bool Ears_Speaking();

// Someone talked over her on another game (the relay's hush): she stops here too.
void Ears_Hush(const char *by);

// The brain link is up.
bool Ears_Up();
