import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.base import AudioPlugin, Parameter


class GainPlugin(AudioPlugin):
    name = "Gain"
    version = "1.0.0"

    def __init__(self) -> None:
        self._linear: float = 1.0

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(48000, 1, 960)

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        return fmt

    def process(self, audio: np.ndarray) -> np.ndarray:
        return audio * self._linear

    def teardown(self) -> None:
        pass

    @property
    def algorithmic_latency_ms(self) -> float:
        return 0.0

    @property
    def parameters(self) -> list[Parameter]:
        return [Parameter(id="gain_db", label="Ganancia (dB)", type="float",
                          default=0.0, min=-24.0, max=24.0)]

    def set_parameter(self, id: str, value) -> None:
        if id == "gain_db":
            self._linear = 10 ** (float(value) / 20.0)
