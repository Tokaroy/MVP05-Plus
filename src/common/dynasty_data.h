#pragma once
// Dynasty Game Tweaks on the game's data tables (assets/data/database): player development and aging
// (progress.big's progbadj/progpadj.csv: by age and star level, the chance ratings go up, down or stay), contract
// prices (contract.csv), re-signing (resign.csv), retirement and rookie star levels
// (rookie.big's retire.csv and star.csv). Changed copies go in the "tweaks" overlay folder beside the exe.
namespace dynastydata {
void Apply();  // at start, after the settings, before boot
}
