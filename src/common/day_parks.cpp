// See day_parks.h. lighting.csv pairs each stadium file with a lighting set from datafile.big: "fenwday,02dusk".
// The number is the sun's angle for that park; the day sets are 01day..06day (with _c/_o variants). A dusk set's park
// is given the same number's day set: 02dusk -> 02day, 03dusk_c -> 03day, 03dusk_e -> 03day, 06dusk_c -> 06day_c.
// The lighting set only lights the players and the field; the sky is a picture in the stadium's own .big
// (data/stadium/<park>.big: sky0.xsh, one texture), and a dusk park's is a dusk sky (Fenway's
// "skb4", purple and pink). So each changed park also gets the sky of a park that is a day park in the game, with
// the same day set (02day: Camden Yards, say), written as a copy of its .big in tweaks.
#include "day_parks.h"

#include <cctype>
#include <cstring>
#include <map>
#include <vector>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

#include "app/app.h"
#include "core/log.h"
#include "kernel/kernel.h"
#include "bigfile.h"
#include "tools_overlay.h"

namespace dayparks {
namespace {
namespace fs = std::filesystem;

std::string Lower(std::string s) {
    for (auto& c : s) c = char(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

// park's sky*.xsh entries replaced by donor's, each keeping its own texture name (the SHPX directory's first
// entry: 4 letters at 16); written to tweaks/data/stadium/<park>.big. False if either can't be read.
bool GiveSky(const std::string& park, const std::string& donor) {
    std::string pb = park + ".big", db = donor + ".big";
    fs::path pp = bigfile::FindAsset({"data", "stadium", pb.c_str()}), dp = bigfile::FindAsset({"data", "stadium", db.c_str()});
    bigfile::Archive pa, da;
    if (pp.empty() || dp.empty() || !bigfile::Read(pp, pa) || !bigfile::Read(dp, da)) return false;
    std::map<std::string, const bigfile::Entry*> skies;
    for (auto& e : da.entries)
        if (Lower(e.name).rfind("sky", 0) == 0 && Lower(e.name).size() > 4 && Lower(e.name).substr(Lower(e.name).size() - 4) == ".xsh")
            skies[Lower(e.name)] = &e;
    int done = 0;
    for (auto& e : pa.entries) {
        auto it = skies.find(Lower(e.name));
        if (it == skies.end()) continue;
        std::vector<uint8_t> mine, theirs;
        if (!bigfile::Unpack(e.data.data(), e.data.size(), mine) ||
            !bigfile::Unpack(it->second->data.data(), it->second->data.size(), theirs))
            continue;
        if (mine.size() < 24 || theirs.size() < 24 || std::memcmp(mine.data(), "SHPX", 4) != 0 ||
            std::memcmp(theirs.data(), "SHPX", 4) != 0)
            continue;
        // The texture's name is in the file twice: in its directory (4 letters at 16) and in the name block at
        // its end (type 0x70, then the name), which is the one the game registers it under: "skb4" for Fenway's
        // sky, which its model asks for by name. Both are given this park's name (the first try changed only the
        // directory's, and the game drew its missing-texture pattern for the sky).
        uint8_t theirs_name[4], mine_name[4];
        std::memcpy(theirs_name, theirs.data() + 16, 4);
        std::memcpy(mine_name, mine.data() + 16, 4);
        std::memcpy(theirs.data() + 16, mine_name, 4);
        bool tail = false;
        for (size_t at = theirs.size() >= 64 ? theirs.size() - 64 : 20; at + 8 <= theirs.size(); at++)
            if (theirs[at] == 0x70 && !theirs[at + 1] && !theirs[at + 2] && !theirs[at + 3] &&
                std::memcmp(theirs.data() + at + 4, theirs_name, 4) == 0) {
                std::memcpy(theirs.data() + at + 4, mine_name, 4);
                tail = true;
            }
        if (!tail) continue;  // not laid out as expected: this park keeps its own sky
        bool packed = e.data.size() >= 2 && e.data[0] == 0x10 && e.data[1] == 0xFB;
        e.data = packed ? bigfile::Pack(theirs) : theirs;
        done++;
    }
    if (!done) return false;
    return bigfile::Write(bigfile::TweaksDir({"data", "stadium"}) / pb, pa);
}

// the day set for a dusk set, or "" to keep it
std::string DayFor(const std::string& set) {
    if (set == "02dusk" || set == "02dusk_c") return "02day";
    if (set == "03dusk_c" || set == "03dusk_e") return "03day";
    if (set == "05dusk") return "05day";
    if (set == "06dusk_c") return "06day_c";
    return "";
}
}  // namespace

void Apply() {
    std::error_code rm;
    const fs::path tw = app::ExeDir() / "tweaks" / "data" / "stadium";
    fs::remove(tw / "lighting.csv", rm);  // last time's, if any
    for (auto it = fs::directory_iterator(tw, rm); !rm && it != fs::directory_iterator(); it.increment(rm))
        if (Lower(it->path().extension().string()) == ".big") fs::remove(it->path(), rm);
    rm.clear();
    if (!tools::g_daylight_parks) return;
    fs::path src = bigfile::FindAsset({"data", "stadium", "lighting.csv"});
    if (src.empty()) {
        LOGR("daylight: no assets/data/stadium/lighting.csv; parks keep their lighting");
        return;
    }
    std::ifstream in(src, std::ios::binary);
    std::stringstream out;
    std::string line, changed;
    std::vector<std::pair<std::string, std::string>> moved;  // park, its new day set
    std::map<std::string, std::vector<std::string>> day_parks;  // day set: the game's own parks with it
    while (std::getline(in, line)) {
        bool cr = !line.empty() && line.back() == '\r';
        if (cr) line.pop_back();
        auto comma = line.find(',');
        // only day files ("...day"): the night ones stay night
        if (comma != std::string::npos && comma >= 3 && Lower(line.substr(comma - 3, 3)) == "day") {
            std::string set = Lower(line.substr(comma + 1));
            while (!set.empty() && (set.back() == ' ' || set.back() == '\t')) set.pop_back();
            std::string day = DayFor(set);
            if (!day.empty()) {
                changed += (changed.empty() ? "" : ", ") + line.substr(0, comma);
                moved.push_back({Lower(line.substr(0, comma)), day});
                line = line.substr(0, comma + 1) + day;
            } else {
                day_parks[set].push_back(Lower(line.substr(0, comma)));
            }
        }
        out << line << (cr ? "\r\n" : "\n");
    }
    fs::path dir = app::ExeDir() / "tweaks" / "data" / "stadium";
    std::error_code ec;
    fs::create_directories(dir, ec);
    std::ofstream(dir / "lighting.csv", std::ios::binary) << out.str();
    // their skies: from the first of the game's own parks on the same day set (06day_c's, 02day's, ...)
    std::string skies;
    // a plain sky first where there's a choice (Coors' may have its mountains in it), then the rest in order
    static const std::map<std::string, std::string> kPrefer = {
        {"02day", "orioday"}, {"03day", "bankday"}, {"05day", "bushday"}, {"06day_c", "shibday"}};
    for (auto& [park, day] : moved) {
        std::string from;
        std::vector<std::string> donors = day_parks[day];
        if (auto p = kPrefer.find(day); p != kPrefer.end()) donors.insert(donors.begin(), p->second);
        for (const std::string& donor : donors)
            if (GiveSky(park, donor)) {
                from = donor;
                break;
            }
        skies += (skies.empty() ? "" : ", ") + park + (from.empty() ? " (kept its own)" : " from " + from);
    }
    bigfile::UseTweaks();
    LOGR("daylight: day games in daylight at %s", changed.empty() ? "(none to change)" : changed.c_str());
    if (!skies.empty()) LOGR("daylight: day skies for %s", skies.c_str());
}

}  // namespace dayparks
