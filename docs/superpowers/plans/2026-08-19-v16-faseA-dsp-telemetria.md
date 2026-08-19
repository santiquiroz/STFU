# v1.6 Fase A — Cadena DSP + catálogo + telemetría de audio + A/B bypass: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar los plugins DSP de la cadena de voz canónica (noise gate, compressor/AGC, de-esser, limiter), un catálogo `GET /plugins` para auto-generar UI, telemetría de audio en vivo (RMS pre/post → reducción en dB + espectro), y A/B bypass. Convierte el backend en una estación de voz editable.

**Architecture:** Cada plugin DSP es una subclase de `AudioPlugin` (patrón de `eq_parametric.py`: stateful, swap atómico de estado bajo el GIL, `Parameter` metadata, `set_parameter` que reconstruye/actualiza) — formato-estable 48k/mono/960, así que cumple el invariante `setup()→fmt` y encadena sin adapters. Se registran en el dict `builtin` de `pipeline_factory.py`. La telemetría vive en `CaptureThread._process_and_output` (worker, single-writer, patrón de los contadores xrun) y sale por el `stats` existente. El bypass es un flag atómico leído en el worker.

**Tech Stack:** Python 3.11+, numpy, scipy.signal, FastAPI, pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-19-v16-voice-studio-design.md`

## Global Constraints

- Base: master post v1.5 (merge `1e13abe`). El driver v2 (`driver/`) NO se toca.
- Correr tests desde `backend/`: `.\.venv\Scripts\python.exe -m pytest`. Suite base 241 verde + los nuevos.
- Todos los plugins DSP: `preferred_format = AudioFormat(48000, 1, 960)`, `setup()` devuelve `fmt` sin cambiar (invariante del hot-swap), `process()` recibe/devuelve `(N, 1) float32`.
- Estado persistente entre chunks (envelope followers, filtros) — NO resetear por chunk. Swap atómico de estado como en `eq_parametric.py` (leer la referencia una vez, comparar identidad antes de escribir).
- El worker corre en budget de 20ms/chunk; el DSP debe ser numpy vectorizado, sin loops Python por sample donde se pueda evitar (envelope por-sample con `np.maximum.accumulate` o recurrencia vectorizada; si hace falta un loop, mantenerlo simple y medir).
- Commits en español, convencional, sin `Co-Authored-By`.
- No romper el pipeline/feeder existentes; todo es aditivo.

---

### Task 1: Noise Gate plugin

**Files:**
- Create: `backend/stfu/plugins/builtin/noise_gate.py`
- Test: `backend/tests/test_noise_gate.py`

**Interfaces:**
- Produces: `NoiseGatePlugin(AudioPlugin)` con `name="Noise Gate"`, params: `threshold_db` (float, -80..0, default -45), `attack_ms` (float, 1..100, default 5), `release_ms` (float, 10..1000, default 150), `hold_ms` (float, 0..500, default 50). Registrado en Task 5.

**Behavior contract (los tests lo fijan):** un envelope follower sigue el nivel de la señal; cuando el nivel cae por debajo de `threshold_db`, la ganancia baja hacia 0 con la constante de `release` (tras esperar `hold`); cuando sube por encima, la ganancia sube hacia 1 con `attack`. Estado (ganancia actual + contador de hold) persiste entre chunks.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_noise_gate.py
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.builtin.noise_gate import NoiseGatePlugin

_FMT = AudioFormat(48000, 1, 960)


def _gate(**params):
    g = NoiseGatePlugin()
    g.setup(_FMT)
    for k, v in params.items():
        g.set_parameter(k, v)
    return g


def _tone(amp, n=48000):
    t = np.arange(n) / 48000.0
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32).reshape(-1, 1)


def _process_all(gate, sig):
    out = []
    for i in range(0, len(sig) - 960, 960):
        out.append(gate.process(sig[i:i + 960]))
    return np.concatenate(out)


def test_loud_signal_passes_mostly_unattenuated():
    gate = _gate(threshold_db=-45.0, attack_ms=5.0)
    loud = _tone(0.5)  # ~ -6 dBFS, muy por encima del umbral
    out = _process_all(gate, loud)
    # tras el ataque, la energía de salida ≈ la de entrada (gate abierto)
    tail_in = np.sqrt(np.mean(loud[24000:]**2))
    tail_out = np.sqrt(np.mean(out[24000 - 960:]**2))
    assert tail_out > 0.9 * tail_in


def test_quiet_signal_gets_attenuated():
    gate = _gate(threshold_db=-45.0, release_ms=100.0, hold_ms=0.0)
    quiet = _tone(0.001)  # ~ -60 dBFS, por debajo del umbral
    out = _process_all(gate, quiet)
    tail = np.sqrt(np.mean(out[24000:]**2))
    quiet_rms = np.sqrt(np.mean(quiet[24000:]**2))
    assert tail < 0.1 * quiet_rms  # fuertemente atenuado


def test_gate_state_persists_across_chunks():
    gate = _gate(threshold_db=-45.0)
    loud = _tone(0.5, n=2000)
    gate.process(loud[:960])
    g_after_first = gate._gain
    gate.process(loud[960:1920])
    # el gate ya está abierto: la ganancia se mantiene alta, no reinicia a 0
    assert gate._gain >= g_after_first - 1e-6


def test_output_shape_and_dtype():
    gate = _gate()
    out = gate.process(_tone(0.3, n=960))
    assert out.shape == (960, 1)
    assert out.dtype == np.float32
```

- [ ] **Step 2: Run to verify fail** — `.\.venv\Scripts\python.exe -m pytest tests/test_noise_gate.py -v` → módulo no existe.

- [ ] **Step 3: Implement** `noise_gate.py`. Guía DSP (el implementer ajusta hasta pasar los tests):
  - `setup`: guarda sample_rate; inicializa `self._gain = 0.0`, `self._hold_counter = 0`.
  - Coeficientes: `attack_coef = exp(-1/(attack_ms*1e-3*fs))`, `release_coef = exp(-1/(release_ms*1e-3*fs))`, `hold_samples = int(hold_ms*1e-3*fs)`.
  - `process`: computar el envelope de amplitud del chunk (p.ej. `np.abs(audio[:,0])`), decidir abierto/cerrado por chunk vs `10**(threshold_db/20)`; suavizar la ganancia hacia 1 (attack) o hacia 0 (release) respetando `hold`. Se puede procesar por bloque (una ganancia suave por chunk) o por sample; empezar por-bloque con un envelope simple y refinar si un test lo exige. Multiplicar el audio por la envolvente de ganancia. Estado `_gain`/`_hold_counter` persiste.
  - `parameters`/`set_parameter`: los 4 params; `set_parameter` recomputa coeficientes.
  - `algorithmic_latency_ms = 0.0`.

- [ ] **Step 4: Run** `.\.venv\Scripts\python.exe -m pytest tests/test_noise_gate.py -v` → 4 PASS.

- [ ] **Step 5: Commit** — `git add ...` / `git commit -m "feat(dsp): plugin Noise Gate con envelope follower y estado persistente"`

---

### Task 2: Compressor / AGC plugin

**Files:**
- Create: `backend/stfu/plugins/builtin/compressor.py`
- Test: `backend/tests/test_compressor.py`

**Interfaces:**
- Produces: `CompressorPlugin(AudioPlugin)` `name="Compresor"`, params: `threshold_db` (-60..0, default -24), `ratio` (1..20, default 3), `attack_ms` (1..100, default 10), `release_ms` (10..1000, default 120), `makeup_db` (0..24, default 0), `agc` (bool, default false), `agc_target_db` (-40..0, default -18). Registrado en Task 5.

**Behavior contract:** reduce el rango dinámico — señales sobre `threshold_db` se atenúan según `ratio`; con `makeup_db` se recupera nivel. En modo `agc`, ajusta la ganancia para converger el RMS de salida hacia `agc_target_db` (auto-leveling). Estado (envelope + ganancia AGC) persiste.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_compressor.py
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.builtin.compressor import CompressorPlugin

_FMT = AudioFormat(48000, 1, 960)


def _comp(**p):
    c = CompressorPlugin()
    c.setup(_FMT)
    for k, v in p.items():
        c.set_parameter(k, v)
    return c


def _tone(amp, n=48000, f=220):
    t = np.arange(n) / 48000.0
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32).reshape(-1, 1)


def _run(c, sig):
    out = []
    for i in range(0, len(sig) - 960, 960):
        out.append(c.process(sig[i:i + 960]))
    return np.concatenate(out)


def _rms_db(x):
    r = np.sqrt(np.mean(x**2))
    return 20 * np.log10(r + 1e-12)


def test_reduces_dynamic_range():
    c = _comp(threshold_db=-24.0, ratio=4.0, makeup_db=0.0)
    loud = _run(c, _tone(0.5))   # fuerte
    c2 = _comp(threshold_db=-24.0, ratio=4.0, makeup_db=0.0)
    quiet = _run(c2, _tone(0.05))  # flojo (por debajo del umbral, casi sin tocar)
    # el rango entre fuerte y flojo se comprime: la diferencia de salida < la de entrada
    in_range = _rms_db(_tone(0.5)) - _rms_db(_tone(0.05))
    out_range = _rms_db(loud[24000:]) - _rms_db(quiet[24000:])
    assert out_range < in_range - 3.0   # al menos 3 dB de compresión de rango


def test_below_threshold_barely_touched():
    c = _comp(threshold_db=-12.0, ratio=4.0, makeup_db=0.0)
    quiet = _tone(0.05)  # ~ -26 dBFS, debajo de -12
    out = _run(c, quiet)
    assert abs(_rms_db(out[24000:]) - _rms_db(quiet[24000:])) < 2.0


def test_agc_converges_toward_target():
    c = _comp(agc=True, agc_target_db=-18.0)
    quiet = _tone(0.02)  # muy por debajo del target
    out = _run(c, quiet)
    assert _rms_db(out[36000:]) > _rms_db(quiet[36000:]) + 3.0  # AGC subió el nivel hacia el target


def test_output_shape_dtype():
    c = _comp()
    out = c.process(_tone(0.3, n=960))
    assert out.shape == (960, 1) and out.dtype == np.float32
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** `compressor.py`. Guía: envelope follower del nivel (attack/release); ganancia de compresión estática `gain_db = (level_db - threshold_db) * (1/ratio - 1)` cuando `level_db > threshold_db`, else 0; sumar `makeup_db`. AGC: mantener una ganancia lenta que empuja el RMS de salida hacia `agc_target_db` (paso proporcional al error, limitado). Estado del envelope y de la ganancia AGC persiste entre chunks. Vectorizar.

- [ ] **Step 4: Run** → 4 PASS.

- [ ] **Step 5: Commit** — `feat(dsp): plugin Compresor con modo AGC (auto-leveling)`

---

### Task 3: De-esser plugin

**Files:**
- Create: `backend/stfu/plugins/builtin/de_esser.py`
- Test: `backend/tests/test_de_esser.py`

**Interfaces:**
- Produces: `DeEsserPlugin(AudioPlugin)` `name="De-esser"`, params: `freq_hz` (2000..12000, default 6000), `threshold_db` (-60..0, default -30), `reduction_db` (0..24, default 8). Registrado en Task 5.

**Behavior contract:** detecta energía en la banda de sibilancia (highpass/bandpass alrededor de `freq_hz`); cuando esa banda supera `threshold_db`, atenúa esa banda hasta `reduction_db` (split-band: separa la banda alta, la comprime, la recombina). Una señal con mucha energía en 6-8kHz sale con menos energía ahí; una señal sin sibilancia casi no se toca.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_de_esser.py
import numpy as np
from scipy.signal import welch
from stfu.core.audio_format import AudioFormat
from stfu.plugins.builtin.de_esser import DeEsserPlugin

_FMT = AudioFormat(48000, 1, 960)


def _de(**p):
    d = DeEsserPlugin()
    d.setup(_FMT)
    for k, v in p.items():
        d.set_parameter(k, v)
    return d


def _tone(amp, f, n=48000):
    t = np.arange(n) / 48000.0
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32).reshape(-1, 1)


def _run(d, sig):
    out = []
    for i in range(0, len(sig) - 960, 960):
        out.append(d.process(sig[i:i + 960]))
    return np.concatenate(out)


def test_sibilant_band_reduced():
    d = _de(freq_hz=6000.0, threshold_db=-40.0, reduction_db=12.0)
    sib = _tone(0.5, 7000)  # fuerte en la banda de sibilancia
    out = _run(d, sib)
    r_in = np.sqrt(np.mean(sib[24000:]**2))
    r_out = np.sqrt(np.mean(out[24000:]**2))
    assert r_out < 0.6 * r_in   # la sibilancia se atenuó notablemente


def test_low_freq_voice_barely_touched():
    d = _de(freq_hz=6000.0, threshold_db=-40.0, reduction_db=12.0)
    voice = _tone(0.5, 300)  # tono grave, sin sibilancia
    out = _run(d, voice)
    r_in = np.sqrt(np.mean(voice[24000:]**2))
    r_out = np.sqrt(np.mean(out[24000:]**2))
    assert r_out > 0.85 * r_in   # casi intacto


def test_output_shape_dtype():
    d = _de()
    out = d.process(_tone(0.3, 500, n=960))
    assert out.shape == (960, 1) and out.dtype == np.float32
```

- [ ] **Step 2-5:** implementar (split-band con biquad highpass/bandpass + envelope + reducción; `sosfilt` con `zi` persistente como EQ), correr → PASS, commit `feat(dsp): plugin De-esser (compresión split-band de sibilancia)`.

---

### Task 4: Limiter plugin

**Files:**
- Create: `backend/stfu/plugins/builtin/limiter.py`
- Test: `backend/tests/test_limiter.py`

**Interfaces:**
- Produces: `LimiterPlugin(AudioPlugin)` `name="Limitador"`, params: `ceiling_db` (-24..0, default -1), `release_ms` (10..500, default 50). Registrado en Task 5.

**Behavior contract:** garantiza que la salida nunca supere `ceiling` en amplitud — cuando un pico lo supera, aplica ganancia reductora instantánea y suelta con `release`. `|out| ≤ ceiling_lin + epsilon` SIEMPRE.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_limiter.py
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.builtin.limiter import LimiterPlugin

_FMT = AudioFormat(48000, 1, 960)


def _lim(**p):
    l = LimiterPlugin()
    l.setup(_FMT)
    for k, v in p.items():
        l.set_parameter(k, v)
    return l


def _run(l, sig):
    out = []
    for i in range(0, len(sig) - 960, 960):
        out.append(l.process(sig[i:i + 960]))
    return np.concatenate(out)


def test_output_never_exceeds_ceiling():
    l = _lim(ceiling_db=-6.0)  # ceiling ≈ 0.501
    ceiling_lin = 10 ** (-6.0 / 20.0)
    t = np.arange(48000) / 48000.0
    loud = (1.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32).reshape(-1, 1)  # clippearía sin limiter
    out = _run(l, loud)
    assert np.max(np.abs(out)) <= ceiling_lin + 1e-3


def test_quiet_signal_unchanged():
    l = _lim(ceiling_db=-1.0)
    t = np.arange(48000) / 48000.0
    quiet = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32).reshape(-1, 1)
    out = _run(l, quiet)
    np.testing.assert_allclose(out[9600:], quiet[9600:], atol=0.02)  # por debajo del techo: intacto


def test_output_shape_dtype():
    l = _lim()
    out = l.process((0.3 * np.ones((960, 1))).astype(np.float32))
    assert out.shape == (960, 1) and out.dtype == np.float32
```

- [ ] **Step 2-5:** implementar (envelope de pico + ganancia reductora con release; look-ahead opcional simple), correr → PASS, commit `feat(dsp): plugin Limitador con techo garantizado`.

---

### Task 5: Registrar plugins + `GET /plugins` catálogo

**Files:**
- Modify: `backend/stfu/core/pipeline_factory.py`
- Create: `backend/stfu/api/routes/plugins.py`
- Modify: `backend/stfu/main.py` (montar el router)
- Test: `backend/tests/test_plugins_catalog.py`

**Interfaces:**
- Consumes: los 4 plugins (Tasks 1-4).
- Produces: el dict `builtin` de `_make_plugin` gana `noise_gate`, `compressor`, `de_esser`, `limiter`. `GET /plugins` → lista de `{plugin_id, name, version, parameters: [{id, label, type, default, min, max, options}]}` para cada builtin (gain, eq_parametric, noise_gate, compressor, de_esser, limiter). El catálogo lo consume la UI de la Fase C para auto-generar sliders.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_plugins_catalog.py
from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)


def test_catalog_lists_builtins():
    r = client.get("/plugins")
    assert r.status_code == 200
    by_id = {p["plugin_id"]: p for p in r.json()}
    for pid in ("gain", "eq_parametric", "noise_gate", "compressor", "de_esser", "limiter"):
        assert pid in by_id
        assert "parameters" in by_id[pid]


def test_catalog_param_shape():
    r = client.get("/plugins")
    comp = next(p for p in r.json() if p["plugin_id"] == "compressor")
    ids = {pp["id"] for pp in comp["parameters"]}
    assert {"threshold_db", "ratio", "attack_ms", "release_ms", "makeup_db"} <= ids
    thr = next(pp for pp in comp["parameters"] if pp["id"] == "threshold_db")
    assert thr["type"] == "float" and "min" in thr and "max" in thr
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement**
  - `pipeline_factory.py`: importar los 4 y agregarlos al dict `builtin` (line 45). Exponer una lista de los ids builtin instanciables sin args para el catálogo, p.ej. una constante `BUILTIN_PLUGINS = {"gain": GainPlugin, "eq_parametric": EQParametricPlugin, "noise_gate": NoiseGatePlugin, "compressor": CompressorPlugin, "de_esser": DeEsserPlugin, "limiter": LimiterPlugin}` y que `_make_plugin` la use.
  - `routes/plugins.py`: `GET /plugins` instancia cada builtin, lee `.name/.version/.parameters` (dataclass `Parameter` → dict vía `dataclasses.asdict`), retorna la lista. (No incluir `model:`/dfn3 — el catálogo es de efectos DSP builtin; los modelos van por `/models`.)
  - `main.py`: `app.include_router(plugins_router)`.

- [ ] **Step 4: Run** `.\.venv\Scripts\python.exe -m pytest tests/test_plugins_catalog.py tests/test_api.py -v` → PASS.

- [ ] **Step 5: Commit** — `feat(api): catálogo GET /plugins con metadata de parámetros para auto-generar UI`

---

### Task 6: Telemetría de audio (RMS pre/post + reducción dB + espectro)

**Files:**
- Modify: `backend/stfu/audio/capture.py`
- Test: `backend/tests/test_audio_telemetry.py`

**Interfaces:**
- Produces: `CaptureThread.stats` gana `"audio": {"pre_db": float, "post_db": float, "reduction_db": float, "spectrum_pre": list[float], "spectrum_post": list[float]}`. `pre_db`/`post_db` = RMS en dBFS del chunk crudo vs procesado; `reduction_db = pre_db - post_db` (positivo = se atenuó ruido/energía). `spectrum_*` = ~48 bins log-espaciados de magnitud (dB), recomputados cada N chunks. Lo consume el visualizador de la Fase C.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_audio_telemetry.py
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.capture import CaptureThread
from stfu.plugins.base import AudioPlugin


class _Halver(AudioPlugin):
    name = "halver"
    version = "1.0"

    @property
    def preferred_format(self):
        return AudioFormat(48000, 1, 960)

    def setup(self, fmt):
        return fmt

    def process(self, audio):
        return audio * 0.5   # baja 6 dB → reduction_db ≈ 6

    def teardown(self):
        pass

    @property
    def algorithmic_latency_ms(self):
        return 0.0

    @property
    def parameters(self):
        return []


def _thread(pipeline):
    fmt = AudioFormat(48000, 2, 960)
    pipeline.compile(fmt)
    return CaptureThread(input_device_id=0, output_device_id=0, fmt=fmt, pipeline=pipeline, out_channels=2)


def test_audio_stats_present_and_reduction_positive_when_attenuating():
    p = Pipeline()
    p.add_plugin(_Halver())
    t = _thread(p)
    chunk = (0.5 * np.ones((960, 2), dtype=np.float32))
    # ejercitar el cálculo de telemetría directamente
    t._record_audio_telemetry(chunk, chunk * 0.5)
    audio = t.stats["audio"]
    assert audio["reduction_db"] > 5.0 and audio["reduction_db"] < 7.0
    assert audio["pre_db"] > audio["post_db"]


def test_spectrum_has_bins():
    p = Pipeline()
    t = _thread(p)
    chunk = np.random.randn(960, 2).astype(np.float32) * 0.1
    for _ in range(10):
        t._record_audio_telemetry(chunk, chunk)
    spec = t.stats["audio"]["spectrum_post"]
    assert isinstance(spec, list) and len(spec) >= 16


def test_silence_reduction_zero_ish():
    p = Pipeline()
    t = _thread(p)
    z = np.zeros((960, 2), dtype=np.float32)
    t._record_audio_telemetry(z, z)
    assert abs(t.stats["audio"]["reduction_db"]) < 1.0
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement** en `capture.py`:
  - En `__init__`: inicializar `self._audio_pre_db = -120.0`, `self._audio_post_db = -120.0`, `self._spectrum_pre: list = []`, `self._spectrum_post: list = []` (single-writer: el worker).
  - Método `_record_audio_telemetry(self, pre: np.ndarray, post: np.ndarray)`:
    - `pre_db = 20*log10(rms(pre)+1e-9)` (clip a -120), ídem post. Guardar en los atributos.
    - Cada `_chunks_since_update % N == 0` (N ~ 5): `rfft` del canal 0 mono-mezcla, magnitud, agrupar en ~48 bins log-espaciados (20Hz..20kHz), a dB, guardar en `_spectrum_pre`/`_spectrum_post` como listas de float.
  - Llamarlo desde `_process_and_output`, pasando el `chunk` crudo (pre) y `processed` (post) ANTES del resample/ring. Cuidado con el costo: el rfft solo cada N chunks; el RMS es barato.
  - En `stats`: agregar `"audio": {"pre_db": round(self._audio_pre_db,1), "post_db": round(self._audio_post_db,1), "reduction_db": round(self._audio_pre_db - self._audio_post_db,1), "spectrum_pre": self._spectrum_pre, "spectrum_post": self._spectrum_post}`.
  - Nota: `_process_and_output` recibe el chunk en el formato del stream (48k/2ch). El `pre` es ese chunk; el `post` es `processed`. Usar mezcla mono para el espectro y el RMS sobre todo el chunk.

- [ ] **Step 4: Run** `.\.venv\Scripts\python.exe -m pytest tests/test_audio_telemetry.py tests/test_capture_worker.py -v` → PASS.

- [ ] **Step 5: Commit** — `feat(audio): telemetría RMS pre/post (reducción en dB) y espectro en stats`

---

### Task 7: A/B bypass

**Files:**
- Modify: `backend/stfu/audio/capture.py` (flag + método)
- Modify: `backend/stfu/audio/engine.py` (set_bypass)
- Modify: `backend/stfu/api/routes/pipeline.py` (ruta bypass) y `backend/stfu/api/routes/feeder.py` (ruta bypass)
- Test: `backend/tests/test_bypass.py`

**Interfaces:**
- Produces: `CaptureThread.set_bypass(on: bool)` (atómico); cuando bypass está on, `_process_or_passthrough` devuelve el chunk crudo sin procesar. `AudioEngine.set_bypass(target, on) -> bool`. `POST /feeder/bypass` (body `{on: bool}`) y `POST /pipeline/{target}/bypass`. `stats` gana `"bypass": bool`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_bypass.py
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.capture import CaptureThread
from stfu.plugins.base import AudioPlugin


class _Zeroer(AudioPlugin):
    name = "zeroer"
    version = "1.0"

    @property
    def preferred_format(self):
        return AudioFormat(48000, 2, 960)

    def setup(self, fmt):
        return fmt

    def process(self, audio):
        return np.zeros_like(audio)  # borra todo → distinguible de passthrough

    def teardown(self):
        pass

    @property
    def algorithmic_latency_ms(self):
        return 0.0

    @property
    def parameters(self):
        return []


def _thread():
    fmt = AudioFormat(48000, 2, 960)
    p = Pipeline()
    p.add_plugin(_Zeroer())
    p.compile(fmt)
    return CaptureThread(input_device_id=0, output_device_id=0, fmt=fmt, pipeline=p, out_channels=2)


def test_bypass_off_processes():
    t = _thread()
    chunk = np.ones((960, 2), dtype=np.float32)
    out = t._process_or_passthrough(chunk)
    assert np.all(out == 0.0)  # el plugin borró (bypass off)


def test_bypass_on_returns_raw():
    t = _thread()
    t.set_bypass(True)
    chunk = np.ones((960, 2), dtype=np.float32)
    out = t._process_or_passthrough(chunk)
    np.testing.assert_array_equal(out, chunk)  # crudo, sin procesar
    assert t.stats["bypass"] is True


def test_bypass_toggles_back():
    t = _thread()
    t.set_bypass(True)
    t.set_bypass(False)
    out = t._process_or_passthrough(np.ones((960, 2), dtype=np.float32))
    assert np.all(out == 0.0)
```

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement**
  - `capture.py`: `self._bypass = False` en `__init__`; `set_bypass(self, on)` setea el bool; en `_process_or_passthrough`, al inicio: `if self._bypass: return audio`. `stats` gana `"bypass": self._bypass`.
  - `engine.py`: `set_bypass(self, target, on) -> bool` — toma el thread bajo lock, llama `thread.set_bypass(on)`, retorna True/False si no existe.
  - `routes/feeder.py`: `POST /feeder/bypass` body `{on: bool}` → `engine.set_bypass("feeder", on)`; 404 si no activo.
  - `routes/pipeline.py`: `POST /pipeline/{target}/bypass` análogo.

- [ ] **Step 4: Run** `.\.venv\Scripts\python.exe -m pytest tests/test_bypass.py tests/test_feeder.py tests/test_api.py -v` → PASS.

- [ ] **Step 5: Commit** — `feat(audio): A/B bypass en vivo (flag del worker + rutas /bypass)`

---

### Task 8: Suite completa + smoke con cadena DSP real

- [ ] **Step 1: Suite** — `.\.venv\Scripts\python.exe -m pytest -q` → todo verde (241 base + nuevos).

- [ ] **Step 2: Smoke — cadena real por un WAV**

```powershell
cd backend
.\.venv\Scripts\python.exe -c "
import numpy as np
from stfu.core.pipeline_factory import build_pipeline
from stfu.core.audio_format import AudioFormat
# cadena: gate -> compresor -> de-esser -> limiter
chain = [
  {'plugin_id':'noise_gate','parameters':{'threshold_db':-45.0}},
  {'plugin_id':'compressor','parameters':{'threshold_db':-24.0,'ratio':3.0,'makeup_db':4.0}},
  {'plugin_id':'de_esser','parameters':{}},
  {'plugin_id':'limiter','parameters':{'ceiling_db':-1.0}},
]
p = build_pipeline(chain)
p.compile(AudioFormat(48000,2,960))
sig = (np.random.randn(48000,2)*0.1).astype('float32')
out = np.concatenate([p.process(sig[i:i+960]) for i in range(0,47040,960)])
ceiling = 10**(-1.0/20.0)
print('chain OK', out.shape, 'finite', np.isfinite(out).all(), 'under ceiling', np.max(np.abs(out))<=ceiling+1e-2)
"
```
Expected: `chain OK (N,2) finite True under ceiling True` — la cadena de 4 plugins corre y el limiter respeta el techo.

- [ ] **Step 3: Smoke API** — arrancar uvicorn, `curl http://localhost:8765/plugins` (lista 6 builtins), matar. Commit de cierre si quedó algo.
