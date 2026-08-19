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
        # Toda la secuencia stop→build→start→register bajo el lock: dos POST
        # concurrentes al mismo target no pueden filtrar un thread huérfano.
        with self._lock:
            old = self._threads.pop(target, None)
            if old:
                old.stop()
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
            self._threads[target] = thread
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


engine = AudioEngine()
