#pragma once
// For code written for the desktop that the Xbox (UWP) app builds as it is (ImGui's DX12 backend), included ahead of
// it by the build: an app loads DLLs from its own package (or the system's), with LoadPackagedLibrary.
#if defined(XBE_UWP) && defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

inline HMODULE XbeLoadLibraryA(const char* name) {
    wchar_t w[MAX_PATH] = {};
    MultiByteToWideChar(CP_ACP, 0, name, -1, w, MAX_PATH);
    return LoadPackagedLibrary(w, 0);
}
#define LoadLibraryA XbeLoadLibraryA
#endif
