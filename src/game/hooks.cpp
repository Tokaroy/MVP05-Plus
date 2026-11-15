// Hooks for default.xbe. A strong definition replaces the recompiled function at that address, for example:
//
// #include "xdk/hle.h"
//
// X86_EXTERN_FUNC(__imp__sub_00012345);
// X86_FUNC(sub_00012345) {
//     __imp__sub_00012345(ctx, base);  // the original
// }

#include <cstdint>
#include <cstring>

#include "core/log.h"
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
