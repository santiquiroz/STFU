# STFU — Auditoría profunda (2026-07-02)

**Alcance:** estado del código vs plan, causa raíz del problema multi-sample-rate, evaluación de la idea "driver propio + FFT a nivel driver", estrategia de driver verificada contra fuentes primarias (Microsoft Learn, repos de proyectos comparables).

**Método:** 5 auditores de código en paralelo (core, audio I/O, APO, frontend, plan-vs-realidad) + 3 investigadores web (opciones de driver, estrategia SRC, proyectos comparables) + verificación adversarial de claims (6 verificaciones completadas, todas confirmaron los claims). Suite de tests ejecutada: **54 passed, 0 failed**.

---

## 1. Dónde estamos vs el plan

Plan de referencia: `docs/superpowers/plans/2026-06-20-stfu-v1-plan.md` (~60% ejecutado).

| Fase / Tarea | Estado | Evidencia |
|---|---|---|
| Fase 0 — v1.0 baseline (pipeline, plugins, CaptureThread, rutas, Simple UI) | ✅ done | commits `edf2d1b`..`0291542` |
| Task 1 — fix shape del pipeline al acumular | ✅ done | `701519e` |
| Task 2 — registro APO en registry (Python) | ✅ done | `d7f3494` + fixes `df1d6eb`, `55aed45` |
| Task 3 — rutas FastAPI `/apo/*` | ✅ done | `c05e59a` + `55aed45` |
| **Task 4 — scaffolding C++ APO DLL** | ❌ **missing** | no existe `apo/` ni ningún `.cpp/.h/CMakeLists.txt` en el repo |
| **Task 5 — pipe client C++ + APOProcess** | ❌ **missing** | ídem |
| Task 6 — pipe server Python | ⚠️ partial | `faf6a49`+`81c9dd5`; `apo_engine.py` es un stub de 1 línea; **nadie instancia `ApoPipeServer` en producción** |
| Task 7 — speaker toggle frontend | ⚠️ partial | `6f8f7b9`; CLSIDs placeholder `{C0FFEE02-...}` con TODO en `api.ts:49-52` |
| Task 8 / Fase 3 — verificación E2E hardware | ❌ blocked | speaker path 500 garantizado (DLL inexistente) |
| v1.2 — auto-restart on device change | ❌ not started | |
| v2.0 — driver virtual WDM | ❌ not started (diferido por diseño) | |

**Traducción:** toda la infraestructura Python del APO es código muerto sirviendo a un componente C++ que nunca se construyó. El mic toggle funciona pero solo como auto-monitor (mic → DFN3 → parlantes); no hay mic virtual, así que Discord/Zoom no pueden consumir el audio limpio.

Los checkboxes del plan nunca se actualizaron — el git log es la única fuente confiable de progreso.

---

## 2. El problema multi-sample-rate: diagnóstico real

Son **dos problemas independientes** que el código actual mezcla:

### Problema A — formato (el error `AUDCLNT_E_UNSUPPORTED_FORMAT`)
- `capture.py:94-101` abre `InputStream` a 48000 fijo (`engine.py:18`). WASAPI shared-mode vía PortAudio rechaza rates que no coincidan con el mix format del endpoint → **el mic de 192kHz sigue roto hoy**. Los commits `d4cb4f5`/`0291542` solo arreglaron el lado de salida.
- **Fix definitivo (verificado contra docs de Microsoft y sounddevice):** `AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | SRC_DEFAULT_QUALITY`. Expuesto en sounddevice ≥ 0.4.7 como:
  ```python
  sd.InputStream(..., samplerate=48000,
                 extra_settings=sd.WasapiSettings(auto_convert=True))
  ```
  Con eso ambos streams se abren al formato canónico (48kHz/float32) y **Windows hace la SRC en user-mode** para cualquier dispositivo (192kHz, 44.1kHz, lo que sea). Permite borrar `_query_device_rate`, `_resample`, `_upsample_nearest`, `_downsample_decimate` y la matemática de `out_blocksize` completos.

### Problema B — reloj (drift entre dos dispositivos)
- Dos streams = dos cristales independientes (50–100+ ppm de skew, deriva con temperatura). La cola `queue.Queue(maxsize=8)` tiene ~160ms de holgura: a 100ppm se llena/vacía cada **~13 minutos** → glitch de 20ms periódico, para siempre. `put_nowait` descarta chunk completo en lleno; `queue.Empty` emite 20ms de ceros.
- AUTOCONVERTPCM **no** arregla esto. La solución de la industria (zita-ajbridge, CamillaDSP): **resampler adaptativo** — ring buffer entre dominios de reloj, medir fill promedio cada ~10s, ajustar el ratio del resampler en cantidades de ppm (libsamplerate/`samplerate` acepta ratio variable por llamada; python-soxr no).
- Alternativa barata interina: drop/insert de 1 sample con crossfade de ~32 samples al cruzar watermarks — inaudible en voz.

### Sobre la idea "transformada de Fourier a nivel de driver"
Rechazada con evidencia, por tres razones independientes:
1. **Latencia:** SRC en dominio FFT (overlap-save) carga ~256 samples de latencia algorítmica vs 16–64 de un polifase equivalente.
2. **Drift:** FFT mapea N bins → M bins por bloque = solo ratios fijos. El problema real (drift) necesita fase de interpolación continuamente variable — exactamente lo que da un polifase-sinc con paso de fase variable (zita `VResampler`, rubato `AsyncSinc`, libsamplerate).
3. **Arquitectura Windows:** el kernel NO hace SRC. Toda conversión/mezcla shared-mode ocurre en `audiodg.exe` (user-mode). Los APO corren al mix format del endpoint y nunca ven un mismatch. SRC en kernel = DSP float a IRQL elevado, tablas non-paged, sin ecosistema — ni Microsoft lo hace.

### Defectos DSP adicionales encontrados (independientes del driver)
- `capture.py:18-25`: upsampling nearest-neighbor (imaging) y decimación sin filtro anti-alias (aliasing). El path de 192kHz→48k es justo el peor.
- `capture.py:36-37`: `import scipy` perezoso **dentro del callback de audio** — primer callback = import + diseño FIR en contexto RT.
- `adapter.py:28-33` y `capture.py:28-39`: `resample_poly` sin estado por chunk de 20ms → clicks a ~50Hz en el borde de cada chunk. Fix: resampler con estado persistente (`soxr.ResampleStream.resample_chunk()`).

---

## 3. Bugs críticos fuera del tema sample-rate

| Sev | Bug | Ubicación |
|---|---|---|
| 🔴 | **EQ roto de raíz:** `iirpeak` es un band-PASS resonante, no un peaking EQ. Cualquier ganancia ≠ 0 elimina todo lo que está fuera de la banda; dos bandas activas ≈ silencio. Necesita biquad peaking RBJ. Además `sosfilt` sin `zi` → estado se resetea cada 20ms | `eq_parametric.py:70-81, 35-40` |
| 🔴 | **DFN3 mal usado:** `df.enhance.enhance()` es API offline; llamada por chunk de 20ms hace `reset_h0()` cada vez → destruye el contexto recurrente del modelo (supresión degradada + artefactos + overhead STFT por llamada). Usar el path de streaming frame-by-frame (DfTract) | `deepfilternet3.py:24-36` |
| 🔴 | **Registro APO puede romper audio del endpoint:** escribe CLSID basura en `HKLM\...\FxProperties` y reinicia `audiosrv`, sin backup/rollback; la UI no expone unregister; promete UAC que nunca ocurre (winreg sin elevación → `PermissionError` → 500) | `register.py`, `Simple.tsx:115-129` |
| 🟠 | `Pipeline.process` toma solo `chunks[0]` del adapter → pérdida silenciosa de audio con cualquier plugin de chunk/rate distinto; emite bloques de ceros con forma equivocada mientras acumula; nunca reconvierte al formato del stream | `pipeline.py:34-46` |
| 🟠 | Speaker pipeline imposible: usa el device de salida como input sin loopback WASAPI (`max_input_channels=0` → 500). No hay loopback en todo el backend | `Simple.tsx:78-89`, `capture.py:94` |
| 🟠 | Race en `AudioEngine.start()`: stop/build/start fuera del lock → dos POST concurrentes filtran un CaptureThread imposible de detener | `engine.py:47-67` |
| 🟠 | Fallo de apertura del output silenciado (`except: pass` sin log); API reporta ok sin audio | `capture.py:91-92` |
| 🟠 | `latency='low'` se perdió en `d4cb4f5` → default 'high' de sounddevice; contradice el objetivo de baja latencia | `capture.py:82-101` |
| 🟠 | Pipe server APO: polling con `sleep(0.01)` + request-response síncrono sin timeout — audiodg no puede bloquearse; frame malformado mata el handler | `pipe_server.py:103-111` |
| 🟠 | CORS empaquetado: backend permite `https://tauri.localhost` pero Tauri 2 en Windows usa `http://tauri.localhost` por defecto → app empaquetada muerta | `main.py:22` |
| 🟡 | Status flags de PortAudio (overflow/underflow) ignorados en ambos callbacks — los síntomas del drift son invisibles en logs | `capture.py:114-134` |
| 🟡 | DFN3 (torch) corre dentro del callback RT de PortAudio; sin worker thread | `capture.py:118` |
| 🟡 | Matching de device default por igualdad exacta de nombre (MME trunca a ~31 chars) → fallback al primer device | `devices.py:26-50` |
| 🟡 | `teardown()` nunca se llama al parar el engine — modelo torch queda residente; cada start recarga el modelo | `engine.py:69-73` |
| 🟡 | Tauri: sin tray, sin sidecar (usuario debe correr uvicorn a mano), identidad template, toggles desincronizados del backend, slider reinicia el stream completo (glitch audible por ajuste) | `src-tauri/*`, `Simple.tsx` |

Tests: 54 pasan pero solo cubren happy paths — no hay test de EQ con ganancia ≠ 0 (habría expuesto el bug al instante), ni de continuidad en bordes de chunk, ni de multi-chunk del adapter. `test_pipeline.py:74-90` codifica el comportamiento de bloques-cero como correcto.

---

## 4. Estrategia de driver — verificada contra el mercado

**Lo que hacen los demás (todas las fuentes confirmadas):**
- NVIDIA Broadcast, RTX Voice, Krisp, AMD Noise Suppression: **todos** usan el patrón *virtual device firmado + engine de procesamiento en user-mode*. Ninguno usa APO. UX: la app elige "X Microphone".
- Open source en Windows: RNNoise/werman y compañía se montan sobre **Equalizer APO** (GPLv2), que carga APOs sin firma poniendo `DisableProtectedAudioDG=1` — así ha shippeado a millones de usuarios por una década, incluyendo supresión de ruido en el mic "sin lag perceptible".
- Firmar un driver kernel en 2025/2026: **attestation signing vía Partner Center + certificado EV obligatorio** (~$250–600 USD/año, Azure Trusted Signing NO sirve para kernel, cross-signing muerto desde 24H2). Sin eso: test mode (la trampa donde está atrapado Scream). WireGuard/wintun demuestra que open source puede firmar — con entidad legal que sostenga el cert.
- Bases forkeables con licencia compatible: **Microsoft SYSVAD** (MS-PL) y **VirtualDrivers/Virtual-Audio-Driver** (MIT+MS-PL, SYSVAD-derived, ya trae mic virtual + speaker virtual, activo 2025, test-signed). VB-Cable: cerrado, no redistribuible. Scream: render-only, sin lado mic. ACX 1.1 es el framework recomendado por Microsoft para drivers nuevos (Win10 2004+), pero sin precedente open-source grande aún.

**Camino por etapas para STFU:**

- **Tier 0 (ya, sin driver):** arreglar WASAPI directo. `auto_convert=True` en ambos streams + formato canónico 48kHz/float32/estéreo + servo de drift. Esto elimina el dolor de sample rates HOY con ~20 líneas de diff neto negativo.
- **Tier 1 (v1.1, el plan actual — validado):** APO C++ (MFX en captura para mic NC transparente, SFX en render para speaker NC), registro estilo Equalizer APO con `DisableProtectedAudioDG=1`. Sin firma, sin kernel, sin reboot. El engine de Windows entrega al APO el mix format y hace toda la SRC → el problema multi-rate desaparece estructuralmente en este path. Límites documentados a aceptar: clientes exclusive-mode saltan los APO; reinstalar el driver de audio borra el registro (implementar auto-repair en `register.py`); fragilidad reportada en 24H2.
  - El bridge APO↔Python debe ser **shared memory lock-free con timeout y passthrough fallback**, no el pipe actual con polling de 10ms.
- **Tier 1.5 (v1.x):** captura per-app sin driver vía `ActivateAudioInterfaceAsync` + `PROCESS_LOOPBACK` (Win10 2004+, sample oficial de Microsoft, probado por OBS). Solo captura — no puede exponer mic virtual.
- **Tier 2 (v2, el flagship):** "STFU Microphone" — driver virtual propio, fork de SYSVAD o VirtualDrivers/Virtual-Audio-Driver, formato interno fijo 48kHz float32 (Windows hace SRC per-app gratis en shared mode). **No empezar hasta tener entidad legal + cert EV.** Drift físico↔virtual: micro-resampling adaptativo en el engine user-mode, jamás en kernel.

---

## 5. Roadmap recomendado (orden de ejecución)

1. **Quick wins WASAPI (días):** `auto_convert=True` ambos streams; borrar resampler manual de capture.py; `latency='low'`; prefill de cola (2 chunks); contadores de overflow/underflow expuestos en `/status`; fix race `engine.start()`; log + flag `playback_active` cuando el output falla; fix CORS (`http://tauri.localhost`).
2. **DSP core (días):** DFN3 → API de streaming con estado (DfTract); EQ → biquads peaking RBJ + `sosfilt` con `zi` persistente; adapter → `soxr.ResampleStream` con estado; pipeline → propagar multi-chunk + adaptar salida al formato del stream; mover inferencia a worker thread fuera del callback RT. Tests de regresión: seno continuo por chunks sin energía en armónicos del chunk-rate; EQ con ganancia ≠ 0.
3. **Servo de drift (días):** ring buffer con telemetría de fill + corrección de ratio ppm vía `samplerate` (libsamplerate), patrón CamillaDSP (ajuste cada ~10s, |corrección| ≤ 200ppm, slew-limited).
4. **APO C++ DLL (semanas — Tasks 4-5 del plan):** COM DLL delgada y RT-safe; shared memory en lugar de named pipe con polling; CLSIDs reales; elevación UAC real; backup/rollback de FxProperties + botón unregister + auto-repair.
5. **Frontend (días):** tray, sidecar/spawn del backend Python, reconciliación de toggles con `GET /status`, endpoint set-parameter en vivo (sin reiniciar stream), páginas Advanced y Hub.
6. **v2 driver virtual:** solo con cert EV; base VirtualDrivers/Virtual-Audio-Driver o SYSVAD; evaluar ACX.

---

## Fuentes clave (verificadas)

- AUTOCONVERTPCM: learn.microsoft.com/en-us/windows/win32/coreaudio/audclnt-streamflags-xxx-constants · markheath.net/post/wasapi-sample-rate-conversion · python-sounddevice ≥0.4.7 `WasapiSettings(auto_convert=True)`
- Drift adaptativo: kokkinizita.linuxaudio.org/papers/adapt-resamp.pdf (Adriaensen) · github.com/HEnquist/camilladsp
- APO: learn.microsoft.com/en-us/windows-hardware/drivers/audio/audio-processing-object-architecture · github.com/dechamps/APO · sourceforge.net/p/equalizerapo
- Firma de drivers: learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/code-signing-attestation · techcommunity (removal of cross-signing trust)
- Bases forkeables: github.com/microsoft/Windows-driver-samples (sysvad, ACX) · github.com/VirtualDrivers/Virtual-Audio-Driver
- Resamplers streaming: python-soxr.readthedocs.io (`ResampleStream`) · libsamplerate variable-ratio
