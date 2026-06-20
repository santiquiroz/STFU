import threading
import sounddevice as sd
from stfu.audio.capture import CaptureThread
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.plugins.builtin.deepfilternet3 import DeepFilterNet3Plugin
from stfu.plugins.builtin.eq_parametric import EQParametricPlugin
from stfu.plugins.builtin.gain import GainPlugin

_PLUGIN_CLASSES = {
    "deepfilternet3": DeepFilterNet3Plugin,
    "eq_parametric": EQParametricPlugin,
    "gain": GainPlugin,
}

_CAPTURE_FORMAT = AudioFormat(sample_rate=48000, channels=1, chunk_samples=960)


def _out_channels_for_device(device_id: int) -> int:
    try:
        info = sd.query_devices(device_id)
        return min(int(info["max_output_channels"]), 2)
    except Exception:
        return 2


def _build_pipeline(plugin_configs: list[dict]) -> Pipeline:
    pipeline = Pipeline()
    for cfg in plugin_configs:
        cls = _PLUGIN_CLASSES.get(cfg["plugin_id"])
        if cls is None:
            raise ValueError(f"Plugin desconocido: {cfg['plugin_id']}")
        plugin = cls()
        for k, v in cfg.get("parameters", {}).items():
            plugin.set_parameter(k, v)
        pipeline.add_plugin(plugin)
    return pipeline


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
        self.stop(target)
        pipeline = _build_pipeline(plugin_configs)
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


engine = AudioEngine()
