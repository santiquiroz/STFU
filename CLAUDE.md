# CLAUDE.md — STFU

Instrucciones de proyecto para asistentes AI (Claude, Copilot, etc.). Contexto de arquitectura y estado para retomar el trabajo sin perder hilo.

## Qué es STFU

App open-source de Windows: cancelación de ruido de micrófono con IA (DeepFilterNet3), corriendo en cualquier GPU (DirectML) o CPU. Meta: reemplazar NVIDIA Broadcast/Krisp sin requerir hardware específico, sin dependencias propietarias.

## Estado actual (2026-07): PIVOTE a driver virtual (v2)

**Decisión clave:** los APO de software (el enfoque v1.1) **no cargan en micrófonos USB** — verificado exhaustivamente en hardware real (Blue Snowball: 1 propiedad FX de fábrica vs ~130 de un codec Realtek de placa base; audiodg nunca instancia el APO). Los mics USB audio-class no tienen grafo de efectos donde inyectar un APO.

**Rumbo v2:** driver de **micrófono virtual "STFU Microphone"** (patrón NVIDIA/Krisp) que funciona con cualquier dispositivo. El plan completo está en `docs/superpowers/plans/2026-07-03-v2-virtual-mic-driver.md` y los cambios exactos del kernel en `driver/DRIVER-CHANGES.md`. **Léelos al retomar.**

## Arquitectura v2 (Modelo A — kernel mínimo)

```
[mic físico] --WASAPI--> [Python: DFN3 + drift servo] --WASAPI render--> [STFU Audio Bridge]
                                                              --RingBuffer kernel--> [STFU Microphone] --> Discord/Zoom
```
El driver es un "cable tonto": el DSP jamás entra al kernel. Todo el procesamiento (captura, DeepFilterNet3, servo de drift, resampleo) queda en el backend Python **que ya está construido y validado**.

## Layout del repo

| Ruta | Qué es |
|---|---|
| `backend/stfu/core/` | Pipeline, FormatAdapter (soxr), logging |
| `backend/stfu/plugins/builtin/` | DeepFilterNet3 (ventana deslizante), EQ RBJ, Gain |
| `backend/stfu/audio/` | Captura WASAPI (auto_convert), transport (RingBuffer + DriftServo), engine, devices |
| `backend/stfu/api/routes/feeder.py` | **Feeder v2**: mic físico → DFN3 → STFU Audio Bridge (o salida de prueba sin driver) |
| `backend/stfu/apo/` | **Archivado** — enfoque APO (solo sirve en endpoints de placa base, no USB) |
| `driver/` | **Driver v2** — fork de VirtualDrivers/Virtual-Audio-Driver + RingBuffer de AudioMirror. Ver `DRIVER-CHANGES.md` |
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

# Driver (SOLO en máquina con Secure Boot OFF + EWDK build 26100)
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
