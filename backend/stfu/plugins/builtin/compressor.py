import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.base import AudioPlugin, Parameter

_DEFAULT_THRESHOLD_DB = -24.0
_DEFAULT_RATIO = 3.0
_DEFAULT_ATTACK_MS = 10.0
_DEFAULT_RELEASE_MS = 120.0
_DEFAULT_MAKEUP_DB = 0.0
_DEFAULT_AGC = False
_DEFAULT_AGC_TARGET_DB = -18.0

_FLOOR_DB = -120.0
_LOG_EPSILON = 1e-12
_AGC_STEP_FACTOR = 0.3
_AGC_MAX_STEP_DB = 2.0
_AGC_MAX_GAIN_DB = 30.0


def _rms_db(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(audio))))
    return float(20.0 * np.log10(rms + _LOG_EPSILON))


class CompressorPlugin(AudioPlugin):
    name = "Compresor"
    version = "1.0.0"

    def __init__(self) -> None:
        self._sample_rate = 48000
        self._threshold_db = _DEFAULT_THRESHOLD_DB
        self._ratio = _DEFAULT_RATIO
        self._attack_ms = _DEFAULT_ATTACK_MS
        self._release_ms = _DEFAULT_RELEASE_MS
        self._makeup_db = _DEFAULT_MAKEUP_DB
        self._agc = _DEFAULT_AGC
        self._agc_target_db = _DEFAULT_AGC_TARGET_DB
        # estado persistente entre chunks: envolvente de nivel (dB), y
        # ganancia lenta de AGC (dB) — se guarda el valor previo además del
        # actual para poder rampearla igual que la envolvente de compresión
        # y evitar saltos de ganancia (zipper noise) en el borde de chunk
        self._envelope_db = _FLOOR_DB
        self._agc_gain_db = 0.0
        self._prev_agc_gain_db = 0.0
        self._build_coefficients()

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(48000, 1, 960)

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        self._sample_rate = fmt.sample_rate
        self._envelope_db = _FLOOR_DB
        self._agc_gain_db = 0.0
        self._prev_agc_gain_db = 0.0
        self._build_coefficients()
        return fmt

    def process(self, audio: np.ndarray) -> np.ndarray:
        audio = audio.astype(np.float32)
        n_samples = audio.shape[0]
        env_ramp_db = self._advance_envelope(audio, n_samples)
        gain_db = self._compression_gain_db(env_ramp_db) + self._makeup_db
        if self._agc:
            gain_db = gain_db + self._agc_gain_ramp(n_samples)
        gain_lin = (10.0 ** (gain_db / 20.0)).astype(np.float32)
        out = audio * gain_lin.reshape(-1, 1)
        if self._agc:
            self._update_agc_gain(out)
        return out

    def _agc_gain_ramp(self, n_samples: int) -> np.ndarray:
        # rampea desde la ganancia AGC vigente al final del chunk anterior
        # hasta el objetivo ya decidido, en vez de aplicarlo como escalón
        return np.linspace(self._prev_agc_gain_db, self._agc_gain_db, num=n_samples, dtype=np.float32)

    def _advance_envelope(self, audio: np.ndarray, n_samples: int) -> np.ndarray:
        old_env_db = self._envelope_db
        level_db = _rms_db(audio)
        coef = self._attack_coef if level_db > old_env_db else self._release_coef
        # forma cerrada del smoothing exponencial de un polo tras n_samples,
        # mismo patrón que NoiseGatePlugin._decide_target/process
        new_env_db = level_db + (old_env_db - level_db) * (coef ** n_samples)
        self._envelope_db = new_env_db
        return np.linspace(old_env_db, new_env_db, num=n_samples, endpoint=False, dtype=np.float32)

    def _compression_gain_db(self, level_db: np.ndarray) -> np.ndarray:
        over_threshold_db = np.maximum(level_db - self._threshold_db, 0.0)
        return over_threshold_db * (1.0 / self._ratio - 1.0)

    def _update_agc_gain(self, out: np.ndarray) -> None:
        error_db = self._agc_target_db - _rms_db(out)
        step_db = np.clip(error_db * _AGC_STEP_FACTOR, -_AGC_MAX_STEP_DB, _AGC_MAX_STEP_DB)
        self._prev_agc_gain_db = self._agc_gain_db
        self._agc_gain_db = float(np.clip(self._agc_gain_db + step_db, -_AGC_MAX_GAIN_DB, _AGC_MAX_GAIN_DB))

    def teardown(self) -> None:
        pass

    @property
    def algorithmic_latency_ms(self) -> float:
        return 0.0

    @property
    def parameters(self) -> list[Parameter]:
        return [
            Parameter(id="threshold_db", label="Umbral (dB)", type="float",
                      default=_DEFAULT_THRESHOLD_DB, min=-60.0, max=0.0),
            Parameter(id="ratio", label="Ratio", type="float",
                      default=_DEFAULT_RATIO, min=1.0, max=20.0),
            Parameter(id="attack_ms", label="Ataque (ms)", type="float",
                      default=_DEFAULT_ATTACK_MS, min=1.0, max=100.0),
            Parameter(id="release_ms", label="Release (ms)", type="float",
                      default=_DEFAULT_RELEASE_MS, min=10.0, max=1000.0),
            Parameter(id="makeup_db", label="Makeup (dB)", type="float",
                      default=_DEFAULT_MAKEUP_DB, min=0.0, max=24.0),
            Parameter(id="agc", label="AGC (auto-leveling)", type="bool",
                      default=_DEFAULT_AGC),
            Parameter(id="agc_target_db", label="Objetivo AGC (dB)", type="float",
                      default=_DEFAULT_AGC_TARGET_DB, min=-40.0, max=0.0),
        ]

    def set_parameter(self, id: str, value) -> None:
        if id == "threshold_db":
            self._threshold_db = float(value)
        elif id == "ratio":
            self._ratio = float(value)
        elif id == "attack_ms":
            self._attack_ms = float(value)
        elif id == "release_ms":
            self._release_ms = float(value)
        elif id == "makeup_db":
            self._makeup_db = float(value)
        elif id == "agc":
            self._agc = bool(value)
        elif id == "agc_target_db":
            self._agc_target_db = float(value)
        else:
            return
        self._build_coefficients()

    def _build_coefficients(self) -> None:
        fs = self._sample_rate
        self._attack_coef = float(np.exp(-1.0 / (self._attack_ms * 1e-3 * fs)))
        self._release_coef = float(np.exp(-1.0 / (self._release_ms * 1e-3 * fs)))
