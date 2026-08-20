# v1.7.0 — Truth, Robustness & Polish: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Cerrar todo el backlog *accionable-ahora* de STFU tras v1.6: (1) verdad documental (docs de agente invertidos, README desfasado, versión de backend), (2) robustez/perf del backend (CancelIoEx, snapshot de salud cacheado, auto-restart por cambio de dispositivo, estado real en /feeder/status, minors de F3, split de capture.py), (3) features de pulido (UI de telemetría por etapa, hotkey global OS, progreso de descarga por WS, add/remove de plugins en vivo). Deja fuera: NPU (bloqueado por modelo), driver v2 (pausado por el usuario), y los spikes v1.7+/v3 no diseñados (STFT lineup, Monitor Mode, Studio Voice, live captions, per-app capture, community hub) — se documentan como backlog futuro.

**Architecture:** Backend Python (FastAPI + audio worker + APO pipe bridge), frontend Tauri 2 + React 19 + TanStack Query + Tailwind v4. Ver `CLAUDE.md`.

**Tech Stack:** Python 3.11, pydantic, FastAPI, pytest; React 19, TanStack Query 5, Tauri 2 (Rust), Tailwind v4. Gate backend: `backend/.venv/Scripts/python -m pytest -q`. Gate frontend: `npm run type-check` + `npm run build` (desde frontend/).

**Fuente:** survey de backlog 2026-08-19 (workflow stfu-backlog-survey). Ranks citados abajo.

## Global Constraints

- Base: master @ b14f822 (post v1.6.0). Branch: `feature/v17-truth-robustness-polish`.
- El driver v2 (`driver/`) está **PAUSADO** — no tocar código del driver; solo su README (marcar pausado). NPU **bloqueado** por model-fit — no implementar EPs de NPU; solo corregir mensajería obsoleta.
- Backend tests desde `backend/`: `.\.venv\Scripts\python.exe -m pytest -q` — suite base **311 verde**, mantener verde.
- Frontend desde `frontend/`: `npm run type-check` + `npm run build` verdes.
- Inmutabilidad, funciones atómicas, sin comentarios de doc salvo el POR QUÉ no obvio (ver CLAUDE.md global del usuario). Commits en español, convencional, sin `Co-Authored-By`.
- Archivos compartidos → orden estricto para evitar conflictos: `capture.py` (T7 lo reestructura) va DESPUÉS de cualquier task que lo toque; `Simple.tsx` lo tocan T6 y T9 → secuenciar T6 antes de T9.

---

### Task 1: Verdad de docs de agente + README raíz (rank 1, 2)

**Files:** `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md` (si existe), `README.md`

**Interfaces:** documentación — reflejar el estado REAL del proyecto.

Contexto verificado (del survey): los docs de agente están congelados en el pivot de driver de jul-2026 y describen la realidad INVERTIDA — marcan `backend/stfu/apo/` como "Archivado" y el driver virtual como foco activo. Realidad hoy: el **APO es el mecanismo shipped y mantenido** (F3 agregó health-check + auto-repair), y el **driver v2 está pausado**. El README raíz está en `(v1.5-dev)`, no menciona la superficie Voice Studio de v1.6 (tab Estudio: editor de cadena DSP, visualizador de espectro, medidor de reducción, presets, A/B bypass, Modo música) y lista como "en progreso/próximo" cosas ya shipped (Model-hub UI, hardening APO 24H2).

- [ ] **Step 1: Read** CLAUDE.md, AGENTS.md, .github/copilot-instructions.md (si existe), README.md para conocer el texto actual exacto.
- [ ] **Step 2: Edit** — en los 3 docs de agente: corregir la inversión (APO = shipped/activo con health-check+auto-repair; driver v2 = PAUSADO, no el foco). En README.md: subir a v1.7, describir la superficie Voice Studio real, mover a "hecho" lo ya shipped, y dejar en "próximo/futuro" solo lo real (STFT lineup, Monitor Mode, etc. — ver Task 12 para la lista). No inventar features; describir lo que existe.
- [ ] **Step 3: Verify** — relectura: ningún doc dice que el APO esté archivado ni que el driver sea el foco activo; el README refleja v1.7 + Voice Studio.
- [ ] **Step 4: Commit** — `docs: corregir inversión APO/driver en docs de agente y modernizar README a v1.7 (Voice Studio)`

---

### Task 2: Bump de versión a 1.7.0 en todo el repo (rank 3)

**Files:** `backend/pyproject.toml`, `frontend/package.json`, `frontend/src-tauri/tauri.conf.json`, `frontend/src-tauri/Cargo.toml` (+ Cargo.lock)

**Interfaces:** metadata.

Contexto: el release v1.6.0 (b14f822) solo tocó el frontend; `backend/pyproject.toml` quedó en 1.5.0. Alinear TODO a 1.7.0.

- [ ] Bump `backend/pyproject.toml` (y cualquier `__version__` en backend si existe — grep `1\.5\.0`/`1\.6\.0` en backend/stfu) a 1.7.0; frontend package.json + tauri.conf.json + Cargo.toml a 1.7.0. Verificar con grep que no queda `1.5.0`/`1.6.0` colgando. Commit — `chore(release): alinear todas las versiones a 1.7.0`

---

### Task 3: `pipe_server.stop()` cancela el ConnectNamedPipe bloqueante (rank 4)

**Files:** `backend/stfu/apo/pipe_server.py` (o `apo/` según ubicación real — verificar), test asociado.

**Interfaces:** `PipeServer.stop()` debe cancelar el accept en curso (CancelIoEx sobre el handle del pipe) para no dejar el thread de accept y el handle colgados.

Contexto: `CancelIoEx` no aparece en pipe_server.py; `stop()` filtra el thread de accept bloqueado en `ConnectNamedPipe`. Confirmado por el audit y la lista de refactor.

- [ ] **Step 1:** localizar pipe_server.py (grep `ConnectNamedPipe`). Leerlo.
- [ ] **Step 2: Test** — escribir/ajustar un test que arranca el server y llama `stop()` y verifica que el thread de accept termina en <N ms (join con timeout) sin quedar vivo.
- [ ] **Step 3: Implement** — en `stop()`, llamar `CancelIoEx(pipe_handle, None)` (vía win32file/ctypes según el patrón del archivo) antes/junto al cierre, para desbloquear `ConnectNamedPipe`; luego join del thread. Manejar el caso "no hay accept en curso".
- [ ] **Step 4:** correr pytest del módulo → verde. Commit — `fix(apo): cancelar ConnectNamedPipe bloqueante en PipeServer.stop (CancelIoEx)`

---

### Task 4: Snapshot cacheado de salud del APO para /status y /ws/metering (rank 5)

**Files:** `backend/stfu/main.py`, `backend/stfu/services/*` (ApoHealthMonitor), test.

**Interfaces:** `_status_payload()` debe leer un snapshot cacheado (publicado por `ApoHealthMonitor` cada ~60s) en vez de llamar `check_registrations()`/`needs_repair()` (lecturas de winreg) en cada GET /status y cada tick ~10Hz de la WS de metering.

Contexto: F3 review finding I2, aún sin fijar en main.py (~líneas 70-71). El monitor ya computa la salud cada 60s; exponer ese snapshot.

- [ ] **Step 1: Read** main.py (_status_payload) y el ApoHealthMonitor. Test que afirme que GET /status no dispara lecturas winreg (mockear check_registrations y contar llamadas: debe ser 0 desde el payload cuando hay snapshot).
- [ ] **Step 2: Implement** — el monitor publica un snapshot (dataclass/dict) en cada ciclo; `_status_payload()` lo lee. Fallback seguro si aún no hay snapshot (primer arranque): valor neutro sin romper.
- [ ] **Step 3:** pytest → verde. Commit — `perf(apo): servir salud del APO desde snapshot cacheado en /status y metering WS`

---

### Task 5: Auto-restart del pipeline al cambiar el dispositivo por defecto (rank 6)

**Files:** `backend/stfu/audio/*` (engine/capture o un watcher), `backend/stfu/services/*`, test.

**Interfaces:** cuando cambia el default input/output de Windows mientras un stream corre, reiniciar el pipeline con el nuevo default en vez de quedar mudo.

Contexto: roadmap v1.2, no iniciado. Distinto del hotplug ya manejado. Usar el mecanismo de notificación de dispositivos (IMMNotificationClient / pywin32) o un poll de `sd.query_devices` default como fallback simple y testeable.

- [ ] **Step 1: Read** cómo AudioEngine arranca/registra streams y cómo se obtiene el default device. Diseñar el watcher (preferir un poll ligero del default device id como enfoque testeable; documentar el POR QUÉ si se usa poll en vez de callback COM).
- [ ] **Step 2: Test** — simular cambio de default (inyectar/monkeypatch el proveedor de default device) y afirmar que el engine reinicia el target con el nuevo id.
- [ ] **Step 3: Implement** — watcher + reinicio idempotente (reusar la invariante anti-huérfano de AudioEngine.start). No reiniciar si el default no cambió.
- [ ] **Step 4:** pytest → verde. Commit — `feat(audio): reiniciar el pipeline automáticamente al cambiar el dispositivo por defecto`

---

### Task 6: /feeder/status expone strength + input_device_id, y Simple.tsx reconcilia (rank 15)

**Files:** `backend/stfu/audio/engine.py` (o capture) para trackear estado, `backend/stfu/api/routes/feeder.py`, `frontend/src/pages/Simple.tsx`, test backend.

**Interfaces:** `feeder_status()` retorna además `strength` (del plugin activo) y `input_device_id` del stream corriendo (o null si no corre). Simple.tsx, en su efecto de reconciliación, hace `setStrength`/`setSelectedInput` desde esos valores cuando el feeder arrancó fuera de sesión.

Contexto: hoy retorna bridge_present/active/playback_active pero no strength/input, así que tras un reload o arranque out-of-session el slider/picker muestran valores stale.

- [ ] **Step 1: Read** engine (cómo trackea el stream), feeder.py (feeder_status), Simple.tsx (efecto de reconciliación con ["feeder-status"]).
- [ ] **Step 2: Test backend** — arrancar feeder con strength X e input Y; GET /feeder/status retorna strength=X, input_device_id=Y; sin stream → null.
- [ ] **Step 3: Implement** — engine trackea strength+input del stream activo (el strength sale del parámetro del plugin NC en index 0); endpoint lo retorna; Simple.tsx reconcilia (solo cuando no está en medio de una acción del usuario — respetar micBusy).
- [ ] **Step 4:** pytest backend verde + `npm run type-check`/`build` verdes. Commit — `feat(feeder): exponer strength e input_device_id en /feeder/status y reconciliar el Control`

---

### Task 7: Split de `capture.py` en submódulos (rank 17)

**Files:** `backend/stfu/audio/capture.py` → `stream_lifecycle.py` / `worker.py` / `stats.py` (o similar), imports actualizados, tests siguen verdes.

**Interfaces:** refactor sin cambio de comportamiento. `CaptureThread` sigue exportado desde donde lo consumen engine/tests. Separar: lifecycle de stream (open/close/reconnect), worker (proceso de chunks + swap), stats/telemetría.

Contexto: capture.py ~371 LOC, 4 threads/4 responsabilidades. Refactor de mantenibilidad puro. **Correr DESPUÉS de T5/T6** si esos tocaron capture.py, para no chocar.

- [ ] **Step 1: Read** capture.py completo. Mapear responsabilidades.
- [ ] **Step 2: Implement** — extraer submódulos con dependencias explícitas; mantener la API pública (`CaptureThread`, `.stats`, `.set_bypass`, etc.) idéntica. Sin cambios de lógica.
- [ ] **Step 3:** correr TODA la suite backend → 311 verde (el refactor no cambia comportamiento). Commit — `refactor(audio): dividir capture.py en lifecycle/worker/stats`

---

### Task 8: UI de telemetría por etapa (rank 7)

**Files:** `frontend/src/services/api.ts` (tipos si faltan), `frontend/src/pages/Simple.tsx` (o un componente nuevo `StageMeter.tsx`), tipos.

**Interfaces:** consumir `status.streams[target].stages[] = {stage, ema_ms, p95_ms, budget_ms, overbudget}` (ya en StreamStats) y mostrar por plugin: nombre, ema/p95 ms, y si está overbudget (color). Compacto.

Contexto: backend expone `stages[]` desde F1 (testeado); Simple.tsx solo muestra `latency_ms` total. **Correr DESPUÉS de T6** (ambos tocan Simple.tsx).

- [ ] Implement un bloque/collapsible que liste las etapas del feeder activo con ema/p95 y un indicador overbudget (Badge red cuando overbudget>0). type-check + build verdes. Commit — `feat(ui): mostrar telemetría por etapa (ema/p95/budget por plugin)`

---

### Task 9: Progreso de descarga por WebSocket (rank 12)

**Files:** `backend/stfu/api/routes/models.py` (o hub), `backend/stfu/hub/*`, `frontend/src/services/api.ts`, `frontend/src/pages/Models.tsx`, tests.

**Interfaces:** la descarga (hf_hub_download / httpx.stream) emite progreso (bytes/total o %) por una WS o por polling de un job; Models.tsx muestra una barra real en vez del spinner indeterminado.

Contexto: la descarga funciona (F4 smoke) pero es síncrona/bloqueante; spec §4.3 prometía "job con progreso por WebSocket". Elegir el enfoque más simple y testeable: un job en background con estado consultable + WS que emite %; o si httpx.stream, emitir por WS los bytes leídos. Mantener el endpoint actual funcionando (compat).

- [ ] **Step 1: Read** el endpoint de download actual + hub download. Diseñar: job con id + progreso (dict en memoria) + WS `/ws/download/{id}` o polling `/models/{id}/download/progress`. Preferir WS para cumplir el spec; documentar el POR QUÉ.
- [ ] **Step 2: Test backend** — mockear la descarga para emitir progreso; afirmar que el estado avanza 0→100 y termina installed=true.
- [ ] **Step 3: Implement** backend (job + progreso) + Models.tsx (barra de progreso real consumiendo el stream). Cancelación no requerida.
- [ ] **Step 4:** pytest + type-check + build verdes. Commit — `feat(models): progreso de descarga en vivo por WebSocket con barra real en la UI`

---

### Task 10: Add/remove de plugins de la cadena en vivo, sin reiniciar el feeder (rank 13)

**Files:** `backend/stfu/core/pipeline.py` (add/remove plugin en vivo), `backend/stfu/audio/engine.py` (+ capture worker swap), `backend/stfu/api/routes/feeder.py` (endpoints), `frontend/src/components/ChainEditor.tsx` / `Studio.tsx`, tests.

**Interfaces:** hoy `Pipeline.replace_plugin` (swap 1:1) existe y es surgical; falta `insert_plugin(index, cfg)` y `remove_plugin(index)` aplicados vía el worker entre chunks sin cortar el stream. Endpoints `/feeder/plugin` (POST insert, DELETE remove) que hagan el swap en vivo. ChainEditor usa esos endpoints cuando el stream está activo, en vez de reiniciar.

Contexto: agregar/quitar plugins reinicia el feeder (corte breve), deferido explícitamente en v1.6. El swap surgical de 1 plugin ya está probado — extender el mismo mecanismo request_plugin_swap a insert/remove.

- [ ] **Step 1: Read** pipeline.py (replace_plugin), capture worker (request_plugin_swap), engine (set_parameter/swap_model), ChainEditor (onApply/updateParam). Diseñar insert/remove análogos al swap (construir el plugin nuevo + warmup fuera del worker; el worker aplica el cambio de lista entre chunks bajo el patrón atómico existente).
- [ ] **Step 2: Test backend** — pipeline insert/remove mantiene el resto de la cadena y el formato; engine aplica en vivo; endpoints responden.
- [ ] **Step 3: Implement** backend (pipeline + engine + rutas) y frontend (ChainEditor: si `liveEditable`/stream activo, insertar/quitar en vivo vía endpoint; si no, comportamiento actual). Actualizar el texto de ayuda (ya no todo requiere re-aplicar).
- [ ] **Step 4:** pytest + type-check + build verdes. Commit — `feat(pipeline): insertar y quitar plugins de la cadena en vivo sin reiniciar el stream`

---

### Task 11: Hotkey global del SO para A/B bypass y Modo música (rank 11)

**Files:** `frontend/src-tauri/` (plugin tauri global-shortcut: Cargo.toml, capabilities/permissions, lib.rs/main.rs), `frontend/src/` (registrar y reaccionar), `frontend/src-tauri/tauri.conf.json` si aplica.

**Interfaces:** registrar un atajo global OS (ej. Ctrl+Alt+M para A/B, y opcional otro para Modo música) vía `@tauri-apps/plugin-global-shortcut`, que dispare el toggle aunque STFU no tenga foco. El evento llega al frontend (o invoca el comando) y ejecuta el mismo `feederBypass`/Music Mode.

Contexto: el spacebar A/B (9035234) solo funciona con la ventana enfocada; el registro OS-wide fue out-of-scope de v1.6. Este toca Rust (Tauri) + JS.

- [ ] **Step 1: Read** la config Tauri actual (tauri.conf.json, src-tauri/lib.rs o main.rs, capabilities). Investigar el plugin global-shortcut de Tauri 2 (agregar dep Rust + JS + permiso en capabilities).
- [ ] **Step 2: Implement** — registrar el/los atajo(s) global(es); al dispararse, invocar el toggle de bypass (y Modo música) reutilizando la lógica del frontend (emitir evento → handler que llama `api.feederBypass`). Atajo(s) sensatos y documentados; evitar colisiones comunes.
- [ ] **Step 3: Verify** — `npm run build` (incluye `tsc`) verde; el build Tauri se valida en la fase de release (no reconstruir el instalador acá). Documentar el atajo en el README (junto a Task 1) o en un texto de ayuda del Control.
- [ ] **Step 4: Commit** — `feat(hotkey): atajo global del SO para A/B bypass y Modo música (tauri global-shortcut)`

---

### Task 12: Minors de F3 + verdad de docs de componentes + backlog futuro documentado (rank 8, 9, 10, 16 + done-verify)

**Files:** `backend/stfu/services/*` / `apo/*` (minors F3), `backend/stfu/*/ep_router.py` (mensaje NPU), `apo/README.md`, `driver/README.md`, `docs/superpowers/audits/2026-08-19-ab-modelos.md` (nuevo), tests.

**Interfaces:** varios cierres pequeños. Agrupados por ser de bajo riesgo y mayormente independientes.

- [ ] **F3 minors (rank 16):** batchear el restart de audiosrv en `repair_registrations` (un solo bounce en vez de uno por endpoint); resolver la colisión de nombre `register.check_registrations` vs `health.check_registrations`; `needs_repair()` que nombre el/los endpoint(s) que fallan en vez de un `any()` opaco; agregar un health-check al arranque del backend. Tests que cubran el batch del restart y el reporte por-endpoint. (Leer el código real de F3 antes; ajustar nombres a lo que exista.)
- [ ] **NPU messaging (rank 10):** en `ep_router.py`, cambiar el docstring/mensaje "NPU llega en F2.5" por el estado real (diferido indefinidamente por model-fit; ver audit 2026-08-18). No agregar EP de NPU. (UI de "NPU: no disponible (sin modelo compatible)" es OPCIONAL — omitir si agrega complejidad; dejar nota en el audit.)
- [ ] **Docs de componentes (rank 8):** `apo/README.md` — reflejar que el auto-repair (health.py + repair_registrations + /apo/repair + ApoHealthMonitor) ya está shipped. `driver/README.md` — marcar el driver v2 como **PAUSADO** y marcar como hechos los pasos ya completados (compile/test-sign/rename/loopback).
- [ ] **A/B decision doc (rank 9):** crear `docs/superpowers/audits/2026-08-19-ab-modelos.md` con la decisión del modelo por defecto y por qué. Si `backend/scripts/ab_models.py` corre rápido y sin descargas pesadas, incluir su tabla RTF; si no, documentar la decisión (fastenhancer-tiny como floor/default, base como calidad) con el razonamiento del audit existente.
- [ ] **done-verify → verdad (rank 23-28):** confirmar por lectura que shm bridge (`apo/src/spsc_ring.h`, `pipe_worker.*`) reemplazó el polling, que Models.tsx (F4) existe, y que la suite backend está verde (correr pytest -q y anotar el conteo). Reflejar cualquier corrección en el README de Task 1 si algo difiere.
- [ ] Correr pytest → verde; commit — `chore(v17): minors de F3, mensajería NPU real, verdad de READMEs de componentes y doc de decisión de modelo`

---

### Task 13: Verificación de release (build + smoke) + backlog futuro

- [ ] **Step 1: Build backend** — `backend/.venv/Scripts/python -m PyInstaller stfu-backend.spec --clean --noconfirm` (deja `backend/dist/stfu-backend`).
- [ ] **Step 2: Build instalador** — `tauri build` vía **VS DevShell del install BuildTools** (el toolset Community está roto — ver `~/.claude/.../memory/reference_stfu_tauri_build_vcvars.md`): script pwsh con `Enter-VsDevShell -VsInstallPath "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools" ...` → `npx tauri build`. Verificar `STFU_1.7.0_x64-setup.exe`.
- [ ] **Step 3: Smoke** — arrancar uvicorn :8765; `curl /status` (salud cacheada), `/feeder/status` (nuevos campos), `/plugins`, `/presets`; matar. Verificar suite backend verde.
- [ ] **Step 4: Backlog futuro documentado** — dejar en el README/roadmap la lista de lo NO hecho y por qué: STFT lineup (rank 14, necesita modelos+diseño), Monitor Mode/Studio Voice/live captions/per-app capture/community hub (v1.7+/v3, sin diseñar), NPU (bloqueado por modelo), driver v2 (pausado). Commit de cierre si queda algo.
