# STFU — Design Specification
**Date:** 2026-06-19 (revised 2026-06-20)
**Status:** Approved
**Scope:** v1 MVP — Bidirectional noise cancellation, Windows

---

## 1. Problem Statement

NVIDIA Broadcast requires an RTX GPU. AMD Noise Suppression is a single closed-source model. Both are black boxes with no customization, no model choice, and no support for hardware outside their vendor's ecosystem.

STFU is an open-source alternative that runs on any Windows GPU or CPU via DirectML, supports community models via HuggingFace, and is built on a generic plugin pipeline that does not assume any specific model format or audio configuration.

**Why no VB-Cable:** VB-Cable is proprietary. The free tier limits bandwidth and channels. STFU ships entirely open-source — zero third-party proprietary dependencies. The speaker NC problem (intercepting system audio before it reaches headphones) is solved via Windows APO for v1 and a full WDM virtual device for v2.

---

## 2. Goals (v1 MVP)

- Bidirectional noise cancellation (microphone + speakers), independently configurable
- Run on CPU or any DirectX 12 GPU (AMD, NVIDIA, Intel) via ONNX Runtime + DirectML
- Per-plugin processor selection — user chooses which device runs each effect
- Built-in model: DeepFilterNet3 (40ms algorithmic latency, CPU viable)
- System tray app for Windows 11 (Windows 10 compatible)
- Simple UI (toggle + slider) and Advanced UI (plugin chain editor)
- Zero proprietary dependencies — all components MIT/Apache/BSD licensed

## 3. Non-Goals (v1)

- Cross-platform support (Linux, macOS deferred)
- Voice cloning or real-time voice conversion (v2)
- Music source separation (v2)
- Per-app audio routing / WDM virtual audio device (v2 — see Section 9)
- VST/CLAP plugin format (v3)

---

## 4. Architecture Overview

Three independent processes with clear boundaries:

```
[Physical Mic]
     │  WASAPI shared mode (sounddevice)
     ▼
[STFU APO (MFX)]   ← COM DLL in Windows audio engine (audiodg.exe)
     │  Named pipe → Python service → DeepFilterNet3 → named pipe
     ▼
[Clean audio] → [Discord / OBS / Zoom] (use physical mic, see clean audio)

[Apps playing audio]
     │
     ▼
[Windows audio engine]
     │
[STFU APO (SFX)]   ← same COM DLL, registered on output endpoint
     │  Named pipe → Python service → DeepFilterNet3 → named pipe
     ▼
[Physical Speaker / Headphones]

[Tauri + React UI] ← thin shell, talks to Python service via HTTP
[Python Audio Service] ← FastAPI + pipeline + APO named pipe server
```

**APO (Audio Processing Object):** A user-mode COM DLL that Windows audio engine (audiodg.exe) loads inline. The engine calls the APO on every audio block — no separate thread, no virtual device. When STFU APO is registered on the Blue Snowball endpoint, Zoom capturing from Blue Snowball automatically receives STFU-processed audio. When registered on the FiiO Q output endpoint, all audio played through it is NC'd before reaching headphones.

**Python Audio Service** owns all audio processing. It starts as a background process on login, exposes a local FastAPI server (HTTP for control) and a named pipe server (real-time audio for APO). The Tauri UI is a thin shell.

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
Thread 1: APO pipe server    → ring_buffer_apo_mic  (audio from Windows audio engine)
Thread 2: Pipeline mic       → ring_buffer_apo_mic → DeepFilterNet3 → ring_buffer_out_mic
Thread 3: APO pipe response  → ring_buffer_out_mic → reply to APO
Thread 4: APO pipe server    → ring_buffer_apo_spk  (audio from speaker APO)
Thread 5: Pipeline speaker   → ring_buffer_apo_spk → DeepFilterNet3 → ring_buffer_out_spk
Thread 6: APO pipe response  → ring_buffer_out_spk → reply to APO
Thread 7: FastAPI server     (async)
Thread 8: [Testing only] WASAPI direct capture → pipeline → headphones (no APO)
```

ONNX Runtime releases the Python GIL during C++ inference — threads do not block each other.

### Latency budget example (APO path)

```
Windows audio engine buffers: 10ms
Named pipe round-trip:         2ms
DeepFilterNet3:               40ms  (algorithmic, fixed)
Total:                        52ms
```

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

Scanned at service startup with `importlib`. Any class inheriting `AudioPlugin` is registered.

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

Parameters are read by the FastAPI layer and sent to the React UI, which renders them dynamically.

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

Community models are discovered via HuggingFace model search filtered by tag `stfu-compatible`. Download via `huggingface_hub.hf_hub_download()`.

---

## 8. Backend Selection

### ONNX Runtime execution providers

| Provider | pip package | Hardware |
|----------|-------------|----------|
| CPU | `onnxruntime` | Any CPU |
| DirectML | `onnxruntime-directml` | Any DirectX 12 GPU (AMD, NVIDIA, Intel) |
| CUDA | `onnxruntime-gpu` | NVIDIA (optional) |

### Per-plugin device selection

Each plugin independently selects backend and device index.

---

## 9. Virtual Audio Device Strategy

### Why VB-Cable was in the original plan — and why it's gone

**The routing problem:** Windows does not allow an app to intercept audio from another app and re-inject it to the same device in shared mode. For speaker NC to work, the audio flow must be broken in two:

```
App → [intercept point] → STFU → Physical Speakers
```

VB-Cable creates that intercept point as a proprietary kernel driver (virtual device). STFU replaces this with two open-source alternatives:

---

### v1: STFU APO — Audio Processing Object (user mode, no kernel driver)

An APO is a COM DLL that Windows loads **inside the audio engine process (audiodg.exe)**. The audio engine calls the APO synchronously on every audio block, before the audio reaches the application (for capture) or before it leaves to hardware (for render).

**Why APO is better than VB-Cable for our use case:**
- User mode — no kernel driver, no Windows signing headache, no reboot required
- Transparent — Zoom selecting "Blue Snowball" automatically gets clean audio; user doesn't reconfigure apps
- Applies to ALL apps simultaneously — not per-app
- Works on Windows 10 and 11

**What STFU APO is NOT:**
- Not a virtual device (doesn't appear as "STFU Virtual Mic" in device list)
- Not per-app (all apps on the same endpoint get the same processing)

**Architecture:**

```
Windows audio engine (audiodg.exe)
  → loads stfu_apo.dll via COM
  → calls APO on each 10ms block

stfu_apo.dll (C++, ~800 lines)
  ├── implements IAudioSystemEffects3 (Windows 11) / IAudioSystemEffects2 (Win10)
  ├── implements IAudioProcessingObjectRT (realtime audio processing)
  └── named pipe client → \\.\pipe\stfu_apo_mic (or stfu_apo_spk)

Python service (stfu/apo/)
  └── named pipe server \\.\pipe\stfu_apo_mic
      ├── receives float32 audio blocks from APO
      ├── runs DeepFilterNet3 pipeline
      └── writes processed audio back to APO
```

**Registration (Python setup code):**
```python
# stfu/apo/register.py
import winreg, subprocess

def register_apo_on_endpoint(endpoint_guid: str, apo_clsid: str, role: str):
    """
    role: "MFX_CAPTURE" (microphone) or "SFX_RENDER" (speaker)
    Writes to HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\...
    """
    # 1. Register COM class
    subprocess.run(["regsvr32", "/s", str(APO_DLL_PATH)])
    # 2. Write FxProperties to endpoint registry key
    key_path = f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\{role}\\{{{endpoint_guid}}}\\FxProperties"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, access=winreg.KEY_SET_VALUE) as k:
        # {d04e05a6-594b-4fb6-a80d-01af5eed7d1d},6 = MFX GUID
        winreg.SetValueEx(k, "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},6", 0, winreg.REG_SZ, apo_clsid)
    # 3. Cycle audio engine to pick up new APO
    subprocess.run(["net", "stop", "audiosrv"], check=False)
    subprocess.run(["net", "start", "audiosrv"], check=False)
```

**Limitations:**
- Requires admin rights for registration (one-time setup)
- APO is re-registered when user changes default audio device
- Named pipe adds ~2ms latency (acceptable)

---

### v2: STFU Virtual Audio Device (WDM kernel driver)

For advanced use cases:
- Per-app routing ("process Discord but not Spotify")
- "STFU Virtual Mic" appears as a selectable device in Zoom/Discord/OBS
- Multiple virtual endpoints with independent processing chains

**Technology stack:**
- Windows Driver Kit (WDK) latest + Visual Studio 2022
- PortCls / WaveRT miniport
- Based on Microsoft's `sysvad` sample (in `microsoft/Windows-driver-samples`)
- Reference: Synchronous Audio Router (SAR) — MIT, `amurzeau/SynchronousAudioRouter`

**Exposes:**
- "STFU Virtual Microphone" — capture endpoint, STFU Python writes NC'd audio
- "STFU Virtual Speaker" — render endpoint, STFU Python reads and processes

**Communication: shared memory + kernel events**
```c
// Kernel driver creates:
\BaseNamedObjects\STFU_MicBridge    // HANDLE to shared memory section
\BaseNamedObjects\STFU_MicReady     // kernel event: new audio available
\BaseNamedObjects\STFU_MicConsumed  // kernel event: processed audio ready
```

Python service maps shared memory via `ctypes.windll.kernel32.OpenFileMappingW`.

**Signing:**
- Dev: `bcdedit /set testsigning on`
- Release: EV Code Signing Certificate (Sectigo ~$200-300/year)
- Long-term: WHQL certification (free, 2-6 weeks)

One EV certificate covers both STFU Audio Device and OpenWinBlue A2DP simultaneously.

---

## 10. FastAPI Service API

```
GET  /status                    → service health, current latency, APO status
GET  /devices                   → enumerate audio devices (WASAPI)
POST /pipeline/mic              → configure mic plugin chain
POST /pipeline/speaker          → configure speaker plugin chain
POST /pipeline/mic/stop         → stop mic pipeline
POST /pipeline/speaker/stop     → stop speaker pipeline
GET  /apo/status                → APO registration status per endpoint
POST /apo/register              → register STFU APO on endpoint (requires admin)
POST /apo/unregister            → unregister STFU APO from endpoint
GET  /models                    → list installed models
POST /models/install            → install from hub or local path
DELETE /models/{id}             → uninstall
GET  /plugins                   → list available plugin classes
GET  /backends                  → list available ONNX providers + devices
WS   /ws/metering               → real-time audio levels + CPU/GPU stats
```

---

## 11. UI

### Modes

**Simple** — Toggle per pipeline (mic / speaker), intensity slider, device selector, total latency display.

**Advanced** — Draggable plugin chain per pipeline. Each plugin card shows parameters, backend/device selector, latency contribution bar.

**Hub** — Browse, install, and manage models.

### Simple UI behavior for speaker toggle

Before APO is registered:
- Speaker toggle shows "Requiere configuración inicial → [Configurar]" button
- Clicking Configure calls `POST /apo/register` (requires admin, shows UAC prompt)
- After registration, speaker toggle enables NC inline on the selected output device

### System tray

- Ícono de estado: verde (activo), rojo (error), gris (pausado)
- Right-click: quick toggle mic / speaker, open UI
- App closes to tray, service keeps running

### Tech stack

- Tauri 2 (Rust shell + system tray)
- React 19 + TypeScript
- TanStack Query (API state management)
- Tailwind CSS
- WebSocket for real-time metering

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
│   │   │   ├── engine.py           # AudioEngine singleton
│   │   │   ├── capture.py          # WASAPI capture+playback thread (test mode)
│   │   │   └── devices.py          # Device enumeration (WASAPI-only filter)
│   │   ├── apo/
│   │   │   ├── pipe_server.py      # Named pipe server (receives audio from APO DLL)
│   │   │   ├── register.py         # APO registration in Windows registry
│   │   │   └── endpoint_finder.py  # Enumerate endpoints + find GUID
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── pipeline.py
│   │   │   │   ├── apo.py          # APO register/unregister/status
│   │   │   │   ├── models.py
│   │   │   │   └── devices.py
│   │   │   └── ws.py               # WebSocket metering
│   │   └── main.py                 # FastAPI app entrypoint
│   └── requirements.txt
├── apo/                            # STFU APO — C++ COM DLL (user mode)
│   ├── src/
│   │   ├── stfu_apo.cpp            # COM DLL entry + class factory
│   │   ├── stfu_apo_mfx.cpp        # MFX APO (capture/mic processing)
│   │   ├── stfu_apo_sfx.cpp        # SFX APO (render/speaker processing)
│   │   ├── pipe_client.cpp         # Named pipe client to Python service
│   │   └── stfu_apo.def            # Exports
│   ├── include/
│   │   ├── stfu_apo.h
│   │   └── pipe_client.h
│   └── CMakeLists.txt              # Build: cl.exe, MSVC, Windows SDK only
├── driver/                         # STFU Virtual Audio Device (v2, WDM)
│   └── stfu_audio/                 # Kernel driver (PortCls/WaveRT)
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Simple.tsx
│   │   │   ├── Advanced.tsx
│   │   │   └── Hub.tsx
│   │   ├── components/
│   │   └── services/
│   └── src-tauri/
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
| `sounddevice` | ≥0.5 | WASAPI audio I/O (test mode + device enumeration) |
| `onnxruntime-directml` | ≥1.20 | DirectML inference (AMD/Intel/NVIDIA) |
| `onnxruntime` | ≥1.20 | CPU inference fallback |
| `numpy` | ≥1.26 | Audio buffer handling |
| `scipy` | ≥1.13 | High-quality resampling |
| `fastapi` | ≥0.115 | REST API + WebSocket |
| `huggingface_hub` | ≥0.24 | Model downloads |
| `uvicorn` | ≥0.30 | ASGI server |
| `pywin32` | ≥308 | Windows registry access for APO registration |

**C++ (APO DLL):** Windows SDK only (audiomediatype.h, audioenginebaseapo.h). No WDK required.

---

## 14. Development Roadmap

### v1.0 (current sprint): Core pipeline + test mode
- WASAPI capture → DeepFilterNet3 → WASAPI playback (mic → headphones, for testing)
- Fix WASAPI format compatibility (stereo capture, native output rate)
- Frontend Simple UI with mic toggle

### v1.1: STFU APO (open-source speaker NC, production mic NC)
- `apo/` C++ COM DLL (MFX + SFX APOs, ~800 lines C++)
- `backend/stfu/apo/` Python named pipe server + registry registration
- Backend `POST /apo/register` endpoint
- Frontend: speaker toggle calls register if needed, then enables pipeline
- One-time admin UAC prompt for registration

### v1.2: WASAPI direct mode improvements
- Auto-restart on device change
- Latency optimization

### v2.0: STFU Virtual Audio Device (WDM kernel driver)
- Virtual capture + render endpoints
- Per-app routing
- WHQL certification path

---

## 15. STFU APO — Implementation Details

### COM DLL structure

`stfu_apo.dll` exports three functions (`stfu_apo.def`):
```
EXPORTS
    DllGetClassObject
    DllCanUnloadNow
    DllRegisterServer    ; called by regsvr32
    DllUnregisterServer
```

### MFX APO class (capture endpoint — mic NC)

```cpp
class CSTFUApoMfx :
    public IAudioSystemEffects3,       // Windows 11 (falls back to IAudioSystemEffects2 on Win10)
    public IAudioProcessingObject,
    public IAudioProcessingObjectRT,   // realtime audio processing
    public IAudioProcessingObjectConfiguration
{
    HRESULT STDMETHODCALLTYPE APOProcess(
        UINT32 u32NumInputConnections,
        APO_CONNECTION_PROPERTY** ppInputConnections,
        UINT32 u32NumOutputConnections,
        APO_CONNECTION_PROPERTY** ppOutputConnections) override
    {
        // 1. Extract float32 block from ppInputConnections[0]
        // 2. Write to named pipe \\.\pipe\stfu_apo_mic
        // 3. Read processed float32 block from named pipe
        // 4. Write to ppOutputConnections[0]
    }
};
```

### Named pipe protocol (binary, fixed-size frames)

```c
// Request: APO → Python
typedef struct {
    uint32_t frame_id;          // monotonic counter
    uint32_t sample_rate;       // e.g. 48000
    uint32_t channels;          // e.g. 2
    uint32_t num_samples;       // e.g. 480 (10ms @ 48kHz)
    float    samples[];         // num_samples * channels float32
} STFUApoRequest;

// Response: Python → APO
typedef struct {
    uint32_t frame_id;          // must match request
    uint32_t num_samples;
    float    samples[];         // processed audio, same layout
} STFUApoResponse;
```

Pipe mode: `PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE` (message-based, not stream-based).

### Python pipe server (per-endpoint)

```python
# stfu/apo/pipe_server.py
class ApoPipeServer:
    def __init__(self, pipe_name: str, pipeline: Pipeline):
        self._pipe_name = pipe_name       # e.g. r"\\.\pipe\stfu_apo_mic"
        self._pipeline = pipeline

    def run(self):
        while True:
            pipe = win32pipe.CreateNamedPipe(
                self._pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                win32pipe.PIPE_UNLIMITED_INSTANCES, 65536, 65536, 0, None)
            win32pipe.ConnectNamedPipe(pipe, None)
            threading.Thread(target=self._handle_client, args=(pipe,)).start()

    def _handle_client(self, pipe):
        while True:
            data = win32file.ReadFile(pipe, 65536)[1]
            request = parse_request(data)
            audio = np.frombuffer(request.samples, dtype=np.float32).reshape(
                request.num_samples, request.channels)
            processed = self._pipeline.process(audio)
            win32file.WriteFile(pipe, build_response(request.frame_id, processed))
```

---

## 16. Research Findings Summary

From 103-agent deep research (2026-06-19):

- **DeepFilterNet3** (arXiv 2305.08227): RTF 0.19 on single CPU thread, 40ms algorithmic latency at 48kHz, PESQ 3.17. Best confirmed NC model for CPU-viable real-time use.
- **StreamVC** (arXiv 2401.03078): 70.8ms end-to-end on CPU. v2 path for voice conversion.
- **Seed-VC** (GitHub Plachtaa/seed-vc): 25M–200M params. Real-time requires RTX 3060+.
- **ONNX Runtime DirectML**: Confirmed viable for Windows multi-GPU audio inference.
- **Windows APO CAPX APIs**: Windows 11 build 22000+ provides IAudioSystemEffects3, AEC framework with automatic reference stream, Settings/Notifications/Threading frameworks. Windows 10 uses IAudioSystemEffects2.
- **Reference APO implementations**: `microsoft/Windows-driver-samples/audio/sysvad/APO/` (includes full AEC APO sample). Equalizer APO (open source, MIT) is a production APO proving the approach is sound.
- **SAR (Synchronous Audio Router)**: MIT license, `amurzeau/SynchronousAudioRouter` (active fork 2024). Kernel-mode WDM driver creating virtual endpoints synchronized to ASIO. Reference for v2 virtual device.

---

*Spec revised 2026-06-20 — VB-Cable removed, STFU APO (user-mode COM) introduced for v1.1, WDM virtual device deferred to v2*
