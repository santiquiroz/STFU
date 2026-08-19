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
