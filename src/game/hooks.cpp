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
X86_EXTERN_FUNC(__imp__sub_0019D190);
X86_FUNC(sub_0019D190) {
    uint32_t level = kernel::R32(ctx.esp + 4);
    __imp__sub_0019D190(ctx, base);
    uint32_t games = tools::g_season_games;
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
        uint32_t games = tools::g_season_games;
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
    uint32_t games = tools::g_season_games;
    if (games < 12 || games >= 162 || v > 1000) return v;
    return uint32_t(uint64_t(v) * 162 / games);
}
}  // namespace
X86_EXTERN_FUNC(__imp__sub_001C9A00);
X86_FUNC(sub_001C9A00) {
    uint32_t ret = kernel::R32(ctx.esp);
    __imp__sub_001C9A00(ctx, base);
    if (ret == 0x499987) ctx.eax = As162(ctx.eax);
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
    uint32_t games = tools::g_season_games;
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

// More memory. The game puts nearly all it loads (stadiums, players, crowds) in one heap it makes at start (0x2C3BD0):
// XPhysicalAlloc (0x2D31E0) of 41 MB (40.75 MB with HD video modes), cleared and handed to the heap (0x2DB06A) with
// the size still in esi. With memory_mb = 128 the Xbox's RAM is doubled (src/common/game_info.cpp) and the heap grows
// by 56 MB of the extra 64, the rest left for what the game allocates outside it; esi is given the new size when the
// call returns, so the clearing and the heap use it too.
X86_EXTERN_FUNC(__imp__sub_002D31E0);
X86_FUNC(sub_002D31E0) {
    uint32_t ret = kernel::R32(ctx.esp), size = kernel::R32(ctx.esp + 4);
    bool heap = ret == 0x2C3BFA && mem::kPhysicalSize >= (128u << 20) && (size == 0x2900000 || size == 0x28C0000);
    uint32_t grown = size + (56u << 20);
    if (heap) kernel::W32(ctx.esp + 4, grown);
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

// Player detail. Each player model has levels of detail 0 (the most detailed) to 2, and 3 for the least. Which one a
// player gets comes from his "importance" (how close and how central to the play he is) against thresholds in the
// game's "lod" tuning (datafile.big's datafile.txt: PLAYER_LOD_0..2_INGAME/OUTOFGAME/HRD/JUMBOTRON_MIN_IMPORTANCE):
// 0x274D90 (lod tuning, importance, out of game, home run derby, jumbotron) returns the first level whose threshold
// the importance beats, else 3. The Xbox uses the "xboxlod" set (in play 40/20/10: level 0 above 40, 1 above 20, 2
// above 10); the file also has the GameCube's, the PS2's and three PC detail levels. With player_full_detail, levels
// 1 and 2 become 0 (3, the game's least for the least important players, is kept in case it hides as well).
X86_EXTERN_FUNC(__imp__sub_00274D90);
X86_FUNC(sub_00274D90) {
    __imp__sub_00274D90(ctx, base);
    if (tools::g_player_full_detail && (ctx.eax == 1 || ctx.eax == 2)) ctx.eax = 0;
}

// Weather. When a game's stadium is set up (0x283B10..), its weather pattern is picked at random and handed to
// 0x27CA60 (thiscall: pattern, flag; returning to 0x283B71): 0 none, 1 and 2 a shower starting some minutes in
// (2 lasting longer), 3 rain from the start for the whole game (only offered at one setting, 0x3E). The rain is drawn
// (0x27D5B0, when EA's "Draw Rain" switch 0x63B200 is on, as it is) from the pattern's timing and strength. With
// rain = 1 every game gets pattern 3.
X86_EXTERN_FUNC(__imp__sub_0027CA60);
X86_FUNC(sub_0027CA60) {
    uint32_t ret = kernel::R32(ctx.esp);
    if (ret == 0x283B71) {
        uint32_t pattern = kernel::R32(ctx.esp + 4);
        if (tools::g_rain == 1) kernel::W32(ctx.esp + 4, 3);
        LOGR("weather: pattern %u%s", pattern, tools::g_rain == 1 ? " (rain in every game: 3)" : "");
    }
    __imp__sub_0027CA60(ctx, base);
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
