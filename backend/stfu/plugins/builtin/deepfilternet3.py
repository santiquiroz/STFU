import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.base import AudioPlugin, Parameter

_CHUNK = 960
_DEFAULT_CONTEXT_MS = 480
_MIN_CONTEXT_MS = 120
_MAX_CONTEXT_MS = 1000


class DeepFilterNet3Plugin(AudioPlugin):
    """DFN3 con ventana deslizante de contexto.

    enhance() es API offline: resetea el estado recurrente en cada llamada.
    Llamarla con chunks de 20ms aislados destruye el contexto temporal del
    modelo. En su lugar se mantiene un buffer rodante de context_ms y se
    emite solo el último chunk (pad=True alinea salida con entrada), así el
    GRU procesa siempre con contexto. Costo medido: ~13ms por llamada con
    480ms de ventana (budget: 20ms).
    """

    name = "DeepFilterNet3 Noise Canceller"
    version = "3.1.0"

    def __init__(self) -> None:
        self._model = None
        self._df_state = None
        self._strength: float = 0.85
        self._context_ms: int = _DEFAULT_CONTEXT_MS
        self._window: np.ndarray | None = None

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=48000, channels=1, chunk_samples=_CHUNK)

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        from df.enhance import init_df
        self._model, self._df_state, _ = init_df()
        self._reset_window()
        return fmt

    def process(self, audio: np.ndarray) -> np.ndarray:
        if self._model is None:
            return audio
        import torch
        from df.enhance import enhance
        self._push_window(audio[:, 0])
        tensor = torch.from_numpy(self._window[np.newaxis, :])
        enhanced = enhance(
            self._model,
            self._df_state,
            tensor,
            pad=True,
            atten_lim_db=self._strength * 100.0,
        )
        out = enhanced[0, -_CHUNK:].numpy()
        return out.reshape(-1, 1).astype(np.float32)

    def teardown(self) -> None:
        self._model = None
        self._df_state = None
        self._window = None

    def _reset_window(self) -> None:
        samples = int(48000 * self._context_ms / 1000)
        samples = max(samples, _CHUNK)
        self._window = np.zeros(samples, dtype=np.float32)

    def _push_window(self, chunk: np.ndarray) -> None:
        self._window = np.concatenate([self._window[len(chunk):], chunk.astype(np.float32)])

    @property
    def algorithmic_latency_ms(self) -> float:
        # 20ms ventana STFT + 20ms lookahead (2 frames de 10ms)
        return 40.0

    @property
    def parameters(self) -> list[Parameter]:
        return [
            Parameter(
                id="strength",
                label="Intensidad de cancelación",
                type="float",
                default=0.85,
                min=0.0,
                max=1.0,
            ),
            Parameter(
                id="context_ms",
                label="Contexto del modelo (ms)",
                type="int",
                default=_DEFAULT_CONTEXT_MS,
                min=_MIN_CONTEXT_MS,
                max=_MAX_CONTEXT_MS,
            ),
        ]

    def set_parameter(self, id: str, value) -> None:
        if id == "strength":
            self._strength = float(value)
        elif id == "context_ms":
            self._context_ms = int(min(max(float(value), _MIN_CONTEXT_MS), _MAX_CONTEXT_MS))
            if self._window is not None:
                self._reset_window()
