import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.base import AudioPlugin, Parameter

_DEFAULT_THRESHOLD_DB = -45.0
_DEFAULT_ATTACK_MS = 5.0
_DEFAULT_RELEASE_MS = 150.0
_DEFAULT_HOLD_MS = 50.0


class NoiseGatePlugin(AudioPlugin):
    name = "Noise Gate"
    version = "1.0.0"

    def __init__(self) -> None:
        self._sample_rate = 48000
        self._threshold_db = _DEFAULT_THRESHOLD_DB
        self._attack_ms = _DEFAULT_ATTACK_MS
        self._release_ms = _DEFAULT_RELEASE_MS
        self._hold_ms = _DEFAULT_HOLD_MS
        # estado persistente entre chunks: ganancia actual del gate y
        # cuántas muestras quedan de hold antes de empezar a liberar
        self._gain = 0.0
        self._hold_counter = 0
        self._build_coefficients()

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(48000, 1, 960)

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        self._sample_rate = fmt.sample_rate
        self._gain = 0.0
        self._hold_counter = 0
        self._build_coefficients()
        return fmt

    def process(self, audio: np.ndarray) -> np.ndarray:
        n_samples = audio.shape[0]
        old_gain = self._gain
        target_gain, coef = self._decide_target(audio, n_samples, old_gain)
        # forma cerrada del smoothing exponencial de un polo tras n_samples
        # muestras: evita un loop Python por-sample manteniendo la misma
        # constante de tiempo per-sample que attack_coef/release_coef.
        new_gain = target_gain + (old_gain - target_gain) * (coef ** n_samples)
        ramp = np.linspace(old_gain, new_gain, num=n_samples, endpoint=False, dtype=np.float32)
        out = audio.astype(np.float32) * ramp.reshape(-1, 1)
        self._gain = new_gain
        return out

    def _decide_target(self, audio: np.ndarray, n_samples: int, old_gain: float) -> tuple[float, float]:
        peak = float(np.max(np.abs(audio))) if n_samples else 0.0
        if peak >= self._threshold_linear:
            self._hold_counter = self._hold_samples
            return 1.0, self._attack_coef
        if self._hold_counter > 0:
            self._hold_counter = max(0, self._hold_counter - n_samples)
            return old_gain, 1.0
        return 0.0, self._release_coef

    def teardown(self) -> None:
        pass

    @property
    def algorithmic_latency_ms(self) -> float:
        return 0.0

    @property
    def parameters(self) -> list[Parameter]:
        return [
            Parameter(id="threshold_db", label="Umbral (dB)", type="float",
                      default=_DEFAULT_THRESHOLD_DB, min=-80.0, max=0.0),
            Parameter(id="attack_ms", label="Ataque (ms)", type="float",
                      default=_DEFAULT_ATTACK_MS, min=1.0, max=100.0),
            Parameter(id="release_ms", label="Release (ms)", type="float",
                      default=_DEFAULT_RELEASE_MS, min=10.0, max=1000.0),
            Parameter(id="hold_ms", label="Hold (ms)", type="float",
                      default=_DEFAULT_HOLD_MS, min=0.0, max=500.0),
        ]

    def set_parameter(self, id: str, value) -> None:
        if id == "threshold_db":
            self._threshold_db = float(value)
        elif id == "attack_ms":
            self._attack_ms = float(value)
        elif id == "release_ms":
            self._release_ms = float(value)
        elif id == "hold_ms":
            self._hold_ms = float(value)
        else:
            return
        self._build_coefficients()

    def _build_coefficients(self) -> None:
        fs = self._sample_rate
        self._threshold_linear = 10.0 ** (self._threshold_db / 20.0)
        self._attack_coef = float(np.exp(-1.0 / (self._attack_ms * 1e-3 * fs)))
        self._release_coef = float(np.exp(-1.0 / (self._release_ms * 1e-3 * fs)))
        self._hold_samples = int(self._hold_ms * 1e-3 * fs)
