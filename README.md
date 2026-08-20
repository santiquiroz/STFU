# STFU — Suppress The Frustrating Unwanted noise

> Open-source, real-time AI noise cancellation for Windows — bidirectional, running on **any GPU (AMD, NVIDIA, Intel) or plain CPU**, with a swappable hub of speech-enhancement models. No RTX card, no subscription, no black box.

---

## Why STFU?

Every existing option makes you give something up:

| Tool | Runs on | Cost | Open? | Catch |
|---|---|---|---|---|
| **NVIDIA Broadcast** | RTX GPUs only | free | no | needs an RTX card; reported lag/artifacts on some setups |
| **Krisp** | any (CPU) | **$96/yr** (was $60) | no | recurring cost; **auto-disables itself** when your CPU spikes |
| **AMD Noise Suppression** | recent Radeon only | free | no | hardware-gated, quality behind Broadcast, effectively unmaintained |
| **NoiseTorch** | **Linux only** | free | yes | not available on Windows |
| **Equalizer APO + RNNoise** | any | free | yes | no UI, old single model, manual setup |
| **STFU** | **any GPU or CPU** | **free** | **yes** | unsigned APO needs one registry flag (documented below) |

STFU gives you:

- **Any hardware** — inference runs through ONNX Runtime. CPU works on every machine (the default models hit ~0.03–0.10 real-time factor on a plain CPU — 10–30× faster than real time); DirectML uses any DX12 GPU (AMD/NVIDIA/Intel) when you want it. NPU support is scaffolded for a future release.
- **Any microphone, any format** — 44.1kHz, 48kHz, 192kHz, mono or stereo: the pipeline adapts automatically at every layer. Format never gates device recognition.
- **Never silently gives up** — under sustained CPU pressure STFU **degrades to a lighter model instead of switching cancellation off**. The opposite of Krisp's auto-disable.
- **Swappable models from a hub** — a curated catalog of speech-enhancement models you download on demand (verified by SHA-256), switchable live without restarting the stream.
- **No virtual devices, no third-party drivers** — noise cancellation runs *inside* the Windows audio engine (APO). Apps keep using your real microphone and speakers; they just receive clean audio.
- **Full control** — open source end to end, from the C++ APO to the Python DSP pipeline.

---

## Status

### Working today (v1.7 — Voice Studio)
- [x] Mic noise cancellation — WASAPI monitor path + **STFU APO** (C++ COM DLL running inside `audiodg.exe`), bridge to the Python engine verified end-to-end
- [x] **ONNX Runtime inference** with streaming state (real frame-by-frame context, no offline-API hacks)
- [x] **Any-device runtime**: `auto | cpu | gpu` selection with a probe + explicit fallback (NaN-guarded); NPU (`npu`) scaffolded for the runtime-pack work
- [x] **Model hub with UI**: curated catalog, browse/download/activate/delete straight from the app, verified SHA-256, and **live model swap** (no stream restart)
- [x] **Voice Studio** (tab "Estudio"): visual DSP chain editor, live spectrum visualizer, dB reduction meter, scene presets (Gaming / Reunión / Streaming / Podcast / Música / Accesibilidad), A/B bypass (spacebar), and Music Mode
- [x] **OS-wide global hotkeys** (`tauri-plugin-global-shortcut`): `Ctrl+Alt+M` toggles A/B bypass and `Ctrl+Alt+N` toggles Music Mode, both working even when STFU isn't the focused window (the spacebar A/B toggle still requires focus, for in-window use)
- [x] **APO auto-repair**: health-check + automatic repair of the APO registration — recovers from Windows 11 24H2 cumulative updates deactivating the APO, and from ghost endpoints, without manual re-registration
- [x] **Anti-overload auto-degrade**: drops to a lighter tier under sustained pressure, never disables NC
- [x] Format-proof audio engine: WASAPI auto-convert (any device rate), stateful resampling (soxr), clock-drift servo between devices
- [x] Per-stage telemetry (EMA + p95 latency per plugin) on `/status` and `/ws/metering`
- [x] Real-time pipeline in a worker thread; a plugin crash degrades to passthrough instead of killing audio
- [x] System tray app (Tauri) that spawns/supervises the backend; NSIS installer; rotating file logs at every layer

### In progress / next
- [ ] Larger curated model lineup once a spectrogram (STFT) front-end lands — quality tier, 48kHz, unlocks GTCRN / DPDFNet-class models
- [ ] Monitor Mode
- [ ] Studio Voice
- [ ] Live captions
- [ ] Per-app capture
- [ ] Community model hub
- [ ] NPU runtime packs (Qualcomm QNN / Intel OpenVINO) — deferred, no compatible model yet
- [ ] `STFU Microphone` virtual device (v2 — per-app routing, requires an EV-signed kernel driver) — **paused** by explicit decision; compiled and test-signed, never installed on a real machine

---

## Models

STFU ships **no model weights in the installer** — you pick from the hub and download on demand. Each model declares its own format and tensor IO in a manifest; the pipeline inserts the converters automatically, so a 16kHz model and a 48kHz model both "just work" against any mic.

Current curated lineup (real, waveform-in / waveform-out, verified end-to-end):

| Tier | Model | Params | Rate | License | Source |
|---|---|---|---|---|---|
| floor | FastEnhancer Tiny | ~22K | 16 kHz | MIT | GitHub release (`aask1357/fastenhancer`) |
| quality | FastEnhancer Base | ~91K | 48 kHz | MIT | GitHub release (`aask1357/fastenhancer`) |

> **Why only FastEnhancer today?** The other researched candidates (GTCRN and the DPDFNet family via sherpa-onnx) turned out to require a **complex-spectrogram front-end** — they take STFT features, not raw audio. STFU's streaming plugin is waveform-in/waveform-out, so those are gated behind future front-end work. FastEnhancer is genuinely waveform-native, MIT-licensed, ships ONNX, and covers both the floor (16k) and quality (48k) tiers. More models land as the front-end grows.

**Adding a model to the hub:** publish an ONNX speech-enhancement model tagged `audio-to-audio` + `speech-enhancement` on Hugging Face, then contribute a manifest (id, tier, license, tensor `io_spec`, SHA-256) under `backend/stfu/hub/curated/`. Use `backend/scripts/inspect_onnx.py <path-or-url>` to dump the exact tensor names/shapes and hash you need.

---

## How it works

**No virtual cables. No kernel driver.** STFU registers a user-mode APO (Audio Processing Object) on your existing audio endpoint — the same mechanism sound-card vendors use. Windows' audio engine (`audiodg.exe`) calls it inline for every audio block:

```
[Physical Mic] ──► Windows audio engine ──► [STFU APO (MFX)] ──► Discord / Zoom / OBS
                        (does all SRC)            │  ▲               (clean audio on
                                                  ▼  │                the REAL mic)
                                            named-pipe bridge
                                                  │  ▲
                              [STFU service: ONNX model → EQ → … in a worker thread]

[Apps playing audio] ──► engine ──► [STFU APO (SFX)] ──► Speakers / Headphones
```

- The Windows engine hands the APO float32 audio at the endpoint's mix format and performs **all sample-rate conversion** — a 192kHz mic and a 44.1kHz headset just work.
- Inference runs in a **worker thread**, never in the real-time audio callback. The model keeps recurrent state across chunks for true streaming context.
- If the STFU service isn't running, the APO passes audio through untouched — your audio never breaks. If a model produces a bad frame (NaN), that frame falls back to dry audio instead of reaching your speakers.

Known limits of the APO tier (accepted, documented): exclusive-mode/ASIO apps bypass APOs; unsigned APOs require `DisableProtectedAudioDG=1` (same as Equalizer APO); reinstalling an audio driver wipes the registration. Windows 11 24H2 can silently deactivate APOs after a cumulative update — STFU's health-check detects this and **auto-repairs the registration** (`POST /apo/repair`), no manual re-registration needed.

---

## Why ONNX Runtime, and where DirectML fits

These are not competing choices — they're layers of one stack:

1. **The model** (`.onnx`) — the portable neural-network graph.
2. **ONNX Runtime** — the engine that executes that graph (the library the backend imports).
3. **Execution Provider (EP)** — the backend that maps operations onto real hardware: `CPUExecutionProvider` (any CPU), `DmlExecutionProvider` = **DirectML** (any DX12 GPU: AMD/NVIDIA/Intel), and vendor NPU providers (Qualcomm/Intel).

So STFU *does* use DirectML — as the GPU execution provider inside ONNX Runtime. CPU is the default because the current models are small enough to run comfortably there; GPU is opt-in via the device selector.

**On NPUs:** unlike GPUs (all of which speak DirectX 12, so one EP covers them), every NPU has its own proprietary stack (Qualcomm QNN, Intel OpenVINO, AMD VitisAI), each shipping an *incompatible* ONNX Runtime build. That's why NPU support requires per-vendor "runtime packs" and is deferred. Microsoft's **Windows ML** is the eventual answer — it lets the OS manage EPs (any GPU or NPU, evergreen) behind the same ONNX Runtime API; STFU isolates all runtime knowledge in one module (`ep_router`) so migrating to it later touches nothing else.

---

## For testers

Installer (`STFU_x64-setup.exe`) is published on **GitHub Releases**. It bundles the UI and the backend — no Python, no dependencies.

1. Run the installer.
2. Launch STFU (lives in the system tray; closing the window keeps audio running).
3. Toggle **Micrófono** and talk. Download a model from the hub if prompted.

**When something fails, attach these logs:**

| Log | Path |
|---|---|
| Backend (devices, formats, pipeline) | `%USERPROFILE%\.stfu\logs\backend.log` |
| UI shell (backend spawn, errors) | `%LOCALAPPDATA%\com.stfu.desktop\logs\stfu-ui.log` |
| APO (inside audiodg) | `DebugView` (Sysinternals) — filter `[STFU-APO]` |

The first lines of `backend.log` contain an environment report (Windows version, every audio device with its native rate) — include them always.

---

## Build from source

```powershell
# Backend (Python 3.11+)
cd backend
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt          # ONNX Runtime + DirectML, no torch
uvicorn stfu.main:app --port 8765
pytest                                    # 175+ tests

# Optional legacy DeepFilterNet3 (torch, ~500MB) — not needed for the ONNX lineup
pip install -r requirements-torch.txt

# Frontend (Node 20+, Rust stable-msvc)
cd frontend
npm install
npm run tauri dev                         # spawns the backend automatically

# APO (VS Build Tools + Windows SDK)
cd apo
./build.ps1 -TestHarness                  # → build/stfu_apo.dll + test_pipe.exe

# Installer
cd backend
.\.venv\Scripts\pyinstaller.exe stfu-backend.spec   # torch-excluded → ~100MB
cd ..\frontend
npm run tauri build                       # → src-tauri/target/release/bundle/nsis/*.exe
```

> On machines with VS Community *and* Build Tools, run `cargo`/`tauri build` from a *Developer Command Prompt* of Build Tools (Community may lack VC libs).

### Handy scripts

- `backend/scripts/inspect_onnx.py <path-or-url>` — dump a model's tensor IO + SHA-256 (for writing a curated manifest)
- `backend/scripts/ab_models.py <noisy.wav>` — run every installed model over a WAV and report real-time factor, to compare quality/speed before picking a default

---

## Architecture

```
stfu/
├── backend/           # Python service (FastAPI :8765 + audio pipeline)
│   └── stfu/
│       ├── core/      # Pipeline engine, FormatAdapter (soxr), telemetry, pipeline_factory
│       ├── inference/ # ep_router — device ladder (auto/cpu/gpu/npu) + probe/fallback
│       ├── plugins/   # AudioPlugin ABC + OnnxStreamingPlugin, EQ RBJ, Gain, (legacy DFN3)
│       ├── audio/     # WASAPI capture, drift servo, worker, degrade_monitor
│       ├── apo/       # APO registration, named-pipe bridge, ApoEngine
│       ├── hub/       # curated manifests, SHA-256 download, model registry
│       └── api/       # REST + WebSocket
├── apo/               # STFU APO — C++ COM DLL (user-mode, audiodg.exe)
├── frontend/          # Tauri 2 (tray, backend spawn) + React 19
└── docs/              # design spec, plans, audits
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Audio interception | **STFU APO** (user-mode COM DLL in audiodg) — no drivers, no virtual cables |
| Audio I/O (direct mode) | `sounddevice` + WASAPI shared w/ AUTOCONVERTPCM |
| Resampling | soxr (stateful streaming) + libsamplerate (drift servo, variable ratio) |
| AI inference | ONNX Runtime — CPU default, DirectML (any GPU) opt-in, NPU scaffolded |
| Models | FastEnhancer (MIT) hub; DeepFilterNet3 legacy behind a torch extra |
| API | FastAPI + WebSocket |
| UI shell | Tauri 2 (Rust) — tray, sidecar, logs |
| Frontend | React 19 + TypeScript + TanStack Query |
| Installer | Tauri bundler → NSIS |

---

## Contributing

Contributions welcome — models (see "Adding a model" above), DSP plugins, the spectrogram front-end that unlocks more of the model zoo, NPU runtime packs, UI.

---

## License

MIT — use it, fork it, build on it.

---

<p align="center">
  Built because silence should be a choice, not a hardware requirement.
</p>
