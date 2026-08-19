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
