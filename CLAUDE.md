# CLAUDE.md — STFU

Instrucciones de proyecto para asistentes AI (Claude, Copilot, etc.). Contexto de arquitectura y estado para retomar el trabajo sin perder hilo.

## Qué es STFU

App open-source de Windows: cancelación de ruido de micrófono con IA, corriendo en cualquier GPU (DirectML) o CPU. Meta: reemplazar NVIDIA Broadcast/Krisp sin requerir hardware específico, sin dependencias propietarias.

## Estado actual (v1.7): APO es el mecanismo shipped y mantenido

**El APO (Audio Processing Object) es el mecanismo de cancelación de ruido activo y en producción.** Registra un APO en modo usuario sobre el endpoint de audio existente (mismo mecanismo que usan los fabricantes de tarjetas de sonido); `audiodg.exe` lo invoca inline en cada bloque de audio. F3 agregó health-check + auto-repair: `health.py`, `repair_registrations()`, endpoint `POST /apo/repair` y `ApoHealthMonitor` detectan y reparan solos cuando Windows 11 24H2 desactiva el APO tras una actualización acumulativa.

**El driver de micrófono virtual "STFU Microphone" (v2) está PAUSADO por decisión explícita del usuario** — no es el foco activo. Está compilado y test-signed pero nunca se instaló en una máquina real. El plan histórico sigue en `docs/superpowers/plans/2026-07-03-v2-virtual-mic-driver.md` y los cambios de kernel en `driver/DRIVER-CHANGES.md`, por si se retoma en el futuro, pero no guían el trabajo actual.

## Superficie actual (v1.6 Voice Studio, shipped)

- Tab **Estudio**: editor de cadena DSP, visualizador de espectro en vivo, medidor de reducción de dB, presets de escena (Gaming/Reunión/Streaming/Podcast/Música/Accesibilidad), A/B bypass (barra espaciadora), Modo música.
- **Model-hub UI** (`Models.tsx`): descarga/activación/borrado de modelos ONNX curados por dispositivo.
- **APO health/auto-repair** (ver arriba).

## Layout del repo

| Ruta | Qué es |
|---|---|
| `backend/stfu/core/` | Pipeline, FormatAdapter (soxr), logging |
| `backend/stfu/plugins/builtin/` | DeepFilterNet3 (ventana deslizante), EQ RBJ, Gain |
| `backend/stfu/audio/` | Captura WASAPI (auto_convert), transport (RingBuffer + DriftServo), engine, devices |
| `backend/stfu/api/routes/feeder.py` | Feeder — mic físico → plugin de cancelación → STFU Audio Bridge (ruta de prueba ligada al driver v2, pausado) |
| `backend/stfu/apo/` | **Mecanismo shipped y mantenido** — registro del APO, puente named-pipe, `ApoEngine`, health-check + auto-repair (`health.py`, `repair_registrations()`, `POST /apo/repair`, `ApoHealthMonitor`) |
| `driver/` | **Driver v2 — PAUSADO** (decisión explícita del usuario, no es el foco activo). Compilado y test-signed, nunca instalado en máquina real. Fork de VirtualDrivers/Virtual-Audio-Driver + RingBuffer de AudioMirror. Ver `DRIVER-CHANGES.md` |
| `frontend/` | Tauri 2 + React 19. Simple.tsx usa el modelo feeder |
| `docs/superpowers/` | Specs, planes, auditorías |

## Comandos

```bash
# Backend
cd backend && .venv\Scripts\python.exe -m pytest tests/ -q   # ~99 tests
.venv\Scripts\python.exe -m uvicorn stfu.main:app --port 8765

# Instalador (backend PyInstaller como sidecar + Tauri NSIS)
cd backend && .venv\Scripts\pyinstaller.exe --clean --noconfirm stfu-backend.spec  # SIEMPRE --clean
cd frontend && npm run tauri build   # correr dentro del entorno VsDevCmd de BuildTools

# Driver v2 — PAUSADO, no es el foco activo (SOLO en máquina con Secure Boot OFF + EWDK build 26100)
cd driver && ./build.ps1              # EWDK msbuild
./install-test.ps1 -InfPath <ruta>    # self-signed + pnputil
```

## Gotchas aprendidos (no repetir errores)

- **PyInstaller SIEMPRE con `--clean`** — sin él reusa .pyc cacheado y el binario corre código viejo (síntoma: "stfu_apo.dll no encontrado" pese a estar presente). `run_backend.py --probe` verifica el binario.
- **Fix sample-rate:** `sd.WasapiSettings(auto_convert=True)` en ambos streams — Windows hace la SRC de cualquier device. No resamplear a mano.
- **cargo/tauri build** deben correr dentro del entorno de **VS BuildTools** (VS Community está sin libs VC → LNK1104 msvcrt.lib). `crate-type = ["rlib"]` (staticlib choca con Defender).
- **subprocess en el backend sin consola** (CREATE_NO_WINDOW) hereda handles inválidos → WinError 50. Redirigir los 3 handles a DEVNULL (`_run_quiet`).
- **Driver dev:** Secure Boot OFF + Memory Integrity OFF + `bcdedit /set testsigning on`. EWDK build == SDK build (26100).
- **Firma:** dev = test-signing gratis; distribución = EV cert (~$279-360/año) + Partner Center attestation (minutos, automatizable, sin costo por envío). Cross-signing muerto; Azure Trusted Signing NO firma kernel.
- `GITHUB_TOKEN` de entorno (cuenta trabajo) pisa el keyring de gh — limpiar antes de `gh release`.

## Estilo

- Español en commits (formato del repo, ver instrucciones de commit del repo). Sin `Co-Authored-By`.
- Funciones atómicas, complejidad ciclomática baja, sin comentarios de doc salvo el POR QUÉ no obvio.
- Verificar antes de declarar hecho: correr tests / smoke test real.
