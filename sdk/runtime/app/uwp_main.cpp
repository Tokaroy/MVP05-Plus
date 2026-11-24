// The Xbox (UWP, Dev Mode) host: the app's CoreWindow, its event loop and where the game's folder is. The PC's is
// main.cpp; the rest of the runtime is the same, through app.h.
//
// The game's folder (ExeDir) is the first of:
//   a folder on a USB drive (D: to Z:) with assets\default.xbe in it, named MVP05-Plus... first: an install made on a
//     PC (unzip MVP05-Plus onto the drive, install from the discs there). The drive is NTFS, with "ALL APPLICATION
//     PACKAGES" given full control (Dev Mode apps only reach a drive that allows them)
//   LocalState\MVP05-Plus, or LocalState itself, the app's own storage (a folder put there with Device Portal)
// What it found is written to LocalState\xbox-start.txt (Device Portal's file explorer shows it), as is anything that
// stops the game (Alert: there's no message box for it on screen yet).
#ifdef XBE_UWP
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
#include <windows.applicationmodel.core.h>
#include <windows.graphics.display.h>
#include <windows.storage.h>
#include <windows.system.h>
#include <windows.ui.core.h>

#include <eh.h>
#include <signal.h>
#include <stdlib.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <deque>
#include <fstream>
#include <functional>
#include <string>
#include <thread>

#include <imgui.h>

#include "app/app.h"
#include "core/input.h"
#include "core/log.h"
#include "gpu/backend.h"
#include "image_symbols.h"
#include "kernel/kernel.h"

using Microsoft::WRL::ComPtr;
namespace AC = ABI::Windows::ApplicationModel::Core;
namespace AA = ABI::Windows::ApplicationModel::Activation;
namespace UC = ABI::Windows::UI::Core;
namespace WF = ABI::Windows::Foundation;
namespace fs = std::filesystem;

namespace app {

namespace {

constexpr uint32_t kWmKeyDown = 0x0100, kWmKeyUp = 0x0101;  // as the game's message hook takes them (winuser.h)

ComPtr<UC::ICoreWindow> g_window;
std::atomic<uint32_t> g_width{1920}, g_height{1080};
std::atomic<bool> g_closed{false}, g_activated{false};
std::atomic<bool> g_keys[256];
std::wstring g_start_log;  // LocalState\xbox-start.txt
fs::path g_root;

// a WinRT string for a call
struct HStr {
    HSTRING h = nullptr;
    explicit HStr(const wchar_t* s) { WindowsCreateString(s, UINT32(wcslen(s)), &h); }
    ~HStr() { WindowsDeleteString(h); }
    operator HSTRING() const { return h; }
};

std::wstring Text(HSTRING h) {
    UINT32 n = 0;
    const wchar_t* p = WindowsGetStringRawBuffer(h, &n);
    return p ? std::wstring(p, n) : std::wstring();
}

template <class I>
HRESULT Factory(const wchar_t* cls, ComPtr<I>& out) {
    return RoGetActivationFactory(HStr(cls), __uuidof(I), reinterpret_cast<void**>(out.ReleaseAndGetAddressOf()));
}

// LocalState\xbox-start.txt: one line each, written at once (the game's own log may not be open yet, or ever)
void StartNote(const std::string& line) {
    if (g_start_log.empty()) return;
    std::ofstream f(fs::path(g_start_log), std::ios::app);
    f << line << "\n";
}

std::string Narrow(const std::wstring& w) {
    std::string s;
    for (wchar_t c : w) s += c < 128 ? char(c) : '?';
    return s;
}

// a WinRT event handler: Invoke calls fn
template <class I, class... A>
struct Handler final : I {
    std::function<HRESULT(A...)> fn;
    std::atomic<ULONG> refs{1};
    explicit Handler(std::function<HRESULT(A...)> f) : fn(std::move(f)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void** out) override {
        if (id == __uuidof(IUnknown) || id == __uuidof(I) || id == __uuidof(IAgileObject)) {
            *out = static_cast<I*>(this);
            AddRef();
            return S_OK;
        }
        *out = nullptr;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override {
        ULONG n = --refs;
        if (!n) delete this;
        return n;
    }
    HRESULT STDMETHODCALLTYPE Invoke(A... a) override { return fn(a...); }
};

using KeyHandler = Handler<WF::ITypedEventHandler<UC::CoreWindow*, UC::KeyEventArgs*>, UC::ICoreWindow*, UC::IKeyEventArgs*>;
using ClosedHandler =
    Handler<WF::ITypedEventHandler<UC::CoreWindow*, UC::CoreWindowEventArgs*>, UC::ICoreWindow*, UC::ICoreWindowEventArgs*>;
using ActivatedHandler = Handler<WF::ITypedEventHandler<AC::CoreApplicationView*, AA::IActivatedEventArgs*>,
                                 AC::ICoreApplicationView*, AA::IActivatedEventArgs*>;

// a key from a keyboard on the Xbox (or a gamepad's, which come this way too and are left to the controller code)
HRESULT OnKey(UC::IKeyEventArgs* args, bool down) {
    ABI::Windows::System::VirtualKey vk{};
    UC::CorePhysicalKeyStatus st{};
    args->get_VirtualKey(&vk);
    args->get_KeyStatus(&st);
    int key = int(vk);
    if (key <= 0 || key >= 256 || (key >= 195 && key <= 218)) return S_OK;  // 195-218: the gamepad's
    bool repeated = down && g_keys[key].load();
    g_keys[key] = down;
    intptr_t lp = intptr_t(st.RepeatCount ? st.RepeatCount : 1) | (repeated ? intptr_t(1) << 30 : 0);
    {  // a keyboard moves around the menus as on the PC
        ImGuiKey k = key == 0x26 ? ImGuiKey_UpArrow : key == 0x28 ? ImGuiKey_DownArrow : key == 0x25 ? ImGuiKey_LeftArrow
                   : key == 0x27 ? ImGuiKey_RightArrow : key == 0x0D ? ImGuiKey_Enter : key == 0x1B ? ImGuiKey_Escape
                   : key == 0x09 ? ImGuiKey_Tab : key == 0x20 ? ImGuiKey_Space : ImGuiKey_None;
        std::lock_guard lock(UiLock());
        if (k != ImGuiKey_None && ImGui::GetCurrentContext()) ImGui::GetIO().AddKeyEvent(k, down);
    }
    intptr_t result = 0;
    if (kGame.message) kGame.message(nullptr, down ? kWmKeyDown : kWmKeyUp, uintptr_t(key), lp, &result);
    if (down && key == 0x7B && !repeated) gpu::g_screenshot.store(true);  // F12, as on the PC
    return S_OK;
}

void MeasureWindow() {
    if (!g_window) return;
    WF::Rect r{};
    g_window->get_Bounds(&r);
    double scale = 1.0;
    ComPtr<ABI::Windows::Graphics::Display::IDisplayInformationStatics> statics;
    ComPtr<ABI::Windows::Graphics::Display::IDisplayInformation> info;
    ComPtr<ABI::Windows::Graphics::Display::IDisplayInformation2> info2;
    if (SUCCEEDED(Factory(L"Windows.Graphics.Display.DisplayInformation", statics)) &&
        SUCCEEDED(statics->GetForCurrentView(&info)) && SUCCEEDED(info.As(&info2)))
        info2->get_RawPixelsPerViewPixel(&scale);
    g_width = std::max(1u, uint32_t(r.Width * scale + 0.5));
    g_height = std::max(1u, uint32_t(r.Height * scale + 0.5));
}

fs::path LocalState() {
    ComPtr<ABI::Windows::Storage::IApplicationDataStatics> statics;
    ComPtr<ABI::Windows::Storage::IApplicationData> data;
    ComPtr<ABI::Windows::Storage::IStorageFolder> folder;
    ComPtr<ABI::Windows::Storage::IStorageItem> item;
    HSTRING path = nullptr;
    if (FAILED(Factory(L"Windows.Storage.ApplicationData", statics)) || FAILED(statics->get_Current(&data)) ||
        FAILED(data->get_LocalFolder(&folder)) || FAILED(folder.As(&item)) || FAILED(item->get_Path(&path)))
        return {};
    fs::path p = Text(path);
    WindowsDeleteString(path);
    return p;
}

bool HasGame(const fs::path& dir) {
    WIN32_FILE_ATTRIBUTE_DATA a{};
    return GetFileAttributesExW((dir / "assets" / IMAGE_XBE).c_str(), GetFileExInfoStandard, &a) != 0;
}

// the game's folder: see the top of this file
fs::path FindRoot() {
    fs::path local = LocalState();
    if (!local.empty()) {
        g_start_log = (local / "xbox-start.txt").wstring();
        // the last run's is kept beside it (a run that crashed is often followed by one that didn't get far)
        MoveFileExW(g_start_log.c_str(), (local / "xbox-start-previous.txt").c_str(), MOVEFILE_REPLACE_EXISTING);
    }
    StartNote("MVP05-Plus on the Xbox: looking for the game's folder");
    StartNote("LocalState: " + Narrow(local.wstring()));
    std::vector<fs::path> found;
    for (wchar_t d = L'D'; d <= L'Z'; d++) {  // (each letter tried: a drive that isn't there says so at once)
        std::wstring root = std::wstring(1, d) + L":\\";
        WIN32_FIND_DATAW fd{};
        HANDLE h = FindFirstFileExW((root + L"*").c_str(), FindExInfoBasic, &fd, FindExSearchNameMatch, nullptr, 0);
        if (h == INVALID_HANDLE_VALUE) {
            DWORD e = GetLastError();
            if (e == ERROR_PATH_NOT_FOUND || e == ERROR_NOT_READY || e == ERROR_INVALID_DRIVE || e == ERROR_INVALID_NAME)
                continue;
            StartNote("  " + Narrow(root) + ": can't be read (error " + std::to_string(e) +
                      "): an NTFS drive needs ALL APPLICATION PACKAGES given full control");
            continue;
        }
        int folders = 0;
        do {
            if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || fd.cFileName[0] == L'.') continue;
            folders++;
            fs::path p = fs::path(root) / fd.cFileName;
            if (HasGame(p)) found.push_back(p);
        } while (FindNextFileW(h, &fd));
        FindClose(h);
        StartNote("  " + Narrow(root) + ": " + std::to_string(folders) + " folders looked in");
    }
    // a folder named for the game first (MVP05-Plus, MVP05-Plus-Beta-3.0 ...), then any with the game in it
    std::stable_sort(found.begin(), found.end(), [](const fs::path& a, const fs::path& b) {
        auto named = [](const fs::path& p) { return p.filename().wstring().rfind(L"MVP05", 0) == 0; };
        return named(a) && !named(b);
    });
    for (auto& p : found) StartNote("  the game is in " + Narrow(p.wstring()));
    if (!found.empty()) return found.front();
    if (!local.empty() && HasGame(local / "MVP05-Plus")) return local / "MVP05-Plus";
    StartNote(local.empty() ? "  no LocalState either" : "  none on a USB drive: the app's own storage, LocalState");
    return local;
}

// The app as Windows runs it: the view gets its window, then Run is the game
struct View final : AC::IFrameworkView, AC::IFrameworkViewSource {
    std::atomic<ULONG> refs{1};
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void** out) override {
        if (id == __uuidof(IUnknown) || id == __uuidof(IInspectable) || id == __uuidof(AC::IFrameworkView))
            *out = static_cast<AC::IFrameworkView*>(this);
        else if (id == __uuidof(AC::IFrameworkViewSource))
            *out = static_cast<AC::IFrameworkViewSource*>(this);
        else {
            *out = nullptr;
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { return --refs; }  // one, for the app's lifetime
    HRESULT STDMETHODCALLTYPE GetIids(ULONG* n, IID** ids) override {
        *n = 0;
        *ids = nullptr;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetRuntimeClassName(HSTRING* name) override { return WindowsCreateString(L"View", 4, name); }
    HRESULT STDMETHODCALLTYPE GetTrustLevel(TrustLevel* level) override {
        *level = BaseTrust;
        return S_OK;
    }

    // IFrameworkViewSource
    HRESULT STDMETHODCALLTYPE CreateView(AC::IFrameworkView** view) override {
        *view = static_cast<AC::IFrameworkView*>(this);
        AddRef();
        return S_OK;
    }

    // IFrameworkView
    HRESULT STDMETHODCALLTYPE Initialize(AC::ICoreApplicationView* view) override {
        EventRegistrationToken t{};
        auto* h = new ActivatedHandler([](AC::ICoreApplicationView* v, AA::IActivatedEventArgs*) {
            ComPtr<UC::ICoreWindow> w;
            if (SUCCEEDED(v->get_CoreWindow(&w)) && w) w->Activate();
            g_activated = true;
            return S_OK;
        });
        view->add_Activated(h, &t);
        h->Release();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE SetWindow(UC::ICoreWindow* window) override {
        g_window = window;
        EventRegistrationToken t{};
        auto* down = new KeyHandler([](UC::ICoreWindow*, UC::IKeyEventArgs* a) { return OnKey(a, true); });
        auto* up = new KeyHandler([](UC::ICoreWindow*, UC::IKeyEventArgs* a) { return OnKey(a, false); });
        auto* closed = new ClosedHandler([](UC::ICoreWindow*, UC::ICoreWindowEventArgs*) {
            g_closed = true;
            return S_OK;
        });
        window->add_KeyDown(down, &t);
        window->add_KeyUp(up, &t);
        window->add_Closed(closed, &t);
        down->Release(), up->Release(), closed->Release();
        MeasureWindow();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE Load(HSTRING) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE Uninitialize() override { return S_OK; }
    HRESULT STDMETHODCALLTYPE Run() override;
};

// (by value: the SDK's headers may declare WinRT enums scoped or not)
const auto kAllPending = static_cast<UC::CoreProcessEventsOption>(3);  // CoreProcessEventsOption_ProcessAllIfPresent

ComPtr<UC::ICoreDispatcher> Dispatcher() {
    ComPtr<UC::ICoreDispatcher> d;
    if (g_window) g_window->get_Dispatcher(&d);
    return d;
}

// the window's events until it closes
void EventLoop() {
    ComPtr<UC::ICoreDispatcher> d = Dispatcher();
    while (!g_closed) {
        if (d) d->ProcessEvents(kAllPending);
        std::this_thread::sleep_for(std::chrono::milliseconds(4));
    }
}

// the app's memory and its limit, in MB (the Xbox closes an app that goes over it, with nothing in its log)
bool AppMemory(uint64_t& used, uint64_t& limit) {
    ComPtr<ABI::Windows::System::IMemoryManagerStatics> mm;
    if (FAILED(Factory(RuntimeClass_Windows_System_MemoryManager, mm)) || !mm) return false;
    UINT64 u = 0, l = 0;
    if (FAILED(mm->get_AppMemoryUsage(&u)) || FAILED(mm->get_AppMemoryUsageLimit(&l))) return false;
    used = u >> 20, limit = l >> 20;
    return true;
}

// every 10 seconds of play, a line in xbox-start.txt (the console's own storage, so it's there after a crash) and
// in the log: the frame rate and the memory, the two things that end a run without an error
void Heartbeat() {
    std::thread([] {
        auto start = std::chrono::steady_clock::now(), was = start;
        uint64_t frames_was = gpu::g_frames.load();
        gpu::g_slow_frames = 0, gpu::g_worst_frame_us = 0;
        for (;;) {
            std::this_thread::sleep_for(std::chrono::seconds(10));
            if (g_closed) return;
            auto now = std::chrono::steady_clock::now();
            int secs = int(std::chrono::duration<double>(now - start).count() + 0.5);
            uint64_t frames = gpu::g_frames.load();
            // the 10 seconds' average, the frames of 25 ms or more (hitches) and the longest
            double avg = (frames - frames_was) / std::max(0.001, std::chrono::duration<double>(now - was).count());
            frames_was = frames, was = now;
            unsigned slow = gpu::g_slow_frames.exchange(0), worst = gpu::g_worst_frame_us.exchange(0);
            char line[200];
            uint64_t used = 0, limit = 0;
            AppMemory(used, limit);
            std::snprintf(line, sizeof(line), "%5ds: %.1f fps, %u hitches (longest %.0f ms), memory %llu of %llu MB",
                          secs, avg, slow, worst / 1000.0, (unsigned long long)used, (unsigned long long)limit);
            StartNote(line);
            LOGR("xbox: %s", line);
        }
    }).detach();
}

// what ends a run without the exception filter seeing it: a C++ exception nothing caught (std::terminate, then
// abort), abort itself, a pure virtual call, a bad argument to the C runtime. Each is noted, then the run ends as before
thread_local char t_thrown[96];  // the type of this thread's last C++ exception (the runtime throws its own, caught)

void ThrowTypeName(const EXCEPTION_RECORD* r) {
    // the MSVC exception record: [2] the ThrowInfo, [3] the image its offsets are from (x64)
    if (r->NumberParameters < 4) return;
    auto image = reinterpret_cast<const uint8_t*>(r->ExceptionInformation[3]);
    auto info = reinterpret_cast<const int32_t*>(r->ExceptionInformation[2]);
    if (!image || !info || !info[3]) return;
    auto types = reinterpret_cast<const int32_t*>(image + info[3]);  // CatchableTypeArray: count, then offsets
    if (types[0] < 1 || !types[1]) return;
    auto type = reinterpret_cast<const int32_t*>(image + types[1]);  // CatchableType: properties, then pType
    if (!type[1]) return;
    const char* name = reinterpret_cast<const char*>(image + type[1] + 16);  // TypeDescriptor: two pointers, the name
    std::snprintf(t_thrown, sizeof(t_thrown), "%s", name);
}

LONG WINAPI FirstChance(EXCEPTION_POINTERS* e) {
    const EXCEPTION_RECORD* r = e->ExceptionRecord;
    if (r->ExceptionCode == 0xE06D7363) {  // a C++ throw
        ThrowTypeName(r);
    } else if ((r->ExceptionCode & 0xF0000000) == 0xC0000000) {  // an error (not a debug print or a thread name)
        static std::atomic<int> told{0};
        if (told.fetch_add(1) < 8) {
            char line[160];
            uint64_t a = r->NumberParameters >= 2 ? uint64_t(r->ExceptionInformation[1]) : 0;
            std::snprintf(line, sizeof(line), "Exception %08lX at %p (address %llX, guest %08llX)", r->ExceptionCode,
                          r->ExceptionAddress, (unsigned long long)a,
                          (unsigned long long)(a - uint64_t(reinterpret_cast<uintptr_t>(kernel::g_base))));
            StartNote(line);
            LOGE("%s", line);
            if (kernel::Thread* t = kernel::Current(); t && t->ctx) kernel::LogGuestStack(*t->ctx, 64);
            logx::Flush();
        }
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

void Ended(const char* how) {
    std::string line = std::string("Ended: ") + how;
    if (t_thrown[0]) line += std::string(" (this thread's last C++ exception: ") + t_thrown + ")";
    StartNote(line);
    LOGE("%s", line.c_str());
    if (kernel::Thread* t = kernel::Current(); t && t->ctx) kernel::LogGuestStack(*t->ctx, 64);
    logx::Flush();
}

void CatchEndings() {
    AddVectoredExceptionHandler(1, FirstChance);
    signal(SIGABRT, [](int) { Ended("abort (a C++ exception nothing caught, or std::abort)"); });
    _set_purecall_handler([] { Ended("a pure virtual function was called"); });
    _set_invalid_parameter_handler([](const wchar_t*, const wchar_t*, const wchar_t*, unsigned, uintptr_t) {
        Ended("the C runtime was given a bad argument");
    });
}

LONG WINAPI Crashed(EXCEPTION_POINTERS* e) {
    if (kernel::Thread* t = kernel::Current(); e && t && t->ctx) {
        auto* r = e->ExceptionRecord;
        LOGE("exception %08lX at %p on guest thread %X", r->ExceptionCode, r->ExceptionAddress, t->id);
        kernel::LogGuestStack(*t->ctx, 256);
    } else if (e) {
        LOGE("exception %08lX at %p", e->ExceptionRecord->ExceptionCode, e->ExceptionRecord->ExceptionAddress);
    }
    if (e) {
        char line[96];
        std::snprintf(line, sizeof(line), "Crashed: exception %08lX at %p", e->ExceptionRecord->ExceptionCode,
                      e->ExceptionRecord->ExceptionAddress);
        StartNote(line);
    }
    logx::Flush();
    return EXCEPTION_CONTINUE_SEARCH;
}

HRESULT STDMETHODCALLTYPE View::Run() {
    ComPtr<UC::ICoreDispatcher> d = Dispatcher();
    for (int i = 0; i < 500 && !g_activated && d; i++) {  // the window, before anything is drawn in it
        d->ProcessEvents(kAllPending);
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    MeasureWindow();
    SetUnhandledExceptionFilter(Crashed);
    g_root = FindRoot();
    CatchEndings();
    StartNote("The game's folder: " + Narrow(g_root.wstring()));
    std::error_code ec;
    fs::create_directories(g_root / "logs", ec);
    logx::Init((g_root / "logs").string(), kGame.log, false);
    StartNote("Log: " + Narrow((g_root / "logs").wstring()) + " (window " + std::to_string(g_width.load()) + "x" +
              std::to_string(g_height.load()) + ")");
    app::Load();
    if (kGame.init) kGame.init();
    LogSystem();
    if (uint64_t used = 0, limit = 0; AppMemory(used, limit)) {
        // a Game gets several GB; an App about 1 GB, too little (Dev Home: View details, App type: Game)
        std::string m = "Memory: " + std::to_string(used) + " MB in use, the limit is " + std::to_string(limit) + " MB" +
                        (limit < 2048 ? " (the app is running as an App: set its App type to Game in Dev Home)" : "");
        StartNote(m);
        LOGR("%s", m.c_str());
    }

    GameFiles game;
    if (!FindGame(game)) {
        StartNote("The game's files weren't found: put your MVP05-Plus folder (with the game installed from your "
                  "discs on the PC) on a USB drive, or in LocalState\\MVP05-Plus");
        EventLoop();
        return S_OK;
    }

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr;
    io.BackendPlatformName = "xbox_uwp";
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard | ImGuiConfigFlags_NavEnableGamepad;
    io.BackendFlags |= ImGuiBackendFlags_HasGamepad;

    input::Init();
    if (kGame.window) kGame.window(g_window.Get());
    if (!kernel::Boot(std::move(game.xbe), IMAGE_XBE, game.dir.string(), (g_root / "hdd").string())) {
        StartNote("The game failed to start: see the log in " + Narrow((g_root / "logs").wstring()));
        Alert(L"The game failed to start, see the log in the logs folder.");
        EventLoop();
        return S_OK;
    }
    StartNote("The game started");
    Heartbeat();
    EventLoop();
    logx::Flush();
    kernel::Shutdown(0);
}

}  // namespace

fs::path ExeDir() { return g_root; }

int Instance() { return 0; }

void* Window() { return static_cast<IUnknown*>(g_window.Get()); }

Mode WindowSize() { return {g_width.load(), g_height.load()}; }

void Alert(const wchar_t* text, bool error) {
    std::string s = Narrow(text);
    if (error) LOGE("%s", s.c_str());
    else LOGR("%s", s.c_str());
    StartNote((error ? "Error: " : "") + s);
}

bool KeyHeld(int vk) { return vk > 0 && vk < 256 && g_keys[vk].load(); }

void UiNewFrame() {
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(float(g_width.load()), float(g_height.load()));
    using clock = std::chrono::steady_clock;
    static clock::time_point last = clock::now();
    auto now = clock::now();
    io.DeltaTime = std::max(std::chrono::duration<float>(now - last).count(), 1e-4f);
    last = now;
}

std::recursive_mutex& UiLock() {
    static std::recursive_mutex m;
    return m;
}

void ApplyDisplay() {}            // the Xbox's screen has one mode for the app: nothing to apply
void OpenGameWindow(bool) {}      // the app's window is always up
void* AppIcon(int) { return nullptr; }
bool OpenSplash() { return false; }
void SplashFirstFrame() {}
void CloseSplash() {}

void Pace() {
    using clock = std::chrono::steady_clock;
    static clock::time_point next = clock::now();
    uint32_t cap = Get().fps_cap;
    auto now = clock::now();
    if (!cap) {
        next = now;
        return;
    }
    auto period = std::chrono::nanoseconds(1000000000ull / cap);
    next += period;
    if (next < now - period) next = now;
    while (clock::now() + std::chrono::milliseconds(2) < next) Sleep(1);
    while (clock::now() < next) std::this_thread::yield();
}

}  // namespace app

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    RoInitialize(RO_INIT_MULTITHREADED);
    ComPtr<AC::ICoreApplication> core;
    if (FAILED(app::Factory(L"Windows.ApplicationModel.Core.CoreApplication", core))) return 1;
    static app::View view;
    core->Run(&view);
    return 0;
}
#endif  // XBE_UWP
