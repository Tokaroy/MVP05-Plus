#pragma once
// Day games in daylight: EA lit some parks' day versions as dusk (Fenway, Turner Field, ...). When daylight_parks is
// on, a copy of the game's assets/data/stadium/lighting.csv with those parks given the day lighting of the same sun
// angle is put in front of the game's own (an overlay folder, "tweaks" beside the exe).
namespace dayparks {
void Apply();  // at start, after the settings, before boot
}
