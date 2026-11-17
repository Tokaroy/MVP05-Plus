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
}  // namespace

void Apply() {
    std::vector<Edit> edits;
    // (none at present: depth of field, its one edit, was taken out in Beta 2.5. The copy an earlier version
    // left is still cleared below)
    std::error_code rm;
    fs::remove(app::ExeDir() / "tweaks" / "data" / "datafile" / "datafile.big", rm);  // last time's, if any
    if (edits.empty()) return;
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
        changed = EditText(text, edits);
        bigfile::SetText(en, text);
    }
    if (!changed) {
        LOGR("tuning: none of the %zu tuning changes found in datafile.txt", edits.size());
        return;
    }
    bigfile::Write(bigfile::TweaksDir({"data", "datafile"}) / "datafile.big", big);
    bigfile::UseTweaks();
    LOGR("tuning: %d tuning value%s changed (datafile.big in tweaks)", changed, changed == 1 ? "" : "s");
}

}  // namespace tuning
