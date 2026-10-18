# Edith networking plan

**Goal (user, 2026-10-18):** one Edith per match. Everyone with the mod sees the same satellite,
hears the same voice, and gets the same reactions. When someone talks to her, she knows who it was:
"come here" means *that* player, and a shove or shutdown hits whoever attacked her. She still never
says anyone's name.

## Where we are

- Every client simulates its own Edith (`Satellite.ini local=1`). The public echovrce servers don't
  run her, so nothing about her crosses the network. Two players with the mod see two different Ediths.
- Satellite.dll on each client: her brain and physics (`Tick`), grab, headbutt and wall detection,
  snowballs, push and shutdown (`ControlPlayer`, which only works on *your own* body online), faces,
  jets, and her speaker (Wwise, PCM from the companion on :47323).
- The companion (ai/satellite_ai.py): Whisper → wake word → cached reply → voice, plus orders to
  the DLL (:47321) and events back (:47322). Memory belongs to one player.
- VeilNet-style packets on the game's own socket only work when the server runs VeilNet
  (EchoCombat servers). On public lobbies a stock server drops them, so this plan uses a relay.

## Progress

- **Phase 1 (presence): done** (`sat-p1`). Offline run 2026-10-18 09:40 against a local relay
  (`relay=ws://127.0.0.1:8765/edith/ws`): connected, read own name from the player table, got `room`
  back as `alone`. Not yet tested with a second player.
- **Phase 2 (one body): written, built, deployed, untested** (`sat-p2`). Host sends `EDS1` every tick
  (~30 Hz, under the relay's 40/s). Velocities are measured from her motion. A puppet runs `PuppetTick`
  instead of `Tick`: it dead-reckons the last state (at most 0.25 s ahead), sets velocity = host
  velocity + 5 (m/s)/m of error (correction capped at 4 m/s), angular = host angular + 5 (rad/s)/rad,
  and teleports if more than 1 m off. It copies her face from the host. With no state for 2 s it goes
  back to her own brain. Her brain is reset whenever puppet mode starts or stops.
  **Tested 09:52 with `tools/fake_player.py host`** (Satellite.ini `debug_roster=FakeBob`): you saw her
  fly FakeBob's circle while ignoring you, as expected with a scripted host. Two loose ends: the relay
  showed your client leave FakeBob's room again (cause unknown), and Satellite.log stopped at
  09:52:21. A `tail -F` from Git Bash blocks the plugin's appends on Windows, so never tail
  Satellite.log; poll it instead.

- **Phases 3 + 5 and "who she listens to": written** (`sat-p3`, 2026-10-18).
  - DLL: names table (`g_names`, `SlotOf` / `NameOf`). Orders `follow|come [name]`,
    `push|shutdown|throw ... to=<name>`, `favour <name>`, `heard <text>`. Events carry `by=<name>`;
    `heard <name> <text>` for another player's speech. The state line adds `me=` and `members=`.
    Host: `touch` → `ApplyTouches` (grab / release / hit, by name). While another player holds her,
    the host follows their state. A push or shutdown aimed at another player goes out as `ctl`.
    Puppet: your grab makes you her owner (EDS1 with the held bit, no spring), a knock from your
    head becomes a `touch hit`, and a `ctl` for you runs `ControlPlayer` on your own body.
  - **Her ears on voice chat** (user: "she needs to be able to hear VOIP in game"). Hooked
    `CAudioInputCallbackRegistry::Register` (0x14020ca30) wraps Echo's voice delegate
    (fn 0x140c85b50) and copies each remote voice's PCM to the companion on UDP 47324
    (`"VOIP"` + rate + name + int16). The name comes from
    `Query::GetGameObjectFromPlayingID` → `Query::GetPosition` → the player head within 1 m.
    `hear_voip=0` turns it off. **Untested: offline has no voice chat.** Needs a real second player.
  - Companion: a `Person` per player (anger, attack counts, follow-up window). The favourite is
    the least-angry member, sent as `favour`. Orders go through `refusal()`: too mean (≥ 5, config
    `ignore_above`), or meaner than whoever gave the current order (held 60 s, `order_hold_s`), gets
    a refusal line. Orders are aimed at whoever asked. Temper shoves / shutdowns go to the culprit.
    Voice chat utterances (`voip_utterances`) and relayed `heard` lines go through the same path. A
    puppet's companion forwards your speech (`heard`) instead of answering. Teaching and the profile
    stay yours only; other players' profiles aren't done.
  - `tools/fake_player.py listen` takes actions on UDP 47330 (`say ...`, `grab`, `release`,
    `headbutt`, `bump`): `python tools/fake_player.py do "say edith spin"`.
  - **Tested 10:11 offline in VR, with FakeBob as the listener** (your client hosts, state at ~21/s):
    FakeBob's "edith come here" was obeyed as his (`come FakeBob`). Two headbutts by FakeBob took
    his anger to 5.9, moved her favourite to you, and his "edith spin" got "Not for you." Two
    grab+throws by FakeBob → `push 9 to=FakeBob` → a `ctl` reached FakeBob (you weren't pushed).
    Your own talking, flips and grabs kept working, counted against you separately. Fixed after the
    test (built, not yet deployed): `ThrowSnowball` returns whether it threw, so a revenge snowball
    at a player with no body isn't reported (she taunted after "nothing to throw at"). The ctl's
    position field is now `at`, because `from` is the relay's stamp and got overwritten.
  - Not yet tested: voice chat (needs a real second player), a puppet grabbing her (the
    FakeBob-host test with your hands), and per-player profiles (not built).
- **A dedicated server that runs her** (2026-10-18, local EchoRelay on 127.0.0.1:777 +
  `echovr.exe -server -headless -noovr`, same install, so the server loads her too).
  - Her body is the server's (replicated). A client in local mode can't steer it, so play with
    `local=0`. On one PC, the server then gets the companion's orders on :47321 (across machines it
    needs relay routing: a proposed follow-up).
  - **Net physics ownership:** a touch hands her body to the player (`SR15NetPhysicsOwnershipTransfer`),
    and the server's thrust then did nothing (she floated, deaf to orders). Now `ReclaimHer`
    takes her back on a `-server` once nobody holds her and 1.5 s have passed:
    `AdvanceGeneration` (0x140cf00b0) + `CR15NetPhysicsCS::SetOwner` (0x140d474d0), owner
    `0xFFFFFFFF`. The owner is the u32 at net-physics record +1Ch, stride 1F8h. **Tested 10:47:57:**
    a bump gave her to you (owner 0), the server took her back at 10:47:58, and she followed again.
- **Your mute:** `R15NetVoipMuteSelfNode` → 0x1401b24a0 sets bit 38 of `*(netgame+2DA0h)`. The
  DLL sends `mute 0|1`; the companion ignores your mic while muted. **Tested:** each toggle matched.
- **No doubles:** the relay's room has `ai` (members with a companion), passed on the state line
  as `ai=`. Their voice chat is ignored, since their own companion hears them.
- **Broken cloned lines:** 27 of 501 `hera_f5` renders were blips (F5 fails on short lines: "On my
  way!" was 0.13 s). `Voice.broken()` plays af_heart instead and doesn't queue them again.
- **Points** (user's rules, replacing anger): `Person.nice` / `mean`, score = nice − mean.
  - +1 nice for kind words to or about her (`sentiment()`). Holds from nice players are free.
  - +1 mean for mean words, throws, headbutts, and grabs by someone not nice. Mean fades 1 per 90 s.
  - 3 bad in a row wipe their nice points, and she answers with a mean line plus a snowball.
  - While negative: a shove every 2 bad acts, a shutdown at −5, and stubbornness (refuses the first
    ask; the same ask again or "please" gets a grumbling yes). The nicer player's order holds
    against a meaner one, and with someone nicer around, a score ≤ −5 is refused outright.
  - Overheard remarks ("she's so annoying") count, and she answers them ("I heard that.").
  - Words come from `ai/library/sentiment.json`, expanded (swearing, slang, threats, praise).
    Whole phrases count for any line said to her; 38/38 on a test set. Bumps count as mean too.
    Points are saved in memory.json (`points`), so restarts keep them.
- **Your body is your client's** (tested 11:05:25): a server's push / shutdown on a remote player does
  nothing (its KillPlayer flags stayed 31e), so every client DLL (never `-server`) takes "push" /
  "shutdown" for your own body on UDP 127.0.0.1:47325 (`NavHandleLocal`). The companion sends orders
  aimed at you there. The client's "mute 0|1 me=<name> speaker=0|1" tells the companion who you are,
  and whether her speaker plays in your game (a server's state lines know neither). Until the next
  DLL deploy, `voice_out=game` in H:\SatelliteAI\config.json keeps her voice in Echo.

- **Her brain moved to the server** (2026-10-18, `docs/brainplan.md`). SparkAPI's
  `edith_brain.py` (`/edith/brain`) now runs Whisper, the wake word, `handle()`, points,
  refusals, the favourite, teaching, and memory per player name, with her library editable live.
  The companion is the thin `ai/edith_ears.py`: mic + VAD + mute, DLL events up, orders and faces
  down, and her lines from the shipped voice pack (`plugins\EdithVoice`), streamed from the server
  when the pack lacks them. Nothing in the relay or the DLL changed: the host's companion still gets
  `heard <name> <text>` and `event ... by=`, and a puppet still forwards `heard`, now as an order
  from the brain. Points and profiles now persist per name, and other players' profiles work.

## Shape

```
   player A (host)                     SparkAPI on Railway                  player B, C ...
 ┌──────────────────┐   wss    ┌──────────────────────────────┐   wss    ┌──────────────────┐
 │ Satellite.dll    │◄────────►│  /edith/ws  (edith_relay.py) │◄────────►│ Satellite.dll    │
 │  her brain +     │          │  groups players who list     │          │  puppet: follows │
 │  physics         │          │  each other in their match,  │          │  the host's      │
 │ companion (AI)   │          │  picks the host, forwards    │          │  state           │
 └──────────────────┘          └──────────────────────────────┘          │ companion: only  │
                                                                          │  forwards speech │
                                                                          └──────────────────┘
```

- **Relay:** a new `edith_relay.py` router in `Railway/SparkAPI`, next to `htv_relay.py`, using the same
  pattern: one WebSocket per player, matched by display name and the match roster (two players are in
  the same group only if *both* list each other), rate limits, nothing stored. `main.py` adds one
  `include_router` line. Deployed with the rest of SparkAPI.
- **Identity:** the player's own display name and the match roster come from the game's player table,
  the way EchoXR-Hands does it (`GetUserName` echovr+0x1c98c0 per occupied slot, own player = the one
  slot with no remote body). The name is the ID everywhere, so no extra accounts or keys are needed.
- **Host:** one player per group runs her brain. The relay picks it, preferring players whose
  companion is running (so she can talk), then whoever joined the group first. When the host leaves,
  the next one takes over from the last state it received, with no snap.
- **Everyone else:** a puppet. Her body is steered toward the host's latest state with velocity
  (a spring on position and rotation, so she still collides normally). If she is more than 1 m off,
  she is teleported (`WorldTeleport`).

## Ownership: grabs and throws feel instant

- Whoever grabs her owns her body while holding her and sends her pose. The host and the other
  puppets follow that player instead of the host.
- On release, the owner sends `released` with her velocity. The host takes her back at that velocity,
  and the existing rules decide thrown or bump, snowball revenge and temper.
- Headbutts and bumps are detected on the client whose head hit her (it is near her, and her local
  velocity was knocked off the state it was following). That client sends `hit` with the new velocity
  and its name; the host applies it.
- The host's own grabs and hits work exactly as today.

## Who is who

- The host reads every player's head position from its own player table, by name (slot → name via
  `GetUserName`, slot → head via the net-game state record the DLL already uses). No positions are sent.
- `follow` / `come` / `stare` / snowball targets / `push` / `shutdown` all carry a **name**.
- A push or shutdown aimed at another player is sent to them, and *their* DLL applies it to their own
  body (`ControlPlayer` with `NavHandleLocal`, the only way that works online).
- Temper counts (`push_after` 2, `shutdown_after` 5) are kept **per player**: bullying from one person
  doesn't get someone else shut down.

## Who she listens to (user, 2026-10-18)

She listens to **everyone** in the match and picks who to listen to by how mean each person has
been to her.
- The host keeps a **meanness score per player**: the existing anger (grabs 0.7, bumps 1, throws 2,
  headbutts 3, insults 2.5, compliments -1.5, cooling 1 point per 20 s), but per name instead of one
  number.
- **Her favourite** is the player she's least angry at (ties: whoever spoke to her most recently).
  With no order she follows and looks at her favourite, not the nearest player.
- **Conflicting orders:** an order from someone meaner than whoever gave the current one is refused
  ("no." / a cold stare, no names). An order from someone nicer overrides it.
- **Too mean:** a player whose score is above a threshold (start at 5) gets ignored, even with nobody
  else talking, until they cool down. Their orders get a refusal line instead.
- Snowballs, shoves and shutdowns still go to whoever did it (per-person temper, below).
- This needs phase 3 (who did what, by name) and phase 5 (other players' speech reaching the host).

## Talking to her

- **Host's companion:** as today, plus it hears everyone else's speech forwarded from their DLLs:
  `heard <name> <text>` on the event port. Each line is handled as that person: orders target them,
  memory events record "Bob grabbed her", and "remember that I like X" goes into a per-person profile.
  Replies never use names (the existing `drop_name` rule).
- **Other players' companions:** forward mode. Whisper and the wake word as now, but instead of
  answering, `heard <text>` goes to their DLL, then to the relay, then to the host. Without a companion
  a player can still grab, throw, headbutt and be shoved; they just can't talk to her.
- **Her voice for everyone:** the host's companion tells its DLL which cached line it is playing
  (`say <cache key>`). The host DLL sends `voice <key>`, and every client plays the same file from its
  own copy of her voice cache (shipped with the mod) through its own speaker at her position, so the
  3D voice works the same everywhere. A line that isn't in the shipped cache (a taught answer, a
  freshly rendered line) streams as PCM from the host instead, 24 kHz mono, about 48 KB/s while she talks.

## Messages

All WebSocket. JSON text for events, binary for the fast state.

| Dir | Type | Content |
|---|---|---|
| client → relay | `hello` (text) | `{"v":1,"t":"hello","name":"Bob","roster":["Ann",...],"ai":true,"build":"sat-1"}` on connect and whenever the roster changes |
| relay → client | `room` (text) | `{"t":"room","host":"Ann","members":["Ann","Bob"]}` whenever the group or host changes |
| host / owner → all | `EDS1` (binary, every tick ≈ 30 Hz, 64 B) | seq u32, owner (u8 index into members), pos 3×f32, quat 4×f32 (x y z w), vel 3×f32, angular vel 3×f32 (world), face u8, mode u8, flags u8 (bit 0 held); arrives wrapped as `EDR1` + len u8 + sender name + `EDS1` |
| host → all | `voice` | `{"t":"voice","key":"<sha1 20>","text":"..."}` (text only for logs) |
| host → all | `pcm` (binary) | `EDP1` + seq + 20 ms chunk, only for lines not in the shipped cache |
| host → all | `snow` | `{"t":"snow","k":3,"pos":[...],"vel":[...]}` (each client moves its own copy of ball k) |
| host → one | `ctl` | `{"t":"ctl","to":"Bob","do":"push","speed":9,"at":[x,y,z]}` / `"do":"shutdown"` |
| any → host | `touch` | `{"t":"touch","what":"grabbed"}` / `released` with `vel` / `hit` with `vel` and `kind` (headbutt or bump) |
| any → host | `heard` | `{"t":"heard","text":"come here"}` (the relay stamps the sender's name) |

The relay stamps every forwarded message with the sender's name (`"from":"Bob"`), so nobody can speak
as someone else, and only forwards within a group. `ctl` goes only to its target; `touch` and `heard`
go only to the host; state, voice, pcm and snow go to everyone else in the group. Limits: state 30/s,
events 20/s, pcm 60 chunks/s from the host only, 4 KB per text message.

## Changes by part

**SparkAPI** (`Railway/SparkAPI`)
- `edith_relay.py`: groups by mutual roster, host election, stamping, routing, limits, `/edith/stats`.
- `main.py`: `app.include_router(edith_router)`.

**Satellite.dll** (`plugin/satellite.cpp` + a new `plugin/edith_net.cpp`, WinHTTP WebSocket like
EchoXR-Hands' `htv_net.cpp`, so nothing extra is installed)
- Read your name and the roster each net-game update; send `hello`; follow `room`.
- Roles: no relay or alone in the group = today's local mode. Host = `Tick` as now, plus sending
  state, voice, snow and ctl. Puppet = spring toward the received state, no brain.
- Players by name: `NearestPlayer` / `PlayerAt` become name lookups; the brain's "player" is the order
  target or the culprit, not "you".
- Ownership on grab; `touch` / `hit` reports; applying `ctl` to your own body.
- Voice: `voice <key>` plays `<plugins>\EdithVoice\<key>.pcm`; `pcm` chunks go straight to the speaker.
- Faces, jets and snowballs follow the received state and events.
- `Satellite.ini`: `relay=wss://sparkapi-production-e6df.up.railway.app/edith/ws`, `network=1`.

**Companion** (`ai/satellite_ai.py`)
- Reads `role=host|puppet` and `host=<name>` from the DLL's state line.
- Host: handles `heard <name> <text>` and events with `by=<name>`; targets orders at that name; keeps
  temper and profile per person; sends `say <key>` alongside the PCM.
- Puppet: forward mode (no replies, no voice), just `heard`.

**Mod package**
- Her voice cache (the rendered HERA and af_heart lines) ships as `plugins\EdithVoice\*.pcm`, about
  1,500 files, roughly 100 MB raw. It can be compressed later if that's too big.
- Everyone needs the same lobby build (her actors, faces, snowballs) and the same Satellite.dll.

## Phases (each one testable on its own)

1. **Presence:** relay plus hello/room. Two clients see each other in the log, one becomes host.
   Test with a fake second player (a small Python client using the `DebugRoster` trick EchoXR-Hands
   uses), so no second headset is needed.
2. **One body:** host state → puppet spring. The fake player replays recorded state, and your client
   as puppet shows her moving on her own.
3. **Hands on:** grab ownership, `touch` / `hit`, `ctl` push and shutdown aimed by name, per-person temper.
4. **Same show:** voice by key plus PCM fallback, faces, snowballs.
5. **Talking:** forward mode, `heard` with names, per-person memory, order targeting.
6. **Real test:** two people with the mod in one public lobby, then host leaving mid-match.

## Risks / open questions

- **Name changes mid-match:** names are read every update, so a change shows as a leave plus a join.
- **Host with a bad connection:** puppets see her stutter. Mitigations: 20 Hz state with interpolation
  and dead reckoning; later, the relay can prefer the lowest-latency member as host.
- **Two players grabbing at once:** the first `touch grabbed` the host sees wins ownership; the second
  hand just holds on locally until release.
- **Shutdown online:** a remote player's own client runs the shutdown, the same path that works for
  you today.
- **Voice cache size and updates:** taught lines stream as PCM until the next mod update ships them.
- **Railway:** WebSocket connections stay open; the HTV relay already does this on the same service.
  Free-plan limits apply to the whole of SparkAPI.
