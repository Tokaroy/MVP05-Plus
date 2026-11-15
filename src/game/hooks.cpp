// Hooks for default.xbe. A strong definition replaces the recompiled function at that address, for example:
//
// #include "xdk/hle.h"
//
// X86_EXTERN_FUNC(__imp__sub_00012345);
// X86_FUNC(sub_00012345) {
//     __imp__sub_00012345(ctx, base);  // the original
// }

#include <cstdint>

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
