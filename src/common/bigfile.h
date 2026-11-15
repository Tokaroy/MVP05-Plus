#pragma once
// EA BIG archives (BIGF) and RefPack, for the Game Tweaks that put changed copies of the game's data files in the
// "tweaks" overlay folder beside the exe (tuning.cpp, dynasty_data.cpp, day_parks.cpp).
#include <cstdint>
#include <filesystem>
#include <initializer_list>
#include <string>
#include <vector>

namespace bigfile {

struct Entry {
    std::string name;
    std::vector<uint8_t> data;  // as stored (RefPack'd or not)
};
struct Archive {
    std::vector<Entry> entries;
    std::vector<uint8_t> tail;  // EA's "L234" and 4 bytes after the entries
};
bool Read(const std::filesystem::path& path, Archive& out);
bool Write(const std::filesystem::path& path, const Archive& a);
bool Unpack(const uint8_t* d, size_t n, std::vector<uint8_t>& out);
std::vector<uint8_t> Pack(const std::vector<uint8_t>& in);
// an entry's text (unpacked if it was); false if it can't be read
bool Text(const Entry& e, std::string& out);
// the entry given new text, packed as it was
void SetText(Entry& e, const std::string& text);
// a file under the game's assets folder, whatever the case of its names; empty if missing
std::filesystem::path FindAsset(std::initializer_list<const char*> parts);
// the "tweaks" overlay folder's copy of an asset path (made), e.g. {"data","database"}
std::filesystem::path TweaksDir(std::initializer_list<const char*> parts);
// put the tweaks folder in front of the game's files (once)
void UseTweaks();

}  // namespace bigfile
