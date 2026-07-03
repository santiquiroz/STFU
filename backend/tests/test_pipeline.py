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

def test_pipeline_returns_stream_format_shape_when_adapter_buffers():
    # Input: 480 stereo samples. Plugin wants: 960 mono samples.
    # Mientras el adapter acumula, el pipeline emite silencio EN EL FORMATO
    # DEL STREAM (contrato con capture.py), no en el formato del plugin.
    fmt_in = AudioFormat(48000, 2, 480)
    fmt_out = AudioFormat(48000, 1, 960)

    gain = _GainPlugin()
    pipeline = Pipeline()
    pipeline.add_plugin(gain)

    with patch.object(type(gain), "preferred_format", new_callable=PropertyMock, return_value=fmt_out):
        pipeline.compile(fmt_in)
        audio = np.zeros((480, 2), dtype=np.float32)
        result = pipeline.process(audio)

    assert result.shape == (480, 2), f"Expected (480, 2), got {result.shape}"
    assert result.dtype == np.float32


def test_pipeline_no_data_loss_when_adapter_splits_chunks():
    # Plugin quiere chunks de 480; el stream entrega 960 → el adapter emite
    # 2 chunks por llamada. El código viejo botaba el segundo (chunks[0]).
    fmt_in = AudioFormat(48000, 1, 960)
    fmt_plugin = AudioFormat(48000, 1, 480)

    gain = _GainPlugin(gain=2.0)
    pipeline = Pipeline()
    pipeline.add_plugin(gain)

    with patch.object(type(gain), "preferred_format", new_callable=PropertyMock, return_value=fmt_plugin):
        pipeline.compile(fmt_in)
        audio = np.ones((960, 1), dtype=np.float32)
        result = pipeline.process(audio)

    assert result.shape == (960, 1)
    np.testing.assert_array_almost_equal(result, audio * 2.0)


def test_set_parameter_applies_live():
    class _ParamGain(_GainPlugin):
        def set_parameter(self, id, value):
            if id == "gain":
                self._gain = float(value)

    p = Pipeline()
    p.add_plugin(_ParamGain(gain=1.0))
    p.compile(AudioFormat(48000, 1, 960))
    audio = np.ones((960, 1), dtype=np.float32)
    np.testing.assert_array_almost_equal(p.process(audio), audio)
    p.set_parameter(0, "gain", 4.0)
    np.testing.assert_array_almost_equal(p.process(audio), audio * 4.0)


def test_set_parameter_out_of_range_raises():
    p = Pipeline()
    with pytest.raises(IndexError):
        p.set_parameter(0, "x", 1.0)


def test_pipeline_output_adapted_back_to_stream_format():
    # Plugin de 16k: la salida debe volver al formato del stream (48k/960)
    # y, pasado el priming del resampler, transportar señal real.
    pipeline = Pipeline()
    pipeline.add_plugin(_Format16kPlugin())
    fmt = AudioFormat(48000, 1, 960)
    pipeline.compile(fmt)

    fs, freq = 48000, 440.0
    outputs = []
    for i in range(30):
        t = (np.arange(960) + i * 960) / fs
        chunk = np.sin(2 * np.pi * freq * t).astype(np.float32).reshape(-1, 1)
        out = pipeline.process(chunk)
        assert out.shape == (960, 1)
        assert out.dtype == np.float32
        outputs.append(out)

    tail_energy = float(np.sqrt(np.mean(np.concatenate(outputs[10:]) ** 2)))
    assert tail_energy > 0.1  # señal presente, no ceros perpetuos
