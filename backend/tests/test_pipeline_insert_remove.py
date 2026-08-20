"""insert_plugin/remove_plugin: extensión quirúrgica de replace_plugin (ver
test_pipeline_surgical_swap.py) para cambios que alteran el largo de la
cadena. Cubre Pipeline en aislamiento y la aplicación staged vía
CaptureThread._drain_swaps (mismo patrón que test_model_swap.py)."""
import numpy as np
import pytest
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.capture import CaptureThread
from stfu.plugins.base import AudioPlugin


class _FmtPlugin(AudioPlugin):
    version = "1.0"

    def __init__(self, tag: str, rate: int = 48000, latency_ms: float = 0.0):
        self._tag = tag
        self._rate = rate
        self._latency_ms = latency_ms
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
        return self._latency_ms

    @property
    def parameters(self):
        return []


def _fmt():
    return AudioFormat(48000, 1, 480)


def _compiled(*plugins):
    p = Pipeline()
    for pl in plugins:
        p.add_plugin(pl)
    p.compile(_fmt())
    return p


def test_insert_at_start_keeps_existing_plugins():
    b = _FmtPlugin("b")
    p = _compiled(b)
    a = _FmtPlugin("a")

    p.insert_plugin(0, a)

    assert [pl.name for pl in p._plugins] == ["a", "b"]
    assert [m["stage"] for m in p.stage_metrics()] == ["a", "b"]


def test_insert_at_middle_keeps_neighbors():
    a, c = _FmtPlugin("a"), _FmtPlugin("c")
    p = _compiled(a, c)
    b = _FmtPlugin("b")

    p.insert_plugin(1, b)

    assert [pl.name for pl in p._plugins] == ["a", "b", "c"]


def test_insert_at_end_appends():
    a = _FmtPlugin("a")
    p = _compiled(a)
    b = _FmtPlugin("b")

    p.insert_plugin(1, b)

    assert [pl.name for pl in p._plugins] == ["a", "b"]
    assert p._output_adapter is None  # mismo formato: sin adapter de salida


def test_insert_does_not_resetup_untouched_neighbors():
    a, c = _FmtPlugin("a"), _FmtPlugin("c")
    p = _compiled(a, c)
    a.setup_calls = 0
    c.setup_calls = 0
    b = _FmtPlugin("b")

    p.insert_plugin(1, b)

    assert a.setup_calls == 0
    assert c.setup_calls == 0  # solo se reconectan adapters, nadie se re-setupea


def test_insert_preserves_processing_contract():
    a = _FmtPlugin("a")
    p = _compiled(a)
    b = _FmtPlugin("b")
    p.insert_plugin(1, b)

    audio = np.ones((480, 1), dtype=np.float32)
    out = p.process(audio)
    assert out.shape == (480, 1)
    assert out.dtype == np.float32


def test_insert_bad_index_raises():
    p = _compiled(_FmtPlugin("a"))
    with pytest.raises(IndexError):
        p.insert_plugin(5, _FmtPlugin("x"))
    with pytest.raises(IndexError):
        p.insert_plugin(-1, _FmtPlugin("x"))


def test_insert_different_format_creates_boundary_adapters():
    a = _FmtPlugin("a", rate=48000)
    p = _compiled(a)
    hi = _FmtPlugin("hi", rate=16000)

    p.insert_plugin(0, hi)

    adapter_in, first = p._stages[0]
    assert first is hi
    assert adapter_in is not None
    adapter_mid, second = p._stages[1]
    assert second is a
    assert adapter_mid is not None


def test_remove_middle_keeps_rest_of_chain():
    a, b, c = _FmtPlugin("a"), _FmtPlugin("b"), _FmtPlugin("c")
    p = _compiled(a, b, c)

    p.remove_plugin(1)

    assert [pl.name for pl in p._plugins] == ["a", "c"]
    assert b.torn_down is True


def test_remove_shortens_chain():
    a, b = _FmtPlugin("a"), _FmtPlugin("b")
    p = _compiled(a, b)

    p.remove_plugin(1)

    assert len(p._plugins) == 1
    assert len(p.stage_metrics()) == 1


def test_remove_last_plugin_leaves_passthrough():
    a = _FmtPlugin("a")
    p = _compiled(a)

    p.remove_plugin(0)

    assert p._plugins == []
    audio = np.ones((480, 1), dtype=np.float32)
    np.testing.assert_array_equal(p.process(audio), audio)


def test_remove_does_not_resetup_untouched_neighbors():
    a, b, c = _FmtPlugin("a"), _FmtPlugin("b"), _FmtPlugin("c")
    p = _compiled(a, b, c)
    a.setup_calls = 0
    c.setup_calls = 0

    p.remove_plugin(1)

    assert a.setup_calls == 0
    assert c.setup_calls == 0


def test_remove_bad_index_raises():
    p = _compiled(_FmtPlugin("a"))
    with pytest.raises(IndexError):
        p.remove_plugin(5)
    with pytest.raises(IndexError):
        p.remove_plugin(-1)


def test_remove_preserves_processing_contract():
    a, b = _FmtPlugin("a"), _FmtPlugin("b")
    p = _compiled(a, b)

    p.remove_plugin(0)

    audio = np.ones((480, 1), dtype=np.float32)
    out = p.process(audio)
    assert out.shape == (480, 1)


def test_remove_different_format_neighbor_rebuilds_boundary_adapter():
    a = _FmtPlugin("a", rate=48000)
    hi = _FmtPlugin("hi", rate=16000)
    c = _FmtPlugin("c", rate=48000)
    p = _compiled(a, hi, c)

    p.remove_plugin(1)  # saca el de 16k que quedaba entre dos de 48k

    assert [pl.name for pl in p._plugins] == ["a", "c"]
    adapter, plugin = p._stages[1]
    assert plugin is c
    assert adapter is None  # mismo formato ahora: no hace falta adapter


def test_preview_latency_matches_actual_after_insert():
    a = _FmtPlugin("a", latency_ms=5.0)
    p = _compiled(a)
    b = _FmtPlugin("b", latency_ms=7.0)

    predicted = p.preview_total_latency_ms([a, b])
    p.insert_plugin(1, b)

    assert predicted == pytest.approx(p.total_latency_ms())


def test_preview_latency_matches_actual_after_remove():
    a = _FmtPlugin("a", latency_ms=5.0)
    b = _FmtPlugin("b", latency_ms=7.0)
    p = _compiled(a, b)

    predicted = p.preview_total_latency_ms([a])
    p.remove_plugin(1)

    assert predicted == pytest.approx(p.total_latency_ms())


def test_preview_latency_accounts_for_adapter_buffering():
    a = _FmtPlugin("a", rate=48000)
    p = _compiled(a)
    hi = _FmtPlugin("hi", rate=16000)

    predicted = p.preview_total_latency_ms([a, hi])
    p.insert_plugin(1, hi)

    assert predicted == pytest.approx(p.total_latency_ms())
    assert predicted > 0.0  # el resampleo agrega buffering latency


def test_worker_applies_staged_insert_between_chunks():
    a = _FmtPlugin("a")
    p = _compiled(a)
    b = _FmtPlugin("b")
    t = CaptureThread(input_device_id=0, output_device_id=0, fmt=_fmt(),
                      pipeline=p, out_channels=1)

    t.request_plugin_insert(1, b)
    t._drain_swaps()

    assert [pl.name for pl in p._plugins] == ["a", "b"]


def test_worker_applies_staged_remove_between_chunks():
    a, b = _FmtPlugin("a"), _FmtPlugin("b")
    p = _compiled(a, b)
    t = CaptureThread(input_device_id=0, output_device_id=0, fmt=_fmt(),
                      pipeline=p, out_channels=1)

    t.request_plugin_remove(0)
    t._drain_swaps()

    assert [pl.name for pl in p._plugins] == ["b"]
    assert a.torn_down is True


def test_worker_applies_staged_operations_in_order():
    a = _FmtPlugin("a")
    p = _compiled(a)
    b = _FmtPlugin("b")
    c = _FmtPlugin("c")
    t = CaptureThread(input_device_id=0, output_device_id=0, fmt=_fmt(),
                      pipeline=p, out_channels=1)

    t.request_plugin_insert(1, b)   # [a, b]
    t.request_plugin_insert(0, c)   # [c, a, b]
    t.request_plugin_remove(1)      # [c, b]
    t._drain_swaps()

    assert [pl.name for pl in p._plugins] == ["c", "b"]
