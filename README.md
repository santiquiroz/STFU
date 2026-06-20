# STFU — Suppress The Frustrating Unwanted noise

> Open-source AI audio processing for Windows — bidirectional noise cancellation, voice enhancement, and a community model hub that runs on **any GPU** (AMD, NVIDIA, Intel) or CPU.

---

## Why STFU?

NVIDIA Broadcast requires an RTX GPU. AMD Noise Suppression is a black box. Both give you one model, no customization, and zero transparency.

STFU gives you:

- **Any hardware** — DirectML runs on AMD, NVIDIA, and Intel GPUs via a single pip package. No CUDA required.
- **Any model** — The community hub supports any ONNX model from HuggingFace. New state-of-the-art model released today? Install it in two clicks.
- **Any use case** — Noise cancellation for gaming, vocal enhancement for podcasting, music processing for production. The same pipeline handles all of it.
- **Full control** — Choose which processor runs each effect. Keep your gaming GPU free while the iGPU handles noise cancellation.

---

## Features

### MVP (v1)
- [x] Bidirectional noise cancellation — microphone and speakers independently
- [x] Runs on CPU or any DirectX 12 GPU via DirectML
- [x] Per-effect processor selection (CPU / GPU 0 / GPU 1 / ...)
- [x] Built-in model: DeepFilterNet3 (40ms latency, no GPU required)
- [x] System tray app — set and forget
- [x] Simple mode (toggle + slider) and Advanced mode (plugin chain editor)
- [x] Windows 11 APO integration (no extra drivers needed)
- [x] VB-Cable fallback for Windows 10

### Roadmap
- [ ] Community model hub — HuggingFace models with `stfu-compatible` tag
- [ ] Voice changer — real-time voice conversion (RVC, Seed-VC via ONNX)
- [ ] Music enhancement — vocal clarity, noise reduction for recordings
- [ ] STFU Audio Device — our own open-source WDM virtual audio driver
- [ ] VST/CLAP plugin format
- [ ] Android support

---

## How it works

```
[Microphone]
     │  WASAPI (sounddevice)
     ▼
[Plugin Pipeline]
     ├── DeepFilterNet3   → DirectML (AMD RX 7800 XT)
     ├── EQ Parametric    → CPU
     └── [your model]    → any backend
     │
     ▼
[Virtual Mic] → Discord, OBS, Teams, Meet...

[Speakers] ← same pipeline in reverse
```

Each plugin in the chain declares its own audio format requirements (sample rate, chunk size, channels). The pipeline automatically inserts resamplers and adapters between plugins — you can chain a 16kHz voice model with a 96kHz stereo music enhancer without any manual configuration.

---

## Model Hub

Any ONNX model tagged `stfu-compatible` on HuggingFace appears in the hub.

```
Browse → Download → Drag into pipeline → Done
```

To publish your own model:
1. Export to ONNX
2. Write a `manifest.json` with format requirements
3. Upload to HuggingFace with tag `stfu-compatible`
4. (Optional) Publish a plugin `.py` for custom parameters

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Audio I/O | Python `sounddevice` + WASAPI |
| AI inference | ONNX Runtime + DirectML (any GPU) |
| Model hub | `huggingface_hub` |
| Resampling | `scipy.signal.resample_poly` |
| API | FastAPI + WebSocket |
| UI shell | Tauri 2 (Rust) |
| Frontend | React 19 + TypeScript |
| Virtual device (v1) | Windows 11 APO / VB-Cable |
| Virtual device (v2) | STFU Audio Device (WDM, open-source) |

---

## Getting Started

> Installation instructions coming with v1 release.

```powershell
# Requirements: Python 3.11+, Windows 10/11
git clone https://github.com/santiquiroz/STFU.git
cd STFU
./scripts/setup.ps1
```

---

## Architecture

```
stfu/
├── backend/          # Python Audio Service (FastAPI + audio pipeline)
│   └── stfu/
│       ├── core/     # Pipeline engine, format adapters
│       ├── plugins/  # AudioPlugin base + built-in effects
│       ├── hub/      # Model download and registry
│       ├── audio/    # WASAPI capture/playback threads
│       └── api/      # FastAPI routes + WebSocket metering
├── frontend/         # Tauri 2 + React 19
│   ├── src/
│   │   ├── pages/    # Simple, Advanced, Hub
│   │   └── components/
│   └── src-tauri/
├── driver/           # STFU Audio Device — WDM virtual driver (v2)
└── scripts/          # Build and setup scripts
```

---

## Contributing

Contributions welcome — plugins, models, drivers, UI improvements.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT — use it, fork it, build on it.

---

<p align="center">
  Built because silence should be a choice, not a hardware requirement.
</p>
