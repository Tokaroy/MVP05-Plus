#pragma once
// Mods: folders under "mods" beside the exe, laid out like the game's assets folder, turned on and ordered in
// mods\mods.txt (the Launcher's Mods tab writes it). Each one that's on is a replacement folder for the game's disc:
// the first in the list with a file wins, then the Game Tweaks' own changed copies win over all of them (the tweaks
// start from the mod's file when a mod has one). The game's own files are never changed.
#include <filesystem>
#include <vector>

namespace mods {
void Load();   // reads mods.txt: at start, before the Game Tweaks
void Mount();  // adds the mods' folders to the disc, after the Game Tweaks
// the folders of the mods that are on, first (winning) first
const std::vector<std::filesystem::path>& Enabled();
}  // namespace mods
