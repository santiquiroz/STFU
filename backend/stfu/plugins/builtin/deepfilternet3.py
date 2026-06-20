import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.base import AudioPlugin, Parameter


class DeepFilterNet3Plugin(AudioPlugin):
    name = "DeepFilterNet3 Noise Canceller"
    version = "3.0.0"

    def __init__(self) -> None:
        self._model = None
        self._df_state = None
        self._strength: float = 0.85

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(sample_rate=48000, channels=1, chunk_samples=960)

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        from df.enhance import init_df
        self._model, self._df_state, _ = init_df()
        return fmt

    def process(self, audio: np.ndarray) -> np.ndarray:
        import torch
        from df.enhance import enhance
        # audio: (960, 1) → enhance expects [C, T] tensor → (1, 960)
        tensor = torch.from_numpy(audio[:, 0][np.newaxis, :])  # (1, 960)
        enhanced = enhance(
            self._model,
            self._df_state,
            tensor,
            atten_lim_db=self._strength * 100.0,
        )
        # enhanced: (1, 960) tensor → (960, 1) numpy float32
        return enhanced[0].numpy().reshape(-1, 1).astype(np.float32)

    def teardown(self) -> None:
        self._model = None
        self._df_state = None

    @property
    def algorithmic_latency_ms(self) -> float:
        return 40.0

    @property
    def parameters(self) -> list[Parameter]:
        return [Parameter(
            id="strength",
            label="Intensidad de cancelación",
            type="float",
            default=0.85,
            min=0.0,
            max=1.0,
        )]

    def set_parameter(self, id: str, value) -> None:
        if id == "strength":
            self._strength = float(value)
