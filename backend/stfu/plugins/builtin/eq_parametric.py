import numpy as np
from scipy.signal import sosfilt
from stfu.core.audio_format import AudioFormat
from stfu.plugins.base import AudioPlugin, Parameter

_DEFAULTS = [
    {"freq": 80.0,    "gain_db": 0.0, "q": 1.0},
    {"freq": 250.0,   "gain_db": 0.0, "q": 1.0},
    {"freq": 1000.0,  "gain_db": 0.0, "q": 1.0},
    {"freq": 4000.0,  "gain_db": 0.0, "q": 1.0},
    {"freq": 12000.0, "gain_db": 0.0, "q": 1.0},
]


def _peaking_sos(freq: float, gain_db: float, q: float, fs: float) -> np.ndarray:
    """Biquad peaking-EQ (RBJ Audio EQ Cookbook): boost/cut en la banda,
    unidad de ganancia fuera de ella."""
    a_lin = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * freq / fs
    alpha = np.sin(w0) / (2.0 * q)
    cos_w0 = np.cos(w0)
    b0 = 1.0 + alpha * a_lin
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * a_lin
    a0 = 1.0 + alpha / a_lin
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / a_lin
    return np.array([b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0])


class EQParametricPlugin(AudioPlugin):
    name = "EQ Paramétrico"
    version = "2.0.0"

    def __init__(self) -> None:
        self._bands = [dict(b) for b in _DEFAULTS]
        self._sample_rate = 48000
        self._channels = 1
        # (sos, zi) en una sola referencia: swap atómico bajo el GIL cuando
        # la UI cambia parámetros mientras el worker procesa
        self._filters: tuple[np.ndarray, np.ndarray] | None = None

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(48000, 1, 960)

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        self._sample_rate = fmt.sample_rate
        self._channels = fmt.channels
        self._build_filters()
        return fmt

    def process(self, audio: np.ndarray) -> np.ndarray:
        filters = self._filters
        if filters is None:
            return audio
        sos, zi = filters
        out, zi_new = sosfilt(sos, audio, axis=0, zi=zi)
        if self._filters is filters:
            self._filters = (sos, zi_new)
        return out.astype(np.float32)

    def teardown(self) -> None:
        self._filters = None

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
        nyq = self._sample_rate / 2.0
        sections = [
            _peaking_sos(b["freq"], b["gain_db"], b["q"], self._sample_rate)
            for b in self._bands
            if b["gain_db"] != 0.0 and b["freq"] < nyq
        ]
        if not sections:
            self._filters = None
            return
        sos = np.stack(sections)
        # estado se resetea al cambiar parámetros: transitorio breve aceptable
        self._filters = (sos, np.zeros((sos.shape[0], 2, self._channels)))
