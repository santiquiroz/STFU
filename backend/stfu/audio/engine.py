import threading
import sounddevice as sd
from stfu.audio.capture import CaptureThread
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline_factory import build_pipeline

# Stereo capture: WASAPI shared mode rejects mono on most devices.
# FormatAdapter handles stereo→mono conversion before plugins that need mono.
_CAPTURE_FORMAT = AudioFormat(sample_rate=48000, channels=2, chunk_samples=960)


def _out_channels_for_device(device_id: int) -> int:
    try:
        info = sd.query_devices(device_id)
        return min(int(info["max_output_channels"]), 2)
    except Exception:
        return 2


class AudioEngine:
    def __init__(self) -> None:
        self._threads: dict[str, CaptureThread] = {}
        self._lock = threading.Lock()

    def start(
        self,
        target: str,
        input_device_id: int,
        output_device_id: int,
        plugin_configs: list[dict],
    ) -> float:
        # La apertura de dispositivo (thread.start()) es I/O bloqueante y queda
        # FUERA del lock para no congelar stats/stop/active_targets. El lock solo
        # cubre el swap del registro. Invariante anti-huérfano: se registra el
        # nuevo y se para el viejo; dos starts concurrentes dejan exactamente uno
        # registrado y paran el resto (el thread nuevo se limpia solo si falla).
        pipeline = build_pipeline(plugin_configs)
        out_ch = _out_channels_for_device(output_device_id)
        thread = CaptureThread(
            input_device_id=input_device_id,
            output_device_id=output_device_id,
            fmt=_CAPTURE_FORMAT,
            pipeline=pipeline,
            out_channels=out_ch,
        )
        thread.start()
        with self._lock:
            old = self._threads.get(target)
            self._threads[target] = thread
        if old:
            old.stop()
        return pipeline.total_latency_ms()

    def stop(self, target: str) -> None:
        with self._lock:
            thread = self._threads.pop(target, None)
        if thread:
            thread.stop()

    def stop_all(self) -> None:
        with self._lock:
            threads = list(self._threads.values())
            self._threads.clear()
        for t in threads:
            t.stop()

    def get_latency_ms(self) -> float:
        with self._lock:
            threads = list(self._threads.values())
        if not threads:
            return 0.0
        return sum(t.measured_latency_ms for t in threads)

    def active_targets(self) -> list[str]:
        with self._lock:
            return list(self._threads.keys())

    def active_model_ids(self, target: str) -> set[str]:
        from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
        with self._lock:
            thread = self._threads.get(target)
        if thread is None:
            return set()
        return {
            p._manifest.id for p in thread.pipeline._plugins
            if isinstance(p, OnnxStreamingPlugin)
        }

    def get_stats(self) -> dict[str, dict]:
        with self._lock:
            threads = dict(self._threads)
        return {target: t.stats for target, t in threads.items()}

    def set_parameter(self, target: str, plugin_index: int, param_id: str, value) -> bool:
        with self._lock:
            thread = self._threads.get(target)
        if thread is None:
            return False
        thread.pipeline.set_parameter(plugin_index, param_id, value)
        return True

    def set_bypass(self, target: str, on: bool) -> bool:
        with self._lock:
            thread = self._threads.get(target)
        if thread is None:
            return False
        thread.set_bypass(on)
        return True

    def swap_model(self, target: str, model_id: str, device: str = "auto") -> bool:
        """Activa un modelo NC en el pipeline vivo. El plugin se construye y
        warmupea (sesión ONNX creada) en este hilo; el worker hace el swap
        entre chunks — sin cortar el stream."""
        from stfu.core.pipeline_factory import build_pipeline
        from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
        with self._lock:
            thread = self._threads.get(target)
        if thread is None:
            return False
        index = next(
            (i for i, p in enumerate(thread.pipeline._plugins)
             if isinstance(p, OnnxStreamingPlugin)),
            0,
        )
        staged = build_pipeline([{"plugin_id": f"model:{model_id}"}], device=device)
        plugin = staged._plugins[0]
        plugin.setup(plugin.preferred_format)  # warmup: crea la sesión acá, no en el worker
        thread.request_plugin_swap(index, plugin)
        return True


engine = AudioEngine()
