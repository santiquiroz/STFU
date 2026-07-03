# STFU — Suppress The Frustrating Unwanted noise

> Open-source AI audio processing for Windows — bidirectional noise cancellation, voice enhancement, and a community model hub that runs on **any GPU** (AMD, NVIDIA, Intel) or CPU.

---

## Why STFU?

NVIDIA Broadcast requires an RTX GPU. AMD Noise Suppression is a black box. Both give you one model, no customization, and zero transparency — and both install a virtual audio device with a fixed format list, so an "exotic" microphone (192kHz, weird channel layouts) may not even be recognized.

STFU gives you:

- **Any hardware** — DirectML runs on AMD, NVIDIA, and Intel GPUs. No CUDA required.
- **Any microphone, any format** — 44.1kHz, 48kHz, 192kHz, mono or stereo: the pipeline adapts automatically at every layer. Format never gates device recognition.
- **No virtual devices, no third-party drivers** — noise cancellation runs *inside* the Windows audio engine (APO). Apps keep using your real microphone and speakers; they just receive clean audio.
- **Any model** — each plugin declares its own format needs (sample rate, channels, chunk size); the pipeline inserts stateful converters automatically.
- **Full control** — open source end to end, from the C++ APO to the DSP pipeline.

---

## Status

### Working today (v1.1-dev)
- [x] Mic noise cancellation (DeepFilterNet3) — WASAPI monitor mode
- [x] Format-proof audio engine: WASAPI auto-convert (any device rate), stateful resampling (soxr), clock-drift servo between devices (CamillaDSP pattern)
- [x] Real-time pipeline in worker thread; RT callbacks only copy memory
- [x] Live parameter updates (no stream restart, no glitches)
- [x] **STFU APO** — C++ COM DLL that runs inside `audiodg.exe`; bridge to the Python engine verified end-to-end
- [x] Speaker NC path wired through the APO bridge
- [x] System tray app; UI shell spawns/supervises the backend
- [x] Rotating file logs at every layer (see [Logs](#logs))

### In progress
- [ ] NSIS installer for testers (GitHub Releases)
- [ ] First real-endpoint APO validation
- [ ] ONNX + DirectML inference (drops installer from ~500MB to ~100MB, enables any-GPU)

### Roadmap
- [ ] Community model hub — HuggingFace models with `stfu-compatible` tag
- [ ] Advanced UI (plugin chain editor) and Hub UI
- [ ] Voice changer, music enhancement
- [ ] `STFU Microphone` virtual device (v2 — only needed for per-app routing; requires EV-signed kernel driver)
- [ ] VST/CLAP plugin format

---

## How it works

**No virtual cables. No kernel driver.** STFU registers a user-mode APO (Audio Processing Object) on your existing audio endpoint — the same mechanism sound card vendors use. Windows' audio engine (`audiodg.exe`) calls it inline for every audio block:

```
[Physical Mic] ──► Windows audio engine ──► [STFU APO (MFX)] ──► Discord / Zoom / OBS
                        (does all SRC)            │  ▲               (see clean audio on
                                                  ▼  │                the REAL mic)
                                            named pipe bridge
                                                  │  ▲
                                     [STFU service: DeepFilterNet3 → EQ → …]

[Apps playing audio] ──► engine ──► [STFU APO (SFX)] ──► Speakers / Headphones
```

- The Windows engine hands the APO float32 audio at the endpoint's mix format and performs **all sample-rate conversion** — a 192kHz mic and a 44.1kHz headset just work.
- If the STFU service isn't running, the APO passes audio through untouched — your audio never breaks.
- Inside the service, each plugin declares its preferred format; `FormatAdapter` inserts stateful soxr resampling, channel conversion and rechunking automatically. A 16kHz voice model chains with a 48kHz stereo enhancer with zero configuration.

Known limits of the APO tier (accepted, documented): exclusive-mode/ASIO apps bypass APOs; unsigned APOs require `DisableProtectedAudioDG=1` (same as Equalizer APO); reinstalling an audio driver wipes the registration (re-register from the UI).

---

## For testers

Installer (`STFU_x64-setup.exe`) will be published on **GitHub Releases**. It bundles the UI and the backend — no Python, no dependencies.

1. Run the installer.
2. Launch STFU (lives in the system tray; closing the window keeps audio running).
3. Toggle **Micrófono** and talk.

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
pip install -r requirements.txt
uvicorn stfu.main:app --port 8765
pytest                     # 80+ tests

# Frontend (Node 20+, Rust stable-msvc)
cd frontend
npm install
npm run tauri dev          # spawns the backend automatically from the venv

# APO (VS Build Tools + Windows SDK)
cd apo
./build.ps1 -TestHarness   # → build/stfu_apo.dll + test_pipe.exe

# Installer
cd backend
.\.venv\Scripts\pyinstaller.exe ... run_backend.py   # see docs
cd ..\frontend
npm run tauri build        # → src-tauri/target/release/bundle/nsis/*.exe
```

> Note: on machines with VS Community *and* Build Tools, run `cargo`/`tauri build` from a *Developer Command Prompt* of Build Tools (Community may lack VC libs).

---

## Architecture

```
stfu/
├── backend/           # Python service (FastAPI :8765 + audio pipeline)
│   └── stfu/
│       ├── core/      # Pipeline engine, FormatAdapter (soxr), logging
│       ├── plugins/   # AudioPlugin ABC + DeepFilterNet3 / EQ RBJ / Gain
│       ├── audio/     # WASAPI capture (auto-convert), drift servo, transport
│       ├── apo/       # APO registration, named-pipe bridge, ApoEngine
│       ├── hub/       # Model download and registry
│       └── api/       # REST + WebSocket
├── apo/               # STFU APO — C++ COM DLL (user-mode, audiodg.exe)
├── frontend/          # Tauri 2 (tray, backend spawn) + React 19
└── docs/              # Design spec, plans, audits
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Audio interception | **STFU APO** (user-mode COM DLL in audiodg) — no drivers, no virtual cables |
| Audio I/O (direct mode) | `sounddevice` + WASAPI shared w/ AUTOCONVERTPCM |
| Resampling | soxr (stateful streaming) + libsamplerate (drift servo, variable ratio) |
| AI inference | DeepFilterNet3 (torch) → ONNX Runtime + DirectML (planned) |
| API | FastAPI + WebSocket |
| UI shell | Tauri 2 (Rust) — tray, sidecar, logs |
| Frontend | React 19 + TypeScript + TanStack Query |
| Installer | Tauri bundler → NSIS |

---

## Contributing

Contributions welcome — plugins, models, DSP, UI.

---

## License

MIT — use it, fork it, build on it.

---

<p align="center">
  Built because silence should be a choice, not a hardware requirement.
</p>
