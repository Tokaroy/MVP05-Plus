#pragma once
// The game's tuning, datafile.big's datafile.txt (lines of records "0x<hash> <n><name>;<field> <value>;...", each
// after the line naming its fields "0x<hash> <n> <v>;<field> <name>;..."), changed for Game Tweaks without touching the
// game's files: a copy of datafile.big with the changed datafile.txt goes in the "tweaks" overlay folder beside the
// exe, which the game reads in place of its own.
namespace tuning {
void Apply();  // at start, after the settings, before boot
}
