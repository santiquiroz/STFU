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
