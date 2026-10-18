// E.D.I.T.H's ears and mouth inside the DLL (docs/brainplan.md "Built-in ears"): what
// ai/edith_ears.py does, without Python, so every player's game can host her and talk with her.
//   brain link: one WebSocket to the brain (Railway/SparkAPI edith_brain.py, /edith/brain)
//   up:   every event line the DLL makes ({"t":"dll"}), your mic's speech and the room's voice chat
//         (EDA1 utterances, int16 mono 16 kHz)
//   down: replies (face, orders, her line) -> the DLL; her line from the voice pack or streamed
//         (EDV1, 24 kHz) into her in-game speaker
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
    void (*voice_keys)(const char *keys);       // her line from the pack: the other games play it too
    bool (*speaker_push)(const int16_t *pcm, size_t n);   // into her speaker (false: no room right now)
    size_t (*speaker_pending)();                // samples still queued in her speaker
};

// Starts the threads. brain_url: wss://.../edith/brain. voice_dir: <plugins>\EdithVoice\ (with the
// trailing slash). mic: "default" (the default recording device) | "communications" | "off".
void Ears_Start(const EarsHost &host, const char *brain_url, const char *voice_dir, const char *mic);

// An event line the DLL made (state, event ... by=, mute, heard, net ...): up to the brain as is.
void Ears_Line(const char *line);

// Another player's voice, as Wwise played it (called on Wwise's audio thread: copies and returns).
void Ears_Voip(const char *name, uint32_t rate, const int16_t *pcm, size_t n);

// Her line is playing (the mic is deaf meanwhile).
bool Ears_Speaking();

// The brain link is up.
bool Ears_Up();
