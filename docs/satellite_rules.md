# The Christmas satellite: how she works (2018 build)

Source: `Echo VR Christmas 2018`, lobby `mpl_lobby_b2_xmas` (`0x6DAA6D98D9354BA5`), compared
with the same build's `mpl_lobby_b2`. Read from the level's component tables
(`tools/level_diff.py`, `tools/find_refs.py`) and from the symbols and constants in her script
DLLs (`tools/script_vocab.py`, output `out/xmas2018/script_vocab.txt`). No PDB exists for these
scripts in either Christmas build, so this is what the scripts *name*, not a full reading of
their logic. Exact tuning values are still to come (see "Still unknown").

## Who's who in the level

Christmas adds 238 actors to `mpl_lobby_b2` (`out/xmas2018/diff.txt`). Hers:

| actor | what | components | scripts |
|---|---|---|---|
| `82fcb72c482b322f` | **her** (model `prp_itt_cube_sat_mp_xmas`) | 2 models, 2 animations, LOD, **8 particle effects** (thrusters), physics, collision, net physics, touch + net touch interact, sound, transform | `prp_itt_cube_sat_mp_script`, `prp_itt_cube_sat_mp_xmas_thruster_control`, `prp_toy_fun_xmas_present_teleportable_prop` |
| `8afc20320c9dd6df` | her **I/O port** (model `prp_itt_io_port_mp_xmas`) | 2 models, 2 animations, sound, transform | `prp_itt_io_port_mp_xmas` |
| `3b5851f3ca7dff68` | **target tracker** | transform | `tst_dsn_robby_cbt_ai_target_tracker` |
| 18 actors (e.g. `04c96cea21d8263b`) | **snowballs** | instanced model, physics, collision, dampener, net physics, touch + net touch interact, sound, transform | `fx_test_austin_multiplayer_lobby_xmas_snowball_a`, `prp_toy_fun_xmas_present_teleportable_prop` |
| 40 actors (e.g. `3d6ea5cbc17bcf6c`) | **waypoints** of her route (model `a571045e03bc6d2c`, a tiny marker mesh) | 2 models, LOD, transform | `prp_itt_cube_sat_mp_home_position_pathfinder`, plus `a01086fe232040f6` (24 of them) or `48ae7c6fb1375182` (16) |

All of them are ordinary level actors with stock components. The engine networks her and the
snowballs itself (net physics, ownership transfer, net events): nothing outside the game's own
systems is involved.

## Her (`prp_itt_cube_sat_mp_xmas_thruster_control`, the biggest script)

- **Flies with physics**: sets world velocity and angular velocity, decelerating by
  `deccel_to_velocity_ratio` / `angular_deccel_to_velocity_ratio`. `ComputeShouldThrust`,
  `ComputeTargetAngle`, `UpdateThrusters` and `ScaleThrusterEmission` drive her 8 thruster
  particle effects; `StopThrust` cuts them.
- **Players can grab and throw her**: handlers `delegate_ongrab`, `delegate_onrelease`,
  `delegate_onimpact`, `delegate_OnStrain`. Ownership moves to whoever holds her
  (`delegate_OnOwnershipTransfer`, `delegate_onownershipdeclined`) and back to the server
  afterwards (`TransferToServer`, `attempting_transfer_to_server`,
  `evt_internal_transfer_to_server_when_ready`). She adds/removes collision exclusions while held.
- **Throws snowballs**: `Snowball`, `Fire`, `ChangeTarget`, `dist_to_nearest_target_sqr`,
  `expected_impact_time` (she leads her shots), `gun_…` names, `R15NetSendEventNode`.
- **Moves along a route**: `evt_cube_sat_waypoint_reached`, `evt_cube_sat_home_position_reached`.
- **Talks**: `evt_greet_player`, `evt_compliment_customization`,
  `evt_compliment_gingerbread_man`, `evt_brawlers_den`, `evt_fireplace` (lines tied to places
  and to what players wear). The 2018 build has no voice lines; the 2017 build does.
- **Bumps**: `evt_cube_sat_net_collided`. **Photos**: `evt_io_port_perform_snapshot` (to her I/O port).
- Constants in the code: 10, 20, 30, 0.25, 0.35, 0.99, 57.2958 (radians to degrees), 1e6 (a
  "no target yet" distance), plus the usual 0.5 / 1 / 1.5 / π values every script has.

`prp_itt_cube_sat_mp_script` (the other script on her) only plays her animations
(`PlayAnimationNode`, `SetAnimationRealChannelNode`, ease in/out) and talks to her `ioport`.

**When she throws (user, 2026-10-17):** only after someone grabs and throws her, or hits her
with their head. Other bumps make her tumble and stare, without a snowball. Her 2018
handlers match: `delegate_ongrab` / `delegate_onrelease` and `delegate_onimpact`.

## Her route (`prp_itt_cube_sat_mp_home_position_pathfinder`, on 40 waypoints)

Each waypoint knows its `next_position`, an `alternate_next_position` and a
`validation_alternate_next_position`. A waypoint can require players nearby
(`requires_player_in_volume`, `player_requirement_volume`, `proximity_volume`; checks for social
users, a team or a team's user), and when the requirement fails it takes the alternate
(`volume_requirement_fail_behavior`, `validation_requirement_fail_behavior`). Other settings:
`home_position`, `is_first_waypoint`, `strafe_to_position`, `pass_through`, `skip`,
`transfer_delay`, `homing_rotation_min_dist_standard`. Events: `evt_cube_sat_waypoint_is_next`,
`evt_cube_sat_home_position_reached`. So: she tours a waypoint graph and goes where the players are.
These per-waypoint values are script settings (external script reals/flags) stored with each
waypoint, which is why the 2018 build "has the right paths".

## Snowballs (`fx_test_austin_multiplayer_lobby_xmas_snowball_a`, 18 of them)

- A pool: each has a `respawn_point`; `RespawnSnowball`, `DestroySnowball`, `manual_respawn`,
  `destroyed`, `locally_destroyed`.
- Fired by a peer event (`nevt_to_peers_snowball_fire`): world velocity plus a tumble
  (`tumble_speed`, angular velocity), collision on.
- On impact: `evt_snowball_impact`, an impact effect by size (`fx_event_impact_destroy_sm` /
  `_med` / `_lrg`), a sound, `nevt_to_server_snowball_destroyed`, then back to its respawn point
  (`evt_snowball_respawn`, `TeleportNode`).
- Players can grab them too (touch interact, net physics, ownership transfer).

## Target tracker (`tst_dsn_robby_cbt_ai_target_tracker`)

Parents itself to a player (`R15NetPlayerByUserIdExpression`, `parent_user_id`,
`parented_to_remote_player`) and keeps that player's velocity smoothed over the last 10 frames
(`linear_velocity_00`..`_09`, `smoothed_linear_velocity`, `smoothing_time`). This is what lets her
lead a moving target (`expected_impact_time`).

## I/O port (`prp_itt_io_port_mp_xmas`)

A holographic port that lights up when someone is close (`active_dist_sqr`,
`holographic_activation_*`, `housing_*` glow values) and plays a "snapshot" (`snapshot_duration`,
`evt_io_port_perform_snapshot`, broadcast scan events).

## Presents (`prp_toy_fun_xmas_present_teleportable_prop`, on her and every snowball)

Christmas presents work as two-way teleporters (`teleport_point_a/_b`, exit volumes,
`nevt_to_all_prop_teleported_a_to_b`). She and the snowballs can go through them.

## Live has what she needs

Every engine node her scripts call is in the live `echovr.exe` (checked by name:
`PhysicsSetWorldVelocityNode`, `R15NetTransferOwnershipNode`, `R15NetSendEventNode`,
`ParticleSetEmissionRateScaleNode`, `AddCollisionExclusionNode`, `R15TeleportVRNode`,
`SpawnParticleEffectNode`, `TeleportNode`, `R15NetUserInVolumeExpression`,
`R15NetPlayerByUserIdExpression`, `TransformSetParentNode`, `SetAnimationRealChannelNode`,
`ExternalScriptRealExpression`, …).

## Still unknown

- The exact numbers (her speeds, throw rate, range, snowball speed): in the script code past
  what `script_vocab.py` shows, and in each actor's script settings in the level. Next: read
  `CScriptCRWin7` rows (their parameter blocks) for her, the waypoints and the snowballs.
- What the waypoints' second scripts (`a01086fe232040f6`, `48ae7c6fb1375182`) do; their names.
- What the 2018 build's other Christmas actors are (238 new actors in all: presents, decorations,
  ambient sounds, the fireplace and gingerbread scenes she comments on).
