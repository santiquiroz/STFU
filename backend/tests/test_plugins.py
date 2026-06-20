import numpy as np
import pytest
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

    def set_parameter(self, id: str, value) -> None:
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
