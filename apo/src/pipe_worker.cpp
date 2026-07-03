#include "pipe_worker.h"

namespace {
constexpr uint32_t kRingChunks = 32;
constexpr DWORD kConnectRetryMs = 500;
constexpr DWORD kWaitDataMs = 50;

void PutU32(std::vector<uint8_t>& v, uint32_t x) {
    v.push_back(static_cast<uint8_t>(x));
    v.push_back(static_cast<uint8_t>(x >> 8));
    v.push_back(static_cast<uint8_t>(x >> 16));
    v.push_back(static_cast<uint8_t>(x >> 24));
}

uint32_t GetU32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}
}  // namespace

void PipeWorker::Start(const std::wstring& pipeName, uint32_t sampleRate,
                       uint32_t channels, uint32_t maxFrames) {
    Stop();
    pipeName_ = pipeName;
    sampleRate_ = sampleRate;
    channels_ = channels;
    chunkSamples_ = maxFrames > 0 ? maxFrames : 480;
    const size_t ringFloats = static_cast<size_t>(kRingChunks) * chunkSamples_ * channels_;
    in_.Reset(ringFloats);
    out_.Reset(ringFloats);
    scratch_.assign(static_cast<size_t>(chunkSamples_) * channels_, 0.0f);
    dataEvent_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    stop_.store(false);
    thread_ = std::thread(&PipeWorker::Loop, this);
}

void PipeWorker::Stop() {
    stop_.store(true);
    if (dataEvent_) SetEvent(dataEvent_);
    if (thread_.joinable()) thread_.join();
    Disconnect();
    if (dataEvent_) {
        CloseHandle(dataEvent_);
        dataEvent_ = nullptr;
    }
}

void PipeWorker::Reset() {
    // Descarta lo pendiente; el APO vuelve a passthrough hasta rellenar.
    in_.Reset(in_.Free() + in_.Available());
    out_.Reset(out_.Free() + out_.Available());
}

bool PipeWorker::Connect() {
    pipe_ = CreateFileW(pipeName_.c_str(), GENERIC_READ | GENERIC_WRITE, 0,
                        nullptr, OPEN_EXISTING, 0, nullptr);
    if (pipe_ == INVALID_HANDLE_VALUE) return false;
    DWORD mode = PIPE_READMODE_MESSAGE;
    if (!SetNamedPipeHandleState(pipe_, &mode, nullptr, nullptr)) {
        Disconnect();
        return false;
    }
    return true;
}

void PipeWorker::Disconnect() {
    if (pipe_ != INVALID_HANDLE_VALUE) {
        CloseHandle(pipe_);
        pipe_ = INVALID_HANDLE_VALUE;
    }
}

bool PipeWorker::Exchange(const float* samples, uint32_t numSamples) {
    msg_.clear();
    PutU32(msg_, frameId_++);
    PutU32(msg_, sampleRate_);
    PutU32(msg_, channels_);
    PutU32(msg_, numSamples);
    const size_t payload = static_cast<size_t>(numSamples) * channels_ * sizeof(float);
    const uint8_t* raw = reinterpret_cast<const uint8_t*>(samples);
    msg_.insert(msg_.end(), raw, raw + payload);

    DWORD written = 0;
    if (!WriteFile(pipe_, msg_.data(), static_cast<DWORD>(msg_.size()), &written, nullptr))
        return false;

    std::vector<uint8_t> resp(8 + payload);
    DWORD read = 0;
    if (!ReadFile(pipe_, resp.data(), static_cast<DWORD>(resp.size()), &read, nullptr))
        return false;
    if (read < 8) return false;
    const uint32_t respSamples = GetU32(resp.data() + 4);
    const size_t respFloats = static_cast<size_t>(respSamples) * channels_;
    if (8 + respFloats * sizeof(float) > read) return false;
    out_.Write(reinterpret_cast<const float*>(resp.data() + 8), respFloats);
    return true;
}

void PipeWorker::Loop() {
    const size_t block = static_cast<size_t>(chunkSamples_) * channels_;
    while (!stop_.load()) {
        if (pipe_ == INVALID_HANDLE_VALUE) {
            if (!Connect()) {
                // Servicio ausente: drena el ring para no estancar al APO
                while (in_.ReadExact(scratch_.data(), block)) {}
                WaitForSingleObject(dataEvent_, kConnectRetryMs);
                continue;
            }
        }
        if (!in_.ReadExact(scratch_.data(), block)) {
            WaitForSingleObject(dataEvent_, kWaitDataMs);
            continue;
        }
        if (!Exchange(scratch_.data(), chunkSamples_)) Disconnect();
    }
}
