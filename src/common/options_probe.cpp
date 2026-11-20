// Test build only: where the game keeps its audio options once an Options save is loaded, so MVP05-Plus can put
// your saved ones back when the game starts (the game itself only loads them from Options > Load).
//
// Every 3 seconds: the newest "(Options)" save's five volume bytes (payload 0x2C8, after the section marker at 0x2C0)
// are looked for in the game's memory, and each place they're found is written to the log, with the bytes around it
// and, later, whenever what's there changes. Nothing is written to the game or the save.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
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
        if (std::memcmp(p + 0x2C0, kMarker, 4) != 0) {
            LOG_FIRST(1, "options probe: %s isn't laid out as expected", e.path().string().c_str());
            continue;
        }
        std::memcpy(out, p + 0x2C8, 5);
        which = e.path().filename().string();
        best = t;
        found = true;
    }
    return found;
}

std::vector<uint32_t> Find(const uint8_t v[5]) {
    std::vector<uint32_t> hits;
    uint8_t* base = mem::Base();
    if (!base) return hits;
    auto scan = [&](uint32_t from, uint32_t to) {
        for (uint32_t page = from; page < to && hits.size() < 64; page += mem::kPage) {
            if (!mem::IsCommitted(page)) continue;
            const uint8_t* p = base + page;
            for (uint32_t i = 0; i + 5 <= mem::kPage; i++)
                if (p[i] == v[0] && std::memcmp(p + i, v, 5) == 0) hits.push_back(page + i);
        }
    };
    scan(mem::kUserLow, 0x10000000);
    scan(mem::kContiguousBase, mem::kContiguousBase + mem::kPhysicalSize);
    return hits;
}

std::string Around(uint32_t a) {
    char s[8];
    std::string out;
    for (int i = -16; i < 24; i++) {
        uint32_t va = a + uint32_t(i);
        if (!mem::IsCommitted(va)) continue;
        snprintf(s, sizeof(s), i == 0 ? "[%02X" : i == 4 ? "%02X] " : "%02X ", mem::Base()[va]);
        out += s;
    }
    return out;
}

void Run() {
    using namespace std::chrono_literals;
    std::this_thread::sleep_for(15s);
    uint8_t last[5] = {}, v[5];
    std::vector<uint32_t> watched;
    std::vector<std::vector<uint8_t>> seen;
    int told = 0;
    for (;; std::this_thread::sleep_for(3s)) {
        std::string which;
        if (NewestVolumes(v, which) && (std::memcmp(v, last, 5) != 0 || watched.empty())) {
            std::memcpy(last, v, 5);
            auto hits = Find(v);
            static size_t last_count = ~size_t(0);
            if (hits.size() != last_count && told++ < 40)
                LOGR("options probe: %s's volumes %u %u %u %u %u found at %zu places", which.c_str(), v[0], v[1], v[2],
                     v[3], v[4], hits.size());
            last_count = hits.size();
            for (size_t i = 0; i < hits.size() && i < 24; i++) {
                if (std::find(watched.begin(), watched.end(), hits[i]) != watched.end()) continue;
                watched.push_back(hits[i]);
                seen.emplace_back(5, 0);
                LOGR("options probe:   %08X: %s", hits[i], Around(hits[i]).c_str());
            }
        }
        for (size_t i = 0; i < watched.size(); i++) {  // what's at each place now, when it changes
            std::vector<uint8_t> now(5);
            for (int k = 0; k < 5; k++)
                now[k] = mem::IsCommitted(watched[i] + k) ? mem::Base()[watched[i] + k] : 0;
            if (now != seen[i] && told < 200) {
                told++;
                LOGR("options probe: %08X now %u %u %u %u %u", watched[i], now[0], now[1], now[2], now[3], now[4]);
                seen[i] = now;
            }
        }
    }
}
}  // namespace

void Start() { std::thread(Run).detach(); }

}  // namespace optprobe
