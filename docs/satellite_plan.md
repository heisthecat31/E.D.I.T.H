# The Christmas satellite in the live lobby: plan

Goal: the little Santa CubeSat from the December 2017 Christmas lobby, in the live
build's lobby (`mpl_lobby_b2`). She drifts around the lobby, makes snowballs and throws
them at players, and everyone on an EchoCombat server sees the same thing.

Nothing is built yet. This is the order to build it in, what each step reuses, and what
is still unknown.

## What we know (2026-10-17)

| | |
|---|---|
| Source build | `J:\echo-summer-dist\Echo VR Christmas`: rad14 `ea_rel6_0` (Dec 2017), `bin\win7\EchoArena.exe` |
| Her level | `mpl_lobby_a_xmas` (`0xE7ACD884163B00A3`) |
| Data layout | `_data\5828984418\win7\{primary,GPU,debug}\<type>\<version>\<name>`: loose `COMPRESS` (Oodle) files, the Lone Echo layout, which lone_echo_blender reads |
| Oodle | `bin\win7\oodle_11_win64.dll` decompresses them, but only from a copy in a folder of its own: loaded in place, the folder's `dbghelp.dll` (the EchoRelay patch) loads too and shows "EchoRelay version check failed" |
| Her look | the Lone Echo CubeSat with a Santa decal (`decal_santa_cubesat_a` is a known name) |
| Her behaviour | scripts compiled into rad14 DLLs: they can't run in the live rad15 engine, so the behaviour is rewritten, not ported |
| Live build | no Christmas level, no snowball, no satellite actor in the lobby |

Already in this repo or next to it, and reused below:

- **CubeSat model in live**: `tools/fix_drone_model.py` puts `assets/drone/Drone4.glb`'s CubeSat
  on the DRONE (mesh in the game's vertex format, BC7 textures, prop shader set copies).
- **New things in a level**: lone_echo_blender `scripts/evr_add_model.py` (actor data, instanced
  model, visibility, transform, physics) and `evr_clone_level.py`.
- **Moving an actor**: CombatBots.dll moves bots with the engine's own `CncaGame::WorldTeleport`
  and follows recorded routes (`tools/record_nav.py`).
- **Pushing physics**: DroneFix.dll sets a body's velocity through `CPhysicsCS` (+0x469cb0).
- **Networking**: VeilNet.dll sends its own messages over the game's connection, relays them
  server -> clients, and knows which servers run EchoCombat (hello / answer).
- **Sounds**: the veil and NEUTRON sound work (`tools/veil_sound.py`), with the sound-bank size
  limit (~3 MiB) and HIRC order rules learnt there.
- **Names**: SymbolNames.dll and `tools/build_symbol_names.py` / `crack_symbols.c`, for reading
  hashes in both builds.

## Phase 0: what she really is (research, nothing shipped)

1. Decompress `mpl_lobby_a_xmas`'s resources (the Oodle copy above; teach the unpacker the
   24-byte prefix some `debug` files have).
2. Find her actor in the level: its components (model, transform, physics, script, sound, FX),
   its mesh, textures and material, and the script DLL that drives her.
3. Find the snowball: actor, mesh, physics, the "make a snowball" and hit effects and sounds.
4. Read her script (it's a native DLL, disassembly works) for the numbers: speed, how far she
   roams, how she picks a target, how often she throws, snowball speed, what a hit does.
5. Write it all down in `docs/satellite_2017.md`.

Done when we can list her parts and her rules. If her script can't be read, the rules come
from video and from memory instead.

## Phase 1: she's there (a model in the lobby, standing still)

She must be able to move, so she's a dynamic actor (model + transform), not static scenery
like `evr_add_model.py` adds by default.

1. Mesh and textures: the CubeSat body from `Drone4.glb` (already in the live format), plus the
   Santa decal and hat from the 2017 data (re-encoded as BC7, as `gear_icons.py` does).
2. Add an actor to `mpl_lobby_b2`'s level resources with a model component and a transform,
   made the way the drone ordnance's model parts are (they move, and they draw the CubeSat
   already).
3. No collision yet. Pack it with the rest of the EchoCombat data, so only modded players load it.

Done when she floats in one spot in the lobby, for every client with the mod, with no new
errors in the logs.

## Phase 2: she moves (server decides, clients follow)

A new plugin, `Satellite.dll` (server and clients), or a part of VeilNet.dll:

1. **Server**: owns her state. She wanders between points inside a lobby volume, recorded with
   `record_nav.py`, at a slow float speed, and drifts toward players now and then (player
   positions as PowerBoost already reads them: player slot -> actor).
2. Server -> clients: a VeilNet message (say `'S'`) about 10 times a second: position, heading,
   what she's doing (idle, making a snowball, throwing).
3. **Clients**: move her actor to the interpolated position each frame (an engine teleport like
   CombatBots, or by writing her transform), and add the bob and spin locally.
4. A client that joins late gets her current state in the answer to its first hello.

Done when two clients see her in the same place, moving smoothly, including one that joined
late.

## Phase 3: snowballs

1. A pool of snowball actors in the level patch (say 8): a small white sphere, physics, and a
   grab component like the lobby's throwables if players should be able to throw them back.
2. **Making one**: her "make" state. Clients show the snowball growing in front of her over
   about a second, with a sound.
3. **Throwing**: the server picks a target player in range, works out a velocity with lead (the
   lobby has no gravity, so straight lines are enough), and sends `'B'` (snowball id, start,
   velocity, start time). Each client launches its copy the same way (set velocity through
   `CPhysicsCS`), so all clients agree without streaming every frame.
4. **Hits**: the server checks the snowball against players' heads and bodies. On a hit, a
   `'H'` message: a snow splat effect and sound everywhere, and maybe a small push on the hit
   player (no damage: the lobby has none).
5. Snowballs return to the pool after a hit or a few seconds.

Done when she throws at someone, everyone sees the same snowball, and a hit splats for everyone.

## Phase 4: hardening

- Servers without EchoCombat: she isn't in their level data, and VeilNet's gate keeps the
  messages off.
- Several lobbies on one server process: one satellite per game space.
- Message rate limits; no snowballs while nobody is in range.
- Crash safety like the drone work: never touch an actor or component after it's freed (the
  DroneFix lesson).
- A config switch (`config/`) to turn her off, or on only in December.

## Phase 5: polish

- Her sounds (bleeps, the throw, the splat) in a bank that stays under the size limit.
- Players catch snowballs and throw them back at her; she reacts to being hit.
- Matching the 2017 look and timing as closely as Phase 0 allows.

## Unknowns and risks

| | |
|---|---|
| Can a new dynamic actor be added to a live level's data, or does she need to reuse an existing pooled actor? | Phase 1 decides; the drone ordnance actor is the fallback template |
| Are lobby physics objects replicated by the game, or local to each client? | Phase 3 assumes local, synced by our own messages |
| Her script may not be readable | rules then come from video and memory |
| Collision and grabbing snowballs need a physics resource and a grab component in the patch | the hardest part of Phase 3 |
| Lobby frame time | a few actors and a 10 Hz message are cheap, but check against the mid-join frame drop work |

## Decisions for you

1. Lobby only (`mpl_lobby_b2`), or the combat lobby too?
2. What a hit does: a splat only, or a splat plus a small push?
3. Can players catch and throw snowballs back (Phase 3 or Phase 5)?
4. Always on, or only in December / behind a config switch?
