// Your Options save, put back when the game starts. The game only loads it from Options > Load, so until then it
// plays with its own options (and the Options screens show them). hooks.cpp reads it into the game the way Load does.
//
// The Options save's data.dat is 1288 bytes: 0x108 of header, then the options as the game wrote them (0x400, of
// which 0x2D7 are used): the profile's options object, a marker (0xBEEFF00D), the rest of it (the five volumes at
// 0x2C8: Broadcast, Game Sound FX, Crowd, Music, Menu Sound FX, 51 a step of the screen's 0 to 5), another marker,
// and the length (0x2D3).
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "app/app.h"

namespace savedopts {
namespace fs = std::filesystem;

bool NewestOptions(std::vector<uint8_t>& out, std::string& which) {
    fs::path dir = app::ExeDir() / "hdd" / "E" / "UDATA" / "45410056";
    std::error_code ec;
    fs::file_time_type best{};
    bool found = false;
    for (auto& e : fs::directory_iterator(dir, ec)) {
        std::ifstream meta(e.path() / "SaveMeta.xbx", std::ios::binary);
        std::string m((std::istreambuf_iterator<char>(meta)), {});
        std::string ascii;  // (the name is UTF-16)
        for (size_t i = 0; i < m.size(); i += 2) ascii += m[i];
        if (ascii.find("(Options)") == std::string::npos) continue;
        std::error_code tec;
        auto t = fs::last_write_time(e.path() / "data.dat", tec);
        if (tec || (found && t <= best)) continue;
        std::ifstream f(e.path() / "data.dat", std::ios::binary);
        std::vector<uint8_t> d((std::istreambuf_iterator<char>(f)), {});
        if (d.size() != 0x108 + 0x400) continue;
        const uint8_t* p = d.data() + 0x108;
        static const uint8_t kMarker[4] = {0x0D, 0xF0, 0xEF, 0xBE};
        uint32_t length;
        std::memcpy(&length, p + 0x2D3, 4);
        if (std::memcmp(p + 0x2C0, kMarker, 4) != 0 || std::memcmp(p + 0x2CF, kMarker, 4) != 0 || length != 0x2D3)
            continue;  // (not as this game writes them)
        out.assign(p, p + 0x400);
        which = e.path().filename().string();
        best = t;
        found = true;
    }
    return found;
}

}  // namespace savedopts
