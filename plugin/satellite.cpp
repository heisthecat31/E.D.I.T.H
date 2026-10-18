// EDITH.dll: the Christmas satellite's behaviour in the live lobby (agent.md S19).
//
// She is a level actor with net physics (tools/build_satellite.py --her-model --with-port), so
// the engine already replicates her body to every client. This plugin only steers her where
// her physics is decided (a dedicated server, or an offline game). Like her 2018 thruster script
// she is steered with thrust, never placed: every tick she accelerates (at most THRUST m/s^2,
// from the velocity her body really has) toward a spot FOLLOW_DIST in front of the nearest player
// and turns (angular velocity) to face them, upright. A push, throw or grab that her own thrust
// didn't cause sets her tumbling free; once left alone she brakes, turns round and stares at the
// nearest player (STARE_MS), then follows again.
//
// Engine calls (live 631547, the same ones EchoCombat's plugins use):
//   +0x3c4470  CTransformCS::get (transforms, &pose, handle)         hooked: game space + tick
//   +0x469cb0  CPhysicsCS set world velocity (sys, handle, &v)       run through the deferred queue
//   +0x198c40  CDeferredMethodQueue add (queue = space+170h, sys, fn, handle, &vec3)
//   +0x1c76b0  CPlayerSlot::GetPosition (game, &out, value): the player's actor at out+8
//   game space +420h: {type symbol, component system} pairs (count +450h; bit 48 of the
//              stored symbol differs, CombatBots' FindSystem)
//   component system virtual +1B0h (cs, &out, {actor, component name}) -> instance handle
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include <string>
#include <vector>
#include <deque>
#include <mutex>
#include <thread>
#include <condition_variable>
#include "detours.h"
#include "logdir.h"
#include "edith_net.h"
#include "edith_pack.h"
#include "edith_ears.h"

namespace {

//: her runtime actor id: (0xffffffff << 16) | her actor-data index. build_satellite puts her at the
//: end of the scene actors: index 659 in mpl_lobby_b2 (agent.md S12); her node id is
//: CSymbol64("echoenh_satellite") = c907788a0be90017
//: EDITH.ini (written by tools/build_satellite.py next to the DLL) gives her index and
//: build position: [satellite] index=659 x=0 y=2.3 z=0
uint64_t HER_ACTOR = 0x0000FFFFFFFF0000ull | 659;
float g_home[3] = { 0.0f, 2.3f, 0.0f };
volatile int g_stage = 0;                                    // (diagnostic) where a tick faulted
// her speaker (see "her speaker" below): declared early, the tick and the state line use them
struct SpeakerDelegate { void *a; void *b; int64_t (*fn)(SpeakerDelegate *, int16_t *, uint16_t); };
struct Speaker { uint32_t playing = 0; bool registered = false; void *space = nullptr; SpeakerDelegate del = {}; } g_spk;
float g_her_pos[3];
volatile LONG g_her_pos_ok = 0;                                    // her position this frame is valid
//: local mode (EDITH.ini local=1): steer her on this client even without -offline / -server. For
//: public lobbies (echovrce) whose servers don't have her: her body is simulated only here.
bool g_local = false;
volatile float g_ear[3];                                           // your head (Wwise listener, game coordinates)
volatile LONG g_ear_ok = 0;
char g_net_role[8] = "off";                                  // off | alone | host | puppet (docs/networkplan.md)
char g_net_host[64] = "";
uint8_t g_net_self = 0xff;                                   // your index in the room's members (EDS1 owner)
char g_net_members[512] = "";                                // the room's members, comma separated
char g_net_ai[512] = "";                                     // those whose companion runs (comma separated)
bool g_network = true;                                       // EDITH.ini network= (the relay)
bool g_server = false;                                       // -server: a dedicated server (not -offline)
// Players by name (UpdateNet refreshes it): slot -> display name, and which slot is you.
struct SlotName { int slot; char name[64]; };
SlotName g_names[32];
int g_nnames = 0, g_own_slot = -1;
char g_me[64] = "";
//: Does this player run E.D.I.T.H? (her room members, or you). She ignores everyone else (user).
bool InRoom(const char *name) {
    if (!name || !name[0]) return false;
    if (!strcmp(name, g_me)) return true;
    size_t n = strlen(name);
    for (const char *p = g_net_members; *p;) {
        const char *e = strchr(p, ',');
        size_t len = e ? (size_t)(e - p) : strlen(p);
        if (len == n && !strncmp(p, name, n)) return true;
        if (!e) break;
        p = e + 1;
    }
    return false;
}
//: who she is about: the order's player ("follow Bob", "come" from Bob) or else her favourite (the
//: companion's "favour <name>": whoever has been nicest to her). Empty = you (local mode's rule).
char g_favour[64] = "";
//: whoever is talking to her: she turns to them for a moment, whatever their score ("lookat <s> <name>",
//: user 2026-10-18: "look at the person currently talking to her, even if they have a low score")
char g_look[64] = "";
ULONGLONG g_look_until = 0;
char g_voice_dir[MAX_PATH] = "";                                // <plugins>\EdithVoice\ (her voice pack)
int SlotOf(const char *name) {
    if (!name || !name[0]) return -1;
    for (int i = 0; i < g_nnames; ++i)
        if (!strcmp(g_names[i].name, name)) return g_names[i].slot;
    return -1;
}
const char *NameOf(int s) {
    for (int i = 0; i < g_nnames; ++i)
        if (g_names[i].slot == s) return g_names[i].name;
    return s >= 0 && s == g_own_slot ? g_me : "";
}
constexpr uint64_t NCA_TRANSFORM = 0xABFE651C8D260515ull;   // component names (CR row +0)
constexpr uint64_t NCA_PHYSICS = 0x5B8CC538E22AD937ull;
//: the game space table is keyed by component name: R14NetPhysics' system knows the net game (+B8h)
constexpr uint64_t SYM_NET_PHYSICS = 0x8fee6557f995e4a3ull;

constexpr float FOLLOW_DIST = 1.5f;      // m from the player she hovers at
constexpr float FOLLOW_ABOVE = 0.35f;    // m above the player's root
constexpr float GAIN = 1.2f;             // (m/s) per m of distance to her spot
constexpr float MAX_SPEED = 3.0f;        // m/s
constexpr DWORD TICK_MS = 33;
// Thrusters (her 2018 thruster_control works the same way: it never sets a position, it thrusts:
// ComputeShouldThrust / UpdateThrusters / PhysicsSetWorldVelocity + PhysicsSetWorldAngularVelocity,
// decelerating by deccel_to_velocity_ratio / angular_deccel_to_velocity_ratio).
constexpr float THRUST = 4.0f;           // m/s^2: how fast her thrusters change her velocity
constexpr float TURN_GAIN = 4.0f;        // (rad/s) per rad of facing error
constexpr float UPRIGHT_GAIN = 3.0f;     // (rad/s) per rad of tilt from upright
constexpr float MAX_TURN = 4.0f;         // rad/s
// Thrown: her real velocity is this far from what she set (a hit, a throw, or a hand holding her).
constexpr float THROWN_DV = 1.5f;        // m/s
constexpr float HANDLED_DV = 0.6f;       // m/s change per tick that means someone is still moving her
constexpr DWORD TUMBLE_MS = 1000;        // free tumble after the last push
constexpr DWORD STARE_MS = 1500;         // then she turns round and stares at you this long
constexpr float STARE_AIMED = 0.35f;     // rad (20 deg): facing you counts from here
constexpr DWORD STARE_MAX_MS = 3000;     // and the stare ends by then anyway (a moving player kept her
                                         // aim just outside 10 deg: one stare lasted 20 s, braked still)
// Snowballs: she throws ONLY at someone who grabbed and threw her, or headbutted her (user's
// rule); any other bump is a tumble and a stare without one.
constexpr float THROWN_SPEED = 1.0f;     // m/s: let go faster than this = thrown (slower = put down)
constexpr float HEADBUTT_DIST = 0.45f;   // m: a push with a player's head this close = a headbutt
constexpr float REACH_DIST = 1.6f;       // m: no player's head this close = nobody touched her (a wall)
constexpr float WALL_DV = 2.5f;          // m/s change in one tick while flying free = she hit something
constexpr float SNOW_SPEED = 7.0f;       // m/s
constexpr float SNOW_MUZZLE = 0.22f;     // m in front of her where the snowball appears
constexpr DWORD SNOW_BACK_MS = 12000;    // a thrown snowball goes back to the pile after this
//: R14TouchInteract: the system (game space table key) and her rows' component name are the same
//: symbol. Records +F8h stride 2A8h; grab counts per hand u32 +188h / +18Ch (both 0 = nobody holds
//: her): CR15TouchInteractCS::RemoveAllGrabOffsets, echovr 0x14075ceb0.
constexpr uint64_t SYM_TOUCH = 0x2e40131422f7b1fcull;
constexpr size_t TOUCH_STRIDE = 0x2a8, TOUCH_GRABS = 0x188;
//: CncaGame::WorldTeleport (game space, SActor, CTransfQ: quat, position, scale, reason): the
//: engine's own teleport (CombatBots uses it to move bots)
constexpr uintptr_t WORLD_TELEPORT_RVA = 0x100db0;
constexpr uint8_t WORLD_TELEPORT_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x20, 0x55, 0x56, 0x41, 0x57, 0x48, 0x83, 0xec, 0x40,
                                             0x83, 0xb9, 0x68, 0x03, 0x00, 0x00, 0x00 };
using world_teleport_fn = void(__fastcall *)(void *space, uint64_t actor, const float *xform, uint8_t reason);
world_teleport_fn WorldTeleport = nullptr;
//: her snowball pool (tools/build_satellite.py --snowballs): actor-data indices, from EDITH.ini
unsigned g_snow_first = 0, g_snow_count = 0;
bool g_snow_test = false;
float g_snow_park[3] = { 0.6f, -40.0f, 0.6f };     // the pile waits well under the lobby floor, out of sight

constexpr uintptr_t TRANSFORM_GET_RVA = 0x3c4470;
constexpr uint8_t TRANSFORM_GET_BYTES[] = { 0x40, 0x53, 0x48, 0x83, 0xec, 0x50, 0x48, 0x8b, 0x81, 0xc8, 0x00, 0x00, 0x00 };
constexpr uintptr_t SET_VELOCITY_RVA = 0x469cb0;
constexpr uint8_t SET_VELOCITY_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x08, 0x48, 0x89, 0x74, 0x24, 0x10, 0x57, 0x48, 0x83, 0xec, 0x60 };
//: CPhysicsCS::SetLocalAngularVelocity (sys, handle, &w): record = +F8h + slot*78h, body = record
//: +20h; writes body +D4h..+DCh and dirty flag body+40h |= 80h (libr15 twin; the linear velocity
//: is at body +C8h..+D0h, SetLocalVelocity 0x467d60)
constexpr uintptr_t SET_ANGULAR_RVA = 0x467be0;
constexpr uint8_t SET_ANGULAR_BYTES[] = { 0x48, 0x8b, 0x81, 0xc8, 0x00, 0x00, 0x00, 0x44, 0x0f, 0xb7, 0xca, 0x42, 0x0f, 0xb7, 0x14, 0x88 };
constexpr uintptr_t DEFER_RVA = 0x198c40;
constexpr uint8_t DEFER_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x20, 0x56, 0x41, 0x56, 0x41, 0x57, 0x48, 0x83, 0xec, 0x30 };
//: CParticleCS::SetEmissionRateScale (cs, handle, float): record = +F8h + slot*18h, effect = record
//: +10h; sets the effect's "emissionratescale" parameter (libr15 twin; ParticleSetEmissionRateScaleNode
//: 0x14109b800 runs it through the float deferred queue below)
constexpr uintptr_t SET_EMISSION_RVA = 0x4676c0;
constexpr uint8_t SET_EMISSION_BYTES[] = { 0x48, 0x8b, 0x81, 0xc8, 0x00, 0x00, 0x00, 0x44, 0x0f, 0xb7, 0xc2, 0x42, 0x0f, 0xb7, 0x14, 0x80 };
constexpr uintptr_t DEFER_FLOAT_RVA = 0x919840;           // CDeferredMethodQueue add (queue, sys, fn, handle, float)
constexpr uint8_t DEFER_FLOAT_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x20, 0x55, 0x56, 0x41, 0x56, 0x48, 0x83, 0xec, 0x20 };
constexpr uintptr_t NETGAME_UPDATE_RVA = 0x1bf610;         // CR15NetGame::Update(netgame*) (EchoXR-Hands)
constexpr uint8_t NETGAME_UPDATE_BYTES[] = { 0x40, 0x57, 0x48, 0x81, 0xec, 0x80, 0x00, 0x00, 0x00 };
constexpr uintptr_t SLOT_ACTOR_RVA = 0x1c76b0;
constexpr uint8_t SLOT_ACTOR_BYTES[] = { 0x40, 0x53, 0x48, 0x83, 0xec, 0x20, 0x41, 0x0f, 0xb7, 0xc0, 0x48, 0x8b, 0xda };

struct Pose { float q[4]; float p[3]; float s; };
using transform_get_fn = Pose *(__fastcall *)(void *, Pose *, uint32_t);
using defer_fn = void(__fastcall *)(uintptr_t, void *, void *, uint32_t, const float *);
using defer_float_fn = void(__fastcall *)(uintptr_t, void *, void *, uint32_t, float);
using slot_actor_fn = uint8_t *(__fastcall *)(void *game, uint8_t *out, uint32_t value);
using find_fn = uint32_t *(__fastcall *)(void *cs, void *out, void *key);

transform_get_fn Real_TransformGet = nullptr;
defer_fn Defer = nullptr;
slot_actor_fn SlotActor = nullptr;
void *g_set_velocity = nullptr;
void *g_set_angular = nullptr;
defer_float_fn DeferFloat = nullptr;
void *g_set_emission = nullptr;

char g_log[MAX_PATH];
DWORD g_main_tid = 0;
bool g_authority = false;
thread_local bool t_busy = false;
ULONGLONG g_last_tick = 0;
bool g_verbose = false;                                     // EDITH.ini verbose=1: her position, jets,
                                                            // speaker and faces every few seconds too

// The game's own log (_local\r14logs\<...>_<pid>.log): CLog write, the function EchoRelay.Patch
// hooks (echovrunexported.h WriteLog, RVA EBE70h). Her lines go there too, as "[EDITH] ...", once
// the game is up (its first net-game update), so one log tells the whole story.
constexpr uintptr_t GAME_LOG_RVA = 0xEBE70;
const uint8_t GAME_LOG_BYTES[] = { 0x48, 0x89, 0x5C, 0x24, 0x18, 0x48, 0x89, 0x6C, 0x24, 0x20, 0x56, 0x57 };
typedef void (*game_log_fn)(int level, uint64_t unk, const char *fmt, va_list a);
game_log_fn GameLogFn = nullptr;
volatile bool g_game_log_on = false;

void GameLog(const char *fmt, ...) {
    va_list a;
    va_start(a, fmt);
    GameLogFn(2, 0, fmt, a);                                // 2 = info
    va_end(a);
}

void Log(const char *fmt, ...) {
    char line[1024];
    va_list a;
    va_start(a, fmt);
    vsnprintf(line, sizeof line, fmt, a);
    va_end(a);
    FILE *f = nullptr;
    if (g_log[0] && fopen_s(&f, g_log, "a") == 0 && f) {
        SYSTEMTIME t;
        GetLocalTime(&t);
        fprintf(f, "[%02d:%02d:%02d] %s\n", t.wHour, t.wMinute, t.wSecond, line);
        fclose(f);
    }
    if (g_game_log_on && GameLogFn) {
        __try { GameLog("[EDITH] %s", line); } __except (EXCEPTION_EXECUTE_HANDLER) { g_game_log_on = false; }
    }
}

uint8_t *FindSystem(void *space, uint64_t sym) {
    uint8_t *table = *(uint8_t **)((uint8_t *)space + 0x420);
    uint64_t count = *(uint64_t *)((uint8_t *)space + 0x450);
    for (uint64_t k = 0; table && k < count && k < 1024; ++k)
        if (((*(uint64_t *)(table + k * 16) ^ sym) & ~(1ull << 48)) == 0)
            return *(uint8_t **)(table + k * 16 + 8);
    return nullptr;
}

uint32_t Instance(void *cs, uint64_t actor, uint64_t name) {
    if (!cs) return 0xffffffffu;
    alignas(16) uint64_t key[2] = { actor, name };
    alignas(16) uint8_t out[64] = {};
    uint32_t *h = ((find_fn)(*(void ***)cs)[0x1b0 / 8])(cs, out, key);
    if (!h || (*h & 0xffff) == 0xffff) return 0xffffffffu;       // index 0xffff: none
    return *h;
}

using actor_of_fn = uint64_t *(__fastcall *)(void *cs, uint64_t *out, uint32_t handle);

// The actor's instance whatever its component name: virtual +1A8h (cs, &out, actor, -1), as
// EchoXR-Hands finds remote players (a player's transform isn't named ncaTransform).
uint32_t AnyInstance(void *cs, uint64_t actor) {
    if (!cs) return 0xffffffffu;
    using lookup_fn = uint32_t *(__fastcall *)(void *cs, uint64_t *out, uint64_t actor, int64_t sub);
    uint64_t tmp = 0;
    uint32_t *h = ((lookup_fn)(*(void ***)cs)[0x1a8 / 8])(cs, &tmp, actor, -1);
    if (!h || (*h & 0xffff) == 0xffff) return 0xffffffffu;
    return *h;
}

// (diagnostic) what the transform system's instances look like: actor ids, record bytes
void Probe(uint8_t *cs) {
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    void **vt = *(void ***)cs;
    Log("probe system %p vtable rva %llx: +1B0 -> rva %llx, +1E0 -> rva %llx", cs, (uint8_t *)vt - base,
        (uint8_t *)vt[0x1b0 / 8] - base, (uint8_t *)vt[0x1e0 / 8] - base);
    for (int o = 0xc0; o < 0x110; o += 8) Log("  cs+%03x = %016llx", o, *(uint64_t *)(cs + o));
    uint16_t *slots = *(uint16_t **)(cs + 0xc8);
    uint8_t *recs = *(uint8_t **)(cs + 0xf8);
    for (uint32_t i = 0; i < 8 && slots; ++i) {
        uint32_t handle = i | ((uint32_t)slots[i * 2 + 1] << 16);
        alignas(16) uint64_t out[4] = { ~0ull, ~0ull, ~0ull, ~0ull };
        uint64_t *a = ((actor_of_fn)vt[0x1e0 / 8])(cs, out, handle);
        uint8_t *r = recs + (size_t)slots[i * 2] * 0x118;
        Log("  handle %08x slot %u: actor_of -> %016llx %016llx | rec %016llx %016llx %016llx %016llx", handle,
            slots[i * 2], a ? a[0] : 0, a ? a[1] : 0, *(uint64_t *)r, *(uint64_t *)(r + 8), *(uint64_t *)(r + 16), *(uint64_t *)(r + 24));
    }
}

// Her 8 thruster jets (tools/build_satellite.py add_thrusters: her 2018 CParticleCR rows, effect
// 1536f4115b2ea1b7, one on each corner joint of her cube). The component names are the 2018 rows'
// names; the game space keys its systems by component name, so the first one finds the system.
// Corners are her skeleton's thruster joints (2018 skeleton 4ab3ff017a2ce803, parent bone at her
// centre): +-0.057 m on every axis.
constexpr uint64_t JET_NAMES[8] = { 0xff87929015f5d761ull, 0xff87929015f5d762ull, 0xff87929015f5d763ull,
                                    0xff87929015f5d764ull, 0xff87929015f5d765ull, 0xff87929015f5d766ull,
                                    0xff87929015f5d767ull, 0xff87929015f5d768ull };
//: row i's joint (41d2cd380e1c57xx): 4f 4c 4d 4a 4b 48 49 46 -> that joint's corner (sign of x y z)
constexpr float JET_CORNER[8][3] = {
    { +1, +1, -1 },   // 574f
    { +1, -1, -1 },   // 574c
    { -1, -1, -1 },   // 574d
    { -1, +1, -1 },   // 574a
    { -1, +1, +1 },   // 574b
    { -1, -1, +1 },   // 5748
    { +1, -1, +1 },   // 5749
    { +1, +1, +1 },   // 5746
};
constexpr float JET_ON = 0.15f;          // a jet lights when its share of the thrust passes this
constexpr float JET_OFF = 0.07f;         // and goes out below this (no flicker in between)
constexpr float JET_MIN = 0.35f;         // emission scale of a jet that has just lit
constexpr float JET_SMOOTH = 0.15f;      // s: low-pass on her measured acceleration
constexpr float JET_BUMP = 25.0f;        // m/s^2 past this is a hit / throw, not her thrusters

// Every game space the transform hook has seen, with its transform system.
struct Seen { void *space; uint8_t *transforms; int tries; };
Seen g_seen[32];

// Her game space, once found: its systems and her instance handles.
struct Her {
    void *space = nullptr;
    uint8_t *transforms = nullptr, *physics = nullptr, *net = nullptr, *touch = nullptr;
    uint32_t xf = 0xffffffffu, phys = 0xffffffffu, grab = 0xffffffffu;
} g_her;

void DumpTable(void *space) {
    uint8_t *table = *(uint8_t **)((uint8_t *)space + 0x420);
    uint64_t count = *(uint64_t *)((uint8_t *)space + 0x450);
    Log("game space %p: %llu component systems", space, count);
    for (uint64_t k = 0; table && k < count && k < 1024; ++k)
        Log("  %016llx -> %p", *(uint64_t *)(table + k * 16), *(void **)(table + k * 16 + 8));
}

uint8_t *FindJetSystem(void *space);

// Note the space of this transform system; look for her in it (a few tries per space).
void Note(uint8_t *transforms) {
    void *space = *(void **)(transforms + 0x80);
    if (!space) return;
    Seen *e = nullptr;
    for (auto &x : g_seen) {
        if (x.space == space) { e = &x; break; }
        if (!e && !x.space) e = &x;
    }
    if (!e) return;
    if (e->space != space) *e = { space, transforms, 0 };
    if (e->transforms != transforms) return;              // (a second transform system: not used)
    if (g_her.space || e->tries >= 600) return;       // (her physics instance comes a moment later)
    ++e->tries;
    uint32_t xf = Instance(transforms, HER_ACTOR, NCA_TRANSFORM);
    if (xf == 0xffffffffu) return;
    uint16_t *slots = *(uint16_t **)(transforms + 0xc8);
    uint8_t *rec = *(uint8_t **)(transforms + 0xf8) + (size_t)slots[(xf & 0xffff) * 2] * 0x118;
    Pose at;
    Real_TransformGet(transforms, &at, xf);
    float dh = fabsf(at.p[0] - g_home[0]) + fabsf(at.p[1] - g_home[1]) + fabsf(at.p[2] - g_home[2]);
    // her jets are hers alone: with them she is her wherever she is (a client: she flew off)
    if (dh > 1.0f && Instance(FindJetSystem(space), HER_ACTOR, JET_NAMES[0]) == 0xffffffffu) {
        Log("space %p: actor %016llx at (%.2f %.2f %.2f), parent %016llx: not her", space, HER_ACTOR,
            at.p[0], at.p[1], at.p[2], *(uint64_t *)(rec + 8));   // another level's actor of that index
        e->tries = 600;
        return;
    }
    uint8_t *physics = FindSystem(space, NCA_PHYSICS);
    uint32_t phys = Instance(physics, HER_ACTOR, NCA_PHYSICS);
    uint8_t *net = FindSystem(space, SYM_NET_PHYSICS);
    Pose p;
    Real_TransformGet(transforms, &p, xf);
    if (phys == 0xffffffffu) return;
    Log("space %p: her transform %08x at (%.2f %.2f %.2f), physics %p/%08x, net physics system %p", space, xf,
        p.p[0], p.p[1], p.p[2], physics, phys, net);
    g_her.space = space; g_her.transforms = transforms; g_her.physics = physics; g_her.net = net;
    g_her.xf = xf; g_her.phys = phys;
    g_her.touch = FindSystem(space, SYM_TOUCH);                // who holds her (snowball rule)
    g_her.grab = Instance(g_her.touch, HER_ACTOR, SYM_TOUCH);
    Log("  her touch interact: system %p, handle %08x", g_her.touch, g_her.grab);
}

// Still valid? (the level can unload)
bool HerAlive() {
    if (!g_her.space) return false;
    if (*(void **)(g_her.transforms + 0x80) != g_her.space ||
        Instance(g_her.transforms, HER_ACTOR, NCA_TRANSFORM) != g_her.xf) {
        Log("her space %p went away", g_her.space);
        g_her = Her();
        for (auto &x : g_seen) x = {};
        return false;
    }
    return true;
}

// The level hash a game space carries (found by scanning its header once for a known hash;
// the offset is the same for every space).
int g_level_off = -1;
bool SpaceIsLevel(void *space, uint64_t level) {
    const uint64_t *w = (const uint64_t *)space;
    if (g_level_off >= 0) return w[g_level_off / 8] == level;
    for (int o = 0; o < 0x1000; o += 8)
        if (w[o / 8] == level) {
            g_level_off = o;
            Log("game spaces keep their level hash at +%#x (found %016llx in %p)", o, level, space);
            return true;
        }
    return false;
}

// A player's head position. Actor ref = SActorGUID {level of the actor's game space, actor}
// (CncaGame::ActorNodeID, libr15). The player actor carries an R15EchoUnit component whose
// record holds the world head transform: CR15EchoUnitCS::WorldHeadTransform (libr15
// 0x1c75504) reads slot table +C8h, records +F8h (stride 0x280 in libr15), +30h..+5Fh.
constexpr uint64_t SYM_ECHO_UNIT = 0xefe7a55edebae6b6ull;     // R15EchoUnit
constexpr size_t ECHO_UNIT_STRIDE = 0x280, ECHO_UNIT_HEAD = 0x30;
bool PlayerPos(uint64_t level, uint64_t actor, float *out) {
    for (auto &x : g_seen) {
        if (!x.space || *(void **)(x.transforms + 0x80) != x.space) continue;
        if (!SpaceIsLevel(x.space, level)) continue;
        uint8_t *eu = FindSystem(x.space, SYM_ECHO_UNIT);
        uint32_t h = AnyInstance(eu, actor);
        static int once = 0;
        if (h == 0xffffffffu) {
            if (once++ < 2) Log("player actor %016llx: no echo unit in space %p (system %p)", actor, x.space, eu);
            continue;
        }
        uint16_t slot = *(uint16_t *)(*(uint8_t **)(eu + 0xc8) + (size_t)(h & 0xffff) * 4);
        const float *f = (const float *)(*(uint8_t **)(eu + 0xf8) + (size_t)slot * ECHO_UNIT_STRIDE + ECHO_UNIT_HEAD);
        if (once++ < 4)
            Log("echo unit %08x (system %p, slot %u): +30 %.3f %.3f %.3f %.3f | %.3f %.3f %.3f %.3f | %.3f %.3f %.3f %.3f",
                h, eu, slot, f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], f[10], f[11]);
        // quaternion (x y z w) then position: use the position
        out[0] = f[4]; out[1] = f[5]; out[2] = f[6];
        return true;
    }
    return false;
}

// Players, the way EchoXR-Hands reads them (CR15NetGame, the per-frame net game): slot count
// u16 at +E2h; slot s occupied when +s*250h+3C0h != 0; its 16-byte actor reference at
// +s*250h+180h. CPlayerSlot's accessor (+0x1c76b0) resolves that reference in place, but it
// can give the owning space rather than the player, so the raw halves are tried too.
uint8_t *volatile g_netgame = nullptr;

// The nearest player's head. The engine's R15NetPlayerByUserIdExpression (echovr 0x140d9ea40,
// found through ReVault) reads it straight from the net game: slot s (u16 < 16) is valid when
// ng+13Ah+s*4 holds its generation and ng+138h+s*4 a value != 0xffff; that player's state is
// the 0x74-byte record at ng + 63FD8h + value*74h (head position, head orientation, body up,
// velocity, ...: the expression's outputs).
constexpr size_t PLAYER_STATE = 0x63fd8, PLAYER_STATE_SIZE = 0x74;
//: head position at record +1Ch (measured in game: it follows the player; BindReplicatedVars,
//: echovr 0x140e01140, names it headpos); velocity at +40h (lead for snowballs); +5Ch is the
//: spawn point the player was placed at.
constexpr int HEAD_POS = 0x1c, HEAD_VEL = 0x40;
// In local mode (a public lobby whose server doesn't run her) "the player" is YOU: the slot whose
// head is at the game's audio listener (your ears), not whoever is nearest to her.
int TargetSlot();
bool PlayerAt(int s, float *pos, float *vel);
bool NearestPlayer(const float *me, float *out, int *slot = nullptr) {
    uint8_t *ng = g_netgame;
    if (!ng) return false;
    int ts = TargetSlot();                                    // the player she's about, by name
    float tv[3];
    if (ts >= 0 && PlayerAt(ts, out, tv)) {
        if (slot) *slot = ts;
        return true;
    }
    float ear[3] = { g_ear[0], g_ear[1], g_ear[2] };
    if (g_local) {
        if (!g_ear_ok) return false;                        // (until her speaker knows where you are)
        me = ear;
    }
    float best = g_local ? 1.5f * 1.5f : 1e30f;
    bool found = false;
    static int logged = 0;
    for (uint32_t s = 0; s < 16; ++s) {
        g_stage = 10;
        uint16_t value = *(uint16_t *)(ng + 0x138 + s * 4);
        if (value == 0xffff || *(uint64_t *)(ng + (size_t)s * 0x250 + 0x3c0) == 0) continue;   // empty (EchoXR-Hands)
        const float *f = (const float *)(ng + PLAYER_STATE + (size_t)value * PLAYER_STATE_SIZE);
        static ULONGLONG last_dump = 0;
        if (logged < 2 || (s == 0 && GetTickCount64() - last_dump > 30000)) {
            ++logged;
            if (s == 0) last_dump = GetTickCount64();
            char line[1024]; int len = 0;
            for (int k = 0; k < (int)(PLAYER_STATE_SIZE / 4); ++k) len += snprintf(line + len, sizeof line - len, " %d:%.3f", k * 4, f[k]);
            Log("player slot %u (value %u) state:%s", s, value, line);
        }
        const float *p = (const float *)((const uint8_t *)f + HEAD_POS);
        if (fabsf(p[0]) + fabsf(p[1]) + fabsf(p[2]) < 1e-4f) continue;
        float d = (p[0] - me[0]) * (p[0] - me[0]) + (p[1] - me[1]) * (p[1] - me[1]) + (p[2] - me[2]) * (p[2] - me[2]);
        if (d < best) {
            best = d; out[0] = p[0]; out[1] = p[1]; out[2] = p[2]; found = true;
            if (slot) *slot = (int)s;
        }
    }
    return found;
}

// Player slot s's head position and velocity (the state record NearestPlayer reads); false when
// the slot is empty now.
bool PlayerAt(int s, float *pos, float *vel) {
    uint8_t *ng = g_netgame;
    if (!ng || s < 0 || s >= 16) return false;
    uint16_t value = *(uint16_t *)(ng + 0x138 + s * 4);
    if (value == 0xffff || *(uint64_t *)(ng + (size_t)s * 0x250 + 0x3c0) == 0) return false;
    const uint8_t *f = ng + PLAYER_STATE + (size_t)value * PLAYER_STATE_SIZE;
    memcpy(pos, f + HEAD_POS, 12);
    memcpy(vel, f + HEAD_VEL, 12);
    return fabsf(pos[0]) + fabsf(pos[1]) + fabsf(pos[2]) > 1e-4f;
}

// --- vectors / quaternions (x y z w) ---------------------------------------------------------
void Cross(const float *a, const float *b, float *o) {
    o[0] = a[1] * b[2] - a[2] * b[1]; o[1] = a[2] * b[0] - a[0] * b[2]; o[2] = a[0] * b[1] - a[1] * b[0];
}
float Dot(const float *a, const float *b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
float Len(const float *a) { return sqrtf(Dot(a, a)); }
void Rotate(const float *q, const float *v, float *o) {          // q * v * q^-1
    float t[3], u[3];
    Cross(q, v, t);
    for (int k = 0; k < 3; ++k) t[k] *= 2.0f;
    Cross(q, t, u);
    for (int k = 0; k < 3; ++k) o[k] = v[k] + q[3] * t[k] + u[k];
}
void QMul(const float *a, const float *b, float *o) {           // a * b
    float r[4] = { a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
                   a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
                   a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
                   a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2] };
    memcpy(o, r, 16);
}
// The rotation from `from` to `to` (world frame) as axis * angle, the short way round.
void QDiff(const float *from, const float *to, float *aa) {
    float inv[4] = { -from[0], -from[1], -from[2], from[3] }, d[4];
    QMul(to, inv, d);
    if (d[3] < 0) for (int k = 0; k < 4; ++k) d[k] = -d[k];
    float s = Len(d);
    float angle = 2.0f * atan2f(s, d[3]);
    for (int k = 0; k < 3; ++k) aa[k] = s > 1e-6f ? d[k] / s * angle : 0.0f;
}
// q turned by the rotation axis * angle `aa` (world frame).
void QTurn(const float *q, const float *aa, float *o) {
    float angle = Len(aa), r[4] = { 0, 0, 0, 1 };
    if (angle > 1e-6f) {
        float s = sinf(angle * 0.5f) / angle;
        r[0] = aa[0] * s; r[1] = aa[1] * s; r[2] = aa[2] * s; r[3] = cosf(angle * 0.5f);
    }
    QMul(r, q, o);
    float l = sqrtf(o[0] * o[0] + o[1] * o[1] + o[2] * o[2] + o[3] * o[3]);
    for (int k = 0; k < 4; ++k) o[k] /= l;
}
//: the physics record's kind (record +40h): the velocity setters only touch body +C8h / +D4h for
//: RIGID records; the other kind (0x20bb238) converts through the transform first (0x467d60), and
//: SetLocalAngularVelocity does nothing for it
constexpr uintptr_t PHYS_KIND_RIGID = 0x20bb210, PHYS_KIND_OTHER = 0x20bb238;
// (diagnostic, once) which kind her physics record is
void LogPhysicsKind() {
    static bool done = false;
    if (done) return;
    done = true;
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    uint8_t *cs = g_her.physics;
    uint16_t slot = *(uint16_t *)(*(uint8_t **)(cs + 0xc8) + (size_t)(g_her.phys & 0xffff) * 4);
    uint8_t *rec = *(uint8_t **)(cs + 0xf8) + (size_t)slot * 0x78;
    uint64_t kind = *(uint64_t *)(rec + 0x40);
    Log("her physics record: kind %016llx (%s), +48h %d, offset velocity (%.2f %.2f %.2f)", kind,
        kind == *(uint64_t *)(base + PHYS_KIND_RIGID) ? "rigid: angular velocity applies"
        : kind == *(uint64_t *)(base + PHYS_KIND_OTHER) ? "the other kind: angular setter is a no-op" : "unknown",
        *(int32_t *)(rec + 0x48), *(float *)(rec + 0xc), *(float *)(rec + 0x10), *(float *)(rec + 0x14));
}
void SetVelocities(const float *v, const float *w) {
    uintptr_t queue = *(uintptr_t *)(g_her.physics + 0x80) + 0x170;
    if (v) Defer(queue, g_her.physics, g_set_velocity, g_her.phys, v);
    if (w) Defer(queue, g_her.physics, g_set_angular, g_her.phys, w);
}
// The angular velocity that turns her front (local +Z) toward `dir` and her local +Y up; returns
// the facing error in radians.
float FaceTowards(const Pose &me, const float *dir, float *w) {
    static const float Z[3] = { 0, 0, 1 }, Y[3] = { 0, 1, 0 };
    float fwd[3], up[3], want[3] = { dir[0], dir[1], dir[2] };
    Rotate(me.q, Z, fwd);
    Rotate(me.q, Y, up);
    float l = Len(want);
    if (l < 1e-4f) { w[0] = w[1] = w[2] = 0; return 0; }
    for (int k = 0; k < 3; ++k) want[k] /= l;
    float turn[3], level[3];
    Cross(fwd, want, turn);                                   // axis * sin(error)
    float err = atan2f(Len(turn), Dot(fwd, want));
    float s = Len(turn);
    if (s > 1e-5f) for (int k = 0; k < 3; ++k) turn[k] = turn[k] / s * err * TURN_GAIN;
    else if (err > 1.0f) { turn[0] = 0; turn[1] = 3.14159f * TURN_GAIN; turn[2] = 0; }   // facing away: yaw round
    Cross(up, Y, level);                                      // tilt back to upright
    for (int k = 0; k < 3; ++k) w[k] = turn[k] + level[k] * UPRIGHT_GAIN;
    float m = Len(w);
    if (m > MAX_TURN) for (int k = 0; k < 3; ++k) w[k] *= MAX_TURN / m;
    return err;
}
// Thrust from velocity `v` toward `want`, at most THRUST m/s^2 over dt.
void Thrust(const float *v, const float *want, float dt, float *out) {
    float dv[3] = { want[0] - v[0], want[1] - v[1], want[2] - v[2] };
    float m = Len(dv), lim = THRUST * dt;
    for (int k = 0; k < 3; ++k) out[k] = v[k] + (m > lim ? dv[k] * lim / m : dv[k]);
}

// What she is doing: following a player, tumbling after a push / throw / grab, or staring at
// the nearest player before going back to following (the Christmas tracking; the snowball goes
// at the end of the stare once the snowballs are in).
enum Mode { FOLLOW, TUMBLE, STARE };
//: why she is tumbling: only THROWN and HEADBUTT earn a snowball (the user's rule)
enum Cause { BUMP, HELD, THROWN, HEADBUTT };
struct Brain {
    Mode mode = FOLLOW;
    Cause cause = BUMP;
    int culprit = -1;                                         // the player slot who did it
    bool held = false;
    ULONGLONG since = 0, last_push = 0, last = 0;
    float sent[3] = {};                                       // the velocity she last set
    float prev[3] = {};                                       // her velocity last tick
    float pos[3] = {};                                        // her position last tick
    bool have = false;
    bool wall = false;                                        // this tumble: she hit something herself
} g_brain;

const char *ModeName(Mode m) { return m == FOLLOW ? "follow" : m == TUMBLE ? "tumble" : "stare"; }
const char *CauseName(Cause c) { return c == BUMP ? "bump" : c == HELD ? "held" : c == THROWN ? "thrown" : "headbutt"; }

// Someone holds her: either hand's grab count in her touch-interact record.
bool Held() {
    if (g_her.grab == 0xffffffffu) {                          // (not there yet when she was found)
        static ULONGLONG tried = 0;
        ULONGLONG now = GetTickCount64();
        if (now - tried < 1000) return false;
        tried = now;
        if (!g_her.touch) g_her.touch = FindSystem(g_her.space, SYM_TOUCH);
        g_her.grab = Instance(g_her.touch, HER_ACTOR, SYM_TOUCH);
        if (g_her.grab == 0xffffffffu) g_her.grab = AnyInstance(g_her.touch, HER_ACTOR);
        if (g_her.grab == 0xffffffffu) return false;
        Log("her touch interact: system %p, handle %08x", g_her.touch, g_her.grab);
    }
    if (!g_her.touch) return false;
    uint16_t slot = *(uint16_t *)(*(uint8_t **)(g_her.touch + 0xc8) + (size_t)(g_her.grab & 0xffff) * 4);
    const uint8_t *rec = *(uint8_t **)(g_her.touch + 0xf8) + (size_t)slot * TOUCH_STRIDE;
    return *(const uint32_t *)(rec + TOUCH_GRABS) || *(const uint32_t *)(rec + TOUCH_GRABS + 4);
}

// --- snowballs ----------------------------------------------------------------------------------
// A pool of grabbable snowball actors parked by her home. A throw teleports the next one to just in
// front of her (CncaGame::WorldTeleport), then sets its velocity (through the deferred queue, on the
// next two ticks, once the teleport has landed); a thrown one goes back to the pile after a while.
struct Snow { ULONGLONG thrown = 0; float v[3] = {}; int launch = 0; } g_snow[16];
unsigned g_snow_next = 0;

uint64_t SnowActor(unsigned k) { return 0x0000FFFFFFFF0000ull | ((g_snow_first + k) & 0xffff); }

void Place(unsigned k, const float *at) {
    float xf[8] = { 0, 0, 0, 1, at[0], at[1], at[2], 1 };
    WorldTeleport(g_her.space, SnowActor(k), xf, 0);
}

void SetSnowVelocity(unsigned k, const float *v) {
    uint32_t h = Instance(g_her.physics, SnowActor(k), NCA_PHYSICS);
    if (h == 0xffffffffu) { Log("snowball %u: no physics instance", k); return; }
    static const float zero[3] = { 0, 0, 0 };
    uintptr_t queue = *(uintptr_t *)(g_her.physics + 0x80) + 0x170;
    Defer(queue, g_her.physics, g_set_velocity, h, v);
    Defer(queue, g_her.physics, g_set_angular, h, zero);
}

void SendSnow(unsigned k, const float *at, const float *v);   // (the relay, below)

// Throw at player slot `s`, leading their head by its velocity over the flight time.
bool ThrowSnowball(const Pose &me, int s) {
    float tp[3], tv[3];
    if (!g_snow_count || !WorldTeleport || !PlayerAt(s, tp, tv)) {
        Log("snowball: nothing to throw at (pool %u, slot %d)", g_snow_count, s);
        return false;
    }
    static const float Z[3] = { 0, 0, 1 };
    float fwd[3], at[3];
    Rotate(me.q, Z, fwd);
    for (int k = 0; k < 3; ++k) at[k] = me.p[k] + fwd[k] * SNOW_MUZZLE;
    float d[3] = { tp[0] - at[0], tp[1] - at[1], tp[2] - at[2] };
    float t = Len(d) / SNOW_SPEED, aim[3];
    for (int k = 0; k < 3; ++k) aim[k] = tp[k] + tv[k] * t - at[k];
    float l = Len(aim);
    if (l < 1e-3f) return false;
    unsigned k = g_snow_next++ % g_snow_count;
    Snow &b = g_snow[k];
    for (int i = 0; i < 3; ++i) b.v[i] = aim[i] / l * SNOW_SPEED;
    Place(k, at);
    b.launch = 2;
    b.thrown = GetTickCount64();
    Log("snowball %u (actor %016llx) at (%.2f %.2f %.2f) -> player %d at (%.2f %.2f %.2f), %.2f m, lead %.2f s",
        k, SnowActor(k), at[0], at[1], at[2], s, tp[0], tp[1], tp[2], Len(d), t);
    SendSnow(k, at, b.v);                                     // the other players see it too
    return true;
}

// A ball the host threw, on a puppet: its own copy of ball k, same start and velocity (each game
// has its own ball actors; the server doesn't know them). Users: "they can't see her throw balls".
void LaunchSnow(unsigned k, const float *at, const float *v) {
    if (!g_snow_count || !WorldTeleport || !HerAlive() || k >= g_snow_count) return;
    Snow &b = g_snow[k];
    memcpy(b.v, v, 12);
    Place(k, at);
    b.launch = 2;
    b.thrown = GetTickCount64();
}

// --- voice orders (ai/satellite_ai.py, the local AI companion) -------------------------------
// Plain-text UDP on 127.0.0.1: orders in on CMD_PORT, events out to EVENT_PORT (what happened to
// her and a state line every 2 s, for the companion's memory). Polled on the game thread in Tick.
//   follow [name] | come [name] | stay | look | home | goto x y z | spin [keep] | flip front|back|left|right [n|keep]
//   | stop | throw [to=name] | push [m/s] [to=name] | shutdown [to=name] | favour [name] | heard <text> | status
// Events carry by=<name> (who did it); "heard <name> <text>" is another player talking to her.
// A spin turns her about world up; a flip about her own side axis (front / back) or her front
// axis (left / right roll). "keep" goes on until "stop" (or another order), with a dizzy event
// every DIZZY_MS; after a long one she wobbles a while.
enum Order { O_FOLLOW, O_COME, O_STAY, O_GOTO, O_SPIN };
const char *OrderName(Order o) {
    return o == O_FOLLOW ? "follow" : o == O_COME ? "come" : o == O_STAY ? "stay" : o == O_GOTO ? "goto" : "spin";
}
struct Orders {
    Order order = O_FOLLOW, after = O_FOLLOW; float target[3] = {}; ULONGLONG until = 0; bool throw_now = false;
    bool endless = false, local = false;                  // spin: forever? axis in her own frame?
    float axis[3] = { 0, 1, 0 }, rate = 0;                // spin axis and rad/s
    ULONGLONG spin_start = 0, last_dizzy = 0, wobble_until = 0;
    float push = 0;                                       // a push at this m/s is wanted
    bool shutdown = false;                                // shut the nearest player's echo unit down
    uint32_t shutdown_reason = 0xffffffffu;               // "shutdown N": death reason N (else the default)
    char who[64] = "";                                    // follow / come: that player ("" = her favourite)
    char to[64] = "";                                     // this order's to=<name> (parsing)
    char push_to[64] = "", kill_to[64] = "", throw_to[64] = "";   // push / shutdown / throw aimed at ("" = her player)
} g_orders;
int TargetSlot() {
    bool to_player = g_orders.order == O_FOLLOW || g_orders.order == O_COME;
    return SlotOf(to_player && g_orders.who[0] ? g_orders.who : g_favour);
}
constexpr u_short CMD_PORT = 47321, EVENT_PORT = 47322;
constexpr float COME_DIST = 0.7f;        // m: "come here" hovers this close
constexpr float SPIN_RATE = 6.0f;        // rad/s about up
constexpr DWORD SPIN_MS = 2000;
constexpr float FLIP_RATE = 7.0f;        // rad/s: a flip takes ~0.9 s
constexpr DWORD DIZZY_MS = 5000;         // an endless spin reports how long it has gone this often
constexpr DWORD WOBBLE_MS = 3500;        // dizzy wobble after a long endless spin
constexpr float PUSH_SPEED = 6.0f;       // m/s a push gives the player by default
constexpr float PUSH_MAX = 15.0f;
SOCKET g_sock = INVALID_SOCKET;
sockaddr_in g_ai = {};

bool g_ears_dll = false;                                      // EDITH.ini ears=dll: her ears are built in (edith_ears.cpp)

void Event(const char *fmt, ...) {
    char buf[512];
    va_list a;
    va_start(a, fmt);
    int n = vsnprintf(buf, sizeof buf, fmt, a);
    va_end(a);
    if (n <= 0) return;
    if (g_ears_dll) Ears_Line(buf);                           // up to the brain
    if (g_sock != INVALID_SOCKET)                             // (and to a Python companion, if one runs)
        sendto(g_sock, buf, n < (int)sizeof buf ? n : (int)sizeof buf - 1, 0, (sockaddr *)&g_ai, sizeof g_ai);
}

void OpenOrders() {
    WSADATA w;
    if (WSAStartup(MAKEWORD(2, 2), &w)) return;
    SOCKET sk = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sk == INVALID_SOCKET) return;
    sockaddr_in me = {};
    me.sin_family = AF_INET;
    me.sin_port = htons(CMD_PORT);
    inet_pton(AF_INET, "127.0.0.1", &me.sin_addr);
    if (bind(sk, (sockaddr *)&me, sizeof me)) { Log("orders: port %u busy", CMD_PORT); closesocket(sk); return; }
    u_long nb = 1;
    ioctlsocket(sk, FIONBIO, &nb);
    g_ai.sin_family = AF_INET;
    g_ai.sin_port = htons(EVENT_PORT);
    inet_pton(AF_INET, "127.0.0.1", &g_ai.sin_addr);
    g_sock = sk;
    Log("orders: listening on 127.0.0.1:%u, events to :%u", CMD_PORT, EVENT_PORT);
}

bool SetFace(const char *name, float seconds);                // her mood faces (below)
void SendVoice(const char *keys);                             // her voice on the other players' games (below)
void SendFace(const char *name, float seconds);               // ...and her face
void ForwardHeard(const char *text);                          // (Edith on the network, below)
bool SendCtl(const char *to, const char *what, float speed, const float *from);

void PollOrders(const Pose &me) {
    if (g_sock == INVALID_SOCKET) return;
    char buf[256];
    for (int k = 0; k < 16; ++k) {
        int n = recv(g_sock, buf, sizeof buf - 1, 0);
        if (n <= 0) return;
        buf[n] = 0;
        float x, y, z;
        Order was = g_orders.order;
        // "... to=<name>": push / shutdown / throw aimed at that player (else the one she's about)
        g_orders.to[0] = 0;
        if (const char *t = strstr(buf, "to=")) sscanf_s(t + 3, "%63s", g_orders.to, (unsigned)sizeof g_orders.to);
        if (!strncmp(buf, "heard ", 6)) {                     // a puppet's companion: speech for the host
            ForwardHeard(buf + 6);
            continue;
        }
        if (!strncmp(buf, "lookat ", 7)) {                    // "lookat <seconds> <name, may have spaces>"
            float s = 0;
            int used = 0;
            if (sscanf_s(buf + 7, "%f %n", &s, &used) >= 1 && used > 0) {
                strncpy_s(g_look, buf + 7 + used, _TRUNCATE);
                g_look_until = GetTickCount64() + (ULONGLONG)(fminf(fmaxf(s, 0.5f), 30.0f) * 1000.0f);
            }
            continue;
        }
        if (!strncmp(buf, "voice ", 6)) {                     // the host's line from the pack: the others play it too
            SendVoice(buf + 6);
            continue;
        }
        if (!strncmp(buf, "favour ", 7) || !strcmp(buf, "favour")) {
            char name[64] = "";
            if (buf[6]) sscanf_s(buf + 7, "%63s", name, (unsigned)sizeof name);
            if (strcmp(name, g_favour)) Log("favourite: '%s' (was '%s')", name, g_favour);
            strcpy_s(g_favour, name);
            continue;
        }
        if (!strncmp(buf, "follow", 6) || !strncmp(buf, "come", 4)) {   // "follow [name]" / "come [name]"
            g_orders.order = buf[0] == 'f' ? O_FOLLOW : O_COME;
            g_orders.who[0] = 0;
            const char *rest = buf + (buf[0] == 'f' ? 6 : 4);
            if (*rest == ' ') sscanf_s(rest + 1, "%63s", g_orders.who, (unsigned)sizeof g_orders.who);
        }
        else if (!strncmp(buf, "stay", 4) || !strncmp(buf, "look", 4)) {
            g_orders.order = O_STAY;
            memcpy(g_orders.target, me.p, 12);
        } else if (!strncmp(buf, "home", 4)) {
            g_orders.order = O_GOTO;
            memcpy(g_orders.target, g_home, 12);
        } else if (sscanf_s(buf, "goto %f %f %f", &x, &y, &z) == 3) {
            g_orders.order = O_GOTO;
            g_orders.target[0] = x; g_orders.target[1] = y; g_orders.target[2] = z;
        } else if (!strncmp(buf, "spin", 4) || !strncmp(buf, "flip", 4)) {   // then back to what she was doing
            bool flip = buf[0] == 'f';
            bool keep = strstr(buf, "keep") != nullptr;
            float ax[3] = { 0, 1, 0 };
            if (flip) {
                if (strstr(buf, "back")) { ax[0] = -1; ax[1] = 0; }
                else if (strstr(buf, "left")) { ax[1] = 0; ax[2] = 1; }
                else if (strstr(buf, "right")) { ax[1] = 0; ax[2] = -1; }
                else { ax[0] = 1; ax[1] = 0; }                // front: her nose goes down (+X)
            }
            int turns = 1;
            const char *num = buf + 4;
            while (*num && (*num < '0' || *num > '9')) ++num;
            if (*num) turns = atoi(num);
            turns = turns < 1 ? 1 : turns > 20 ? 20 : turns;
            ULONGLONG now = GetTickCount64();
            if (was != O_SPIN) { g_orders.after = was; g_orders.spin_start = now; g_orders.last_dizzy = now; }
            g_orders.order = O_SPIN;
            g_orders.endless = keep;
            g_orders.local = flip;
            memcpy(g_orders.axis, ax, 12);
            g_orders.rate = flip ? FLIP_RATE : SPIN_RATE;
            memcpy(g_orders.target, me.p, 12);
            g_orders.until = now + (flip ? (DWORD)(turns * 6.2832f / FLIP_RATE * 1000.0f) + 150 : SPIN_MS * turns);
        } else if (!strncmp(buf, "stop", 4)) {
            if (was == O_SPIN) g_orders.until = 0, g_orders.endless = false;   // ends this tick
        } else if (!strncmp(buf, "push", 4)) {
            float s = 0;
            g_orders.push = sscanf_s(buf, "push %f", &s) == 1 && s > 0 ? fminf(s, PUSH_MAX) : PUSH_SPEED;
            strcpy_s(g_orders.push_to, g_orders.to);
        } else if (!strncmp(buf, "shutdown", 8)) {
            unsigned r = 0;
            g_orders.shutdown = true;
            g_orders.shutdown_reason = sscanf_s(buf, "shutdown %u", &r) == 1 && r < 13 ? r : 0xffffffffu;
            strcpy_s(g_orders.kill_to, g_orders.to);
        }
        else if (!strncmp(buf, "throw", 5)) { g_orders.throw_now = true; strcpy_s(g_orders.throw_to, g_orders.to); }
        else if (!strncmp(buf, "face ", 5)) {
            char name[32] = {};
            float s = 0;
            if (sscanf_s(buf + 5, "%31s %f", name, (unsigned)sizeof name, &s) < 1 || !SetFace(name, s)) {
                Event("error face %s", buf + 5);
                continue;
            }
            SendFace(name, s);                                // the other players see it too
        }
        else if (strncmp(buf, "status", 6)) { Log("orders: unknown \"%s\"", buf); Event("error unknown order %s", buf); continue; }
        Log("order \"%s\" (%s -> %s)", buf, OrderName(was), OrderName(g_orders.order));
        Event("ok %s", buf);
    }
}

void UpdateSnow() {
    ULONGLONG now = GetTickCount64();
    for (unsigned k = 0; k < g_snow_count && k < 16; ++k) {
        Snow &b = g_snow[k];
        if (b.launch > 0) { SetSnowVelocity(k, b.v); --b.launch; }
        if (b.thrown && now - b.thrown > SNOW_BACK_MS) {      // back to the pile
            float at[3] = { g_snow_park[0] + 0.12f * k, g_snow_park[1], g_snow_park[2] };
            static const float zero[3] = { 0, 0, 0 };
            Place(k, at);
            SetSnowVelocity(k, zero);
            b.thrown = 0;
        }
    }
}

// --- her control over the player ---------------------------------------------------------------
// The player's CR15PlayerNavCS record (system vtable rva 1c439d0, records +F8h stride 890h): +20h
// flags (100h | 80h = already shut down), +28h its R15EchoUnit system, +30h its echo unit handle
// (the unit's record, stride 280h, holds the head transform at +30h, position +40h).
//   0x74adb0  CR15PlayerNavCS::SetVelocity (cs, handle, &v): the engine's ForcePushPlayer
//   0x747500  CR15PlayerNavCS::KillPlayer (cs, handle, damage type, limb, CSymbol64): the echo
//             unit shutdown (kill volumes, the thrusters tutorial): the unit dies and respawns
// Both go through the deferred queue like her own velocity (KillPlayer through a small
// trampoline: the queue calls fn(cs, handle, &vec3)).
constexpr uintptr_t NAV_VTABLE_RVA = 0x1c439d0;
constexpr size_t NAV_STRIDE = 0x890;
constexpr uintptr_t NAV_SET_VELOCITY_RVA = 0x74adb0;
constexpr uint8_t NAV_SET_VELOCITY_BYTES[] = { 0x48, 0x83, 0xec, 0x38, 0x48, 0x8b, 0x81, 0xc8, 0x00, 0x00, 0x00, 0xf2, 0x41, 0x0f, 0x10, 0x00 };
constexpr uintptr_t KILL_PLAYER_RVA = 0x747500;
constexpr uint8_t KILL_PLAYER_BYTES[] = { 0x4c, 0x8b, 0xdc, 0x45, 0x89, 0x43, 0x18, 0x55, 0x57, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57 };
using kill_player_fn = void(__fastcall *)(void *cs, uint32_t handle, uint32_t type, uint32_t limb, uint64_t sym);
void *g_nav_set_velocity = nullptr;
kill_player_fn KillPlayer = nullptr;
//: KillPlayer(cs, handle, r8 = death reason, r9 = body part, CSymbol64). Reasons (runtime table
//: rva 0x20c81b0): 0 creep, 1 spore, 2 radiation, 3 cyst, 4 impact at high velocity, 5 crushing,
//: 6 laser, 7 leaving safe boundaries, 8 cutter, 9 fury thruster, 10 scripting, 11 electrical,
//: 12 emp. Parts (0x20c8280): 0 non-specific, 1 head, 2/3 arms, 4 entire body. The player script
//: (25b9f751143a5dd0, R15DeathReasonSwitchNode) picks the death sequence by reason: "creep" showed
//: nothing in the lobby. The micro thrusters tutorial's red walls (CR15KillVolCR rows: mode 0,
//: reason 6, part 4) are lasers: the same shutdown.
//: Laser (6) was tried: the switch calls LaserDeath (0857cf65a1af60b8) on the Player's component
//: 90259bcb96ac1e88, which only r14_glb_global_tutorial gives the player ("FunctionCall could not
//: find actor / component"). r14_glb_global_mp's player actors (dfb4e911bdaddc39, f1e70acd0dde0312)
//: carry ImpactDeath (7df05c1589e59f16, component c5cb02587476de17) and CrushDeath (7fda28908f2c0ca8,
//: c29e5b0b26218947). Impact (4) failed the same way (component 4c6c8c218c97b7e6). Fixed by
//: Hooked_FindScriptComponent (tutorial names -> the lobby's), so laser is the default again: the
//: tutorial's red walls exactly. "shutdown N" picks another reason to try.
constexpr uint32_t KILL_REASON = 6;      // laser
constexpr uint32_t KILL_LIMB = 4;        // entire body

uint8_t *FindNav() {
    static uint8_t *nav = nullptr;
    static void *nav_space = nullptr;
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    if (nav && *(void **)(nav + 0x80) == nav_space) return nav;
    nav = nullptr;
    for (auto &x : g_seen) {
        if (!x.space) continue;
        uint8_t *table = *(uint8_t **)((uint8_t *)x.space + 0x420);
        uint64_t count = *(uint64_t *)((uint8_t *)x.space + 0x450);
        for (uint64_t k = 0; table && k < count && k < 1024; ++k) {
            uint8_t *cs = *(uint8_t **)(table + k * 16 + 8);
            if (cs && *(uint8_t **)cs == base + NAV_VTABLE_RVA) {
                nav = cs; nav_space = x.space;
                Log("player nav system %p in space %p", cs, x.space);
                return nav;
            }
        }
    }
    return nullptr;
}

// The nav handle of player slot `s`: record +00h (u16) is the player's number (KillPlayer reads its
// player row with it). Pool size: u16 at system +F0h (2 in the offline lobby; reading past the
// slot table faulted). If no record carries that number, the one live record (flags +20h bit
// 2000h) when there is exactly one.
uint32_t NavHandleFor(uint8_t *nav, int s) {
    uint32_t hit = 0xffffffffu, live = 0xffffffffu;
    int nlive = 0;
    __try {
        uint16_t *slots = *(uint16_t **)(nav + 0xc8);
        uint8_t *recs = *(uint8_t **)(nav + 0xf8);
        uint32_t n = *(uint16_t *)(nav + 0xf0);
        if (n > 64) n = 64;
        for (uint32_t i = 0; slots && recs && i < n; ++i) {
            uint16_t slot = slots[i * 2];
            if (slot >= n) continue;
            uint8_t *r = recs + (size_t)slot * NAV_STRIDE;
            uint32_t h = i | ((uint32_t)slots[i * 2 + 1] << 16);
            uint16_t who = *(uint16_t *)r;
            uint32_t flags = *(uint32_t *)(r + 0x20);
            static int logged = 0;
            if (logged++ < 8) Log("nav record %u (handle %08x): player %u, flags %x", slot, h, who, flags);
            if (who == (uint16_t)s) hit = h;
            if (flags & 0x2000) { live = h; ++nlive; }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        Log("nav: fault reading the nav records");
    }
    return hit != 0xffffffffu ? hit : nlive == 1 ? live : 0xffffffffu;
}

// Your own nav record (local mode). The nav player number is per client, NOT the server's player
// slot (online you were slot 1 but record 0: push / shutdown hit record 1). Each record's player row
// (system +B8h -> rows, stride D0h, by record +00h) holds the actor's level node at +08h: the local
// player is r14_glb_global_mp's dfb4e911bdaddc39 (the actor the death scripts run on; the other
// player actor there is f1e70acd0dde0312), runtime actor at +10h (...003e).
constexpr uint64_t LOCAL_PLAYER_NODE = 0xdfb4e911bdaddc39ull;
uint32_t NavHandleLocal(uint8_t *nav) {
    uint32_t zero = 0xffffffffu;
    __try {
        uint16_t *slots = *(uint16_t **)(nav + 0xc8);
        uint8_t *recs = *(uint8_t **)(nav + 0xf8);
        uint8_t *rows = **(uint8_t ***)(nav + 0xb8);
        uint32_t n = *(uint16_t *)(nav + 0xf0);
        if (n > 64) n = 64;
        for (uint32_t i = 0; slots && recs && rows && i < n; ++i) {
            uint16_t slot = slots[i * 2];
            if (slot >= n) continue;
            uint16_t who = *(uint16_t *)(recs + (size_t)slot * NAV_STRIDE);
            uint32_t h = i | ((uint32_t)slots[i * 2 + 1] << 16);
            uint64_t node = *(uint64_t *)(rows + (size_t)who * 0xd0 + 8);
            if (node == LOCAL_PLAYER_NODE) return h;
            if (who == 0) zero = h;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        Log("nav: fault reading the nav records (local)");
    }
    return zero;
}

struct KillArgs { uint32_t type; uint64_t sym; } g_kill;
uint32_t *NavFlags(uint8_t *nav, uint32_t h) {
    uint16_t slot = *(uint16_t *)(*(uint8_t **)(nav + 0xc8) + (size_t)(h & 0xffff) * 4);
    return (uint32_t *)(*(uint8_t **)(nav + 0xf8) + (size_t)slot * NAV_STRIDE + 0x20);
}
// The lobby player carries the "dying" bit (100h, CR15IsPlayerDyingExpression) all the time, and
// KillPlayer returns at once on 100h | 80h; the shutdown + respawn themselves are r14_glb_global_mp's
// scripts (loaded with every multiplayer level) reacting to KillPlayer's actor event 737c2e93dbbead32.
// So: clear those bits, then kill (on the game thread, from the deferred queue).
struct KillWatch { uint8_t *nav = nullptr; uint32_t h = 0; ULONGLONG at = 0; int logged = 0; } g_kill_watch;
void __fastcall KillTrampoline(void *cs, uint32_t handle, const float *) {   // run by the deferred queue
    uint32_t *f = NavFlags((uint8_t *)cs, handle);
    uint32_t before = *f;
    *f = before & ~0x180u;
    KillPlayer(cs, handle, g_kill.type, KILL_LIMB, g_kill.sym);
    Log("shutdown: KillPlayer(%p, %08x): flags %x -> %x -> %x", cs, handle, before, before & ~0x180u, *f);
    g_kill_watch = { (uint8_t *)cs, handle, GetTickCount64(), 0 };
}
// (diagnostic) the player's flags at 0.5, 2, 5, 10 s after a shutdown: did the scripts take it?
void WatchKill() {
    static const DWORD at[] = { 500, 2000, 5000, 10000 };
    KillWatch &w = g_kill_watch;
    if (!w.nav || w.logged >= 4 || GetTickCount64() - w.at < at[w.logged]) return;
    Log("shutdown +%lu ms: flags %x", at[w.logged], *NavFlags(w.nav, w.h));
    ++w.logged;
}

// The death sequences are script functions the player script (25b9f751143a5dd0, R15DeathReasonSwitch)
// calls on the Player actor by component name. r14_glb_global_tutorial gives the player those
// components under the names the switch uses; r14_glb_global_mp (the lobby's global level) has the
// same scripts on its players under other names, so in the lobby the call fails ("FunctionCall could
// not find actor / component"). 0x168340 is the engine's find-a-script-component-by-name (out, space,
// actor, name), used by every SScriptBindings::ExternalFunction*: a failed find of a tutorial name is
// retried with the lobby's name for the same script. Nothing in any level changes.
constexpr uintptr_t FIND_SCRIPT_COMPONENT_RVA = 0x168340;
constexpr uint8_t FIND_SCRIPT_COMPONENT_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x08, 0x4c, 0x89, 0x44, 0x24, 0x18, 0x48, 0x89,
                                                    0x54, 0x24, 0x10, 0x56 };
using find_script_component_fn = void *(__fastcall *)(uint8_t *out, void *space, uint64_t actor, uint64_t name);
find_script_component_fn Real_FindScriptComponent = nullptr;
struct NameMap { uint64_t tutorial, lobby; const char *what; };
constexpr NameMap DEATH_NAMES[] = {
    { 0x4C6C8C218C97B7E6ull, 0xC5CB02587476DE17ull, "ImpactDeath (7df05c1589e59f16)" },
    { 0x90259BCB96AC1E88ull, 0xC59C0D5C287A894Eull, "LaserDeath (0857cf65a1af60b8)" },
};
void *__fastcall Hooked_FindScriptComponent(uint8_t *out, void *space, uint64_t actor, uint64_t name) {
    void *r = Real_FindScriptComponent(out, space, actor, name);
    if (*(uint64_t *)out && *(uint16_t *)(out + 8) != 0xffff) return r;       // found
    for (const NameMap &m : DEATH_NAMES)
        if (m.tutorial == name) {
            r = Real_FindScriptComponent(out, space, actor, m.lobby);
            static int logged = 0;
            if (logged++ < 10)
                Log("death script %s: component %016llx -> lobby's %016llx on actor %016llx: %s", m.what, name, m.lobby,
                    actor, *(uint64_t *)out && *(uint16_t *)(out + 8) != 0xffff ? "found" : "still missing");
            break;
        }
    return r;
}

// Push player slot `s` away from her at `speed` m/s (a little upward), or shut their unit down.
bool ControlPlayer(const Pose &me, int s, float speed, bool kill, bool own = false) {
    float tp[3], tv[3];
    uint8_t *nav = FindNav();
    if (!nav || !PlayerAt(s, tp, tv)) { Log("control: no nav system (%p) or player %d", nav, s); return false; }
    uint32_t h = g_local || own ? NavHandleLocal(nav) : NavHandleFor(nav, s);   // (own: your body, on your client)
    if (h == 0xffffffffu) { Log("control: no nav record for player %d", s); return false; }
    uintptr_t queue = *(uintptr_t *)(nav + 0x80) + 0x170;
    if (kill) {
        if (!KillPlayer) return false;
        if (g_kill_watch.nav && GetTickCount64() - g_kill_watch.at < 8000) { Log("shutdown: one is still running"); return false; }
        g_kill.type = g_orders.shutdown_reason != 0xffffffffu ? g_orders.shutdown_reason : KILL_REASON;
        Log("shutdown: death reason %u", g_kill.type);
        g_kill.sym = *(uint64_t *)(*(uint8_t **)(nav + 0x80) + 0x58);
        static const float zero[3] = { 0, 0, 0 };
        Defer(queue, nav, (void *)KillTrampoline, h, zero);
        Log("shutdown: player %d (nav %08x) queued", s, h);
        return true;
    }
    if (!g_nav_set_velocity) return false;
    float d[3] = { tp[0] - me.p[0], tp[1] - me.p[1] + 0.3f, tp[2] - me.p[2] };
    float l = Len(d);
    if (l < 1e-3f) { d[0] = 0; d[1] = 1; d[2] = 0; l = 1; }
    float v[3];
    for (int k = 0; k < 3; ++k) v[k] = tv[k] * 0.2f + d[k] / l * speed;
    Defer(queue, nav, g_nav_set_velocity, h, v);
    Log("push: player %d (nav %08x) at %.1f m/s (%.2f %.2f %.2f)", s, h, speed, v[0], v[1], v[2]);
    return true;
}

void SetMode(Mode m, ULONGLONG now) {
    if (g_brain.mode != m) Log("mode %s -> %s", ModeName(g_brain.mode), ModeName(m));
    g_brain.mode = m;
    g_brain.since = now;
}

void Tick() {
    g_stage = 2;
    if (!HerAlive()) { g_brain = Brain(); return; }
    g_stage = 3;
    Pose me;
    Real_TransformGet(g_her.transforms, &me, g_her.xf);
    LogPhysicsKind();
    ULONGLONG now = GetTickCount64();
    // dt from the performance counter: GetTickCount64 steps in ~16 ms, which made her measured
    // velocity jitter enough to look like a hand still moving her
    LARGE_INTEGER qpc, freq;
    QueryPerformanceCounter(&qpc);
    QueryPerformanceFrequency(&freq);
    static LONGLONG last_qpc = 0;
    float dt = g_brain.have && last_qpc ? (float)(qpc.QuadPart - last_qpc) / (float)freq.QuadPart : TICK_MS / 1000.0f;
    dt = fmaxf(fminf(dt, 0.1f), 0.005f);
    last_qpc = qpc.QuadPart;
    g_brain.last = now;
    // her real velocity: how far she moved since the last tick (works whatever her physics kind)
    float v[3] = { 0, 0, 0 };
    if (g_brain.have)
        for (int k = 0; k < 3; ++k) v[k] = (me.p[k] - g_brain.pos[k]) / dt;
    for (int k = 0; k < 3; ++k) g_brain.pos[k] = me.p[k];
    float pl[3];
    int pslot = -1;
    bool player = NearestPlayer(me.p, pl, &pslot);
    g_stage = 4;
    UpdateSnow();
    WatchKill();
    PollOrders(me);
    if (g_orders.throw_now) {                                  // "throw one at me" (to=<name>: at them)
        g_orders.throw_now = false;
        int ts = g_orders.throw_to[0] ? SlotOf(g_orders.throw_to) : pslot;
        if (ts >= 0 && (player || ts != pslot) && ThrowSnowball(me, ts)) { Event("event threw snowball (asked) to=%s", NameOf(ts)); }
        else Event("error no player to throw at %s", g_orders.throw_to);
    }
    // push / shutdown: at to=<name>, else her player. Someone else's body only moves on their own
    // client (ControlPlayer online works on yours alone): the host sends them a ctl.
    for (int kill = 0; kill < 2; ++kill) {
        float sp = kill ? 0.0f : g_orders.push;
        if (kill ? !g_orders.shutdown : sp <= 0) continue;
        if (kill) g_orders.shutdown = false; else g_orders.push = 0;
        const char *to = kill ? g_orders.kill_to : g_orders.push_to;
        std::string name = to[0] ? to : NameOf(pslot);
        bool remote = !name.empty() && name != g_me && !strcmp(g_net_role, "host");
        int slot = to[0] ? SlotOf(to) : pslot;
        bool ok = remote ? SendCtl(name.c_str(), kill ? "shutdown" : "push", sp, me.p)
                         : slot >= 0 && (to[0] || player) && ControlPlayer(me, slot, sp, kill != 0);
        if (ok && kill) Event("event shut player down to=%s", name.c_str());
        else if (ok) Event("event pushed player speed=%.1f to=%s", sp, name.c_str());
        else Event("error could not %s %s", kill ? "shut down" : "push", name.c_str());
    }
    static ULONGLONG last_state = 0;
    if (now - last_state > 2000) {
        last_state = now;
        float hd = player ? sqrtf((pl[0] - me.p[0]) * (pl[0] - me.p[0]) + (pl[1] - me.p[1]) * (pl[1] - me.p[1])
                                  + (pl[2] - me.p[2]) * (pl[2] - me.p[2])) : -1.0f;
        Event("state mode=%s order=%s her=%.2f,%.2f,%.2f player=%.2f,%.2f,%.2f dist=%.2f held=%d speaker=%d net=%s host=%s me=%s members=%s ai=%s",
              ModeName(g_brain.mode), OrderName(g_orders.order), me.p[0], me.p[1], me.p[2], pl[0], pl[1], pl[2], hd,
              (int)g_brain.held, g_spk.playing ? 1 : 0, g_net_role, g_net_host, g_me, g_net_members, g_net_ai);
    }
    static ULONGLONG last_test = 0;                           // (EDITH.ini snow_test=1: a throw every 8 s)
    if (g_snow_test && player && now - last_test > 8000) { last_test = now; ThrowSnowball(me, pslot); }

    // held? (her touch-interact grab counts) -- a grab, then a release while moving = thrown
    // (a grab here is this machine's player: online only your own hands show in her grab counts)
    bool held = Held();
    const char *by = g_local || g_network ? g_me : NameOf(pslot);
    if (held && !g_brain.held) {
        Log("grabbed (nearest player slot %d)", pslot);
        Event("event grabbed by=%s", by);
        SetMode(TUMBLE, now);
        g_brain.cause = HELD;
        g_brain.culprit = g_own_slot >= 0 && (g_local || g_network) ? g_own_slot : pslot;
    }
    if (held) g_brain.last_push = now;
    if (!held && g_brain.held) {
        float sp = Len(v);
        g_brain.cause = sp > THROWN_SPEED ? THROWN : BUMP;    // let go gently = no snowball
        Log("released at %.2f m/s: %s", sp, CauseName(g_brain.cause));
        Event("event released speed=%.1f %s by=%s", sp, CauseName(g_brain.cause), by);
        g_brain.last_push = now;
    }
    g_brain.held = held;

    // pushed? (her velocity isn't what she set; while tumbling, it keeps changing under a hand)
    if (g_brain.have && !held) {
        float off[3] = { v[0] - g_brain.sent[0], v[1] - g_brain.sent[1], v[2] - g_brain.sent[2] };
        float chg[3] = { v[0] - g_brain.prev[0], v[1] - g_brain.prev[1], v[2] - g_brain.prev[2] };
        // a player's head this far off can't have touched her: she hit a wall (or anything) herself.
        // The head is yours (only your own hits are seen here; others report theirs as touches).
        float hp[3] = { pl[0], pl[1], pl[2] }, hv[3];
        bool head = player;
        int hslot = pslot;
        if (g_own_slot >= 0 && PlayerAt(g_own_slot, hp, hv)) { head = true; hslot = g_own_slot; }
        float hd = head ? sqrtf((hp[0] - me.p[0]) * (hp[0] - me.p[0]) + (hp[1] - me.p[1]) * (hp[1] - me.p[1])
                                + (hp[2] - me.p[2]) * (hp[2] - me.p[2])) : 1e9f;
        bool nobody = hd > REACH_DIST;
        static ULONGLONG last_ow = 0;
        if (g_brain.mode != TUMBLE && Len(off) > THROWN_DV && nobody) {
            Log("hit something by herself: %.2f m/s off what she set, nearest head %.2f m", Len(off), hd);
            if (now - last_ow > 1500) { last_ow = now; Event("event hit wall"); }
            g_brain.cause = BUMP;                             // no stare, no snowball: just ow
            SetMode(TUMBLE, now);
            g_brain.last_push = now;
            g_brain.wall = true;
        } else if (g_brain.mode == TUMBLE && nobody && Len(chg) > WALL_DV) {   // flung into a wall
            Log("hit something while tumbling: %.2f m/s change, nearest head %.2f m", Len(chg), hd);
            if (now - last_ow > 1500) { last_ow = now; Event("event hit wall"); }
            g_brain.last_push = now;
        } else if (g_brain.mode != TUMBLE && Len(off) > THROWN_DV) {
            // a headbutt: a player's head right at her when she was knocked
            g_brain.cause = hd < HEADBUTT_DIST ? HEADBUTT : BUMP;
            g_brain.wall = false;
            g_brain.culprit = hslot;
            if (g_network && !InRoom(NameOf(hslot))) {        // someone without the mod (she isn't in
                g_brain.cause = BUMP;                         // their game): a plain bump, no stare, no
                g_brain.wall = true;                          // ball back (user: ignore them)
            }
            Log("pushed: %.2f m/s off what she set (velocity %.2f %.2f %.2f), nearest head %.2f m: %s", Len(off),
                v[0], v[1], v[2], hd, CauseName(g_brain.cause));
            Event("event %s by=%s", g_brain.cause == HEADBUTT ? "headbutt" : "bumped", NameOf(hslot));
            SetMode(TUMBLE, now);
            g_brain.last_push = now;
        } else if (g_brain.mode == TUMBLE && Len(chg) > HANDLED_DV) {
            g_brain.last_push = now;                          // still being thrown about
        }
    }
    g_brain.prev[0] = v[0]; g_brain.prev[1] = v[1]; g_brain.prev[2] = v[2];
    g_brain.have = true;

    float out[3] = { v[0], v[1], v[2] }, w[3] = { 0, 0, 0 };
    switch (g_brain.mode) {
    case TUMBLE:                                              // free: no thrust, no steering
        g_brain.sent[0] = v[0]; g_brain.sent[1] = v[1]; g_brain.sent[2] = v[2];
        if (!held && now - g_brain.last_push > TUMBLE_MS) {
            SetMode(player && !g_brain.wall ? STARE : FOLLOW, now);   // a wall gets no stare
            g_brain.wall = false;
        }
        return;
    case STARE: {                                             // brake, turn round, stare at you
        float zero[3] = { 0, 0, 0 };
        Thrust(v, zero, dt, out);
        float err = 0;
        bool revenge = g_brain.cause == THROWN || g_brain.cause == HEADBUTT;
        float tp[3], tv[3];
        bool target = revenge && PlayerAt(g_brain.culprit, tp, tv);   // stare at the culprit
        if (!target && player) { tp[0] = pl[0]; tp[1] = pl[1]; tp[2] = pl[2]; target = true; }
        if (target) {
            float dir[3] = { tp[0] - me.p[0], tp[1] - me.p[1], tp[2] - me.p[2] };
            err = FaceTowards(me, dir, w);
        }
        player = target;
        if (!player || (now - g_brain.since > STARE_MS && err < STARE_AIMED) || now - g_brain.since > STARE_MAX_MS) {
            Log("stare done (facing error %.2f rad), cause %s", err, CauseName(g_brain.cause));
            if (revenge && ThrowSnowball(me, g_brain.culprit)) Event("event threw snowball (revenge) to=%s", NameOf(g_brain.culprit));
            g_brain.cause = BUMP;
            SetMode(FOLLOW, now);
        }
        break;
    }
    case FOLLOW: {
        Order o = g_orders.order;
        if (o == O_SPIN && g_orders.endless && now - g_orders.last_dizzy >= DIZZY_MS) {   // "keep going": how long now
            g_orders.last_dizzy = now;
            Event("event dizzy t=%llu %s", (now - g_orders.spin_start) / 1000, g_orders.local ? "flip" : "spin");
        }
        if (o == O_SPIN && !g_orders.endless && now > g_orders.until) {
            ULONGLONG t = (now - g_orders.spin_start) / 1000;
            if (t >= 8) {                                     // a long one: she wobbles about a while
                g_orders.wobble_until = now + WOBBLE_MS;
                Event("event stopped spinning t=%llu", t);
            }
            o = g_orders.order = g_orders.after;
        }
        bool to_player = o == O_FOLLOW || o == O_COME;
        if (to_player && !player) {
            float zero[3] = { 0, 0, 0 };
            Thrust(v, zero, dt, out);
            break;
        }
        // her spot: following, FOLLOW_DIST (COME_DIST) from the player on the line from the player
        // to her, a little up; otherwise the order's point (where she was told to stay / go)
        float spot[3] = { g_orders.target[0], g_orders.target[1], g_orders.target[2] };
        if (to_player) {
            float d[3] = { me.p[0] - pl[0], 0.0f, me.p[2] - pl[2] };
            float h = sqrtf(d[0] * d[0] + d[2] * d[2]);
            if (h < 1e-3f) { d[0] = 1.0f; d[2] = 0.0f; h = 1.0f; }
            float r = o == O_COME ? COME_DIST : FOLLOW_DIST;
            spot[0] = pl[0] + d[0] / h * r; spot[1] = pl[1] + FOLLOW_ABOVE; spot[2] = pl[2] + d[2] / h * r;
        }
        float to[3] = { spot[0] - me.p[0], spot[1] - me.p[1], spot[2] - me.p[2] };
        float dist = Len(to);
        float speed = fminf(dist * GAIN, MAX_SPEED);
        float want[3] = { 0, 0, 0 };
        if (dist > 0.05f) for (int k = 0; k < 3; ++k) want[k] = to[k] / dist * speed;
        Thrust(v, want, dt, out);
        if (o == O_GOTO && dist < 0.2f) {                     // arrived: stay there
            g_orders.order = O_STAY;
            Event("event arrived");
        }
        float lp[3], lv[3];
        int ls = now < g_look_until ? SlotOf(g_look) : -1;
        if (ls >= 0 && PlayerAt(ls, lp, lv)) {                // someone is talking to her: face them
            float look[3] = { lp[0] - me.p[0], lp[1] - me.p[1], lp[2] - me.p[2] };
            FaceTowards(me, look, w);
        } else if (player) {
            float look[3] = { pl[0] - me.p[0], pl[1] - me.p[1], pl[2] - me.p[2] };
            FaceTowards(me, look, w);
        }
        if (o == O_SPIN) {
            if (g_orders.local) Rotate(me.q, g_orders.axis, w);   // her own axis, wherever it points now
            else memcpy(w, g_orders.axis, 12);
            for (int k = 0; k < 3; ++k) w[k] *= g_orders.rate;
        } else if (now < g_orders.wobble_until) {             // dizzy: a drunken wobble on top of the look
            float t = (float)(now % 100000) / 1000.0f, left = (float)(g_orders.wobble_until - now) / WOBBLE_MS;
            w[0] += 2.2f * left * sinf(t * 5.1f);
            w[1] += 1.5f * left * sinf(t * 3.3f + 1.0f);
            w[2] += 2.2f * left * cosf(t * 4.3f);
        }
        static ULONGLONG last_log = 0;
        if (g_verbose && now - last_log > 5000) {
            last_log = now;
            Log("her (%.2f %.2f %.2f) v (%.2f %.2f %.2f) player (%.2f %.2f %.2f) -> %.2f m", me.p[0], me.p[1], me.p[2],
                v[0], v[1], v[2], pl[0], pl[1], pl[2], dist);
        }
        break;
    }
    }
    g_stage = 20;
    SetVelocities(out, w);
    g_brain.sent[0] = out[0]; g_brain.sent[1] = out[1]; g_brain.sent[2] = out[2];
}

// Her thruster jets, on every machine (particles aren't networked): each jet's emission follows
// the thrust she is making, which is measured the same way everywhere, from how her motion
// changes. Thrust along `a` comes from the jets on the far side (a jet's exhaust points out of
// its corner, pushing her the other way); turning adds a little to all of them; hovering idles.
struct Jets {
    uint8_t *cs = nullptr;
    uint32_t h[8];
    float sent[8];
    bool lit[8];                                              // jet i is firing
    float pos[3], vel[3], acc[3];
    float q[4];
    int have = 0;                                             // 0 none, 1 position, 2 velocity
    LONGLONG last_qpc = 0;
    ULONGLONG refreshed = 0;
    int tries = 0;
} g_jets;

bool g_jet_test = false;                                     // EDITH.ini jets_test=1: every jet full on

// The particle system: the one of the space's systems that has her first jet (the space table is
// keyed by system symbol, not by the rows' names; logged once so the key can be pinned).
uint64_t g_jet_key = 0;
uint8_t *FindJetSystem(void *space) {
    if (g_jet_key) return FindSystem(space, g_jet_key);
    uint8_t *table = *(uint8_t **)((uint8_t *)space + 0x420);
    uint64_t count = *(uint64_t *)((uint8_t *)space + 0x450);
    for (uint64_t k = 0; table && k < count && k < 1024; ++k) {
        uint8_t *cs = *(uint8_t **)(table + k * 16 + 8);
        if (!cs) continue;
        uint32_t h = 0xffffffffu;
        __try { h = Instance(cs, HER_ACTOR, JET_NAMES[0]); } __except (EXCEPTION_EXECUTE_HANDLER) {}
        if (h == 0xffffffffu) continue;
        g_jet_key = *(uint64_t *)(table + k * 16);
        auto base = (uint8_t *)GetModuleHandleW(nullptr);
        Log("her jets live in system %p (key %016llx, vtable rva %llx)", cs, g_jet_key, *(uint8_t **)cs - base);
        return cs;
    }
    return nullptr;
}

// A particle effect only emits once its component is enabled: CParticleCS::InitParticleCI clears
// every emitter's run bit (0x40) and OnComponentEnabled (virtual +58h) sets it again. In live a
// script enables them; hers would have. Component systems keep a u16 mask of disabling categories
// per slot at +E0h, enabled slots packed first (count u16 +F4h); virtual +200h EnableComponent
// (cs, handle, categories) clears those bits (libr15 CDecalCS::EnableComponent 0x15bc90c).
using enable_fn = void(__fastcall *)(void *cs, uint32_t handle, uint16_t categories);
uint16_t JetMask(int i) {
    uint8_t *cs = g_jets.cs;
    uint16_t slot = *(uint16_t *)(*(uint8_t **)(cs + 0xc8) + (size_t)(g_jets.h[i] & 0xffff) * 4);
    return *(uint16_t *)(*(uint8_t **)(cs + 0xe0) + (size_t)slot * 2);
}
constexpr uintptr_t PARTICLE_ENABLE_RVA = 0x433f40;          // CParticleCS vtable (rva 1711ba8) slot +200h
constexpr uintptr_t PARTICLE_ON_ENABLED_RVA = 0x44af80;      // its +50h: OnComponentEnabled (run bit on, restart)
using on_enabled_fn = void(__fastcall *)(void *cs, uint32_t handle);
// The effect's first emitter has its run bit (0x40 at emitter +58h; emitters at effect +38h, stride
// 70h, count +40h; PC OnComponentEnabled reaches them from effect+8 at +30h/+38h, the same place)
bool JetRunning(int i) {
    uint8_t *cs = g_jets.cs;
    uint16_t slot = *(uint16_t *)(*(uint8_t **)(cs + 0xc8) + (size_t)(g_jets.h[i] & 0xffff) * 4);
    uint8_t *fx = *(uint8_t **)(*(uint8_t **)(cs + 0xf8) + (size_t)slot * 0x18 + 0x10);
    if (!fx || !*(uint64_t *)(fx + 0x40)) return false;
    return (*(uint32_t *)(*(uint8_t **)(fx + 0x38) + 0x58) & 0x40) != 0;
}
void EnableJets(bool log) {
    void *fn = (*(void ***)g_jets.cs)[0x200 / 8];
    if ((uint8_t *)fn != (uint8_t *)GetModuleHandleW(nullptr) + PARTICLE_ENABLE_RVA) {
        if (log) Log("  particle system +200h is %p, not EnableComponent: jets left as they are", fn);
        return;
    }
    for (int i = 0; i < 8; ++i) {
        uint16_t m = JetMask(i);
        if (m) {
            ((enable_fn)(*(void ***)g_jets.cs)[0x200 / 8])(g_jets.cs, g_jets.h[i], m);
            if (log) Log("  jet %d was disabled (categories %04x): enabled, now %04x", i, m, JetMask(i));
        }
    }
}

// A jet on or off. The emission scale alone never quietens the effect (user: all 8 always
// showing at 0.08), so each jet is started / stopped like the engine does when a component is
// enabled / disabled. EnableComponent only calls those callbacks when cs+ACh == 0, and in the
// lobby it is 1, so they are called here: +50h OnComponentEnabled (run bit on, restart) and +58h
// OnComponentDisabled (0x44ac80, run bit off; live particles fade out). (libr15 has them swapped.)
constexpr uintptr_t PARTICLE_ON_DISABLED_RVA = 0x44ac80;
bool LightJet(int i, bool on) {
    void **vt = *(void ***)g_jets.cs;
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    void *fn = vt[(on ? 0x50 : 0x58) / 8];
    if ((uint8_t *)fn != base + (on ? PARTICLE_ON_ENABLED_RVA : PARTICLE_ON_DISABLED_RVA)) {
        static bool said = false;
        if (!said) { said = true; Log("  particle system +50h/+58h are not OnComponentEnabled/Disabled: jets stay as they are"); }
        return false;
    }
    if (JetRunning(i) != on) ((on_enabled_fn)fn)(g_jets.cs, g_jets.h[i]);
    return true;
}

void SetJet(int i, float rate) {
    uintptr_t queue = *(uintptr_t *)(g_jets.cs + 0x80) + 0x170;
    DeferFloat(queue, g_jets.cs, g_set_emission, g_jets.h[i], rate);
    g_jets.sent[i] = rate;
}

void UpdateJets() {
    if (!g_her.space) { g_jets = Jets(); return; }
    if (!g_jets.cs) {                                         // her jet instances (once her level is up)
        if (g_jets.tries >= 300) return;
        ++g_jets.tries;
        uint8_t *cs = FindJetSystem(g_her.space);
        int found = 0;
        for (int i = 0; i < 8; ++i) {
            g_jets.h[i] = Instance(cs, HER_ACTOR, JET_NAMES[i]);
            found += g_jets.h[i] != 0xffffffffu;
            g_jets.sent[i] = -1.0f;
        }
        if (found < 8) {
            if (g_jets.tries == 300) Log("her jets: %d of 8 found in particle system %p: no thrusters", found, cs);
            return;
        }
        g_jets.cs = cs;
        Log("her jets: particle system %p, handles %08x .. %08x", cs, g_jets.h[0], g_jets.h[7]);
        for (int i = 0; i < 8; ++i) {                         // (diagnostic) is an effect running behind each?
            uint16_t slot = *(uint16_t *)(*(uint8_t **)(cs + 0xc8) + (size_t)(g_jets.h[i] & 0xffff) * 4);
            uint8_t *rec = *(uint8_t **)(cs + 0xf8) + (size_t)slot * 0x18;
            Log("  jet %d: slot %u record %016llx %016llx effect %p", i, slot, *(uint64_t *)rec,
                *(uint64_t *)(rec + 8), *(void **)(rec + 0x10));
        }
        EnableJets(true);
        // (diagnostic) did OnComponentEnabled reach the emitters? effect +38h emitters (stride 70h,
        // count +40h), run bit 0x40 at emitter +58h (libr15 OnComponentEnabled); cs+ACh != 0 skips it
        Log("  particle system +ACh = %d, enabled count %u", *(int32_t *)(cs + 0xac), *(uint16_t *)(cs + 0xf4));
        for (int i = 0; i < 8; ++i) {
            uint16_t slot = *(uint16_t *)(*(uint8_t **)(cs + 0xc8) + (size_t)(g_jets.h[i] & 0xffff) * 4);
            uint8_t *fx = *(uint8_t **)(*(uint8_t **)(cs + 0xf8) + (size_t)slot * 0x18 + 0x10);
            if (!fx) continue;
            uint8_t *em = *(uint8_t **)(fx + 0x38);
            uint64_t n = *(uint64_t *)(fx + 0x40);
            char line[256]; int len = 0;
            for (uint64_t e = 0; em && e < n && e < 8; ++e)
                len += snprintf(line + len, sizeof line - len, " %08x", *(uint32_t *)(em + e * 0x70 + 0x58));
            Log("  jet %d effect %p: %llu emitter(s), flags%s", i, fx, n, line);
        }
    }
    Pose me;
    Real_TransformGet(g_her.transforms, &me, g_her.xf);
    LARGE_INTEGER qpc, freq;
    QueryPerformanceCounter(&qpc);
    QueryPerformanceFrequency(&freq);
    float dt = g_jets.last_qpc ? (float)(qpc.QuadPart - g_jets.last_qpc) / (float)freq.QuadPart : TICK_MS / 1000.0f;
    dt = fmaxf(fminf(dt, 0.1f), 0.005f);
    g_jets.last_qpc = qpc.QuadPart;
    float v[3] = { 0, 0, 0 }, a[3] = { 0, 0, 0 };
    if (g_jets.have >= 1) for (int k = 0; k < 3; ++k) v[k] = (me.p[k] - g_jets.pos[k]) / dt;
    if (g_jets.have >= 2) for (int k = 0; k < 3; ++k) a[k] = (v[k] - g_jets.vel[k]) / dt;
    if (Len(a) > JET_BUMP) a[0] = a[1] = a[2] = 0;           // hit, thrown, held: not her thrusters
    float blend = fminf(dt / JET_SMOOTH, 1.0f);
    for (int k = 0; k < 3; ++k) {
        g_jets.acc[k] += (a[k] - g_jets.acc[k]) * blend;
        g_jets.pos[k] = me.p[k];
        g_jets.vel[k] = v[k];
    }
    // turning: how far her orientation moved this tick (angle of q_now * q_prev^-1)
    float turn = 0;
    if (g_jets.have >= 1) {
        float d = fabsf(me.q[0] * g_jets.q[0] + me.q[1] * g_jets.q[1] + me.q[2] * g_jets.q[2] + me.q[3] * g_jets.q[3]);
        turn = 2.0f * acosf(fminf(d, 1.0f)) / dt;              // rad/s
    }
    for (int k = 0; k < 4; ++k) g_jets.q[k] = me.q[k];
    if (g_jets.have < 2) { ++g_jets.have; return; }

    float am = Len(g_jets.acc), dir[3] = { 0, 0, 0 };
    if (am > 1e-3f) for (int k = 0; k < 3; ++k) dir[k] = g_jets.acc[k] / am;
    float push = fminf(am / THRUST, 1.0f);
    float spin = fminf(turn / MAX_TURN, 1.0f) * 0.35f;
    ULONGLONG now = GetTickCount64();
    bool refresh = now - g_jets.refreshed > 1000;            // re-send now and then (a respawned effect)
    if (refresh) {
        g_jets.refreshed = now;
        EnableJets(false);                                    // (something may disable them again)
    }
    for (int i = 0; i < 8; ++i) {
        float c[3] = { JET_CORNER[i][0] * 0.57735f, JET_CORNER[i][1] * 0.57735f, JET_CORNER[i][2] * 0.57735f }, cw[3];
        Rotate(me.q, c, cw);                                  // her corner, in the world
        float facing = fmaxf(-Dot(cw, dir), 0.0f);            // 0..1: on the side away from the thrust
        float share = g_jet_test ? 1.0f : fminf(push * facing + spin, 1.0f);
        bool lit = share > JET_ON || (g_jets.lit[i] && share > JET_OFF);
        if (lit != g_jets.lit[i] || refresh) {
            if (!LightJet(i, lit)) lit = true;               // (can't switch: leave it running)
            g_jets.lit[i] = lit;
        }
        float rate = lit ? fmaxf(share, JET_MIN) : 0.0f;
        if (refresh || fabsf(rate - g_jets.sent[i]) > 0.03f) SetJet(i, rate);
    }
    static ULONGLONG last_log = 0;
    if (g_verbose && now - last_log > 5000) {
        last_log = now;
        Log("jets: thrust %.2f m/s^2 (%.2f %.2f %.2f), turn %.2f rad/s, rates %.2f %.2f %.2f %.2f %.2f %.2f %.2f %.2f, running %d%d%d%d%d%d%d%d",
            am, dir[0], dir[1], dir[2], turn, g_jets.sent[0], g_jets.sent[1], g_jets.sent[2], g_jets.sent[3],
            g_jets.sent[4], g_jets.sent[5], g_jets.sent[6], g_jets.sent[7], JetRunning(0), JetRunning(1),
            JetRunning(2), JetRunning(3), JetRunning(4), JetRunning(5), JetRunning(6), JetRunning(7));
    }
}

Pose *__fastcall Hooked_TransformGet(void *cs, Pose *out, uint32_t handle) {
    Pose *r = Real_TransformGet(cs, out, handle);
    if (!t_busy && GetCurrentThreadId() == g_main_tid) {      // (clients too: her jets run everywhere)
        t_busy = true;
        __try {
            Note((uint8_t *)cs);                     // register its game space; look for her there
        } __except (EXCEPTION_EXECUTE_HANDLER) {
        }
        t_busy = false;
    }
    return r;
}

// Her mood faces (tools/make_port_faces.py, build_satellite --port-faces): one I/O port per face in
// the same seat on her. Her own port (index her + 1) is happy; EDITH.ini face_first.. are angry,
// dizzy, surprised, hurt, annoyed. One is shown at a time: CModelCS +58h OnComponentDisabled sets the
// model's visibility mask to 0, +50h OnComponentEnabled puts its own mask back (record +4).
// Order "face <name> [seconds]" (the AI picks by mood); after the seconds she is happy again.
constexpr uintptr_t MODEL_CS_VTABLE_RVA = 0x1716710;
constexpr uintptr_t MODEL_ON_ENABLED_RVA = 0x4b7ea0, MODEL_ON_DISABLED_RVA = 0x4b7b90;
const char *const FACE_NAMES[] = { "happy", "angry", "dizzy", "surprised", "hurt", "annoyed" };
constexpr int MAX_FACES = 6;
unsigned g_face_first = 0, g_face_count = 0;
struct Faces {
    uint8_t *cs = nullptr;
    uint32_t h[MAX_FACES] = {};
    int n = 0, tries = 0;
    volatile LONG want = 0;
    int shown = -1;
    ULONGLONG until = 0, asserted = 0;
} g_faces;

uint64_t FaceActor(int i) {
    return i == 0 ? HER_ACTOR + 1 : 0x0000FFFFFFFF0000ull | ((g_face_first + i - 1) & 0xffff);
}

int FaceIndex(const char *name) {
    for (int i = 0; i < MAX_FACES; ++i)
        if (!_strnicmp(name, FACE_NAMES[i], strlen(FACE_NAMES[i]))) return i;
    return -1;
}

bool SetFace(const char *name, float seconds) {
    int i = FaceIndex(name);
    if (i < 0 || (i > 0 && (unsigned)i > g_face_count)) return false;
    g_faces.want = i;
    g_faces.until = i && seconds > 0 ? GetTickCount64() + (ULONGLONG)(fminf(seconds, 600.0f) * 1000.0f) : 0;
    return true;
}

void UpdateFaces() {
    if (!g_face_count) return;
    if (!g_her.space) { int w = g_faces.want; g_faces = Faces(); g_faces.want = w; return; }
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    if (!g_faces.cs) {
        if (g_faces.tries >= 300) return;
        ++g_faces.tries;
        uint8_t *table = *(uint8_t **)((uint8_t *)g_her.space + 0x420);
        uint64_t count = *(uint64_t *)((uint8_t *)g_her.space + 0x450);
        for (uint64_t k = 0; table && k < count && k < 1024 && !g_faces.cs; ++k) {
            uint8_t *cs = *(uint8_t **)(table + k * 16 + 8);
            if (!cs || *(uint8_t **)cs != base + MODEL_CS_VTABLE_RVA) continue;
            if (AnyInstance(cs, FaceActor(0)) != 0xffffffffu) g_faces.cs = cs;
        }
        if (!g_faces.cs) {
            if (g_faces.tries == 300) Log("faces: no model system with her port: one face only");
            return;
        }
        void **vt = *(void ***)g_faces.cs;
        if ((uint8_t *)vt[0x50 / 8] != base + MODEL_ON_ENABLED_RVA || (uint8_t *)vt[0x58 / 8] != base + MODEL_ON_DISABLED_RVA) {
            Log("faces: model system +50h/+58h not as expected: one face only");
            g_face_count = 0;
            return;
        }
        int n = 1 + (int)(g_face_count < MAX_FACES - 1 ? g_face_count : MAX_FACES - 1);
        for (int i = 0; i < n; ++i) {
            g_faces.h[i] = AnyInstance(g_faces.cs, FaceActor(i));
            if (g_faces.h[i] == 0xffffffffu) {
                Log("faces: port %d (actor %016llx) has no model: one face only", i, FaceActor(i));
                g_face_count = 0;
                return;
            }
        }
        g_faces.n = n;
        g_faces.shown = -1;
        Log("faces: model system %p, %d ports (%08x .. %08x)", g_faces.cs, n, g_faces.h[0], g_faces.h[n - 1]);
    }
    ULONGLONG now = GetTickCount64();
    if (g_faces.until && now >= g_faces.until) { g_faces.until = 0; g_faces.want = 0; }
    int want = g_faces.want < g_faces.n ? (int)g_faces.want : 0;
    if (want == g_faces.shown && now - g_faces.asserted < 1000) return;   // re-asserted each second
    void **vt = *(void ***)g_faces.cs;
    for (int i = 0; i < g_faces.n; ++i)
        ((on_enabled_fn)vt[(i == want ? 0x50 : 0x58) / 8])(g_faces.cs, g_faces.h[i]);
    if (want != g_faces.shown && g_verbose) Log("face: %s", FACE_NAMES[want]);
    g_faces.shown = want;
    g_faces.asserted = now;
}

// --- Edith on the network (docs/networkplan.md) --------------------------------------------------
// One Edith per match: every client with the plugin keeps a WebSocket to the relay (Railway/SparkAPI
// edith_relay.py), says who it is and who else is in its match, and the relay picks the host.
// Phase 1 (presence): hello + room, logged and on the state line. Phases 2-3 (one body, hands on) and
// 5 (other players' speech reaching the host): below UpdateNet. Her ears on voice chat: UpdateVoip.
// Names come from the player table like EchoXR-Hands: GetUserName(netgame, slot) per occupied slot;
// yours is the slot whose head is at your ears (local mode's rule), or EDITH.ini my_name.
constexpr uintptr_t GET_USERNAME_RVA = 0x1c98c0;
constexpr uint8_t GET_USERNAME_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x08, 0x57, 0x48, 0x83, 0xec, 0x20, 0x0f, 0xb7 };
using get_username_fn = const char *(__fastcall *)(uint8_t *ng, uint16_t slot);
get_username_fn GetUserNameFn = nullptr;
char g_relay[256] = "wss://sparkapi-production-e6df.up.railway.app/edith/ws";
char g_my_name[64] = "";
char g_debug_roster[256] = "";                                // (testing) names added to your match's roster
constexpr const char *NET_BUILD = "sat-p3";
bool g_ai_configured = false;                                 // EDITH.ini ai= (her voice companion)

// Occupied slots and their display names (POD only: it runs under __try, the table can change).
int ReadNames(uint8_t *ng, SlotName *out, int max) {
    int n = 0;
    __try {
        uint16_t count = *(uint16_t *)(ng + 0xe2);
        if (count == 0 || count > 32) count = 16;
        for (uint16_t s = 0; s < count && n < max; ++s) {
            if (*(uint64_t *)(ng + (size_t)s * 0x250 + 0x3c0) == 0) continue;
            const char *nm = GetUserNameFn(ng, s);
            if (!nm || !nm[0]) continue;
            out[n].slot = s;
            strncpy_s(out[n].name, nm, _TRUNCATE);
            ++n;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { return -1; }
    return n;
}

// Your slot: the occupied one whose head is at the game's audio listener, within 1.5 m.
int OwnSlot() {
    if (!g_ear_ok) return -1;
    float ear[3] = { g_ear[0], g_ear[1], g_ear[2] }, best = 1.5f * 1.5f;
    int own = -1;
    for (int s = 0; s < 16; ++s) {
        float p[3], v[3];
        if (!PlayerAt(s, p, v)) continue;
        float d = (p[0] - ear[0]) * (p[0] - ear[0]) + (p[1] - ear[1]) * (p[1] - ear[1]) + (p[2] - ear[2]) * (p[2] - ear[2]);
        if (d < best) { best = d; own = s; }
    }
    return own;
}

// Which slot is YOU: the one occupied slot whose player has no remote body (EchoXR-Hands' rule; the
// R14RemotePlayer system holds every other player's body). The old "head at your ears" guess flipped
// between nearby players in a busy lobby (user, 2026-10-18: her brain saw PIBBLE, Hi, Ivan... as you),
// which broke her room on the relay and who she answered. POD only: it runs under __try.
constexpr uint64_t SYM_REMOTE_PLAYER = 0x999d680b6b01b67eull;   // R14RemotePlayer
int IsRemote(uint8_t *cs, uint64_t actor) {
    using lookup_fn = uint32_t *(__fastcall *)(void *, uint64_t *, uint64_t, int64_t);
    using valid_fn = int(__fastcall *)(void *, uint32_t);
    void **vt = *(void ***)cs;
    uint64_t tmp = 0;
    uint32_t *hp = ((lookup_fn)vt[0x1a8 / 8])(cs, &tmp, actor, -1);
    if (!hp || (*hp & 0xffff) == 0xffff) return 0;
    return ((valid_fn)vt[0x1c8 / 8])(cs, *hp) ? 1 : 0;
}
int LocalSlotByBody(uint8_t *ng, const SlotName *names, int n) {
    __try {
        uint8_t *cs[8];
        int ncs = 0;
        for (auto &x : g_seen) {
            if (!x.space || *(void **)(x.transforms + 0x80) != x.space || ncs >= 8) continue;
            uint8_t *c = FindSystem(x.space, SYM_REMOTE_PLAYER);
            bool dup = false;
            for (int i = 0; i < ncs; ++i) dup |= cs[i] == c;
            if (c && !dup) cs[ncs++] = c;
        }
        if (!ncs) return -1;
        int local = -1, nolocal = 0;
        for (int i = 0; i < n; ++i) {
            int s = names[i].slot;
            const uint64_t *raw = (const uint64_t *)(ng + (size_t)s * 0x250 + 0x180);
            uint64_t cand[3] = { raw[0], raw[1], 0 };
            uint64_t out[2] = { raw[0], raw[1] };
            if (SlotActor) { SlotActor(ng, (uint8_t *)out, (uint32_t)s); cand[2] = out[0]; }
            bool remote = false;
            for (int c = 0; c < 3 && !remote; ++c)
                if (cand[c] && cand[c] != ~0ull)
                    for (int k = 0; k < ncs && !remote; ++k) remote = IsRemote(cs[k], cand[c]) == 1;
            if (!remote) { local = s; ++nolocal; }
        }
        return nolocal == 1 ? local : -2;                     // -2: not sure (keep what we had)
    } __except (EXCEPTION_EXECUTE_HANDLER) { return -1; }
}

void UpdateNet(uint8_t *ng) {
    static ULONGLONG last = 0;
    ULONGLONG now = GetTickCount64();
    if (!GetUserNameFn || now - last < 1000) return;
    last = now;
    SlotName names[32];
    int n = ReadNames(ng, names, 32);
    if (n < 0) return;
    memcpy(g_names, names, sizeof names);                     // (who is who: orders and events by name)
    g_nnames = n;
    const char *how = "the one player without a remote body";
    int body = LocalSlotByBody(ng, names, n);
    bool known = false;
    for (int i = 0; i < n; ++i) known |= names[i].slot == g_own_slot;
    if (body >= 0) g_own_slot = body;
    else if (!known) {                                        // not sure yet and nothing to keep: the old guess
        int own = OwnSlot();
        if (own >= 0) g_own_slot = own;
        how = "the head at your ears";
    }
    std::string me = g_my_name;
    if (me.empty())
        for (int i = 0; i < n; ++i)
            if (names[i].slot == g_own_slot) me = names[i].name;
    static std::string said_me;
    if (me.empty()) {
        if (said_me != "?") { said_me = "?"; Log("edith net: waiting to know which player is you (%d in the match)", n); }
        return;
    }
    if (me != said_me) { said_me = me; Log("edith net: you are '%s' (%s)", me.c_str(), g_my_name[0] ? "EDITH.ini my_name" : how); }
    strncpy_s(g_me, me.c_str(), _TRUNCATE);
    if (!g_network) return;
    std::vector<std::string> others;
    for (int i = 0; i < n; ++i)
        if (me != names[i].name) others.push_back(names[i].name);
    for (const char *p = g_debug_roster; *p;) {               // EDITH.ini debug_roster=a,b: fake players
        const char *e = strchr(p, ',');
        std::string nm(p, e ? e - p : strlen(p));
        if (!nm.empty() && nm != me) others.push_back(nm);
        p = e ? e + 1 : p + strlen(p);
    }
    EdithNet_SetHello(me, others, g_ai_configured, NET_BUILD);

    EdithRoom room = EdithNet_Room();
    const char *role = !room.connected ? "off" : room.host.empty() ? "alone" : room.host == me
                       ? (room.members.size() > 1 ? "host" : "alone") : "puppet";
    std::string members;
    for (auto &m : room.members) members += (members.empty() ? "" : ",") + m;
    static std::string seen;
    std::string now_seen = std::string(role) + "|" + room.host + "|" + members;
    if (now_seen != seen) {
        seen = now_seen;
        Log("edith net: %s (host '%s', members %s)", role, room.host.c_str(), members.empty() ? "-" : members.c_str());
        Event("net %s host=%s members=%s", role, room.host.c_str(), members.c_str());
    }
    strcpy_s(g_net_role, role);
    strncpy_s(g_net_host, room.host.c_str(), _TRUNCATE);
    strncpy_s(g_net_members, members.c_str(), _TRUNCATE);
    std::string ai;
    for (auto &m : room.ai) ai += (ai.empty() ? "" : ",") + m;
    strncpy_s(g_net_ai, ai.c_str(), _TRUNCATE);
    g_net_self = 0xff;
    for (size_t i = 0; i < room.members.size() && i < 255; ++i)
        if (room.members[i] == me) g_net_self = (uint8_t)i;
}

// Phase 2 (one body): the host sends her state every tick; everyone else's copy of her follows it.
//   EDS1 (64 B, little-endian): "EDS1", seq u32, owner u8 (index into the room's members),
//   pos 3xf32, quat 4xf32 (x y z w), vel 3xf32, angular vel 3xf32 (world, rad/s), face u8, mode u8,
//   flags u8 (bit 0: held). The relay wraps it as "EDR1" + len u8 + sender name + EDS1.
// Phase 3 (hands on): whoever holds her owns her body and sends EDS1 with the held bit; the host and
// the other puppets follow that instead. Grabs, releases and hits are reported to the host as
//   {"t":"touch","what":"grabbed"|"released"|"hit","vel":[x,y,z],"kind":"headbutt"|"bump"}
// and the host aims a push / shutdown at another player with {"t":"ctl","to":..,"do":..,"speed":..,"at":[her]}
// ("from" is the relay's stamp):
// their own client moves their body.
constexpr size_t EDS1_SIZE = 64;
constexpr float PUPPET_GAIN = 5.0f;      // (m/s) per m she is off the host's state
constexpr float PUPPET_FIX = 4.0f;       // m/s: at most this much correction on top of her velocity
constexpr float PUPPET_TURN = 5.0f;      // (rad/s) per rad of orientation error
constexpr float PUPPET_MAX_TURN = 12.0f; // rad/s
constexpr float PUPPET_SNAP = 1.0f;      // m: further off than this, she is teleported
constexpr float PUPPET_LEAD = 0.25f;     // s: dead reckoning at most this far past the last state
constexpr DWORD PUPPET_STALE_MS = 2000;  // no state this long: back to her own brain (local mode)
constexpr DWORD HOLD_STALE_MS = 300;     // the holder's state this old: not holding any more
constexpr DWORD HIT_FREE_MS = 400;       // after a hit a puppet lets her fly while the host takes it

struct NetState {
    bool have = false;
    ULONGLONG at = 0;                                         // when it arrived
    std::string from;
    uint32_t seq = 0;
    uint8_t owner = 0, face = 0, mode = 0, flags = 0;
    float p[3], q[4], v[3], w[3];
} g_rx, g_hold_rx;                                            // the host's state; the holder's

void ReadState(NetState &rx, const std::string &from, const uint8_t *d) {
    uint32_t seq;
    memcpy(&seq, d + 4, 4);
    // a new sender, or a seq far behind (its plugin restarted), starts over; otherwise newest only
    if (rx.have && from == rx.from && seq <= rx.seq && rx.seq - seq < 1000) return;
    if (from != rx.from) Log("edith net: following %s's state%s", from.c_str(), &rx == &g_hold_rx ? " (holding her)" : "");
    rx.from = from;
    rx.seq = seq;
    rx.owner = d[8];
    memcpy(rx.p, d + 9, 12);
    memcpy(rx.q, d + 21, 16);
    memcpy(rx.v, d + 37, 12);
    memcpy(rx.w, d + 49, 12);
    rx.face = d[61]; rx.mode = d[62]; rx.flags = d[63];
    rx.at = GetTickCount64();
    rx.have = true;
}

// --- tiny JSON readers for the relay's flat messages ---
std::string JStr(const std::string &s, const char *key) {
    std::string k = std::string("\"") + key + "\":\"";
    size_t p = s.find(k);
    if (p == std::string::npos) return "";
    std::string out;
    for (p += k.size(); p < s.size() && s[p] != '"'; ++p) {
        if (s[p] == '\\' && p + 1 < s.size()) {
            char e = s[++p];
            if (e == 'u' && p + 4 < s.size()) {                 // \uXXXX: keep ASCII, drop the rest
                unsigned v = strtoul(s.substr(p + 1, 4).c_str(), nullptr, 16);
                p += 4;
                if (v >= 0x20 && v < 0x80) out += (char)v;
                continue;
            }
            out += e == 'n' ? ' ' : e;
        } else out += s[p];
    }
    return out;
}
float JNum(const std::string &s, const char *key, float def) {
    std::string k = std::string("\"") + key + "\":";
    size_t p = s.find(k);
    return p == std::string::npos ? def : (float)atof(s.c_str() + p + k.size());
}
bool JVec(const std::string &s, const char *key, float *v) {
    std::string k = std::string("\"") + key + "\":[";
    size_t p = s.find(k);
    if (p == std::string::npos) return false;
    return sscanf_s(s.c_str() + p + k.size(), "%f,%f,%f", &v[0], &v[1], &v[2]) == 3;
}
std::string JEsc(const char *s) {
    std::string o;
    for (; *s; ++s) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') { o += '\\'; o += (char)c; }
        else if (c >= 0x20) o += (char)c;
    }
    return o;
}

// Touches other players reported (the host applies them in the frame's steering).
struct Touch { std::string from, what, kind; float v[3]; bool has_v; };
std::vector<Touch> g_touches;
char g_holder[64] = "";                                       // who holds her (not you), host side
ULONGLONG g_holder_at = 0;

// A puppet's companion heard something for her: the host hears it as theirs (the relay stamps it).
void ForwardHeard(const char *text) {
    if (strcmp(g_net_role, "puppet")) { Log("heard (not a puppet, dropped): %s", text); return; }
    EdithNet_SendText(std::string("{\"t\":\"heard\",\"text\":\"") + JEsc(text) + "\"}");
    Log("heard -> host: %s", text);
}

// The host: push / shut down another player (their client does it to their own body).
bool SendCtl(const char *to, const char *what, float speed, const float *from) {
    if (strcmp(g_net_role, "host")) return false;
    char b[256];
    snprintf(b, sizeof b, "{\"t\":\"ctl\",\"to\":\"%s\",\"do\":\"%s\",\"speed\":%.1f,\"at\":[%.2f,%.2f,%.2f]}",
             JEsc(to).c_str(), what, speed, from[0], from[1], from[2]);
    EdithNet_SendText(b);
    Log("ctl -> %s: %s %.1f", to, what, speed);
    return true;
}

// Her voice for everyone: the host's companion plays a line from the voice pack and says which files
// ("voice <key> [<key>...]"); the host sends the keys to the room, and each puppet plays the same files
// from its own <plugins>\EdithVoice through her speaker (UDP 47323, paced like the companion streams),
// so players without the companion hear her too. Lines not in the pack (streamed) stay host-only.
bool VoiceKeysOk(const char *k) {
    for (; *k; ++k)
        if (!((*k >= '0' && *k <= '9') || (*k >= 'a' && *k <= 'f') || *k == ' ')) return false;
    return true;
}
void SendVoice(const char *keys) {
    if (strcmp(g_net_role, "host") || !VoiceKeysOk(keys) || strlen(keys) > 400) return;
    EdithNet_SendText(std::string("{\"t\":\"voice\",\"keys\":\"") + keys + "\"}");
}
void SendSnow(unsigned k, const float *at, const float *v) {
    if (strcmp(g_net_role, "host")) return;
    char b[192];
    snprintf(b, sizeof b, "{\"t\":\"snow\",\"k\":%u,\"pos\":[%.3f,%.3f,%.3f],\"vel\":[%.3f,%.3f,%.3f]}",
             k, at[0], at[1], at[2], v[0], v[1], v[2]);
    EdithNet_SendText(b);
}
void SendFace(const char *name, float seconds) {             // her face, for puppets without a companion
    if (strcmp(g_net_role, "host")) return;
    char b[128];
    snprintf(b, sizeof b, "{\"t\":\"face\",\"name\":\"%s\",\"s\":%.1f}", JEsc(name).c_str(), seconds);
    EdithNet_SendText(b);
}
std::mutex g_voice_mx;
std::condition_variable g_voice_cv;
std::deque<std::string> g_voice_q;
void VoiceWorker() {
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    sockaddr_in to = {};
    to.sin_family = AF_INET;
    to.sin_port = htons(47323);                                // her speaker (VOICE_PORT)
    inet_pton(AF_INET, "127.0.0.1", &to.sin_addr);
    constexpr size_t CHUNK = 24000 / 10 * 2;                   // 0.1 s of int16 mono 24 kHz
    for (;;) {
        std::string keys;
        {
            std::unique_lock<std::mutex> lk(g_voice_mx);
            g_voice_cv.wait(lk, [] { return !g_voice_q.empty(); });
            keys = g_voice_q.front();
            g_voice_q.pop_front();
        }
        std::vector<char> pcm;
        for (size_t p = 0; p < keys.size();) {
            size_t e = keys.find(' ', p);
            std::string k = keys.substr(p, e == std::string::npos ? std::string::npos : e - p);
            p = e == std::string::npos ? keys.size() : e + 1;
            if (k.size() != 20) continue;
            std::string path = std::string(g_voice_dir) + k + ".pcm";
            FILE *f = nullptr;
            if (fopen_s(&f, path.c_str(), "rb") || !f) { Log("voice: %s not in the pack", k.c_str()); continue; }
            char buf[65536];
            size_t n;
            while ((n = fread(buf, 1, sizeof buf, f)) > 0) pcm.insert(pcm.end(), buf, buf + n);
            fclose(f);
        }
        ULONGLONG t0 = GetTickCount64();
        double sent = 0;
        for (size_t i = 0; i + 1 < pcm.size(); i += CHUNK) {
            int n = (int)min(CHUNK, (pcm.size() - i) & ~(size_t)1);
            sendto(s, pcm.data() + i, n, 0, (sockaddr *)&to, sizeof to);
            sent += n / 2 / 24000.0;
            double ahead = sent - (GetTickCount64() - t0) / 1000.0;
            if (ahead > 0.4) Sleep((DWORD)((ahead - 0.4) * 1000));
        }
        double left = sent - (GetTickCount64() - t0) / 1000.0;
        if (left > 0) Sleep((DWORD)(left * 1000) + 400);       // her tail, then the next line
    }
}
void PlayPack(const std::string &keys) {
    if (!g_voice_dir[0] || !VoiceKeysOk(keys.c_str())) return;
    static bool started = false;
    {
        std::lock_guard<std::mutex> lk(g_voice_mx);
        if (g_voice_q.size() < 6) g_voice_q.push_back(keys);
        if (!started) { started = true; std::thread(VoiceWorker).detach(); }
    }
    g_voice_cv.notify_one();
}

void SendTouch(const char *what, const float *v, const char *kind) {
    char b[192];
    int n = snprintf(b, sizeof b, "{\"t\":\"touch\",\"what\":\"%s\"", what);
    if (v) n += snprintf(b + n, sizeof b - n, ",\"vel\":[%.2f,%.2f,%.2f]", v[0], v[1], v[2]);
    if (kind) n += snprintf(b + n, sizeof b - n, ",\"kind\":\"%s\"", kind);
    snprintf(b + n, sizeof b - n, "}");
    EdithNet_SendText(b);
    Log("touch -> host: %s%s%s", what, kind ? " " : "", kind ? kind : "");
}

// A ctl from the host aimed at you: your own body, as ControlPlayer does it for local mode.
void DoCtl(const std::string &what, float speed) {
    if (!HerAlive() || g_own_slot < 0) { Log("ctl %s: you or she aren't known yet", what.c_str()); return; }
    Pose me;
    Real_TransformGet(g_her.transforms, &me, g_her.xf);
    bool kill = what == "shutdown";
    if (!kill && what != "push") return;
    bool ok = ControlPlayer(me, g_own_slot, speed > 0 ? fminf(speed, PUSH_MAX) : PUSH_SPEED, kill, true);
    Log("ctl from host: %s%s", what.c_str(), ok ? "" : " (failed)");
}

// Your own body, from your companion: "push [m/s]" / "shutdown [reason]" on UDP 127.0.0.1:47325.
// Online only your client moves your body, so a server's ControlPlayer did nothing (10:57, she
// "pushed" and "shut down" you on the server and nothing happened); her snowballs, the server's own
// objects, did land. Every client binds it (never a -server); the first one on a PC wins.
constexpr u_short SELF_PORT = 47325;
SOCKET g_self = INVALID_SOCKET;
void OpenSelf() {
    if (g_server) return;
    WSADATA w;
    WSAStartup(MAKEWORD(2, 2), &w);
    SOCKET sk = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    sockaddr_in a = {};
    a.sin_family = AF_INET;
    a.sin_port = htons(SELF_PORT);
    inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
    if (sk == INVALID_SOCKET || bind(sk, (sockaddr *)&a, sizeof a)) {
        Log("self: port %u busy (another client has it)", SELF_PORT);
        if (sk != INVALID_SOCKET) closesocket(sk);
        return;
    }
    u_long nb = 1;
    ioctlsocket(sk, FIONBIO, &nb);
    g_self = sk;
    Log("self: push / shutdown for your own body on 127.0.0.1:%u", SELF_PORT);
}
void PollSelf() {
    if (g_self == INVALID_SOCKET) return;
    char buf[128];
    for (int k = 0; k < 4; ++k) {
        int n = recv(g_self, buf, sizeof buf - 1, 0);
        if (n <= 0) return;
        buf[n] = 0;
        float sp = 0;
        unsigned r = 0;
        if (!strncmp(buf, "push", 4)) {
            sscanf_s(buf, "push %f", &sp);
            DoCtl("push", sp);
            Event("event pushed player speed=%.1f to=%s", sp > 0 ? fminf(sp, PUSH_MAX) : PUSH_SPEED, g_me);
        } else if (!strncmp(buf, "shutdown", 8)) {
            g_orders.shutdown_reason = sscanf_s(buf, "shutdown %u", &r) == 1 && r < 13 ? r : 0xffffffffu;
            DoCtl("shutdown", 0);
            Event("event shut player down to=%s", g_me);
        } else Log("self: unknown \"%s\"", buf);
    }
}

// Every tick: what the relay forwarded.
void TakeNet() {
    bool host = !strcmp(g_net_role, "host");
    for (auto &m : EdithNet_Take()) {
        const auto *d = (const uint8_t *)m.data.data();
        size_t size = m.data.size();
        if (m.binary) {
            if (size <= 5 || memcmp(d, "EDR1", 4)) continue;
            size_t n = d[4];
            if (5 + n > size) continue;
            std::string from((const char *)d + 5, n);
            const uint8_t *body = d + 5 + n;
            if (size - 5 - n >= EDS1_SIZE && !memcmp(body, "EDS1", 4)) {
                if (body[63] & 1 && from != g_net_host) ReadState(g_hold_rx, from, body);   // someone holds her
                else if (from == g_net_host) ReadState(g_rx, from, body);
            }
            continue;
        }
        std::string t = JStr(m.data, "t"), from = JStr(m.data, "from");
        if (t == "heard" && host) {                           // someone else talked to her
            std::string text = JStr(m.data, "text");
            Log("heard from %s: %s", from.c_str(), text.c_str());
            Event("heard %s %s", from.c_str(), text.c_str());
        } else if (t == "touch" && host) {
            Touch tc{ from, JStr(m.data, "what"), JStr(m.data, "kind"), { 0, 0, 0 }, false };
            tc.has_v = JVec(m.data, "vel", tc.v);
            if (g_touches.size() < 32) g_touches.push_back(tc);
        } else if (t == "ctl" && JStr(m.data, "to") == g_me) {
            DoCtl(JStr(m.data, "do"), JNum(m.data, "speed", 0));
        } else if (t == "voice" && !host && from == g_net_host) { // the host's Edith said a pack line
            PlayPack(JStr(m.data, "keys"));
        } else if (t == "snow" && !host && from == g_net_host) {  // ...threw a ball
            float at[3], v[3];
            if (JVec(m.data, "pos", at) && JVec(m.data, "vel", v)) LaunchSnow((unsigned)JNum(m.data, "k", 0), at, v);
        } else if (t == "face" && !host && from == g_net_host) {  // ...changed face
            SetFace(JStr(m.data, "name").c_str(), JNum(m.data, "s", 0));
        } else {
            static int logged = 0;
            if (logged++ < 20) Log("edith net: got %.80s", m.data.c_str());
        }
    }
}

// The host: grabs, releases and hits other players reported, into her brain (as Tick does its own).
void ApplyTouches(ULONGLONG now) {
    for (auto &t : g_touches) {
        int slot = SlotOf(t.from.c_str());
        const char *by = t.from.c_str();
        if (t.what == "grabbed") {
            strncpy_s(g_holder, by, _TRUNCATE);
            g_holder_at = now;
            SetMode(TUMBLE, now);
            g_brain.cause = HELD;
            g_brain.culprit = slot;
            g_brain.last_push = now;
            Log("grabbed by %s (slot %d)", by, slot);
            Event("event grabbed by=%s", by);
        } else if (t.what == "released") {
            if (!strcmp(g_holder, by)) g_holder[0] = 0;
            float sp = t.has_v ? Len(t.v) : 0.0f;
            if (t.has_v) SetVelocities(t.v, nullptr);
            SetMode(TUMBLE, now);
            g_brain.cause = sp > THROWN_SPEED ? THROWN : BUMP;
            g_brain.culprit = slot;
            g_brain.last_push = now;
            g_brain.have = false;                             // (she was following their hand: measure afresh)
            if (t.has_v) memcpy(g_brain.sent, t.v, 12);
            Log("released by %s at %.2f m/s: %s", by, sp, CauseName(g_brain.cause));
            Event("event released speed=%.1f %s by=%s", sp, CauseName(g_brain.cause), by);
        } else if (t.what == "hit") {
            if (t.has_v) { SetVelocities(t.v, nullptr); memcpy(g_brain.sent, t.v, 12); }
            g_brain.cause = t.kind == "headbutt" ? HEADBUTT : BUMP;
            g_brain.culprit = slot;
            g_brain.wall = false;
            SetMode(TUMBLE, now);
            g_brain.last_push = now;
            g_brain.have = false;
            Log("%s by %s", CauseName(g_brain.cause), by);
            Event("event %s by=%s", g_brain.cause == HEADBUTT ? "headbutt" : "bumped", by);
        }
    }
    g_touches.clear();
}

// Her state to the group, measured from her motion (like her jets, whatever her mode): the host's
// every tick, or a puppet's while its player holds her (`holding`).
void SendState(bool holding) {
    static float pp[3], pq[4];
    static LONGLONG pqpc = 0;
    static uint32_t seq = 0;
    if ((!holding && strcmp(g_net_role, "host")) || !HerAlive()) { pqpc = 0; return; }
    Pose me;
    Real_TransformGet(g_her.transforms, &me, g_her.xf);
    LARGE_INTEGER qpc, freq;
    QueryPerformanceCounter(&qpc);
    QueryPerformanceFrequency(&freq);
    float dt = pqpc ? (float)(qpc.QuadPart - pqpc) / (float)freq.QuadPart : 0.0f;
    float v[3] = { 0, 0, 0 }, w[3] = { 0, 0, 0 };
    if (dt > 0.005f && dt < 0.2f) {
        for (int k = 0; k < 3; ++k) v[k] = (me.p[k] - pp[k]) / dt;
        QDiff(pq, me.q, w);
        for (int k = 0; k < 3; ++k) w[k] /= dt;
    }
    memcpy(pp, me.p, 12);
    memcpy(pq, me.q, 16);
    pqpc = qpc.QuadPart;
    uint8_t b[EDS1_SIZE];
    memcpy(b, "EDS1", 4);
    ++seq;
    memcpy(b + 4, &seq, 4);
    b[8] = g_net_self;
    memcpy(b + 9, me.p, 12);
    memcpy(b + 21, me.q, 16);
    memcpy(b + 37, v, 12);
    memcpy(b + 49, w, 12);
    b[61] = (uint8_t)g_faces.want;
    b[62] = (uint8_t)g_brain.mode;
    b[63] = holding ? 1 : 0;                                  // (the host following a holder isn't holding)
    EdithNet_SendBinary(b, sizeof b);
}

// A puppet: the host has a fresh state for her.
bool PuppetActive(ULONGLONG now) {
    return !strcmp(g_net_role, "puppet") && g_rx.have && g_rx.from == g_net_host && now - g_rx.at < PUPPET_STALE_MS;
}

// Someone else holds her and their state is fresh: follow their hand.
bool HolderActive(ULONGLONG now) {
    return g_hold_rx.have && g_hold_rx.from != g_me && now - g_hold_rx.at < HOLD_STALE_MS;
}

// Steer her body (velocity, so she still collides) toward a sent state, carried forward by its
// velocity since it arrived; too far off, she is teleported there. `out` gets the velocity set.
// Returns false when it teleported (her motion this tick means nothing).
bool FollowState(const NetState &rx, const Pose &me, ULONGLONG now, float *out) {
    float age = fminf((now - rx.at) / 1000.0f, PUPPET_LEAD), tp[3], tq[4], turn[3];
    for (int k = 0; k < 3; ++k) { tp[k] = rx.p[k] + rx.v[k] * age; turn[k] = rx.w[k] * age; }
    QTurn(rx.q, turn, tq);
    float err[3] = { tp[0] - me.p[0], tp[1] - me.p[1], tp[2] - me.p[2] };
    float off = Len(err);
    static ULONGLONG last_snap = 0;
    if (off > PUPPET_SNAP && WorldTeleport && now - last_snap > 250) {   // (a teleport takes a tick to land)
        last_snap = now;
        float xf[8] = { tq[0], tq[1], tq[2], tq[3], tp[0], tp[1], tp[2], 1 };
        WorldTeleport(g_her.space, HER_ACTOR, xf, 0);
        Log("follow: %.2f m off %s's state, teleported to (%.2f %.2f %.2f)", off, rx.from.c_str(), tp[0], tp[1], tp[2]);
        memcpy(out, rx.v, 12);
        return false;
    }
    float w[3], aa[3];
    float fix = fminf(off * PUPPET_GAIN, PUPPET_FIX);
    for (int k = 0; k < 3; ++k) out[k] = rx.v[k] + (off > 1e-4f ? err[k] / off * fix : 0.0f);
    QDiff(me.q, tq, aa);
    for (int k = 0; k < 3; ++k) w[k] = rx.w[k] + aa[k] * PUPPET_TURN;
    float m = Len(w);
    if (m > PUPPET_MAX_TURN) for (int k = 0; k < 3; ++k) w[k] *= PUPPET_MAX_TURN / m;
    SetVelocities(out, w);
    static ULONGLONG last_log = 0;
    if (now - last_log > 5000) {
        last_log = now;
        Log("follow %s: her (%.2f %.2f %.2f) state (%.2f %.2f %.2f) %.0f ms old, %.2f m off, %.2f rad", rx.from.c_str(),
            me.p[0], me.p[1], me.p[2], rx.p[0], rx.p[1], rx.p[2], (float)(now - rx.at), off, Len(aa));
    }
    return true;
}

// Instead of her brain on a puppet: follow the host (or whoever holds her). Your own hands and head
// are seen here only: a grab makes you her owner (you send her state, no spring fighting your hand),
// and a knock from your head is reported to the host as a hit.
struct Puppet { bool held = false, have = false; float pos[3], sent[3]; LONGLONG qpc = 0; ULONGLONG free_until = 0; } g_pup;

void PuppetTick() {
    if (!HerAlive()) return;
    Pose me;
    Real_TransformGet(g_her.transforms, &me, g_her.xf);
    ULONGLONG now = GetTickCount64();
    LARGE_INTEGER qpc, freq;
    QueryPerformanceCounter(&qpc);
    QueryPerformanceFrequency(&freq);
    float dt = g_pup.qpc ? (float)(qpc.QuadPart - g_pup.qpc) / (float)freq.QuadPart : 0.0f;
    float v[3] = { 0, 0, 0 };
    bool measured = g_pup.have && dt > 0.005f && dt < 0.2f;
    if (measured) for (int k = 0; k < 3; ++k) v[k] = (me.p[k] - g_pup.pos[k]) / dt;
    memcpy(g_pup.pos, me.p, 12);
    g_pup.qpc = qpc.QuadPart;
    g_pup.have = true;

    bool held = Held();
    if (held != g_pup.held) {
        g_pup.held = held;
        SendTouch(held ? "grabbed" : "released", held ? nullptr : v, nullptr);
        Log("puppet: %s her (%.2f m/s)", held ? "you grabbed" : "you let go of", Len(v));
    }
    static ULONGLONG last_state = 0;
    if (now - last_state > 2000) {                            // (the companion's state line, as in Tick)
        last_state = now;
        Event("state mode=%s order=%s her=%.2f,%.2f,%.2f player=0,0,0 dist=-1 held=%d speaker=%d net=%s host=%s me=%s members=%s ai=%s",
              ModeName((Mode)(g_rx.mode <= STARE ? g_rx.mode : 0)), OrderName(g_orders.order), me.p[0], me.p[1], me.p[2],
              held || (g_rx.flags & 1), g_spk.playing ? 1 : 0, g_net_role, g_net_host, g_me, g_net_members, g_net_ai);
    }
    if (held) {                                               // your hand moves her: you own her body
        SendState(true);
        memcpy(g_pup.sent, v, 12);
        return;
    }
    // knocked off what she was set to, with your head right there: a hit, for the host to judge
    float off[3] = { v[0] - g_pup.sent[0], v[1] - g_pup.sent[1], v[2] - g_pup.sent[2] }, hp[3], hv[3];
    if (measured && now > g_pup.free_until && Len(off) > THROWN_DV && g_own_slot >= 0 && PlayerAt(g_own_slot, hp, hv)) {
        float d[3] = { hp[0] - me.p[0], hp[1] - me.p[1], hp[2] - me.p[2] };
        float hd = Len(d);
        if (hd < REACH_DIST) {
            SendTouch("hit", v, hd < HEADBUTT_DIST ? "headbutt" : "bump");
            g_pup.free_until = now + HIT_FREE_MS;
        }
    }
    if (now < g_pup.free_until) { memcpy(g_pup.sent, v, 12); return; }   // let her fly till the host has it
    const NetState &rx = HolderActive(now) ? g_hold_rx : g_rx;
    if (!FollowState(rx, me, now, g_pup.sent)) g_pup.have = false;
    if (rx.face < MAX_FACES && g_faces.want != rx.face) { g_faces.want = rx.face; g_faces.until = 0; }
}

void UpdateVoip(ULONGLONG now);                               // (her ears on voice chat, below)

// A dedicated server that runs her keeps her body. Echo's net physics hands an object to the player
// who touches it (their throws feel instant), and the server's thrust then can't move her: after a
// headbutt she floated off on her own momentum, deaf to orders (2026-10-18). So once nobody holds
// her and 1.5 s have passed since the owner changed, the server takes her back the way its own
// arbiter does (nevr-server-rs docs/re/ownership-and-possession.md 1, 16):
//   0x140cf00b0 CCompactPool::AdvanceGeneration(net physics cs, handle) -> fresh generation (mod 15)
//   0x140d474d0 CR15NetPhysicsCS::SetOwner(cs, handle, owner, generation); owner 0xFFFFFFFF = unowned
//   (the server simulates it). Her owner is the u32 at record +1Ch (records +F8h, stride 1F8h).
constexpr uintptr_t SET_OWNER_RVA = 0xd474d0, ADVANCE_GEN_RVA = 0xcf00b0;
constexpr uint8_t SET_OWNER_BYTES[] = { 0x66, 0x44, 0x89, 0x4c, 0x24, 0x20, 0x44, 0x89, 0x44, 0x24, 0x18, 0x89, 0x54, 0x24, 0x10, 0x48 };
constexpr uint8_t ADVANCE_GEN_BYTES[] = { 0x48, 0x8b, 0x81, 0xc8, 0x00, 0x00, 0x00, 0x44, 0x0f, 0xb7, 0xca, 0x42, 0x0f, 0xb7, 0x14, 0x88 };
constexpr uint32_t NO_OWNER = 0xffffffffu;
constexpr DWORD RECLAIM_MS = 1500;
using set_owner_fn = void(__fastcall *)(void *cs, uint64_t handle, uint32_t owner, uint16_t generation);
using advance_gen_fn = uint16_t(__fastcall *)(void *cs, uint32_t handle);
set_owner_fn SetOwnerFn = nullptr;
advance_gen_fn AdvanceGen = nullptr;

void ReclaimHer(ULONGLONG now) {
    static void *net = nullptr;
    static uint32_t h = 0xffffffffu, seen = 0xfffffffeu;
    static ULONGLONG since = 0;
    if (!g_server || !SetOwnerFn || !AdvanceGen || !g_her.net) return;
    if (net != g_her.net) {
        net = g_her.net;
        h = AnyInstance(net, HER_ACTOR);
        seen = 0xfffffffeu;
        Log("ownership: her net physics instance %08x in system %p", h, net);
    }
    if (h == 0xffffffffu) return;
    uint16_t slot = *(uint16_t *)(*(uint8_t **)((uint8_t *)net + 0xc8) + (size_t)(h & 0xffff) * 4);
    uint32_t owner = *(uint32_t *)(*(uint8_t **)((uint8_t *)net + 0xf8) + (size_t)slot * 0x1f8 + 0x1c);
    if (owner != seen) {
        Log("ownership: her owner %08x -> %08x", seen, owner);
        seen = owner;
        since = now;
    }
    if (owner == NO_OWNER) return;
    if (Held()) { since = now; return; }                       // in someone's hand: theirs
    if (now - since < RECLAIM_MS) return;
    uint16_t gen = AdvanceGen(net, h);
    SetOwnerFn(net, h, NO_OWNER, gen);
    Log("ownership: took her back from %08x (generation %u)", owner, gen);
    g_brain.have = false;                                      // (her motion is the server's again)
    since = now;
}

// Your voice chat mute, for the companion: muted in game = she doesn't hear your mic either (user,
// 2026-10-18). R15NetVoipMuteSelfNode (registered at 0x140f4eb1a) queues 0x1401b24a0(netgame, mute),
// which sets / clears bit 38 of the u64 at *(netgame + 2DA0h) and tells voice chat. Sent as
// "mute 0|1" on a change and every 2 s, only once you are known (a server has no you).
constexpr size_t NG_VOIP_FLAGS = 0x2da0;
constexpr uint64_t VOIP_SELF_MUTED = 1ull << 38;
int g_muted = -1;
void ReadMute(uint8_t *ng) {
    int m = -1;
    __try {
        uint64_t *flags = *(uint64_t **)(ng + NG_VOIP_FLAGS);
        if (flags) m = (*flags & VOIP_SELF_MUTED) ? 1 : 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) {}
    if (m < 0 || !g_me[0]) return;
    static ULONGLONG last_sent = 0;
    ULONGLONG now = GetTickCount64();
    if (m != g_muted) Log("voice chat: you are %s", m ? "muted" : "unmuted");
    // (who you are and whether her speaker plays here, for the companion when a server steers her: its
    //  state lines know neither, and her voice went out of the PC instead of Echo, 2026-10-18)
    if (m != g_muted || now - last_sent > 2000) {
        Event("mute %d me=%s speaker=%d", m, g_me, g_spk.playing ? 1 : 0);
        last_sent = now;
    }
    g_muted = m;
}

// CR15NetGame::Update (the net game, once a frame on the game thread): steer her.
using netgame_update_fn = void(__fastcall *)(uint8_t *);
netgame_update_fn Real_NetGameUpdate = nullptr;
void __fastcall Hooked_NetGameUpdate(uint8_t *ng) {
    Real_NetGameUpdate(ng);
    g_netgame = ng;
    ULONGLONG now = GetTickCount64();
    if (now - g_last_tick < TICK_MS) return;
    g_last_tick = now;
    if (GameLogFn && !g_game_log_on) g_game_log_on = true;   // (the game is up: its log too)
    t_busy = true;
    __try {
        ReadMute(ng);                                         // muted in game: she doesn't hear you
        ReclaimHer(now);                                      // a server keeps her body (net physics owner)
        PollSelf();                                           // shoves / shutdowns for your own body
        if (g_network) TakeNet();                             // one Edith per match (docs/networkplan.md)
        static bool was_puppet = false;
        bool puppet = PuppetActive(now);
        if (puppet != was_puppet) {                           // her brain starts fresh either way
            Log("edith net: %s", puppet ? "puppet: following the host's state" : "running her own brain");
            g_brain = Brain();
            g_pup = Puppet();
            was_puppet = puppet;
        }
        bool host = !strcmp(g_net_role, "host");
        if (host) ApplyTouches(now);                          // what other players did to her
        if (g_holder[0] && (!HolderActive(now) || g_hold_rx.from != g_holder) && now - g_holder_at > 1500) {
            Log("edith net: %s stopped holding her (no release)", g_holder);   // (left, or the release got lost)
            g_holder[0] = 0;
            g_brain.have = false;
        }
        if (g_authority || g_local) {                         // steering: where her physics is decided
            if (puppet) { PuppetTick(); UpdateSnow(); }       // (thrown balls the host relayed)
            else if (host && g_holder[0] && HolderActive(now) && g_hold_rx.from == g_holder) {
                Pose me;                                      // someone else's hand moves her: follow it
                Real_TransformGet(g_her.transforms, &me, g_her.xf);
                float out[3];
                FollowState(g_hold_rx, me, now, out);
                g_brain.last_push = now;
            } else Tick();
        } else if (!HerAlive()) g_brain = Brain();
        g_stage = 30;
        UpdateJets();                                         // her jets: everywhere
        UpdateFaces();                                        // her face for her mood
        UpdateNet(ng);
        if (g_network && !puppet) SendState(false);
        UpdateVoip(now);                                      // who is talking on voice chat (her ears)
        if (HerAlive()) {                                     // for her speaker (RenderAudio)
            Pose hp;
            Real_TransformGet(g_her.transforms, &hp, g_her.xf);
            memcpy(g_her_pos, hp.p, 12);
            g_her_pos_ok = 1;
        } else g_her_pos_ok = 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        static int n = 0;
        if (n++ < 5) Log("tick: exception %08lx at stage %d", GetExceptionCode(), g_stage);
        g_her = Her();
        g_jets = Jets();
    }
    t_busy = false;
}


// ---- her speaker: her voice out of Echo's own sound engine, from where she is ------------------
// EchoVRMusic's route (its docs/REVERSING.md; same echovr.exe, 35,397,120 B): Wwise 2018 is linked
// into echovr.exe with its AK:: API exported. A game object of ours plays Echo's voice-chat event
// (0xf5b8b08d, an Audio Input source) and Echo's CAudioInputCallbackRegistry (global +20A2FE0h;
// vtable slot 6 Register(reg, playing id, delegate, {rate, 16, 0}) int16 mono, slot 7 Unregister)
// pulls PCM from our delegate on Wwise's audio thread. Wwise places the sound at the object, which
// follows her every frame, so the game's own 3D audio carries her voice (VR or desktop).
// The PCM comes from the local AI (ai/satellite_ai.py) as raw int16 mono 24 kHz UDP datagrams to
// 127.0.0.1:47323 ("flush" clears what is queued).
struct AkVector { float x, y, z; };
struct AkTransform { AkVector front, top, pos; };          // Wwise 2017+ member order
typedef uint32_t (*AkPostEventId_t)(uint32_t, uint64_t, uint32_t, void *, void *, uint32_t, void *, uint32_t);
typedef int (*AkRegisterGameObj_t)(uint64_t, const char *);
typedef int (*AkUnregisterGameObj_t)(uint64_t);
typedef int (*AkSetPosition_t)(uint64_t, const AkTransform *);
typedef int (*AkRenderAudio_t)(bool);
typedef void (*AkStopPlayingID_t)(uint32_t, int32_t, int);
typedef int (*AkGetListeners_t)(uint64_t, uint64_t *, uint32_t *);
typedef int (*AkGetListenerPosition_t)(uint64_t, AkTransform *);
AkGetListeners_t AkGetListeners = nullptr;
AkGetListenerPosition_t AkGetListenerPosition = nullptr;
AkPostEventId_t AkPostEvent = nullptr;
AkRegisterGameObj_t AkRegisterGameObj = nullptr;
AkUnregisterGameObj_t AkUnregisterGameObj = nullptr;
AkSetPosition_t AkSetPosition = nullptr;
AkRenderAudio_t Real_RenderAudio = nullptr;
AkStopPlayingID_t AkStopPlayingID = nullptr;

struct SpeakerFormat { uint32_t rate, bits, type, pad; };
typedef void (*RegistryRegister_t)(void *, uint32_t, const SpeakerDelegate *, const SpeakerFormat *);
typedef void (*RegistryUnregister_t)(void *, uint32_t);
constexpr uintptr_t REGISTRY_PTR_RVA = 0x20A2FE0, REGISTRY_LOAD_RVA = 0x205466;
constexpr uint8_t REGISTRY_LOAD_BYTES[] = { 0x48, 0x8b, 0x1d, 0x73, 0xdb, 0xe9, 0x01, 0x48, 0x83, 0xc3, 0x38 };
constexpr uint32_t VOICE_EVENT = 0xf5b8b08d, VOICE_RATE = 24000;   // Kokoro's rate
constexpr uint64_t SPEAKER_OBJ = 0x5341544C49544531ull;            // "SATLITE1"
constexpr u_short VOICE_PORT = 47323;
constexpr uint32_t RING = 1u << 19;                                // ~21 s at 24 kHz
int16_t g_ring[RING];
volatile LONG64 g_wr = 0, g_rd = 0;
bool g_primed = false;
float g_voice_gain = 0.8f;                                         // EDITH.ini voice_gain
float g_voice_full = 1.5f, g_voice_cutoff = 20.0f;                 // m: full volume within, silent from
volatile float g_dist_gain = 1.0f;                                 // set per frame from your distance to her

// Wwise's audio thread: queued speech after a 120 ms prebuffer, else silence (the voice stays live).
int64_t FillSpeaker(SpeakerDelegate *, int16_t *out, uint16_t n) {
    static float cur = 1.0f;                                       // ramps to the distance gain over a buffer
    float target = g_dist_gain * g_voice_gain, step = n ? (target - cur) / n : 0.0f;
    LONG64 wr = g_wr, rd = g_rd, have = wr - rd;
    if (!g_primed && have >= (LONG64)(VOICE_RATE * 12 / 100)) g_primed = true;
    uint16_t i = 0;
    if (g_primed) {
        for (; i < n && rd < wr; ++i, ++rd) {
            cur += step;
            float v = g_ring[rd & (RING - 1)] * cur;
            out[i] = (int16_t)(v > 32767.f ? 32767.f : v < -32767.f ? -32767.f : v);
        }
        if (rd >= wr) g_primed = false;
        g_rd = rd;
    }
    cur = target;
    for (; i < n; ++i) out[i] = 0;
    return n;
}

DWORD WINAPI VoiceReceiver(LPVOID) {
    SOCKET sk = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sk == INVALID_SOCKET) return 0;
    int big = 8 << 20;
    setsockopt(sk, SOL_SOCKET, SO_RCVBUF, (const char *)&big, sizeof big);
    sockaddr_in me = {};
    me.sin_family = AF_INET;
    me.sin_port = htons(VOICE_PORT);
    inet_pton(AF_INET, "127.0.0.1", &me.sin_addr);
    if (bind(sk, (sockaddr *)&me, sizeof me)) { Log("speaker: port %u busy", VOICE_PORT); closesocket(sk); return 0; }
    Log("speaker: her voice in on 127.0.0.1:%u (int16 mono %u Hz)", VOICE_PORT, VOICE_RATE);
    static char buf[65536];
    for (;;) {
        int n = recv(sk, buf, sizeof buf, 0);
        if (n <= 0) continue;
        if (n == 5 && !memcmp(buf, "flush", 5)) { g_wr = g_rd; continue; }
        LONG64 wr = g_wr;
        const int16_t *pcm = (const int16_t *)buf;
        for (int k = 0; k < n / 2; ++k) g_ring[(wr + k) & (RING - 1)] = pcm[k];
        g_wr = wr + n / 2;
    }
}

void *Registry() {
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    return *(void **)(base + REGISTRY_PTR_RVA);
}

void SpeakerOff(const char *why) {
    if (!g_spk.registered) return;
    if (g_spk.playing) {
        AkStopPlayingID(g_spk.playing, 0, 4);
        if (void *reg = Registry()) ((RegistryUnregister_t)(*(void ***)reg)[7])(reg, g_spk.playing);
    }
    AkUnregisterGameObj(SPEAKER_OBJ);
    Log("speaker off (%s)", why);
    g_spk = Speaker();
}

// RenderAudio (game thread, before Wwise renders): our speaker on, at her.
void SpeakerTick() {
    if (!g_her_pos_ok || !g_her.space) { if (g_spk.registered && !g_her.space) SpeakerOff("she is gone"); return; }
    if (g_spk.registered && g_spk.space != g_her.space) SpeakerOff("her level changed");
    //: Wwise's space has X mirrored from the game's: the listener sits at (-x, y, z) of your head
    //: (logged: head -7.05 4.96 5.22, listener 7.05 4.96 5.22), so her voice goes at (-x, y, z) too.
    //: Unflipped, she sounded from her mirror image across the lobby.
    AkTransform t = { { 0, 0, 1 }, { 0, 1, 0 }, { -g_her_pos[0], g_her_pos[1], g_her_pos[2] } };
    if (!g_spk.registered) {
        void *reg = Registry();
        if (!reg) return;
        AkRegisterGameObj(SPEAKER_OBJ, "Satellite");
        AkSetPosition(SPEAKER_OBJ, &t);
        g_spk.registered = true;
        g_spk.space = g_her.space;
        g_spk.playing = AkPostEvent(VOICE_EVENT, SPEAKER_OBJ, 0, nullptr, nullptr, 0, nullptr, 0);
        if (!g_spk.playing) { Log("speaker: PostEvent(0x%08x) failed (voice bank not loaded yet?)", VOICE_EVENT); return; }
        g_spk.del = { nullptr, nullptr, FillSpeaker };
        SpeakerFormat fmt = { VOICE_RATE, 16, 0, 0 };
        ((RegistryRegister_t)(*(void ***)reg)[6])(reg, g_spk.playing, &g_spk.del, &fmt);
        Log("speaker on: playing id %u at (%.2f %.2f %.2f)", g_spk.playing, t.pos.x, t.pos.y, t.pos.z);
        return;
    }
    if (!g_spk.playing) {                                    // the event failed: retry now and then
        static ULONGLONG last = 0;
        if (GetTickCount64() - last > 2000) { last = GetTickCount64(); AkUnregisterGameObj(SPEAKER_OBJ); g_spk = Speaker(); }
        return;
    }
    AkSetPosition(SPEAKER_OBJ, &t);
    uint64_t ids[4];
    uint32_t nl = 4;
    AkTransform ear = {};
    if (AkGetListeners && AkGetListenerPosition && AkGetListeners(SPEAKER_OBJ, ids, &nl) == 1 && nl
        && AkGetListenerPosition(ids[0], &ear) == 1) {
        float dx = t.pos.x - ear.pos.x, dy = t.pos.y - ear.pos.y, dz = t.pos.z - ear.pos.z, d = sqrtf(dx * dx + dy * dy + dz * dz);
        float r1 = g_voice_cutoff, r0 = fminf(g_voice_full, r1 - 0.1f), g;
        if (d <= r0) g = 1.0f;
        else if (d >= r1) g = 0.0f;
        else { float k = 1.0f - (d - r0) / (r1 - r0); g = k * k; }
        g_dist_gain = g;
        g_ear[0] = -ear.pos.x; g_ear[1] = ear.pos.y; g_ear[2] = ear.pos.z;   // (Wwise X is mirrored)
        g_ear_ok = 1;
        static ULONGLONG last = 0;
        if (g_verbose && GetTickCount64() - last > 5000) {
            last = GetTickCount64();
            Log("speaker: her (%.2f %.2f %.2f), your ears (%.2f %.2f %.2f) facing (%.2f %.2f %.2f), %.2f m, gain %.2f",
                t.pos.x, t.pos.y, t.pos.z, ear.pos.x, ear.pos.y, ear.pos.z, ear.front.x, ear.front.y, ear.front.z, d, g * g_voice_gain);
        }
    }
}

int Hooked_RenderAudio(bool allow) {
    __try {
        SpeakerTick();
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        static int n = 0;
        if (n++ < 3) Log("speaker: exception %08lx", GetExceptionCode());
        g_spk = Speaker();
    }
    return Real_RenderAudio(allow);
}

bool SpeakerInstall(uint8_t *base) {
    HMODULE exe = GetModuleHandleW(nullptr);
    AkPostEvent = (AkPostEventId_t)GetProcAddress(exe, "?PostEvent@SoundEngine@AK@@YAKK_KKP6AXW4AkCallbackType@@PEAUAkCallbackInfo@@@ZPEAXKPEAUAkExternalSourceInfo@@K@Z");
    AkRegisterGameObj = (AkRegisterGameObj_t)GetProcAddress(exe, "?RegisterGameObj@SoundEngine@AK@@YA?AW4AKRESULT@@_KPEBD@Z");
    AkUnregisterGameObj = (AkUnregisterGameObj_t)GetProcAddress(exe, "?UnregisterGameObj@SoundEngine@AK@@YA?AW4AKRESULT@@_K@Z");
    AkSetPosition = (AkSetPosition_t)GetProcAddress(exe, "?SetPosition@SoundEngine@AK@@YA?AW4AKRESULT@@_KAEBVAkTransform@@@Z");
    Real_RenderAudio = (AkRenderAudio_t)GetProcAddress(exe, "?RenderAudio@SoundEngine@AK@@YA?AW4AKRESULT@@_N@Z");
    AkStopPlayingID = (AkStopPlayingID_t)GetProcAddress(exe, "?StopPlayingID@SoundEngine@AK@@YAXKJW4AkCurveInterpolation@@@Z");
    AkGetListeners = (AkGetListeners_t)GetProcAddress(exe, "?GetListeners@Query@SoundEngine@AK@@YA?AW4AKRESULT@@_KPEA_KAEAK@Z");
    AkGetListenerPosition = (AkGetListenerPosition_t)GetProcAddress(exe, "?GetListenerPosition@Query@SoundEngine@AK@@YA?AW4AKRESULT@@_KAEAVAkTransform@@@Z");
    if (!AkPostEvent || !AkRegisterGameObj || !AkUnregisterGameObj || !AkSetPosition || !Real_RenderAudio || !AkStopPlayingID
        || memcmp(base + REGISTRY_LOAD_RVA, REGISTRY_LOAD_BYTES, sizeof REGISTRY_LOAD_BYTES)) {
        Log("speaker: Wwise exports or the audio input registry not as expected: no voice in game");
        return false;
    }
    CreateThread(nullptr, 0, VoiceReceiver, nullptr, 0, nullptr);
    return true;
}

// ---- her ears on voice chat: other players' voices, to the companion, by name -------------------
// Echo plays each remote player's voice the way her speaker plays hers (EchoVRMusic docs/REVERSING.md
// 3): voice-chat event 0xf5b8b08d on a game object at their head, and Register(reg, playing id,
// delegate, {rate, 16, 0}) with the delegate {object, context, 0x140c85b50} (a thunk into the voice
// stream's reader). Hooked Register swaps that delegate's fn for VoipTap, which calls the reader and
// copies what it gave Wwise (int16 mono) to the companion: UDP 127.0.0.1:47324, datagrams
//   "VOIP" + rate u32 + name length u8 + name + int16 samples
// Who it is: Query::GetGameObjectFromPlayingID -> Query::GetPosition -> the player head within 1 m
// (never yours). EDITH.ini hear_voip=0 turns it off.
constexpr uintptr_t REGISTRY_REGISTER_RVA = 0x20ca30, VOICE_READ_RVA = 0xc85b50;
constexpr uint8_t REGISTRY_REGISTER_BYTES[] = { 0x48, 0x89, 0x5c, 0x24, 0x20, 0x55, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55,
                                                0x41, 0x56, 0x41, 0x57, 0x48, 0x83, 0xec, 0x40 };
constexpr uint8_t VOICE_READ_BYTES[] = { 0x4c, 0x8b, 0x49, 0x08, 0x48, 0x8b, 0x09, 0xe9 };
constexpr u_short VOIP_PORT = 47324;
constexpr float VOIP_MATCH = 1.0f;                                 // m: voice object to a player's head
using register_fn = uint64_t(__fastcall *)(void *, uint32_t, const SpeakerDelegate *, const SpeakerFormat *);
using voice_read_fn = int64_t (*)(SpeakerDelegate *, int16_t *, uint16_t);
typedef uint64_t (*AkGameObjFromPlaying_t)(uint32_t);
typedef int (*AkQueryPosition_t)(uint64_t, AkTransform *);
register_fn Real_Register = nullptr;
voice_read_fn VoiceRead = nullptr;
AkGameObjFromPlaying_t AkGameObjFromPlaying = nullptr;
AkQueryPosition_t AkQueryPosition = nullptr;
bool g_hear_voip = true;
// Keyed by the whole delegate {object, context}: Echo can register every remote voice with the same
// object (11 voices at a lobby join, all landed on one entry, so one playing id's position named
// everyone's voice: gg95 heard as you, Furo almost never; user, 2026-10-18).
struct VoipStream { void *obj, *ctx; uint32_t id, rate; char name[64]; volatile ULONGLONG last; volatile bool member; };
VoipStream g_voip[32];
SOCKET g_voip_sock = INVALID_SOCKET;
sockaddr_in g_voip_to = {};

VoipStream *VoipFind(const SpeakerDelegate *d) {
    for (auto &s : g_voip)
        if (s.obj == d->a && s.ctx == d->b) return &s;
    return nullptr;
}

// Wwise's audio thread: the voice as Echo would play it, and a copy for her.
int64_t VoipTap(SpeakerDelegate *d, int16_t *pcm, uint16_t n) {
    int64_t r = VoiceRead(d, pcm, n);
    if (r <= 0 || (g_voip_sock == INVALID_SOCKET && !g_ears_dll)) return r;
    VoipStream *s = VoipFind(d);
    if (!s || !s->member) return r;                           // only players with the mod (user)
    s->last = GetTickCount64();
    char pkt[64 + 2 * 4096];
    char name[64];
    memcpy(name, s->name, sizeof name);
    name[63] = 0;
    size_t len = strlen(name), frames = (size_t)r < 4096 ? (size_t)r : 4096;
    memcpy(pkt, "VOIP", 4);
    memcpy(pkt + 4, &s->rate, 4);
    pkt[8] = (char)len;
    memcpy(pkt + 9, name, len);
    memcpy(pkt + 9 + len, pcm, frames * 2);
    if (g_ears_dll) Ears_Voip(name, s->rate, pcm, frames);   // her built-in ears
    else sendto(g_voip_sock, pkt, (int)(9 + len + frames * 2), 0, (sockaddr *)&g_voip_to, sizeof g_voip_to);
    return r;
}

uint64_t __fastcall Hooked_Register(void *reg, uint32_t id, const SpeakerDelegate *d, const SpeakerFormat *f) {
    if (g_hear_voip && d && f && (void *)d->fn == (void *)VoiceRead) {
        VoipStream *s = VoipFind(d);
        if (!s) {                                                  // a free (or the quietest) entry
            s = &g_voip[0];
            for (auto &x : g_voip)
                if (!x.obj || x.last < s->last) s = &x;
        }
        s->obj = d->a; s->ctx = d->b; s->id = id; s->rate = f->rate; s->name[0] = 0; s->member = false;
        s->last = GetTickCount64();
        SpeakerDelegate w = *d;
        w.fn = VoipTap;
        Log("voip: a voice (playing id %u, %u Hz, delegate %p/%p): listening", id, f->rate, d->a, d->b);
        return Real_Register(reg, id, &w, f);
    }
    return Real_Register(reg, id, d, f);
}

// Game thread, twice a second: which player each voice belongs to.
void UpdateVoip(ULONGLONG now) {
    static ULONGLONG last = 0;
    if (!Real_Register || now - last < 500) return;
    last = now;
    for (auto &s : g_voip) {
        if (!s.obj) continue;
        uint64_t go = AkGameObjFromPlaying(s.id);
        AkTransform t = {};
        if (!go || go == ~0ull || AkQueryPosition(go, &t) != 1) continue;
        float p[3] = { -t.pos.x, t.pos.y, t.pos.z };              // (Wwise X is mirrored)
        int best = -1;
        float bd = VOIP_MATCH;
        for (int i = 0; i < g_nnames; ++i) {
            float hp[3], hv[3];
            if (g_names[i].slot == g_own_slot || !PlayerAt(g_names[i].slot, hp, hv)) continue;
            float d[3] = { hp[0] - p[0], hp[1] - p[1], hp[2] - p[2] };
            if (Len(d) < bd) { bd = Len(d); best = i; }
        }
        const char *name = best >= 0 ? g_names[best].name : "";
        s.member = name[0] && InRoom(name);                    // (the audio thread forwards members only)
        if (strcmp(name, s.name)) {
            Log("voip: playing id %u is %s (voice at %.2f %.2f %.2f)", s.id, name[0] ? name : "nobody we know", p[0], p[1], p[2]);
            strncpy_s(s.name, name, _TRUNCATE);
        }
    }
}

bool VoipInstall(uint8_t *base) {
    HMODULE exe = GetModuleHandleW(nullptr);
    AkGameObjFromPlaying = (AkGameObjFromPlaying_t)GetProcAddress(exe, "?GetGameObjectFromPlayingID@Query@SoundEngine@AK@@YA_KK@Z");
    AkQueryPosition = (AkQueryPosition_t)GetProcAddress(exe, "?GetPosition@Query@SoundEngine@AK@@YA?AW4AKRESULT@@_KAEAVAkTransform@@@Z");
    if (!g_hear_voip) { Log("voip: off (EDITH.ini hear_voip=0)"); return false; }
    if (!AkGameObjFromPlaying || !AkQueryPosition || memcmp(base + REGISTRY_REGISTER_RVA, REGISTRY_REGISTER_BYTES, sizeof REGISTRY_REGISTER_BYTES)
        || memcmp(base + VOICE_READ_RVA, VOICE_READ_BYTES, sizeof VOICE_READ_BYTES)) {
        Log("voip: the registry or Wwise queries aren't as expected: she can't hear voice chat");
        return false;
    }
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
    g_voip_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    g_voip_to.sin_family = AF_INET;
    g_voip_to.sin_port = htons(VOIP_PORT);
    inet_pton(AF_INET, "127.0.0.1", &g_voip_to.sin_addr);
    VoiceRead = (voice_read_fn)(base + VOICE_READ_RVA);
    Real_Register = (register_fn)(base + REGISTRY_REGISTER_RVA);
    Log("voip: voice chat to 127.0.0.1:%u (her ears)", VOIP_PORT);
    return true;
}

// ---- her built-in ears (edith_ears.cpp): what they ask of the DLL ----------------------------------
char g_brain_url[256] = "wss://sparkapi-production-e6df.up.railway.app/edith/brain";
char g_mic[32] = "default";
bool EarsInLobby() { return g_her_pos_ok != 0; }
bool EarsMuted() { return g_muted == 1; }
bool EarsPuppet() { return !strcmp(g_net_role, "puppet"); }
bool EarsHasEars(const char *name) {                          // in the room's ai list (their own game hears them)
    size_t n = strlen(name);
    for (const char *p = g_net_ai; *p;) {
        const char *e = strchr(p, ',');
        size_t len = e ? (size_t)(e - p) : strlen(p);
        if (len == n && !strncmp(p, name, n)) return true;
        if (!e) break;
        p = e + 1;
    }
    return false;
}
const char *EarsMe() { return g_me; }
// A reply's order, as the Python companion sent it: "heard <text>" (a puppet's own speech) goes to the
// host through the relay at once (a puppet doesn't poll its order port); a push / shutdown aimed at you
// goes to your own client's body port (:47325, without to=); "voice" is the pack line for the others;
// everything else to the order port (:47321).
void EarsOrder(const char *order) {
    if (!strncmp(order, "heard ", 6)) { ForwardHeard(order + 6); return; }
    if (!strncmp(order, "voice ", 6)) { SendVoice(order + 6); return; }
    static SOCKET sk = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    std::string o = order, to;
    size_t t = o.find(" to=");
    if (t != std::string::npos) { to = o.substr(t + 4); to = to.substr(0, to.find(' ')); }
    bool body = (!strncmp(order, "push", 4) || !strncmp(order, "shutdown", 8)) && (to.empty() || to == g_me || to == "you");
    if (body && t != std::string::npos) o = o.substr(0, t) + o.substr(o.find(' ', t + 1) == std::string::npos ? o.size() : o.find(' ', t + 1));
    sockaddr_in a = {};
    a.sin_family = AF_INET;
    a.sin_port = htons(body ? SELF_PORT : CMD_PORT);
    inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
    sendto(sk, o.c_str(), (int)o.size(), 0, (sockaddr *)&a, sizeof a);
}
void EarsVoiceKeys(const char *keys) { SendVoice(keys); }
bool EarsSpeakerPush(const int16_t *pcm, size_t n) {
    LONG64 wr = g_wr;
    if (!g_spk.playing || (size_t)(wr - g_rd) + n > RING - VOICE_RATE / 10) return false;   // (no room / no speaker)
    for (size_t k = 0; k < n; ++k) g_ring[(wr + k) & (RING - 1)] = pcm[k];
    g_wr = wr + (LONG64)n;
    return true;
}
size_t EarsSpeakerPending() { LONG64 d = g_wr - g_rd; return d > 0 ? (size_t)d : 0; }

void StartEars() {
    EarsHost h = {};
    h.log = Log;
    h.in_lobby = EarsInLobby;
    h.muted = EarsMuted;
    h.puppet = EarsPuppet;
    h.has_ears = EarsHasEars;
    h.me = EarsMe;
    h.order = EarsOrder;
    h.voice_keys = EarsVoiceKeys;
    h.speaker_push = EarsSpeakerPush;
    h.speaker_pending = EarsSpeakerPending;
    Ears_Start(h, g_brain_url, g_voice_dir, g_mic);
}

// Her AI (EDITH.ini ai=<path to run_edith_ears.ps1>): started without a window when the game
// starts, unless one is already running (its event port, 47322, is taken). It gets this game's pid
// (--with-echo) and closes when the game does; it only listens while this plugin reports her in the
// lobby (the state line).
char g_ai_script[MAX_PATH] = "";
bool g_ai_console = false;
DWORD WINAPI LaunchAI(LPVOID) {
    Sleep(3000);
    WSADATA w;
    WSAStartup(MAKEWORD(2, 2), &w);
    SOCKET sk = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    sockaddr_in a = {};
    a.sin_family = AF_INET;
    a.sin_port = htons(EVENT_PORT);
    inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
    bool free_port = sk != INVALID_SOCKET && bind(sk, (sockaddr *)&a, sizeof a) == 0;
    if (sk != INVALID_SOCKET) closesocket(sk);
    if (!free_port) { Log("ai: already running (port %u taken)", EVENT_PORT); return 0; }
    char cmd[MAX_PATH * 2 + 128];
    snprintf(cmd, sizeof cmd, "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%s\" --with-echo %lu", g_ai_script,
             GetCurrentProcessId());
    char dir[MAX_PATH];
    strcpy_s(dir, g_ai_script);
    if (char *s = strrchr(dir, '\\')) *s = 0;
    STARTUPINFOA si = { sizeof si };
    PROCESS_INFORMATION pi = {};
    // no window (EDITH.ini ai_console=1 shows its console, for debugging)
    if (CreateProcessA(nullptr, cmd, nullptr, nullptr, FALSE, g_ai_console ? CREATE_NEW_CONSOLE : CREATE_NO_WINDOW,
                       nullptr, dir, &si, &pi)) {
        Log("ai: started (%s), pid %lu", g_ai_script, pi.dwProcessId);
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    } else Log("ai: could not start %s (error %lu)", cmd, GetLastError());
    return 0;
}

DWORD WINAPI Install(LPVOID) {
    auto base = (uint8_t *)GetModuleHandleW(nullptr);
    if (!memcmp(base + GAME_LOG_RVA, GAME_LOG_BYTES, sizeof GAME_LOG_BYTES)) GameLogFn = (game_log_fn)(base + GAME_LOG_RVA);
    else Log("prologue mismatch at the game's log write: her lines stay in EDITH.log only");
    uint8_t *get = base + TRANSFORM_GET_RVA, *vel = base + SET_VELOCITY_RVA, *def = base + DEFER_RVA,
            *slot = base + SLOT_ACTOR_RVA;
    if (memcmp(get, TRANSFORM_GET_BYTES, sizeof TRANSFORM_GET_BYTES) || memcmp(vel, SET_VELOCITY_BYTES, sizeof SET_VELOCITY_BYTES)
        || memcmp(def, DEFER_BYTES, sizeof DEFER_BYTES) || memcmp(slot, SLOT_ACTOR_BYTES, sizeof SLOT_ACTOR_BYTES)
        || memcmp(base + NETGAME_UPDATE_RVA, NETGAME_UPDATE_BYTES, sizeof NETGAME_UPDATE_BYTES)
        || memcmp(base + SET_ANGULAR_RVA, SET_ANGULAR_BYTES, sizeof SET_ANGULAR_BYTES)
        || memcmp(base + SET_EMISSION_RVA, SET_EMISSION_BYTES, sizeof SET_EMISSION_BYTES)
        || memcmp(base + DEFER_FLOAT_RVA, DEFER_FLOAT_BYTES, sizeof DEFER_FLOAT_BYTES)) {
        Log("not the live build these addresses are for: nothing hooked");
        return 0;
    }
    Real_TransformGet = (transform_get_fn)get;
    Defer = (defer_fn)def;
    SlotActor = (slot_actor_fn)slot;
    g_set_velocity = vel;
    g_set_angular = base + SET_ANGULAR_RVA;
    DeferFloat = (defer_float_fn)(base + DEFER_FLOAT_RVA);
    if (memcmp(base + WORLD_TELEPORT_RVA, WORLD_TELEPORT_BYTES, sizeof WORLD_TELEPORT_BYTES) == 0)
        WorldTeleport = (world_teleport_fn)(base + WORLD_TELEPORT_RVA);
    else Log("prologue mismatch at WorldTeleport: no snowballs");
    g_set_emission = base + SET_EMISSION_RVA;
    if (!memcmp(base + NAV_SET_VELOCITY_RVA, NAV_SET_VELOCITY_BYTES, sizeof NAV_SET_VELOCITY_BYTES))
        g_nav_set_velocity = base + NAV_SET_VELOCITY_RVA;
    else Log("prologue mismatch at CR15PlayerNavCS::SetVelocity: no pushing");
    if (!memcmp(base + KILL_PLAYER_RVA, KILL_PLAYER_BYTES, sizeof KILL_PLAYER_BYTES))
        KillPlayer = (kill_player_fn)(base + KILL_PLAYER_RVA);
    else Log("prologue mismatch at CR15PlayerNavCS::KillPlayer: no shutdown");
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourAttach(&(PVOID &)Real_TransformGet, Hooked_TransformGet);
    Real_NetGameUpdate = (netgame_update_fn)(base + NETGAME_UPDATE_RVA);
    DetourAttach(&(PVOID &)Real_NetGameUpdate, Hooked_NetGameUpdate);
    if (!memcmp(base + FIND_SCRIPT_COMPONENT_RVA, FIND_SCRIPT_COMPONENT_BYTES, sizeof FIND_SCRIPT_COMPONENT_BYTES)) {
        Real_FindScriptComponent = (find_script_component_fn)(base + FIND_SCRIPT_COMPONENT_RVA);
        DetourAttach(&(PVOID &)Real_FindScriptComponent, Hooked_FindScriptComponent);
    } else Log("prologue mismatch at the script component find: shutdown can't reach the death scripts");
    if (!memcmp(base + SET_OWNER_RVA, SET_OWNER_BYTES, sizeof SET_OWNER_BYTES) &&
        !memcmp(base + ADVANCE_GEN_RVA, ADVANCE_GEN_BYTES, sizeof ADVANCE_GEN_BYTES)) {
        SetOwnerFn = (set_owner_fn)(base + SET_OWNER_RVA);
        AdvanceGen = (advance_gen_fn)(base + ADVANCE_GEN_RVA);
    } else Log("prologue mismatch at SetOwner / AdvanceGeneration: a server can't take her back after a touch");
    if (!memcmp(base + GET_USERNAME_RVA, GET_USERNAME_BYTES, sizeof GET_USERNAME_BYTES))
        GetUserNameFn = (get_username_fn)(base + GET_USERNAME_RVA);
    else Log("prologue mismatch at GetUserName: Edith stays local (no network)");
    if (g_network && GetUserNameFn) {
        EdithNet_Start(Log);
        EdithNet_Configure(g_relay);
        Log("edith net: relay %s", g_relay);
    }
    bool speaker = SpeakerInstall(base);
    if (speaker) DetourAttach(&(PVOID &)Real_RenderAudio, Hooked_RenderAudio);
    if (VoipInstall(base)) DetourAttach(&(PVOID &)Real_Register, Hooked_Register);
    LONG rc = DetourTransactionCommit();
    if (g_authority || g_local) OpenOrders();
    OpenSelf();
    if (g_sock == INVALID_SOCKET) {                          // not steering her here: events only (your mute)
        WSADATA w;
        WSAStartup(MAKEWORD(2, 2), &w);
        g_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        g_ai.sin_family = AF_INET;
        g_ai.sin_port = htons(EVENT_PORT);
        inet_pton(AF_INET, "127.0.0.1", &g_ai.sin_addr);
    }
    if (g_ears_dll) StartEars();
    Log("hooked CTransformCS::get + CR15NetGame::Update: %ld (%s)", rc, g_authority ? "authority: she is steered here" : g_local ? "local mode: steered on this client, following you" : "not authority: idle");
    return 0;
}

}  // namespace

BOOL WINAPI DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        EchoCombatLogPath(self, 3, "EDITH.log", g_log, sizeof g_log);
        g_main_tid = GetCurrentThreadId();
        const char *cmd = GetCommandLineA();
        g_authority = strstr(cmd, "-server") || strstr(cmd, "-offline");
        g_server = strstr(cmd, "-server") != nullptr;
        if (!g_authority) {
            char ini0[MAX_PATH];
            GetModuleFileNameA(self, ini0, MAX_PATH);
            if (char *dot = strrchr(ini0, '.')) strcpy_s(dot, ini0 + MAX_PATH - dot, ".ini");
            g_local = GetPrivateProfileIntA("satellite", "local", 0, ini0) != 0;
        }
        Log("EDITH.dll loaded (pid %lu, main thread %lu)", GetCurrentProcessId(), g_main_tid);
        EdithPack_Install(self, Log);                         // her lobby data from <plugins>\<dll name>\*.edith (no repack)
        char ini[MAX_PATH], buf[64];
        GetModuleFileNameA(self, ini, MAX_PATH);
        strcpy_s(g_voice_dir, ini);                           // <plugins>\EdithVoice\ next to the DLL
        if (char *sl = strrchr(g_voice_dir, '\\')) strcpy_s(sl + 1, g_voice_dir + MAX_PATH - (sl + 1), "EdithVoice\\");
        if (char *dot = strrchr(ini, '.')) strcpy_s(dot, ini + MAX_PATH - dot, ".ini");
        unsigned index = GetPrivateProfileIntA("satellite", "index", 659, ini);
        HER_ACTOR = 0x0000FFFFFFFF0000ull | (index & 0xffff);
        g_jet_test = GetPrivateProfileIntA("satellite", "jets_test", 0, ini) != 0;
        g_snow_first = GetPrivateProfileIntA("satellite", "snow_first", 0, ini);
        g_snow_count = g_snow_first ? GetPrivateProfileIntA("satellite", "snow_count", 0, ini) : 0;
        if (g_snow_count > 16) g_snow_count = 16;
        g_snow_test = GetPrivateProfileIntA("satellite", "snow_test", 0, ini) != 0;
        g_face_first = GetPrivateProfileIntA("satellite", "face_first", 0, ini);
        g_face_count = g_face_first ? GetPrivateProfileIntA("satellite", "face_count", 0, ini) : 0;
        g_network = GetPrivateProfileIntA("satellite", "network", 1, ini) != 0;            // docs/networkplan.md
        g_hear_voip = GetPrivateProfileIntA("satellite", "hear_voip", 1, ini) != 0;        // her ears on voice chat
        g_verbose = GetPrivateProfileIntA("satellite", "verbose", 0, ini) != 0;
        g_ai_console = GetPrivateProfileIntA("satellite", "ai_console", 0, ini) != 0;
        GetPrivateProfileStringA("satellite", "relay", g_relay, g_relay, sizeof g_relay, ini);
        GetPrivateProfileStringA("satellite", "my_name", "", g_my_name, sizeof g_my_name, ini);
        GetPrivateProfileStringA("satellite", "debug_roster", "", g_debug_roster, sizeof g_debug_roster, ini);
        if (g_debug_roster[0]) Log("edith net: debug_roster %s (fake players in your match)", g_debug_roster);
        if (GetPrivateProfileStringA("satellite", "voice_gain", "", buf, sizeof buf, ini)) g_voice_gain = (float)atof(buf);
        if (GetPrivateProfileStringA("satellite", "voice_full", "", buf, sizeof buf, ini)) g_voice_full = (float)atof(buf);
        if (GetPrivateProfileStringA("satellite", "voice_cutoff", "", buf, sizeof buf, ini)) g_voice_cutoff = (float)atof(buf);
        GetPrivateProfileStringA("satellite", "ai", "", g_ai_script, sizeof g_ai_script, ini);
        char ears[16];                                        // her ears: built in (dll), the Python companion
        GetPrivateProfileStringA("satellite", "ears", "dll", ears, sizeof ears, ini);   // (python, ai=), or off
        GetPrivateProfileStringA("satellite", "brain", g_brain_url, g_brain_url, sizeof g_brain_url, ini);
        GetPrivateProfileStringA("satellite", "mic", g_mic, g_mic, sizeof g_mic, ini);
        g_ears_dll = !_stricmp(ears, "dll") && !g_server;     // (a dedicated server has no player to hear)
        if (_stricmp(ears, "python")) g_ai_script[0] = 0;     // built in or off: no Python companion
        g_ai_configured = g_ears_dll || (g_ai_script[0] && GetFileAttributesA(g_ai_script) != INVALID_FILE_ATTRIBUTES);
        if (g_ai_script[0] && GetFileAttributesA(g_ai_script) != INVALID_FILE_ATTRIBUTES)
            CreateThread(nullptr, 0, LaunchAI, nullptr, 0, nullptr);
        else if (g_ai_script[0]) Log("ai: %s not found", g_ai_script);
        Log("snowball pool: %u from actor index %u", g_snow_count, g_snow_first);
        const char *keys[3] = { "x", "y", "z" };
        for (int k = 0; k < 3; ++k)
            if (GetPrivateProfileStringA("satellite", keys[k], "", buf, sizeof buf, ini)) g_home[k] = (float)atof(buf);
        Log("her actor %016llx, built at (%.2f %.2f %.2f) (%s)", HER_ACTOR, g_home[0], g_home[1], g_home[2], ini);
        Install(nullptr);
    }
    return TRUE;
}
