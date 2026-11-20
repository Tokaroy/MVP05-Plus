// Test build only: where the game keeps its audio options once an Options save is loaded, so MVP05-Plus can put
// your saved ones back when the game starts (the game itself only loads them from Options > Load).
//
// The Options save keeps the five volumes as bytes, 51 a step (0 to 5 on the Audio Options screen: Broadcast, Game
// Sound FX, Crowd, Music, Menu Sound FX in the save's order). In memory they may be kept another way, so every 3
// seconds the game's memory is searched for all five of the newest Options save's values close together, as bytes,
// 32-bit numbers or floats, as the save has them or as the screen's 0 to 5 (or 0.0 to 1.0). Each place found is
// logged with the bytes around it, and again whenever they change. Nothing is written to the game or the save.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <set>
#include <string>
#include <thread>
#include <vector>

#include "app/app.h"
#include "core/log.h"
#include "kernel/memory.h"

namespace optprobe {
namespace {
namespace fs = std::filesystem;

bool NewestVolumes(uint8_t out[5], std::string& which) {
    fs::path dir = app::ExeDir() / "hdd" / "E" / "UDATA" / "45410056";
    std::error_code ec;
    fs::file_time_type best{};
    bool found = false;
    for (auto& e : fs::directory_iterator(dir, ec)) {
        std::ifstream meta(e.path() / "SaveMeta.xbx", std::ios::binary);
        std::string m((std::istreambuf_iterator<char>(meta)), {});
        std::string ascii;
        for (size_t i = 0; i < m.size(); i += 2) ascii += m[i];
        if (ascii.find("(Options)") == std::string::npos) continue;
        auto t = fs::last_write_time(e.path() / "data.dat", ec);
        if (ec || (found && t <= best)) continue;
        std::ifstream f(e.path() / "data.dat", std::ios::binary);
        std::vector<uint8_t> d((std::istreambuf_iterator<char>(f)), {});
        if (d.size() != 0x108 + 0x400) continue;
        const uint8_t* p = d.data() + 0x108;
        static const uint8_t kMarker[4] = {0x0D, 0xF0, 0xEF, 0xBE};
        if (std::memcmp(p + 0x2C0, kMarker, 4) != 0) continue;
        std::memcpy(out, p + 0x2C8, 5);
        which = e.path().filename().string();
        best = t;
        found = true;
    }
    return found;
}

struct Way {
    const char* name;
    int size;     // 1, 4 (an integer or a float)
    bool real;    // a float
    double scale; // the value looked for: the save's byte / scale
};
const Way kWays[] = {{"bytes as saved", 1, false, 1}, {"bytes 0-5", 1, false, 51}, {"ints as saved", 4, false, 1},
                     {"ints 0-5", 4, false, 51}, {"floats 0-1", 4, true, 255}, {"floats 0-5", 4, true, 51},
                     {"floats as saved", 4, true, 1}, {"shorts as saved", 2, false, 1}};

bool Match(const uint8_t* p, const Way& w, double want) {
    if (w.real) {
        float f;
        std::memcpy(&f, p, 4);
        return std::fabs(double(f) - want) < 0.003 * std::max(1.0, want);
    }
    uint32_t v = w.size == 1 ? p[0] : w.size == 2 ? uint32_t(p[0] | p[1] << 8) : uint32_t(p[0] | p[1] << 8 | p[2] << 16 | p[3] << 24);
    return double(v) == want;
}

struct Hit {
    uint32_t at;
    const Way* way;
};

// places where all five values (any order) sit within a few fields of each other
std::vector<Hit> Find(const uint8_t v[5]) {
    std::vector<Hit> hits;
    uint8_t* base = mem::Base();
    if (!base) return hits;
    for (const Way& w : kWays) {
        double want[5];
        std::set<double> distinct;
        for (int i = 0; i < 5; i++) {
            want[i] = w.scale == 51 ? std::round(v[i] / 51.0) : v[i] / w.scale;  // (0-5: the screen's steps)
            distinct.insert(want[i]);
        }
        if (distinct.size() < 4) continue;  // (too ordinary to find)
        const uint32_t span = uint32_t(w.size) * 12;  // the five within twelve fields
        const size_t before = hits.size();
        auto scan = [&](uint32_t from, uint32_t to) {
            for (uint32_t page = from; page < to && hits.size() < before + 10; page += mem::kPage) {
                if (!mem::IsCommitted(page) || !mem::IsCommitted(page + mem::kPage)) continue;
                const uint8_t* p = base + page;
                for (uint32_t i = 0; i < mem::kPage; i += uint32_t(w.size)) {
                    if (!Match(p + i, w, want[0])) continue;
                    // all five within [i - span, i + span]
                    int got = 0;
                    for (int k = 0; k < 5; k++) {
                        bool seen = false;
                        for (uint32_t j = i >= span ? i - span : 0; j <= i + span && !seen; j += uint32_t(w.size))
                            seen = Match(p + j, w, want[k]);
                        got += seen;
                    }
                    if (got == 5) {
                        hits.push_back({page + i, &w});
                        i += span;
                    }
                }
            }
        };
        scan(mem::kUserLow, 0x10000000);
        scan(mem::kContiguousBase, mem::kContiguousBase + mem::kPhysicalSize - mem::kPage);
    }
    return hits;
}

std::string Around(uint32_t a, int before = 32, int after = 48) {
    char s[8];
    std::string out;
    for (int i = -before; i < after; i++) {
        uint32_t va = a + uint32_t(i);
        if (!mem::IsCommitted(va)) continue;
        snprintf(s, sizeof(s), i == 0 ? "[%02X " : "%02X ", mem::Base()[va]);
        out += s;
    }
    return out;
}

void Run() {
    using namespace std::chrono_literals;
    std::this_thread::sleep_for(15s);
    uint8_t last[5] = {}, v[5];
    std::vector<uint32_t> watched;
    std::vector<std::string> seen;
    int told = 0;
    for (;; std::this_thread::sleep_for(3s)) {
        std::string which;
        if (!NewestVolumes(v, which)) continue;
        bool changed = std::memcmp(v, last, 5) != 0;
        if (changed || watched.empty()) {
            std::memcpy(last, v, 5);
            auto hits = Find(v);
            static size_t last_count = ~size_t(0);
            if ((hits.size() != last_count || changed) && told++ < 40)
                LOGR("options probe: %s's volumes %u %u %u %u %u found at %zu places", which.c_str(), v[0], v[1], v[2],
                     v[3], v[4], hits.size());
            last_count = hits.size();
            for (auto& h : hits) {
                if (std::find(watched.begin(), watched.end(), h.at) != watched.end()) continue;
                if (watched.size() >= 24) break;
                watched.push_back(h.at);
                seen.push_back(Around(h.at, 8, 56));
                LOGR("options probe:   %08X (%s): %s", h.at, h.way->name, Around(h.at).c_str());
            }
        }
        for (size_t i = 0; i < watched.size(); i++) {  // what's there now, when it changes
            std::string now = Around(watched[i], 8, 56);
            if (now != seen[i] && told++ < 200) {
                LOGR("options probe: %08X now %s", watched[i], now.c_str());
                seen[i] = now;
            }
        }
    }
}
}  // namespace

void Start() { std::thread(Run).detach(); }

}  // namespace optprobe
