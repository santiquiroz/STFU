# STFU — Design Specification
**Date:** 2026-06-19
**Status:** Approved
**Scope:** v1 MVP — Bidirectional noise cancellation, Windows

---

## 1. Problem Statement

NVIDIA Broadcast requires an RTX GPU. AMD Noise Suppression is a single closed-source model. Both are black boxes with no customization, no model choice, and no support for hardware outside their vendor's ecosystem.

STFU is an open-source alternative that runs on any Windows GPU or CPU via DirectML, supports community models via HuggingFace, and is built on a generic plugin pipeline that does not assume any specific model format or audio configuration.

---

## 2. Goals (v1 MVP)

- Bidirectional noise cancellation (microphone + speakers), independently configurable
- Run on CPU or any DirectX 12 GPU (AMD, NVIDIA, Intel) via ONNX Runtime + DirectML
- Per-plugin processor selection — user chooses which device runs each effect
- Built-in model: DeepFilterNet3 (40ms algorithmic latency, CPU viable)
- System tray app for Windows 11 (Windows 10 with VB-Cable fallback)
- Simple UI (toggle + slider) and Advanced UI (plugin chain editor)

## 3. Non-Goals (v1)

- Cross-platform support (Linux, macOS deferred)
- Voice cloning or real-time voice conversion (v2)
- Music source separation (v2)
- Own WDM virtual audio driver (v2 — see Section 9)
- VST/CLAP plugin format (v3)

---

## 4. Architecture Overview

Three independent processes with clear boundaries:

```
[Physical Mic]
     │  WASAPI exclusive/shared mode (sounddevice)
     ▼
[Python Audio Service]          ← audio I/O + inference + FastAPI
     │  HTTP / WebSocket (localhost)
     ▼
[Tauri + React UI]              ← UI shell, tray icon

[Virtual Mic] → [Discord / OBS / Teams]
     ↑
[Windows APO (W11) / VB-Cable (W10)]
```

**Python Audio Service** owns all audio processing. It starts as a background process on login and exposes a local FastAPI server. The Tauri UI is a thin shell that renders the React frontend and communicates with the service via HTTP.

This is intentionally the same pattern as bipolar-code (FastAPI backend + Tauri frontend) for consistency and maintainability.

---

## 5. Generic Audio Pipeline

### Core principle

The pipeline makes **no assumptions about sample rate, chunk size, channels, or model type**. Each plugin declares its own requirements. The pipeline engine inserts format adapters automatically between plugins.

### AudioFormat

```python
@dataclass
class AudioFormat:
    sample_rate: int      # 8000 – 384000 Hz
    channels: int         # 1 (mono), 2 (stereo), N (multi)
    chunk_samples: int    # samples per processing chunk
    dtype: str            # always "float32" internally
```

### AudioPlugin interface

```python
class AudioPlugin:
    name: str
    version: str
    parameters: list[Parameter]   # exposed to UI automatically

    @property
    def preferred_format(self) -> AudioFormat: ...

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        # receives actual format after adaptation
        # returns output format (may differ from input)
        ...

    def process(self, audio: np.ndarray) -> np.ndarray:
        # audio.shape == (chunk_samples, channels), float32
        ...

    def teardown(self) -> None: ...

    @property
    def algorithmic_latency_ms(self) -> float: ...
```

### Pipeline engine

```python
class Pipeline:
    def compile(self, input_format: AudioFormat) -> None:
        # walks the plugin chain
        # inserts Adapter between plugins where formats differ
        # configures each plugin with its actual runtime format

    def process(self, chunk: np.ndarray) -> np.ndarray:
        # runs each plugin in sequence, applying adapters

    def total_latency_ms(self) -> float:
        # sum of plugin algorithmic latencies + adapter buffering latencies
```

### Format Adapter

Handles three conversions transparently:
- **Resampling**: `scipy.signal.resample_poly` (high quality, minimal artifacts)
- **Channel conversion**: mono ↔ stereo, upmix/downmix
- **Rechunking**: accumulation buffer for plugins requiring larger/smaller chunks

### Threading model

```
Thread 1: WASAPI capture  → ring_buffer_in
Thread 2: Pipeline        → ring_buffer_in → process → ring_buffer_out
Thread 3: WASAPI playback → ring_buffer_out
Thread 4: Speaker loopback capture → pipeline_speaker → physical speakers
Thread 5: FastAPI server  (async)
```

ONNX Runtime releases the Python GIL during C++ inference — threads 1-4 do not block each other.

### Latency budget example

```
Capture buffer:          10ms
DeepFilterNet3:          40ms  (algorithmic, fixed)
Adapter (if needed):      2ms  (buffering)
Playback buffer:         10ms
─────────────────────────────
Total minimum:           62ms
```

The UI shows this budget as a visual bar per plugin and a total display.

---

## 6. Plugin System

### Built-in plugins (v1)

| Plugin | Format | Backend | Latency |
|--------|--------|---------|---------|
| DeepFilterNet3 | 48kHz, mono, 20ms | CPU / DirectML | 40ms |
| EQ Parametric (5 bands) | any | CPU (numpy) | 0ms |
| Gain | any | CPU (numpy) | 0ms |

### GenericONNXPlugin

For ONNX models without a dedicated plugin class, `GenericONNXPlugin` inspects the model graph to infer input/output shapes and derives a best-effort `AudioFormat`. Covers the majority of simple noise suppression models.

### Plugin discovery

```
stfu/plugins/builtin/   ← installed with app
%APPDATA%\stfu\plugins\ ← user / community plugins
```

Scanned at service startup with `importlib`. Any class inheriting `AudioPlugin` is registered. No restart required after adding a plugin file.

### Parameter system

```python
@dataclass
class Parameter:
    id: str
    label: str
    type: Literal["float", "int", "bool", "enum"]
    default: Any
    min: Any = None
    max: Any = None
    options: list[str] = None   # for enum
```

Parameters are read by the FastAPI layer and sent to the React UI, which renders them dynamically (slider for float/int, toggle for bool, dropdown for enum). Adding a new parameter to a plugin requires no frontend changes.

---

## 7. Model Hub

### Model manifest

Every model has a `manifest.json`:

```json
{
  "id": "deepfilternet3",
  "name": "DeepFilterNet3 Noise Canceller",
  "version": "3.0.0",
  "plugin_class": "stfu.plugins.builtin.deepfilternet3.DeepFilterNet3Plugin",
  "source": "huggingface:rikorose/DeepFilterNet3",
  "file": "deepfilternet3.onnx",
  "preferred_format": {
    "sample_rate": 48000,
    "channels": 1,
    "chunk_samples": 960
  },
  "supported_backends": ["cpu", "directml", "cuda"],
  "size_mb": 6.2,
  "algorithmic_latency_ms": 40,
  "tags": ["noise-cancellation", "speech", "real-time"]
}
```

### Local storage

```
%APPDATA%\stfu\
└── models\
    ├── deepfilternet3\
    │   ├── manifest.json
    │   └── deepfilternet3.onnx
    └── <community-model>\
        ├── manifest.json
        └── model.onnx
```

### HuggingFace integration

Community models are discovered via HuggingFace model search filtered by tag `stfu-compatible`. Download via `huggingface_hub.hf_hub_download()`. The hub UI polls the FastAPI `/models/available` endpoint which queries HuggingFace.

### Publishing a community model

1. Export model to ONNX
2. Write `manifest.json`
3. Upload both to HuggingFace with tag `stfu-compatible`
4. (Optional) Publish `plugin.py` for custom parameters

---

## 8. Backend Selection

### ONNX Runtime execution providers

| Provider | pip package | Hardware |
|----------|-------------|----------|
| CPU | `onnxruntime` | Any CPU |
| DirectML | `onnxruntime-directml` | Any DirectX 12 GPU (AMD, NVIDIA, Intel) |
| CUDA | `onnxruntime-gpu` | NVIDIA (optional) |

DirectML is the default GPU path on Windows. It requires no vendor SDK installation and works on AMD, NVIDIA, and Intel Arc GPUs.

### Per-plugin device selection

Each plugin independently selects:
- Backend: CPU / DirectML / CUDA
- Device index: which GPU (for systems with multiple)

This allows, for example:
- NC on iGPU (GPU 1) while gaming on discrete GPU (GPU 0)
- Voice changer on NVIDIA, EQ on CPU

The UI exposes this per plugin card in Advanced mode.

---

## 9. Virtual Audio Device Strategy

### v1: Windows 11 APO + VB-Cable fallback

**Windows 11 (22H2+):** Register STFU as an Audio Processing Object (APO) on the physical microphone. The processed audio is what all apps see — no virtual device needed, no driver required.

**Windows 10 / older Windows 11:** Bundle VB-Cable installer (silent install via PowerShell during setup). STFU writes processed audio to VB-Cable Input; apps select "VB-Cable Output" as their microphone.

### v2: STFU Audio Device (WDM driver)

Goal: ship a fully open-source (MIT) WDM virtual audio driver as part of the STFU project — the first of its kind for this use case.

Based on Microsoft's `sysvad` WDK sample. Exposes:
- "STFU Virtual Microphone" — capture device
- "STFU Virtual Speaker" — render device

Distribution signing path:
1. **Development / open-source contributors:** `bcdedit /set testsigning on`
2. **Release builds:** EV Code Signing Certificate (Sectigo ~$200-300/year, one cert covers all STFU drivers)
3. **Long-term:** Microsoft WHQL certification (free, 2-6 weeks)

One EV certificate covers OpenWinBlue's A2DP driver and STFU Audio Device simultaneously.

---

## 10. FastAPI Service API

```
GET  /status                    → service health, current latency
GET  /devices                   → enumerate audio devices (WASAPI)
POST /pipeline/mic              → configure mic plugin chain
POST /pipeline/speaker          → configure speaker plugin chain
GET  /models                    → list installed models
POST /models/install            → install from hub or local path
DELETE /models/{id}             → uninstall
GET  /plugins                   → list available plugin classes
POST /plugins/{id}/config       → update plugin parameters
GET  /backends                  → list available ONNX providers + devices
WS   /ws/metering               → real-time audio levels + CPU/GPU stats
```

---

## 11. UI

### Modes

**Simple** — Toggle per pipeline (mic / speaker), intensity slider, device selector, total latency display. Target: gamers, streamers.

**Advanced** — Draggable plugin chain per pipeline. Each plugin card shows parameters, backend/device selector, latency contribution bar. Target: creators, podcasters.

**Hub** — Browse, install, and manage models. Shows installed models and HuggingFace community models. Supports local ONNX import. Target: power users.

### System tray

- Ícono de estado: verde (activo), rojo (error), gris (pausado)
- Right-click: quick toggle mic / speaker, open UI
- App closes to tray, service keeps running

### Tech stack

- Tauri 2 (Rust shell + system tray)
- React 19 + TypeScript
- TanStack Query (API state management)
- Tailwind CSS
- WebSocket for real-time metering (audio levels, latency, GPU usage)

---

## 12. Project Structure

```
stfu/
├── backend/
│   ├── stfu/
│   │   ├── core/
│   │   │   ├── pipeline.py         # Pipeline + compilation
│   │   │   ├── audio_format.py     # AudioFormat dataclass
│   │   │   └── adapter.py          # Resamplers, rechunking, channel conversion
│   │   ├── plugins/
│   │   │   ├── base.py             # AudioPlugin + Parameter
│   │   │   ├── generic_onnx.py     # GenericONNXPlugin
│   │   │   └── builtin/
│   │   │       ├── deepfilternet3.py
│   │   │       ├── eq_parametric.py
│   │   │       └── gain.py
│   │   ├── hub/
│   │   │   ├── manager.py          # Download, install, remove models
│   │   │   └── registry.py         # Local model index
│   │   ├── audio/
│   │   │   ├── capture.py          # WASAPI capture thread
│   │   │   ├── playback.py         # WASAPI playback thread
│   │   │   └── devices.py          # Device enumeration
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── pipeline.py
│   │   │   │   ├── models.py
│   │   │   │   └── devices.py
│   │   │   └── ws.py               # WebSocket metering
│   │   └── main.py                 # FastAPI app entrypoint
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Simple.tsx
│   │   │   ├── Advanced.tsx
│   │   │   └── Hub.tsx
│   │   ├── components/
│   │   │   ├── PluginCard.tsx
│   │   │   ├── LevelMeter.tsx
│   │   │   ├── BackendSelector.tsx
│   │   │   └── LatencyBudget.tsx
│   │   └── services/
│   └── src-tauri/
├── driver/                         # STFU Audio Device (v2)
│   └── stfu_audio/
├── docs/
│   └── superpowers/specs/
│       └── 2026-06-19-stfu-design.md
└── scripts/
    ├── build.ps1
    └── setup.ps1
```

---

## 13. Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `sounddevice` | ≥0.5 | WASAPI audio I/O |
| `onnxruntime-directml` | ≥1.20 | DirectML inference (AMD/Intel/NVIDIA) |
| `onnxruntime` | ≥1.20 | CPU inference fallback |
| `numpy` | ≥1.26 | Audio buffer handling |
| `scipy` | ≥1.13 | High-quality resampling |
| `fastapi` | ≥0.115 | REST API + WebSocket |
| `huggingface_hub` | ≥0.24 | Model downloads |
| `uvicorn` | ≥0.30 | ASGI server |

---

## 14. Research Findings Summary

From 103-agent deep research (2026-06-19):

- **DeepFilterNet3** (arXiv 2305.08227, Interspeech 2023): RTF 0.19 on single CPU thread, 40ms algorithmic latency at 48kHz, PESQ 3.17. Best confirmed noise cancellation model for CPU-viable real-time use. Written in Rust with Python/ONNX bindings.
- **StreamVC** (arXiv 2401.03078, ICASSP 2024): 70.8ms end-to-end on CPU. Viable path for future real-time voice conversion without GPU.
- **Seed-VC** (GitHub Plachtaa/seed-vc): 25M–200M param family. Real-time path (430ms) requires RTX 3060+. Zero-shot voice cloning capability for v2.
- **SynthVC** (arXiv 2510.09245, Oct 2025): Eliminates ASR at inference, 14.7M params base. Promising direction for CPU-viable voice conversion.
- **VCClient** (w-okada/voice-changer): Reference implementation for full voice conversion pipeline. Two-mode architecture (browser-mediated vs WASAPI-direct) validates our thread model.
- **ONNX Runtime DirectML**: Confirmed viable for Windows multi-GPU audio inference via `onnxruntime-directml`.

---

*Spec reviewed and approved by user — 2026-06-19*
