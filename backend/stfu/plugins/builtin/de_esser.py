import numpy as np
from scipy.signal import butter, sosfilt
from stfu.core.audio_format import AudioFormat
from stfu.plugins.base import AudioPlugin, Parameter

_DEFAULT_FREQ_HZ = 6000.0
_DEFAULT_THRESHOLD_DB = -30.0
_DEFAULT_REDUCTION_DB = 8.0

_CROSSOVER_ORDER = 2
_FLOOR_DB = -120.0
_LOG_EPSILON = 1e-12
_ATTACK_MS = 3.0
_RELEASE_MS = 80.0


def _linkwitz_riley_sos(freq: float, fs: float, btype: str) -> np.ndarray:
    """Crossover Linkwitz-Riley de orden 4 (cascada de dos Butterworth de
    orden 2 idénticos). A diferencia de un Butterworth simple, low+high
    reconstruye magnitud plana (ganancia 1 exacta) en toda la banda cuando
    ambas se suman sin atenuar, así que reducir solo la banda alta atenúa
    de verdad la energía total en vez de generar overshoot de fase cerca
    del corte."""
    section = butter(_CROSSOVER_ORDER, freq, btype=btype, fs=fs, output="sos")
    return np.vstack([section, section])


def _rms_db(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(audio))))
    return float(20.0 * np.log10(rms + _LOG_EPSILON))


class DeEsserPlugin(AudioPlugin):
    name = "De-esser"
    version = "1.0.0"

    def __init__(self) -> None:
        self._sample_rate = 48000
        self._channels = 1
        self._freq_hz = _DEFAULT_FREQ_HZ
        self._threshold_db = _DEFAULT_THRESHOLD_DB
        self._reduction_db = _DEFAULT_REDUCTION_DB
        # (sos, zi) de cada rama del crossover en una sola referencia por
        # rama: swap atómico bajo el GIL, mismo patrón que
        # EQParametricPlugin. La envolvente de nivel (dB) de la banda alta
        # persiste entre chunks para decidir cuándo reducir.
        self._hp_filter: tuple[np.ndarray, np.ndarray] | None = None
        self._lp_filter: tuple[np.ndarray, np.ndarray] | None = None
        self._envelope_db = _FLOOR_DB
        self._build_filter()
        self._build_coefficients()

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(48000, 1, 960)

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        self._sample_rate = fmt.sample_rate
        self._channels = fmt.channels
        self._envelope_db = _FLOOR_DB
        self._build_filter()
        self._build_coefficients()
        return fmt

    def process(self, audio: np.ndarray) -> np.ndarray:
        audio = audio.astype(np.float32)
        if self._hp_filter is None or self._lp_filter is None:
            return audio.copy()
        high_band = self._filter_band("_hp_filter", audio)
        low_band = self._filter_band("_lp_filter", audio)
        gain = self._sibilance_gain(high_band, audio.shape[0])
        return (low_band + gain.reshape(-1, 1) * high_band).astype(np.float32)

    def _filter_band(self, attr: str, audio: np.ndarray) -> np.ndarray:
        filt = getattr(self, attr)
        sos, zi = filt
        band, zi_new = sosfilt(sos, audio, axis=0, zi=zi)
        if getattr(self, attr) is filt:
            setattr(self, attr, (sos, zi_new))
        return band.astype(np.float32)

    def _sibilance_gain(self, high_band: np.ndarray, n_samples: int) -> np.ndarray:
        old_env_db = self._envelope_db
        level_db = _rms_db(high_band)
        coef = self._attack_coef if level_db > old_env_db else self._release_coef
        # forma cerrada del smoothing exponencial de un polo tras n_samples,
        # mismo patrón que CompressorPlugin._advance_envelope
        new_env_db = level_db + (old_env_db - level_db) * (coef ** n_samples)
        self._envelope_db = new_env_db
        env_ramp_db = np.linspace(old_env_db, new_env_db, num=n_samples, endpoint=False, dtype=np.float32)
        return self._gain_from_envelope(env_ramp_db)

    def _gain_from_envelope(self, env_db: np.ndarray) -> np.ndarray:
        over_threshold_db = np.maximum(env_db - self._threshold_db, 0.0)
        reduction_db = np.minimum(over_threshold_db, self._reduction_db)
        return (10.0 ** (-reduction_db / 20.0)).astype(np.float32)

    def teardown(self) -> None:
        self._hp_filter = None
        self._lp_filter = None

    @property
    def algorithmic_latency_ms(self) -> float:
        return 0.0

    @property
    def parameters(self) -> list[Parameter]:
        return [
            Parameter(id="freq_hz", label="Frecuencia (Hz)", type="float",
                      default=_DEFAULT_FREQ_HZ, min=2000.0, max=12000.0),
            Parameter(id="threshold_db", label="Umbral (dB)", type="float",
                      default=_DEFAULT_THRESHOLD_DB, min=-60.0, max=0.0),
            Parameter(id="reduction_db", label="Reducción (dB)", type="float",
                      default=_DEFAULT_REDUCTION_DB, min=0.0, max=24.0),
        ]

    def set_parameter(self, id: str, value) -> None:
        if id == "freq_hz":
            self._freq_hz = float(value)
            self._build_filter()
        elif id == "threshold_db":
            self._threshold_db = float(value)
        elif id == "reduction_db":
            self._reduction_db = float(value)

    def _build_filter(self) -> None:
        nyq = self._sample_rate / 2.0
        if self._freq_hz >= nyq:
            self._hp_filter = None
            self._lp_filter = None
            return
        sos_hp = _linkwitz_riley_sos(self._freq_hz, self._sample_rate, "highpass")
        sos_lp = _linkwitz_riley_sos(self._freq_hz, self._sample_rate, "lowpass")
        # estado se resetea al cambiar freq_hz: transitorio breve aceptable
        self._hp_filter = (sos_hp, np.zeros((sos_hp.shape[0], 2, self._channels)))
        self._lp_filter = (sos_lp, np.zeros((sos_lp.shape[0], 2, self._channels)))

    def _build_coefficients(self) -> None:
        fs = self._sample_rate
        self._attack_coef = float(np.exp(-1.0 / (_ATTACK_MS * 1e-3 * fs)))
        self._release_coef = float(np.exp(-1.0 / (_RELEASE_MS * 1e-3 * fs)))
