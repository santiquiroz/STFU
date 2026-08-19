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
