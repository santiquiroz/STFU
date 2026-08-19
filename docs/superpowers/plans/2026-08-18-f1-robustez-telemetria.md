# F1 — Robustez + Telemetría per-stage: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar los gaps de robustez del backend (worker que muere en silencio, teardown muerto, stop no cancelable del pipe server, device matching frágil) y agregar telemetría por etapa del pipeline expuesta en `/status` y `/ws/metering`.

**Architecture:** La telemetría vive en `Pipeline.process()` — único seam que cubre el path WASAPI (CaptureThread) y el path APO (ApoPipeServer) a la vez. Un `StageMetrics` por etapa con EMA + p95 sobre ventana rodante, un solo hilo escritor (el worker), lecturas snapshot sin lock. La robustez del worker convierte excepciones de plugin en estado `pipeline_failed` visible + passthrough, nunca muerte silenciosa.

**Tech Stack:** Python 3.11+, numpy, sounddevice, pywin32, FastAPI, pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-18-stfu-modernization-design.md` (§5.1-6, §6)

## Global Constraints

- Windows-only; tests que requieren pywin32/pipes reales se marcan `@pytest.mark.skipif(sys.platform != "win32", ...)`.
- Correr tests desde `backend/`: `.\.venv\Scripts\python.exe -m pytest` (pytest config en `pyproject.toml`, `testpaths=["tests"]`).
- Los tests existentes (test_pipeline, test_adapter, test_transport) deben quedar verdes en cada task — son la red de seguridad del refactor.
- Commits en español, formato convencional (`fix:`, `feat:`, `test:`). Sin línea `Co-Authored-By`.
- Callbacks de PortAudio: solo copiar memoria, jamás locks largos ni alocaciones grandes.
- No cambiar la forma de respuestas de API que el frontend ya consume, salvo agregar claves nuevas.

---

### Task 1: `StageMetrics` — métricas de una etapa

**Files:**
- Create: `backend/stfu/core/telemetry.py`
- Test: `backend/tests/test_telemetry.py`

**Interfaces:**
- Produces: `StageMetrics(name: str, budget_ms: float, window: int = 256)` con `.record(elapsed_ms: float) -> None` y `.snapshot() -> dict` (claves: `stage`, `ema_ms`, `p95_ms`, `budget_ms`, `overbudget`). Task 2 lo consume desde `Pipeline`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_telemetry.py
from stfu.core.telemetry import StageMetrics


def test_snapshot_empty():
    m = StageMetrics("nc", budget_ms=20.0)
    snap = m.snapshot()
    assert snap == {"stage": "nc", "ema_ms": 0.0, "p95_ms": 0.0, "budget_ms": 20.0, "overbudget": 0}


def test_ema_converges_toward_recent_values():
    m = StageMetrics("nc", budget_ms=20.0)
    for _ in range(200):
        m.record(10.0)
    assert abs(m.snapshot()["ema_ms"] - 10.0) < 0.1


def test_p95_over_window():
    m = StageMetrics("nc", budget_ms=20.0, window=100)
    for v in range(100):  # 0..99 ms
        m.record(float(v))
    assert m.snapshot()["p95_ms"] == 95.0


def test_overbudget_counts_samples_above_budget():
    m = StageMetrics("nc", budget_ms=20.0)
    m.record(19.0)
    m.record(21.0)
    m.record(25.0)
    assert m.snapshot()["overbudget"] == 2


def test_window_is_rolling():
    m = StageMetrics("nc", budget_ms=1000.0, window=10)
    for _ in range(10):
        m.record(100.0)
    for _ in range(10):
        m.record(1.0)  # desplaza todas las muestras viejas
    assert m.snapshot()["p95_ms"] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_telemetry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'stfu.core.telemetry'`

- [ ] **Step 3: Write the implementation**

```python
# backend/stfu/core/telemetry.py
from collections import deque

_EMA_ALPHA = 0.1


class StageMetrics:
    """Métricas de una etapa del pipeline.

    Un solo hilo escribe (el worker del pipeline); las lecturas desde el hilo
    de API son snapshots sin lock — GIL + deque(maxlen) lo hacen seguro con
    un único escritor. El p95 se calcula al leer, nunca en el hot path.
    """

    def __init__(self, name: str, budget_ms: float, window: int = 256) -> None:
        self.name = name
        self.budget_ms = budget_ms
        self._samples: deque[float] = deque(maxlen=window)
        self._ema_ms: float = 0.0
        self._overbudget: int = 0

    def record(self, elapsed_ms: float) -> None:
        self._samples.append(elapsed_ms)
        self._ema_ms = (
            elapsed_ms if self._ema_ms == 0.0
            else _EMA_ALPHA * elapsed_ms + (1.0 - _EMA_ALPHA) * self._ema_ms
        )
        if elapsed_ms > self.budget_ms:
            self._overbudget += 1

    def snapshot(self) -> dict:
        ordered = sorted(self._samples)
        p95 = ordered[int(len(ordered) * 0.95)] if ordered else 0.0
        return {
            "stage": self.name,
            "ema_ms": round(self._ema_ms, 3),
            "p95_ms": round(p95, 3),
            "budget_ms": self.budget_ms,
            "overbudget": self._overbudget,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_telemetry.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/core/telemetry.py backend/tests/test_telemetry.py
git commit -m "feat: StageMetrics — EMA, p95 rodante y contador overbudget por etapa"
```

---

### Task 2: Instrumentación del `Pipeline`

**Files:**
- Modify: `backend/stfu/core/pipeline.py`
- Test: `backend/tests/test_pipeline_telemetry.py`

**Interfaces:**
- Consumes: `StageMetrics` (Task 1).
- Produces: `Pipeline.stage_metrics() -> list[dict]` (snapshots por etapa, en orden de cadena). Tasks 3, 5 y 7 lo consumen. `compile()` crea las métricas; el budget de cada etapa = duración del chunk del formato de entrada (`chunk_samples / sample_rate * 1000`).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_pipeline_telemetry.py
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.plugins.base import AudioPlugin, Parameter


class _SleeplessPlugin(AudioPlugin):
    """Plugin passthrough para medir instrumentación, no duración real."""
    name = "sleepless"
    version = "1.0"

    @property
    def preferred_format(self):
        return AudioFormat(48000, 1, 480)

    def setup(self, fmt):
        return fmt

    def process(self, audio):
        return audio

    def teardown(self):
        pass

    @property
    def algorithmic_latency_ms(self):
        return 0.0

    @property
    def parameters(self):
        return []


def _fmt():
    return AudioFormat(sample_rate=48000, channels=1, chunk_samples=480)


def test_stage_metrics_empty_before_compile():
    p = Pipeline()
    assert p.stage_metrics() == []


def test_stage_metrics_one_entry_per_plugin():
    p = Pipeline()
    p.add_plugin(_SleeplessPlugin())
    p.add_plugin(_SleeplessPlugin())
    p.compile(_fmt())
    metrics = p.stage_metrics()
    assert len(metrics) == 2
    assert all(m["stage"] == "sleepless" for m in metrics)


def test_budget_is_chunk_duration_of_input_format():
    p = Pipeline()
    p.add_plugin(_SleeplessPlugin())
    p.compile(_fmt())  # 480/48000 = 10ms
    assert p.stage_metrics()[0]["budget_ms"] == 10.0


def test_process_records_samples():
    p = Pipeline()
    p.add_plugin(_SleeplessPlugin())
    fmt = _fmt()
    p.compile(fmt)
    chunk = np.zeros((fmt.chunk_samples, fmt.channels), dtype=np.float32)
    for _ in range(5):
        p.process(chunk)
    snap = p.stage_metrics()[0]
    assert snap["ema_ms"] >= 0.0
    assert snap["p95_ms"] >= 0.0


def test_recompile_resets_metrics():
    p = Pipeline()
    p.add_plugin(_SleeplessPlugin())
    fmt = _fmt()
    p.compile(fmt)
    p.process(np.zeros((fmt.chunk_samples, fmt.channels), dtype=np.float32))
    p.compile(fmt)
    assert p.stage_metrics()[0]["overbudget"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pipeline_telemetry.py -v`
Expected: FAIL — `AttributeError: 'Pipeline' object has no attribute 'stage_metrics'`

- [ ] **Step 3: Implement**

En `backend/stfu/core/pipeline.py`:

Imports (arriba del archivo):

```python
from time import perf_counter
from stfu.core.telemetry import StageMetrics
```

En `__init__`, agregar:

```python
        self._stage_metrics: list[StageMetrics] = []
```

En `clear()`, agregar tras `self._stages.clear()`:

```python
        self._stage_metrics.clear()
```

En `compile()`, tras `self._input_format = input_format`:

```python
        budget_ms = input_format.chunk_samples / input_format.sample_rate * 1000.0
        self._stage_metrics = [
            StageMetrics(p.name, budget_ms=budget_ms) for p in self._plugins
        ]
```

Reemplazar `process()` completo:

```python
    def process(self, audio: np.ndarray) -> np.ndarray:
        if not self._plugins:
            return audio
        chunks: list[np.ndarray] = [audio]
        for (adapter, plugin), metrics in zip(self._stages, self._stage_metrics):
            t0 = perf_counter()
            chunks = self._run_stage(adapter, plugin, chunks)
            metrics.record((perf_counter() - t0) * 1000.0)
        self._push_output(chunks)
        return self._pop_output()
```

Agregar método:

```python
    def stage_metrics(self) -> list[dict]:
        return [m.snapshot() for m in self._stage_metrics]
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pipeline_telemetry.py tests/test_pipeline.py -v`
Expected: todos PASS (los tests viejos de pipeline no deben romper)

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/core/pipeline.py backend/tests/test_pipeline_telemetry.py
git commit -m "feat: telemetría per-stage en Pipeline.process — cubre path WASAPI y APO"
```

---

### Task 3: Worker robusto — `pipeline_failed` + passthrough

**Files:**
- Modify: `backend/stfu/audio/capture.py`
- Test: `backend/tests/test_capture_worker.py`

**Interfaces:**
- Consumes: `Pipeline.stage_metrics()` (Task 2).
- Produces: `CaptureThread.stats` gana claves `"pipeline_failed": bool`, `"stages": list[dict]`, `"total_latency_ms": float`. Task 5 las expone en `/status`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_capture_worker.py
import queue
import numpy as np
import pytest
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.capture import CaptureThread
from stfu.plugins.base import AudioPlugin


class _ExplodingPlugin(AudioPlugin):
    name = "exploding"
    version = "1.0"

    @property
    def preferred_format(self):
        return AudioFormat(48000, 2, 960)

    def setup(self, fmt):
        return fmt

    def process(self, audio):
        raise RuntimeError("boom")

    def teardown(self):
        pass

    @property
    def algorithmic_latency_ms(self):
        return 0.0

    @property
    def parameters(self):
        return []


def _thread_with(pipeline: Pipeline) -> CaptureThread:
    fmt = AudioFormat(sample_rate=48000, channels=2, chunk_samples=960)
    pipeline.compile(fmt)
    return CaptureThread(
        input_device_id=0, output_device_id=0, fmt=fmt,
        pipeline=pipeline, out_channels=2,
    )


def test_plugin_exception_marks_failed_and_passes_audio_through():
    pipeline = Pipeline()
    pipeline.add_plugin(_ExplodingPlugin())
    t = _thread_with(pipeline)
    chunk = np.ones((960, 2), dtype=np.float32)

    out = t._process_or_passthrough(chunk)

    assert t.stats["pipeline_failed"] is True
    np.testing.assert_array_equal(out, chunk)  # passthrough, no silencio


def test_failed_state_skips_pipeline_on_next_chunks():
    pipeline = Pipeline()
    pipeline.add_plugin(_ExplodingPlugin())
    t = _thread_with(pipeline)
    chunk = np.ones((960, 2), dtype=np.float32)
    t._process_or_passthrough(chunk)  # primera: explota y marca failed
    out = t._process_or_passthrough(chunk)  # segunda: ni intenta
    np.testing.assert_array_equal(out, chunk)


def test_healthy_pipeline_reports_stats_shape():
    pipeline = Pipeline()
    t = _thread_with(pipeline)
    s = t.stats
    assert s["pipeline_failed"] is False
    assert s["stages"] == []
    assert s["total_latency_ms"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capture_worker.py -v`
Expected: FAIL — `AttributeError: ... '_process_or_passthrough'`

- [ ] **Step 3: Implement**

En `backend/stfu/audio/capture.py`:

En `__init__`, junto a `self._latency_ms`:

```python
        self._pipeline_failed = False
```

En `_worker_loop`, reemplazar las tres líneas del timing (`t0 = ...`, `processed = ...`, `self._latency_ms = ...`) por:

```python
            processed = self._process_or_passthrough(chunk)
```

Agregar método (después de `_worker_loop`):

```python
    def _process_or_passthrough(self, chunk: np.ndarray) -> np.ndarray:
        """Una excepción de plugin no mata el worker: marca el estado y el
        audio sigue fluyendo sin procesar hasta que el usuario reinicie."""
        if self._pipeline_failed:
            return chunk
        t0 = time.perf_counter()
        try:
            processed = self._pipeline.process(chunk)
        except Exception:
            _log.exception("pipeline crashed; el target continúa en passthrough")
            self._pipeline_failed = True
            return chunk
        self._latency_ms = (time.perf_counter() - t0) * 1000.0
        return processed
```

En `stats`, agregar al dict:

```python
            "pipeline_failed": self._pipeline_failed,
            "stages": self._pipeline.stage_metrics(),
            "total_latency_ms": round(self._pipeline.total_latency_ms(), 2),
```

Nota sobre contadores: `_input_overflows`/`_queue_drops` los escribe solo el callback de entrada y `_output_underflows` solo el de salida — un único hilo escritor por contador, el GIL garantiza que no se pierden incrementos. Documentarlo con este comentario sobre el bloque de contadores en `__init__`:

```python
        # Invariante: cada contador tiene UN solo hilo escritor (input CB o
        # output CB); con el GIL los += no pierden updates. No agregar
        # escritores sin repensar esto.
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capture_worker.py tests/test_capture_stats.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/audio/capture.py backend/tests/test_capture_worker.py
git commit -m "fix: excepción de plugin ya no mata el worker — estado pipeline_failed + passthrough"
```

---

### Task 4: Teardown real en stop

**Files:**
- Modify: `backend/stfu/audio/capture.py` (método `stop`)
- Modify: `backend/stfu/apo/apo_engine.py` (métodos `stop`, `stop_all`)
- Test: `backend/tests/test_teardown_wiring.py`

**Interfaces:**
- Consumes: `Pipeline.clear()` (existente — llama `teardown()` de cada plugin).
- Produces: garantía de que `CaptureThread.stop()` y `ApoEngine.stop/stop_all` liberan los modelos (cierre del item 🟡 de la auditoría 2026-07-02: modelo torch residente + recarga por start).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_teardown_wiring.py
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.capture import CaptureThread
from stfu.plugins.base import AudioPlugin


class _CountingPlugin(AudioPlugin):
    name = "counting"
    version = "1.0"
    teardown_calls = 0

    @property
    def preferred_format(self):
        return AudioFormat(48000, 2, 960)

    def setup(self, fmt):
        return fmt

    def process(self, audio):
        return audio

    def teardown(self):
        type(self).teardown_calls += 1

    @property
    def algorithmic_latency_ms(self):
        return 0.0

    @property
    def parameters(self):
        return []


def test_capture_stop_tears_down_plugins():
    _CountingPlugin.teardown_calls = 0
    fmt = AudioFormat(sample_rate=48000, channels=2, chunk_samples=960)
    pipeline = Pipeline()
    pipeline.add_plugin(_CountingPlugin())
    pipeline.compile(fmt)
    t = CaptureThread(input_device_id=0, output_device_id=0, fmt=fmt,
                      pipeline=pipeline, out_channels=2)
    # stop() sin start(): streams None, worker None — debe limpiar igual
    t.stop()
    assert _CountingPlugin.teardown_calls == 1
```

Para `ApoEngine` el server real necesita pywin32 y un pipe: testear la unidad con un doble:

```python
class _FakeServer:
    def __init__(self):
        self.pipeline = Pipeline()
        self.pipeline.add_plugin(_CountingPlugin())
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_apo_engine_stop_tears_down(monkeypatch):
    from stfu.apo.apo_engine import ApoEngine
    _CountingPlugin.teardown_calls = 0
    eng = ApoEngine()
    fake = _FakeServer()
    eng._servers["capture"] = fake
    eng.stop("capture")
    assert fake.stopped is True
    assert _CountingPlugin.teardown_calls == 1


def test_apo_engine_stop_all_tears_down():
    from stfu.apo.apo_engine import ApoEngine
    _CountingPlugin.teardown_calls = 0
    eng = ApoEngine()
    eng._servers["capture"] = _FakeServer()
    eng._servers["render"] = _FakeServer()
    eng.stop_all()
    assert _CountingPlugin.teardown_calls == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_teardown_wiring.py -v`
Expected: FAIL — `teardown_calls == 0`

- [ ] **Step 3: Implement**

`capture.py`, al final de `stop()` (tras el join del worker):

```python
        self._pipeline.clear()
```

`apo_engine.py`, `stop()`:

```python
    def stop(self, flow: str) -> None:
        with self._lock:
            server = self._servers.pop(flow, None)
        if server:
            server.stop()
            server.pipeline.clear()
```

`apo_engine.py`, `stop_all()`:

```python
    def stop_all(self) -> None:
        with self._lock:
            servers = list(self._servers.values())
            self._servers.clear()
        for s in servers:
            s.stop()
            s.pipeline.clear()
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_teardown_wiring.py tests/test_pipeline.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/audio/capture.py backend/stfu/apo/apo_engine.py backend/tests/test_teardown_wiring.py
git commit -m "fix: stop() libera los plugins — teardown deja de ser código muerto"
```

---

### Task 5: `/status` completo + `/ws/metering` unificado

**Files:**
- Modify: `backend/stfu/main.py`
- Test: `backend/tests/test_status_api.py`

**Interfaces:**
- Consumes: `stats` extendido (Task 3) vía `engine.get_stats()`.
- Produces: `/status` retorna además `apo` (estado por flow, Task 7 lo completa con liveness real); `/ws/metering` envía exactamente el mismo payload que `/status` (las superficies dejan de divergir). El frontend actual lee `latency_ms`/`active` — se conservan.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_status_api.py
from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)


def test_status_shape():
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"status", "latency_ms", "active", "streams", "apo"}


def test_metering_ws_sends_same_shape_as_status():
    with client.websocket_connect("/ws/metering") as ws:
        msg = ws.receive_json()
    assert set(msg) >= {"status", "latency_ms", "active", "streams", "apo"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_status_api.py -v`
Expected: FAIL — falta `apo` en `/status` y el WS manda payload reducido

- [ ] **Step 3: Implement**

En `backend/stfu/main.py`, reemplazar `status()` y `ws_metering()`:

```python
def _status_payload() -> dict:
    from stfu.apo.apo_engine import apo_engine
    return {
        "status": "ok",
        "latency_ms": engine.get_latency_ms(),
        "active": engine.active_targets(),
        "streams": engine.get_stats(),
        "apo": apo_engine.status(),
    }


@app.get("/status")
def status():
    return _status_payload()


@app.websocket("/ws/metering")
async def ws_metering(websocket: WebSocket):
    await metering_ws(websocket, _status_payload)
```

(El import de `apo_engine` es inline como en `lifespan` — evita el ciclo en el arranque.)

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_status_api.py tests/test_api.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/main.py backend/tests/test_status_api.py
git commit -m "feat: /status con stages y estado APO; /ws/metering unificado con /status"
```

---

### Task 6: `ApoPipeServer.stop()` cancelable + accept loop robusto

**Files:**
- Modify: `backend/stfu/apo/pipe_server.py`
- Test: `backend/tests/test_apo_pipe_lifecycle.py`

**Interfaces:**
- Produces: `ApoPipeServer.is_alive -> bool` (Task 7 lo consume); `stop()` retorna con el thread joineado (ya no filtra el handle bloqueado en `ConnectNamedPipe`).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_apo_pipe_lifecycle.py
import sys
import time
import pytest
from stfu.core.pipeline import Pipeline

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="named pipes")

_PIPE = r"\\.\pipe\stfu_test_lifecycle"


def test_stop_unblocks_accept_and_joins():
    from stfu.apo.pipe_server import ApoPipeServer
    server = ApoPipeServer(_PIPE, Pipeline())
    server.start()
    time.sleep(0.2)  # el accept loop queda bloqueado en ConnectNamedPipe
    assert server.is_alive is True
    t0 = time.perf_counter()
    server.stop()
    assert time.perf_counter() - t0 < 3.0  # no espera un cliente que nunca llega
    assert server.is_alive is False


def test_is_alive_false_before_start():
    from stfu.apo.pipe_server import ApoPipeServer
    server = ApoPipeServer(_PIPE, Pipeline())
    assert server.is_alive is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_pipe_lifecycle.py -v`
Expected: FAIL — `is_alive` no existe; `stop()` no joinea (el primer test cuelga o falla el assert de tiempo)

- [ ] **Step 3: Implement**

En `backend/stfu/apo/pipe_server.py`:

Agregar property y reemplazar `stop()`:

```python
    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        """Stop the named pipe server."""
        self._stop_event.set()
        self._unblock_accept()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _unblock_accept(self) -> None:
        """ConnectNamedPipe es bloqueante: una conexión dummy lo despierta
        para que el accept loop vea el stop_event y salga."""
        try:
            handle = win32file.CreateFile(
                self._pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None, win32file.OPEN_EXISTING, 0, None,
            )
            win32file.CloseHandle(handle)
        except pywintypes.error:
            pass  # nadie escuchando: el accept loop ya salió o nunca arrancó
```

Reemplazar `_accept_loop` (el descriptor de seguridad entra al try; se captura `Exception`, no solo `pywintypes.error`; tras `ConnectNamedPipe` se re-chequea el stop para no tratar la conexión dummy como cliente):

```python
    def _accept_loop(self) -> None:
        """Accept incoming client connections."""
        try:
            sa = _pipe_security_attributes()
        except Exception:
            _log.exception("no se pudo crear el security descriptor del pipe")
            return
        while not self._stop_event.is_set():
            pipe = None
            try:
                pipe = win32pipe.CreateNamedPipe(
                    self._pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    _MAX_MESSAGE, _MAX_MESSAGE, 0, sa,
                )
                win32pipe.ConnectNamedPipe(pipe, None)
                if self._stop_event.is_set():
                    win32file.CloseHandle(pipe)
                    break
                threading.Thread(target=self._handle_client, args=(pipe,), daemon=True).start()
            except Exception:
                _log.exception("pipe accept error")
                if pipe is not None:
                    win32file.CloseHandle(pipe)
```

En `_handle_client`, reemplazar el `except pywintypes.error: pass` final por:

```python
        except pywintypes.error as e:
            _log.debug("cliente APO desconectado: %s", e)
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_pipe_lifecycle.py tests/test_apo_pipe_server.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/apo/pipe_server.py backend/tests/test_apo_pipe_lifecycle.py
git commit -m "fix: stop del pipe server cancela ConnectNamedPipe y joinea; accept loop loguea todo"
```

---

### Task 7: `ApoEngine.status()` refleja liveness real

**Files:**
- Modify: `backend/stfu/apo/apo_engine.py` (método `status`)
- Test: `backend/tests/test_apo_engine_status.py`

**Interfaces:**
- Consumes: `ApoPipeServer.is_alive` (Task 6).
- Produces: `status() -> dict[str, bool]` — misma forma que hoy (`{flow: bool}`, el frontend no cambia) pero el valor es liveness del thread, no membership del dict.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_apo_engine_status.py
from stfu.apo.apo_engine import ApoEngine


class _DeadServer:
    is_alive = False

    def stop(self):
        pass


class _LiveServer:
    is_alive = True

    def stop(self):
        pass


def test_status_reflects_thread_liveness():
    eng = ApoEngine()
    eng._servers["capture"] = _LiveServer()
    eng._servers["render"] = _DeadServer()
    assert eng.status() == {"capture": True, "render": False}


def test_status_empty():
    assert ApoEngine().status() == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_engine_status.py -v`
Expected: FAIL — hoy retorna `{"capture": True, "render": True}`

- [ ] **Step 3: Implement**

```python
    def status(self) -> dict[str, bool]:
        with self._lock:
            return {flow: s.is_alive for flow, s in self._servers.items()}
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_engine_status.py tests/test_api_apo.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/apo/apo_engine.py backend/tests/test_apo_engine_status.py
git commit -m "fix: status del APO engine reporta liveness del pipe thread, no membership"
```

---

### Task 8: Default device por host API, sin comparar nombres

**Files:**
- Modify: `backend/stfu/audio/devices.py`
- Test: `backend/tests/test_devices_defaults.py`

**Interfaces:**
- Produces: `list_devices()` marca `is_default_input/is_default_output` por índice de device del host API WASAPI (`query_hostapis()[wasapi]["default_input_device"]`), no por igualdad de nombre MME truncado. `_default_device_names()` se elimina.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_devices_defaults.py
import sounddevice as sd
from stfu.audio import devices as dev


_HOSTAPIS = [
    {"name": "MME", "default_input_device": 0, "default_output_device": 1},
    {"name": "Windows WASAPI", "default_input_device": 3, "default_output_device": 4},
]

# El nombre MME está truncado (~31 chars) — con matching por nombre el
# default WASAPI jamás matchearía.
_DEVICES = [
    {"name": "Micrófono (USB Audio Device tru", "hostapi": 0, "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 44100.0},
    {"name": "Altavoces (USB Audio Device tru", "hostapi": 0, "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 44100.0},
    {"name": "Otro micrófono WASAPI de nombre largo", "hostapi": 1, "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 48000.0},
    {"name": "Micrófono (USB Audio Device true name)", "hostapi": 1, "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 192000.0},
    {"name": "Altavoces (USB Audio Device true name)", "hostapi": 1, "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000.0},
]


def _patch_sd(monkeypatch):
    monkeypatch.setattr(sd, "query_hostapis", lambda idx=None: _HOSTAPIS if idx is None else _HOSTAPIS[idx])
    monkeypatch.setattr(sd, "query_devices", lambda idx=None: _DEVICES if idx is None else _DEVICES[idx])


def test_default_flags_use_wasapi_hostapi_indices(monkeypatch):
    _patch_sd(monkeypatch)
    result = dev.list_devices()
    by_id = {d.id: d for d in result}
    assert by_id[3].is_default_input is True
    assert by_id[4].is_default_output is True
    assert by_id[2].is_default_input is False


def test_get_default_input_returns_wasapi_default(monkeypatch):
    _patch_sd(monkeypatch)
    assert dev.get_default_input().id == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_devices_defaults.py -v`
Expected: FAIL — con matching por nombre, ningún device WASAPI es default (nombres truncados no matchean)

- [ ] **Step 3: Implement**

En `backend/stfu/audio/devices.py`, eliminar `_default_device_names()` y agregar:

```python
def _default_device_ids(wasapi_idx: int | None) -> tuple[int | None, int | None]:
    """Índices globales del default input/output del host API WASAPI.

    sd.default.device apunta al host API por defecto (MME en Windows, nombres
    truncados a ~31 chars); el host API WASAPI publica sus propios defaults
    con índice global — sin comparar strings."""
    if wasapi_idx is not None:
        try:
            api = sd.query_hostapis(wasapi_idx)
            din = api["default_input_device"]
            dout = api["default_output_device"]
            return (din if din >= 0 else None, dout if dout >= 0 else None)
        except Exception:
            _log.warning("query_hostapis(%s) falló", wasapi_idx, exc_info=True)
    try:
        raw = sd.default.device
        return int(raw[0]), int(raw[1])
    except Exception:
        _log.warning("sd.default.device no disponible", exc_info=True)
        return None, None
```

Agregar arriba del archivo:

```python
import logging

_log = logging.getLogger(__name__)
```

Reemplazar `list_devices()`:

```python
def list_devices() -> list[DeviceInfo]:
    wasapi_idx = _wasapi_index()
    default_in, default_out = _default_device_ids(wasapi_idx)
    result = []
    for i, d in enumerate(sd.query_devices()):
        if wasapi_idx is not None and d["hostapi"] != wasapi_idx:
            continue
        result.append(DeviceInfo(
            id=i,
            name=d["name"],
            channels_in=d["max_input_channels"],
            channels_out=d["max_output_channels"],
            default_sample_rate=int(d["default_samplerate"]),
            is_default_input=(i == default_in),
            is_default_output=(i == default_out),
        ))
    return result
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_devices_defaults.py tests/test_devices.py -v`
Expected: todos PASS. Si `tests/test_devices.py` asumía matching por nombre, actualizar sus mocks al nuevo esquema de hostapi defaults — el comportamiento nuevo es el correcto (regla: no preservar tests que codifican el bug).

- [ ] **Step 5: Verificación manual en hardware real**

Run: `.\.venv\Scripts\python.exe -c "from stfu.audio.devices import get_default_input, get_default_output; print(get_default_input()); print(get_default_output())"`
Expected: el mic y los parlantes que Windows tiene como default, no "el primer device".

- [ ] **Step 6: Commit**

```bash
git add backend/stfu/audio/devices.py backend/tests/test_devices_defaults.py backend/tests/test_devices.py
git commit -m "fix: default device por índices del host API WASAPI — muere el matching por nombre MME truncado"
```

---

### Task 9: Suite completa + verificación E2E ligera

**Files:**
- Ninguno nuevo — verificación integral.

- [ ] **Step 1: Suite completa**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: todos PASS (los 80+ existentes + los nuevos de F1)

- [ ] **Step 2: Smoke con backend real**

```powershell
cd backend; .\.venv\Scripts\python.exe -m uvicorn stfu.main:app --port 8765
# En otra terminal:
curl http://localhost:8765/status
```
Expected: JSON con `streams`, `apo`, y (si se activa el mic desde la UI o vía POST /pipeline/mic) `stages` con `ema_ms`/`p95_ms` reales del DFN3.

- [ ] **Step 3: Commit final de fase (si quedó algo suelto)**

```bash
git status --short   # debe estar limpio; si no, commitear restos con mensaje descriptivo
```
