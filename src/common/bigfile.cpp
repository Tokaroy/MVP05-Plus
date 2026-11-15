// See bigfile.h.
#include "bigfile.h"

#include <algorithm>
#include <cctype>
#include <cstring>
#include <fstream>
#include <mutex>

#include "app/app.h"
#include "kernel/kernel.h"

namespace bigfile {
namespace fs = std::filesystem;
namespace {
uint32_t Be32(const uint8_t* p) { return uint32_t(p[0]) << 24 | uint32_t(p[1]) << 16 | uint32_t(p[2]) << 8 | p[3]; }
void PutBe32(std::vector<uint8_t>& o, uint32_t v) {
    for (int s = 24; s >= 0; s -= 8) o.push_back(uint8_t(v >> s));
}
std::string Lower(std::string s) {
    for (auto& c : s) c = char(std::tolower(static_cast<unsigned char>(c)));
    return s;
}
}  // namespace

// EA's RefPack
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

// RefPack: greedy matches from hash chains (up to 128 KB back), so the file stays about the size of EA's

std::vector<uint8_t> Pack(const std::vector<uint8_t>& in) {
    const size_t n = in.size();
    std::vector<uint8_t> o = {0x10, 0xFB, uint8_t(n >> 16), uint8_t(n >> 8), uint8_t(n)};
    o.reserve(n / 2 + 16);
    constexpr size_t kWindow = 131072, kHashSize = 1 << 16;
    constexpr int kDepth = 32;
    std::vector<int32_t> head(kHashSize, -1), prev(n, -1);
    auto hash = [&](size_t i) { return ((in[i] << 10) ^ (in[i + 1] << 5) ^ in[i + 2]) & (kHashSize - 1); };
    auto insert = [&](size_t i) {
        if (i + 2 >= n) return;
        size_t h = hash(i);
        prev[i] = head[h];
        head[h] = int32_t(i);
    };
    size_t lit = 0, i = 0;  // literals waiting from lit up to i
    auto flush_literals = [&](size_t keep) {  // all but `keep` (0..3) of them, in blocks of 4..112
        while (i - lit - keep >= 4) {
            size_t k = std::min<size_t>(112, (i - lit - keep) & ~size_t(3));
            o.push_back(uint8_t(0xE0 | (k / 4 - 1)));
            o.insert(o.end(), in.begin() + lit, in.begin() + lit + k);
            lit += k;
        }
    };
    while (i < n) {
        size_t best_len = 0, best_off = 0;
        if (i + 2 < n) {
            int32_t c = head[hash(i)];
            for (int d = 0; c >= 0 && d < kDepth; d++, c = prev[c]) {
                size_t off = i - size_t(c);
                if (off > kWindow) break;
                size_t l = 0, maxl = std::min<size_t>(1028, n - i);
                while (l < maxl && in[c + l] == in[i + l]) l++;
                bool ok = (l >= 3 && off <= 1024) || (l >= 4 && off <= 16384) || l >= 5;
                if (ok && l > best_len) {
                    best_len = l;
                    best_off = off;
                    if (l == maxl) break;
                }
            }
        }
        if (!best_len) {
            insert(i);
            i++;
            continue;
        }
        size_t len = best_len, off = best_off;
        flush_literals((i - lit) & 3);
        size_t l = i - lit;  // 0..3 literals carried by the command
        size_t f = off - 1;
        if (len <= 10 && off <= 1024) {
            o.push_back(uint8_t(((f >> 3) & 0x60) | ((len - 3) << 2) | l));
            o.push_back(uint8_t(f));
        } else if (len <= 67 && off <= 16384) {
            o.push_back(uint8_t(0x80 | (len - 4)));
            o.push_back(uint8_t((l << 6) | (f >> 8)));
            o.push_back(uint8_t(f));
        } else {
            o.push_back(uint8_t(0xC0 | ((f >> 16) & 1) << 4 | ((len - 5) >> 8) << 2 | l));
            o.push_back(uint8_t(f >> 8));
            o.push_back(uint8_t(f));
            o.push_back(uint8_t(len - 5));
        }
        o.insert(o.end(), in.begin() + lit, in.begin() + i);
        for (size_t k = 0; k < len; k++) insert(i + k);
        i += len;
        lit = i;
    }
    flush_literals((i - lit) & 3);
    o.push_back(uint8_t(0xFC | (i - lit)));
    o.insert(o.end(), in.begin() + lit, in.begin() + i);
    return o;
}



bool Read(const fs::path& path, Archive& out) {
    std::ifstream f(path, std::ios::binary);
    std::vector<uint8_t> d((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    if (d.size() < 16 || std::memcmp(d.data(), "BIGF", 4) != 0) return false;
    out = {};
    uint32_t count = Be32(&d[8]);
    size_t p = 16;
    for (uint32_t i = 0; i < count && p + 8 < d.size(); i++) {
        uint32_t off = Be32(&d[p]), size = Be32(&d[p + 4]);
        size_t e = p + 8;
        while (e < d.size() && d[e]) e++;
        Entry en{std::string(reinterpret_cast<const char*>(&d[p + 8]), e - p - 8), {}};
        p = e + 1;
        if (size_t(off) + size > d.size()) return false;
        en.data.assign(d.begin() + off, d.begin() + off + size);
        out.entries.push_back(std::move(en));
    }
    out.tail.assign(d.begin() + std::min(p, d.size()), d.begin() + std::min(d.size(), p + 8));
    return true;
}

bool Write(const fs::path& path, const Archive& a) {
    size_t header = 16;
    for (auto& en : a.entries) header += 8 + en.name.size() + 1;
    header += a.tail.size();
    size_t first = (header + 3) & ~size_t(3);
    std::vector<uint8_t> o = {'B', 'I', 'G', 'F', 0, 0, 0, 0};
    PutBe32(o, uint32_t(a.entries.size()));
    PutBe32(o, uint32_t(header));
    size_t at = first;
    for (auto& en : a.entries) {
        PutBe32(o, uint32_t(at));
        PutBe32(o, uint32_t(en.data.size()));
        o.insert(o.end(), en.name.begin(), en.name.end());
        o.push_back(0);
        at += en.data.size();
    }
    o.insert(o.end(), a.tail.begin(), a.tail.end());
    o.resize(first, 0);
    for (auto& en : a.entries) o.insert(o.end(), en.data.begin(), en.data.end());
    uint32_t total = uint32_t(o.size());
    std::memcpy(&o[4], &total, 4);  // little endian, as EA's
    std::ofstream f(path, std::ios::binary);
    f.write(reinterpret_cast<const char*>(o.data()), std::streamsize(o.size()));
    return bool(f);
}

bool Text(const Entry& e, std::string& out) {
    if (e.data.size() > 1 && e.data[1] == 0xFB) {
        std::vector<uint8_t> raw;
        if (!Unpack(e.data.data(), e.data.size(), raw)) return false;
        out.assign(raw.begin(), raw.end());
    } else {
        out.assign(e.data.begin(), e.data.end());
    }
    return true;
}

void SetText(Entry& e, const std::string& text) {
    bool packed = e.data.size() > 1 && e.data[1] == 0xFB;
    std::vector<uint8_t> raw(text.begin(), text.end());
    e.data = packed ? Pack(raw) : raw;
}

fs::path FindAsset(std::initializer_list<const char*> parts) {
    std::error_code ec;
    fs::path dir = app::ExeDir() / "assets";
    for (const char* part : parts) {
        fs::path next;
        for (auto it = fs::directory_iterator(dir, ec); !ec && it != fs::directory_iterator(); it.increment(ec))
            if (Lower(it->path().filename().string()) == Lower(part)) {
                next = it->path();
                break;
            }
        if (next.empty()) return {};
        dir = next;
    }
    return dir;
}

fs::path TweaksDir(std::initializer_list<const char*> parts) {
    fs::path dir = app::ExeDir() / "tweaks";
    for (const char* part : parts) dir /= part;
    std::error_code ec;
    fs::create_directories(dir, ec);
    return dir;
}

void UseTweaks() {
    static std::once_flag once;
    std::call_once(once, [] { kernel::SetDiscOverlay(app::ExeDir() / "tweaks"); });
}

}  // namespace bigfile
