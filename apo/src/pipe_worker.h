#pragma once
#include <windows.h>
#include <atomic>
#include <cstdint>
#include <string>
#include <thread>
#include <vector>
#include "spsc_ring.h"

// Puente APO <-> servicio Python por named pipe (protocolo STFUFrame).
// El hilo worker es el ÚNICO que toca el pipe: APOProcess solo empuja/lee
// rings lock-free. Si el servicio no está, el audio pasa limpio (los rings
// se drenan y el APO hace passthrough).
class PipeWorker {
public:
    void Start(const std::wstring& pipeName, uint32_t sampleRate,
               uint32_t channels, uint32_t maxFrames);
    void Stop();
    void Reset();

    SpscRing& InRing() { return in_; }
    SpscRing& OutRing() { return out_; }
    void SignalData() { if (dataEvent_) SetEvent(dataEvent_); }

private:
    void Loop();
    bool Connect();
    void Disconnect();
    bool Exchange(const float* samples, uint32_t numSamples);

    SpscRing in_;
    SpscRing out_;
    std::thread thread_;
    std::atomic<bool> stop_{false};
    HANDLE dataEvent_ = nullptr;
    HANDLE pipe_ = INVALID_HANDLE_VALUE;
    std::wstring pipeName_;
    uint32_t sampleRate_ = 48000;
    uint32_t channels_ = 2;
    uint32_t chunkSamples_ = 480;  // frames por mensaje al servicio
    uint32_t frameId_ = 0;
    std::vector<float> scratch_;
    std::vector<uint8_t> msg_;
};
