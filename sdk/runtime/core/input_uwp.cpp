// The Xbox (UWP) app's controllers: Xbox controllers through Windows.Gaming.Input, read into the console controller's
// report as input.cpp does on the PC (which uses SDL, not available to an Xbox app). There's no GameCube adapter or
// PlayStation pad on the Xbox: gcadapter is here as nothing.
#ifdef XBE_UWP
#include "core/input.h"

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <roapi.h>
#include <winstring.h>
#include <wrl/client.h>
#include <windows.gaming.input.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <mutex>

#include "app/app.h"
#include "core/gc_adapter.h"
#include "core/log.h"

using Microsoft::WRL::ComPtr;
namespace GI = ABI::Windows::Gaming::Input;

namespace gcadapter {
void Start() {}
bool Read(int, input::GameCube&) { return false; }
void Rumble(int, bool) {}
}  // namespace gcadapter

namespace input {

namespace {

std::mutex g_lock;
ComPtr<GI::IGamepadStatics> g_statics;
// a controller takes the lowest free port when it's first seen, and keeps it until it's gone
ComPtr<GI::IGamepad> g_pads[4];

// (by value: the SDK's headers may declare the flags scoped or not)
enum : uint32_t {
    kMenu = 0x1, kView = 0x2, kA = 0x4, kB = 0x8, kX = 0x10, kY = 0x20, kUp = 0x40, kDown = 0x80, kLeft = 0x100,
    kRight = 0x200, kLB = 0x400, kRB = 0x800, kLS = 0x1000, kRS = 0x2000,
};

// the controllers connected now, matched to the ports: a new one to the first free port, a gone one's port freed
void UpdatePads() {
    using clock = std::chrono::steady_clock;
    static clock::time_point last{};
    auto now = clock::now();
    if (now - last < std::chrono::milliseconds(250)) return;  // the list changes rarely: four times a second
    last = now;
    if (!g_statics) return;
    ComPtr<ABI::Windows::Foundation::Collections::IVectorView<GI::Gamepad*>> list;
    if (FAILED(g_statics->get_Gamepads(&list)) || !list) return;
    unsigned n = 0;
    list->get_Size(&n);
    ComPtr<GI::IGamepad> now_pads[8];
    n = std::min(n, 8u);
    for (unsigned i = 0; i < n; i++) list->GetAt(i, &now_pads[i]);
    auto connected = [&](GI::IGamepad* p) {
        for (unsigned i = 0; i < n; i++)
            if (now_pads[i].Get() == p) return true;
        return false;
    };
    for (int port = 0; port < 4; port++)
        if (g_pads[port] && !connected(g_pads[port].Get())) {
            g_pads[port].Reset();
            LOGR("input: controller %d unplugged", port + 1);
        }
    for (unsigned i = 0; i < n; i++) {
        bool have = false;
        for (auto& p : g_pads) have |= p.Get() == now_pads[i].Get();
        if (have) continue;
        for (int port = 0; port < 4; port++)
            if (!g_pads[port]) {
                g_pads[port] = now_pads[i];
                LOGR("input: controller %d plugged in: Xbox controller", port + 1);
                break;
            }
    }
}

int16_t Stick(double v) { return int16_t(std::clamp(v * 32767.0, -32768.0, 32767.0)); }
uint8_t Trigger(double v) { return uint8_t(std::clamp(v * 255.0 + 0.5, 0.0, 255.0)); }

}  // namespace

void Init() {
    HSTRING cls = nullptr;
    const wchar_t* name = L"Windows.Gaming.Input.Gamepad";
    WindowsCreateString(name, UINT32(wcslen(name)), &cls);
    HRESULT hr = RoGetActivationFactory(cls, __uuidof(GI::IGamepadStatics),
                                        reinterpret_cast<void**>(g_statics.ReleaseAndGetAddressOf()));
    WindowsDeleteString(cls);
    if (FAILED(hr)) {
        LOGE("input: no controllers (Windows.Gaming.Input %08lX)", static_cast<unsigned long>(hr));
        return;
    }
    LOGI("input: Windows.Gaming.Input");
    std::lock_guard lock(g_lock);
    UpdatePads();
}

Pad Poll(int port) {
    Pad p;
    {
        std::lock_guard lock(g_lock);
        UpdatePads();
        GI::GamepadReading r{};
        if (port >= 0 && port < 4 && g_pads[port] && SUCCEEDED(g_pads[port]->GetCurrentReading(&r))) {
            uint32_t b = static_cast<uint32_t>(r.Buttons);
            auto on = [&](uint32_t m) { return (b & m) != 0; };
            p.connected = true;
            p.buttons = uint16_t(on(kUp) << 0 | on(kDown) << 1 | on(kLeft) << 2 | on(kRight) << 3 | on(kMenu) << 4 |
                                 on(kView) << 5 | on(kLS) << 6 | on(kRS) << 7);
            // A B X Y black white: the bumpers stand for black (RB) and white (LB), as on the PC
            const uint32_t face[6] = {kA, kB, kX, kY, kRB, kLB};
            for (int i = 0; i < 6; i++) p.analog[i] = on(face[i]) ? 0xFF : 0;
            p.analog[6] = Trigger(r.LeftTrigger);
            p.analog[7] = Trigger(r.RightTrigger);
            p.lx = Stick(r.LeftThumbstickX);  // y up already, as the console's
            p.ly = Stick(r.LeftThumbstickY);
            p.rx = Stick(r.RightThumbstickX);
            p.ry = Stick(r.RightThumbstickY);
        }
    }
    if (app::kGame.pad) app::kGame.pad(port, p);
    return p;
}

// the motors run until set again
void Rumble(int port, uint16_t left, uint16_t right) {
    if (app::kGame.rumble) app::kGame.rumble(port, left, right);
    std::lock_guard lock(g_lock);
    if (port < 0 || port >= 4 || !g_pads[port]) return;
    GI::GamepadVibration v{};
    v.LeftMotor = left / 65535.0;
    v.RightMotor = right / 65535.0;
    g_pads[port]->put_Vibration(v);
}

}  // namespace input
#endif  // XBE_UWP
