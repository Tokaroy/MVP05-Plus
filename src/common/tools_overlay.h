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
extern bool g_player_full_detail;  // every player drawn with his most detailed model (the game drops distant ones to lower ones)
extern bool g_daylight_parks;  // day games in daylight at the parks EA lit as dusk (Fenway, ...)
extern bool g_depth_of_field;  // EA's depth of field (xbox_render's DOF IsActive, off on the Xbox)
extern uint32_t g_rain;  // 0: the game's own weather, 1: rain in every game
// asked for from the Tools menu, done by the game's own thread at the end of a frame (src/game/hooks.cpp)
extern std::atomic<int> g_unlock_request;  // 1: asked, 2: done, 3: no profile signed in
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
