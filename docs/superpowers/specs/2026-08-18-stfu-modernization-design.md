# STFU — Modernización v1.5: inferencia ONNX any-device, hub de modelos, refactor y hardening (2026-08-18)

**Estado:** diseño aprobado en sesión de brainstorming 2026-08-18. Pendiente: plan de implementación.

**Insumos:** auditoría 2026-07-02, survey de backend 2026-08-18 (19 archivos, 1.531 LOC producción), research de mercado últimos 30 días (modelos, runtimes, quejas de competidores, breakage 24H2).

---

## 1. Objetivo y alcance

Aplicar los aprendizajes de Upflow a STFU: inferencia ONNX que corre en **cualquier device (CPU, GPU, NPU)**, hub curado de modelos descargables desde Hugging Face, refactor amplio del backend con telemetría por etapa, hardening del APO contra Windows 11 24H2, y README con posicionamiento claro.

**En alcance:**
- Runtime de inferencia ONNX propio (`OnnxStreamingPlugin`) con selección de device `auto|cpu|gpu|npu`.
- NPU funcional en esta iteración vía runtime packs por vendor (Intel/Qualcomm).
- Lineup curado de 4-5 modelos con descarga HF y swap en vivo.
- DFN3-torch degradado a plugin legacy opcional (fuera del instalador).
- Refactor amplio del backend (lista §5) + telemetría per-stage.
- Auto-heal del registro APO post-updates de Windows.
- README reescrito.

**Fuera de alcance (explícito):**
- Port a Linux/macOS. Windows-only se mantiene.
- Driver virtual v2 (branch pausado; el runtime ONNX le servirá igual al feeder cuando se retome).
- Hub abierto con búsqueda libre por tag (solo lista curada esta iteración).
- NPU AMD Ryzen AI (VitisAI no tiene distribución pip limpia; se documenta).
- Windows ML como runtime (destino probable futuro; ver §3.4).

---

## 2. Contexto de mercado que informa el diseño (research 2026-08-18)

- **DirectML está en "sustained engineering"** — Microsoft movió el desarrollo activo a Windows ML. DML sigue shippeando (`onnxruntime-directml` 1.24.x) y sirve como EP GPU hoy, pero no es apuesta de largo plazo.
- **Modelos nuevos hacen viable CPU como piso universal:** FastEnhancer (MIT, 22K-1.1M params, RTF 0.006-0.011 en CPU, ONNX oficial, ICASSP 2026), DPDFNet (Ceva, Apache-2.0, 2.3-3.6M params, ONNX first-party, variante nativa 48kHz HR, API streaming con estado explícito), GTCRN (48K params, referencia previa del tier liviano).
- **sherpa-onnx** ya empaqueta GTCRN + familia DPDFNet como API de speech enhancement mantenida — referencia de implementación para nuestra capa de sesión/estado (no dependencia).
- **Windows 11 24H2 rompe APOs:** cumulative updates desactivan APOs en silencio (threads Equalizer APO jul-2026), endpoints fantasma post-update, error 0x88890004 en reinstalación.
- **Posicionamiento libre:** Krisp subió a $96/año y se auto-apaga bajo CPU alta; Broadcast es RTX-only; AMD NS está abandonado; NoiseTorch es Linux-only. "NoiseTorch para Windows, any device" es slot vacío.
- Convención HF para SE: tags `audio-to-audio` + `speech-enhancement`; registro machine-readable estilo sherpa-onnx / melband-roformer-infer.

---

## 3. Runtime de inferencia

### 3.1 `OnnxStreamingPlugin`

Nueva clase en `stfu/plugins/onnx_streaming.py` que implementa el ABC `AudioPlugin` existente. Un plugin por modelo instalado, instanciado desde su manifest.

- `setup()`: crea la `InferenceSession` de ONNX Runtime con los providers que resuelve el `ep_router`; inicializa tensores de estado recurrente en cero según `io_spec` del manifest.
- `process(chunk)`: una corrida de sesión por chunk. Los tensores de estado de salida se realimentan como entrada de la siguiente llamada — streaming real con contexto persistente. Sin ventana deslizante, sin `reset_h0()`, sin API offline.
- `teardown()`: libera sesión y estados.
- Parámetro `strength` universal: mezcla dry/wet post-inferencia (`out = wet*s + dry*(1-s)`), independiente del modelo.
- `preferred_format` viene del manifest; `FormatAdapter` existente hace la conversión (un modelo de 16kHz convive con el path de 48kHz sin código nuevo).

### 3.2 `ep_router` — selección de device

Módulo `stfu/inference/ep_router.py` (portado de los patrones `ep_registry` + `onnx_cpu_fallback_probe` + `dml_device` de Upflow):

- Setting `device: auto|cpu|gpu|npu` (default `auto`).
- `auto`: prueba en orden NPU → GPU → CPU. Probe = crear sesión con el EP candidato + procesar un chunk de silencio + validar salida sin NaN/Inf. Primer probe exitoso gana.
- Override manual respeta la elección del usuario; si el EP elegido falla el probe, error visible en `/status` y UI (no fallback silencioso — el usuario eligió).
- Fallback en runtime: si una sesión activa lanza error de EP, se recrea con el siguiente EP de la escalera y se loguea + expone en telemetría.
- El resultado del probe se cachea por (device, modelo) en `~/.stfu/runtime_cache.json`; se invalida si cambia versión de driver o de runtime pack.

### 3.3 NPU — runtime packs por vendor

Restricción dura: un proceso Python solo puede cargar UN build de `onnxruntime` (`onnxruntime-directml`, `onnxruntime-qnn` y `onnxruntime-openvino` proveen todos el paquete `onnxruntime` y conflictúan). Diseño:

- **Base bundled:** el instalador trae `onnxruntime-directml` → CPU + GPU funcionan out-of-the-box en cualquier máquina.
- **NPU pack:** descarga bajo demanda del wheel del vendor a `~/.stfu/runtimes/<vendor>/`, extraído como árbol de paquete. Al arrancar, si el device configurado es `npu` (o `auto` detectó NPU), el backend inserta esa ruta en `sys.path` **antes** del primer `import onnxruntime`. Patrón `pack_provisioner`/`vendor_paths` de Upflow.
- **Cambiar de device = restart del backend** (la UI ya sabe reiniciar el backend; se reusa ese flujo). Sin hot-swap de runtime.
- Detección de vendor: plataforma `ARM64` → pack QNN (Snapdragon X); NPU Intel presente (enumeración de device class NPU vía WMI) → pack OpenVINO; sin NPU detectada → la opción `npu` aparece deshabilitada en UI con razón.
- **AMD Ryzen AI: fuera de alcance.** VitisAI EP no se distribuye por pip de forma limpia. Documentado en README.
- **Spike bloqueante al inicio de la fase NPU:** verificar en pip el estado real de `onnxruntime-qnn` (win-arm64) y `onnxruntime-openvino` (soporte NPU Meteor/Lunar Lake). Si OpenVINO-EP-NPU no está maduro, alternativa documentada: paquete `openvino` nativo (corre ONNX directo, sin ORT) como backend Intel-NPU dedicado detrás de la misma interfaz del router.

### 3.4 Windows ML

Destino probable cuando su API Python madure (EPs evergreen, selección automática, NPU sin packs). El diseño lo anticipa: `ep_router` es el único módulo que conoce runtimes; migrar a WinML es reemplazar su implementación sin tocar plugins ni manifests. No se implementa en esta iteración.

### 3.5 Degradación bajo presión (anti-Krisp)

Si la telemetría (§6) reporta p95 del stage NC por encima del budget de chunk (20ms) sostenido por N ventanas, el engine baja automáticamente al modelo del tier inferior del mismo lineup y notifica por WebSocket. **Nunca se desactiva la cancelación por carga.** Feature explícita de README frente al auto-disable de Krisp.

---

## 4. Modelos y hub

### 4.1 Lineup curado inicial

| Tier | Modelo | Params | Rate | Licencia | Fuente |
|---|---|---|---|---|---|
| floor | FastEnhancer Tiny | 22K | 16k | MIT | releases GitHub aask1357/fastenhancer |
| floor+ | FastEnhancer Base | 91K | 16k | MIT | ídem |
| default | DPDFNet2 | 2.3M | 16k | Apache-2.0 | HF ceva-ip |
| quality | DPDFNet 48kHz HR | 3.6M | 48k full-band | Apache-2.0 | HF ceva-ip |
| alt | GTCRN | 48K | 16k | MIT | sherpa-onnx release assets |

- Cada modelo se valida A/B contra DFN3 (escucha + RTF medido en CPU del dev box) antes de entrar al lineup; el default de instalación se decide con esos números.
- DFN3-torch queda como plugin legacy detrás de extra `pip install .[torch]`; se elimina `deepfilternet`/torch de `requirements.txt` base. Instalador ~500MB → ~100MB.

### 4.2 Manifest extendido

`ModelManifest` existente (validación de id/file/plugin_class se conserva) se extiende con:

```
io_spec:            # nombres de tensores: audio in/out, estados in/out, shapes
sample_rate, channels, chunk_samples
tier:               # floor | default | quality
license:            # SPDX
source:             # hf | github-release | url
hf_repo / url, sha256
supported_devices:  # subset de [cpu, gpu, npu]
```

`sha256` se verifica post-descarga. Manifests del lineup curado viven en el repo (`backend/stfu/hub/curated/*.json`) — la descarga trae solo el `.onnx`.

### 4.3 Descarga y registro

Port de patrones Upflow (`hf_client`, `model_installer`, `download_chain`, `progress`):

- `GET /models` — instalados + disponibles (curados no instalados).
- `POST /models/{id}/download` — job con progreso por WebSocket; verificación sha256; registro en `~/.stfu/models/<id>/`.
- `POST /models/{id}/activate` — swap en vivo del plugin NC en el pipeline activo (el pipeline ya soporta recompilación; el modelo nuevo hace `setup()` antes del swap, el viejo hace `teardown()` después).
- `DELETE /models/{id}` — desinstala (rechaza si activo).
- UI: selector de modelo con tier, tamaño, licencia, device compatible, estado de descarga.

### 4.4 Convención comunitaria (preparación, no implementación)

Los manifests curados usan el mismo esquema que usará el hub abierto futuro. Tags HF documentados en README: `audio-to-audio`, `speech-enhancement`, `stfu-compatible`.

---

## 5. Refactor del backend (del survey 2026-08-18)

Orden: primero lo que reduce riesgo de todo lo demás.

**Robustez (bugs reales):**
1. `_worker_loop` sin try/except alrededor de `pipeline.process()` — excepción de plugin mata el worker en silencio y el target queda zombie. Fix: capturar, loguear, marcar target `failed` en `/status`, pasar audio en passthrough. El estado `failed` se expone en UI.
2. `teardown()` muerto en producción: `CaptureThread.stop()` → `pipeline.clear()`; ídem `ApoEngine.stop()`. Cierra el último item 🟡 de la auditoría (modelo residente + recarga por start).
3. Contadores xrun (`+=` desde dos callbacks): pasar a incrementos bajo el lock del ring o contadores por-thread sumados en lectura.
4. `pipe_server`: `stop()` no cancela `ConnectNamedPipe` bloqueante (thread + handle filtrados) — cancelar vía `CancelIoEx` o conexión dummy; excepciones del client loop hoy mueren con `pass` — loguear siempre; capturar más que `pywintypes.error` en el accept loop.
5. Device matching por igualdad exacta de nombre MME truncado → resolver default por índice dentro del host API WASAPI, sin comparar strings.
6. `apo_engine.status()` debe reflejar si el thread del pipe está vivo, no membership en un dict.

**Estructura:**
7. Split `capture.py` (191 LOC, 4 threads, 4 responsabilidades): `stream_lifecycle` (apertura/cierre PortAudio), `worker` (loop de proceso), `stats` (contadores thread-safe). `transport.py` queda como está (limpio).
8. `pipeline_factory` compartido — elimina el import privado `_build_pipeline` desde `apo_engine` y los imports circulares inline.
9. Limpieza: imports muertos en `routes/apo.py`; mutable default Pydantic en `routes/feeder.py`; `vars(d)` → response model en `routes/devices.py`; validación `target in (...)` duplicada 3× → dependencia FastAPI.

**Rendimiento (medir antes de optimizar — regla Upflow):**
10. `np.concatenate` por chunk en `pipeline._push_output` y `adapter._rechunk` (realloc O(n) cada 20ms) → buffers preallocados con cursor. Se hace DESPUÉS de tener telemetría (§6) para confirmar impacto con números.
11. Lock de `Pipeline` para `set_parameter`/`compile` vs `process` desde threads distintos (hoy sin sincronización en el path APO).

---

## 6. Telemetría per-stage

- Instrumentación en `Pipeline._run_stage` — único seam que cubre el path WASAPI y el path APO a la vez. Nada de medir solo en `_worker_loop`.
- Por stage: EMA + p95 sobre ventana rodante (ring de muestras de `perf_counter`, sin alocación por chunk).
- `/status.streams[target].stages[] = {plugin, ema_ms, p95_ms, budget_ms}` + `total_latency_ms` (algorítmica + buffering, hoy solo visible en el POST de arranque).
- `/ws/metering` se unifica: mismo payload que `/status` (hoy divergieron).
- Eventos `overbudget` → insumo del auto-degrade (§3.5).

---

## 7. APO hardening (24H2)

1. Health-check del registro al arrancar el backend + periódico (¿FxProperties intactas para los endpoints registrados?). Si un cumulative update desactivó el APO → estado `needs-repair` en `/status` + botón de re-registro (elevado) en UI.
2. Enumeración de endpoints tolera fantasmas: filtrar por `DEVICE_STATE_ACTIVE`.
3. Auto-repair tras reinstalación de driver de audio (item pendiente de la auditoría — el registro se pierde y hoy nadie lo detecta).

---

## 8. README

Rewrite completo:
- Posicionamiento: "NoiseTorch para Windows — cancelación de ruido open source en cualquier CPU, GPU o NPU".
- Tabla comparativa honesta: NVIDIA Broadcast (RTX-only), Krisp ($96/año, se auto-apaga bajo carga), AMD NS (abandonado), Equalizer APO+RNNoise (sin UI, modelo viejo). STFU: gratis, any-device, degrada en vez de apagarse, open source.
- Tabla de tiers de modelos (§4.1) con requisitos reales.
- Quickstart de testers y build-from-source actualizados.
- Sección de modelos comunitarios con la convención de tags HF.
- Límites documentados sin marketing: exclusive-mode salta APOs, `DisableProtectedAudioDG=1`, NPU AMD pendiente, cambio de device requiere restart.

---

## 9. Testing

TDD para todo lo nuevo; regresión antes de refactorizar lo existente.

Nuevos:
- `OnnxStreamingPlugin`: modelo ONNX fake diminuto en tests (generado con onnx helper, determinista) — estado persiste entre chunks, strength mezcla, teardown libera.
- `ep_router`: probe con EP fake que falla/da NaN → cae al siguiente; override manual no hace fallback silencioso; cache de probes.
- Worker crash → target `failed` + passthrough (hoy cero tests de `_worker_loop`).
- Teardown wiring (stop → clear).
- Hub: descarga mockeada, sha256 mismatch rechaza, activate swap, delete de modelo activo rechaza.
- Telemetría: stages reportan, p95 calcula, overbudget dispara.
- `AudioEngine` y `ApoEngine` (hoy cero tests).

Los tests existentes fuertes (adapter, pipeline, transport) son la red de seguridad del refactor — corren verdes en cada paso.

---

## 10. Fases de ejecución

| Fase | Contenido | Depende de |
|---|---|---|
| F1 | Refactor robustez (§5.1-6) + telemetría (§6) | — |
| F2 | `OnnxStreamingPlugin` + `ep_router` (cpu/gpu) + lineup curado + hub + A/B validación | F1 (telemetría para medir RTF) |
| F2.5 | NPU runtime packs (spike wheels → implementación) | F2 |
| F3 | Refactor estructura+perf (§5.7-11, con números de F1) + APO hardening (§7) | F1 |
| F4 | README + UI (selector modelos, estados failed/needs-repair/degrade) | F2 |

v2 (driver virtual) permanece pausado; el runtime ONNX de F2 es directamente reutilizable por el feeder v2.

---

## 11. Riesgos

| Riesgo | Mitigación |
|---|---|
| Wheels NPU (qnn/openvino) inmaduros o sin win-arm64 en pip | Spike bloqueante al inicio de F2.5; fallback openvino nativo documentado; NPU no bloquea F2 |
| Calidad de DPDFNet/FastEnhancer < DFN3 en escucha real | A/B antes de cambiar default; DFN3 sigue disponible como legacy |
| Refactor amplio rompe audio que hoy funciona | Tests fuertes existentes como red; robustez primero; perf solo con números de telemetría |
| 24H2 cambia comportamiento de APO otra vez | Health-check periódico detecta, no asume |
| fp16 en DML (know-how Upflow: NaN, RMSNorm) | Modelos del lineup se usan fp32 por default; fp16 solo si telemetría lo justifica y con validación NaN en probe |
