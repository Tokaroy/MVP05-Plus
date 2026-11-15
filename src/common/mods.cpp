// See mods.h. mods.txt: one mod a line, first wins; "on <folder>" or "off <folder>", '#' starts a comment.
#include "mods.h"

#include <fstream>
#include <string>

#include "app/app.h"
#include "core/log.h"
#include "kernel/kernel.h"

namespace mods {
namespace {
namespace fs = std::filesystem;
std::vector<fs::path> g_enabled;

std::string U8(const fs::path& p) {
    auto s = p.u8string();
    return std::string(s.begin(), s.end());
}

std::string Trim(std::string s) {
    while (!s.empty() && (s.back() == '\r' || s.back() == ' ' || s.back() == '\t')) s.pop_back();
    size_t a = s.find_first_not_of(" \t");
    return a == std::string::npos ? std::string() : s.substr(a);
}
}  // namespace

void Load() {
    g_enabled.clear();
    const fs::path dir = app::ExeDir() / "mods";
    std::ifstream f(dir / "mods.txt");
    if (!f) return;
    std::string line;
    int off = 0;
    while (std::getline(f, line)) {
        line = Trim(line);
        if (line.empty() || line[0] == '#') continue;
        bool on = line.rfind("on ", 0) == 0;
        if (!on && line.rfind("off ", 0) != 0) continue;
        std::string name = Trim(line.substr(on ? 3 : 4));
        if (name.empty() || name.find("..") != std::string::npos || name.find_first_of("/\\:") != std::string::npos)
            continue;
        if (!on) {
            off++;
            continue;
        }
        std::error_code ec;
        fs::path p = dir / fs::path(std::u8string(name.begin(), name.end()));
        if (fs::is_directory(p, ec))
            g_enabled.push_back(p);
        else
            LOGR("mods: %s is on but its folder isn't in mods", name.c_str());
    }
    std::string names;
    for (auto& p : g_enabled) names += (names.empty() ? "" : ", ") + U8(p.filename());
    LOGR("mods: %zu on%s%s (%d off)", g_enabled.size(), g_enabled.empty() ? "" : ": ", names.c_str(), off);
}

void Mount() {
    for (auto& p : g_enabled) kernel::SetDiscOverlay(p);
}

const std::vector<fs::path>& Enabled() { return g_enabled; }

}  // namespace mods
