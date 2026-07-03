#pragma once
#include <atomic>
#include <cstdint>
#include <cstring>
#include <vector>

// Ring SPSC de floats: un productor, un consumidor, solo atomics.
// El lado RT (APOProcess) nunca bloquea: si no cabe, descarta; si no hay,
// el llamador hace passthrough.
class SpscRing {
public:
    void Reset(size_t capacity) {
        buf_.assign(capacity + 1, 0.0f);
        read_.store(0, std::memory_order_relaxed);
        write_.store(0, std::memory_order_relaxed);
    }

    size_t Available() const {
        const size_t w = write_.load(std::memory_order_acquire);
        const size_t r = read_.load(std::memory_order_acquire);
        return (w + buf_.size() - r) % buf_.size();
    }

    size_t Free() const { return buf_.size() - 1 - Available(); }

    // Escribe n floats; retorna cuántos cupieron.
    size_t Write(const float* data, size_t n) {
        const size_t w = write_.load(std::memory_order_relaxed);
        const size_t free = Free();
        if (n > free) n = free;
        const size_t first = (n < buf_.size() - w) ? n : buf_.size() - w;
        std::memcpy(buf_.data() + w, data, first * sizeof(float));
        if (n > first) std::memcpy(buf_.data(), data + first, (n - first) * sizeof(float));
        write_.store((w + n) % buf_.size(), std::memory_order_release);
        return n;
    }

    // Lee exactamente n floats si hay; si no hay suficientes, no lee nada
    // (retorna false) para mantener frames completos.
    bool ReadExact(float* out, size_t n) {
        if (Available() < n) return false;
        const size_t r = read_.load(std::memory_order_relaxed);
        const size_t first = (n < buf_.size() - r) ? n : buf_.size() - r;
        std::memcpy(out, buf_.data() + r, first * sizeof(float));
        if (n > first) std::memcpy(out + first, buf_.data(), (n - first) * sizeof(float));
        read_.store((r + n) % buf_.size(), std::memory_order_release);
        return true;
    }

private:
    std::vector<float> buf_{1};
    std::atomic<size_t> read_{0};
    std::atomic<size_t> write_{0};
};
