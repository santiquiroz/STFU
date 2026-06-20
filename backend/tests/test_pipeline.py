import numpy as np
import pytest
from unittest.mock import patch, PropertyMock
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.plugins.base import AudioPlugin, Parameter

class _GainPlugin(AudioPlugin):
    name = "Gain"
    version = "1.0.0"
    def __init__(self, gain=2.0, latency_ms=0.0):
        self._gain = gain
        self._lat = latency_ms
    @property
    def preferred_format(self): return AudioFormat(48000, 1, 960)
    def setup(self, fmt): return fmt
    def process(self, audio): return audio * self._gain
    def teardown(self): pass
    @property
    def algorithmic_latency_ms(self): return self._lat
    @property
    def parameters(self): return []

class _Format16kPlugin(AudioPlugin):
    name = "16k"
    version = "1.0.0"
    @property
    def preferred_format(self): return AudioFormat(16000, 1, 320)
    def setup(self, fmt): return fmt
    def process(self, audio): return audio
    def teardown(self): pass
    @property
    def algorithmic_latency_ms(self): return 5.0
    @property
    def parameters(self): return []

def test_empty_pipeline_is_passthrough():
    p = Pipeline()
    p.compile(AudioFormat(48000, 1, 960))
    audio = np.ones((960, 1), dtype=np.float32)
    np.testing.assert_array_equal(p.process(audio), audio)

def test_single_plugin_applies_effect():
    p = Pipeline()
    p.add_plugin(_GainPlugin(gain=3.0))
    p.compile(AudioFormat(48000, 1, 960))
    audio = np.ones((960, 1), dtype=np.float32)
    np.testing.assert_array_almost_equal(p.process(audio), audio * 3.0)

def test_adapter_inserted_for_format_mismatch():
    p = Pipeline()
    p.add_plugin(_Format16kPlugin())
    p.compile(AudioFormat(48000, 1, 960))
    audio = np.ones((960, 1), dtype=np.float32)
    result = p.process(audio)
    assert result is not None
    assert result.dtype == np.float32  # format preserved through pipeline

def test_total_latency_sums_all():
    p = Pipeline()
    p.add_plugin(_GainPlugin(latency_ms=40.0))
    p.add_plugin(_GainPlugin(latency_ms=10.0))
    p.compile(AudioFormat(48000, 1, 960))
    assert p.total_latency_ms() == pytest.approx(50.0)

def test_clear_resets_to_passthrough():
    p = Pipeline()
    p.add_plugin(_GainPlugin(gain=5.0))
    p.compile(AudioFormat(48000, 1, 960))
    p.clear()
    audio = np.ones((960, 1), dtype=np.float32)
    np.testing.assert_array_equal(p.process(audio), audio)

def test_pipeline_returns_correct_shape_when_adapter_buffers():
    # Input: 480 stereo samples. Plugin wants: 960 mono samples.
    # After one 480-sample block, adapter has 480 samples < 960 → yields nothing.
    fmt_in = AudioFormat(48000, 2, 480)
    fmt_out = AudioFormat(48000, 1, 960)

    gain = _GainPlugin()
    pipeline = Pipeline()
    pipeline.add_plugin(gain)

    with patch.object(type(gain), "preferred_format", new_callable=PropertyMock, return_value=fmt_out):
        pipeline.compile(fmt_in)
        audio = np.zeros((480, 2), dtype=np.float32)
        result = pipeline.process(audio)

    assert result.shape == (960, 1), f"Expected (960, 1), got {result.shape}"
    assert result.dtype == np.float32
