import numpy as np
import pytest
from typing import Any
from stfu.core.audio_format import AudioFormat
from stfu.plugins.base import AudioPlugin, Parameter

class _PassthroughPlugin(AudioPlugin):
    name = "Passthrough"
    version = "1.0.0"

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(48000, 1, 960)

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        return fmt

    def process(self, audio: np.ndarray) -> np.ndarray:
        return audio

    def teardown(self) -> None:
        pass

    @property
    def algorithmic_latency_ms(self) -> float:
        return 0.0

    @property
    def parameters(self) -> list[Parameter]:
        return [Parameter(id="vol", label="Volume", type="float", default=1.0)]

    def set_parameter(self, id: str, value: Any) -> None:
        pass

def test_plugin_name_and_version():
    p = _PassthroughPlugin()
    assert p.name == "Passthrough"
    assert p.version == "1.0.0"

def test_setup_returns_format():
    p = _PassthroughPlugin()
    fmt = AudioFormat(48000, 1, 960)
    assert p.setup(fmt) == fmt

def test_process_returns_same_shape():
    p = _PassthroughPlugin()
    fmt = AudioFormat(48000, 1, 960)
    p.setup(fmt)
    audio = np.zeros((960, 1), dtype=np.float32)
    result = p.process(audio)
    assert result.shape == (960, 1)
    assert result.dtype == np.float32

def test_parameter_defaults():
    param = Parameter(id="x", label="X", type="float", default=0.5)
    assert param.min is None
    assert param.max is None
    assert param.options is None

def test_plugin_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        AudioPlugin()


from stfu.plugins.builtin.deepfilternet3 import DeepFilterNet3Plugin


def test_dfn3_preferred_format():
    p = DeepFilterNet3Plugin()
    assert p.preferred_format == AudioFormat(48000, 1, 960)


def test_dfn3_setup_process_teardown():
    p = DeepFilterNet3Plugin()
    fmt = p.preferred_format
    out_fmt = p.setup(fmt)
    assert out_fmt == fmt
    audio = np.zeros((960, 1), dtype=np.float32)
    result = p.process(audio)
    assert result.shape == (960, 1)
    assert result.dtype == np.float32
    p.teardown()


def test_dfn3_strength_parameter():
    p = DeepFilterNet3Plugin()
    params = {x.id: x for x in p.parameters}
    assert "strength" in params
    assert params["strength"].type == "float"
    assert params["strength"].default == pytest.approx(0.85)
    assert params["strength"].min == 0.0
    assert params["strength"].max == 1.0


def test_dfn3_latency():
    assert DeepFilterNet3Plugin().algorithmic_latency_ms == pytest.approx(40.0)


from stfu.plugins.builtin.gain import GainPlugin
from stfu.plugins.builtin.eq_parametric import EQParametricPlugin


def test_gain_zero_db_is_passthrough():
    p = GainPlugin()
    p.setup(AudioFormat(48000, 1, 960))
    audio = np.random.randn(960, 1).astype(np.float32)
    np.testing.assert_array_almost_equal(p.process(audio), audio)


def test_gain_plus_6db():
    p = GainPlugin()
    p.setup(AudioFormat(48000, 1, 960))
    p.set_parameter("gain_db", 6.0)
    audio = np.ones((960, 1), dtype=np.float32)
    expected = 10 ** (6.0 / 20.0)
    np.testing.assert_array_almost_equal(p.process(audio), np.full_like(audio, expected), decimal=4)


def test_gain_accepts_any_format():
    p = GainPlugin()
    fmt = AudioFormat(44100, 2, 1024)
    assert p.setup(fmt) == fmt


def test_eq_has_five_bands():
    p = EQParametricPlugin()
    ids = {x.id for x in p.parameters}
    for i in range(1, 6):
        assert f"band_{i}_gain_db" in ids
        assert f"band_{i}_freq" in ids
        assert f"band_{i}_q" in ids


def test_eq_zero_gain_passthrough():
    p = EQParametricPlugin()
    fmt = AudioFormat(48000, 1, 960)
    p.setup(fmt)
    audio = np.random.randn(960, 1).astype(np.float32)
    np.testing.assert_array_almost_equal(p.process(audio), audio, decimal=5)
