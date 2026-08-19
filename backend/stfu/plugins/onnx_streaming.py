"""Plugin genérico para modelos ONNX de speech enhancement con streaming real.

El manifest declara los tensores (io_spec); los estados recurrentes de salida
se realimentan como entrada de la siguiente llamada — el modelo mantiene su
contexto temporal sin ventanas deslizantes ni resets.
"""
import logging
from pathlib import Path
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.hub.registry import ModelManifest
from stfu.inference import ep_router
from stfu.plugins.base import AudioPlugin, Parameter

_log = logging.getLogger(__name__)


class OnnxStreamingPlugin(AudioPlugin):
    def __init__(self, manifest: ModelManifest, model_path: Path, device: str = "auto") -> None:
        if manifest.io_spec is None:
            raise ValueError(f"manifest {manifest.id!r} sin io_spec: no es un modelo ONNX")
        self._manifest = manifest
        self._model_path = Path(model_path)
        self._device = device
        self._session = None
        self._states: dict[str, np.ndarray] = {}
        self._strength: float = 1.0
        self._active_device: str | None = None
        self._nan_warned: bool = False
        self._degraded: bool = False

    @property
    def name(self) -> str:
        return self._manifest.name

    @property
    def version(self) -> str:
        return self._manifest.version

    @property
    def preferred_format(self) -> AudioFormat:
        return AudioFormat(**self._manifest.preferred_format)

    @property
    def active_device(self) -> str | None:
        return self._active_device

    @property
    def runtime_status(self) -> dict:
        return {
            "device": self._active_device,
            "degraded": self._degraded,
            "model_id": self._manifest.id,
        }

    def setup(self, fmt: AudioFormat) -> AudioFormat:
        if self._session is None:
            self._active_device = ep_router.select_device(self._device, self._probe)
        self._reset_states()
        self._degraded = False
        return fmt

    def _probe(self, providers: list[str]) -> bool:
        import onnxruntime as ort
        try:
            session = ort.InferenceSession(str(self._model_path), providers=providers)
            self._session = session
            self._reset_states()
            out = self._run(np.zeros((self.preferred_format.chunk_samples, 1), dtype=np.float32))
            if not np.isfinite(out).all():
                _log.warning("probe %s produjo NaN/Inf", providers[0])
                self._session = None
                return False
            return True
        except Exception:
            _log.warning("probe %s falló", providers[0], exc_info=True)
            self._session = None
            return False

    def process(self, audio: np.ndarray) -> np.ndarray:
        if self._session is None:
            return audio
        dry = audio
        try:
            wet = self._run(audio)
        except Exception:
            _log.exception("run de la sesión falló en device %s; intentando fallback", self._active_device)
            if not self._fallback_to_next_device():
                self._enter_degraded_passthrough()
                return dry
            try:
                wet = self._run(audio)
            except Exception:
                _log.exception("run falló también tras fallback; passthrough")
                self._enter_degraded_passthrough()
                return dry
        if not np.isfinite(wet).all():
            self._warn_nan_once()
            return dry
        s = self._strength
        return (wet * s + dry * (1.0 - s)).astype(np.float32, copy=False)

    def _enter_degraded_passthrough(self) -> None:
        # _active_device se deja como quedó (última EP viva): no es la señal de
        # actividad una vez acá — runtime_status.degraded es la autoritativa.
        self._session = None
        self._degraded = True

    def _fallback_to_next_device(self) -> bool:
        for candidate in ep_router.remaining_ladder(self._active_device or self._device):
            try:
                providers = ep_router.providers_for(candidate)
            except ep_router.DeviceUnavailable:
                continue
            if self._probe(providers):
                self._active_device = candidate
                _log.warning("EP fallback: sesión recreada en device %s", candidate)
                return True
        return False

    def _warn_nan_once(self) -> None:
        if not self._nan_warned:
            _log.warning(
                "modelo %s produjo NaN/Inf en runtime — usando passthrough dry",
                self._manifest.id,
            )
            self._nan_warned = True

    def _run(self, audio: np.ndarray) -> np.ndarray:
        spec = self._manifest.io_spec
        chunk = audio.shape[0]
        shape = [chunk if d == "chunk" else d for d in spec.audio_input.shape]
        feeds = {spec.audio_input.name: audio[:, 0].reshape(shape).astype(np.float32)}
        for st in spec.states:
            feeds[st.input] = self._states[st.input]
        output_names = [spec.audio_output] + [st.output for st in spec.states]
        results = self._session.run(output_names, feeds)
        for st, value in zip(spec.states, results[1:]):
            self._states[st.input] = value
        return np.asarray(results[0]).reshape(-1, 1)

    def teardown(self) -> None:
        self._session = None
        self._states = {}

    def _reset_states(self) -> None:
        spec = self._manifest.io_spec
        self._states = {
            st.input: np.zeros(st.shape, dtype=np.float32) for st in spec.states
        }

    @property
    def algorithmic_latency_ms(self) -> float:
        return self._manifest.algorithmic_latency_ms

    @property
    def parameters(self) -> list[Parameter]:
        return [
            Parameter(id="strength", label="Intensidad de cancelación",
                      type="float", default=1.0, min=0.0, max=1.0),
        ]

    def set_parameter(self, id: str, value) -> None:
        if id == "strength":
            self._strength = float(value)
