#pragma once
// MVP05-Plus Tools inside the game: F10, or Back + Start held for a second on a controller, opens and closes it.
// While it's open the game gets no controller input, and the controllers move around the menu instead.
#include <atomic>
#include <cstdint>

#include "core/input.h"

namespace tools {

extern uint32_t g_pitcher_recovery;  // percent of the game's own between-games stamina recovery (100: as the game)
extern uint32_t g_injury_length;  // percent of the game's own injury lengths in a dynasty (100: as the game)
extern uint32_t g_memory_mb;  // the Xbox's RAM: 64 (as the console) or 128, with the game's heap grown to match
extern uint32_t g_rain;  // 0 the game's own (rain at SBC Park, Safeco at night), 1 at every outdoor park, 2 in every game
extern bool g_daylight_parks;  // day games in daylight at the parks EA lit as dusk (Fenway, ...): lighting and sky
extern bool g_player_full_detail;  // a request for detail level 2 or 3 becomes one for level 1 (hooks.cpp)
// dynasty data tweaks (dynasty_data.cpp): percents of the game's own (100: as the game), resign_chance 100 +/- points,
// rookie_quality 1 better / 2 much better
extern uint32_t g_dev_speed, g_aging, g_retirement, g_contract_prices, g_resign_chance, g_rookie_quality;
// asked for from the Tools menu, done by the game's own thread at the end of a frame (src/game/hooks.cpp)
extern std::atomic<int> g_unlock_request;  // 1: asked, 2: done, 3: no profile signed in
// Stamina Changer: the two pitchers who last threw in the game being played (hooks.cpp keeps them: the in-game team's
// pitcher table, the record and his stamina now; table 0: none), newest first, and a stamina to give one of them
struct MoundPitcher {
    std::atomic<uint32_t> table{0}, record{0}, stamina{0};
};
extern MoundPitcher g_mound[2];
extern std::atomic<int> g_stamina_request;   // 1 or 2: set g_mound[request - 1]'s stamina to g_stamina_want
extern std::atomic<uint32_t> g_stamina_want;
// the payroll budget of the dynasty's own team, kept by the game thread while the menu is open (hooks.cpp): dollars now
// (below 0: none to show), and a new figure to set when the request is 1
extern std::atomic<float> g_budget_now, g_budget_want;
extern std::atomic<int> g_budget_request;
extern std::atomic<int> g_debug_menu_request;  // EA's debug menu: 1 asked, 2 done, 3 not made yet
extern std::atomic<int> g_points_request;  // MVP points: 1 asked, 2 done, 3 no profile signed in
extern std::atomic<uint32_t> g_points_amount;
extern uint32_t g_season_games;  // the schedule's length: counted from schedule.big at start, else season_games

bool Open();
// window messages: F10, and Esc closing the menu instead of asking to quit
bool Message(void* hwnd, uint32_t msg, uintptr_t wp, intptr_t lp, intptr_t* result);
void Ui(double fps);
// every polled pad: the open combo, and while open the pad goes to the menu instead of the game
void Pad(int port, input::Pad& p);

}  // namespace tools
