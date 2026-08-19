import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.base import AudioPlugin, Parameter

_DEFAULT_CEILING_DB = -1.0
_DEFAULT_RELEASE_MS = 50.0

_FLOOR_DB = -120.0
_LOG_EPSILON = 1e-12


def _peak_db(audio: np.ndarray) -> float:
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    return float(20.0 * np.log10(peak + _LOG_EPSILON))


class LimiterPlugin(AudioPlugin):
    name = "Limitador"
    version = "1.0.0"

    def __init__(self) -> None:
        self._sample_rate = 48000
        self._ceiling_db = _DEFAULT_CEILING_DB
        self._release_ms = _DEFAULT_RELEASE_MS
        # estado persistente entre chunks: envolvente de pico (dB) que
        # gobierna la reducción de ganancia; arranca en silencio total
        self._envelope_db = _FLOOR_DB
        self._build_coefficients()

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(48000, 1, 960)

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        self._sample_rate = fmt.sample_rate
        self._envelope_db = _FLOOR_DB
        self._build_coefficients()
        return fmt

    def process(self, audio: np.ndarray) -> np.ndarray:
        audio = audio.astype(np.float32)
        n_samples = audio.shape[0]
        env_db = self._advance_envelope(audio, n_samples)
        gain_db = np.minimum(0.0, self._ceiling_db - env_db)
        gain_lin = (10.0 ** (gain_db / 20.0)).astype(np.float32)
        out = audio * gain_lin.reshape(-1, 1)
        # red de seguridad (belt-and-suspenders): garantiza el contrato de
        # techo pase lo que pase con la aproximación de la envolvente —
        # ver task-4-brief.md. La ganancia suave ya deja out <= ceiling_lin
        # por construcción (envelope_db[n] >= pico real del bloque en todo
        # momento), esto solo cubre error de punto flotante en el borde.
        return np.clip(out, -self._ceiling_lin, self._ceiling_lin)

    def _advance_envelope(self, audio: np.ndarray, n_samples: int) -> np.ndarray:
        old_env_db = self._envelope_db
        peak_db = _peak_db(audio)
        if peak_db > old_env_db:
            # ataque instantáneo: la envolvente salta directo al pico del
            # bloque completo, sin retardo — así ningún sample del bloque
            # (esté donde esté el pico) queda sub-atenuado.
            new_env_db = peak_db
            self._envelope_db = new_env_db
            return np.full(n_samples, new_env_db, dtype=np.float32)
        new_env_db = peak_db + (old_env_db - peak_db) * (self._release_coef ** n_samples)
        self._envelope_db = new_env_db
        return np.linspace(old_env_db, new_env_db, num=n_samples, endpoint=False, dtype=np.float32)

    def teardown(self) -> None:
        pass

    @property
    def algorithmic_latency_ms(self) -> float:
        return 0.0

    @property
    def parameters(self) -> list[Parameter]:
        return [
            Parameter(id="ceiling_db", label="Techo (dB)", type="float",
                      default=_DEFAULT_CEILING_DB, min=-24.0, max=0.0),
            Parameter(id="release_ms", label="Release (ms)", type="float",
                      default=_DEFAULT_RELEASE_MS, min=10.0, max=500.0),
        ]

    def set_parameter(self, id: str, value) -> None:
        if id == "ceiling_db":
            self._ceiling_db = float(value)
        elif id == "release_ms":
            self._release_ms = float(value)
        else:
            return
        self._build_coefficients()

    def _build_coefficients(self) -> None:
        fs = self._sample_rate
        self._release_coef = float(np.exp(-1.0 / (self._release_ms * 1e-3 * fs)))
        self._ceiling_lin = float(10.0 ** (self._ceiling_db / 20.0))
