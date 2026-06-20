import numpy as np
from scipy.signal import iirpeak, sosfilt
from stfu.core.audio_format import AudioFormat
from stfu.plugins.base import AudioPlugin, Parameter

_DEFAULTS = [
    {"freq": 80.0,    "gain_db": 0.0, "q": 1.0},
    {"freq": 250.0,   "gain_db": 0.0, "q": 1.0},
    {"freq": 1000.0,  "gain_db": 0.0, "q": 1.0},
    {"freq": 4000.0,  "gain_db": 0.0, "q": 1.0},
    {"freq": 12000.0, "gain_db": 0.0, "q": 1.0},
]


class EQParametricPlugin(AudioPlugin):
    name = "EQ Paramétrico"
    version = "1.0.0"

    def __init__(self) -> None:
        self._bands = [dict(b) for b in _DEFAULTS]
        self._sample_rate = 48000
        self._channels = 1
        self._sos: list = []

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(48000, 1, 960)

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        self._sample_rate = fmt.sample_rate
        self._channels = fmt.channels
        self._build_filters()
        return fmt

    def process(self, audio: np.ndarray) -> np.ndarray:
        out = audio.copy()
        for sos in self._sos:
            for ch in range(out.shape[1]):
                out[:, ch] = sosfilt(sos, out[:, ch])
        return out

    def teardown(self) -> None:
        self._sos.clear()

    @property
    def algorithmic_latency_ms(self) -> float:
        return 0.0

    @property
    def parameters(self) -> list[Parameter]:
        params = []
        for i, b in enumerate(self._bands, 1):
            params += [
                Parameter(f"band_{i}_freq",    f"Banda {i} Freq (Hz)", "float", b["freq"],    min=20.0,  max=20000.0),
                Parameter(f"band_{i}_gain_db", f"Banda {i} Gain (dB)", "float", b["gain_db"], min=-18.0, max=18.0),
                Parameter(f"band_{i}_q",       f"Banda {i} Q",         "float", b["q"],       min=0.1,   max=10.0),
            ]
        return params

    def set_parameter(self, id: str, value) -> None:
        for i, b in enumerate(self._bands, 1):
            if id == f"band_{i}_freq":
                b["freq"] = float(value)
            elif id == f"band_{i}_gain_db":
                b["gain_db"] = float(value)
            elif id == f"band_{i}_q":
                b["q"] = float(value)
        self._build_filters()

    def _build_filters(self) -> None:
        self._sos = []
        nyq = self._sample_rate / 2.0
        for b in self._bands:
            if b["gain_db"] == 0.0:
                continue
            w0 = b["freq"] / nyq
            if w0 >= 1.0:
                continue
            bcoef, acoef = iirpeak(w0, b["q"])
            g = 10 ** (b["gain_db"] / 20.0)
            self._sos.append(np.array([[bcoef[0] * g, bcoef[1] * g, bcoef[2] * g, 1.0, acoef[1], acoef[2]]]))
