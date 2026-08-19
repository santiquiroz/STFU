# F3 — APO hardening 24H2 + deuda diferida: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar los tres rulings de deuda diferidos de F2 (race de telemetría en swap, recompile total en swap, EP fallback en runtime) y agregar el hardening del APO contra Windows 11 24H2 (detección de desactivación silenciosa post-update, tolerancia a endpoints fantasma, auto-repair del registro).

**Architecture:** Bloque A es código puro de bajo riesgo sobre `pipeline.py` y `onnx_streaming.py` — reasignaciones en bloque y un swap quirúrgico que preserva buffers. Bloque B agrega un módulo `apo/health.py` que compara los endpoints donde registramos (backups persistidos) contra su estado real en el registro, un health-check periódico en el lifespan que expone `apo_health` en `/status`, y una ruta de auto-repair elevada. La detección corre sin admin (solo lee el registro); la reparación eleva.

**Tech Stack:** Python 3.11+, numpy, winreg (Windows), FastAPI, pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-18-stfu-modernization-design.md` (§3.2, §5.7 parcial, §7)

## Global Constraints

- Base: master post-merge de F1+F2 (merge commit `e57289b`). El driver v2 (`driver/`) NO se toca.
- Windows-only; tests que tocan winreg/registro real se marcan `@pytest.mark.skipif(sys.platform != "win32", ...)` y se mockean con `unittest.mock.patch` sobre `winreg`.
- Correr tests desde `backend/`: `.\.venv\Scripts\python.exe -m pytest` (pytest config en `pyproject.toml`).
- Suite completa verde en cada task (219 tests de base tras el merge de F2 + los del driver v2).
- Commits en español, formato convencional. Sin `Co-Authored-By`.
- No romper la forma de respuestas de API existentes; solo agregar claves nuevas.
- Callbacks de PortAudio: solo copiar memoria. El swap quirúrgico corre en el worker entre chunks (ya establecido en F2).

---

### Task 1: `compile()` reasigna `_stages` en bloque (cierra race de telemetría)

**Files:**
- Modify: `backend/stfu/core/pipeline.py`
- Test: `backend/tests/test_pipeline_compile_atomic.py`

**Interfaces:**
- Sin cambio de firma. `compile()` deja de mutar `self._stages` in-place (`clear()` + `append()` en loop) y en su lugar construye una lista local y la reasigna en una sola operación — como ya hace con `_stage_metrics`. Así un lector concurrente de `total_latency_ms()` (que itera `self._stages` desde el hilo de API) nunca observa una lista truncada durante un swap.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_pipeline_compile_atomic.py
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.plugins.base import AudioPlugin


class _P(AudioPlugin):
    name = "p"
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
        return 5.0

    @property
    def parameters(self):
        return []


def test_recompile_never_exposes_partial_stages():
    p = Pipeline()
    p.add_plugin(_P())
    p.add_plugin(_P())
    fmt = AudioFormat(48000, 1, 480)
    p.compile(fmt)
    # Snapshot de la referencia de _stages antes de recompilar
    before = p._stages
    p.compile(fmt)
    after = p._stages
    # Debe ser un objeto de lista NUEVO (reasignación en bloque), no el mismo
    # mutado in-place — garantiza que un lector con la referencia vieja ve una
    # lista completa y estable, no una truncada a mitad de compile().
    assert after is not before
    assert len(after) == 2
    # la referencia vieja sigue siendo una lista completa de 2 (no fue vaciada)
    assert len(before) == 2


def test_total_latency_stable_after_recompile():
    p = Pipeline()
    p.add_plugin(_P())
    p.add_plugin(_P())
    fmt = AudioFormat(48000, 1, 480)
    p.compile(fmt)
    assert p.total_latency_ms() == 10.0  # 2 plugins × 5ms
    p.compile(fmt)
    assert p.total_latency_ms() == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pipeline_compile_atomic.py -v`
Expected: FAIL en `test_recompile_never_exposes_partial_stages` — `after is not before` es False porque hoy `compile()` hace `self._stages.clear()` (muta la misma lista).

- [ ] **Step 3: Implement**

En `backend/stfu/core/pipeline.py`, reemplazar el cuerpo de `compile()`:

```python
    def compile(self, input_format: AudioFormat) -> None:
        self._input_format = input_format
        self._out_buffer = np.empty((0, input_format.channels), dtype=np.float32)
        budget_ms = input_format.chunk_samples / input_format.sample_rate * 1000.0
        stage_metrics = [
            StageMetrics(p.name, budget_ms=budget_ms) for p in self._plugins
        ]
        stages: list[tuple[Optional[FormatAdapter], AudioPlugin]] = []
        current = input_format
        for plugin in self._plugins:
            pref = plugin.preferred_format
            adapter = FormatAdapter(current, pref) if current != pref else None
            stages.append((adapter, plugin))
            current = plugin.setup(pref if adapter else current)
        # Reasignación en bloque: un lector concurrente (total_latency_ms desde el
        # hilo de API) nunca ve una lista a medio construir.
        self._stages = stages
        self._stage_metrics = stage_metrics
        self._output_adapter = (
            FormatAdapter(current, input_format) if current != input_format else None
        )
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pipeline_compile_atomic.py tests/test_pipeline.py tests/test_pipeline_telemetry.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/core/pipeline.py backend/tests/test_pipeline_compile_atomic.py
git commit -m "fix: compile() reasigna _stages en bloque — sin lista truncada visible durante un swap"
```

---

### Task 2: Swap quirúrgico — `replace_plugin` preserva buffers cuando el formato coincide

**Files:**
- Modify: `backend/stfu/core/pipeline.py`
- Test: `backend/tests/test_pipeline_surgical_swap.py`

**Interfaces:**
- Consumes: `compile()` (Task 1).
- Produces: `replace_plugin(index, plugin)` hace un swap **in-place del stage** cuando el plugin nuevo produce el mismo formato de setup que el viejo (mismo `preferred_format` y mismo formato de salida de `setup()`), sin recompilar ni re-setupear los demás plugins — así los `FormatAdapter` de los stages vecinos conservan su estado (buffer soxr). Si el formato difiere, cae al `compile()` completo (comportamiento actual). El caso común (swap entre modelos NC del mismo rate, o NC como único plugin) toma el camino quirúrgico.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_pipeline_surgical_swap.py
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.plugins.base import AudioPlugin


class _FmtPlugin(AudioPlugin):
    version = "1.0"

    def __init__(self, tag: str, rate: int = 48000):
        self._tag = tag
        self._rate = rate
        self.setup_calls = 0
        self.torn_down = False

    @property
    def name(self):
        return self._tag

    @property
    def preferred_format(self):
        return AudioFormat(self._rate, 1, 480)

    def setup(self, fmt):
        self.setup_calls += 1
        return fmt

    def process(self, audio):
        return audio

    def teardown(self):
        self.torn_down = True

    @property
    def algorithmic_latency_ms(self):
        return 0.0

    @property
    def parameters(self):
        return []


def _compiled(*plugins):
    p = Pipeline()
    for pl in plugins:
        p.add_plugin(pl)
    p.compile(AudioFormat(48000, 1, 480))
    return p


def test_same_format_swap_does_not_resetup_neighbors():
    neighbor = _FmtPlugin("eq", rate=48000)
    old = _FmtPlugin("model-a", rate=48000)
    p = _compiled(old, neighbor)
    neighbor.setup_calls = 0  # resetear el conteo post-compile inicial
    new = _FmtPlugin("model-b", rate=48000)

    p.replace_plugin(0, new)

    assert p._plugins[0] is new
    assert old.torn_down is True
    assert new.setup_calls == 1          # el nuevo se setupea
    assert neighbor.setup_calls == 0     # el vecino NO se re-setupea (buffers intactos)
    assert p.stage_metrics()[0]["stage"] == "model-b"


def test_different_format_swap_falls_back_to_full_recompile():
    neighbor = _FmtPlugin("eq", rate=48000)
    old = _FmtPlugin("model-a", rate=48000)
    p = _compiled(old, neighbor)
    neighbor.setup_calls = 0
    new = _FmtPlugin("model-c", rate=16000)  # rate distinto → adapters cambian

    p.replace_plugin(0, new)

    assert p._plugins[0] is new
    assert new.setup_calls == 1
    assert neighbor.setup_calls == 1     # recompile total re-setupea todo
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pipeline_surgical_swap.py -v`
Expected: FAIL en `test_same_format_swap_does_not_resetup_neighbors` — hoy `replace_plugin` llama `compile()` que re-setupea el vecino (`neighbor.setup_calls == 1`, no 0).

- [ ] **Step 3: Implement**

En `backend/stfu/core/pipeline.py`, reemplazar `replace_plugin`:

```python
    def replace_plugin(self, index: int, plugin: AudioPlugin) -> None:
        """Swap en caliente desde el hilo del worker. Si el plugin nuevo produce
        el mismo formato de setup que el viejo, hace un swap quirúrgico del stage
        sin re-setupear los demás plugins (preserva el buffer de sus adapters).
        Si el formato difiere, recompila todo."""
        if not 0 <= index < len(self._plugins):
            raise IndexError(f"plugin index {index} fuera de rango")
        old = self._plugins[index]
        if self._input_format is None or not self._can_swap_in_place(index, plugin):
            self._plugins[index] = plugin
            old.teardown()
            if self._input_format is not None:
                self.compile(self._input_format)
            return
        adapter, _ = self._stages[index]
        setup_in = adapter.output_format if adapter is not None else self._stage_input_format(index)
        plugin.setup(setup_in)
        self._plugins[index] = plugin
        budget = self._input_format.chunk_samples / self._input_format.sample_rate * 1000.0
        new_stages = list(self._stages)
        new_stages[index] = (adapter, plugin)
        self._stages = new_stages
        new_metrics = list(self._stage_metrics)
        new_metrics[index] = StageMetrics(plugin.name, budget_ms=budget)
        self._stage_metrics = new_metrics
        old.teardown()

    def _stage_input_format(self, index: int) -> AudioFormat:
        """Formato que entra al plugin del stage `index` (sin adapter)."""
        if index == 0:
            return self._input_format
        prev_adapter, prev_plugin = self._stages[index - 1]
        prev_in = prev_adapter.output_format if prev_adapter is not None else self._stage_input_format(index - 1)
        return prev_plugin.preferred_format

    def _can_swap_in_place(self, index: int, plugin: AudioPlugin) -> bool:
        """True si el plugin nuevo tiene el mismo preferred_format que el viejo
        y su setup() no cambia el formato de salida (los adapters vecinos siguen
        siendo válidos). Conservador: ante cualquier duda, False → recompile."""
        old = self._plugins[index]
        if plugin.preferred_format != old.preferred_format:
            return False
        adapter, _ = self._stages[index]
        setup_in = adapter.output_format if adapter is not None else self._stage_input_format(index)
        # Solo estable si el plugin es el último o su formato de salida no altera
        # el adapter siguiente. Se exige que setup() sea idempotente en formato:
        # el contrato de AudioPlugin.setup devuelve el formato de salida; si el
        # nuevo devuelve el mismo que produce el viejo hoy, el stage siguiente no
        # cambia. Como no podemos llamar setup() dos veces sin efecto, se asume
        # estable cuando preferred_format coincide (caso NC modelo↔modelo).
        return True
```

Nota de diseño: `FormatAdapter` debe exponer `output_format`. Si no existe, agregar la property en `adapter.py` (devuelve el formato destino que ya guarda internamente). Verificar con: `grep -n "output_format\|self._dst\|self._to" backend/stfu/core/adapter.py` y exponer el destino como `output_format`.

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pipeline_surgical_swap.py tests/test_model_swap.py tests/test_pipeline.py -v`
Expected: todos PASS. Si `test_model_swap.py` asumía recompile-total en el swap, ajustar sus asserts al comportamiento quirúrgico nuevo (preservar la intención: el swap ocurre y el modelo nuevo queda activo).

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/core/pipeline.py backend/stfu/core/adapter.py backend/tests/test_pipeline_surgical_swap.py
git commit -m "feat: swap quirúrgico — replace_plugin preserva buffers de adapters vecinos si el formato coincide"
```

---

### Task 3: EP fallback en runtime en `OnnxStreamingPlugin`

**Files:**
- Modify: `backend/stfu/plugins/onnx_streaming.py`
- Modify: `backend/stfu/inference/ep_router.py` (helper de escalera)
- Test: `backend/tests/test_onnx_ep_fallback.py`

**Interfaces:**
- Consumes: `ep_router` (Task de F2).
- Produces: `ep_router.remaining_ladder(device: str) -> list[str]` — devuelve los devices de la escalera **por debajo** del actual (para el fallback). `OnnxStreamingPlugin.process()`: si `session.run` lanza un error de runtime del EP, recrea la sesión con el siguiente device de la escalera (probe incluido) y reintenta una vez; si no queda escalera, cae a passthrough dry y marca el estado. Implementa §3.2 ("si una sesión activa lanza error de EP, se recrea con el siguiente EP y se loguea").

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_onnx_ep_fallback.py
from pathlib import Path
import numpy as np
import pytest
from stfu.hub.registry import ModelManifest
from stfu.inference import ep_router
from tests.helpers_onnx import make_streaming_model

_CHUNK = 256


def test_remaining_ladder_below_current():
    assert ep_router.remaining_ladder("gpu") == ["cpu"]
    assert ep_router.remaining_ladder("cpu") == []
    assert ep_router.remaining_ladder("npu") == ["gpu", "cpu"]


@pytest.fixture()
def plugin(tmp_path):
    from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
    model_path = tmp_path / "m.onnx"
    make_streaming_model(model_path, chunk=_CHUNK, state_dim=4)
    m = ModelManifest(
        id="t", name="T", version="1.0",
        plugin_class="stfu.plugins.onnx_streaming.OnnxStreamingPlugin",
        source="local", file="model.onnx",
        preferred_format={"sample_rate": 16000, "channels": 1, "chunk_samples": _CHUNK},
        size_mb=0.01, algorithmic_latency_ms=16.0, tier="floor", license="MIT",
        io_spec={
            "audio_input": {"name": "audio", "shape": [1, "chunk"]},
            "audio_output": "enhanced",
            "states": [{"input": "state_in", "output": "state_out", "shape": [1, 4]}],
        },
    )
    pl = OnnxStreamingPlugin(m, model_path, device="cpu")
    pl.setup(pl.preferred_format)
    return pl


def test_runtime_ep_error_falls_back_to_passthrough_when_no_ladder(plugin, monkeypatch):
    # device cpu → no queda escalera; un error de run cae a dry passthrough.
    chunk = np.ones((_CHUNK, 1), dtype=np.float32)

    def boom(*a, **k):
        raise RuntimeError("EP session crashed")

    monkeypatch.setattr(plugin._session, "run", boom)
    out = plugin.process(chunk)
    np.testing.assert_array_equal(out, chunk)   # dry passthrough, finito
    assert plugin.active_device == "cpu"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_onnx_ep_fallback.py -v`
Expected: FAIL — `remaining_ladder` no existe; `process()` hoy deja propagar el error de `run` (no cae a passthrough).

- [ ] **Step 3: Implement**

En `backend/stfu/inference/ep_router.py`, agregar:

```python
def remaining_ladder(device: str) -> list[str]:
    """Devices por debajo del actual en la escalera fija npu→gpu→cpu, para
    fallback en runtime cuando el EP activo falla."""
    order = ["npu", "gpu", "cpu"]
    if device not in order:
        return []
    return order[order.index(device) + 1:]
```

En `backend/stfu/plugins/onnx_streaming.py`, reemplazar `process()` y `_run`:

```python
    def process(self, audio: np.ndarray) -> np.ndarray:
        if self._session is None:
            return audio
        dry = audio
        try:
            wet = self._run(audio)
        except Exception:
            _log.exception("run de la sesión falló en device %s; intentando fallback", self._active_device)
            if not self._fallback_to_next_device():
                self._session = None
                return dry
            try:
                wet = self._run(audio)
            except Exception:
                _log.exception("run falló también tras fallback; passthrough")
                self._session = None
                return dry
        if not np.isfinite(wet).all():
            self._warn_nan_once()
            return dry
        s = self._strength
        return (wet * s + dry * (1.0 - s)).astype(np.float32, copy=False)

    def _fallback_to_next_device(self) -> bool:
        for candidate in ep_router.remaining_ladder(self._active_device or self._device):
            try:
                providers = ep_router.providers_for(candidate)
            except ep_router.DeviceUnavailable:
                continue
            if self._probe(providers):
                self._active_device = candidate
                _log.warning("EP fallback: sesión recreada en device %s", candidate)
                return True
        return False
```

(Conservar `_warn_nan_once`/`_nan_warned` del fix de F2 y `_run`/`_probe`/`_reset_states` intactos. `_probe` ya deja `self._session` seteada al recrear.)

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_onnx_ep_fallback.py tests/test_onnx_streaming_plugin.py tests/test_ep_router.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/inference/ep_router.py backend/stfu/plugins/onnx_streaming.py backend/tests/test_onnx_ep_fallback.py
git commit -m "feat: EP fallback en runtime — sesión ONNX se recrea en el siguiente device ante fallo del EP activo (§3.2)"
```

---

### Task 4: `apo/health.py` — detección de desactivación y fantasmas

**Files:**
- Create: `backend/stfu/apo/health.py`
- Test: `backend/tests/test_apo_health.py`

**Interfaces:**
- Consumes: `register._load_backups`, `register.get_apo_status`, `endpoint_finder._device_state`, `constants.CLSID_BY_FLOW`.
- Produces:

```python
def check_registrations() -> list[dict]:
    # Para cada endpoint donde registramos (backups), devuelve:
    # {"endpoint_guid": str, "flow": "Capture"|"Render", "state": str}
    # state ∈ {"ok", "deactivated", "endpoint-missing"}:
    #   ok            → nuestro CLSID sigue primero en la cadena de efectos
    #   deactivated   → registramos pero nuestro CLSID ya no está (cumulative
    #                   update lo quitó) — el endpoint sigue existiendo
    #   endpoint-missing → el endpoint ya no está en el registro (driver
    #                   reinstalado / dispositivo removido)

def needs_repair() -> bool:
    # True si algún endpoint registrado está deactivated o endpoint-missing.
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_apo_health.py
from unittest.mock import patch
from stfu.apo import health


_BACKUPS = {
    "{AAAA1111-2222-3333-4444-555566667777}|Capture": ["{OLD-MIC-CLSID}"],
    "{BBBB1111-2222-3333-4444-555566667777}|Render": [],
}


def _patch(status_map, missing=()):
    def fake_status(guid, flow, clsid=None):
        key = f"{guid}|{flow}"
        if key in missing:
            return {"registered": False, "clsid": None}
        return status_map.get(key, {"registered": False, "clsid": None})
    return fake_status


def test_all_ok():
    status = {
        "{AAAA1111-2222-3333-4444-555566667777}|Capture": {"registered": True, "clsid": "x"},
        "{BBBB1111-2222-3333-4444-555566667777}|Render": {"registered": True, "clsid": "y"},
    }
    with patch.object(health, "_load_backups", return_value=_BACKUPS), \
         patch.object(health, "get_apo_status", side_effect=_patch(status)), \
         patch.object(health, "_endpoint_exists", return_value=True):
        result = health.check_registrations()
    assert all(r["state"] == "ok" for r in result)
    assert health_states(result) == {"ok"}


def test_deactivated_after_update():
    status = {
        "{AAAA1111-2222-3333-4444-555566667777}|Capture": {"registered": False, "clsid": None},
        "{BBBB1111-2222-3333-4444-555566667777}|Render": {"registered": True, "clsid": "y"},
    }
    with patch.object(health, "_load_backups", return_value=_BACKUPS), \
         patch.object(health, "get_apo_status", side_effect=_patch(status)), \
         patch.object(health, "_endpoint_exists", return_value=True):
        result = health.check_registrations()
        by_flow = {r["flow"]: r["state"] for r in result}
    assert by_flow["Capture"] == "deactivated"
    assert by_flow["Render"] == "ok"


def test_endpoint_missing_after_driver_reinstall():
    status = {
        "{AAAA1111-2222-3333-4444-555566667777}|Capture": {"registered": False, "clsid": None},
    }
    with patch.object(health, "_load_backups", return_value=_BACKUPS), \
         patch.object(health, "get_apo_status", side_effect=_patch(status)), \
         patch.object(health, "_endpoint_exists", side_effect=lambda g, f: not g.startswith("{AAAA")):
        result = health.check_registrations()
        by_flow = {r["flow"]: r["state"] for r in result}
    assert by_flow["Capture"] == "endpoint-missing"


def test_needs_repair_true_when_any_deactivated():
    with patch.object(health, "check_registrations", return_value=[
        {"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"},
        {"endpoint_guid": "h", "flow": "Render", "state": "ok"},
    ]):
        assert health.needs_repair() is True


def test_needs_repair_false_when_all_ok():
    with patch.object(health, "check_registrations", return_value=[
        {"endpoint_guid": "g", "flow": "Capture", "state": "ok"},
    ]):
        assert health.needs_repair() is False


def health_states(result):
    return {r["state"] for r in result}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_health.py -v`
Expected: FAIL — módulo `stfu.apo.health` no existe.

- [ ] **Step 3: Implement**

```python
# backend/stfu/apo/health.py
"""Salud del registro del APO. Windows 11 24H2 puede desactivar un APO en
silencio tras un cumulative update, y reinstalar un driver de audio borra el
endpoint. Este módulo compara los endpoints donde registramos (backups) contra
su estado real — solo lee el registro, no requiere admin."""
import logging

from stfu.apo.constants import CLSID_BY_FLOW
from stfu.apo.endpoint_finder import _device_state, _flow_key, _STATE_ACTIVE
from stfu.apo.register import _load_backups, get_apo_status

_log = logging.getLogger(__name__)


def _parse_backup_key(key: str) -> tuple[str, str]:
    guid, _, flow = key.rpartition("|")
    return guid, flow


def _endpoint_exists(endpoint_guid: str, flow: str) -> bool:
    return _device_state(_flow_key(flow), endpoint_guid) != -1


def check_registrations() -> list[dict]:
    result = []
    for key in _load_backups():
        endpoint_guid, flow = _parse_backup_key(key)
        if flow not in CLSID_BY_FLOW:
            continue
        if not _endpoint_exists(endpoint_guid, flow):
            state = "endpoint-missing"
        else:
            status = get_apo_status(endpoint_guid, flow, CLSID_BY_FLOW[flow])
            state = "ok" if status.get("registered") else "deactivated"
        result.append({"endpoint_guid": endpoint_guid, "flow": flow, "state": state})
    return result


def needs_repair() -> bool:
    return any(r["state"] != "ok" for r in check_registrations())
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_health.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/apo/health.py backend/tests/test_apo_health.py
git commit -m "feat: apo/health — detecta APO desactivado por update y endpoint borrado por reinstalación de driver"
```

---

### Task 5: `/apo/health` + `apo_health` en `/status`

**Files:**
- Modify: `backend/stfu/api/routes/apo.py`
- Modify: `backend/stfu/main.py`
- Test: `backend/tests/test_apo_health_api.py`

**Interfaces:**
- Consumes: `health.check_registrations`, `health.needs_repair` (Task 4).
- Produces: `GET /apo/health` → `{"needs_repair": bool, "endpoints": [...]}`; `/status` gana la clave `apo_health` con el mismo shape (para que la UI muestre el estado sin un poll extra).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_apo_health_api.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)

_ENDPOINTS = [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}]


def test_apo_health_route():
    with patch("stfu.api.routes.apo.check_registrations", return_value=_ENDPOINTS), \
         patch("stfu.api.routes.apo.health_needs_repair", return_value=True):
        r = client.get("/apo/health")
    assert r.status_code == 200
    body = r.json()
    assert body["needs_repair"] is True
    assert body["endpoints"] == _ENDPOINTS


def test_status_includes_apo_health():
    r = client.get("/status")
    assert r.status_code == 200
    assert "apo_health" in r.json()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_health_api.py -v`
Expected: FAIL — no existe `/apo/health` ni `apo_health` en `/status`.

- [ ] **Step 3: Implement**

En `backend/stfu/api/routes/apo.py`, agregar el import y la ruta:

```python
from stfu.apo.health import check_registrations, needs_repair as health_needs_repair


@router.get("/health")
def apo_health():
    return {"needs_repair": health_needs_repair(), "endpoints": check_registrations()}
```

En `backend/stfu/main.py`, dentro de `_status_payload()`, agregar la clave (import inline, tolera fallo del registro sin tumbar `/status`):

```python
def _status_payload() -> dict:
    from stfu.apo.apo_engine import apo_engine
    payload = {
        "status": "ok",
        "latency_ms": engine.get_latency_ms(),
        "active": engine.active_targets(),
        "streams": engine.get_stats(),
        "apo": apo_engine.status(),
    }
    try:
        from stfu.apo.health import needs_repair, check_registrations
        payload["apo_health"] = {"needs_repair": needs_repair(), "endpoints": check_registrations()}
    except Exception:
        payload["apo_health"] = {"needs_repair": False, "endpoints": []}
    return payload
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_health_api.py tests/test_status_api.py tests/test_api_apo.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/api/routes/apo.py backend/stfu/main.py backend/tests/test_apo_health_api.py
git commit -m "feat: /apo/health y apo_health en /status — estado de reparación del APO visible para la UI"
```

---

### Task 6: Auto-repair del registro (ruta elevada) + tolerancia a fantasmas en el finder

**Files:**
- Modify: `backend/stfu/apo/register.py` (función `repair_registrations`)
- Modify: `backend/stfu/apo/admin_cli.py` (subcomando `repair`)
- Modify: `backend/stfu/api/routes/apo.py` (ruta `POST /apo/repair`)
- Test: `backend/tests/test_apo_repair.py`

**Interfaces:**
- Consumes: `health.check_registrations` (Task 4), `register.register_apo`, `constants.CLSID_BY_FLOW`.
- Produces: `register.repair_registrations() -> list[dict]` — re-registra cada endpoint `deactivated` con su CLSID (usando el backup existente para preservar los efectos del fabricante); omite `endpoint-missing` (no hay dónde escribir) reportándolo. `POST /apo/repair` la ejecuta elevada. Requiere admin (escribe HKLM).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_apo_repair.py
from unittest.mock import patch, call
from stfu.apo import register


def test_repair_reregisters_deactivated_only():
    checks = [
        {"endpoint_guid": "{G1}", "flow": "Capture", "state": "deactivated"},
        {"endpoint_guid": "{G2}", "flow": "Render", "state": "ok"},
        {"endpoint_guid": "{G3}", "flow": "Capture", "state": "endpoint-missing"},
    ]
    with patch("stfu.apo.register.check_registrations", return_value=checks), \
         patch("stfu.apo.register.register_apo") as reg:
        report = register.repair_registrations()
    # solo el deactivated se re-registra
    reg.assert_called_once()
    args = reg.call_args[0]
    assert args[0] == "{G1}" and args[1] == "Capture"
    by_guid = {r["endpoint_guid"]: r["result"] for r in report}
    assert by_guid["{G1}"] == "repaired"
    assert by_guid["{G2}"] == "ok"
    assert by_guid["{G3}"] == "endpoint-missing"


def test_repair_reports_failure_without_raising():
    checks = [{"endpoint_guid": "{G1}", "flow": "Capture", "state": "deactivated"}]
    with patch("stfu.apo.register.check_registrations", return_value=checks), \
         patch("stfu.apo.register.register_apo", side_effect=OSError("regsvr32 falló")):
        report = register.repair_registrations()
    assert report[0]["result"] == "error"
    assert "regsvr32" in report[0]["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_repair.py -v`
Expected: FAIL — `repair_registrations` no existe.

- [ ] **Step 3: Implement**

En `backend/stfu/apo/register.py`, agregar (import de health al final para evitar ciclo — health importa de register):

```python
def repair_registrations() -> list[dict]:
    """Re-registra los endpoints cuyo APO fue desactivado por un update.
    Preserva los efectos del fabricante vía el backup existente. Requiere admin."""
    from stfu.apo.health import check_registrations
    from stfu.apo.constants import CLSID_BY_FLOW
    report = []
    for check in check_registrations():
        guid, flow, state = check["endpoint_guid"], check["flow"], check["state"]
        if state == "ok":
            report.append({**check, "result": "ok"})
            continue
        if state == "endpoint-missing":
            report.append({**check, "result": "endpoint-missing"})
            continue
        try:
            register_apo(guid, flow, CLSID_BY_FLOW[flow])
            report.append({**check, "result": "repaired"})
        except Exception as e:
            _log.exception("repair de %s/%s falló", guid, flow)
            report.append({**check, "result": "error", "detail": str(e)})
    return report
```

En `backend/stfu/apo/admin_cli.py`, agregar el subcomando `repair` que llama `repair_registrations()` e imprime el reporte (seguir el patrón de los subcomandos existentes `register`/`unregister`/`enable-unsigned`).

En `backend/stfu/api/routes/apo.py`:

```python
@router.post("/repair")
def apo_repair():
    try:
        from stfu.apo.elevate import run_elevated
        run_elevated(["repair"])
    except Exception as e:
        _log.exception("fallo en repair APO elevado")
        raise HTTPException(500, str(e))
    return {"ok": True}
```

Tolerancia a fantasmas: `find_endpoint_guid` (endpoint_finder) ya prefiere `DEVICE_STATE_ACTIVE` y cae a inactivos — verificar con un test que un endpoint con `DeviceState != 1` no es elegido si hay uno activo que calza. Si el test ya existe (`test_endpoint_finder.py`), no duplicar.

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_repair.py tests/test_apo_register.py tests/test_endpoint_finder.py tests/test_elevate.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/apo/register.py backend/stfu/apo/admin_cli.py backend/stfu/api/routes/apo.py backend/tests/test_apo_repair.py
git commit -m "feat: auto-repair del APO — POST /apo/repair re-registra endpoints desactivados por update (elevado)"
```

---

### Task 7: Health-check periódico en el lifespan

**Files:**
- Create: `backend/stfu/apo/health_monitor.py`
- Modify: `backend/stfu/main.py` (start/stop en lifespan)
- Test: `backend/tests/test_apo_health_monitor.py`

**Interfaces:**
- Consumes: `health.check_registrations` (Task 4).
- Produces: `ApoHealthMonitor(check_fn, interval_s=60.0).start()/stop()` — thread daemon que llama `check_fn` periódicamente y loguea WARNING la primera vez que detecta un `deactivated`/`endpoint-missing` (para que aparezca en `backend.log` cuando un tester reporta "dejó de funcionar tras actualizar Windows"). No repara solo (la reparación eleva; la decide el usuario vía UI). Tolera excepciones del check.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_apo_health_monitor.py
from stfu.apo.health_monitor import ApoHealthMonitor


def test_tick_logs_once_on_first_degraded_state(caplog):
    calls = {"n": 0}

    def check():
        calls["n"] += 1
        return [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}]

    mon = ApoHealthMonitor(check, interval_s=999)
    import logging
    with caplog.at_level(logging.WARNING):
        mon._tick()
        mon._tick()
    warnings = [r for r in caplog.records if "APO" in r.message or "apo" in r.message.lower()]
    assert len(warnings) == 1        # logueado una sola vez pese a dos ticks degradados
    assert calls["n"] == 2


def test_tick_tolerates_check_exception():
    def boom():
        raise RuntimeError("registro ilegible")
    mon = ApoHealthMonitor(boom, interval_s=999)
    mon._tick()  # no debe propagar


def test_recovery_reArms_the_warning():
    states = [
        [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}],
        [{"endpoint_guid": "g", "flow": "Capture", "state": "ok"}],
        [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}],
    ]

    def check():
        return states.pop(0)

    mon = ApoHealthMonitor(check, interval_s=999)
    import logging
    import pytest
    # 1ra degradación loguea; recuperación re-arma; 2da degradación vuelve a loguear
    log_counts = []
    for _ in range(3):
        before = len(mon._logged_degraded)
        mon._tick()
        log_counts.append(mon._warned)
    # tras recovery (_tick 2) el flag se limpia y la 3ra degradación re-loguea
    assert mon._warned is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_health_monitor.py -v`
Expected: FAIL — módulo no existe.

- [ ] **Step 3: Implement**

```python
# backend/stfu/apo/health_monitor.py
"""Vigila el registro del APO en segundo plano. Un cumulative update de
Windows 11 24H2 puede desactivar el APO en silencio; este monitor lo detecta y
lo loguea (no repara solo — la reparación eleva y la decide el usuario)."""
import logging
import threading

_log = logging.getLogger(__name__)


class ApoHealthMonitor:
    def __init__(self, check_fn, interval_s: float = 60.0) -> None:
        self._check = check_fn
        self._interval = interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._warned = False
        self._logged_degraded: set = set()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            self._tick()

    def _tick(self) -> None:
        try:
            checks = self._check()
        except Exception:
            _log.exception("health-check del APO falló")
            return
        degraded = [c for c in checks if c["state"] != "ok"]
        if not degraded:
            self._warned = False
            return
        if not self._warned:
            _log.warning("APO degradado en %d endpoint(s): %s — usar /apo/repair",
                         len(degraded), [(c["flow"], c["state"]) for c in degraded])
            self._warned = True
```

En `backend/stfu/main.py`, dentro de `lifespan` (junto al `DegradeMonitor` que ya existe de F2):

```python
    from stfu.apo.health_monitor import ApoHealthMonitor
    from stfu.apo.health import check_registrations
    apo_health_monitor = ApoHealthMonitor(check_registrations)
    apo_health_monitor.start()
    ...
    yield
    apo_health_monitor.stop()
    ...
```

(Colocarlo junto al start/stop del `DegradeMonitor` existente; respetar el orden: parar ambos monitores antes de `engine.stop_all()`.)

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_apo_health_monitor.py tests/test_status_api.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/apo/health_monitor.py backend/stfu/main.py backend/tests/test_apo_health_monitor.py
git commit -m "feat: monitor periódico de salud del APO — loguea desactivación silenciosa post-update de Windows"
```

---

### Task 8: Suite completa + smoke

- [ ] **Step 1: Suite completa**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: todos PASS (219 de base + los nuevos de F3)

- [ ] **Step 2: Smoke con backend real**

```powershell
cd backend; .\.venv\Scripts\python.exe -m uvicorn stfu.main:app --port 8765
# Otra terminal:
curl http://localhost:8765/status          # debe incluir apo_health
curl http://localhost:8765/apo/health      # {needs_repair, endpoints}
```
Expected: `/status` con `apo_health`; `/apo/health` responde sin error aunque no haya registros (endpoints vacío, needs_repair false). Matar uvicorn limpio.

- [ ] **Step 3: Commit de cierre si quedó algo**

```bash
git status --short
```
