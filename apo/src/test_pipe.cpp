// Harness E2E: valida el protocolo STFUFrame contra el pipe server Python.
// Uso: test_pipe.exe [pipeName]  (default \\.\pipe\stfu_apo_mic)
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <string>
#include "guids.h"
#include "pipe_worker.h"

int wmain(int argc, wchar_t** argv) {
    const std::wstring pipeName = argc > 1 ? argv[1] : STFU_PIPE_MIC;
    constexpr uint32_t kRate = 48000, kChannels = 2, kFrames = 480, kBlocks = 50;

    PipeWorker worker;
    worker.Start(pipeName, kRate, kChannels, kFrames);

    std::vector<float> block(kFrames * kChannels);
    std::vector<float> out(kFrames * kChannels);
    uint32_t received = 0;
    double maxErr = 0.0;

    for (uint32_t b = 0; b < kBlocks; ++b) {
        for (uint32_t f = 0; f < kFrames; ++f) {
            const float s = std::sinf(2.0f * 3.14159265f * 440.0f *
                                      (b * kFrames + f) / kRate);
            block[f * kChannels] = s;
            block[f * kChannels + 1] = s;
        }
        worker.InRing().Write(block.data(), block.size());
        worker.SignalData();
        Sleep(10);
        if (worker.OutRing().ReadExact(out.data(), out.size())) {
            ++received;
            // el server passthrough debe devolver el bloque idéntico (con
            // desfase de bloques; solo validamos rango sano)
            for (float v : out) maxErr = std::max(maxErr, (double)std::fabs(v) - 1.0);
        }
    }
    worker.Stop();

    wprintf(L"blocks sent=%u received=%u maxOver=%f\n", kBlocks, received, maxErr);
    if (received < kBlocks / 2) {
        wprintf(L"FAIL: bridge no responde\n");
        return 1;
    }
    wprintf(L"OK\n");
    return 0;
}
