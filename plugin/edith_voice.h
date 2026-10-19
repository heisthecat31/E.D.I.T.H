// Her voice lines as Wwise banks inside EDITH.dll (tools/make_voice_banks.py -> out/edith_voice.bin,
// embedded as RCDATA 101). A line plays by loading its bank from that memory into the game's
// sound engine (AK::SoundEngine::LoadBank, in memory), posting its event on her speaker's game
// object (which follows her) and unloading the bank once it has played.
#pragma once
#include <windows.h>
#include <stdint.h>

typedef void (*EdithVoiceLog)(const char *fmt, ...);

// Finds the embedded banks. Returns how many lines there are (0: none embedded).
int Voice_Init(HMODULE self, EdithVoiceLog log);

// The line's length in milliseconds, or -1 when no bank has it.
int Voice_Ms(const char *key);

// Plays the line on game object `obj` and waits for it to end (then unloads its bank). false: no
// bank for it, or the sound engine refused it (logged).
bool Voice_Play(const char *key, uint64_t obj);
