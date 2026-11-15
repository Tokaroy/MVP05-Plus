// See daylight.h. lighting.csv pairs each stadium file with a lighting set from datafile.big: "fenwday,02dusk".
// The number is the sun's angle for that park; the day sets are 01day..06day (with _c/_o variants). A dusk set's park
// is given the same number's day set: 02dusk -> 02day, 03dusk_c -> 03day, 03dusk_e -> 03day, 06dusk_c -> 06day_c.
#include "day_parks.h"

#include <cctype>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

#include "app/app.h"
#include "core/log.h"
#include "kernel/kernel.h"
#include "tools_overlay.h"

namespace dayparks {
namespace {
namespace fs = std::filesystem;

std::string Lower(std::string s) {
    for (auto& c : s) c = char(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

fs::path FindCi(fs::path dir, std::initializer_list<const char*> parts) {
    std::error_code ec;
    for (const char* part : parts) {
        fs::path next;
        for (auto it = fs::directory_iterator(dir, ec); !ec && it != fs::directory_iterator(); it.increment(ec))
            if (Lower(it->path().filename().string()) == part) {
                next = it->path();
                break;
            }
        if (next.empty()) return {};
        dir = next;
    }
    return dir;
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
    fs::remove(app::ExeDir() / "tweaks" / "data" / "stadium" / "lighting.csv", rm);  // last time's, if any
    if (!tools::g_daylight_parks) return;
    fs::path src = FindCi(app::ExeDir() / "assets", {"data", "stadium", "lighting.csv"});
    if (src.empty()) {
        LOGR("daylight: no assets/data/stadium/lighting.csv; parks keep their lighting");
        return;
    }
    std::ifstream in(src, std::ios::binary);
    std::stringstream out;
    std::string line, changed;
    while (std::getline(in, line)) {
        bool cr = !line.empty() && line.back() == '\r';
        if (cr) line.pop_back();
        auto comma = line.find(',');
        // only day files ("...day"): the night ones stay night
        if (comma != std::string::npos && comma >= 3 && Lower(line.substr(comma - 3, 3)) == "day") {
            std::string day = DayFor(Lower(line.substr(comma + 1)));
            if (!day.empty()) {
                changed += (changed.empty() ? "" : ", ") + line.substr(0, comma);
                line = line.substr(0, comma + 1) + day;
            }
        }
        out << line << (cr ? "\r\n" : "\n");
    }
    fs::path dir = app::ExeDir() / "tweaks" / "data" / "stadium";
    std::error_code ec;
    fs::create_directories(dir, ec);
    std::ofstream(dir / "lighting.csv", std::ios::binary) << out.str();
    kernel::SetDiscOverlay(app::ExeDir() / "tweaks");
    LOGR("daylight: day games in daylight at %s", changed.empty() ? "(none to change)" : changed.c_str());
}

}  // namespace dayparks
