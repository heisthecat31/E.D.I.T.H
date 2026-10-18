# E.D.I.T.H: agent notes

Goal (first project): the **Christmas satellite** in the live game. She's a little Santa
CubeSat from the Christmas lobbies who floats around the lobby, makes snowballs and throws
them at players. Bring her into the live build (`631547.rad15_live`, data package
`5932408047`) lobby `mpl_lobby_b2`, so everyone on an EchoCombat server sees the same thing.

Keep this file current. Every finding goes in **Findings** with its evidence; every dead
end goes in **Wrong turns**. The phase plan is `docs/satellite_plan.md` (written before the
2018 build was found; where they differ, this file wins).

## Folders

| path | what |
|---|---|
| `J:\EchoVR-Tools-Launcher\E.D.I.T.H` | this work folder: `tools/`, `out/`, `docs/` |
| `J:\EchoVR-Tools-Launcher\EchoPorting` | the event-lobby port to live (Summer first). **Read its `agent.md` before touching formats**: converters, the loose-file / `.kfclvl` delivery, the script ABI (F25), launch line (F5) |
| `J:\echo-summer-dist\Echo VR Christmas 2018` | **main source.** rad15_winter goldmaster 268902, lobby `mpl_lobby_b2_xmas`, data `_data\5868485946\rad15\win7` (manifest + packages, read with evrtool), scripts as loose DLLs in `bin\win7\scripts\<hash>.dll`. Has the right pathfinder paths; no voice lines |
| `J:\echo-summer-dist\Echo VR Christmas` | Dec 2017 build (rad14 `ea_rel6_0`), lobby `mpl_lobby_a_xmas`, loose `COMPRESS` files in `_data\5828984418\win7` (Lone Echo layout). Has her voice lines |
| `J:\echo-summer-dist\Echo VR Lobby v1\bin\win7\EchoArena.pdb` | full symbols for a 2017 rad14 engine (a bit older than Christmas 2017) |
| `J:\EchoVR-Tools-Launcher\EchoCombat` | plugins (DroneFix, VeilNet, PowerBoost, CombatBots), `evrtool`, the DRONE CubeSat model (`tools/fix_drone_model.py`), name tools (`tools/build_symbol_names.py`, `tools/crack_symbols.c`, `build/SymbolNames.txt`) |
| `J:\EchoVR-Tools-Launcher\lone_echo_blender` | format docs (`docs/`), readers (`scripts/le_archive_decode.py`, `evr_actor_table.py`, `evr_add_model.py`, `evr_win7_to_win10.py`), pyoodle (`app/extract/pyoodle`) |
| `H:\ready-at-dawn-echo-arena` | test install (laptop hard drive, slow loads). `C:\Oculus\...\ready-at-dawn-echo-arena` is the user's VR client |

## Rules

- Never modify the event builds or a stock datadir; outputs go in `out/`.
- **Never load an event build's `oodle_11_win64.dll` in place.** Its folder's `dbghelp.dll` is
  the EchoRelay patch: loading Oodle from there pulls it in, the DLL fails to start (error 1114)
  and the user gets "EchoRelay: version check failed" popups. Use `tools/oodle/oodle_11_win64.dll`
  (a copy alone in its own folder). For lone_echo_blender scripts set
  `LONE_ECHO_OODLE_DLL` to it and `PYOODLE_PATH` to `lone_echo_blender\app\extract\pyoodle`.
- Windows Python can't open `/j/...` paths: pass `J:\...` (`cygpath -w`).
- Format claims need a measurement (twin compare, parse over the corpus, or the game loading it).
- Test with the user's normal flags; offline smoke tests use EchoPorting's F5 launch line.
  Test level: **`mpl_lobby_b2`**, not `mpl_lobby_b2_summer` (summer takes ages to load).
- Don't copy secrets (e.g. EchoPorting's `.mcp.json` holds a ReVault access token).

## Tools here

| tool | does |
|---|---|
| `tools/unpack_xmas.py <src> <dst> [regex]` | decompresses every `COMPRESS` file under a folder (2017 data), optional string grep |
| `tools/xmas_list.py <level> <out> <names.txt>` | lists a 2017 `CArchiveResourceWin7` level's sub-resources (type, name, offset, size) and saves the streams. Needs the env vars above plus `LONE_ECHO_DATA_ROOT` = the 2017 `win7` folder |
| `tools/actor_diff.py` | actors in one level that another lacks. **Fails on 2018 actor data** (the lone_echo_blender parser expects the live layout) |
| `tools/level_diff.py <dirA> <lvlA> <dirB> <lvlB> --types <contents.tsv> --names <f>...` | actors (with their component types) one level has and another lacks, from the owning-actor field of every component row; works on 2018 data |
| `tools/find_refs.py <dir> <lvl> <hash>... --names <f>...` | component rows that mention given hashes, with the owning actor |
| `tools/script_vocab.py <names>... -- <dll>...` | a script DLL's symbol hashes (named) and float constants, no PDB needed |
| EchoCombat `evrtool.exe find <dataDir> <hash>...` / `get <dataDir> <list> <out>` | finds and extracts resources by name from any rad15 manifest datadir (2018 or live) |

## Findings

### S1. Her parts (names from the 2017 build's own strings, 2026-10-17)
`out/xmas2017/names_found.txt`. Cracked by hashing the 2017 build's strings (exe, sourcedb,
unpacked scripts and level) and then her prefixes plus words (`crack_symbols.exe`).

| hash | name | 2018 | live |
|---|---|---|---|
| `493ad5c876c84fae` | `prp_itt_cube_sat` (model, skeleton, anim set) | 13 resources | none |
| `4ab3ff017a2ce803` | `prp_itt_cube_sat_mp_xmas` (her prefab) | 12 | none |
| `0116d1062743cb8e` | `prp_itt_cube_sat_mp_script` (main script) | script | none |
| `8af13004a97ce83a` | `prp_itt_cube_sat_mp_xmas_thruster_control` | script | none |
| `fddb5fb5a78f30fe` | `prp_itt_cube_sat_mp_home_position_pathfinder` | script | none |
| `8e23e03db27c66b9` | `prp_itt_io_port_mp_xmas` (I/O port: model + script; likely where snowballs come out) | 14 + script | none |
| `9435dac4d519b449` | `fx_test_austin_multiplayer_lobby_xmas_snowball_a` (snowball script) | script | none |
| `067d7f39b0c7482a` | `tst_dsn_robby_cbt_ai_target_tracker` (AI target tracking) | script | none |

Also in the 2017 level: textures `prp_itt_cube_sat_blend_msk`, `prp_itt_cube_sat_strobe_fx_emi`;
props `prp_toy_fun_xmas_present_teleporter` / `_teleportable_prop`; sounds
`mpl_lobby_a_xmas_ambient/_music/_sfx`. The level has a `CR14FrisbeeCRWin7` table (snowballs
probably fly as frisbee-type objects).

### S2. The 2017 Christmas lobby (`mpl_lobby_a_xmas`, `0xE7ACD884163B00A3`)
One `CArchiveResourceWin7` (81 MB compressed; 160 MB primary + 318 MB GPU unpacked) with 2,645
sub-resources: 54 scripts, 22 dynamic instances, 54 mesh lists, 27 skeletons, 12 anim sets,
33 GPU particle effects and per-level component tables. Listing: `out/xmas2017/mpl_lobby_a_xmas_contents.tsv`.
The `debug` type folders hold `COMPRESS` files with 24 extra bytes before the container;
pyoodle rejects them as is (not needed so far).

### S3. The 2018 Christmas lobby (`mpl_lobby_b2_xmas`, `0x6DAA6D98D9354BA5`)
The Christmas variant of `mpl_lobby_b2`, the lobby live uses. Same rad15 resource type hashes
as live's Win7 names. Both levels extracted with evrtool (77 resources each) to
`out/xmas2018/mpl_lobby_b2_xmas` and `out/xmas2018/mpl_lobby_b2` (`<type>\<level>`). Diffing
the two in the same build shows what Christmas adds to `mpl_lobby_b2`, which is what has to be
added to live's `mpl_lobby_b2`.

### S4. Scripts: what does and doesn't carry to live
- Script DLLs import nothing and export only `setup_bindings`; the engine passes them a table.
- Live keeps scripts as a resource (type `06eace9f64204fd0` = DLL with a 20-byte header,
  `991421b41de58370` = `CScriptResourceWin10`, 4 bytes). 212 of the 2018 build's 360 scripts
  exist in live, rebuilt in Nov 2021 (e.g. `80461e04c6d82c21`: 2018 15 KB, live 126 KB).
- `setup_bindings` fills the same table slots (+0x20..+0xD0) in the same order in 2018 and live.
- **But per EchoPorting F25 (from the PDBs) the runtime structs changed** (EXECUTION_THREAD
  208 -> 224 B with shifted fields, thread stride 0xd0 -> 0xe0, nodefunction gained a
  parameter). So her 2018 scripts can't run in live unchanged: either re-target them the way
  EchoPorting plans for Summer, or rewrite her behaviour (plugin), as `docs/satellite_plan.md` does.

### S5. Live
No Christmas level is shipped, no snowball, nothing of hers. Live's `matchsettings_config.json`
still lists `mpl_lobby_b2_xmas` (EchoPorting F5). The DRONE already draws a CubeSat in live
(`echocombat_drone_cubesat_port`, from `assets/drone/Drone4.glb`).

### S6. What Christmas 2018 adds to `mpl_lobby_b2` (2026-10-17)
`tools/level_diff.py` (owning actor id at row +8 of every component table) ->
`out/xmas2018/diff.txt`: 238 actors only in `mpl_lobby_b2_xmas`. `tools/find_refs.py` (rows that
mention her script / model hashes) -> `out/xmas2018/her_refs.txt`. Her actor `82fcb72c482b322f`,
I/O port `8afc20320c9dd6df`, target tracker `3b5851f3ca7dff68`, 18 snowballs, 40 waypoints. All
plain level actors with stock components; the engine networks her and the snowballs (net
physics, ownership transfer, net events). Details: `docs/satellite_rules.md`.

### S7. Her scripts, as far as they can be read without a PDB (2026-10-17)
- Her 2018 script resources (`b074cf486db462a7`) are the bare DLLs (= `bin\win7\scripts`); the
  2017 ones too. **No PDB in either build** (unlike Summer 2019, F25), so `sdis.py` / `script_port.py`
  have no names to work with here.
- `tools/script_vocab.py` lists each DLL's symbol hashes (named from the 2017 names, the live table
  and the type names) and its float constants -> `out/xmas2018/script_vocab.txt`. That gave her
  behaviour in outline: physics flight with 8 thrusters, players can grab and throw her, waypoint
  route that follows the players, snowball pool with respawn points, target lead from a tracker
  that smooths the target's velocity, voice-line events, I/O port "snapshot", present teleporters.
- Every engine node those scripts call exists in the live exe (checked by name).

### S8. What this means for the port
She's built entirely from stock components and scripts, networked by the engine. Bringing the
2018 actors into live's `mpl_lobby_b2` with EchoPorting's converters, plus her 9 scripts
re-targeted to the live script ABI (F25), would give her exact behaviour with no plugin and no
VeilNet messages. That's likely less work and more faithful than the plugin rewrite in
`docs/satellite_plan.md`, but it depends on EchoPorting's script re-targeting working without
PDBs (it was designed around them).

### S9. A NEW actor in live mpl_lobby_b2 (2026-10-17, the user chose "spawn a new one")
`tools/build_satellite.py`: clones live mpl_lobby_b2 as `mpl_lobby_b2_sat` (evr_clone_level),
adds actor `echoenh_satellite` (`c907788a0be90017`) stamped from donor `8c45e06184aae5ba` (a
small 5-bulb light fixture): actor data (echomod `clone_actor`), CModelCR (`clone_model_entries`),
CTransformCR, CActorLOD/CBoundingSphere/CTextureStreaming rows, and a node in the level's
**CGSceneResource node graph** (quest_combat_port `resource_io/cgsceneresource.py`). Packaged as
`.kfclvl` on H: (EchoPorting play.py) and launched with the F5 line.
- Without the scene node: loads, but not drawn (the scene graph's actor -> vertex lookup lists
  every model actor: 78/78).
- Scene node APPENDED (vertex 1768): loads, but a poster then followed the camera and lights
  appeared in the spawn area: the lookup's value must equal its position.
- Scene node INSERTED at its signed-sorted place with every vertex reference renumbered
  (vertex ids, edge handles, root/leaf lists, idxremap, types, names, the scene actors table of
  type-0 records, box tree leaves): loads clean (vertex 523, record 195). User check pending.
- `play.launch` kills the game once in game; for the user to look, start echovr yourself
  (Start-Process, same args) and leave it running. User: "you're closing way too soon".

### S10. Her model in live format (`tools/port_assets.py`, 2026-10-17)
Converts named 2018 resources with EchoPorting `build_port.convert_one` into `out/her_assets`
(`<type10>/<name>`). Her model `prp_itt_cube_sat_mp_xmas` + I/O port + base `prp_itt_cube_sat`
+ their textures / material / 3 shader sets (DXBC -> DXIL): 41 ported. 2018 differs from the
2019 Win7 those converters were measured on (twins vs `J:\Summer`):
- CGSceneResource: 2018 = 2019 + 8 zero bytes at the end (31/40 twins) -> strip.
- CGMeshListResource: 2019 starts with a u64 flag 2018 lacks -> prepend 8 zero bytes.
- CTransformCR rows 160 B (2019: 168), CComponentLODCR 88, CPhysicsCR 40: not converted yet.
- **CSkeletonResource**: different header (1800 vs 1576 B, root table moved from 0x40 to 0x128,
  32-B rows where 2019 has 24, an extra 16-B table) -> no converter yet. **Her mesh is skinned**
  (vertex usages 5/6), so she needs it.
- **CAnimSetResource**: 2018 layout differs too (converter reads garbage) -> no converter yet.
Her 2018 pose: (-0.073, 1.239, -0.25), rotation (0, 0.5, 0, 0.866) = 60 deg about Y, scale 1;
home waypoint `5496188c1420bd04` at (0, 1.07, 0). I/O port + target tracker are parented to her.
40 waypoints and 17 snowballs listed in the session (positions from her 2018 transform table).

### S11. Her own model in the build (2026-10-17)
`build_satellite.py --her-model [--view]`: her converted 2018 CModelCR row (conv_cr converts the
2018 CModelCR) transplanted into live's table (`transplant_model_rows`; every copy of her old
actor id `82fcb72c482b322f` in the row re-pointed, else "Missing actor with nodeid ..." and the
level fails), her 2018 pose, the donor-cloned one-table rows re-pointed from the donor's model to
hers, and `out/her_assets` shipped in the .kfclvl. Loads clean, in game.
- Skeleton: Summer 2019 has the base `prp_itt_cube_sat` skeleton (same bones as hers); hers =
  that with her name at +0, through conv_skeleton. Her own 3-entry tail table (different names,
  base vs xmas) is NOT carried yet. 2018 skeleton layout itself still unconverted.
- No animation set yet (2018 CAnimSetResource unconverted): she draws in rest pose.
- Texture data: 4 `RawTexturePackfile` (2018 type 51e6cb2d64c65e4f -> live ae49fad43254367a,
  copied verbatim; names from the "Cannot find resource 0xAE49FAD43254367A:..." log lines).
- `--view` (or Start-Process) leaves the game running for the user.

### S12. Why she wasn't drawn: the scene's per-actor transform records (2026-10-17)
The scene's `actors` table (56 B records: 2 x u64, quaternion, position, scale) is indexed by
ACTOR-DATA index for the first N actors (live mpl_lobby_b2: N = 659, record r == actor r
659/659); actors N.. are pooled templates. `insert_actor` now puts her AT index N (pooled
actors move up one; headers, components, parents, bits renumbered) and the scene gets her own
transform record at N. After this the engine started streaming her textures (more packfile
requests = she is being drawn). `tools/fill_packfiles.sh` loops build -> run -> fetch missing
`RawTexturePackfile`s (+ neighbours) from 2018 until none are missing (15 now; 0 missing in 3
runs). User check: she is NOT visible.

### S13. The new actor isn't drawn whatever model it has (2026-10-17)
`build_satellite.py --scale` / `--shots` added. In 10 s screenshots the new actor shows nothing with:
her model at (0, 2.6, 0) at 5x, the donor's model there at 5x, and a lobby terminal model
(`aaa5ce66c86a29ce`) at 3x and at (0, 1.7, 0) at 2x. So the fault is in how the actor is added,
not in her ported assets (more packfile requests in S12 didn't mean she was drawn). Ruled out:
- scene record order: record r == actor-data r (659/659 positions); type-0 vertices (659) are
  in signed-sorted order, NOT record order (11/659 match).
- CModelCR base tail `node_index`: 0xFFFF in all 82 live rows (not an actor link). The donor's
  SSceneSet / SInitData name the actor only at +8; SInitData +0x18 = 0x1c (StartVisible 0x10 set).
- box tree: 45 leaves (0..44), not records.
The offline spawn point is random per launch, so one screenshot can miss a spot.
**Don't start echovr while a smoke test is running**: the loader rewrites the .kfclvl when it
loads (mtime = load time), and a second instance reading it then fails with "zstd: Unknown frame
descriptor" (user's 09:51:02 log).


### S14. VISIBLE: models only draw on dynamic actors (2026-10-17)
- Static lobby props are drawn from baked scene data: swapping all 226 terminal model ids in our
  CModelCR (both package and loose copies verified) changed nothing on screen, nor did moving
  them or clearing a CModelCR bitfield. The light-fixture donor is that kind of actor, so every
  build from it was invisible whatever we did to the rows.
- A model on an animated actor draws: `--donor ad268e2881f03045` (root actor, no prefab,
  CAnimationCR + particles + script at the spawn tubes) with `--her-model` shows her at (0, 2.3, 0)
  as a NEW actor. `--skip` (default CScriptCR, CParticleEffectCR) keeps the donor's script and
  particles off her; `clone_table_rows` copies multi-array tables (CAnimationCR) via EchoCombat
  cr_table; `copy_model_row_bits` gives her CModelCR row the donor's bitfield bits and owner.
- Don't use the lobby disc (8825e75eedb08b7e): it has its own bubble, and the user doesn't want
  stock items replaced (an earlier test put her model on it: drawn, but wrong).
- User check of this build: she is upside down, most of the model is missing, no collision, no
  animation, no sound. Strobe flashing is right (she does that in Christmas).
  Likely cause of the first two: the skeleton is Summer's base `prp_itt_cube_sat` renamed (S11),
  not her own 2018 one.


### S15. Upright, with her I/O port (2026-10-17)
- Upside down = the donor's rotation: ad268e2881f03045 is turned 180 deg about X and `--at`
  skipped HER_ROT. `--her-model` now always uses her 2018 rotation unless `--rot` is given.
- `tools/conv_skeleton18.py`: CSkeletonResource 2018 Win7 -> 2019 Win7 (then EchoPorting
  conv_skeleton -> live). Twin prp_itt_cube_sat: same size, 12 bytes differ (float rounding, hash
  order of the small key tables). Layout table in its docstring. Her skeleton and the port's
  (`8e23e03db27c66b9`, 5 bones, no Summer twin) are converted from their own 2018 files into
  out/her_assets/46adff5980245670 (replaces the renamed Summer base skeleton).
- Her mesh list = the base CubeSat's (same sizes); the hole in one face is where the I/O port
  goes. `--with-port` adds it as a second new actor (`echoenh_satellite_ioport`, 2018 row of
  8afc20320c9dd6df, model prp_itt_io_port_mp_xmas), offset (0.057, 0, 0.032) from her in 2018,
  rotated with her. Not parented to her yet (it won't follow her once she moves).
- Build: `python tools/build_satellite.py --her-model --with-port --at 0 2.3 0 [--launch|--view]`.
- Still missing: collision (CPhysicsCR row + her physics resource), animation (2018
  CAnimSetResource unconverted) and her scripts (flight, snowballs, voice, sounds), see S8.


### S16. Collision, grab, impact sounds; I/O port attached (2026-10-17, user-confirmed)
- `tools/conv_physics18.py`: bone-attached CPhysicsResource 2018 -> 2019 -> live (EchoPorting's
  conv_physics refuses bone count != 0). 2018 -> 2019: drop the u64 at header +8; each body's
  transform 64 -> 80 B (scale (1,1,1,0) at +32); shape records (192 B per bone) +64 u16 0xb2 -> 0x1dd.
  2019 -> live: bodies via conv_physics, shape records +64 u16 -> 0 and 24 zero bytes at +186
  (192 -> 216). Twins: 14/30 exact, the rest float last-bit / quaternion sign / re-exports.
  Her physics (17 bones, 1 body) and the port's (5 bones) are in out/her_assets/b7d338793fa37832.
- `--physics-donor` (default the disc 8825e75eedb08b7e) copies a live grabbable prop's
  CPhysicsCR, CR15NetPhysicsCR, CR15TouchInteractCR, CR15NetTouchInteractCR and CR15NetIdCR rows
  onto her: the flag words changed since 2018 (CPhysicsCR 40 -> 48 B, flags (a|b) << 2; net physics
  2 -> 0x10, touch 0x80 -> 0x480, net touch 2 -> 0x70). Not CR15SyncGrabCR (the disc's own).
  2018-only CR15CollisionCR (impact events) and CParticleCR (her 8 thrusters, effect
  1536f4115b2ea1b7 on 8 joints) have no live table: live uses CParticleEffectCR (152 B).
- User: can grab and hit her, impact sounds right. She doesn't move on her own (no scripts).
- Port: `attach=(her, joint)` writes a live joint attachment (parenttype 3, parentxf
  (-1, 0, ncaTransform), model (parent actor id, 0, ncaModel), joint name, offset type 1), as the
  2018 port row does. Joint = her root bone 0xDC009ABAB276ED03 (bytes 03ed76b2ba9a00dc: read hex
  dumps as little-endian!). User: attached, moves with her.

### S17. What's left and how hard (2026-10-17)
- **Animations**: her set is only under the base name (`9576db2165a5f779/493ad5c876c84fae`,
  11336 B); no Summer twin. 68 other sets exist in both 2018 and Summer (out/twins18_anim). The
  2018 format is NOT a re-layout of 2019: it is a RAD struct (tools/radstruct.py reads the frame:
  808-B root with inline array headers, flag 4) whose root carries a much richer evaluator tree
  (named blend nodes with offsets) where 2019 keeps a 36-B one-clip tree; the 2018 element is
  944 B vs 2019's 888 (0x378) with 14 sub-tables. The curve payloads look shared. A converter
  needs the 2018 tree node types mapped to 2019's (anim_walk / conv_animset know 2019 + live).
- **Scripts** (flight, route, snowballs, voice, I/O port faces, animation playback): her 9
  DLLs have no PDB. EchoPorting's rewriter (script_port.py) only reached stage 1 (identity) and
  needs PDB types. The map editor can compile node graphs into live DLLs (scripting/codegen,
  ~40 verified node types) and import shipped DLLs' node types + control-flow edges
  (scripting/roundtrip), but not the logic compiled into each node. Routes: (a) PDB-less binary
  re-target of the 2018 code, (b) rebuild her graphs in the map editor's codegen from the 2018
  disassembly, (c) a native plugin that drives her (docs/satellite_plan.md). Only (a) is
  byte-faithful.

### S18. Animation sets 2018 -> live (`tools/conv_animset18.py`, 2026-10-17)
- **2018 layout** (every one of the 68 twins + her set walks to EOF, `parse18`): root fields
  +0x00 desc C x 16 (element name, u64 index), +0x38 (0,A) (0,B) (0,0x140) u32 0 u32 1 (an inline
  blob, not an array desc), +0x80 desc 8 x 56, +0xc0 desc C x 944; data from 0x130: the C x 16
  name table, A x 112 records, the B-byte tree block, a 0x140-B block, align 8, the 8 x 56
  entries, C x 944 elements, then per element the 13 2019 payloads + u32 x 14 + 12-B x 14*S +
  S x 96-B scenes. The 0x140 block, the 8 x 56 entries and root +0xf8..+0x130 are the SAME bytes
  in all 69 files: S17's "much richer evaluator tree" was this boilerplate, not per-set data.
  radstruct's generic walk does not apply (it misreads the +0x38 blob); the converter walks it.
- **-> 2019**: header (0,A) (0,B) (0,C); the name table is dropped and gives the 2019 element
  order (2018 stores elements in another order; 68/68). Records 112 -> 128 B: fields move
  (`REC`), tree offset +8 -> +12, and 2019 +120 is new = active bone masks (u64 header 1) in the
  record's tree (711/711 twin records). Elements: the u32 x 14 table goes inline at +0x2c0 (it is
  56 B in every file), the 12-B table is dropped, u16-table align word 0x20 -> 0, scene rows
  96 -> 64 B = row[0:8] + row[40:96] = the Summer skeleton's root row byte for byte (her set).
- **Trees**: evaluator ids 0..0x19 are the same classes in both exes (unpack switch at 2018 rva
  0x1466f0 / Summer 0xc6556c, RTTI). Changes: clip (1) gains the set name after the anim name
  (28 -> 36 B); 0x12 blend: count high word 0xffffffff -> 0, entry tail (f32 1/6, f32 1.0) ->
  (f32 1.0, u32 0) (116/116), mask words +68/+72 cleared when +68/+72/+76 = (2,5,0) (54/54; kept
  for (2,5,2), 30/30); 0x13 auto layer: f32 1/6 -> 0, its n inline 0x0d child names dropped
  (2/2); three-way id 0x0a -> 0x08 (16/16; 2018 never uses 8, Summer never 0x0a).
- **Twin result** (65 with a Summer version; `python -I tools/conv_animset18.py`): 4 byte-exact,
  42 same data (only: record order, which Summer sorts by source name and the hashes can't give;
  uninitialised words in 2019 masks, entry 0 of each 0x12 and inactive masks, which hold stale
  memory such as "pr_lp_rup..." strings; curve floats within 8 ULP), 19 re-exported for Summer
  (more tracks, channel quantisation flag 0x10 -> 0x50 with the blob re-laid, one skeleton with
  an extra joint so its u16 map grows). All 68 walk as w7, and via `to_live` (EchoPorting
  conv_animset on the result) as live.
- **Her set** (493ad5c876c84fae, 11336 B): 5 records, each a single clip, no masks; 2019 8792 B,
  live 8512 B, both walk to EOF. Live scene key 0x6b365c52261456fb = root key of her converted
  skeleton under both names (out/her_assets/46adff5980245670, Summer-only skeleton so the Win7
  key stays). Written to `out/her_assets/e9e7d2e25d8e2252/` as 493ad5c876c84fae and
  4ab3ff017a2ce803; each copy's clips carry its own file name (Summer sets name only themselves
  in 66/68 files), so the two differ in 40 bytes. Elements still name skeleton 493ad5c876c84fae.
  Not tried in game yet.


### S19. Satellite.dll: her behaviour as a plugin (2026-10-17, user chose plugin over re-targeting)
`plugin/satellite.cpp`, `build_satellite_plugin.bat` -> out/plugin/Satellite.dll, deployed to
<game>in\win10\plugins (EchoCombat's dbgcore loader). Log: <game>\_local\echoCombatBetaLogsSatellite.log. Steers only where her physics is decided (`-server` / `-offline`); net physics
replicates her to clients. build_satellite writes plugins\Satellite.ini (her actor index, build
position). Engine facts (live 631547; ReVault project `echovr`, client EchoPorting tools/rv.py, read-only):
- Game space +420h: {component NAME symbol (ncaTransform, ncaPhysics, R14NetPhysics...), system}
  pairs, count +450h; space +58h = its level hash. CSymbol64 type names (R15NetDamageable) are
  not what the lobby spaces hold.
- Runtime actor id (SActor) = packed (0xffffffff << 16) | actor-data index; SActorGUID = {level
  hash, SActor} (CncaGame::ActorNodeID, libr15 0x17f9614). Component lookup: system virtual
  +1B0h (cs, &out, {SActor, component name}); +1A8h (cs, &out, SActor, -1) any name; +1E0h
  handle -> SActor. Result index 0xffff = none. CTransformCS: slots +C8h (u16 slot, u16 gen),
  records +F8h stride 0x118, world pose +E8h; CTransformCS::get 0x3c4470.
- Her: actor index 659 (+1 = the port), identified by position = her build position (another
  level's actor 659 is elsewhere). Velocity: CPhysicsCS 0x469cb0 through the deferred queue
  (space+170h, 0x198c40), as DroneFix.
- Tick: CR15NetGame::Update 0x1bf610 (EchoXR-Hands' hook), net game pointer.
- Players: CR15NetGame slots (u16 at +138h + s*4 value, +13Ah gen; occupied when
  ng+s*250h+3C0h != 0). Per-player state record at ng + 63FD8h + value*74h, which the engine's
  R15NetPlayerByUserIdExpression (echovr 0x140d9ea40) copies to its outputs (+4); output names
  -> offsets in BindReplicatedVars (0x140e01140). MEASURED in game (user moving): head position at
  record +1Ch, velocity at +40h, a unit vector at +34h; +5Ch = the spawn point the player was placed
  at. (+18h made her copy the player's x as her height.)
- Dead ends: R15EchoUnit system in the global space = pooled templates (identity poses); the
  player actor has no ncaTransform; hooking every CTransformCS::get to tick (thrashed spaces).
- User wants: she follows the player using her Christmas thruster logic (seamless), and the
  Christmas tracking: thrown -> turns round, stares at you, launches a snowball.

### S20. Movement (user: "perfect") and thruster jets (2026-10-17)
- Movement in Satellite.dll: FOLLOW / TUMBLE / STARE. Thrust-limited velocity (THRUST 4 m/s^2)
  toward a spot 1.5 m from the nearest player; faces them with angular velocity
  (CPhysicsCS::SetLocalAngularVelocity 0x467be0, rigid kind only). Her velocity = position delta
  over a QPC dt (body +C8h read was frame-dependent: false pushes). Pushed when |v - sent| > 1.5;
  tumble lasts while per-tick change > 0.6 m/s, +1 s; then brake + stare 1.5 s; "snowball goes here".
- Jets, level side (`build_satellite.py add_thrusters`, on by default, `--no-thrusters`): her 8
  2018 CParticleCRWin7 rows (176 B; name ff87929015f5d761..68, effect 1536f4115b2ea1b7 +32,
  joint +56, scale 0.1 +96) as live CParticleEffectCR rows (152 B), stamped from the donor's own
  particle row: effect +32, joint +48, attach word +56 = 0x01000002 (live rows with a joint:
  0x01000002 / 0x01000003 / 0x01010002; none: 0x01000000 or 0), offset +60, euler +72, scale +84.
  The donor's particle membership in the actor data already covers her. Effect + 2 textures
  ported (port_assets.py EXTRA_TYPES: particle effect / graph / RawTexturePackfile Win7); graph
  ac2ec0cdb1b6c8f2 is already in live. Loads with no missing resources (fill_packfiles: 0).
- Jets, engine side: CParticleCS::SetEmissionRateScale 0x4676c0 (cs, handle, float): slots +C8h,
  records +F8h stride 0x18, effect = record +10h, sets parameter 0x3d948699e7eb3e77
  ("emissionratescale") via 0x5c8640 (libr15 twin 0x1661e2c). ParticleSetEmissionRateScaleNode
  (0x14109b800) calls it through the FLOAT deferred queue 0x919840 (queue = cs+80h -> +170h,
  sys, fn, handle, float). The particle system is NOT keyed by row names in the space table:
  key b27851aa3111fc34 (vtable rva 1711ba8); the plugin scans the systems for the one whose
  +1B0h lookup knows her first jet, then {her SActor, jet name} gives each handle.
- Jet layout: her skeleton's thruster joints 41d2cd380e1c57xx sit on the cube corners
  (+-0.057 m, parent bone at her centre). Rate per jet = 0.08 idle + push x max(0, -corner . thrust
  dir) + 0.35 x turn share, from her measured acceleration (low-pass 0.15 s, > 25 m/s^2 = a hit,
  ignored). Runs on every machine (particles aren't networked), so her ownership doesn't matter;
  Note() now also accepts her away from her build spot when she has her jets (clients).
- **Why they were invisible (fixed, user-confirmed "the jets are showing"):** particle components
  load DISABLED (category 1 in the per-slot mask at cs+E0h; enabled slots packed first, count
  u16 cs+F4h) and InitParticleCI clears every emitter's run bit (0x40 at emitter +58h; emitters
  at effect +38h, stride 70h, count +40h). In live a script enables them. The plugin calls
  CParticleCS virtual +200h EnableComponent (0x433f40, (cs, handle, categories)), and since the
  lobby's particle system has cs+ACh = 1 (EnableComponent then skips the callback), it also calls
  +50h OnComponentEnabled (0x44af80: run bit on, restart, register) itself. On PC +58h is
  OnComponentDisabled (libr15's vtable differs). Checked again every second.
  Dead ends on the way: bigger scale (--jet-scale), a live effect (--jet-effect f41851241fc581d1),
  no joint (--jet-nojoint): all invisible while disabled. Those flags stay as test switches;
  Satellite.ini `jets_test=1` holds every jet at full (build_satellite keeps extra ini keys).
- Emission scale alone never quietens her effect (user: all 8 always showing at 0.08), so each
  jet is switched: lit when its share (push x facing + turn) > 0.15, out below 0.07, by calling
  OnComponentEnabled (+50h) / OnComponentDisabled (+58h, 0x44ac80) directly; the emission
  scale (min 0.35) only sets strength while lit. Log line shows `running` bits per jet.
- Not confirmed by eye yet: which way each effect's exhaust points (the joint orientations decide
  it; the corner model assumes outward). If they fire on the wrong side, flip the sign in
  UpdateJets (`facing`).

### S21. Snowballs (2026-10-17, in progress)
- Mesh: 2018 snowballs are CGDynamicInstanceResource (Win7 485e2b116301fd47 + GPU c5bfea0b576cf941),
  a type live dropped; in 2019 it became CGInstancedModelResource (54 of the 2018 build's 73 are
  Summer twins by name). `tools/conv_instmodel18.py`: 2018 packed stream (u32 count + rows per
  table) -> Summer rad56 tables; rules: mesh +76 |= 0x08; rp +76 bit 15 -> bit 13; vb: texcoords
  padded to index 3 (copies of tc0) after the last real one, format-1 usage-4 pair gets indices
  1/0 (lone one + a copy) and their 4-byte fields swap in every vertex (GPU); LOD u16/u16 ->
  u32/u32; trailer word 0 = mesh count; shader sets via a twin map. 51/54 twins: 16 exact, 35
  differ only in a texcoord-4 field Summer baked later (zeros in 2018); 3 are re-exports. Then
  EchoPorting conv_instmodel -> live. Snowball meshes 9b6b4f26cec5f353 (+84675c2d.., 49e4b565..),
  material 366f58585802311d, 3 shader sets ported (port_assets) into out/snow_assets.
- Actors: `--snowballs 6` clones live grabbable ball b2791092fa9cdc6d (instanced mesh
  addb85401ec90c6b, r 0.041 m) per snowball (echomod clone_instancemodel_cr + every other row),
  swaps the 72-B full entries' mesh (+32), parks them at SNOW_PARK; indices 661.. -> ini
  snow_first / snow_count. First try drew the donor ball: instanced models only load if the level's
  CArchiveResource (2a41cf1c1d9e5d32, (type, name) pairs) names them -> lone_echo_blender
  evr_level_grow.add_manifest_entries for every snow asset. Adding the mesh to CInstanceModelCR
  array 2 (signed-sorted set of the rows' meshes, 54/54) broke the load ("offset past the end of the
  stream", runtime type 6df512c53b124e38) because it rewrote the set in place. Properly: array 2
  is stored at its COUNT (54 x 8 B) and array 3 (u16 per row) is each row's slot in it (the engine
  binds meshes by slot, not by the full entry's hash; libr15 InitInstanceModelCI takes resources
  sequentially from cs+4C8h). `set_instance_mesh` grows the set, shifts slots, points the rows:
  231/231 consistent, but the level then failed with "Instance model (0x80011E8D2E3D410E) not
  found on actor" x23 and a fatal "LOD Region Target CS ... more than 2 status change callbacks".
  **User decision: keep the live ball's look.** The mesh swap is now opt-in (`--snow-mesh`, still
  broken as above); default build = 6 balls, no snow assets, level loads.
- Plugin: grab = R14TouchInteract (system key = row name 2e40131422f7b1fc) record +F8h stride 2A8h,
  grab counts +188h/+18Ch (RemoveAllGrabOffsets 0x14075ceb0); her handle shows up a moment after
  she does (retried). Thrown = released > 1 m/s; headbutt = pushed with the nearest head < 0.45 m
  (tested: 0.30 m logged as headbutt). Revenge only for those two: stare at the culprit's slot,
  then ThrowSnowball: WorldTeleport (0x100db0) a pool ball 0.22 m in front of her, velocity
  7 m/s with lead (head velocity +40h) on the next two ticks, back to the pile after 12 s.
  Satellite.ini snow_test=1 throws every 8 s (verified the throw path).
- Stuck stare fixed (user: "sometimes she just stays stationary"): the stare only ended when
  aimed within 10 deg; a moving player kept her just outside it (a 20 s stare, braking). Now 20 deg
  after 1.5 s, or 3 s at most, then the throw.

### S22. Her local AI: hears you, remembers, obeys (2026-10-17, user: "understands me much better")
- `ai/satellite_ai.py` (own folder; tools/dis.py used to shadow stdlib `dis`, now renamed tools/disasm.py), started by
  `run_satellite_ai.ps1` (opens fine in its own console; the app's terminal panel cancels it).
  Everything in H:\SatelliteAI: venv (faster-whisper, kokoro-onnx, piper-tts, pyaudio), Ollama
  v0.40.5 standalone zip (no installer/autostart; `serve` started by the script, models in
  H:\SatelliteAI\models, BELOW_NORMAL priority), qwen3:4b, Whisper base.en, Kokoro int8 + voices,
  config.json, memory.json (facts, events, turns, places), satellite_ai.log.
- Pipeline: mic 16 kHz, level VAD with a 0.3 s pre-roll (without it word onsets were lost: "throw"
  -> "for") and 0.5 s end silence -> Whisper base.en CPU (0.8 s / 3 s clip; small.en 2.7 s), primed
  with her phrases + hotword -> wake word (her name + Whisper's spellings: QB, Jeeby, ...) or an
  8 s follow-up window -> (a) places: "remember this spot as X" / "go to X" (player position from
  the plugin's state line), (b) instant orders by regex (follow/come/stay/home/spawn/spin/throw/
  ball) with pre-rendered stock lines, ~0.5 s, (c) else Qwen3 4B on the CPU (num_gpu 0, 4 threads,
  JSON schema do/place/say/remember, streamed so orders go out when "do" closes), ~6-9 s.
  Kokoro af_heart speaks; the mic is muted while she talks (she heard herself before).
- The player's name: config player_name, else the newest real "displayname" in each game log
  folder (skips "demo" offline and the server placeholder "AccountName") -> he_is_the_cat.
- Satellite.dll orders: UDP 127.0.0.1:47321 (follow, come, stay, look, home, goto x y z, spin ->
  back to the previous order, throw, status); events to :47322 (grabbed, released, headbutt,
  bumped, threw snowball, arrived, state every 2 s). Opened only with authority.
- Performance: everything on the GPU (model + Whisper) took VRAM to 7.6/8 GB and tanked the game;
  all on the CPU at low priority it doesn't. `gpu_layers` in config offloads part of the model.


### S23. Her voice in game, instant library, reactions (2026-10-17)
- **Her speaker** (Satellite.dll, EchoVRMusic's route, its docs/REVERSING.md, same 35,397,120 B exe):
  hook the exported Wwise `RenderAudio`; there, register game object 0x5341544C49544531 ("Satellite"),
  PostEvent Echo's voice-chat event 0xf5b8b08d (Audio Input source) on it, and register our delegate
  with Echo's CAudioInputCallbackRegistry (global +20A2FE0h, vtable slot 6 Register(reg, playing id,
  {a, b, fn(del, int16*, maxFrames)}, {24000, 16, 0, 0}), slot 7 Unregister; check bytes at +205466h).
  SetPosition(obj, {front, top, her position}) every frame: Echo's own 3D audio places her voice.
  PCM in: UDP 127.0.0.1:47323, raw int16 mono 24 kHz ("flush" clears), a receiver thread into a 20 s
  ring; the delegate plays after a 120 ms prebuffer and gives silence otherwise (the voice stays live).
  Satellite.ini voice_gain (default 1.6). The state line now ends speaker=0|1. Off when her level goes.
- **AI** (ai/satellite_ai.py): Voice streams to the speaker when the state line says speaker=1
  (config voice_out auto|game|local), 0.1 s datagrams 0.4 s ahead of real time; else local output.
  Rendered lines are cached on disk (H:\SatelliteAIoicecache, sha1 of voice|speed|text) and every
  stock line is rendered at start (`--warm` renders them all and exits); long lines are spoken sentence
  by sentence (the next renders while one plays).
- **Instant library** (ai/library.py + ai/library/*.json, edit freely): knowledge.json (Echo VR, Arena,
  Combat, lobby, community, Lone Echo, Lone Echo II, her own story; sourced from Echopedia
  echopedia.ntsfranz.com, Wikipedia, Meta's Echo Combat post, press), smalltalk.json, reactions.json.
  Order in handle(): places -> compliment/insult small talk -> memory (call me / my favorite X is /
  remember that / I like / I hate / forget / what's my name / what do you remember / do you remember /
  how many times / what did we do today / places) -> instant orders -> small talk -> knowledge
  (scored, exact question wins, else margin 1.15) -> Qwen with the top 3 entries as "Echo notes".
- memory.json gains "profile" {nickname, likes, dislikes, favorites, notes}; old "likes X" facts
  carried over. She calls you by the nickname if you gave one.
- **Reactions**: events -> lines (bumped, grabbed, thrown = released ... thrown, released, headbutt,
  threw snowball (revenge)); first / again / lots by today's count; 3 s cooldown; "be quiet" mutes
  them for 2 min.
- **User rules**: never emoji or symbols (say_clean on everything she says, plus the prompt), never
  the word "coming" (-> "on my way"); facts from the web, not the extracted game folders.
- Knowledge grown to 116 entries (Lobby 2.0 / patch 9, Quest open beta May 5 2020 + cross-play + Rift
  3v3 -> 4v4, patch 25 bots, Echo Pass season dates, Combat launch details, ESL VR League, champions,
  fastest jousts, servers, launch options, Spark, full Lone Echo plot and ending, Atlas, biomass,
  Apollo). Merge more with a script like the one used (same id = replaced).
- **Speed (user: 59 s model reply):** Kokoro on all cores (my `--warm` job plus the AI's own warm
  thread) starved Qwen and Whisper. Now Kokoro has its own ONNX session at 2 threads (config
  voice_threads), only short lines are warmed at start (knowledge answers voice on first use, then
  cached), warming pauses while she hears / thinks / speaks, the prompt is back to num_ctx 2048 and
  only gets Echo notes scoring > 8. Measured with the CPU quiet: 7.8 s per model reply (as before),
  instant paths ~0 s plus Whisper. Don't run `--warm` while the AI is running.

### S24. Endless spins, flips, a meaner Cubie who shoves you and shuts you down (2026-10-17)
- **Snowball pile under the map:** park at (0.6, -40, 0.6) (`g_snow_park`, build_satellite `SNOW_PARK`).
- **Orders** (plugin, UDP 47321): `spin [n|keep]`, `flip front|back|left|right [n|keep]`, `stop`,
  `push [m/s]`, `shutdown`. A flip turns about her own X (front +X, back -X) or Z (rolls) at 7 rad/s;
  `keep` runs until `stop` / another order, sending `event dizzy t=N spin|flip` every 5 s; a spin of
  8 s or more ends with `event stopped spinning t=N` and a 3.5 s dizzy wobble. Verified in game.
- **Player control** (libr15 names, PC addresses found by pattern): the player's CR15PlayerNavCS
  (vtable rva 0x1c439d0, records stride 0x890; +0x20 flags, +0x28/+0x30 its echo unit) is found by
  matching the unit's head (+0x40) to the net game player's head. Push = `CR15PlayerNavCS::SetVelocity`
  rva 0x74adb0 (cs, handle, &v), the engine's ForcePushPlayer. Shutdown = `CR15PlayerNavCS::KillPlayer`
  rva 0x747500 (cs, handle, damage type, limb, CSymbol64; "You have died from %s to the %s."), what kill
  volumes call (CR15KillVolCS::OnEnter, mode 0), the thrusters tutorial's shutdown: the unit dies and
  respawns. NOT CR15NetDamageableCS (that's Combat). Both go through the deferred queue (KillPlayer
  via a trampoline the queue calls as fn(cs, handle, &vec3)). Not yet confirmed in game.
  First try faulted: the nav pool is tiny (u16 at system +0xF0 = 2 offline) and the echo unit's +0x40
  "head" is body-local (0.22 0.19 0.25), so matching by world head never worked. Now: nav record +0x00
  (u16) = player number (record 0 = player 0, flags 0x2200 live; record 1 flags 0x200, idle).
- **Her voice** was too loud and sounded offset: voice_gain 1.6 -> 0.8, plus EchoVRMusic's distance
  fade (full within voice_full 1.5 m, quadratic to 0 at voice_cutoff 20 m; Echo's own fade is far too
  gentle). Logs her position vs the Wwise listener every 5 s to chase the offset.
- **She answered everything:** every reply re-opened the 8 s no-name window, so she chained replies to
  you talking to someone else. Now only a reply to her name opens it, once, for lines up to 10 words;
  stock Echo facts answer only questions ("Hit." got the stun tip); model told never to swear, to say
  "Huh?" to nonsense, repeat_penalty 1.3. "throw me" = push (not a snowball).
- **Push works in game** (user: "only throwing worked"). **Shutdown doesn't:** nav flag 0x100 is
  "dying" (CR15IsPlayerDyingExpression) and is already set on the lobby player (0x2300), so KillPlayer
  returns at once. And KillPlayer only records the death (UpdateDeathRecord) and fires actor event
  0x737c2e93dbbead32; the shutdown visuals and respawn are the tutorial LEVEL SCRIPT reacting to it,
  which the lobby doesn't have. Options: port that script into mpl_lobby_b2_sat, or fake it in the
  plugin (clear 0x100, kill, then respawn at spawn ourselves).
  **Correction:** kill volumes live in mpl_tutorial_micro_thrusters / mpl_tutorial_boost (CR15KillVolCR),
  but the scripts that react to the kill event (05b80f10f89a8dc0, 92481bf498600a78, b73ba2391c2b58a9,
  b9aee8d7a6daf176, facee79ce06a067c: ReVault code search for 737c2e93dbbead32) are in the GLOBAL
  levels r14_glb_global_mp / r14_glb_global_tutorial, and r14_glb_global_mp loads with the lobby. So
  nothing to port: the plugin clears 0x180 in the queued call right before KillPlayer and logs the
  flags at 0.5/2/5/10 s. Tutorial levels unpacked to out/tutorial_micro, out/tutorial_movement.
  First real kill (reason 0 "creep"): game log "You have died from creep to the entire body.", but
  nothing visible. KillPlayer(cs, h, r8 = REASON, r9 = body part, sym); the player script
  25b9f751143a5dd0 (r14_glb_global_mp) has R15DeathReasonSwitchNode and calls ImpactDeath
  (7df05c1589e59f16: fullscreen exposure/tint, disable movement, particles, event_global_death_reset)
  / CrushDeath (7fda28908f2c0ca8). Reason / part names read from the running game (tables at rva
  0x20c81b0 / 0x20c8280). Micro thrusters red walls = CR15KillVolCR rows (-1.0, mode 0, reason 6
  laser, part 4 entire body). Plugin now passes 6 / 4. Not yet tested.
  Laser tried: "You have died from laser to the entire body." then "FunctionCall could not find
  actor / component" (script 25b9, node 118a6abd, Actor Player, Component 90259bcb96ac1e88, Function
  356a113a15c7bba4 = LaserDeath in 0857cf65a1af60b8). CScriptCR rows (comp, actor, flags, script):
  r14_glb_global_tutorial's player c6b1c21fbda1d334 has LaserDeath under 9025... (flags 0) AND c59c...;
  r14_glb_global_mp's players dfb4e911bdaddc39 / f1e70acd0dde0312 only under c59c... (flags 1), plus
  ImpactDeath (c5cb02587476de17) and CrushDeath (c29e5b0b26218947). Not editing the stock global
  level: default reason now 4 (impact); "shutdown N" orders reason N for testing.
  Impact tested 15:55: same failure, component 4c6c8c218c97b7e6 (function d9dc3b4b335bcac6
  ImpactDeath). So the lobby's player never had death scripts under the switch's names. Fix: hook
  echovr 0x168340 (find script component by name: out {sys, u16 index}, space, actor, name; called by
  every SScriptBindings::ExternalFunction*, libr15 ComponentHandle<CScriptCS> 0x25f7c40 ->
  0x1291c2c): a failed find of 4c6c... / 9025... retries with c5cb... / c59c.... Default back to laser.
  Open question: those lobby rows carry flags 1 (tutorial's duplicate row has 1 too, the used one 0):
  if 1 = disabled, the found component may still fail the enabled check.
  Tested 15:59: "LaserDeath: component 9025 -> lobby's c59c on actor ...003e: found"; LaserDeath runs
  (3x "CSetAnimationRealChannelNode has invalid channel ID" 0x232FC0519B0386FC on rig e53a35d2892e5d89:
  the burn effect's channel isn't on the lobby chassis rig); flags 2302 -> 2300 -> 200 by +5 s; a
  dialogue 0x6B7FCE33ED1C7DE2 starts at +4 s then aborts, and 25b9 node a74a88a5 "can't find
  actor/component". **User: "it worked"** (the real tutorial laser shutdown + respawn, in the lobby).

### S25. Shipped into the real mpl_lobby_b2 + the VR install (2026-10-17)
- `build_satellite.py --name mpl_lobby_b2 --base H:\Tools\Tools\Settings\input-pcvr --her-model
  --with-port --at 0 2.3 0`: in place (no clone/rename); each lobby resource from the first --base
  that has it (the user's input-pcvr already had a MODIFIED lobby: actor data, transforms, statics,
  physics, BVH...), else stock. Her index 659, port 660, snowballs 661-666 (same as the _sat build).
- Staged into H:\Tools\Tools\Settings\input-pcvr (user: "just stage it"): 199 new files, 5 lobby files
  replaced (originals in out/input_pcvr_backup_20261017_160655), 0 clashes. Not packaged by me.
- VR install C:\Oculus\Games\Software\Software\ready-at-dawn-echo-arena\bin\win10\plugins:
  Satellite.dll + Satellite.ini (index 659, snow 661/6, ai=<run_satellite_ai.ps1>, local=1).
- The user plays PUBLIC echovrce.com lobbies (no args, not -offline): the servers don't have her, her
  body is simulated only on the client. First run: "not authority: idle" = lifeless. **local=1** steers
  her on the client and makes "the player" YOU: the net-game slot whose head is at the Wwise listener
  (g_ear, X un-mirrored, within 1.5 m), not the nearest player; orders port opens too.
- AI auto-start: Satellite.ini ai= -> the plugin starts it in its own console 3 s after load unless
  port 47322 is taken, with --with-echo <pid>; the AI exits when that game exits (WaitForSingleObject)
  and ignores the mic unless the plugin's state line is < 6 s old (= she's loaded and steered).
  Verified 16:10: started, "not in her lobby: doing nothing", "game 15700 closed: closing".
- User: local mode works (she follows) but no push / shutdown online. Online you are net-game slot 1
  but nav record 0: the nav "player number" is per client. Push and kill hit record 1 (actor
  f1e70acd0dde0312, no death components -> "FunctionCall could not find"). Nav player rows (system
  +B8h -> rows stride D0h): +08h = level node (dfb4e911bdaddc39 = local player in r14_glb_global_mp,
  f1e70acd0dde0312 = the other), +10h = runtime actor (...003e / ...003f). Local mode now uses the
  dfb4 record (fallback record 0). Deployed to the VR install 16:15; not yet tested online.
- **Speaker offset found:** Wwise X is mirrored from the game's (head -7.05 4.96 5.22 = listener
  7.05 4.96 5.22). Her voice now goes to (-x, y, z).
- **Prompt (user's rule):** describe the world and the satellite in third person, then "Roleplay as
  the satellite." Never "You are a ...".
- Shell heredocs put literal backspace chars (\x08) where `\b` was meant: library.py's Lone Echo II
  rule was broken since S23. Write Python patch files with the Write tool, not bash heredocs.
- **AI:** `move_instant` (keep spinning / keep going until I say so / front, back flips / barrel roll /
  stop / push me [hard] / shut me down), dizzy lines by seconds spun, anger 0-10 (bump +1, grab +0.7,
  throw +2, headbutt +3, insult +2.5, sorry -3, cools 1 per 20 s): from `push_anger` 5 she shoves you,
  at `shutdown_anger` 8.5 she shuts your unit down (then calms to 3). Meaner lines in reactions.json
  (+ dizzy, stopped spinning, angry/asked push/shutdown) and smalltalk.json; meaner model prompt with
  her anger in context. `--view` now launches in VR (user: never -windowed).

### S26. No live model: everything cached; her real 2017 voice (2026-10-17)
- **User: "remove the local running ai and have everything cached".** ai/satellite_ai.py no longer
  starts Ollama or calls a model (ask_model / SCHEMA / system_prompt / ensure_ollama / pull_model
  removed). Order in handle(): places, small talk (compliment / insult), memory, moves, instant
  orders, small talk, knowledge (questions), then the **chat bank** (library.chat), else config
  "unknown" = "Sorry i dont quite know that one yet", and the line goes to H:\SatelliteAI\unknown.txt
  (what to add next). H:\SatelliteAI\ollama + models (~5 GB) are now unused (not deleted).
- **Chat bank**: ai/library/chat_*.py (her, you, echo, fun, original) -> `make_chat.py` -> chat.json
  (196 entries, 850 phrasings, 777 replies; optional "do" order). library.chat(): per example
  0.55 x difflib ratio + 0.45 x word Jaccard (+0.1 if every content word said), fillers stripped
  ("really", "so", "today", ...), threshold 0.65, margin 0.03 (or 0.85+). Tested 30/30 asks hit,
  10/10 off-topic lines miss. Everything answers in ~0.03 s plus Whisper.
- **Her real voice**: Dec 2017 build, mpl_lobby_a_xmas (0xE7ACD884163B00A3) archive -> 3 Wwise banks;
  bank 7ccf82aba6bc50a2 has 97 embedded clips, ~51 of them her speaking (decoded with
  H:\Tools\Tools\Settings\vgstream\vgmstream-cli.exe, transcribed with Whisper). 39 clean clips,
  67.6 s, 31 lines -> out/xmas2017/vo/dataset (+ metadata.json). Re-extract with tools/xmas_list.py
  with the isolated Oodle (tools/dis.py, which shadowed stdlib dis, is now tools/disasm.py).
- `ai/library/add_recordings.py`: clips -> ai/library/recordings/*.pcm (24 kHz int16) +
  recordings.json; her lines placed into reactions (grabbed "Hey, I'm not a snow globe.", threw
  snowball "Think fast." / "I'll just leave this here.", ...) and small talk (hello, compliment, joke,
  christmas, ...). Voice plays the real clip whenever a sentence is one of them (random take).
- **Clone**: F5-TTS v1 Base fine-tuned on those 39 clips (voiceclone venv, Lib/data/cubie_pinyin,
  ckpts Lib/ckpts/cubie, --bnb_optimizer: without it, desktop apps' VRAM made it thrash at 56 s/update;
  with a free GPU ~1.2 s/update, 5 updates/epoch, 300 epochs). `ai/render_f5.py --test` renders
  samples per checkpoint (H:\SatelliteAI\f5_test); then `satellite_ai.py --list-lines
  H:\SatelliteAI\lines.txt` (1157 lines) and `render_f5.py --ckpt model_N.pt` fills the voice cache
  under voice "cubie_f5" (key sha1("cubie_f5|<voice_speed>|text")). Config "voice": "cubie_f5" then;
  lines missing from it are spoken by Kokoro "fallback_voice" (af_heart), cached under Kokoro's key,
  and listed in voicecache/missing_cubie_f5.txt for the next batch.
- Voice samples: ai/voice_tour.py (28 Kokoro voices), ai/voice_mix.py (blends + pitch / ring / radio).
- **Her name is now Edith** (user, 2026-10-17; was Cubie): config name, wake words edith / edit / edyth /
  edeth / eadith / eddith / editha / edie / eadie / satellite; name-stripping patterns accept both;
  chat entry why_edith ("I used to be Cubie. I upgraded."). Internal ids keep cubie (cubie_f5 voice,
  recordings cubie_*.pcm, Lib/ckpts/cubie). A strong chat match (0.85+) now beats knowledge answers.
- Clone training paused at update 800 by the user (too long); last saved model_600.pt / model_last.pt;
  resuming the same command continues from 600 (~900 updates, ~50 min).

## Next

0. User checks the jets in game (direction, strength; JET_IDLE / spin share to taste).
1. Snowballs: a pool of 2018 snowball actors (S6, 18 of them), thrown with lead from the
   player's velocity (state record +40h). **User rule (2026-10-17): she throws ONLY after being
   grabbed and thrown, or hit by a player's head (head collision).** Any other push (a hand
   slap, a bump into a wall or prop) means tumble + stare, no snowball. So the tumble needs its
   cause: thrown = she was held (her touch-interact / net grab state, or her velocity following a
   hand for several ticks) and then released; head hit = at the moment of the push a player's head
   (state record +1Ch) was within ~0.4 m of her and moving toward her. Throw at the player who did
   it, at the end of the stare.
2. Waypoint route (40 waypoints, their CScriptCRWin7 settings) when no one is near.
3. I/O port glow / snapshot; animations in game (S18 converted, unconfirmed); voice (2017 build).

## Wrong turns

- Loading the 2017 build's Oodle in place (see Rules): EchoRelay popups.
- "2018 scripts can run in live as is" from matching `setup_bindings` slots: wrong, the
  runtime structs they touch changed (S4).
- lone_echo_blender's `evr_actor_table` on 2018 actor data: `bad CBitMap image @0x208`.

## Status

- 2026-10-17: phase 0 started. Her parts named (S1), both Christmas lobbies unpacked (S2, S3),
  script carry-over checked (S4). Next: the 2018 level diff and her script rules.
- 2026-10-17 (later): 2018 diff done (S6), her actors and behaviour mapped from her scripts'
  symbols (S7, `docs/satellite_rules.md`). Port route question for the user (S8). Next: script
  settings in the level, then the user's choice.
- 2026-10-17 (evening): she flies in live mpl_lobby_b2 as a new actor with her own model, port,
  collision and grab; follows / tumbles / stares (user: perfect). Thruster jets in (S20): visible
  once the plugin enables them; now thrust-driven. Direction / strength feel not yet judged.

### S27. Mood faces on her I/O port (2026-10-18)
- The 2017/2018 port glass has one face. The user's CubeSat face sheet (24 faces) -> out/cubesat_faces
  (face_NN.png, white on black at her face's spot: x 34..315, y 83..236 of the 512 glass texture).
  Picks: happy = her own port, angry 17, dizzy 14, surprised 13, hurt 16, annoyed 7.
- `tools/make_port_faces.py` -> out/face_assets: per mood a copy of the port model 8e23e03db27c66b9
  (all 13 resource types, renamed), its glass CGShaderSetResource 8348d8fe307ef54f (names the
  texture) and glass texture 3bfeb8c3e1d718a3 (BC1 sRGB 512, 10 mips: top two = RawTexturePackfile
  chunks named at low +40h, the other 8 after the DDS header at +194h; encoded with Settings\ms_texconv).
- `build_satellite.py --port-faces`: 5 more port actors in the same seat (indices 667-671, after the
  snowballs); Satellite.ini face_first=667 face_count=5.
- Satellite.dll: CModelCS (vtable rva 1716710) +58h OnComponentDisabled = model visibility mask 0,
  +50h OnComponentEnabled = its own mask back (+200h/+208h Enable/DisableComponent are the generic
  pair). One port shown, re-asserted each second. Order `face <happy|angry|dizzy|surprised|hurt|annoyed> [s]`.
  The AI: grab surprised, throw hurt, headbutt / spin dizzy, bump / insult annoyed, push / shutdown /
  4th+ attack angry, then happy again.
- Clean in-place base: out/lobby_base = input-pcvr minus my staging (backup, else files without my
  actors' ids, else stock); without --port-faces it rebuilds the installed lobby byte for byte.
  Staged 95 new + 7 replaced into input-pcvr (originals out/input_pcvr_backup_20261018_075807).

### S28. Her voice: HERA (2026-10-18, user: "i like it right now, can we consider this done")
- config "voice": "hera_f5" (fallback af_heart). ai/render_f5.py VOICES["hera_f5"]: EchoCombat's announcer F5
  fine-tune (voiceclone ckpts/hra/model_1200, vocab hra_pinyin) + HERA's tutorial line as reference
  (voiceclone/hera_ref_pad.wav from J:\EchoAudio\vo_2d__bus_1174689782__vo68\1143053249_133210734.wav), pace 0.8,
  slight robot filter (ring 0.12 @ 70 Hz + 5 ms comb 0.3), one-word sentences rendered alone (F5 swallowed them),
  short sentence breaks widened 0.25 s (not after ! / ?), SEED_FOR per-line takes. No time-stretching (robotic).
- KEPT AS A MIX (user: "keep it as it is now"): ~480 lines HERA, the rest af_heart; config grow_voice=false stops
  the after-game render. Her 2017 recordings only play with cubie_f5 (config recordings_for). Missing lines queue in
  voicecache/missing_hera_f5.txt; grow_voice renders them after the game closes.
- Intro: "I'm Edith, the new AI for the Echo Construct." Asking to be killed / shut down only gets a shove.
- Athena's intro line ("I'm Athena, Central AI for the Echo Construct") is vo_spatial__bus_1135589620__vo382\3538734084_133992937.wav.

### S29. Her lobby data as a .edith package, no repack (2026-10-18, tested on the H: install)
- `tools/make_edith_pack.py`: the stock-based build (out/build/mpl_lobby_b2, only files that differ
  from H:\pcvr-extracted) packed with the map editor's rad_archive_tool into manifests/<H> +
  packages/<H>_0 (H = CSymbol64("e.d.i.t.h_mpl_lobby_b2") = fee6c3689f3bc364), bundled as one
  out/E.D.I.T.H/mpl_lobby_b2.edith (222 resources, 5.1 MB). Install: <plugins>\Satellite\mpl_lobby_b2.edith.
- `plugin/edith_pack.cpp` (replaces edith_loose.cpp in the build): unpacks into <plugins>\Satellite\cache\<H>,
  redirects FileExists/FileOpen (0xE0CD0 / 0xE15E0) of manifests/<H> and packages/<H>_N there, and at
  level load (0x4FE050) calls AddManifestPackage (0xFA1680 on *0x20A2AB8). Result: stock lobby loads in
  2.4 s with her, faces, snowballs; mounted keys override the lobby's own (loose serving failed: S28 notes).
- **Conflict:** echo_editor_loader.dll loose-serves keys of installed .kfclvl maps that aren't mounted; any
  map sharing her keys feeds raw bytes into her package reads -> "zstd: Unknown frame descriptor" + crash.
  On H: mpl_lobby_b2_sat.kfclvl (her model) and mpl_lobby_b2_summer.kfclvl (CubeSat textures) did that;
  renamed to *.off-for-edith-test for the test.
- **Fixed (guard):** .edith v2 carries her (type, name) key list. After her mount, if a 5-byte jmp hook sits on
  the resource request (0xFA1FE0), edith_pack.cpp puts a guard in front of it (one aligned 8-byte write, stub
  allocated within 2 GB): her keys go to the engine's own code through a trampoline of its original first
  15 bytes (3 movs) + jmp to +15; everything else goes on to the other loader. Tested on H: with both maps back:
  lobby + Edith load, 0 zstd errors, ears started from Satellite.ini ai=run_edith_ears.ps1.
- **Renamed (user, 2026-10-18): the plugin is EDITH.dll.** Its ini and package folder follow the DLL name:
  plugins\EDITH.ini, plugins\EDITH\mpl_lobby_b2.edith (+ cache\), log _local\echoCombatBetaLogs\EDITH.log.
  build_satellite_plugin.bat builds out\plugin\EDITH.dll; build_satellite.py writes EDITH.ini. C: and H: moved
  (old Satellite.dll kept as Satellite.dll.renamed-to-EDITH.bak). C:'s .edith is built on out/lobby_base
  (the user's input-pcvr lobby, keeps their edits); H:'s on stock. Body texture edits (S29+): plate reads
  "SAT / E.D.I.T.H", the snowflake badge is the user's cat (tools/retexture.py; originals out/her_assets_backup).
