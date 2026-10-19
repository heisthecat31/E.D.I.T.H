# Edith's brain on the server

**Goal (user, 2026-10-18):** Edith's intelligence, memory and choice of lines live in SparkAPI on
Railway, so she can be changed live without touching anyone's PC. The user's decisions:

- **Brain:** SparkAPI, next to `edith_relay.py` (`Railway/SparkAPI/edith_brain.py`, route `/edith/brain`).
- **Speech to text:** Whisper on the server (faster-whisper `base.en`, int8, CPU).
- **Voice:** a voice pack shipped with the mod (`plugins\EdithVoice\<key>.pcm`). A line the pack
  lacks is rendered on the server (Kokoro `af_heart`, 24 kHz mono) and streamed.

Her rules and voice rules are unchanged: no emoji, never the word "coming", never says names.

## Shape

```
  player's PC                                             SparkAPI (Railway)
 ┌───────────────────────────────┐   wss /edith/brain   ┌────────────────────────────────────┐
 │ Satellite.dll                 │                      │ edith_brain.py                     │
 │  events :47322 ──────────┐    │   dll lines (text)   │  Whisper base.en (int8, CPU)       │
 │  orders :47321 ◄──────┐  │    │ ───────────────────► │  wake word + follow-up window      │
 │  speaker :47323 ◄──┐  │  │    │   EDA1 utterances    │  handle(): orders, refusals,       │
 │  voice chat :47324 │  │  │    │ ───────────────────► │   points, favourite, teaching,     │
 │                    │  │  ▼    │                      │   memory, small talk, knowledge,   │
 │ ai/edith_ears.py   │  │       │   reply (text)       │   chat bank                        │
 │  mic + VAD, mute   │  └─────  │ ◄─────────────────── │  library: edith_library/*.json,    │
 │  pack lookup ──────┘          │   EDV1 PCM (stream)  │   reloaded on change               │
 │  plugins\EdithVoice\*.pcm     │ ◄─────────────────── │  Kokoro af_heart (lines not in     │
 └───────────────────────────────┘                      │   the pack)                        │
                                                        │  records per player name:          │
                                                        │   Postgres edith_players / files   │
                                                        └────────────────────────────────────┘
```

- **Companion** (`ai/edith_ears.py`, started by `run_edith_ears.ps1`; `Satellite.ini ai=` points at
  it): mic at 16 kHz, speech found by level against a moving noise floor (as before), uploaded as
  int16. It sends nothing while you're muted on Echo's voice chat (the DLL's `mute 1`), while her
  line is playing, outside her lobby (no state line for 6 s), or with no brain link. Other players'
  voice chat (:47324) is cut into utterances the same way and uploaded by name (not on a puppet, not
  for players whose own companion runs). Every line from the DLL's event port goes up as is. Replies:
  face and orders to :47321, then the line is played.
- **Brain** (`edith_brain.py`): one `Edith` per companion connection, a port of
  `ai/satellite_ai.py` (`listen_events`, the main loop, `handle`, `refusal`, `judge_act`,
  `remark`, `sentiment`, `memory_instant`, `teach_instant`, `move_instant`, places, favourite).
  Whisper runs in a thread (one at a time); the rules run on the event loop.
- **Old companion:** `ai/satellite_ai.py` still works fully offline (`run_satellite_ai.ps1`).

## Built-in ears (EDITH.dll, 2026-10-18)

Players without the Python companion only had her voice and ears while someone with it hosted;
alone, nothing in their game talked to the brain (user: "why does he only hear her when I'm in
lobby"). `plugin/edith_ears.cpp` does what `ai/edith_ears.py` did, inside the DLL:

- **Brain link:** a WinHTTP WebSocket to `brain=` (default Railway), the same messages (`hello`
  with build `ears-dll-1`, `dll` lines, `EDA1` utterances, `speaking`, `render` / `EDV1`).
- **Up:** every `Event()` line; the mic (WASAPI shared, default recording device, `mic=default |
  communications | off`) mixed to mono 16 kHz, speech found by level like the companion. Nothing is
  sent while muted on voice chat, while her line plays, outside her lobby, or with no link. Voice chat
  from the tap goes straight in (host only, members without their own ears).
- **Down:** faces and orders: `heard <text>` goes to the host through the relay at once (a puppet
  never polled its order port, so the old companion's forwarding never arrived); a push / shutdown at
  you goes to :47325; `voice` keys to the room; the rest to :47321. Her line: pack file (with the
  broken-render check) or streamed render, written straight into her speaker's ring.
- **`EDITH.ini ears=`:** `dll` (default), `python` (the old companion through `ai=`), `off`. A
  `-server` never starts them.
- Also fixed the same day: voice chat streams are keyed by the whole delegate {object, context}.
  Echo registered 11 voices on one object at a lobby join, so one playing id's position named
  everyone's voice (gg95 heard as you, Furo almost never).
- **Tested 15:05 offline in VR:** mic open (48 kHz mono float), brain connected; "Edith, hello",
  "follow", "spin" answered from the pack with the orders applied, Whisper about 0.3 s. Not yet:
  two players both with built-in ears, a puppet's speech forwarded to the host.

## Who and what is remembered

- **Records per player name** (`edith_players`, JSONB, when `DATABASE_URL` is set; else
  `$DATA_DIR/edith_brain/players/*.json`): `profile` (nickname, likes, dislikes, favorites, notes),
  `points` (nice, mean, mean_at, streak), and for the player whose game runs her: `events`, `turns`,
  `places`, `learned` (what they taught her), `facts`. Written every 2 s off the event loop.
- **Points** are global per name: someone who bullied her in one lobby is still in the red in the
  next one (mean points fade 1 per 90 s, also while away).
- **Profiles are per player now:** "I like pizza" from FakeBob goes into FakeBob's record, and "what
  do you know about me" answers each player with their own.
- **Teaching and places** stay with the player whose game runs her (as before: places are saved at
  your position, which only your DLL reports).
- Names aren't verified: a companion could claim a name. Her memory is low stakes; the relay's
  stamping is what protects orders between players.
- `tools/import_memory.py --name <you>` moves the old `H:\SatelliteAI\memory.json` into your record
  (admin token from `EDITH_ADMIN_TOKEN`).

## Her library, live

- Deployed copy: `Railway/SparkAPI/edith_library/` (`knowledge`, `smalltalk`, `reactions`, `chat`,
  `sentiment` from `ai/library/`, plus `lines.json` (her fixed lines, were constants in
  `satellite_ai.py`) and `config.json` (name, wake words, follow-up window, points rules, voice
  keys, the "don't know" line).
- Live copy: `$DATA_DIR/edith_brain/library/` (the Railway volume), seeded from the deployed copy.
  A deploy updates a file only if nobody edited it live since the last deploy (a live edit wins and
  is logged).
- The brain checks the files' times at most every 2 s and rebuilds the library on a change. A file
  that fails to parse or build keeps the old library (`/edith/brain/stats` shows `library_error`).
- Over HTTP, with `ADMIN_TOKEN` (header `X-Admin-Token`):
  - `GET /edith/brain/library/<file>`: the file as JSON.
  - `PUT /edith/brain/library/<file>`: replace it. It must build a working library first, else 400
    and nothing changes. She uses it within 2 s.
  - `GET /edith/brain/unknown`: what she couldn't answer (what to add next).
  - `GET|PUT|DELETE /edith/brain/player/<name>`: a player's record.
  - `GET /edith/brain/stats` (open): companions connected, Whisper / Kokoro up, library sizes.
- Lines added live that aren't in the pack are streamed (Kokoro `af_heart`) until the next pack.

## Her voice

- **Key:** `sha1("<voice>|<speed>|<text>")[:20]`, the same as `satellite_ai.py Voice._file`, with
  `voice=hera_f5`, `fallback_voice=af_heart`, `voice_speed=1.1` from `config.json`. Each reply
  carries `key` (her voice), `alt` (the fallback voice) and, for more than one sentence, `parts`.
- **Companion order:** her whole line → all its sentences in her voice → the fallback voice's whole
  line → sentences mixed (pack where it has them, streamed where not) → the whole line streamed. Her
  voice's file is skipped when it's a broken F5 blip (`Voice.broken`: under half the fallback's
  length, or under 0.12 s a word).
- **Stream:** `{"t":"render","id":n,"text":...}` → binary `EDV1` + u32 id + PCM (0.2 s frames,
  sentence by sentence) → `{"t":"rendered","id":n}`. The server caches renders by key.
- **Pack:** `tools/make_voice_pack.py` copies `H:\SatelliteAI\voicecache` into `out/EdithVoice`:
  every file a known line maps to (library, sentences, taught answers, `lines.txt`), minus broken
  `hera_f5` renders. 2026-10-18: 3,390 lines known, 1,877 files, 197 MB; 27 broken renders and
  1,623 unmapped files (older voices and speeds) left out. `--install` copies it into the game's
  plugins folder.
- **Out:** her speaker in game (:47323, 0.1 s datagrams, 0.4 s ahead) when the state line says
  `speaker=1`, else the default output device.

## Messages

All on one WebSocket, `wss://<SparkAPI>/edith/brain`.

| Dir | Message | Content |
|---|---|---|
| ears → brain | `hello` | `{"t":"hello","v":1,"name":"<me or ''>","tz":<minutes east of UTC>,"build":"ears-1"}` |
| brain → ears | `hi` | `{"t":"hi","name":"Edith","voice":"hera_f5","fallback":"af_heart","speed":1.1,"stt":true,"tts":true}` |
| ears → brain | `dll` | `{"t":"dll","line":"state ..."}`: every line from the DLL's event port (`state`, `event ... by=`, `mute 0/1`, `heard <name> <text>`) |
| ears → brain | `EDA1` (binary) | `EDA1` + u8 name length + name (empty = this PC's mic) + int16 mono 16 kHz, one utterance, ≤ 13 s |
| ears → brain | `text` | `{"t":"text","text":"edith come here"}` (tests: answered like your own speech, no lobby check) |
| ears → brain | `speaking` | `{"t":"speaking","on":true/false}` (her line started / finished: reactions wait, the mic is off) |
| brain → ears | `reply` | `{"t":"reply","say":"Zoom zoom!","key":"…","alt":"…","parts":[[text,key,alt],…],"face":["happy",4],"orders":["come Bob"],"how":"instant come"}`; `say` can be empty (orders / face only, e.g. `favour Ann` every 10 s) |
| ears → brain | `render` | `{"t":"render","id":7,"text":"You like pizza?"}` |
| brain → ears | `EDV1` (binary) | `EDV1` + u32 id + int16 mono 24 kHz |
| brain → ears | `rendered` | `{"t":"rendered","id":7,"ok":true}` |
| brain → ears | `log` | `{"t":"log","text":"heard (1.3 s, whisper 0.48 s): Edith, come here."}` |

A puppet's own speech comes back as an order, `heard <text>`, which its DLL forwards to the host
through the relay as before. The host's companion then sends `heard <name> <text>` up as a `dll`
line, and the host's Edith answers it.

Limits per connection: 60 text messages/s, 30 utterances/min (≤ 13 s each), 30 renders/min,
4 queued utterances; 300 connections.

## Railway

- `requirements.txt` adds `numpy`, `faster-whisper`, `kokoro-onnx`.
- First start downloads Whisper `base.en` (~145 MB) to `$DATA_DIR/edith_brain/whisper` and Kokoro
  (`kokoro-v1.0.int8.onnx` ~90 MB, `voices-v1.0.bin` ~27 MB) to `$DATA_DIR/edith_brain/kokoro`.
  With `DATA_DIR` on a volume this happens once.
- Memory: about 0.5 GB for both models. CPU: ~0.5 s of Whisper per utterance on 4 threads
  (measured locally); Kokoro renders only lines missing from the pack.
- Env: `EDITH_STT=0` / `EDITH_TTS=0` turn either off; `EDITH_WHISPER_THREADS` (4),
  `EDITH_VOICE_THREADS` (2); `EDITH_WHISPER_DIR`, `EDITH_KOKORO_DIR`, `EDITH_LIBRARY` override the
  folders.

## Tested in game (2026-10-18 11:19, offline lobby in VR, brain on Railway)

- `Satellite.dll` started `run_edith_ears.ps1`. It found the pack in the game's
  `plugins\EdithVoice` (1,877 lines) and connected to `wss://sparkapi-production-e6df.up.railway.app/edith/brain`
  (Whisper, Kokoro and Postgres all up).
- Mic → Railway → reply, with Whisper at 0.25 to 0.29 s per utterance: "Hello, Edith" ("Hey!"),
  follow, spin, back flip, front flip, and "Keep spinning until I tell you to stop" (`spin keep`,
  no name needed in the follow-up window). Each order reached the DLL, and every line played from
  the pack through her in-game speaker. The dizzy lines fired every 5 s from the DLL's events, with
  the dizzy face.
- "Go back to spawn." said without her name and outside the window was ignored, as designed.
- Not tried in game yet: streamed lines, points from grabs and throws, mute, a second player.

## Carried over from satellite_ai.py (10:50 to 11:20 changes)

Bumps count as mean. Place names can be bare or misheard (difflib 0.75, and fragments under 4
letters don't match). Asking for an unknown place gets a how-to line. Corrections get a "misheard"
line, "change face" picks a random face, and questions recall notes (need 2 shared words). Lines of
2 words or fewer get a filler, and other talk over 5 words gets a nod (logged as unknown).
"X, remember that" saves a note, and "what's the first thing you said" works. `instant()` takes up
to 8 words, and the order said first wins. More flip and keep phrasings, plus "shoot me down".
`sentiment()` counts lines over 12 words by whole phrases only. The `mute 0|1 me= speaker=` line sets
`me` on the brain and the speaker choice on the companion. The companion sends a push or shutdown
aimed at you to your own client on :47325, without `to=`. The new lines are in `lines.json`
(`misheard`, `new_face`, `filler`, `nod`), and `chat.json` was rebuilt (296 entries). The server's
`edith_library` is now the copy that counts: edit it there (or live), not in `ai/library`.

## Tested (2026-10-18, local: uvicorn on 127.0.0.1:8766, venv H:\SatelliteAI\venv)

- Rules, offline: orders aimed by name (`come Me`, `follow FakeBob`), spins / keep / stop, kind and
  mean words with points, stubbornness (FakeBob at −2: "Make me.", then the grumbling yes), per-player
  profiles, places (`goto 1.00 2.00 3.00`), teaching (taught by you, answered for FakeBob),
  the unknown line, a shove at FakeBob after a throw. Records written per name.
- Audio: synthesized speech uploaded as `EDA1`: Whisper 0.43 to 0.48 s per utterance, wake word,
  the follow-up window ("Spin twice." with no name), FakeBob's voice chat as FakeBob's.
- Voice: pack hits by key ("Zoom zoom!", the joust answer, the unknown line); "You like pizza?
  Noted." streamed from the server.
- Live library: a `PUT` of `config.json` changed her "don't know" line within 2 s; a bad `chat.json`
  was refused (400) with her library unchanged; a new small talk intent added by editing the live
  file answered at once.

## Her own chat model again (plan, 2026-10-19)

User: she doesn't have to be smart, but she learns on her own, does what people ask, never says "sorry
i dont understand" again, and reports toxic / rude players and bug reports to the user. Instant lines
(her banks in EDITH.dll) stay first; new replies are rendered with Kokoro af_heart on Railway, as now.
User chose "a pretty straight-forward, low cpu chatbot engine" (over Claude Haiku API and Gemma 4 12B).

1. **Engine**: Qwen2.5-0.5B-Instruct, Q4_K_M GGUF (~400 MB), llama-cpp-python (prebuilt CPU wheel),
   2 threads, one reply at a time, downloaded on first start to `$DATA_DIR/edith_brain/chat` like
   Whisper and Kokoro. Env `EDITH_CHAT=0` turns it off, `EDITH_CHAT_MODEL` swaps the GGUF. ~1-2 s for a
   one-sentence reply (to be measured on Railway); a 6 s timeout falls back to her nod line.
2. **Where it answers**: only where `handle()` gives up today: the `unknown`, `nod` and question
   fallbacks. Prompt: who she is (short, in her voice and rules: no emoji, never "coming"), what she
   knows about the speaker (their profile), the last few turns, and the allowed actions. One or two
   short spoken sentences. say_clean + her rules on the output; an action tag (`[do: come]`, from her
   order list only) is carried out like a heard order.
3. **Learning**: every model reply is kept as a learned answer (Postgres / JSON beside the players):
   the same question next time answers instantly, and Kokoro's render is cached. Learned answers get
   points from how players react (thanks / told off) and are dropped when they go bad. `GET
   /edith/brain/learned` lists them, so popular ones can join her banks in the next EDITH.dll.
4. **Reports**: every utterance she hears (addressed or overheard, modded players only) is checked
   with her sentiment list plus a toxic word list and bug words (bug, glitch, crash, broken, stuck,
   lag, exploit, "doesn't work"). A hit becomes a report {who, what, kind, when, match}: sent at once
   to a Discord webhook (env `EDITH_REPORT_WEBHOOK`), and queued for the owner (env `EDITH_OWNER`,
   he_is_the_cat): the next time the owner spawns in her lobby she tells them ("While you were away,
   X was rude to me.", "Y reported a bug: ..."). `GET /edith/brain/reports` (ADMIN_TOKEN) lists them.
   Rate-limited per player so one rant is one report.
5. **Requests**: orders keep their instant regex path; the model's action tag covers requests worded
   in ways the regex misses.
