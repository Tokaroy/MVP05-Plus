#pragma once
#include <atomic>
#include <cstdint>
#include <functional>

namespace audio {

constexpr uint32_t kRate = 48000;

// the whole mix's gain (1: as the Xbox plays it); above 1, the loudest parts are rounded off rather than clipped
inline std::atomic<float> g_output_gain{1.0f};

// the platform output pulls interleaved stereo float frames from render
void StartOutput(std::function<void(float* out, uint32_t frames)> render);
// Bounded: a guest mixer lock may be held by a faulted thread.
void StopOutput();

}  // namespace audio
