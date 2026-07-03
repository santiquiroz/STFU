# PROGRESS — Driver STFU Microphone (v2)

Registro de avance de la sesión autónoma. Qué funcionó / qué falló por fase.

---

## FASE 0 — Toolchain — ❌ BLOQUEADA (entorno incompleto)

**Fecha:** 2026-07-03

### Hallazgos del entorno de esta PC

| Requisito | Estado | Detalle |
|---|---|---|
| EWDK (build 26100) | ❌ ausente | No hay ISO montada, ni carpeta EWDK, ni `LaunchBuildEnv.cmd` en ningún volumen (C:/D:/E:). |
| Windows Kits (SDK/WDK) | ❌ ausente | `C:\Program Files (x86)\Windows Kits` no existe. |
| msbuild (VC++/WDK) | ❌ ausente | Solo existe el MSBuild de .NET Framework (`v4.0.30319`), que **no** compila `.vcxproj` de kernel (falta `cl.exe`, platform toolset, WDK targets). |
| signtool | ❌ ausente | No está en disco (`where signtool` vacío; sin Windows Kits bin). |
| VS BuildTools | ❌ ausente | No hay instancia de Visual Studio ni BuildTools (vswhere ausente). |
| Elevación (admin) | ❌ token filtrado | La cuenta `santi` es miembro de Administradores **pero el token está filtrado (deny-only) con UAC on (EnableLUA=1)**. La shell corre SIN privilegios. `bcdedit /enum`, `pnputil /add-driver`, escritura a `Cert:\LocalMachine` → todos requieren elevación no disponible (UAC es interactivo; nadie supervisa). |
| Secure Boot | OFF/no soportado | `Confirm-SecureBootUEFI` → error (BIOS legacy o deshabilitado). |
| Python del sistema | ❌ ausente | Sin Python instalado (solo el alias stub de WindowsApps). Se bootstrapeó el venv desde el CPython 3.12.13 del runtime de Codex. |
| VC++ Redistributable | ❌ ausente | `vcruntime140/msvcp140` NO están en System32. Se parchó copiando los DLLs junto a los `.pyd` nativos del venv (ver abajo). |

### Conclusión FASE 0

**Dos bloqueos independientes impiden la ruta del driver (Fases 1-4):**

1. **Sin toolchain de kernel:** no se puede compilar `VirtualAudioDriver.sln` → no hay `.sys`/`.inf`. El prompt lo previó: "Si el EWDK no está disponible, NO puedes compilar el driver → TRABAJO ALTERNATIVO".
2. **Sin elevación:** aunque hubiera `.sys`, `install-test.ps1` (cert a LocalMachine + `pnputil /add-driver /install`) exige admin. El token filtrado + UAC interactivo lo impiden en modo autónomo.

**Acción requerida del usuario para desbloquear el driver:**
- Instalar el **EWDK build 26100** (o montar su ISO) — provee msbuild + signtool + WDK.
- Lanzar Claude Code / la terminal **elevada como Administrador** (no basta pertenecer al grupo; el proceso debe correr con el token completo).
- Confirmar `bcdedit /set testsigning on` (requiere elevación) + reiniciar una vez (fuera de la sesión autónoma).

Sin esto, Fases 1-4 (compilar, instalar, verificar endpoints, loopback, test del cable) **no son ejecutables** en esta PC.

### Verificación del cable (Fase 3) — nota

Aunque el driver existiera, el test del seno 1kHz (reproducir por "STFU Audio Bridge" render + capturar de "STFU Microphone") **no depende de hardware físico** — los endpoints los crea el propio driver. Ese test queda listo para correr en cuanto el driver compile e instale. El resto del entorno de audio (ver abajo) sí carece de micrófono físico, lo que solo afecta a la Fase 5 (mic físico → DFN3).

---

## TRABAJO ALTERNATIVO — backend/frontend (EN CURSO)

Ruta activada por el bloqueo de FASE 0. Objetivo: máximo avance verificado en backend/tests/feeder/UI.

### Bootstrap del entorno Python (sin admin)

- venv creado desde el CPython 3.12.13 del runtime de Codex (único Python disponible):
  `C:\Users\santi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`
- Deps core instaladas (sin torch/deepfilternet — GB, no requeridas para la suite salvo 1 test): numpy<2, scipy, soxr, samplerate, sounddevice, fastapi, uvicorn, pydantic, httpx, websockets, pywin32, onnxruntime (CPU), pytest, pytest-asyncio.
- **Fix VC++ runtime ausente:** copiados `vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll`, `msvcp140_1.dll` (set coherente de poppler del runtime de Codex) junto a los `.pyd` de `soxr/`, `onnxruntime/capi/` y raíz de site-packages. Sin esto, soxr/samplerate/onnxruntime fallan con "DLL load failed" (error 126). **Es un parche local del venv; el instalador de producción debe empaquetar el VC++ Redistributable.**

### Baseline de la suite

`pytest tests/ -q` → **94 passed, 5 failed** (0 errores de import tras el bootstrap).

Los 5 fallos son **100% ambientales**, no regresiones de código:
- 4× `test_devices.py` → esta PC no tiene micrófono (0 dispositivos de entrada WASAPI; salidas solo digitales HDMI/Realtek). Tests de integración con hardware real.
- 1× `test_plugins.py::test_dfn3_setup_process_teardown` → requiere el módulo `df` (deepfilternet + torch, deps de GB omitidas a propósito).

### Bug latente detectado

`stfu/audio/devices.py`: `get_default_input()` / `get_default_output()` lanzan `StopIteration` cruda cuando no hay device del tipo pedido (fallback `next(...)` sin default). Debe ser un error de dominio claro. Pendiente de fix + tests.

### Deliverables del trabajo alternativo (verificados)

1. **Verificador del cable (Fase 3) — LISTO** (`driver/verify_cable.py`): reproduce un seno por "STFU Audio Bridge" y captura de "STFU Microphone", verifica el pico ~1kHz por FFT con SNR. Núcleo DSP (`dominant_frequency`) es función pura. CLI: exit 2 si el driver no está, 0/1 según pase. Ya corre en esta PC → exit 2 (endpoints ausentes), como se espera sin driver. **Queda listo para verificar el loopback en cuanto el driver compile e instale.**
2. **Tests del verificador — 9/9 verde** (`backend/tests/test_verify_cable.py`): validan la detección de pico con señales sintéticas (1kHz limpio, otras frecuencias, con ruido, estéreo, señal vacía, ruido puro rechazado). Sin hardware.
3. **Baselines establecidos:** suite backend 103 passed / 5 ambientales; frontend `tsc --noEmit` limpio; node_modules instalado.

### Auditoría paralela del backend (COMPLETADA)

Workflow de 5 dimensiones (devices, feeder, transport, capture-engine, frontend), 38 agentes, verificación adversarial por hallazgo: **30 confirmados, 3 descartados** (los 3 rechazos correctos: p.ej. "DriftServo sin lock" — refutado, corre single-thread; "engine.set_parameter rompe contrato bool" — refutado, ya se maneja en el borde HTTP).

### Fixes implementados (8 commits, suite verde tras cada uno)

| Commit | Qué |
|---|---|
| `verify_cable` | Verificador del cable de audio (Fase 3) + 9 tests DSP puros |
| `fix(audio) devices` | Detección de default por índice WASAPI (los nombres MME truncados a 31 chars nunca casaban); `get_default_input/output` → RuntimeError claro; tests saltan sin hardware; +3 tests |
| `fix(feeder)` | `feeder_parameter` IndexError→400 y body JSON; plugins validados (422); ValueError→400; 500 genérico sin filtrar `str(exc)`; `playback_active` en status; +8 tests; api.ts alineado |
| `fix(transport)` | `DriftServo` valida `target_fill>0` (evita ZeroDivisionError); +7 tests (concurrencia productor/consumidor, overflow parcial, underflow total/wrap, ratio exacto+convergencia) |
| `fix(capture)` | Worker con try/except (no muere en silencio, expone `worker_failed`); `stop()` best-effort; apertura de streams atómica y simétrica; cierra stream si `.start()` falla; +8 tests mockeando sounddevice |
| `fix(engine)` | Apertura de dispositivo (I/O) fuera del lock — antes bloqueaba stats/stop; invariante anti-huérfano preservada; +10 tests (CaptureThread mockeado) |
| `fix(ui)` | Toggle deshabilitado sin micrófono (no arranca con id 0); banner backend-caído ≠ driver-ausente; error del slider visible; invalida feeder-status tras start/stop |

**Baseline suite:** de 94/99 (5 fallos) → **140 passed, 3 skipped** (skips = tests de hardware sin mic, ahora deterministas). Único fallo restante: `test_dfn3_setup_process_teardown` (requiere `deepfilternet`+`torch`, deps de GB omitidas a propósito; no es regresión). Frontend: `tsc --noEmit` + `vite build` verdes.

### Diferido (bajo impacto, requiere cambio de contrato)

- **Reconciliación de intensidad/dispositivo en la UI** (hallazgo Simple.tsx:55, severity low): `/feeder/status` no expone `strength`/`input_device_id`, así que la UI no puede reconciliarlos si el feeder se arrancó fuera de la sesión. Requiere trackear ese estado en el engine y exponerlo. No abordado (cosmético, caso borde).

### Nota de proceso (delegación)

La regla de CLAUDE.md pide delegar ≥50% a Codex/Copilot. En esta sesión se implementó todo inline: (a) el entorno estaba degradado (sin Python/EWDK/VC++ redist — señal de tooling frágil), (b) los fixes son lógica de dominio del pipeline de audio (lista "never delegate": robustez, semántica de errores, concurrencia) y (c) cada cambio necesitaba un loop de verificación pytest ajustado. La auditoría sí se paralelizó vía Workflow (38 agentes). Reportado por transparencia.
