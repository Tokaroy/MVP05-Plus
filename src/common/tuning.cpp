// See tuning.h.
#include "tuning.h"

#include <cctype>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>
#include <vector>

#include "app/app.h"
#include "core/log.h"
#include "kernel/kernel.h"
#include "bigfile.h"
#include "tools_overlay.h"

namespace tuning {
namespace {
namespace fs = std::filesystem;

struct Edit {
    const char* record;  // e.g. "xbox_render"
    const char* field;   // e.g. "IsActive"
    const char* value;
};

std::string Lower(std::string s) {
    for (auto& c : s) c = char(std::tolower(static_cast<unsigned char>(c)));
    return s;
}


// the edits applied to datafile.txt's lines; the count of fields changed
int EditText(std::string& text, const std::vector<Edit>& edits) {
    int done = 0;
    std::map<std::string, std::string> names;  // the fields of the records that follow: name -> index
    size_t pos = 0;
    std::string out;
    out.reserve(text.size() + 64);
    while (pos < text.size()) {
        size_t end = text.find('\n', pos);
        if (end == std::string::npos) end = text.size();
        std::string line = text.substr(pos, end - pos);
        pos = end + (end < text.size());
        size_t lt = line.find('<'), sc = line.find(';');
        if (sc != std::string::npos && (lt == std::string::npos || lt > sc)) {  // a field-names line
            names.clear();
            size_t a = sc + 1;
            while (a < line.size()) {
                size_t b = line.find(';', a);
                if (b == std::string::npos) break;
                std::string item = line.substr(a, b - a);
                size_t sp = item.find(' ');
                if (sp != std::string::npos) names[item.substr(sp + 1)] = item.substr(0, sp);
                a = b + 1;
            }
        } else if (lt != std::string::npos) {  // a record
            size_t gt = line.find('>', lt);
            std::string rec = gt == std::string::npos ? "" : line.substr(lt + 1, gt - lt - 1);
            for (const Edit& e : edits) {
                if (rec != e.record) continue;
                auto it = names.find(e.field);
                if (it == names.end()) continue;
                std::string key = ";" + it->second + " ";
                size_t f = line.find(key, gt);
                if (f == std::string::npos) continue;
                size_t v = f + key.size(), ve = line.find(';', v);
                if (ve == std::string::npos) continue;
                line = line.substr(0, v) + e.value + line.substr(ve);
                done++;
            }
        }
        out += line;
        if (pos <= text.size() && end < text.size()) out += '\n';
    }
    text.swap(out);
    return done;
}
// A datafile text's records of one kind, each as field name -> value (the names from the field-names line before it).
using Fields = std::map<std::string, std::string>;
std::map<std::string, std::string> FieldNames(const std::string& line, size_t sc) {
    std::map<std::string, std::string> names;  // index -> name
    size_t a = sc + 1;
    while (a < line.size()) {
        size_t b = line.find(';', a);
        if (b == std::string::npos) break;
        std::string item = line.substr(a, b - a);
        size_t sp = item.find(' ');
        if (sp != std::string::npos) names[item.substr(0, sp)] = item.substr(sp + 1);
        a = b + 1;
    }
    return names;
}
bool FindRecord(const std::string& text, const std::string& rec, Fields& out) {
    std::map<std::string, std::string> names;
    size_t pos = 0;
    while (pos < text.size()) {
        size_t end = text.find('\n', pos);
        if (end == std::string::npos) end = text.size();
        std::string line = text.substr(pos, end - pos);
        pos = end + 1;
        if (!line.empty() && line.back() == '\r') line.pop_back();
        size_t lt = line.find('<'), sc = line.find(';');
        if (sc == std::string::npos) continue;
        if (lt == std::string::npos || lt > sc) {
            names = FieldNames(line, sc);
            continue;
        }
        size_t gt = line.find('>', lt);
        if (gt == std::string::npos || line.substr(lt + 1, gt - lt - 1) != rec) continue;
        size_t a = gt + 2;
        while (a < line.size()) {
            size_t b = line.find(';', a);
            if (b == std::string::npos) b = line.size();
            std::string item = line.substr(a, b - a);
            size_t sp = item.find(' ');
            std::string idx = sp == std::string::npos ? item : item.substr(0, sp);
            auto it = names.find(idx);
            if (it != names.end()) out[it->second] = sp == std::string::npos ? "" : item.substr(sp + 1);
            a = b + 1;
        }
        return true;
    }
    return false;
}
// rec's values in text replaced, field by field (by name), with from's; the count changed
int SetRecord(std::string& text, const std::string& rec, const Fields& from) {
    std::map<std::string, std::string> names;
    size_t pos = 0;
    while (pos < text.size()) {
        size_t start = pos, end = text.find('\n', pos);
        if (end == std::string::npos) end = text.size();
        std::string line = text.substr(start, end - start);
        pos = end + 1;
        bool cr = !line.empty() && line.back() == '\r';
        if (cr) line.pop_back();
        size_t lt = line.find('<'), sc = line.find(';');
        if (sc == std::string::npos) continue;
        if (lt == std::string::npos || lt > sc) {
            names = FieldNames(line, sc);
            continue;
        }
        size_t gt = line.find('>', lt);
        if (gt == std::string::npos || line.substr(lt + 1, gt - lt - 1) != rec) continue;
        std::string out = line.substr(0, gt + 2);
        int changed = 0;
        size_t a = gt + 2;
        while (a < line.size()) {
            size_t b = line.find(';', a);
            if (b == std::string::npos) b = line.size();
            std::string item = line.substr(a, b - a);
            size_t sp = item.find(' ');
            std::string idx = sp == std::string::npos ? item : item.substr(0, sp);
            std::string value = sp == std::string::npos ? "" : item.substr(sp + 1);
            auto n = names.find(idx);
            if (n != names.end()) {
                auto v = from.find(n->second);
                if (v != from.end() && v->second != value) value = v->second, changed++;
            }
            out += idx + " " + value + ";";
            a = b + 1;
        }
        if (!changed) return 0;
        if (cr) out += '\r';
        text = text.substr(0, start) + out + text.substr(end);
        return changed;
    }
    return 0;
}

// The console lighting (console_lighting): the GameCube's or the PS2's light sets (their datafile.big's "gclighting" or
// "ps2lighting" records, kept by the Launcher in gamecube/ or ps2/datafile.big from that disc) in place of the Xbox's
// ("xboxlighting"), field by field by name (the files number their fields differently). The GameCube's differ in 7
// of the 22 sets: no second key light (Light2, and the dugouts') at 02dusk and 04day parks, a few angles, and a grey
// haze where the Xbox's default sets are blue and purple. The PS2's differ in most: dimmer key and dugout lights,
// fewer dugout lights, other angles, bounce light and lighter shadows. The fields only the Xbox has stay as they are.
int ConsoleLighting(bigfile::Archive& big, uint32_t which) {
    const char* folder = which == 1 ? "gamecube" : "ps2";
    const char* console = which == 1 ? "GameCube" : "PS2";
    const char* record = which == 1 ? "gclighting" : "ps2lighting";
    fs::path gcp = app::ExeDir() / folder / "datafile.big";
    bigfile::Archive gc;
    std::error_code ec;
    if (!fs::exists(gcp, ec)) {
        LOGR("graphics: the %s lighting needs %s/datafile.big (the Launcher keeps it when it reads the %s disc for "
             "the button art); the Xbox lighting stays", console, folder, console);
        return 0;
    }
    if (!bigfile::Read(gcp, gc)) return 0;
    std::map<std::string, const bigfile::Entry*> theirs;
    for (auto& e : gc.entries) theirs[Lower(e.name)] = &e;
    int changed = 0, sets = 0;
    for (auto& en : big.entries) {
        auto it = theirs.find(Lower(en.name));
        if (it == theirs.end()) continue;
        std::string mine, other;
        if (!bigfile::Text(en, mine) || !bigfile::Text(*it->second, other)) continue;
        Fields light;
        if (!FindRecord(other, record, light)) continue;
        int n = SetRecord(mine, "xboxlighting", light);
        if (!n) continue;
        bigfile::SetText(en, mine);
        changed += n;
        sets++;
    }
    LOGR("graphics: the %s lighting in %d light set%s (%d value%s)", console, sets, sets == 1 ? "" : "s", changed,
         changed == 1 ? "" : "s");
    return changed;
}
}  // namespace

void Apply() {
    std::vector<Edit> edits;
    // (none at present: depth of field, its one edit, was taken out in Beta 2.5. The copy an earlier version
    // left is still cleared below)
    std::error_code rm;
    fs::remove(app::ExeDir() / "tweaks" / "data" / "datafile" / "datafile.big", rm);  // last time's, if any
    if (edits.empty() && tools::g_console_lighting != 1 && tools::g_console_lighting != 2) return;
    fs::path src = bigfile::FindAsset({"data", "datafile", "datafile.big"});
    bigfile::Archive big;
    if (src.empty() || !bigfile::Read(src, big)) {
        LOGR("tuning: no assets/data/datafile/datafile.big; the tuning tweaks are off");
        return;
    }
    int changed = 0;
    for (auto& en : big.entries) {
        if (Lower(en.name) != "datafile.txt") continue;
        std::string text;
        if (!bigfile::Text(en, text)) {
            LOGR("tuning: couldn't unpack datafile.txt; the tuning tweaks are off");
            return;
        }
        if (!edits.empty()) {
            changed = EditText(text, edits);
            bigfile::SetText(en, text);
        }
    }
    if (tools::g_console_lighting == 1 || tools::g_console_lighting == 2)
        changed += ConsoleLighting(big, tools::g_console_lighting);
    if (!changed) {
        if (!edits.empty()) LOGR("tuning: none of the %zu tuning changes found in datafile.txt", edits.size());
        return;
    }
    bigfile::Write(bigfile::TweaksDir({"data", "datafile"}) / "datafile.big", big);
    bigfile::UseTweaks();
    LOGR("tuning: %d tuning value%s changed (datafile.big in tweaks)", changed, changed == 1 ? "" : "s");
}

}  // namespace tuning
