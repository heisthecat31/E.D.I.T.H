# E.D.I.T.H under nEVR (branch `nevr`)

Today E.D.I.T.H only runs on the old plugin loader (bin\win10\dbgcore.dll), and install.bat takes
nEVR out to get there. This branch makes EDITH.dll a real nEVR plugin, so players keep nEVR (and
EchoCombat's pack) and get her from the launcher's Mods page. EchoCombat's `nevr-pack` branch
(worktree EchoCombat-nevr) is the model: same ABI header, same Install/Shutdown shape.

## How she loads today

- `DllMain` (plugin/satellite.cpp) does everything under the loader lock: log path, the
  `-server`/`-offline` command-line check, EDITH.ini, `EdithPack_Install` (hooks FileExists,
  FileOpen, LevelLoad; mounts plugins\EDITH\*.edith on lobby load), the AI launch thread, then
  `Install()` (TransformGet, NetGameUpdate, FindScriptComponent, SetOwner/AdvanceGeneration,
  RenderAudio, VoIP Register).
- Data beside the DLL: EDITH.ini, EDITH\ (the .edith package + cache\), EdithVoice\ (~200 MB).
- Logging comes from EchoCombat **main**'s logdir.h (`EchoCombatLogPath(self, 3, ...)`), via
  `/I EchoCombat\plugin` in build_satellite_plugin.bat.
- Nothing is ever unhooked; threads (VoiceReceiver, LaunchAI, ears, edith_net) never stop.

## What nEVR needs

1. **Exports** (nevr_plugin_interface.h, ABI 5): `NvrPluginGetInfo` ("edith"),
   `NvrPluginGetApiVersion`, `NvrPluginGetCapabilities` (COSMETIC | NETWORK | HOOKS_ENGINE),
   `NvrPluginInitEx`, `NvrPluginInit`, `NvrPluginShutdown`. DllMain only records `self`.
2. **Move DllMain's body into `NvrPluginInitEx`**: INI read, pack install, AI thread, hooks.
   `g_server` from `ctx->flags & NEVR_HOST_IS_SERVER` (EchoCombatIsServer); `-offline` still
   from the command line. Return nonzero if the core hooks fail, so nEVR drops her cleanly.
3. **`NvrPluginShutdown`**: detach every hook from both Install()s (keep a flag per hook as
   DroneFix does), stop the threads (net socket, ears, voice receiver), stop the AI process.
4. **Logging**: switch to nevr_plugin.h's `EchoCombatLogPath(out, size, "EDITH")` ->
   bin\win10\plugin_logs\EDITH\EDITH.log (the launcher's "Upload logs" collects it), plus the
   stderr line nEVR's plugin log channel reads.
5. **Build**: a `build_satellite_plugin_nevr.bat` (or a switch) that includes
   EchoCombat-nevr\plugin instead of main's, with a `/DEDITH_NEVR` so one source serves both
   loaders while main still ships the dbgcore build. Without `/DECHOCOMBAT_LOG` for releases.
6. **Her package next to NvrContentOverlay**: keep edith_pack.cpp (her own mount) rather than a
   content pack: the overlay serves one active pack (`{"active": ...}`), which is EchoCombat's.
   To check in a log: both detour FileExists/FileOpen; Detours chains them, but the overlay's
   manifest-sha256 check and edith_pack's "another hook on the IO request" guard must both
   still pass, and her LevelLoad hook must be in before the lobby loads (nEVR may init plugins
   later than dbgcore did: if so, ask for `early: true` in her config.yaml entry).
7. **Release**: tools/make_release.py --nevr -> E.D.I.T.H-<v>.zip in the launcher's pack layout
   (plugins/EDITH.dll, EDITH.ini, EDITH\, EdithVoice\) + release/edith.mods.json (id `edith`,
   `plugins: ["EDITH.dll"]`, sha256, size). Check the launcher copies plugins/ subfolders
   (EchoCombat only ships flat files). No loader, no stock BugSplat64.dll in this zip.
8. **install.bat on this branch**: no "remove nEVR" path. With nEVR: copy into plugins\ and add
   EDITH to _local\config.yaml (or tell the player to use the launcher). Without nEVR: say
   nEVR is needed (or keep the dbgcore path if one zip should serve both).

## Behaviour to verify in game (nEVR client, public echovrce lobby)

- She appears, flies, follows (local mode, `local=1`), jets visible (particle-enable hook).
- Snowballs, faces, voice and her built-in ears; VoIP hook still finds Register.
- Two nEVR clients in one match: one shared Edith through the relay (edith_net).
- Together with EchoCombat 1.1.8 installed: both packs load, no "loaded too late".
- Closing the game: no BugSplat. EchoCombat's teardown skip lives in VeilNet's InitEx; without
  EchoCombat her particle effects may hit the shutdown crash, so she may need the same skip.
- Dedicated servers stay without nEVR (they can't log in to EchoRelay), so the server path is
  unchanged: the dbgcore build keeps covering `-server`.

## Order

1 -> 2 -> 4 -> 5 (builds and loads under nEVR, logs say so) -> 3 -> 6 (in-game check) ->
7 -> 8. Then the user publishes to the launcher dev folder (separate step, their call).

## Status (2026-10-19, uncommitted)

Done and tested on nEVR (H:\EchoVR\pc-latest, next to EchoCombat 1.1.8) with ONLY EDITH.dll in
plugins\: nEVR loads it, the lobby loads with her in it, her bank lines play (user heard the intro).
Install there needs `x-local-plugins: true` at the top of _local\config.yaml (the launcher keeps
that line and rewrites the rest; with it on, a DLL placed in plugins\ by hand loads).

The earlier "Cannot find resource 0x37102E4B27955A14:0x93629BB04D39790A" was not nEVR: C:'s .edith
(48.5 MB, built on the user's edited lobby, out/lobby_base) had been copied onto a stock install.
The DLL embeds the stock-based one (out/E.D.I.T.H, 5.07 MB).

Build: `build_voice_banks.bat` (out\edith_voice.bin), then `build_satellite_plugin.bat` ->
out\plugin\EDITH.dll (~62 MB), ONE DLL for both hosts: DllMain checks BugSplat64.dll (nEVR's
exports NEVR_SetGameModule; or bigger than 1 MB); under nEVR she starts from NvrPluginInitEx
(logs in bin\win10\plugin_logs\EDITH), else from DllMain as before (logs in
_local\echoCombatBetaLogs). Tested 2026-10-19 on both (H:\EchoVR\pc-latest nEVR, C: dbgcore).
Left: steps 3 (NvrPluginShutdown; she pins herself meanwhile), 6, 7 (release zip + mods.json:
now just EDITH.dll), 8 (install.bat for this branch).

## One DLL, nothing beside it (user, 2026-10-19)

Everything ships inside EDITH.dll: no EDITH\, no EdithVoice\, no .edith, no EDITH.ini.

1. **Her voice as Wwise banks, inside the DLL.** echovr.exe exports AK::SoundEngine::LoadBank
   (in-memory: `const void*, size, pool, &bankId`), UnloadBank and PostEvent. Her 1,880 cached
   lines (197 MB of int16 24 kHz PCM, ~69 min) become banks built at build time, like the game's
   (HIRC event -> action -> sound, DIDX/DATA media; EchoCombat's veil_sound.py writes these).
   The DLL loads a line's bank from its own bytes, PostEvents it on her game object (Wwise places
   it at her, 3D, like the game's sounds), unloads it after. Every client has the same DLL, so the
   host only sends a line id over the relay and every client plays it from its own copy.
   - Small banks (one per line, or a few lines each) loaded on demand: one huge bank risks the
     bank memory pool (the veil bank's ~3 MiB trouble).
   - Size: as PCM the DLL is ~200 MB. Wwise ADPCM (codec 0x00020001, 4:1, decoder built into
     Wwise) would make it ~50 MB, but needs an encoder written here and a check that the game plays
     it. Vorbis needs Wwise's own encoder (not available).
2. **New lines over the network.** Lines not in the banks (made after the build) stream from
   the host: rendered PCM, compressed (ADPCM, ~12 KB/s), in relay binary messages; each client
   feeds them into her existing speaker (the Audio Input source, edith speaker code). Host-only
   today.
3. **Her lobby data inside the DLL** (the 5 MB package as an embedded resource). The engine
   opens packages by file path, so the DLL either unpacks it to a cache under %LOCALAPPDATA% at
   start (nothing shipped beside the DLL) or serves the reads from memory (more hooking). The
   nEVR lobby failure above has to be fixed either way.
4. **Settings without EDITH.ini**: built-in defaults (her actor indices, local=1, relay URL),
   overridable through nEVR's config.yaml `args` (the launcher's Options) -> NvrPluginInitEx.
5. **The companion (Python AI)** stays outside: it's optional and the built-in ears already work.

### Done (2026-10-19)

1. **Voice banks**: plugin/edith_adpcm.h (Wwise IMA ADPCM, 36-byte blocks of 64 samples; SNR
   27.5 dB), tools/make_voice_banks.py (+ tools/adpcm_tool.c), one bank per line: event
   FNV("play_edith_<key>") -> Play -> top-level sound on bus 870370818 (voice chat's) with the arc
   mine attenuation 686965829 (3D). 1,880 lines: 56 MB (PCM was 198 MB). RCDATA 101.
   plugin/edith_voice.cpp loads a line's bank from DLL memory (LoadBank, 16-byte aligned copy),
   posts it on her speaker object SATLITE1, unloads it after. Ears and VoiceWorker play from it.
2. **New lines**: still rendered by the brain and streamed over the network to each game (as
   before); a game keeps them in memory for the session (64 MB at most), nothing on disk.
3. **Lobby data**: RCDATA 102; unpacked to %LOCALAPPDATA%\EDITH\cache. A .edith in
   plugins\EDITH\ overrides it (development, e.g. C:'s edited-lobby build).
4. **Settings**: built-in defaults; nEVR args (`{"local":"0", ...}`) override; an EDITH.ini beside
   the DLL still works for development. `voice_test=<key>` plays a bank line 3 times.
