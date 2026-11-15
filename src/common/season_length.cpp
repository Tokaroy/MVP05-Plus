// The season's length, from the schedule the game will play: assets/data/database/schedule.big is read when the game
// starts, its three MLB season files (mlb162_1/2/3.dat, RefPack'd CSV: DATE,GAMETIME,HOME,AWAY,HALF,...) counted, and
// the games each team plays become tools::g_season_games. The short-season hook (src/game/hooks.cpp) gives the majors
// that length, so a season ends when its schedule does, however the schedule got there. Without a readable schedule,
// or one whose teams don't all play the same number of games, the setting stays as it was (season_games in
// mvp05-settings.toml, from the Launcher's Schedule tab; 162 by default).
#include "season_length.h"

#include <cctype>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "app/app.h"
#include "core/log.h"
#include "tools_overlay.h"

namespace season {
namespace {

namespace fs = std::filesystem;

std::string Lower(std::string s) {
    for (auto& c : s) c = char(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

// assets/data/database/schedule.big, whatever the case of its folders
fs::path FindSchedule() {
    std::error_code ec;
    fs::path dir = app::ExeDir() / "assets";
    for (const char* part : {"data", "database", "schedule.big"}) {
        fs::path next;
        for (auto it = fs::directory_iterator(dir, ec); !ec && it != fs::directory_iterator(); it.increment(ec)) {
            if (Lower(it->path().filename().string()) == part) {
                next = it->path();
                break;
            }
        }
        if (next.empty()) return {};
        dir = next;
    }
    return dir;
}

uint32_t Be32(const uint8_t* p) { return uint32_t(p[0]) << 24 | uint32_t(p[1]) << 16 | uint32_t(p[2]) << 8 | p[3]; }

// EA's RefPack, as tools/installer/schedules.py's refpack_decompress
bool Unpack(const uint8_t* d, size_t n, std::vector<uint8_t>& out) {
    if (n < 5 || d[1] != 0xFB) return false;
    size_t w = (d[0] & 0x80) ? 4 : 3;
    size_t size = 0;
    for (size_t i = 0; i < w; i++) size = size << 8 | d[2 + i];
    size_t p = 2 + w + ((d[0] & 0x01) ? w : 0);
    out.clear();
    out.reserve(size);
    while (p < n) {
        uint8_t b0 = d[p];
        size_t lit, len = 0, off = 0;
        if (b0 < 0x80) {
            if (p + 1 >= n) return false;
            uint8_t b1 = d[p + 1];
            p += 2;
            lit = b0 & 3;
            len = ((b0 >> 2) & 7) + 3;
            off = ((b0 & 0x60) << 3) + b1 + 1;
        } else if (b0 < 0xC0) {
            if (p + 2 >= n) return false;
            uint8_t b1 = d[p + 1], b2 = d[p + 2];
            p += 3;
            lit = b1 >> 6;
            len = (b0 & 0x3F) + 4;
            off = ((b1 & 0x3F) << 8) + b2 + 1;
        } else if (b0 < 0xE0) {
            if (p + 3 >= n) return false;
            uint8_t b1 = d[p + 1], b2 = d[p + 2], b3 = d[p + 3];
            p += 4;
            lit = b0 & 3;
            len = ((b0 & 0x0C) << 6) + b3 + 5;
            off = ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1;
        } else if (b0 < 0xFC) {
            lit = ((b0 & 0x1F) << 2) + 4;
            if (p + 1 + lit > n) return false;
            out.insert(out.end(), d + p + 1, d + p + 1 + lit);
            p += 1 + lit;
            continue;
        } else {
            lit = b0 & 3;
            if (p + 1 + lit > n) return false;
            out.insert(out.end(), d + p + 1, d + p + 1 + lit);
            break;
        }
        if (p + lit > n) return false;
        out.insert(out.end(), d + p, d + p + lit);
        p += lit;
        if (off > out.size()) return false;
        for (size_t i = 0; i < len; i++) out.push_back(out[out.size() - off]);
    }
    return out.size() == size;
}

// the games each team plays in one season file, the All-Star Game (AL/NL) left out; 0 unless every team plays the
// same number
int GamesPerTeam(const std::vector<uint8_t>& text) {
    std::map<std::string, int> games;
    std::string s(text.begin(), text.end());
    size_t pos = s.find('\n');  // past the header
    while (pos != std::string::npos && pos < s.size()) {
        size_t end = s.find('\n', pos + 1);
        std::string line = s.substr(pos + 1, (end == std::string::npos ? s.size() : end) - pos - 1);
        pos = end;
        std::vector<std::string> f;
        size_t a = 0;
        while (true) {
            size_t b = line.find(',', a);
            std::string v = line.substr(a, b == std::string::npos ? std::string::npos : b - a);
            while (!v.empty() && std::isspace(static_cast<unsigned char>(v.back()))) v.pop_back();
            while (!v.empty() && std::isspace(static_cast<unsigned char>(v.front()))) v.erase(v.begin());
            f.push_back(v);
            if (b == std::string::npos) break;
            a = b + 1;
        }
        if (f.size() < 5 || f[0].empty() || f[2] == "AL" || f[2] == "NL") continue;
        games[f[2]]++;
        games[f[3]]++;
    }
    if (games.size() != 30) return 0;
    std::set<int> counts;
    for (auto& [team, n] : games) counts.insert(n);
    return counts.size() == 1 ? *counts.begin() : 0;
}

}  // namespace

void FromSchedule() {
    fs::path big = FindSchedule();
    if (big.empty()) {
        LOGR("season length: no schedule.big in assets; %u games (season_games)", tools::g_season_games);
        return;
    }
    std::ifstream f(big, std::ios::binary);
    std::vector<uint8_t> d((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    if (d.size() < 16 || std::memcmp(d.data(), "BIGF", 4) != 0) {
        LOGR("season length: schedule.big isn't a BIG archive; %u games (season_games)", tools::g_season_games);
        return;
    }
    uint32_t count = Be32(&d[8]);
    size_t p = 16;
    std::map<std::string, int> found;
    for (uint32_t i = 0; i < count && p + 8 < d.size(); i++) {
        uint32_t off = Be32(&d[p]), size = Be32(&d[p + 4]);
        size_t e = p + 8;
        while (e < d.size() && d[e]) e++;
        std::string name = Lower(std::string(reinterpret_cast<const char*>(&d[p + 8]), e - p - 8));
        p = e + 1;
        auto slash = name.find_last_of("/\\");
        if (slash != std::string::npos) name = name.substr(slash + 1);
        if (name != "mlb162_1.dat" && name != "mlb162_2.dat" && name != "mlb162_3.dat") continue;
        if (size_t(off) + size > d.size()) continue;
        std::vector<uint8_t> text;
        if (size > 1 && d[off + 1] == 0xFB) {
            if (!Unpack(&d[off], size, text)) continue;
        } else {
            text.assign(d.begin() + off, d.begin() + off + size);
        }
        found[name] = GamesPerTeam(text);
    }
    std::set<int> lengths;
    for (auto& [name, n] : found) lengths.insert(n);
    if (found.size() != 3 || lengths.size() != 1 || *lengths.begin() < 1 || *lengths.begin() > 162) {
        LOGR("season length: couldn't count the schedule's games (%zu of 3 season files, %s); %u games "
             "(season_games)", found.size(), lengths.size() > 1 ? "of different lengths" : "every team not the same",
             tools::g_season_games);
        return;
    }
    uint32_t games = uint32_t(*lengths.begin());
    if (games != tools::g_season_games)
        LOGR("season length: the schedule has %u games a team (season_games said %u)", games, tools::g_season_games);
    else
        LOGR("season length: %u games a team, from schedule.big", games);
    tools::g_season_games = games;
}

}  // namespace season
