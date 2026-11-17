// See dynasty_data.h.
#include "dynasty_data.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <sstream>
#include <string>
#include <vector>

#include "app/app.h"
#include "bigfile.h"
#include "core/log.h"
#include "tools_overlay.h"

namespace dynastydata {
namespace {
namespace fs = std::filesystem;

std::string Lower(std::string s) {
    for (auto& c : s) c = char(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

std::string Num(double v) {
    char b[32];
    std::snprintf(b, sizeof b, "%.6g", v);
    return b;
}

// each data row (first field a number) given to edit as fields; the rest kept as it was
std::string EachRow(const std::string& text, const std::function<void(std::vector<std::string>&)>& edit) {
    std::string out;
    size_t pos = 0;
    while (pos < text.size()) {
        size_t end = text.find('\n', pos);
        bool nl = end != std::string::npos;
        std::string line = text.substr(pos, (nl ? end : text.size()) - pos);
        pos = nl ? end + 1 : text.size();
        bool cr = !line.empty() && line.back() == '\r';
        if (cr) line.pop_back();
        std::vector<std::string> f;
        size_t a = 0;
        while (true) {
            size_t b = line.find(',', a);
            f.push_back(line.substr(a, b == std::string::npos ? std::string::npos : b - a));
            if (b == std::string::npos) break;
            a = b + 1;
        }
        if (!f.empty() && !f[0].empty() && std::isdigit(static_cast<unsigned char>(f[0][0]))) {
            edit(f);
            line.clear();
            for (size_t i = 0; i < f.size(); i++) line += (i ? "," : "") + f[i];
        }
        out += line + (cr ? "\r" : "") + (nl ? "\n" : "");
    }
    return out;
}

double D(const std::string& s) { return std::atof(s.c_str()); }

// progbadj/progpadj: Age,Star,Up,Down,Same
std::string Development(const std::string& t, double up_x, double down_x) {
    return EachRow(t, [&](std::vector<std::string>& f) {
        if (f.size() < 5) return;
        double up = D(f[2]) * up_x, down = D(f[3]) * down_x;
        if (up + down > 1) {
            double k = 1 / (up + down);
            up *= k;
            down *= k;
        }
        f[2] = Num(up);
        f[3] = Num(down);
        f[4] = Num(std::max(0.0, 1 - up - down));
    });
}

// resign.csv: Age,Star Level,Chance of re-signing (percent)
std::string Resign(const std::string& t, int delta) {
    return EachRow(t, [&](std::vector<std::string>& f) {
        if (f.size() < 3) return;
        int c = std::atoi(f[2].c_str());
        if (c > 0) f[2] = std::to_string(std::clamp(c + delta, 1, 99));
    });
}

// retire.csv: Age,SL1..SL5 (percent a year); 45, where everyone retires, kept
std::string Retire(const std::string& t, double x) {
    return EachRow(t, [&](std::vector<std::string>& f) {
        if (std::atoi(f[0].c_str()) >= 45) return;
        for (size_t i = 1; i < f.size(); i++)
            if (!f[i].empty()) f[i] = std::to_string(std::clamp(int(std::atoi(f[i].c_str()) * x + 0.5), 0, 100));
    });
}

// star.csv: position,distro,1..5 (the share of rookies at each star level)
std::string Rookies(const std::string& t, int level) {
    // 1 better, 2 much better, 3 weaker (the game's own: 52% 1-stars, 4% 5-stars)
    static const double kBetter[3][5] = {{0.40, 0.26, 0.16, 0.11, 0.07}, {0.30, 0.25, 0.20, 0.15, 0.10},
                                         {0.62, 0.20, 0.10, 0.06, 0.02}};
    std::string out;
    bool header = true;
    std::istringstream in(t);
    std::string line;
    while (std::getline(in, line)) {
        bool cr = !line.empty() && line.back() == '\r';
        if (cr) line.pop_back();
        if (!header && !line.empty()) {
            std::vector<std::string> f;
            std::stringstream ls(line);
            std::string x;
            while (std::getline(ls, x, ',')) f.push_back(x);
            if (f.size() >= 7) {
                for (int i = 0; i < 5; i++) f[2 + i] = Num(kBetter[level - 1][i]);
                line.clear();
                for (size_t i = 0; i < f.size(); i++) line += (i ? "," : "") + f[i];
            }
        }
        header = false;
        out += line + (cr ? "\r\n" : "\n");
    }
    return out;
}

// a BIG in data/database: each named entry given new text by its edit; written to tweaks if any changed
bool EditBig(const char* big_name, const std::vector<std::pair<std::string, std::function<std::string(const std::string&)>>>& edits,
             std::string& done) {
    fs::path src = bigfile::FindAsset({"data", "database", big_name});
    bigfile::Archive big;
    if (src.empty() || !bigfile::Read(src, big)) {
        LOGR("dynasty tweaks: no assets/data/database/%s", big_name);
        return false;
    }
    bool any = false;
    for (auto& en : big.entries)
        for (auto& [name, edit] : edits) {
            if (Lower(en.name) != name) continue;
            std::string text;
            if (!bigfile::Text(en, text)) continue;
            bigfile::SetText(en, edit(text));
            done += (done.empty() ? "" : ", ") + name;
            any = true;
        }
    if (any) bigfile::Write(bigfile::TweaksDir({"data", "database"}) / big_name, big);
    return any;
}
}  // namespace

void Apply() {
    std::error_code rm;
    for (const char* n : {"progress.big", "rookie.big", "resign.csv"})  // last time's, if any
        fs::remove(app::ExeDir() / "tweaks" / "data" / "database" / n, rm);
    const double up = tools::g_dev_speed / 100.0, down = tools::g_aging / 100.0,
                 retire = tools::g_retirement / 100.0;
    const int resign = int(tools::g_resign_chance) - 100;
    std::string done;
    bool any = false;
    {
        std::vector<std::pair<std::string, std::function<std::string(const std::string&)>>> edits;
        if (up != 1 || down != 1)
            for (const char* n : {"progbadj.csv", "progpadj.csv"})
                edits.push_back({n, [=](const std::string& t) { return Development(t, up, down); }});
        if (!edits.empty()) any |= EditBig("progress.big", edits, done);
    }
    {
        std::vector<std::pair<std::string, std::function<std::string(const std::string&)>>> edits;
        if (retire != 1) edits.push_back({"retire.csv", [=](const std::string& t) { return Retire(t, retire); }});
        int q = int(tools::g_rookie_quality);
        if (q >= 1 && q <= 3) edits.push_back({"star.csv", [=](const std::string& t) { return Rookies(t, q); }});
        if (!edits.empty()) any |= EditBig("rookie.big", edits, done);
    }
    if (resign) {
        fs::path src = bigfile::FindAsset({"data", "database", "resign.csv"});
        if (!src.empty()) {
            std::ifstream f(src, std::ios::binary);
            std::string t((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
            std::ofstream(bigfile::TweaksDir({"data", "database"}) / "resign.csv", std::ios::binary) << Resign(t, resign);
            done += std::string(done.empty() ? "" : ", ") + "resign.csv";
            any = true;
        }
    }
    if (any) {
        bigfile::UseTweaks();
        LOGR("dynasty tweaks: %s (in tweaks)", done.c_str());
    }
}

}  // namespace dynastydata
