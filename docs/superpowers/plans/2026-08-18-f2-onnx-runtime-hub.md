# F2 — Runtime ONNX any-device + Hub de modelos: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inferencia ONNX con streaming real (estado entre chunks), selección de device `auto|cpu|gpu` con probe+fallback, lineup curado de modelos descargables desde HF/GitHub con verificación sha256, swap en vivo, y DFN3-torch degradado a extra opcional.

**Architecture:** `OnnxStreamingPlugin` implementa el ABC `AudioPlugin` existente y realimenta los tensores de estado recurrente entre llamadas — el `FormatAdapter` existente resuelve la conversión de formato, no se toca. `ep_router` es el único módulo que conoce runtimes (escalera NPU→GPU→CPU con probe de silencio + validación NaN); NPU queda como enum presente pero sin EP hasta F2.5. El hub porta los patrones de Upflow: manifests curados en el repo, descarga con sha256, registro local en `~/.stfu/models`.

**Tech Stack:** onnxruntime-directml (ya en requirements), huggingface_hub (ya), httpx (ya), numpy, pydantic v2. Dev: `onnx` (nuevo, solo para generar modelos de test y para inspección de IO).

**Spec:** `docs/superpowers/specs/2026-08-18-stfu-modernization-design.md` (§3.1, §3.2, §3.5, §4)

## Global Constraints

- Prerequisito: Plan F1 completo (usa `stage_metrics`, `pipeline_failed`, `/status` extendido).
- Windows-only. Tests corren desde `backend/`: `.\.venv\Scripts\python.exe -m pytest`.
- `onnxruntime-directml>=1.20.0` es el único build de ORT del proceso; jamás agregar `onnxruntime` base a requirements (conflicto de paquete).
- Los EPs se piden SIEMPRE con fallback explícito a CPU al crear sesión (`providers=[EP, "CPUExecutionProvider"]`).
- fp32 por default en todos los modelos del lineup (know-how Upflow: fp16 en DML da NaN sin cirugía); fp16 solo con justificación medida, fuera de este plan.
- Commits en español, formato convencional. Sin `Co-Authored-By`.
- Manifests curados viven en `backend/stfu/hub/curated/`; la descarga solo trae el binario del modelo.
- Test suite completa verde al final de cada task.

---

### Task 1: Manifest extendido con `io_spec`, tier, licencia y fuentes

**Files:**
- Modify: `backend/stfu/hub/registry.py`
- Test: `backend/tests/test_manifest_v2.py`

**Interfaces:**
- Produces (consumido por Tasks 2-7):

```python
class TensorSpec(BaseModel):
    name: str
    shape: list[int | str]        # dims fijas o "chunk" (se resuelve al chunk del formato)

class StateSpec(BaseModel):
    input: str                    # nombre del tensor de estado de entrada
    output: str                   # nombre del tensor de salida que lo realimenta
    shape: list[int]
    
class IoSpec(BaseModel):
    audio_input: TensorSpec
    audio_output: str             # nombre del tensor de audio de salida
    states: list[StateSpec] = []

class ModelManifest(BaseModel):   # campos NUEVOS sobre los existentes
    tier: Literal["floor", "default", "quality", "legacy"] = "default"
    license: str = ""             # SPDX
    hf_repo: str | None = None    # source == "hf"
    url: str | None = None        # source == "github-release" | "url"
    sha256: str | None = None
    supported_devices: list[str] = ["cpu", "gpu"]
    io_spec: IoSpec | None = None # None => plugin no-ONNX (builtin/legacy)
    supported_backends: list[str] = []   # legado, pasa a opcional
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_manifest_v2.py
import pytest
from stfu.hub.registry import ModelManifest, IoSpec, TensorSpec, StateSpec


def _base(**over):
    d = dict(
        id="fastenhancer-tiny", name="FastEnhancer Tiny", version="1.0",
        plugin_class="stfu.plugins.onnx_streaming.OnnxStreamingPlugin",
        source="hf", file="model.onnx",
        preferred_format={"sample_rate": 16000, "channels": 1, "chunk_samples": 256},
        size_mb=0.1, algorithmic_latency_ms=16.0,
        tier="floor", license="MIT", hf_repo="aask1357/fastenhancer",
        sha256="a" * 64,
        io_spec={
            "audio_input": {"name": "input", "shape": [1, "chunk"]},
            "audio_output": "output",
            "states": [{"input": "state_in", "output": "state_out", "shape": [1, 64]}],
        },
    )
    d.update(over)
    return d


def test_manifest_v2_parses():
    m = ModelManifest(**_base())
    assert m.tier == "floor"
    assert m.io_spec.states[0].input == "state_in"
    assert m.supported_devices == ["cpu", "gpu"]


def test_io_spec_optional_for_builtin_plugins():
    m = ModelManifest(**_base(io_spec=None, sha256=None, hf_repo=None))
    assert m.io_spec is None


def test_invalid_tier_rejected():
    with pytest.raises(ValueError):
        ModelManifest(**_base(tier="ultra"))


def test_existing_validators_still_apply():
    with pytest.raises(ValueError):
        ModelManifest(**_base(file="..\\evil.onnx"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_manifest_v2.py -v`
Expected: FAIL — `IoSpec` no existe

- [ ] **Step 3: Implement**

En `backend/stfu/hub/registry.py`, agregar tras los imports (mantener validadores existentes intactos):

```python
from typing import Literal


class TensorSpec(BaseModel):
    name: str
    shape: list[int | str]


class StateSpec(BaseModel):
    input: str
    output: str
    shape: list[int]


class IoSpec(BaseModel):
    audio_input: TensorSpec
    audio_output: str
    states: list[StateSpec] = []
```

En `ModelManifest`, agregar campos (los existentes no cambian, `supported_backends` pasa a `list[str] = []`):

```python
    tier: Literal["floor", "default", "quality", "legacy"] = "default"
    license: str = ""
    hf_repo: str | None = None
    url: str | None = None
    sha256: str | None = None
    supported_devices: list[str] = ["cpu", "gpu"]
    io_spec: IoSpec | None = None
    supported_backends: list[str] = []
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_manifest_v2.py tests/test_hub.py -v`
Expected: todos PASS (si `test_hub.py` construía manifests con `supported_backends` requerido, sigue funcionando — ahora es opcional)

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/hub/registry.py backend/tests/test_manifest_v2.py
git commit -m "feat: ModelManifest v2 — io_spec, tier, licencia, fuentes y sha256"
```

---

### Task 2: `ep_router` — escalera de devices con probe

**Files:**
- Create: `backend/stfu/inference/__init__.py` (vacío)
- Create: `backend/stfu/inference/ep_router.py`
- Test: `backend/tests/test_ep_router.py`

**Interfaces:**
- Produces (Task 3 lo consume):

```python
DEVICE_LADDER: dict[str, list[str]]   # {"auto": ["npu","gpu","cpu"], "cpu": ["cpu"], ...}
EP_BY_DEVICE: dict[str, str | None]   # {"gpu": "DmlExecutionProvider", "cpu": "CPUExecutionProvider", "npu": None}
def available_devices() -> list[str]
def providers_for(device: str) -> list[str]          # EPs con fallback CPU incluido
def select_device(device: str, probe: Callable[[list[str]], bool]) -> str
    # recorre la escalera; retorna el primer device cuyo probe pasa; ValueError si ninguno
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_ep_router.py
import pytest
from stfu.inference import ep_router


def test_providers_for_gpu_includes_cpu_fallback():
    assert ep_router.providers_for("gpu") == ["DmlExecutionProvider", "CPUExecutionProvider"]


def test_providers_for_cpu():
    assert ep_router.providers_for("cpu") == ["CPUExecutionProvider"]


def test_providers_for_npu_raises_until_f25():
    with pytest.raises(ep_router.DeviceUnavailable):
        ep_router.providers_for("npu")


def test_auto_picks_first_device_whose_probe_passes():
    attempts = []

    def probe(providers):
        attempts.append(providers[0])
        return providers[0] == "CPUExecutionProvider"

    assert ep_router.select_device("auto", probe) == "cpu"
    # npu se saltea (sin EP), gpu probeó y falló, cpu pasó
    assert attempts == ["DmlExecutionProvider", "CPUExecutionProvider"]


def test_manual_device_does_not_fall_back():
    with pytest.raises(ep_router.DeviceUnavailable):
        ep_router.select_device("gpu", lambda providers: False)


def test_unknown_device_rejected():
    with pytest.raises(ValueError):
        ep_router.select_device("tpu", lambda p: True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ep_router.py -v`
Expected: FAIL — módulo no existe

- [ ] **Step 3: Implement**

```python
# backend/stfu/inference/ep_router.py
"""Único módulo que conoce runtimes de inferencia.

Escalera de devices con probe: `auto` prueba NPU→GPU→CPU y se queda con el
primero que funciona; un device elegido a mano NO hace fallback silencioso —
el usuario lo eligió, un fallo debe ser visible. NPU se habilita en F2.5 vía
runtime packs (spec §3.3); mientras tanto existe en el enum pero sin EP.
"""
import logging
from typing import Callable

_log = logging.getLogger(__name__)

DEVICE_LADDER: dict[str, list[str]] = {
    "auto": ["npu", "gpu", "cpu"],
    "npu": ["npu"],
    "gpu": ["gpu"],
    "cpu": ["cpu"],
}

EP_BY_DEVICE: dict[str, str | None] = {
    "npu": None,  # F2.5: runtime packs (QNN / OpenVINO)
    "gpu": "DmlExecutionProvider",
    "cpu": "CPUExecutionProvider",
}


class DeviceUnavailable(RuntimeError):
    pass


def available_devices() -> list[str]:
    import onnxruntime as ort
    available = set(ort.get_available_providers())
    return [
        device for device, ep in EP_BY_DEVICE.items()
        if ep is not None and ep in available
    ]


def providers_for(device: str) -> list[str]:
    ep = EP_BY_DEVICE.get(device, "missing")
    if ep == "missing":
        raise ValueError(f"device desconocido: {device!r}")
    if ep is None:
        raise DeviceUnavailable(f"device {device!r} sin runtime instalado (llega en F2.5)")
    if ep == "CPUExecutionProvider":
        return [ep]
    return [ep, "CPUExecutionProvider"]


def select_device(device: str, probe: Callable[[list[str]], bool]) -> str:
    if device not in DEVICE_LADDER:
        raise ValueError(f"device desconocido: {device!r}")
    for candidate in DEVICE_LADDER[device]:
        try:
            providers = providers_for(candidate)
        except DeviceUnavailable:
            continue
        if probe(providers):
            _log.info("device seleccionado: %s (%s)", candidate, providers[0])
            return candidate
        _log.warning("probe falló para device %s", candidate)
    raise DeviceUnavailable(f"ningún device de la escalera {device!r} pasó el probe")
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ep_router.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/inference/ backend/tests/test_ep_router.py
git commit -m "feat: ep_router — escalera auto/npu/gpu/cpu con probe y sin fallback silencioso manual"
```

---

### Task 3: `OnnxStreamingPlugin`

**Files:**
- Create: `backend/stfu/plugins/onnx_streaming.py`
- Create: `backend/tests/helpers_onnx.py` (generador de modelo de test)
- Modify: `backend/requirements.txt` (agregar `onnx>=1.16` en la sección de test, junto a pytest)
- Test: `backend/tests/test_onnx_streaming_plugin.py`

**Interfaces:**
- Consumes: `ModelManifest`/`IoSpec` (Task 1), `ep_router.providers_for` + `select_device` (Task 2).
- Produces (Tasks 4-6 lo consumen):

```python
class OnnxStreamingPlugin(AudioPlugin):
    def __init__(self, manifest: ModelManifest, model_path: Path, device: str = "auto") -> None
    # tras setup(): .active_device -> str (device real elegido por el router)
```

- [ ] **Step 1: Write the test-model helper**

El modelo de test es un grafo ONNX mínimo con la MISMA topología que un SE streaming real: audio in + estado in → audio out (audio*0.5 + broadcast del primer elemento del estado, para verificar que el estado influye) + estado out (estado+1, para verificar realimentación).

```python
# backend/tests/helpers_onnx.py
"""Genera un modelo ONNX streaming mínimo para tests (audio + estado)."""
from pathlib import Path
import numpy as np
from onnx import TensorProto, helper


def make_streaming_model(path: Path, chunk: int = 256, state_dim: int = 4) -> None:
    audio_in = helper.make_tensor_value_info("audio", TensorProto.FLOAT, [1, chunk])
    state_in = helper.make_tensor_value_info("state_in", TensorProto.FLOAT, [1, state_dim])
    audio_out = helper.make_tensor_value_info("enhanced", TensorProto.FLOAT, [1, chunk])
    state_out = helper.make_tensor_value_info("state_out", TensorProto.FLOAT, [1, state_dim])

    half = helper.make_tensor("half", TensorProto.FLOAT, [], [0.5])
    one = helper.make_tensor("one", TensorProto.FLOAT, [], [1.0])
    zero_idx = helper.make_tensor("zero_idx", TensorProto.INT64, [1], [0])

    nodes = [
        # enhanced = audio * 0.5 + state_in[0,0]
        helper.make_node("Mul", ["audio", "half"], ["scaled"]),
        helper.make_node("Gather", ["state_in", "zero_idx"], ["s_row"], axis=0),
        helper.make_node("Gather", ["s_row", "zero_idx"], ["s_elem"], axis=1),
        helper.make_node("Add", ["scaled", "s_elem"], ["enhanced"]),
        # state_out = state_in + 1
        helper.make_node("Add", ["state_in", "one"], ["state_out"]),
    ]
    graph = helper.make_graph(
        nodes, "stfu_test_stream", [audio_in, state_in], [audio_out, state_out],
        initializer=[half, one, zero_idx],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    path.write_bytes(model.SerializeToString())
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_onnx_streaming_plugin.py
from pathlib import Path
import numpy as np
import pytest
from stfu.hub.registry import ModelManifest
from tests.helpers_onnx import make_streaming_model

_CHUNK = 256


@pytest.fixture()
def manifest(tmp_path) -> tuple[ModelManifest, Path]:
    model_path = tmp_path / "model.onnx"
    make_streaming_model(model_path, chunk=_CHUNK, state_dim=4)
    m = ModelManifest(
        id="test-stream", name="Test Stream", version="1.0",
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
    return m, model_path


def _plugin(manifest_and_path, device="cpu"):
    from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
    m, p = manifest_and_path
    plugin = OnnxStreamingPlugin(m, p, device=device)
    plugin.setup(plugin.preferred_format)
    return plugin


def test_process_runs_model(manifest):
    plugin = _plugin(manifest)
    chunk = np.ones((_CHUNK, 1), dtype=np.float32)
    out = plugin.process(chunk)
    assert out.shape == (_CHUNK, 1)
    # estado inicial = ceros → enhanced = audio*0.5 + 0
    np.testing.assert_allclose(out[:, 0], 0.5, rtol=1e-5)


def test_state_feeds_back_between_chunks(manifest):
    plugin = _plugin(manifest)
    chunk = np.ones((_CHUNK, 1), dtype=np.float32)
    plugin.process(chunk)                      # state pasa de 0 a 1
    out2 = plugin.process(chunk)               # enhanced = 0.5 + 1.0
    np.testing.assert_allclose(out2[:, 0], 1.5, rtol=1e-5)


def test_strength_mixes_dry_wet(manifest):
    plugin = _plugin(manifest)
    plugin.set_parameter("strength", 0.0)      # 100% dry
    chunk = np.ones((_CHUNK, 1), dtype=np.float32)
    out = plugin.process(chunk)
    np.testing.assert_allclose(out[:, 0], 1.0, rtol=1e-5)


def test_teardown_and_setup_resets_state(manifest):
    plugin = _plugin(manifest)
    chunk = np.ones((_CHUNK, 1), dtype=np.float32)
    plugin.process(chunk)
    plugin.teardown()
    plugin.setup(plugin.preferred_format)
    out = plugin.process(chunk)
    np.testing.assert_allclose(out[:, 0], 0.5, rtol=1e-5)  # estado volvió a cero


def test_preferred_format_from_manifest(manifest):
    plugin = _plugin(manifest)
    fmt = plugin.preferred_format
    assert (fmt.sample_rate, fmt.channels, fmt.chunk_samples) == (16000, 1, _CHUNK)


def test_active_device_reported(manifest):
    plugin = _plugin(manifest, device="cpu")
    assert plugin.active_device == "cpu"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.\.venv\Scripts\pip.exe install "onnx>=1.16"` y luego `.\.venv\Scripts\python.exe -m pytest tests/test_onnx_streaming_plugin.py -v`
Expected: FAIL — `stfu.plugins.onnx_streaming` no existe. Agregar `onnx>=1.16` a `requirements.txt` (sección test, junto a pytest).

- [ ] **Step 4: Implement**

```python
# backend/stfu/plugins/onnx_streaming.py
"""Plugin genérico para modelos ONNX de speech enhancement con streaming real.

El manifest declara los tensores (io_spec); los estados recurrentes de salida
se realimentan como entrada de la siguiente llamada — el modelo mantiene su
contexto temporal sin ventanas deslizantes ni resets.
"""
import logging
from pathlib import Path
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.hub.registry import ModelManifest
from stfu.inference import ep_router
from stfu.plugins.base import AudioPlugin, Parameter

_log = logging.getLogger(__name__)


class OnnxStreamingPlugin(AudioPlugin):
    def __init__(self, manifest: ModelManifest, model_path: Path, device: str = "auto") -> None:
        if manifest.io_spec is None:
            raise ValueError(f"manifest {manifest.id!r} sin io_spec: no es un modelo ONNX")
        self._manifest = manifest
        self._model_path = Path(model_path)
        self._device = device
        self._session = None
        self._states: dict[str, np.ndarray] = {}
        self._strength: float = 1.0
        self._active_device: str | None = None

    @property
    def name(self) -> str:
        return self._manifest.name

    @property
    def version(self) -> str:
        return self._manifest.version

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(**self._manifest.preferred_format)

    @property
    def active_device(self) -> str | None:
        return self._active_device

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        if self._session is None:
            self._active_device = ep_router.select_device(self._device, self._probe)
        self._reset_states()
        return fmt

    def _probe(self, providers: list[str]) -> bool:
        import onnxruntime as ort
        try:
            session = ort.InferenceSession(str(self._model_path), providers=providers)
            self._session = session
            self._reset_states()
            out = self._run(np.zeros((self.preferred_format.chunk_samples, 1), dtype=np.float32))
            if not np.isfinite(out).all():
                _log.warning("probe %s produjo NaN/Inf", providers[0])
                self._session = None
                return False
            return True
        except Exception:
            _log.warning("probe %s falló", providers[0], exc_info=True)
            self._session = None
            return False

    def process(self, audio: np.ndarray) -> np.ndarray:
        if self._session is None:
            return audio
        dry = audio
        wet = self._run(audio)
        s = self._strength
        return (wet * s + dry * (1.0 - s)).astype(np.float32, copy=False)

    def _run(self, audio: np.ndarray) -> np.ndarray:
        spec = self._manifest.io_spec
        chunk = audio.shape[0]
        shape = [chunk if d == "chunk" else d for d in spec.audio_input.shape]
        feeds = {spec.audio_input.name: audio[:, 0].reshape(shape).astype(np.float32)}
        for st in spec.states:
            feeds[st.input] = self._states[st.input]
        output_names = [spec.audio_output] + [st.output for st in spec.states]
        results = self._session.run(output_names, feeds)
        for st, value in zip(spec.states, results[1:]):
            self._states[st.input] = value
        return np.asarray(results[0]).reshape(-1, 1)

    def teardown(self) -> None:
        self._session = None
        self._states = {}

    def _reset_states(self) -> None:
        spec = self._manifest.io_spec
        self._states = {
            st.input: np.zeros(st.shape, dtype=np.float32) for st in spec.states
        }

    @property
    def algorithmic_latency_ms(self) -> float:
        return self._manifest.algorithmic_latency_ms

    @property
    def parameters(self) -> list[Parameter]:
        return [
            Parameter(id="strength", label="Intensidad de cancelación",
                      type="float", default=1.0, min=0.0, max=1.0),
        ]

    def set_parameter(self, id: str, value) -> None:
        if id == "strength":
            self._strength = float(value)
```

Nota de diseño: `setup()` re-ejecutado (recompilaciones del pipeline) NO recrea la sesión — solo resetea estados. La sesión se crea una vez en el primer setup vía probe del router; por eso el warmup previo al swap en vivo (Task 6) es simplemente llamar `setup()` desde el hilo de API antes de encolar.

- [ ] **Step 5: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_onnx_streaming_plugin.py -v`
Expected: 7 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/stfu/plugins/onnx_streaming.py backend/tests/helpers_onnx.py backend/tests/test_onnx_streaming_plugin.py backend/requirements.txt
git commit -m "feat: OnnxStreamingPlugin — streaming real con estados realimentados y mezcla dry/wet"
```

---

### Task 4: `pipeline_factory` compartido con modelos del registro

**Files:**
- Create: `backend/stfu/core/pipeline_factory.py`
- Modify: `backend/stfu/audio/engine.py` (borrar `_PLUGIN_CLASSES` y `_build_pipeline`, importar del factory)
- Modify: `backend/stfu/apo/apo_engine.py` (importar del factory, no de `audio.engine`)
- Test: `backend/tests/test_pipeline_factory.py`

**Interfaces:**
- Consumes: `OnnxStreamingPlugin` (Task 3), `ModelRegistry` (existente).
- Produces (Tasks 5-6 y rutas lo consumen):

```python
def build_pipeline(plugin_configs: list[dict], registry: ModelRegistry | None = None,
                   device: str = "auto") -> Pipeline
# plugin_id builtin: "deepfilternet3" | "eq_parametric" | "gain"
# plugin_id de modelo: "model:<model_id>"  → OnnxStreamingPlugin del registro
def default_registry() -> ModelRegistry     # singleton sobre ~/.stfu/models
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_pipeline_factory.py
import pytest
from pathlib import Path
from stfu.core.pipeline_factory import build_pipeline
from stfu.hub.registry import ModelRegistry, ModelManifest
from tests.helpers_onnx import make_streaming_model


def _registry_with_model(tmp_path) -> ModelRegistry:
    registry = ModelRegistry(tmp_path / "models")
    model_file = tmp_path / "m.onnx"
    make_streaming_model(model_file)
    manifest = ModelManifest(
        id="test-stream", name="Test", version="1.0",
        plugin_class="stfu.plugins.onnx_streaming.OnnxStreamingPlugin",
        source="local", file="model.onnx",
        preferred_format={"sample_rate": 16000, "channels": 1, "chunk_samples": 256},
        size_mb=0.01, algorithmic_latency_ms=16.0,
        io_spec={
            "audio_input": {"name": "audio", "shape": [1, "chunk"]},
            "audio_output": "enhanced",
            "states": [{"input": "state_in", "output": "state_out", "shape": [1, 4]}],
        },
    )
    registry.register(manifest, model_file)
    return registry


def test_builds_builtin_plugins():
    p = build_pipeline([{"plugin_id": "gain", "parameters": {"gain_db": -3.0}}])
    assert len(p._plugins) == 1


def test_builds_model_plugin_from_registry(tmp_path):
    registry = _registry_with_model(tmp_path)
    p = build_pipeline([{"plugin_id": "model:test-stream"}], registry=registry, device="cpu")
    from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
    assert isinstance(p._plugins[0], OnnxStreamingPlugin)


def test_unknown_model_id_raises(tmp_path):
    registry = ModelRegistry(tmp_path / "models")
    with pytest.raises(ValueError, match="model:nope"):
        build_pipeline([{"plugin_id": "model:nope"}], registry=registry)


def test_unknown_plugin_raises():
    with pytest.raises(ValueError, match="desconocido"):
        build_pipeline([{"plugin_id": "wat"}])


def test_dfn3_without_torch_gives_clear_error(monkeypatch):
    import importlib.util
    real = importlib.util.find_spec

    def fake_find_spec(name, *a, **kw):
        if name == "df":
            return None
        return real(name, *a, **kw)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    with pytest.raises(ValueError, match="requirements-torch"):
        build_pipeline([{"plugin_id": "deepfilternet3"}])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pipeline_factory.py -v`
Expected: FAIL — módulo no existe

- [ ] **Step 3: Implement**

```python
# backend/stfu/core/pipeline_factory.py
"""Construcción de pipelines desde configs — compartido por AudioEngine,
ApoEngine y el feeder. Único lugar que mapea plugin_id → clase."""
import importlib.util
from pathlib import Path
from stfu.core.pipeline import Pipeline
from stfu.hub.registry import ModelRegistry
from stfu.plugins.builtin.eq_parametric import EQParametricPlugin
from stfu.plugins.builtin.gain import GainPlugin

_MODEL_PREFIX = "model:"
_registry_singleton: ModelRegistry | None = None


def default_registry() -> ModelRegistry:
    global _registry_singleton
    if _registry_singleton is None:
        _registry_singleton = ModelRegistry(Path.home() / ".stfu" / "models")
    return _registry_singleton


def _build_dfn3():
    if importlib.util.find_spec("df") is None:
        raise ValueError(
            "DeepFilterNet3 requiere el extra torch: pip install -r requirements-torch.txt"
        )
    from stfu.plugins.builtin.deepfilternet3 import DeepFilterNet3Plugin
    return DeepFilterNet3Plugin()


def _build_model_plugin(model_id: str, registry: ModelRegistry, device: str):
    from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
    manifest = registry.get(model_id)
    model_path = registry.model_path(model_id)
    if manifest is None or model_path is None:
        raise ValueError(f"Plugin desconocido: model:{model_id} (modelo no instalado)")
    return OnnxStreamingPlugin(manifest, model_path, device=device)


def _make_plugin(plugin_id: str, registry: ModelRegistry | None, device: str):
    if plugin_id.startswith(_MODEL_PREFIX):
        reg = registry if registry is not None else default_registry()
        return _build_model_plugin(plugin_id[len(_MODEL_PREFIX):], reg, device)
    if plugin_id == "deepfilternet3":
        return _build_dfn3()
    builtin = {"eq_parametric": EQParametricPlugin, "gain": GainPlugin}
    cls = builtin.get(plugin_id)
    if cls is None:
        raise ValueError(f"Plugin desconocido: {plugin_id}")
    return cls()


def build_pipeline(plugin_configs: list[dict], registry: ModelRegistry | None = None,
                   device: str = "auto") -> Pipeline:
    pipeline = Pipeline()
    for cfg in plugin_configs:
        plugin = _make_plugin(cfg["plugin_id"], registry, device)
        for k, v in cfg.get("parameters", {}).items():
            plugin.set_parameter(k, v)
        pipeline.add_plugin(plugin)
    return pipeline
```

En `backend/stfu/audio/engine.py`: borrar `_PLUGIN_CLASSES`, `_build_pipeline` y los imports de plugins; agregar `from stfu.core.pipeline_factory import build_pipeline` y en `start()` reemplazar `pipeline = _build_pipeline(plugin_configs)` por `pipeline = build_pipeline(plugin_configs)`.

En `backend/stfu/apo/apo_engine.py`: reemplazar `from stfu.audio.engine import _build_pipeline` por `from stfu.core.pipeline_factory import build_pipeline` (y la llamada). El import queda a nivel de módulo — el ciclo `audio.engine ↔ apo_engine` desaparece porque ya nadie importa de `audio.engine`.

Buscar otros usos: `grep -rn "_build_pipeline" backend/stfu/` — `api/routes/feeder.py` también lo usa; actualizarlo igual.

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_pipeline_factory.py tests/test_api.py tests/test_feeder.py tests/test_api_apo.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/core/pipeline_factory.py backend/stfu/audio/engine.py backend/stfu/apo/apo_engine.py backend/stfu/api/routes/feeder.py backend/tests/test_pipeline_factory.py
git commit -m "refactor: pipeline_factory compartido — muere el import privado y entra model:<id>"
```

---

### Task 5: Hub — catálogo curado, descarga con sha256 y rutas

**Files:**
- Create: `backend/stfu/hub/curated/` (manifests JSON — Task 7 los llena con datos verificados)
- Modify: `backend/stfu/hub/manager.py` (reescritura)
- Modify: `backend/stfu/api/routes/models.py` (rutas nuevas)
- Test: `backend/tests/test_hub_download.py`

**Interfaces:**
- Consumes: `ModelManifest` v2 (Task 1), `ModelRegistry` (existente), `default_registry` (Task 4).
- Produces:

```python
class HubManager:
    def __init__(self, registry: ModelRegistry, curated_dir: Path) -> None
    def catalog(self) -> list[dict]      # curados + instalados, con "installed": bool
    def download(self, model_id: str) -> Path   # bloqueante; valida sha256; registra
    def delete(self, model_id: str, active_ids: set[str]) -> None  # rechaza si activo
# Rutas: GET /models · POST /models/{id}/download · DELETE /models/{id}
# (POST /models/{id}/activate llega en Task 6 — necesita el swap del engine)
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_hub_download.py
import hashlib
import json
import pytest
from pathlib import Path
from stfu.hub.manager import HubManager, Sha256Mismatch
from stfu.hub.registry import ModelRegistry


def _curated_dir(tmp_path, model_bytes: bytes) -> Path:
    curated = tmp_path / "curated"
    curated.mkdir()
    manifest = {
        "id": "fastenhancer-tiny", "name": "FastEnhancer Tiny", "version": "1.0",
        "plugin_class": "stfu.plugins.onnx_streaming.OnnxStreamingPlugin",
        "source": "url", "file": "model.onnx",
        "url": "https://example.com/model.onnx",
        "sha256": hashlib.sha256(model_bytes).hexdigest(),
        "preferred_format": {"sample_rate": 16000, "channels": 1, "chunk_samples": 256},
        "size_mb": 0.01, "algorithmic_latency_ms": 16.0,
        "tier": "floor", "license": "MIT",
        "io_spec": {
            "audio_input": {"name": "audio", "shape": [1, "chunk"]},
            "audio_output": "enhanced", "states": [],
        },
    }
    (curated / "fastenhancer-tiny.json").write_text(json.dumps(manifest))
    return curated


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    model_bytes = b"fake onnx bytes"
    registry = ModelRegistry(tmp_path / "models")
    manager = HubManager(registry, _curated_dir(tmp_path, model_bytes))
    monkeypatch.setattr(manager, "_fetch", lambda manifest, dest: dest.write_bytes(model_bytes))
    return manager


def test_catalog_lists_curated_not_installed(hub):
    cat = hub.catalog()
    assert len(cat) == 1
    assert cat[0]["id"] == "fastenhancer-tiny"
    assert cat[0]["installed"] is False


def test_download_verifies_and_registers(hub):
    path = hub.download("fastenhancer-tiny")
    assert path.exists()
    assert hub.catalog()[0]["installed"] is True


def test_download_rejects_sha_mismatch(hub, monkeypatch):
    monkeypatch.setattr(hub, "_fetch", lambda manifest, dest: dest.write_bytes(b"tampered"))
    with pytest.raises(Sha256Mismatch):
        hub.download("fastenhancer-tiny")
    assert hub.catalog()[0]["installed"] is False


def test_delete_rejects_active_model(hub):
    hub.download("fastenhancer-tiny")
    with pytest.raises(ValueError, match="activo"):
        hub.delete("fastenhancer-tiny", active_ids={"fastenhancer-tiny"})


def test_delete_removes_installed(hub):
    hub.download("fastenhancer-tiny")
    hub.delete("fastenhancer-tiny", active_ids=set())
    assert hub.catalog()[0]["installed"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_hub_download.py -v`
Expected: FAIL — `HubManager` actual no tiene esta interfaz

- [ ] **Step 3: Implement**

```python
# backend/stfu/hub/manager.py  (reescritura completa)
"""Catálogo curado + descarga verificada de modelos.

Los manifests curados viven en el repo; la descarga trae solo el binario del
modelo desde HF o una URL directa y lo registra tras validar sha256."""
import hashlib
import json
import logging
import shutil
import tempfile
from pathlib import Path
import httpx
from stfu.hub.registry import ModelManifest, ModelRegistry

_log = logging.getLogger(__name__)


class Sha256Mismatch(RuntimeError):
    pass


class HubManager:
    def __init__(self, registry: ModelRegistry, curated_dir: Path) -> None:
        self._registry = registry
        self._curated_dir = Path(curated_dir)

    def _curated(self) -> list[ModelManifest]:
        return [
            ModelManifest.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(self._curated_dir.glob("*.json"))
        ]

    def catalog(self) -> list[dict]:
        installed_ids = {m.id for m in self._registry.list()}
        result = []
        seen = set()
        for m in self._curated():
            seen.add(m.id)
            result.append({**m.model_dump(), "installed": m.id in installed_ids})
        for m in self._registry.list():
            if m.id not in seen:
                result.append({**m.model_dump(), "installed": True})
        return result

    def download(self, model_id: str) -> Path:
        manifest = next((m for m in self._curated() if m.id == model_id), None)
        if manifest is None:
            raise ValueError(f"modelo {model_id!r} no está en el catálogo")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / manifest.file
            self._fetch(manifest, dest)
            self._verify_sha256(manifest, dest)
            self._registry.register(manifest, dest)
        _log.info("modelo %s instalado", model_id)
        return self._registry.model_path(model_id)

    def _fetch(self, manifest: ModelManifest, dest: Path) -> None:
        if manifest.source == "hf" and manifest.hf_repo:
            from huggingface_hub import hf_hub_download
            local = hf_hub_download(repo_id=manifest.hf_repo, filename=manifest.file)
            shutil.copy2(local, dest)
            return
        if manifest.url:
            with httpx.stream("GET", manifest.url, follow_redirects=True, timeout=60.0) as r:
                r.raise_for_status()
                with dest.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            return
        raise ValueError(f"manifest {manifest.id!r} sin fuente descargable")

    def _verify_sha256(self, manifest: ModelManifest, path: Path) -> None:
        if not manifest.sha256:
            raise ValueError(f"manifest {manifest.id!r} sin sha256 — no se instala sin verificación")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != manifest.sha256:
            raise Sha256Mismatch(
                f"{manifest.id}: sha256 esperado {manifest.sha256[:12]}…, obtenido {digest[:12]}…"
            )

    def delete(self, model_id: str, active_ids: set[str]) -> None:
        if model_id in active_ids:
            raise ValueError(f"modelo {model_id!r} está activo — desactivar antes de borrar")
        model_dir = self._registry.base_dir / model_id
        if model_dir.exists():
            shutil.rmtree(model_dir)
```

Reescribir `backend/stfu/api/routes/models.py`:

```python
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException
from stfu.core.pipeline_factory import default_registry
from stfu.hub.manager import HubManager, Sha256Mismatch

router = APIRouter()


def _curated_dir() -> Path:
    # PyInstaller onedir: los datos van junto al ejecutable
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "stfu" / "hub" / "curated"
    return Path(__file__).resolve().parents[2] / "hub" / "curated"


def _hub() -> HubManager:
    return HubManager(default_registry(), _curated_dir())


def _active_model_ids() -> set[str]:
    from stfu.audio.engine import engine
    ids = set()
    for target in engine.active_targets():
        ids |= engine.active_model_ids(target)
    return ids


@router.get("/models")
def list_models():
    return _hub().catalog()


@router.post("/models/{model_id}/download")
def download_model(model_id: str):
    try:
        path = _hub().download(model_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Sha256Mismatch as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"installed": True, "path": str(path)}


@router.delete("/models/{model_id}")
def delete_model(model_id: str):
    try:
        _hub().delete(model_id, _active_model_ids())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"deleted": True}
```

`engine.active_model_ids(target)` no existe aún — llega en Task 6. Para que esta task compile sola, agregar en `AudioEngine` el stub real (no placeholder — es la versión sin swap):

```python
    def active_model_ids(self, target: str) -> set[str]:
        from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
        with self._lock:
            thread = self._threads.get(target)
        if thread is None:
            return set()
        return {
            p._manifest.id for p in thread.pipeline._plugins
            if isinstance(p, OnnxStreamingPlugin)
        }
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_hub_download.py tests/test_hub.py tests/test_api.py -v`
Expected: PASS. `tests/test_hub.py` viejo testeaba `search_huggingface`/`download(repo_id, filename, manifest)` — esa interfaz murió con la reescritura: reescribir esos tests contra `HubManager.catalog/download` nuevos (mismo espíritu, nueva firma).

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/hub/ backend/stfu/api/routes/models.py backend/stfu/audio/engine.py backend/tests/test_hub_download.py backend/tests/test_hub.py
git commit -m "feat: hub curado — catálogo, descarga con sha256 obligatorio y delete seguro"
```

---

### Task 6: Swap de modelo en vivo

**Files:**
- Modify: `backend/stfu/core/pipeline.py` (método `replace_plugin`)
- Modify: `backend/stfu/audio/capture.py` (cola de swaps drenada por el worker)
- Modify: `backend/stfu/audio/engine.py` (método `swap_model`)
- Modify: `backend/stfu/api/routes/models.py` (ruta activate)
- Test: `backend/tests/test_model_swap.py`

**Interfaces:**
- Consumes: `OnnxStreamingPlugin` (Task 3), factory (Task 4).
- Produces:

```python
Pipeline.replace_plugin(index: int, plugin: AudioPlugin) -> None  # teardown viejo + recompile
CaptureThread.request_plugin_swap(index: int, plugin: AudioPlugin) -> None  # thread-safe
AudioEngine.swap_model(target: str, model_id: str, device: str = "auto") -> bool
# POST /models/{model_id}/activate?target=mic
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_model_swap.py
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.capture import CaptureThread
from stfu.plugins.base import AudioPlugin


class _TaggedPlugin(AudioPlugin):
    version = "1.0"

    def __init__(self, tag: str):
        self._tag = tag
        self.torn_down = False

    @property
    def name(self):
        return self._tag

    @property
    def preferred_format(self):
        return AudioFormat(48000, 2, 960)

    def setup(self, fmt):
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


def _fmt():
    return AudioFormat(sample_rate=48000, channels=2, chunk_samples=960)


def test_replace_plugin_tears_down_old_and_recompiles():
    old, new = _TaggedPlugin("old"), _TaggedPlugin("new")
    p = Pipeline()
    p.add_plugin(old)
    p.compile(_fmt())
    p.replace_plugin(0, new)
    assert old.torn_down is True
    assert p._plugins[0] is new
    assert p.stage_metrics()[0]["stage"] == "new"  # métricas recreadas


def test_worker_drains_swap_queue_before_processing():
    old, new = _TaggedPlugin("old"), _TaggedPlugin("new")
    pipeline = Pipeline()
    pipeline.add_plugin(old)
    fmt = _fmt()
    pipeline.compile(fmt)
    t = CaptureThread(input_device_id=0, output_device_id=0, fmt=fmt,
                      pipeline=pipeline, out_channels=2)
    t.request_plugin_swap(0, new)
    t._drain_swaps()
    assert pipeline._plugins[0] is new
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_model_swap.py -v`
Expected: FAIL — `replace_plugin` no existe

- [ ] **Step 3: Implement**

`pipeline.py`:

```python
    def replace_plugin(self, index: int, plugin: AudioPlugin) -> None:
        """Swap en caliente: teardown del viejo, recompilación de stages.
        Debe llamarse desde el hilo que ejecuta process() (el worker)."""
        if not 0 <= index < len(self._plugins):
            raise IndexError(f"plugin index {index} fuera de rango")
        old = self._plugins[index]
        self._plugins[index] = plugin
        old.teardown()
        if self._input_format is not None:
            self.compile(self._input_format)
```

`capture.py` — en `__init__`:

```python
        self._swap_queue: queue.Queue = queue.Queue()
```

Método nuevo + drenaje al inicio de cada iteración del worker:

```python
    def request_plugin_swap(self, index: int, plugin) -> None:
        self._swap_queue.put((index, plugin))

    def _drain_swaps(self) -> None:
        while True:
            try:
                index, plugin = self._swap_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._pipeline.replace_plugin(index, plugin)
                self._pipeline_failed = False  # un modelo nuevo resetea el estado failed
            except Exception:
                _log.exception("swap de plugin %d falló", index)
```

En `_worker_loop`, como primera línea dentro del `while`:

```python
            self._drain_swaps()
```

`engine.py`:

```python
    def swap_model(self, target: str, model_id: str, device: str = "auto") -> bool:
        """Activa un modelo NC en el pipeline vivo. El plugin se construye y
        warmupea (sesión ONNX creada) en este hilo; el worker hace el swap
        entre chunks — sin cortar el stream."""
        from stfu.core.pipeline_factory import build_pipeline, default_registry
        from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
        with self._lock:
            thread = self._threads.get(target)
        if thread is None:
            return False
        index = next(
            (i for i, p in enumerate(thread.pipeline._plugins)
             if isinstance(p, OnnxStreamingPlugin)),
            0,
        )
        staged = build_pipeline([{"plugin_id": f"model:{model_id}"}], device=device)
        plugin = staged._plugins[0]
        plugin.setup(plugin.preferred_format)  # warmup: crea la sesión acá, no en el worker
        thread.request_plugin_swap(index, plugin)
        return True
```

`routes/models.py`:

```python
@router.post("/models/{model_id}/activate")
def activate_model(model_id: str, target: str = "mic", device: str = "auto"):
    from stfu.audio.engine import engine
    if not any(m["id"] == model_id and m["installed"] for m in _hub().catalog()):
        raise HTTPException(status_code=404, detail=f"modelo {model_id!r} no instalado")
    if not engine.swap_model(target, model_id, device):
        raise HTTPException(status_code=409, detail=f"target {target!r} no está activo")
    return {"activated": model_id, "target": target}
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_model_swap.py tests/test_pipeline.py tests/test_capture_worker.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/core/pipeline.py backend/stfu/audio/capture.py backend/stfu/audio/engine.py backend/stfu/api/routes/models.py backend/tests/test_model_swap.py
git commit -m "feat: swap de modelo en vivo — warmup en API thread, swap entre chunks en el worker"
```

---

### Task 7: Manifests curados reales + script de inspección/hashes

**Files:**
- Create: `backend/scripts/inspect_onnx.py`
- Create: `backend/stfu/hub/curated/fastenhancer-tiny.json`
- Create: `backend/stfu/hub/curated/fastenhancer-base.json`
- Create: `backend/stfu/hub/curated/dpdfnet2-16k.json`
- Create: `backend/stfu/hub/curated/dpdfnet2-48k-hr.json`
- Create: `backend/stfu/hub/curated/gtcrn.json`

Esta task es descubrimiento de datos: los nombres exactos de tensores, shapes de estado y sha256 solo se conocen inspeccionando cada `.onnx` real. El script imprime todo lo necesario para escribir cada manifest.

- [ ] **Step 1: Write the inspection script**

```python
# backend/scripts/inspect_onnx.py
"""Imprime IO spec + sha256 de un .onnx: todo lo que necesita un manifest curado.

Uso: python scripts/inspect_onnx.py <ruta-o-url-del-modelo>
"""
import hashlib
import sys
import tempfile
from pathlib import Path

import httpx
import onnxruntime as ort


def _fetch(src: str) -> Path:
    if not src.startswith("http"):
        return Path(src)
    dest = Path(tempfile.mkdtemp()) / src.rsplit("/", 1)[-1]
    with httpx.stream("GET", src, follow_redirects=True, timeout=120.0) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    return dest


def main() -> None:
    path = _fetch(sys.argv[1])
    print(f"file: {path.name}")
    print(f"size_mb: {path.stat().st_size / 1e6:.2f}")
    print(f"sha256: {hashlib.sha256(path.read_bytes()).hexdigest()}")
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    print("inputs:")
    for t in session.get_inputs():
        print(f"  - {t.name}  shape={t.shape}  dtype={t.type}")
    print("outputs:")
    for t in session.get_outputs():
        print(f"  - {t.name}  shape={t.shape}  dtype={t.type}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Localizar los archivos de modelo publicados**

Para cada candidato, encontrar el asset ONNX real (nombres verificados durante investigación 2026-08-18, re-verificar al ejecutar):

```powershell
# DPDFNet — HF org ceva-ip (modelos 9.7-14.2 MB, incl. dpdfnet2_48khz_hr)
.\.venv\Scripts\python.exe -c "from huggingface_hub import list_repo_files; print(list_repo_files('ceva-ip/DPDFNet'))"
# Si el repo id difiere, buscar: list_models(author='ceva-ip')

# FastEnhancer — assets ONNX en GitHub releases
curl.exe -s https://api.github.com/repos/aask1357/fastenhancer/releases/latest

# GTCRN — release assets de sherpa-onnx (gtcrn_simple.onnx)
curl.exe -s https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/tags/speech-enhancement-models
```

- [ ] **Step 3: Inspeccionar cada modelo y escribir su manifest**

Por cada modelo: `python scripts/inspect_onnx.py <url>` → con el output, escribir `backend/stfu/hub/curated/<id>.json` con el esquema de Task 1. Ejemplo de estructura (los valores de io_spec/sha256 salen del script, NO inventarlos):

```json
{
  "id": "gtcrn",
  "name": "GTCRN",
  "version": "1.0",
  "plugin_class": "stfu.plugins.onnx_streaming.OnnxStreamingPlugin",
  "source": "url",
  "url": "<asset url del release de sherpa-onnx>",
  "file": "gtcrn_simple.onnx",
  "sha256": "<del script>",
  "preferred_format": {"sample_rate": 16000, "channels": 1, "chunk_samples": 256},
  "size_mb": 0.5,
  "algorithmic_latency_ms": 16.0,
  "tier": "floor",
  "license": "MIT",
  "supported_devices": ["cpu", "gpu"],
  "io_spec": {
    "audio_input": {"name": "<del script>", "shape": [1, "chunk"]},
    "audio_output": "<del script>",
    "states": [{"input": "<del script>", "output": "<del script>", "shape": ["<del script>"]}]
  }
}
```

**Criterio de exclusión:** si un modelo NO es waveform-in/waveform-out (pide espectrogramas o features externas como entrada), se excluye del lineup de F2 y se anota en el manifest-candidato con un comentario en el commit — el soporte de front-ends de features es trabajo futuro, no de este plan. El lineup mínimo aceptable de F2 es DOS modelos funcionando (uno floor + uno 48k).

- [ ] **Step 4: Smoke test real por modelo**

```powershell
# instala desde el catálogo real y corre un chunk
.\.venv\Scripts\python.exe -c "
from stfu.core.pipeline_factory import build_pipeline, default_registry
from stfu.hub.manager import HubManager
from pathlib import Path
import numpy as np
hub = HubManager(default_registry(), Path('stfu/hub/curated'))
hub.download('gtcrn')
p = build_pipeline([{'plugin_id': 'model:gtcrn'}], device='cpu')
from stfu.core.audio_format import AudioFormat
p.compile(AudioFormat(48000, 2, 960))
out = p.process(np.random.randn(960, 2).astype('float32') * 0.1)
print('OK', out.shape, np.isfinite(out).all())
"
```
Expected: `OK (960, 2) True` — el FormatAdapter convierte 48k estéreo → el formato del modelo y de vuelta.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/inspect_onnx.py backend/stfu/hub/curated/
git commit -m "feat: lineup curado — manifests verificados con io_spec y sha256 reales"
```

---

### Task 8: DFN3 a extra opcional + instalador sin torch

**Files:**
- Modify: `backend/requirements.txt` (quitar `deepfilternet`)
- Create: `backend/requirements-torch.txt`
- Modify: spec de PyInstaller del backend (localizar con `Get-ChildItem backend -Filter *.spec`)
- Test: `backend/tests/test_pipeline_factory.py` (ya cubre el error claro — Task 4, test `test_dfn3_without_torch_gives_clear_error`)

- [ ] **Step 1: requirements split**

`backend/requirements.txt`: eliminar la línea `deepfilternet>=0.5.6`.

`backend/requirements-torch.txt` (nuevo):

```
# Extra opcional: DeepFilterNet3 legacy (torch). El lineup ONNX no lo necesita.
-r requirements.txt
deepfilternet>=0.5.6
```

- [ ] **Step 2: PyInstaller excluye torch**

Localizar el spec: `Get-ChildItem backend -Filter *.spec` (y `Get-ChildItem . -Filter *.spec` desde la raíz si no aparece). En el `Analysis(...)` agregar/extender:

```python
    excludes=["torch", "torchaudio", "df", "deepfilternet"],
```

y verificar que `stfu/hub/curated/*.json` entre en `datas` (los manifests curados deben viajar en el binario):

```python
    datas=[("stfu/hub/curated", "stfu/hub/curated")],
```

- [ ] **Step 3: Rebuild del instalador y medición**

```powershell
cd backend
.\.venv\Scripts\pyinstaller.exe <spec>  # el spec localizado en Step 2
# medir el resultado
Get-ChildItem dist -Recurse | Measure-Object -Property Length -Sum
```
Expected: el onedir del backend baja de ~400-600MB a ~100-150MB. Si torch sigue apareciendo en `dist`, revisar imports transitivos con `python -X importtime -c "import stfu.main"`.

- [ ] **Step 4: Suite completa en un venv limpio (sin torch)**

```powershell
python -m venv .venv-clean
.\.venv-clean\Scripts\pip.exe install -r requirements.txt "onnx>=1.16"
.\.venv-clean\Scripts\python.exe -m pytest -v
```
Expected: todos PASS — ningún test importa torch/df fuera de guards. Si alguno lo hace, marcarlo `@pytest.mark.skipif(importlib.util.find_spec("df") is None, reason="extra torch")`.

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/requirements-torch.txt <spec-file>
git commit -m "feat: DFN3 pasa a extra torch opcional — instalador sin torch (~100MB)"
```

---

### Task 9: A/B de calidad + RTF — decisión del default

**Files:**
- Create: `backend/scripts/ab_models.py`

- [ ] **Step 1: Write the script**

```python
# backend/scripts/ab_models.py
"""Procesa un WAV ruidoso con cada modelo instalado: escribe un WAV por modelo
y reporta RTF (tiempo de proceso / duración del audio) en CPU.

Uso: python scripts/ab_models.py ruido.wav [--device cpu|gpu]
"""
import argparse
import time
from pathlib import Path

import numpy as np
import soundfile as sf  # scipy.io.wavfile como fallback si soundfile no está

from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline_factory import build_pipeline, default_registry


def process_wav(model_id: str, wav_path: Path, device: str) -> tuple[Path, float]:
    audio, rate = sf.read(wav_path, dtype="float32", always_2d=True)
    fmt = AudioFormat(sample_rate=rate, channels=audio.shape[1], chunk_samples=int(rate * 0.02))
    pipeline = build_pipeline([{"plugin_id": f"model:{model_id}"}], device=device)
    pipeline.compile(fmt)
    chunks = [
        audio[i:i + fmt.chunk_samples]
        for i in range(0, len(audio) - fmt.chunk_samples, fmt.chunk_samples)
    ]
    out = []
    t0 = time.perf_counter()
    for c in chunks:
        out.append(pipeline.process(c))
    elapsed = time.perf_counter() - t0
    rtf = elapsed / (len(audio) / rate)
    dest = wav_path.with_name(f"{wav_path.stem}__{model_id}.wav")
    sf.write(dest, np.concatenate(out), rate)
    return dest, rtf


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()
    installed = [m.id for m in default_registry().list()]
    if not installed:
        raise SystemExit("no hay modelos instalados — POST /models/<id>/download primero")
    print(f"{'modelo':<24} {'RTF':>8}  salida")
    for model_id in installed:
        dest, rtf = process_wav(model_id, args.wav, args.device)
        print(f"{model_id:<24} {rtf:>8.4f}  {dest.name}")


if __name__ == "__main__":
    main()
```

Dependencia: `soundfile` NO está en requirements — agregarla solo como dep de scripts/test (`soundfile>=0.12` junto a pytest en requirements.txt).

- [ ] **Step 2: Correr el A/B con audio real**

Grabar o conseguir un WAV con voz + ruido (teclado, ventilador). Correr:

```powershell
.\.venv\Scripts\python.exe scripts/ab_models.py ruido.wav
```

Escuchar los WAVs de salida + comparar RTF. Con DFN3 instalado como extra (`pip install -r requirements-torch.txt`), incluirlo como referencia de calidad.

- [ ] **Step 3: Decidir y documentar el default**

Con los números y la escucha: elegir el modelo default del instalador. Registrar la decisión con los RTF medidos en `docs/superpowers/audits/2026-XX-XX-ab-modelos.md` (tabla modelo × RTF × veredicto de escucha). El default elegido se fija como el modelo que la UI activa si el usuario no eligió otro.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/ab_models.py backend/requirements.txt docs/superpowers/audits/
git commit -m "feat: script A/B de modelos — RTF medido + WAVs para escucha comparada"
```

---

### Task 9b: Auto-degrade bajo presión (spec §3.5 — anti-Krisp)

**Files:**
- Create: `backend/stfu/audio/degrade_monitor.py`
- Modify: `backend/stfu/main.py` (lifespan: start/stop del monitor)
- Test: `backend/tests/test_degrade_monitor.py`

**Interfaces:**
- Consumes: `engine.get_stats()` (stages con `p95_ms`/`budget_ms`, F1), `engine.active_model_ids` (Task 5), `engine.swap_model` (Task 6), `HubManager.catalog()` (Task 5).
- Produces: `DegradeMonitor(engine, catalog_fn).start()/stop()` — thread que degrada el modelo NC al siguiente tier instalado tras K ticks consecutivos con p95 > budget. Nunca desactiva la cancelación.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_degrade_monitor.py
from stfu.audio.degrade_monitor import DegradeMonitor, _next_lighter_model


_CATALOG = [
    {"id": "dpdfnet2-48k-hr", "name": "DPDFNet 48kHz HR", "tier": "quality", "installed": True},
    {"id": "dpdfnet2-16k", "name": "DPDFNet2", "tier": "default", "installed": True},
    {"id": "fastenhancer-tiny", "name": "FastEnhancer Tiny", "tier": "floor", "installed": True},
    {"id": "gtcrn", "name": "GTCRN", "tier": "floor", "installed": False},
]


def test_next_lighter_model_picks_installed_lower_tier():
    assert _next_lighter_model("dpdfnet2-48k-hr", _CATALOG) == "dpdfnet2-16k"
    assert _next_lighter_model("dpdfnet2-16k", _CATALOG) == "fastenhancer-tiny"


def test_next_lighter_model_none_at_floor():
    assert _next_lighter_model("fastenhancer-tiny", _CATALOG) is None


class _FakeEngine:
    def __init__(self, over_budget: bool):
        p95 = 30.0 if over_budget else 5.0
        self._stats = {"mic": {"stages": [
            {"stage": "DPDFNet 48kHz HR", "p95_ms": p95, "budget_ms": 20.0, "ema_ms": p95, "overbudget": 0},
        ]}}
        self.swaps: list[tuple[str, str]] = []

    def get_stats(self):
        return self._stats

    def active_model_ids(self, target):
        return {"dpdfnet2-48k-hr"}

    def swap_model(self, target, model_id, device="auto"):
        self.swaps.append((target, model_id))
        return True


def test_degrades_after_consecutive_strikes():
    eng = _FakeEngine(over_budget=True)
    mon = DegradeMonitor(eng, lambda: _CATALOG, strikes_to_degrade=3)
    for _ in range(3):
        mon._tick()
    assert eng.swaps == [("mic", "dpdfnet2-16k")]


def test_healthy_stage_resets_strikes():
    eng = _FakeEngine(over_budget=True)
    mon = DegradeMonitor(eng, lambda: _CATALOG, strikes_to_degrade=3)
    mon._tick()
    mon._tick()
    eng._stats["mic"]["stages"][0]["p95_ms"] = 5.0  # se recuperó
    mon._tick()
    eng._stats["mic"]["stages"][0]["p95_ms"] = 30.0
    mon._tick()
    assert eng.swaps == []  # nunca juntó 3 seguidos


def test_cooldown_blocks_double_degrade():
    eng = _FakeEngine(over_budget=True)
    mon = DegradeMonitor(eng, lambda: _CATALOG, strikes_to_degrade=1, cooldown_ticks=10)
    mon._tick()
    mon._tick()
    assert len(eng.swaps) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_degrade_monitor.py -v`
Expected: FAIL — módulo no existe

- [ ] **Step 3: Implement**

```python
# backend/stfu/audio/degrade_monitor.py
"""Degradación automática bajo presión (spec §3.5): si el stage del modelo NC
sostiene p95 > budget, se baja al siguiente tier instalado más liviano.
La cancelación NUNCA se apaga por carga — a diferencia de Krisp."""
import logging
import threading

_log = logging.getLogger(__name__)

_TIER_ORDER = ["quality", "default", "floor"]  # de más pesado a más liviano


def _next_lighter_model(model_id: str, catalog: list[dict]) -> str | None:
    by_id = {m["id"]: m for m in catalog}
    current = by_id.get(model_id)
    if current is None or current["tier"] not in _TIER_ORDER:
        return None
    for tier in _TIER_ORDER[_TIER_ORDER.index(current["tier"]) + 1:]:
        candidate = next(
            (m for m in catalog if m["tier"] == tier and m["installed"] and m["id"] != model_id),
            None,
        )
        if candidate:
            return candidate["id"]
    return None


class DegradeMonitor:
    def __init__(self, engine, catalog_fn, interval_s: float = 5.0,
                 strikes_to_degrade: int = 3, cooldown_ticks: int = 24) -> None:
        self._engine = engine
        self._catalog_fn = catalog_fn
        self._interval = interval_s
        self._strikes_needed = strikes_to_degrade
        self._cooldown_ticks = cooldown_ticks
        self._strikes: dict[str, int] = {}
        self._cooldown: dict[str, int] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

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
            try:
                self._tick()
            except Exception:
                _log.exception("degrade monitor tick falló")

    def _tick(self) -> None:
        catalog = self._catalog_fn()
        model_names = {m["name"]: m["id"] for m in catalog}
        for target, stats in self._engine.get_stats().items():
            self._check_target(target, stats, model_names, catalog)

    def _check_target(self, target: str, stats: dict,
                      model_names: dict[str, str], catalog: list[dict]) -> None:
        if self._cooldown.get(target, 0) > 0:
            self._cooldown[target] -= 1
            return
        model_stages = [s for s in stats.get("stages", []) if s["stage"] in model_names]
        over = any(s["p95_ms"] > s["budget_ms"] for s in model_stages)
        if not over:
            self._strikes[target] = 0
            return
        self._strikes[target] = self._strikes.get(target, 0) + 1
        if self._strikes[target] < self._strikes_needed:
            return
        self._degrade(target, model_stages, model_names, catalog)

    def _degrade(self, target: str, model_stages: list[dict],
                 model_names: dict[str, str], catalog: list[dict]) -> None:
        current_id = model_names[model_stages[0]["stage"]]
        lighter = _next_lighter_model(current_id, catalog)
        self._strikes[target] = 0
        if lighter is None:
            _log.warning("%s: %s sobre budget pero ya es el tier más liviano", target, current_id)
            self._cooldown[target] = self._cooldown_ticks
            return
        _log.warning("%s: degradando %s → %s por presión sostenida", target, current_id, lighter)
        if self._engine.swap_model(target, lighter):
            self._cooldown[target] = self._cooldown_ticks
```

En `backend/stfu/main.py`, dentro de `lifespan` (antes del `yield` arranque, después parada):

```python
    from stfu.audio.degrade_monitor import DegradeMonitor
    from stfu.api.routes.models import _hub
    monitor = DegradeMonitor(engine, lambda: _hub().catalog())
    monitor.start()
    yield
    monitor.stop()
    engine.stop_all()
    from stfu.apo.apo_engine import apo_engine
    apo_engine.stop_all()
```

- [ ] **Step 4: Run tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_degrade_monitor.py tests/test_status_api.py -v`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/stfu/audio/degrade_monitor.py backend/stfu/main.py backend/tests/test_degrade_monitor.py
git commit -m "feat: auto-degrade a tier más liviano bajo presión sostenida — la cancelación nunca se apaga"
```

---

### Task 10: Suite completa + smoke E2E

- [ ] **Step 1: Suite completa**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: todos PASS

- [ ] **Step 2: Smoke E2E con backend real**

```powershell
cd backend; .\.venv\Scripts\python.exe -m uvicorn stfu.main:app --port 8765
# Otra terminal:
curl http://localhost:8765/models                                  # catálogo curado
curl -X POST http://localhost:8765/models/gtcrn/download           # descarga real
# activar mic desde la UI (o POST /pipeline/mic con model:gtcrn) y hablar
curl http://localhost:8765/status                                  # stages con ema_ms del modelo ONNX
curl -X POST "http://localhost:8765/models/dpdfnet2-48k-hr/activate?target=mic"  # swap en vivo, sin glitch
```
Expected: cancelación audible con el modelo ONNX, swap sin corte del stream, `stages` reportando el costo real por chunk.

- [ ] **Step 3: Commit de cierre si quedaron restos**

```bash
git status --short
```
