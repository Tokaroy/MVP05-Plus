// Hooks for default.xbe. A strong definition replaces the recompiled function at that address, for example:
//
// #include "xdk/hle.h"
//
// X86_EXTERN_FUNC(__imp__sub_00012345);
// X86_FUNC(sub_00012345) {
//     __imp__sub_00012345(ctx, base);  // the original
// }

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <map>
#include <mutex>
#include <cstring>

#include "core/log.h"
#include "kernel/kernel.h"
#include "kernel/memory.h"
#include "xdk/hle.h"
#include "../common/tools_overlay.h"

// Short seasons. The game's season length for a league (cdecl, its level: 0 and 1 the majors, 2 and 3 AAA, 4 AA,
// 5 to 9 A ball; 162, 144, 142 and 140 games) is what the standings code measures a season against: games left,
// and whether the regular season is over (it's asked at 0x466692 and 0x467008 for a team, at 0x49174D for a league,
// and for the halves through 0x1AEC10). The majors are given the schedule's own length (counted from schedule.big
// when the game starts, src/common/season_length.cpp), so a short season ends by itself.
//
// A dynasty keeps the season it's playing in its save, so a schedule switched in the Launcher part-way through a
// season only starts with the next one, and until then the installed schedule.big says the wrong length. The season
// being played is in memory: the schedule set at [[0x6572A0]+0x28] holds the four levels' schedules (the majors'
// first), each {capacity, games, records}, a record 28 bytes with the home team's id at +4 and the road team's at
// +0x10 (0x463C00 counts a team's games left that way). When the majors' has 30 teams all playing the same 12 to
// 162 games (the two All-Star teams, one game each, aside), that is the season's length, and it's kept through the
// playoffs, whose schedule is only the series. Otherwise it's the installed schedule's.
//
// Spring training is played from the same slot (mlbspr_1.dat: 30 teams, 22 games each), and must not be taken for a
// 22-game season. Its loader (0x477500) empties the three minor-league schedules, which a season's loader (0x4775C0)
// fills (2,160 games in AAA), so a majors' schedule only counts as a season when AAA's has games too. In spring
// training the length is the installed schedule's: the season about to be loaded from it.
namespace {
bool InHeap(uint32_t va, uint32_t n) {
    return va >= 0x80000000u && va - 0x80000000u < mem::kPhysicalSize && n <= mem::kPhysicalSize - (va - 0x80000000u);
}
uint32_t CountSchedule(uint32_t records, uint32_t count) {
    std::map<uint32_t, uint32_t> games;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t home = kernel::R32(records + i * 28 + 4), road = kernel::R32(records + i * 28 + 0x10);
        if (home == road) return 0;
        games[home]++;
        games[road]++;
        if (games.size() > 32) return 0;
    }
    uint32_t teams = 0, length = 0;
    for (auto& [team, n] : games) {
        if (n == 1) continue;  // an All-Star team
        if (length && n != length) return 0;
        length = n;
        teams++;
    }
    return teams == 30 && length >= 12 && length <= 162 ? length : 0;
}
uint32_t SeasonGames() {
    static uint32_t key[6] = {}, counted = 0, last_good = 0;
    uint32_t mgr = kernel::R32(0x6572A0), set = InHeap(mgr, 0x2C) ? kernel::R32(mgr + 0x28) : 0;
    uint32_t sched = InHeap(set, 8) ? kernel::R32(set) : 0;
    if (!InHeap(sched, 12)) {  // no season in memory (the menus, an exhibition): nothing kept from the last one
        key[0] = 0;
        last_good = 0;
        return tools::g_season_games;
    }
    uint32_t count = kernel::R32(sched + 4), records = kernel::R32(sched + 8);
    if (count < 2 || count > 2600 || !InHeap(records, count * 28)) return last_good ? last_good : tools::g_season_games;
    uint32_t aaa = kernel::R32(set + 4), minors = InHeap(aaa, 12) ? kernel::R32(aaa + 4) : 0;
    uint32_t now[6] = {sched, count, records, kernel::R32(records + 4) ^ kernel::R32(records + 0x10),
                       kernel::R32(records + (count - 1) * 28 + 4) ^ kernel::R32(records + (count - 1) * 28 + 0x10),
                       minors};
    if (std::memcmp(now, key, sizeof key) != 0) {
        std::memcpy(key, now, sizeof key);
        counted = CountSchedule(records, count);
        if (counted && (minors < 360 || minors > 2600)) {  // spring training: the season to come
            counted = 0;
            last_good = 0;
        }
        if (counted && counted != last_good) {
            if (counted != tools::g_season_games)
                LOGR("season length: the season being played has %u games a team (the installed schedule: %u, from "
                     "the next season)", counted, tools::g_season_games);
            else
                LOGR("season length: the season being played has %u games a team", counted);
        }
        if (counted) last_good = counted;
    }
    return last_good ? last_good : tools::g_season_games;
}
}  // namespace
X86_EXTERN_FUNC(__imp__sub_0019D190);
X86_FUNC(sub_0019D190) {
    uint32_t level = kernel::R32(ctx.esp + 4);
    __imp__sub_0019D190(ctx, base);
    uint32_t games = SeasonGames();
    if ((level == 0 || level == 1) && ctx.eax == 162 && games >= 12 && games < 162) {
        LOG_FIRST(1, "short season: the majors' season is %u games", games);
        ctx.eax = games;
    }
}

// Dynasty goals in a short season. A team's goals live in an object of 32 records (vtable 0x5B8BCC; record i at
// +4 + 12*i: on/off byte, then X at +8 and Y at +12; names in the "gol" tuning group at 0x637EA8: XCyYoung,
// TopXCyYoung, ..., WinX@Home, WinX@Away, XHRsforTeam, WinPct, WinX, ..., XHRsYplayers, XWinsbyYP, ...). The targets
// are sized for 162-game seasons. The functions that read them for the goals screen, their text and whether a goal
// is met (all thiscall on that object) see the counting targets scaled by the season's length while they run; the
// object itself (and so the save) keeps the game's own numbers. The win-percentage goal is checked as wins against
// X * 486 (three 162-game seasons, 0x5B8C30): while the check runs, its X is scaled the same way.
namespace {

constexpr uint32_t kGoalVtable = 0x5B8BCC;
constexpr uint32_t kCounting[] = {9, 10, 12, 14, 27, 28};  // WinX@Home, WinX@Away, XHRsforTeam, WinX, XHRsYplayers,
                                                           // XWinsbyYP (X: home/road/total wins, HRs, a pitcher's wins)
constexpr uint32_t kWinPct = 13;
thread_local int g_goal_depth = 0;

uint32_t GoalAt(uint32_t obj, uint32_t i) { return obj + 8 + 12 * i; }

struct ScaledGoals {
    uint32_t obj = 0;
    uint32_t saved[8] = {};
    bool pct = false;
    ScaledGoals(uint32_t o, bool with_pct) {
        uint32_t games = SeasonGames();
        if (g_goal_depth++ || games < 12 || games >= 162 || kernel::R32(o) != kGoalVtable) return;
        obj = o;
        pct = with_pct;
        int k = 0;
        for (uint32_t i : kCounting) {
            uint32_t at = GoalAt(obj, i), x = kernel::R32(at);
            saved[k++] = x;
            if (x > 0 && x < 100000) {
                uint32_t s = uint32_t((uint64_t(x) * games + 81) / 162);
                kernel::W32(at, s ? s : 1);
            }
        }
        if (pct) {
            uint32_t at = GoalAt(obj, kWinPct), bits = kernel::R32(at);
            saved[k] = bits;
            float f;
            std::memcpy(&f, &bits, 4);
            f = f * float(games) / 162.0f;
            std::memcpy(&bits, &f, 4);
            kernel::W32(at, bits);
        }
        LOG_FIRST(1, "short season: dynasty goals' counting targets scaled to %u games", games);
    }
    ~ScaledGoals() {
        g_goal_depth--;
        if (!obj) return;
        int k = 0;
        for (uint32_t i : kCounting) kernel::W32(GoalAt(obj, i), saved[k++]);
        if (pct) kernel::W32(GoalAt(obj, kWinPct), saved[k]);
    }
};

}  // namespace

// whether a goal is met (goal, value): the counting targets and the win percentage's
X86_EXTERN_FUNC(__imp__sub_001DC8C0);
X86_FUNC(sub_001DC8C0) {
    ScaledGoals s(ctx.ecx, true);
    __imp__sub_001DC8C0(ctx, base);
}
// a goal's progress
X86_EXTERN_FUNC(__imp__sub_001DC960);
X86_FUNC(sub_001DC960) {
    ScaledGoals s(ctx.ecx, false);
    __imp__sub_001DC960(ctx, base);
}
// a goal's text ("Win %1 Total %2 Games")
X86_EXTERN_FUNC(__imp__sub_001DCB10);
X86_FUNC(sub_001DCB10) {
    ScaledGoals s(ctx.ecx, false);
    __imp__sub_001DCB10(ctx, base);
}
// the goals screen's line for a goal, and its progress figure
X86_EXTERN_FUNC(__imp__sub_001F63E0);
X86_FUNC(sub_001F63E0) {
    ScaledGoals s(ctx.ecx, false);
    __imp__sub_001F63E0(ctx, base);
}
X86_EXTERN_FUNC(__imp__sub_001F6650);
X86_FUNC(sub_001F6650) {
    ScaledGoals s(ctx.ecx, false);
    __imp__sub_001F6650(ctx, base);
}

// The 40/40 goal (FortyForty) has no X: the goal tracker (db_sec, 0x499987/0x499996) reads a player's season
// home runs and stolen bases (0x1C9A00, 0x1C98E0) and compares each with a fixed 40. For those two reads only, a
// short season's totals are given as if over 162 games, so 40/40 means about 11/11 in a 46-game season.
namespace {
uint32_t As162(uint32_t v) {
    uint32_t games = SeasonGames();
    if (games < 12 || games >= 162 || v > 1000) return v;
    return uint32_t(uint64_t(v) * 162 / games);
}
}  // namespace
//
// The two per-player goals count players in the same tracker: "X home runs by Y players" (goal 27, 0x49A2F8) reads
// each player's home runs (0x1C9A00, returning to 0x49A33A) and "X wins by Y pitchers" (goal 28, 0x4999CD) each
// pitcher's wins (0x1CA0D0, returning to 0x499A15), and compares them with the goal's X, which the tracker takes
// straight from the goal object (0x4998C1), not through the readers above that scale it. So those two reads are
// given as if over 162 games too: with X 20 shown as 8 in a 64-game season, 8 home runs count.
X86_EXTERN_FUNC(__imp__sub_001C9A00);
X86_FUNC(sub_001C9A00) {
    uint32_t ret = kernel::R32(ctx.esp);
    __imp__sub_001C9A00(ctx, base);
    if (ret == 0x499987 || ret == 0x49A33A) ctx.eax = As162(ctx.eax);
}
X86_EXTERN_FUNC(__imp__sub_001CA0D0);
X86_FUNC(sub_001CA0D0) {
    uint32_t ret = kernel::R32(ctx.esp);
    __imp__sub_001CA0D0(ctx, base);
    if (ret == 0x499A15) ctx.eax = As162(ctx.eax);
}
X86_EXTERN_FUNC(__imp__sub_001C98E0);
X86_FUNC(sub_001C98E0) {
    uint32_t ret = kernel::R32(ctx.esp);
    __imp__sub_001C98E0(ctx, base);
    if (ret == 0x499996) ctx.eax = As162(ctx.eax);
}

// The win-percentage goal's progress figure (db_sec 0x49A02B: goal 13 in the goal tracker) is wins over the games
// of the contract so far, counted as 162 for each finished season (imul edi,edi,0xA2 at 0x49A083) plus this
// season's games played (0x1ACF30, returning to 0x49A092). With edi still holding the finished seasons' 162s when
// that call returns, they are made the season's length instead, so a 46-game dynasty shows wins over 46s.
X86_EXTERN_FUNC(__imp__sub_001ACF30);
X86_FUNC(sub_001ACF30) {
    uint32_t ret = kernel::R32(ctx.esp);
    __imp__sub_001ACF30(ctx, base);
    uint32_t games = SeasonGames();
    if (ret == 0x49A092 && games >= 12 && games < 162 && ctx.edi % 162 == 0 && ctx.edi <= 162 * 2)
        ctx.edi = ctx.edi / 162 * games;
}

// Pitchers' stamina between games. The dynasty keeps every pitcher's current stamina in "pitcher.dat", a table
// (vtable 0x5ADC04, records of 20 bytes at [this+0x24], count at [this+0x20]) whose field 27 is the current stamina
// (bits 7..13 of the record's word at +0x10; field 0 is the stamina rating, the most it can be). The game gives each
// pitcher back about a quarter of his rating every day (10 + 15% of it: 24 a day at 97), so a 100-pitch start is
// gone in two days and relievers are never tired. Every write of field 27 goes through SetField (0x19FB30, thiscall:
// field, record, value); for pitcher.dat (the only table that big; the in-game teams' copies have 25) a rise is cut
// to pitcher_recovery percent of itself. Drops (pitching) are left alone, and so are the two refills to the full
// rating (new season, 0x1A5997 and 0x1C122C).
namespace {
constexpr uint32_t kStaminaTable = 0x5ADC04, kCurrentStamina = 27;
}  // namespace
X86_EXTERN_FUNC(__imp__sub_0019FB30);
X86_FUNC(sub_0019FB30) {
    uint32_t self = ctx.ecx, ret = kernel::R32(ctx.esp), field = kernel::R32(ctx.esp + 4),
             rec = kernel::R32(ctx.esp + 8), value = kernel::R32(ctx.esp + 12);
    if (field == kCurrentStamina && kernel::R32(self) == kStaminaTable) {
        uint32_t count = kernel::R32(self + 0x20);
        if (rec < count) {
            uint32_t base_rec = kernel::R32(self + 0x24) + rec * 20;
            int old = int((kernel::R32(base_rec + 0x10) >> 7) & 0x7F), now = std::clamp(int(value), 0, 127);
            int pct = int(std::min<uint32_t>(tools::g_pitcher_recovery, 100));
            bool big = count >= 100, refill = ret == 0x1A5997 || ret == 0x1C122C;
            static std::mutex m;  // which code writes it, for checking: the first 6 writes from each place
            static std::map<uint32_t, int> seen;
            {
                std::lock_guard<std::mutex> lock(m);
                if (seen[ret]++ < 6)
                    LOGR("stamina: field 27 set from %08X (table of %u, record %u): %d -> %d%s", ret, count, rec, old,
                         now, big && !refill && pct < 100 && now > old ? " (recovery cut)" : "");
            }
            if (!big && ret == 0x8F9FA) {
                // a pitch thrown in the game being played (0x8F9F5 writes the pitcher's stamina in his in-game
                // team's table, of 25 records): remembered
                // for the Tools menu's Stamina Changer, the pitcher who threw last first
                auto& m0 = tools::g_mound[0];
                auto& m1 = tools::g_mound[1];
                if (m0.table.load() != self) {
                    m1.table = m0.table.load();
                    m1.record = m0.record.load();
                    m1.stamina = m0.stamina.load();
                }
                m0.table = self;
                m0.record = rec;
                m0.stamina = uint32_t(now);
            }
            if (big && !refill && pct < 100 && now > old) {
                int scaled = old + ((now - old) * pct + 50) / 100;
                if (scaled == old) scaled = old + 1;
                kernel::W32(ctx.esp + 12, uint32_t(scaled));
            }
        }
    }
    __imp__sub_0019FB30(ctx, base);
}

// Injury length. The dynasty keeps every player's injury in "attrib.dat" (vtable 0x5ADCC4, records of 60 bytes at
// [this+0x24], count at [this+0x20]): field 30 is the injury's kind and field 31 (the record's byte at +0x14) the days
// left. A new injury's days are written through SetField (0x1A1CA0, thiscall: field, record, value), from the game
// just played (0x1BE8EA) or the dynasty's own (0x1CDC55), and the days count down from there. A rise of field 31 in
// attrib.dat (the in-game teams' copies are far smaller) is made injury_length percent of itself.
namespace {
constexpr uint32_t kAttribTable = 0x5ADCC4, kInjuryDays = 31;
}  // namespace
X86_EXTERN_FUNC(__imp__sub_001A1CA0);
X86_FUNC(sub_001A1CA0) {
    uint32_t self = ctx.ecx, ret = kernel::R32(ctx.esp), field = kernel::R32(ctx.esp + 4),
             rec = kernel::R32(ctx.esp + 8), value = kernel::R32(ctx.esp + 12);
    uint32_t pct = std::min<uint32_t>(tools::g_injury_length, 400);
    if (field == kInjuryDays && kernel::R32(self) == kAttribTable) {
        uint32_t count = kernel::R32(self + 0x20);
        if (rec < count && count >= 1000) {
            int old = int(kernel::G<uint8_t>(kernel::R32(self + 0x24) + rec * 60 + 0x14)), now = std::clamp(int(value), 0, 255);
            int scaled = now;
            if (pct != 100 && pct > 0 && now > old) scaled = std::clamp(old + ((now - old) * int(pct) + 50) / 100, old + 1, 255);
            static std::mutex m;
            static std::map<uint32_t, int> seen;
            {
                std::lock_guard<std::mutex> lock(m);
                if (seen[ret]++ < 6)
                    LOGR("injury: days set from %08X (record %u): %d -> %d%s", ret, rec, old, now,
                         scaled != now ? " (length changed)" : "");
            }
            if (scaled != now) kernel::W32(ctx.esp + 12, uint32_t(scaled));
        }
    }
    __imp__sub_001A1CA0(ctx, base);
}

// Auto Fix Roster without a way out. The roster fixer (0x4901D0, cdecl: team; run from the injury pop-up's Auto Fix
// at 0x1C66AB, and for the computer's teams) fills the rotation in a loop: while the team has fewer than five
// starters (0x1B8C30, returning to 0x4902A5) it picks a pitcher (0x4771B0) and adds him (0x1B8DA0). When no pitcher
// can be picked (enough of the staff hurt at once, which longer injuries make likelier) nothing is added, the count
// never reaches five and the loop never ends: the game freezes. Five passes is all the loop can need, so after
// twelve the count is given as five and the fixer goes on with the starters it has.
namespace {
thread_local uint32_t g_rotation_passes = 0;
}
X86_EXTERN_FUNC(__imp__sub_004901D0);
X86_FUNC(sub_004901D0) {
    g_rotation_passes = 0;
    __imp__sub_004901D0(ctx, base);
}
X86_EXTERN_FUNC(__imp__sub_001B8C30);
X86_FUNC(sub_001B8C30) {
    uint32_t ret = kernel::R32(ctx.esp), team = kernel::R32(ctx.esp + 4);
    __imp__sub_001B8C30(ctx, base);
    if (ret == 0x4902A5 && int32_t(ctx.eax) < 5 && ++g_rotation_passes > 12) {
        LOGR("roster: Auto Fix couldn't find a fifth starter for team %u (%d in the rotation): going on without", team,
             int32_t(ctx.eax));
        ctx.eax = 5;
    }
}

// Contract prices. What a player asks for (free agents and the dynasty's own players re-signing alike) comes from
// 0x462720 (thiscall on the negotiation; ecx at entry), not from contract.csv's $ columns: the game never reads those
// (only its years, at 0x636294..0x63629C). It blends the player's current salary toward a value from his ratings,
// rounds it to the game's salary steps (0x1AC660: step * [db+0x1F8] + [db+0x1F4], db = [0x657288]) and caps it at
// step 0x2143, then writes the asking price at +4 and the least he'll take at +8. With contract_prices those two are
// made that percent of themselves, rounded to a step and capped as the game does.
X86_EXTERN_FUNC(__imp__sub_00462720);
X86_FUNC(sub_00462720) {
    uint32_t self = ctx.ecx;
    static uint32_t last_self = 0, last_bits[2] = {};  // what this left there last, so it's never scaled twice
    uint32_t pre[2] = {self ? kernel::R32(self + 4) : 0, self ? kernel::R32(self + 8) : 0};
    __imp__sub_00462720(ctx, base);
    uint32_t pct = tools::g_contract_prices;
    uint32_t db = kernel::R32(0x657288);
    if (pct == 100 || pct == 0 || !self || !db) return;
    auto getf = [](uint32_t va) { uint32_t u = kernel::R32(va); float f; std::memcpy(&f, &u, 4); return f; };
    auto setf = [](uint32_t va, float f) { uint32_t u; std::memcpy(&u, &f, 4); kernel::W32(va, u); };
    float step = getf(db + 0x1F8), add = getf(db + 0x1F4);
    if (!(step > 0.0f)) return;
    // the call can leave without working a price out: then what's there is what was there (ours, when it's the same
    // negotiation), and it's left alone. So is anything that isn't a salary (under the lowest, or not a number)
    uint32_t post[2] = {kernel::R32(self + 4), kernel::R32(self + 8)};
    if (self == last_self && post[0] == pre[0] && post[1] == pre[1] && post[0] == last_bits[0] && post[1] == last_bits[1])
        return;
    float before[2], after[2];
    for (int k = 0; k < 2; k++) {
        float v = getf(self + 4 + 4 * k);
        before[k] = v;
        if (!(v >= add) || !(v < add + step * float(0x2143 + 1))) return;
        float want = v * float(pct) / 100.0f;
        int steps = int((want - add) / step + 0.5f);
        steps = std::clamp(steps, 0, 0x2143);
        after[k] = float(steps) * step + add;
    }
    for (int k = 0; k < 2; k++) setf(self + 4 + 4 * k, after[k]);
    last_self = self;
    last_bits[0] = kernel::R32(self + 4);
    last_bits[1] = kernel::R32(self + 8);
    static std::atomic<int> told{0};
    if (told.fetch_add(1) < 8)
        LOGR("contracts: asking %.0f -> %.0f, least %.0f -> %.0f (%u%%)", before[0], after[0], before[1], after[1], pct);
}

// More memory. The game puts nearly all it loads (stadiums, players, crowds) in one heap it makes at start (0x2C3BD0):
// XPhysicalAlloc (0x2D31E0) of 41 MB (40.75 MB with HD video modes), cleared and handed to the heap (0x2DB06A) with
// the size still in esi. With memory_mb = 128 the Xbox's RAM is doubled (src/common/game_info.cpp) and the heap grows
// by 56 MB of the extra 64, the rest left for what the game allocates outside it; esi is given the new size when the
// call returns, so the clearing and the heap use it too.
static void PlayerDetailPools();
X86_EXTERN_FUNC(__imp__sub_002D31E0);
X86_FUNC(sub_002D31E0) {
    uint32_t ret = kernel::R32(ctx.esp), size = kernel::R32(ctx.esp + 4);
    bool heap = ret == 0x2C3BFA && mem::kPhysicalSize >= (128u << 20) && (size == 0x2900000 || size == 0x28C0000);
    uint32_t grown = size + (56u << 20);
    if (heap) kernel::W32(ctx.esp + 4, grown);
    if (ret == 0x2C3BFA) PlayerDetailPools();  // at boot, before the pools are made
    __imp__sub_002D31E0(ctx, base);
    if (heap) {
        if (ctx.eax) {
            ctx.esi = grown;
            LOGR("memory: the game's heap is %u MB (Xbox RAM %u MB)", grown >> 20, mem::kPhysicalSize >> 20);
        } else {
            LOGE("memory: couldn't make the game's heap %u MB", grown >> 20);
        }
    }
}

// Player detail. Every character on the field (players, umpires, coaches) is drawn with a "body" from one of four
// pools, one a level of detail: 0 the most detailed (the only one with the player's own face), then 1, 2 and 3. The
// pools' sizes are the table at 0x59B358: 6, 10, 20 and 25 bodies. A character asks for a level (0x81AC0, a virtual
// of his) and gets a body from that pool through 0x12D820 (thiscall on the pools at [0x653EA0]+0x11D54: character,
// level, keys): his own from last time, else a free one, else the one least recently used if nobody has used it this
// frame or the last; when every body in the pool is in use it calls itself for the next level down (returning to
// 0x12D9A9). So only six characters are ever at full detail, and the umpires and the fielders away from the play
// are at 2 or 3 while the pitcher pitches.
//
// The pools can't be made bigger by their table. When the game boots it builds each body from the level's model
// file (models/hibody, bgbody, mebody, lobody: 0x12D640 for all four levels and 0x12DA10 for 1 to 3, from 0x12D7E0
// and 0x12F7E0), taking the file's next body each time (0x3001A0 with a running index), and the files hold exactly
// 6, 10, 20 and 25. A body past the file's last gets nothing, and the game crashes on it in the first load screen:
// that was the crash with this option when it made pool 1 55 bodies and pool 0 40 (Beta 2.5 test builds). More
// bodies would need the model file loaded again for each extra set; not done.
//
// So player_full_detail only changes what's asked for: a request for level 2 or 3 becomes one for level 1. The ten
// level 1 bodies go to the first ten who ask in a frame, and the rest fall to level 2 as the game does it itself, so
// nobody is drawn at level 3 until 36 are on the field. The call the game makes on itself for the next level down is
// left as it is (changing that one back to 1 would never end).
//
// The "importance" thresholds in datafile.big's lod tuning (xboxlod's PLAYER_LOD_*_MIN_IMPORTANCE) and the chooser
// that reads them (0x274D90, through 0x274DE0) are not what decides: nothing in the game calls that chooser.
static void PlayerDetailPools() {}  // (the pools stay the game's own size: see above)

X86_EXTERN_FUNC(__imp__sub_0012D820);
X86_FUNC(sub_0012D820) {
    uint32_t ret = kernel::R32(ctx.esp), level = kernel::R32(ctx.esp + 8), give = level;
    if (tools::g_player_full_detail && (level == 2 || level == 3) && ret != 0x12D9A9) {
        give = 1;
        kernel::W32(ctx.esp + 8, give);
    }
    static std::atomic<uint32_t> asked[5], given[5], fell{0}, calls{0};
    if (level < 5 && give < 5 && calls.load() < 5000) {
        if (ret == 0x12D9A9) fell++;
        else asked[level]++, given[give]++;
        if (calls.fetch_add(1) + 1 == 5000)
            LOGR("player detail: over 5000 requests, asked for levels 0 to 3: %u, %u, %u, %u (none %u); given: %u, %u, "
                 "%u, %u; passed down a level by the game: %u",
                 asked[0].load(), asked[1].load(), asked[2].load(), asked[3].load(), asked[4].load(), given[0].load(),
                 given[1].load(), given[2].load(), given[3].load(), fell.load());
    }
    __imp__sub_0012D820(ctx, base);
}

// Rain. The game has rain (EA's debug menu has "Rain Pattern" and "Draw Rain"), but it only makes the weather object
// at four stadiums: the scene set-up at 0x128A32 calls 0x286A70 (cdecl: scene, the set-up's first argument, stadium
// number) only when the scene is a game (scene+0x6F0 == 0) and the stadium number is 0x13 or 0x39 (SBC Park, day and
// night), 0x3E (Safeco Field at night) or 0x23 (a002day); the numbers index the stadium file table at 0x62E4B0.
// 0x286A70 makes the object (kept at 0x660384, freed with the scene at 0x271F10) and resets it with 0x283AB0, which
// picks the pattern: a number 0..8, and 1 or 2 (a shower) when it is one of those, so 2 games in 9, else none (0x27CA60,
// thiscall: pattern, start now). The rain is drawn as lines by the object itself (0x27D5B0), with nothing loaded from
// the stadium, so it works anywhere.
//
// With rain = 1 every outdoor stadium gets the weather object, with the game's own odds. With rain = 2 every game has
// pattern 3 (rain for the whole game) from the start: 0x27CA60 only keeps a 3 when the object's +0x3C is set, and
// only starts at once when "start now" is. The object is made from the call just before the game's own check
// (0x270950, returning to 0x128A23, where edi is the scene, esi the stadium's entry and ebp the set-up's frame), and
// not in the four domes (astrdome, metrdome, olymdome, tropdome: 73 to 76).
X86_EXTERN_FUNC(__imp__sub_00286A70);
X86_FUNC(sub_00286A70) {
    __imp__sub_00286A70(ctx, base);
    uint32_t obj = kernel::R32(0x660384);
    if (tools::g_rain == 2 && obj) {
        uint32_t result = ctx.eax, ecx = ctx.ecx;
        kernel::W32(obj + 0x3C, 1);
        ctx.ecx = obj;
        kernel::CallGuest(ctx, 0x27CA60, {3, 1});
        ctx.ecx = ecx;
        ctx.eax = result;
        kernel::W32(0x663EC0, 3);
        LOGR("weather: rain for the whole game");
    } else if (obj) {
        LOGR("weather: the game's own pattern, %u (0 none, 1 and 2 a shower)", kernel::R32(obj + 0x24));
    }
}

X86_EXTERN_FUNC(__imp__sub_00270950);
X86_FUNC(sub_00270950) {
    bool setup = kernel::R32(ctx.esp) == 0x128A23;
    __imp__sub_00270950(ctx, base);
    if (!setup || !tools::g_rain) return;
    uint32_t scene = ctx.edi, entry = ctx.esi;
    if (!scene || !entry || kernel::R32(scene + 0x6F0) != 0 || kernel::R32(0x660384)) return;
    uint32_t stadium = kernel::R32(entry);
    bool own = stadium == 0x13 || stadium == 0x39 || stadium == 0x3E || stadium == 0x23;  // the game makes these
    bool dome = stadium >= 73 && stadium <= 76;
    if (own || dome || stadium > 84) return;
    LOGR("weather: stadium %u given the game's rain", stadium);
    kernel::CallGuest(ctx, 0x286A70, {scene, kernel::R32(ctx.ebp + 8), stadium});
}

// Things the Tools menu asks the game to do, run by the game's own thread at the end of a frame: the two functions
// that hand a finished frame to D3D (0x2F9320 and 0x2F8D00, around D3DDevice_Swap).
namespace {
void RunToolRequests(X86Context& ctx) {
    if (tools::g_unlock_request.load() == 1) {
        // EA's "Unlock All Unlockables" (debug menu button, 0x204600): every unlockable for the profile signed in
        // (0x311650 on the profile manager at 0x657288; -1 when there's none)
        uint32_t profiles = kernel::R32(0x657288), saved_ecx = ctx.ecx;
        ctx.ecx = profiles;
        uint32_t who = profiles ? kernel::CallGuest(ctx, 0x311650, {}) : 0xFFFFFFFFu;
        ctx.ecx = saved_ecx;
        if (who == 0xFFFFFFFFu) {
            tools::g_unlock_request = 3;
        } else {
            kernel::CallGuest(ctx, 0x204600, {});
            tools::g_unlock_request = 2;
            LOGR("extras: unlocked everything for profile %u", who);
        }
    }
    if (tools::g_points_request.load() == 1) {
        // EA's "Add Points" (debug menu button, 0x4C9D80): 0x1AD690 (thiscall on the profile manager: profile,
        // points) adds MVP points to the profile (capped by the game)
        uint32_t profiles = kernel::R32(0x657288), saved_ecx = ctx.ecx;
        ctx.ecx = profiles;
        uint32_t who = profiles ? kernel::CallGuest(ctx, 0x311650, {}) : 0xFFFFFFFFu;
        if (who == 0xFFFFFFFFu) {
            tools::g_points_request = 3;
        } else {
            ctx.ecx = profiles;
            kernel::CallGuest(ctx, 0x1AD690, {who, tools::g_points_amount.load()});
            tools::g_points_request = 2;
            LOGR("extras: added %u MVP points to profile %u", tools::g_points_amount.load(), who);
        }
        ctx.ecx = saved_ecx;
    }
    // Stamina Changer: the stamina of a pitcher in the game being played, through the table's own SetField (0x19FB30,
    // thiscall: field 27, record, value), if the table is still one (its vtable, and the record within its count)
    if (int which = tools::g_stamina_request.load()) {
        auto& m = tools::g_mound[which == 2 ? 1 : 0];
        uint32_t table = m.table.load(), rec = m.record.load(), want = std::min<uint32_t>(tools::g_stamina_want.load(), 99);
        if (table && kernel::R32(table) == kStaminaTable && rec < kernel::R32(table + 0x20) && kernel::R32(table + 0x20) < 100) {
            uint32_t saved_ecx = ctx.ecx, saved_eax = ctx.eax;
            ctx.ecx = table;
            kernel::CallGuest(ctx, 0x19FB30, {kCurrentStamina, rec, want});
            ctx.ecx = saved_ecx;
            ctx.eax = saved_eax;
            m.stamina = (kernel::R32(kernel::R32(table + 0x24) + rec * 20 + 0x10) >> 7) & 0x7F;
            LOGR("stamina changer: pitcher %u of the in-game table set to %u", rec, want);
        } else {
            m.table = 0;  // that game is over
        }
        tools::g_stamina_request = 0;
    }
    // drop the remembered pitchers once their tables are gone
    for (auto& m : tools::g_mound)
        if (uint32_t t = m.table.load(); t && kernel::R32(t) != kStaminaTable) m.table = 0;
    // The payroll budget is the team's org_budget (field 21 of org.dat's table), in the game's $100,000 steps: set to
    // 110% of the payroll when a dynasty starts (0x471670) and moved each off-season by how the team did (0x49C0C0).
    // Read and set through the game's own accessors on the database (0x657288): 0x1ADF50 (0) is the dynasty's own
    // team, 0x1ACCB0 (field, team) reads, 0x1ACCE0 (field, team, value) sets; a step is [db+0x204] dollars on top
    // of [db+0x1F4] (0x1AC6E0). Kept up to date only while the Tools menu is open with a dynasty loaded.
    if (tools::Open() && kernel::R32(0x658250) && kernel::R32(0x657288)) {
        uint32_t db = kernel::R32(0x657288), saved_ecx = ctx.ecx, saved_eax = ctx.eax;
        auto f = [](uint32_t va) { uint32_t u = kernel::R32(va); float x; std::memcpy(&x, &u, 4); return x; };
        float step = f(db + 0x204), add = f(db + 0x1F4);
        ctx.ecx = db;
        uint32_t team = kernel::CallGuest(ctx, 0x1ADF50, {0});
        if (step > 0 && team < 64) {
            if (tools::g_budget_request.load() == 1) {
                int steps = std::clamp(int((tools::g_budget_want.load() - add) / step + 0.5f), 0, 0x7FFF);
                ctx.ecx = db;
                kernel::CallGuest(ctx, 0x1ACCE0, {0x15, team, uint32_t(steps)});
                LOGR("dynasty: team %u's payroll budget set to $%.1f million", team, (steps * step + add) / 1e6f);
            }
            ctx.ecx = db;
            uint32_t steps = kernel::CallGuest(ctx, 0x1ACCB0, {0x15, team});
            tools::g_budget_now = steps < 0x100000 ? float(steps) * step + add : -1.0f;
        } else {
            tools::g_budget_now = -1.0f;
        }
        tools::g_budget_request = 0;
        ctx.ecx = saved_ecx;
        ctx.eax = saved_eax;
    } else if (!tools::Open()) {
        tools::g_budget_request = 0;
    }
    if (tools::g_debug_menu_request.load() == 1) {
        // EA's debug menu is built in the released game (root 0x26D280: Restart, Quit, Debug_Hit, Camera,
        // ScriptMenu, Scenario, Replay, RealReplay, Debug_FielderAI, Teleport_Fielder, Fielding, Player_Render,
        // Stadium Render, Render, Create-A-Venue, Misc, Mudlark, Batting, Tuning, Debug_Audio, Controllers) and so
        // is its controller (0x2BD600, kept at 0x65A714; the front end makes its own, 0x232FE4). What's off is the
        // controller's reading of the pads: its update (0x2BD760) only polls them (0x2A3050) while the byte at
        // 0x63D068 is 1, and the constructor clears that when the debug flag 0x65A720 (never set in this build) is
        // 0. Event 11 to its handler (0x2AF310, thiscall on controller + 0x24) shows or hides the menu and pauses
        // the game as it does; with the byte set, the pads then work it.
        uint32_t controller = kernel::R32(0x65A714);
        if (!controller) {
            tools::g_debug_menu_request = 3;
        } else {
            uint32_t saved_ecx = ctx.ecx;
            *static_cast<uint8_t*>(kernel::HostPtr(0x63D068)) = 1;
            ctx.ecx = controller + 0x24;
            kernel::CallGuest(ctx, 0x2AF310, {11});
            ctx.ecx = saved_ecx;
            tools::g_debug_menu_request = 2;
            LOGR("extras: EA's debug menu %s", kernel::R32(0x663AB0) & 0xFF ? "shown" : "hidden");
        }
    }
}
}  // namespace
X86_EXTERN_FUNC(__imp__sub_002F9320);
X86_FUNC(sub_002F9320) {
    __imp__sub_002F9320(ctx, base);
    RunToolRequests(ctx);
}
X86_EXTERN_FUNC(__imp__sub_002F8D00);
X86_FUNC(sub_002F8D00) {
    __imp__sub_002F8D00(ctx, base);
    RunToolRequests(ctx);
}
