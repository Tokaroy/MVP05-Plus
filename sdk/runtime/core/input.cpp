// controllers through SDL (Xbox, PlayStation and Switch pads) and the GameCube adapter, read into the console
// controller's report
#ifndef XBE_UWP  // the Xbox (UWP) build has its own: uwp_main.cpp, input_uwp.cpp
#include "core/input.h"

#include <algorithm>
#include <utility>
#include <vector>
#include <cctype>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <iterator>
#include <string>
#include <mutex>

#include <SDL3/SDL.h>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

#include "app/app.h"
#include "core/gc_adapter.h"
#include "core/log.h"

namespace input {

namespace {

// a controller takes the lowest free port when it is plugged in and keeps it until it is unplugged
std::mutex g_lock;
bool g_sdl = false;
SDL_Gamepad* g_pads[4] = {};
int g_gc[4] = {-1, -1, -1, -1};  // the GameCube adapter port on each controller port, -1 none

bool Free(int port) { return !g_pads[port] && g_gc[port] < 0; }
int FirstFree() {
    for (int i = 0; i < 4; i++)
        if (Free(i)) return i;
    return -1;
}

void AddPad(SDL_JoystickID id) {
    for (SDL_Gamepad* pad : g_pads)
        if (pad && SDL_GetGamepadID(pad) == id) return;
    int port = FirstFree();
    if (port < 0) return;
    SDL_Gamepad** slot = &g_pads[port];
    *slot = SDL_OpenGamepad(id);
    const char* name = *slot ? SDL_GetGamepadName(*slot) : SDL_GetError();
    LOGR("input: controller %d %s: %s", int(slot - g_pads) + 1, *slot ? "plugged in" : "failed to open", name ? name : "");
    if (!*slot) return;
    // the pad's player lights (DualShock 3 LEDs, DualSense player lights, DualShock 4 light bar colour) show its port
    SDL_SetGamepadPlayerIndex(*slot, port);
    char guid[64] = {};
    SDL_GUIDToString(SDL_GetGamepadGUIDForID(id), guid, sizeof(guid));
    SDL_Joystick* joy = SDL_GetGamepadJoystick(*slot);
    LOGR("input: controller %d type %s, %d axes, guid %s", port + 1,
         SDL_GetGamepadStringForType(SDL_GetGamepadType(*slot)), joy ? SDL_GetNumJoystickAxes(joy) : 0, guid);
}

// a controller SDL sees but has no button map for: not used (gamecontrollerdb.txt beside the exe can map it)
void LogUnmapped(SDL_JoystickID id) {
    if (SDL_IsGamepad(id)) return;
    char guid[64] = {};
    SDL_GUIDToString(SDL_GetJoystickGUIDForID(id), guid, sizeof(guid));
    const char* name = SDL_GetJoystickNameForID(id);
    LOGR("input: %s (guid %s) has no button map, not used; a line for it in gamecontrollerdb.txt beside the exe maps it",
         name ? name : "a controller", guid);
}

void RemovePad(SDL_JoystickID id) {
    for (int i = 0; i < 4; i++) {
        if (!g_pads[i] || SDL_GetGamepadID(g_pads[i]) != id) continue;
        SDL_CloseGamepad(g_pads[i]);
        g_pads[i] = nullptr;
        LOGI("input: controller %d unplugged", i + 1);
    }
}

// a controller plugged in while all four ports were taken got none: it takes one when a port comes free (AddPad
// passes over the ones already open)
void AddWaiting() {
    if (!g_sdl || FirstFree() < 0) return;
    int count = 0;
    if (SDL_JoystickID* ids = SDL_GetGamepads(&count)) {
        for (int i = 0; i < count; i++) AddPad(ids[i]);
        SDL_free(ids);
    }
}

// GameCube controllers come and go with the adapter's own ports
void AddWaiting();
bool UpdateGameCube() {  // true when a port came free
    bool freed = false;
    GameCube gc;
    for (int slot = 0; slot < 4; slot++) {
        bool on = gcadapter::Read(slot, gc);
        int port = int(std::find(std::begin(g_gc), std::end(g_gc), slot) - std::begin(g_gc));
        if (on && port == 4) {
            port = FirstFree();
            if (port < 0) continue;
            g_gc[port] = slot;
            LOGR("input: controller %d plugged in: GameCube controller (adapter port %d)", port + 1, slot + 1);
        } else if (!on && port < 4) {
            g_gc[port] = -1;
            LOGR("input: controller %d unplugged: GameCube controller (adapter port %d)", port + 1, slot + 1);
            freed = true;
        }
    }
    return freed;
}

// once a millisecond at most, however many ports and threads read
void UpdatePads() {
    static uint64_t last = 0;
    uint64_t now = uint64_t(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
    if (now == last) return;
    last = now;
    bool freed = UpdateGameCube();
    if (!g_sdl) return;
    SDL_PumpEvents();
    SDL_Event e;
    while (SDL_PeepEvents(&e, 1, SDL_GETEVENT, SDL_EVENT_FIRST, SDL_EVENT_LAST) == 1) {
        if (e.type == SDL_EVENT_GAMEPAD_ADDED) AddPad(e.gdevice.which);
        else if (e.type == SDL_EVENT_JOYSTICK_ADDED) LogUnmapped(e.jdevice.which);
        else if (e.type == SDL_EVENT_GAMEPAD_REMOVED) RemovePad(e.gdevice.which), freed = true;
    }
    if (freed) AddWaiting();
}

// Windows counts only the keyboard and mouse as activity, so with a controller alone the screen blanks and the PC
// may sleep mid-game. A controller in use restarts the idle countdown the way a mouse move does (no lasting
// request): put the controller down and the screen still turns off after the usual time. Stick and trigger
// changes under a small margin don't count, so a resting stick's jitter doesn't keep the screen on.
void NoteActivity(int port, const Pad& p) {
#ifdef _WIN32
    struct Seen {
        uint16_t buttons = 0;
        uint8_t analog[8] = {};
        int16_t lx = 0, ly = 0, rx = 0, ry = 0;
    };
    static Seen seen[4];
    static uint64_t last_reset = 0;
    if (port < 0 || port >= 4 || !p.connected) return;
    Seen& s = seen[port];
    constexpr int kStick = 3000, kAnalog = 24;  // about 9% of a stick's travel, 9% of a trigger's
    bool moved = p.buttons != s.buttons;
    for (int i = 0; i < 8; i++) moved |= std::abs(int(p.analog[i]) - int(s.analog[i])) > kAnalog;
    moved |= std::abs(p.lx - s.lx) > kStick || std::abs(p.ly - s.ly) > kStick || std::abs(p.rx - s.rx) > kStick ||
             std::abs(p.ry - s.ry) > kStick;
    if (!moved) return;
    s.buttons = p.buttons;
    std::copy(std::begin(p.analog), std::end(p.analog), std::begin(s.analog));
    s.lx = p.lx, s.ly = p.ly, s.rx = p.rx, s.ry = p.ry;
    uint64_t now = GetTickCount64();
    if (now - last_reset < 5000) return;  // the idle timeout is minutes: every 5 seconds at most is plenty
    last_reset = now;
    SetThreadExecutionState(ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED);
#else
    (void)port, (void)p;
#endif
}

}  // namespace

void Init() {
    // WGI reads the triggers apart and HIDAPI takes PlayStation and Switch pads. Reads come from the guest's threads,
    // so SDL's own thread takes the device notices.
    SDL_SetHint(SDL_HINT_JOYSTICK_THREAD, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_WGI, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_RAWINPUT, "0");
    SDL_SetHint(SDL_HINT_XINPUT_ENABLED, "1");
    SDL_SetHint(SDL_HINT_JOYSTICK_DIRECTINPUT, "0");
    // the GameCube adapter is read by gc_adapter.cpp: SDL would want libusb for it, and both reading it would make
    // each controller appear twice
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_GAMECUBE, "0");
    // DualShock 3s through SDL's own PS3 driver, which reads their pressure-sensitive buttons (off by default on
    // Windows: with Sony's driver the pad needs DsHidMini in its SDL mode). PS3-style third-party pads and PS2
    // adapters are read by SDL either way.
    SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI_PS3, "1");
    gcadapter::Start();
    if (!SDL_Init(SDL_INIT_GAMEPAD)) {
        LOGE("input: SDL failed to start, no controllers: %s", SDL_GetError());
        return;
    }
    int v = SDL_GetVersion();
    LOGI("input: SDL %d.%d.%d", SDL_VERSIONNUM_MAJOR(v), SDL_VERSIONNUM_MINOR(v), SDL_VERSIONNUM_MICRO(v));
    // community button maps (SDL's gamecontrollerdb.txt format) for controllers SDL doesn't know, such as some PS2
    // adapters
    std::error_code ec;
    auto db = app::ExeDir() / "gamecontrollerdb.txt";
    if (std::filesystem::is_regular_file(db, ec)) {
        auto u8 = db.u8string();
        std::string utf8(u8.begin(), u8.end());
        int added = SDL_AddGamepadMappingsFromFile(utf8.c_str());
        LOGR("input: gamecontrollerdb.txt: %d button maps added", added < 0 ? 0 : added);
    }
    std::lock_guard lock(g_lock);
    g_sdl = true;
    int count = 0;
    if (SDL_JoystickID* ids = SDL_GetGamepads(&count)) {
        for (int i = 0; i < count; i++) AddPad(ids[i]);
        SDL_free(ids);
    }
}

// The keyboard as controller 1 when the game starts with no controller plugged in. A controller plugged in takes
// over for the rest of the run (unplugging it again doesn't bring the keyboard back). Its keys count only while the
// game's window has the focus. Each control's keys come from [keyboard] in the settings
// file ("Enter, Space"; "none" for no key), the defaults below for any it doesn't name. Keys the window already uses
// (Esc, F3, F10 to F12, Alt+Enter, Alt+F4) are best left out; Enter with Alt held is the fullscreen switch, not A.
enum Control {
    kUp, kDown, kLeft, kRight, kStart, kBack, kLeftClick, kRightClick,  // the buttons' bits, in order
    kA, kB, kX, kY, kBlack, kWhite, kLeftTrigger, kRightTrigger,       // analog[0..7]
    kLeftUp, kLeftDown, kLeftLeft, kLeftRight, kRightUp, kRightDown, kRightLeft, kRightRight,
    kControls
};
struct ControlName {
    const char* name;
    const char* keys;  // the default
};
const ControlName kControlNames[kControls] = {
    {"dpad_up", "Up"}, {"dpad_down", "Down"}, {"dpad_left", "Left"}, {"dpad_right", "Right"},
    {"start", "Tab"}, {"back", "X"}, {"left_stick_click", "LeftShift"}, {"right_stick_click", "RightShift"},
    {"a", "Enter, Space"}, {"b", "Backspace"}, {"x", "Q"}, {"y", "E"}, {"black", "R"}, {"white", "F"},
    {"left_trigger", "Z"}, {"right_trigger", "C"},
    {"left_stick_up", "W"}, {"left_stick_down", "S"}, {"left_stick_left", "A"}, {"left_stick_right", "D"},
    {"right_stick_up", "I"}, {"right_stick_down", "K"}, {"right_stick_left", "J"}, {"right_stick_right", "L"},
};

// a key's name: a letter or digit, or one of these (any case, spaces and dashes ignored)
int KeyCode(std::string name) {
    std::string n;
    for (char c : name)
        if (c != ' ' && c != '-' && c != '_') n += char(std::tolower(static_cast<unsigned char>(c)));
    if (n.size() == 1 && std::isalnum(static_cast<unsigned char>(n[0]))) return std::toupper(static_cast<unsigned char>(n[0]));
    static const std::pair<const char*, int> kNames[] = {
        {"up", VK_UP}, {"down", VK_DOWN}, {"left", VK_LEFT}, {"right", VK_RIGHT}, {"enter", VK_RETURN},
        {"return", VK_RETURN}, {"space", VK_SPACE}, {"backspace", VK_BACK}, {"tab", VK_TAB},
        {"shift", VK_SHIFT}, {"leftshift", VK_LSHIFT}, {"rightshift", VK_RSHIFT}, {"ctrl", VK_CONTROL},
        {"control", VK_CONTROL}, {"leftctrl", VK_LCONTROL}, {"rightctrl", VK_RCONTROL}, {"capslock", VK_CAPITAL},
        {"insert", VK_INSERT}, {"delete", VK_DELETE}, {"home", VK_HOME}, {"end", VK_END}, {"pageup", VK_PRIOR},
        {"pagedown", VK_NEXT}, {"comma", VK_OEM_COMMA}, {"period", VK_OEM_PERIOD}, {"minus", VK_OEM_MINUS},
        {"equals", VK_OEM_PLUS}, {"semicolon", VK_OEM_1}, {"slash", VK_OEM_2}, {"backquote", VK_OEM_3},
        {"leftbracket", VK_OEM_4}, {"backslash", VK_OEM_5}, {"rightbracket", VK_OEM_6}, {"quote", VK_OEM_7},
        {"f1", VK_F1}, {"f2", VK_F2}, {"f4", VK_F4}, {"f5", VK_F5}, {"f6", VK_F6}, {"f7", VK_F7}, {"f8", VK_F8},
        {"f9", VK_F9}, {"numpadenter", VK_RETURN}, {"numpadplus", VK_ADD}, {"numpadminus", VK_SUBTRACT},
        {"numpadmultiply", VK_MULTIPLY}, {"numpaddivide", VK_DIVIDE}, {"numpadperiod", VK_DECIMAL},
    };
    for (const auto& [k, vk] : kNames)
        if (n == k) return vk;
    if (n.size() == 7 && n.compare(0, 6, "numpad") == 0 && std::isdigit(static_cast<unsigned char>(n[6])))
        return VK_NUMPAD0 + (n[6] - '0');
    return 0;
}

// each control's keys, from the settings (once)
const std::vector<int>* KeyboardLayout() {
    static std::vector<int> keys[kControls];
    static bool made = false;
    if (made) return keys;
    made = true;
    const auto& mine = app::Get().keyboard;
    for (int c = 0; c < kControls; c++) {
        std::string list = kControlNames[c].keys;
        for (const auto& [control, value] : mine)
            if (control == kControlNames[c].name) list = value;
        size_t at = 0;
        while (at <= list.size()) {
            size_t comma = std::min(list.find(',', at), list.size());
            std::string one = list.substr(at, comma - at);
            one.erase(0, one.find_first_not_of(' '));
            one.erase(one.find_last_not_of(' ') + 1);
            at = comma + 1;
            if (one.empty()) continue;
            std::string lower = one;
            for (char& ch : lower) ch = char(std::tolower(static_cast<unsigned char>(ch)));
            if (lower == "none") continue;
            if (int vk = KeyCode(one)) keys[c].push_back(vk);
            else LOGW("input: [keyboard] %s: no key called \"%s\", left out", kControlNames[c].name, one.c_str());
        }
    }
    for (const auto& [control, value] : mine) {
        bool known = false;
        for (const ControlName& n : kControlNames) known = known || control == n.name;
        if (!known) LOGW("input: [keyboard] %s isn't a control, left out", control.c_str());
    }
    return keys;
}

bool KeyboardPad(Pad& p) {
    static bool on = true, told = false;
    if (!on) return false;
    bool none = true;
    for (int i = 0; i < 4; i++) none = none && Free(i);
    if (!none) {
        on = false;
        if (told) LOGR("input: a controller is in: the keyboard isn't controller 1 any more");
        return false;
    }
    if (!told) {
        LOGR("input: no controller: the keyboard is controller 1");
        told = true;
    }
    p.connected = true;  // (plugged in while the window is in the background too, with nothing pressed)
    HWND window = static_cast<HWND>(app::Window());
    if (!window || GetForegroundWindow() != window) return true;
    const std::vector<int>* keys = KeyboardLayout();
    const bool alt = (GetAsyncKeyState(VK_MENU) & 0x8000) != 0;
    auto held = [&](int c) {
        for (int vk : keys[c])
            if ((GetAsyncKeyState(vk) & 0x8000) && !(vk == VK_RETURN && alt)) return true;
        return false;
    };
    for (int c = kUp; c <= kRightClick; c++) p.buttons |= uint16_t(held(c) << (c - kUp));
    for (int c = kA; c <= kRightTrigger; c++) p.analog[c - kA] = held(c) ? 0xFF : 0;
    auto axis = [&](int minus, int plus) { return int16_t(held(plus) ? 32767 : held(minus) ? -32768 : 0); };
    p.lx = axis(kLeftLeft, kLeftRight);
    p.ly = axis(kLeftDown, kLeftUp);  // (y up)
    p.rx = axis(kRightLeft, kRightRight);
    p.ry = axis(kRightDown, kRightUp);
    return true;
}

Pad Poll(int port) {
    Pad p;
    {
        std::lock_guard lock(g_lock);
        UpdatePads();
        if (SDL_Gamepad* pad = port >= 0 && port < 4 ? g_pads[port] : nullptr) {
            p.connected = true;
            SDL_GamepadType type = SDL_GetGamepadType(pad);
            p.playstation = type == SDL_GAMEPAD_TYPE_PS3 || type == SDL_GAMEPAD_TYPE_PS4 || type == SDL_GAMEPAD_TYPE_PS5;
            constexpr SDL_GamepadButton kButtons[] = {
                SDL_GAMEPAD_BUTTON_DPAD_UP,   SDL_GAMEPAD_BUTTON_DPAD_DOWN,  SDL_GAMEPAD_BUTTON_DPAD_LEFT,
                SDL_GAMEPAD_BUTTON_DPAD_RIGHT, SDL_GAMEPAD_BUTTON_START,     SDL_GAMEPAD_BUTTON_BACK,
                SDL_GAMEPAD_BUTTON_LEFT_STICK, SDL_GAMEPAD_BUTTON_RIGHT_STICK};
            for (int i = 0; i < 8; i++) p.buttons |= uint16_t(SDL_GetGamepadButton(pad, kButtons[i]) << i);
            // A B X Y black white
            constexpr SDL_GamepadButton kAnalog[] = {SDL_GAMEPAD_BUTTON_SOUTH, SDL_GAMEPAD_BUTTON_EAST,
                                                     SDL_GAMEPAD_BUTTON_WEST,  SDL_GAMEPAD_BUTTON_NORTH,
                                                     SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER};
            for (int i = 0; i < 6; i++) p.analog[i] = SDL_GetGamepadButton(pad, kAnalog[i]) ? 0xFF : 0;
            auto axis = [&](SDL_GamepadAxis a) { return int(SDL_GetGamepadAxis(pad, a)); };
            // 0 to 32767 into 0 to 255
            p.analog[6] = uint8_t(std::max(axis(SDL_GAMEPAD_AXIS_LEFT_TRIGGER), 0) >> 7);
            p.analog[7] = uint8_t(std::max(axis(SDL_GAMEPAD_AXIS_RIGHT_TRIGGER), 0) >> 7);
            // SDL's sticks have y down
            // not plain negation: -32768 has no positive
            p.lx = int16_t(axis(SDL_GAMEPAD_AXIS_LEFTX));
            p.ly = int16_t(-1 - axis(SDL_GAMEPAD_AXIS_LEFTY));
            p.rx = int16_t(axis(SDL_GAMEPAD_AXIS_RIGHTX));
            p.ry = int16_t(-1 - axis(SDL_GAMEPAD_AXIS_RIGHTY));
            // SDL's PS3 drivers give a pad with pressure-sensitive buttons ten more axes after the six usual ones,
            // in its button order: south, east, west, north, the shoulders, then up, down, left, right
            if (type == SDL_GAMEPAD_TYPE_PS3) {
                SDL_Joystick* joy = SDL_GetGamepadJoystick(pad);
                if (joy && SDL_GetNumJoystickAxes(joy) >= 16) {
                    p.has_pressure = true;
                    for (int i = 0; i < 10; i++)
                        p.pressure[i] = uint8_t((int(SDL_GetJoystickAxis(joy, 6 + i)) + 32768) / 257);
                }
            }
        } else if (port >= 0 && port < 4 && g_gc[port] >= 0 && gcadapter::Read(g_gc[port], p.gc)) {
            // by name: A B X Y as themselves, Z the white button, L and R the triggers' travel, their clicks the
            // thumbstick clicks (GameInfo::pad may lay it out again, as gc_controls.cpp does)
            const GameCube& c = p.gc;
            auto on = [&](uint16_t b) { return (c.buttons & b) != 0; };
            p.connected = true;
            p.buttons = uint16_t(on(GameCube::Up) << 0 | on(GameCube::Down) << 1 | on(GameCube::Left) << 2 |
                                 on(GameCube::Right) << 3 | on(GameCube::Start) << 4 | on(GameCube::LClick) << 6 |
                                 on(GameCube::RClick) << 7);
            constexpr uint16_t kFace[6] = {GameCube::A, GameCube::B, GameCube::X, GameCube::Y, 0, GameCube::Z};
            for (int i = 0; i < 6; i++) p.analog[i] = on(kFace[i]) ? 0xFF : 0;
            p.analog[6] = c.l;
            p.analog[7] = c.r;
            p.lx = c.lx;
            p.ly = c.ly;
            p.rx = c.cx;
            p.ry = c.cy;
        } else if (port == 0) {
            KeyboardPad(p);
        }
        NoteActivity(port, p);
    }
    if (app::kGame.pad) app::kGame.pad(port, p);
    return p;
}

// the motors run until set again
void Rumble(int port, uint16_t left, uint16_t right) {
    if (app::kGame.rumble) app::kGame.rumble(port, left, right);
    std::lock_guard lock(g_lock);
    if (port >= 0 && port < 4 && g_pads[port]) SDL_RumbleGamepad(g_pads[port], left, right, 0);
    if (port >= 0 && port < 4 && g_gc[port] >= 0) gcadapter::Rumble(g_gc[port], left || right);  // on or off only
}

}  // namespace input
#endif  // XBE_UWP
