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
        # Config con la que cada target fue arrancado (device ids + plugin
        # chain): permite reiniciar un target reusando su cadena de plugins
        # cuando cambia el default device, sin que el caller tenga que
        # reenviarla (ver restart_with_devices / DefaultDeviceWatcher).
        self._configs: dict[str, dict] = {}
        # Incrementa en cada registro/baja EFECTIVO de un target (nunca se
        # borra, sobrevive a un stop). Un restart_with_devices lee el epoch
        # antes de abrir el device nuevo (I/O bloqueante y lento); si al
        # llegar a comitear el epoch ya cambió, algo más reciente (un stop
        # del usuario, u otro start) ganó la carrera y el restart se
        # descarta sin registrarse — ver start(expected_epoch=...).
        self._epochs: dict[str, int] = {}
        self._lock = threading.Lock()

    def start(
        self,
        target: str,
        input_device_id: int,
        output_device_id: int,
        plugin_configs: list[dict],
        *,
        expected_epoch: int | None = None,
    ) -> float | None:
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
        discard = None
        with self._lock:
            if expected_epoch is not None and self._epochs.get(target, 0) != expected_epoch:
                # TOCTOU: algo cambió el estado de `target` mientras este
                # thread abría el device nuevo. Ese cambio más reciente gana:
                # el thread recién abierto se descarta SIN registrarse (nunca
                # queda huérfano ni resucita un target que el usuario paró).
                discard = thread
                old = None
            else:
                old = self._threads.get(target)
                self._threads[target] = thread
                self._configs[target] = {
                    "input_device_id": input_device_id,
                    "output_device_id": output_device_id,
                    "plugin_configs": plugin_configs,
                }
                self._epochs[target] = self._epochs.get(target, 0) + 1
        if discard is not None:
            discard.stop()
            return None
        if old:
            old.stop()
        return pipeline.total_latency_ms()

    def stop(self, target: str) -> None:
        with self._lock:
            thread = self._threads.pop(target, None)
            self._configs.pop(target, None)
            if thread is not None:
                self._epochs[target] = self._epochs.get(target, 0) + 1
        if thread:
            thread.stop()

    def stop_all(self) -> None:
        with self._lock:
            threads = dict(self._threads)
            self._threads.clear()
            self._configs.clear()
            for target in threads:
                self._epochs[target] = self._epochs.get(target, 0) + 1
        for t in threads.values():
            t.stop()

    def current_devices(self, target: str) -> tuple[int, int] | None:
        """(input_device_id, output_device_id) con los que corre `target`
        ahora mismo, o None si no está activo."""
        with self._lock:
            config = self._configs.get(target)
        if config is None:
            return None
        return config["input_device_id"], config["output_device_id"]

    def runtime_state(self, target: str) -> dict | None:
        """input_device_id y strength (parámetro del plugin NC en index 0)
        con los que corre `target` ahora mismo, o None si no está activo.
        strength es None si el plugin en index 0 no tiene ese parámetro
        (p.ej. una cadena sin modelo NC)."""
        with self._lock:
            config = self._configs.get(target)
        if config is None:
            return None
        plugin_configs = config["plugin_configs"]
        strength = None
        if plugin_configs:
            parameters = plugin_configs[0].get("parameters") or {}
            strength = parameters.get("strength")
        return {
            "input_device_id": config["input_device_id"],
            "strength": strength,
        }

    def restart_with_devices(
        self,
        target: str,
        input_device_id: int | None = None,
        output_device_id: int | None = None,
    ) -> float | None:
        """Reinicia `target` con la MISMA plugin chain, reemplazando el/los
        device id(s) dados. Reusa start(), así que hereda la invariante
        anti-huérfano MÁS la guarda anti-TOCTOU (expected_epoch): si un
        stop()/start() del usuario llega mientras el device nuevo se estaba
        abriendo, ese cambio gana y este restart se descarta sin registrarse.
        None si el target no está activo (nada que reiniciar) o si perdió
        la carrera contra un cambio más reciente."""
        with self._lock:
            config = self._configs.get(target)
            epoch = self._epochs.get(target)
        if config is None:
            return None
        new_input = input_device_id if input_device_id is not None else config["input_device_id"]
        new_output = output_device_id if output_device_id is not None else config["output_device_id"]
        return self.start(
            target=target,
            input_device_id=new_input,
            output_device_id=new_output,
            plugin_configs=config["plugin_configs"],
            expected_epoch=epoch,
        )

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
        # Escribe también en _configs (no solo en el pipeline vivo): si no,
        # runtime_state()/restart_with_devices() siguen leyendo el valor de
        # arranque para siempre — un cambio de slider quedaría "fantasma"
        # tras un reload o un restart por cambio de default device.
        with self._lock:
            thread = self._threads.get(target)
            if thread is None:
                return False
            config = self._configs.get(target)
            if config is not None:
                plugins = config.get("plugin_configs") or []
                if 0 <= plugin_index < len(plugins):
                    plugins[plugin_index].setdefault("parameters", {})[param_id] = value
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

    def insert_plugin(
        self, target: str, index: int, plugin_config: dict, device: str = "auto",
    ) -> float | None:
        """Inserta un plugin en el pipeline vivo sin reiniciar el stream:
        se construye y warmupea (setup()) en este hilo, igual que
        swap_model, y el worker aplica el insert en la lista entre chunks.
        También escribe en _configs (mismo criterio que set_parameter) para
        que runtime_state()/restart_with_devices reflejen la cadena viva.
        None si el target no está activo; IndexError si el índice no entra
        en la cadena actual."""
        from stfu.core.pipeline_factory import build_pipeline
        with self._lock:
            thread = self._threads.get(target)
            config = self._configs.get(target)
        if thread is None or config is None:
            return None
        current_plugins = thread.pipeline._plugins
        if not 0 <= index <= len(current_plugins):
            raise IndexError(f"insert index {index} fuera de rango")
        staged = build_pipeline([plugin_config], device=device)
        plugin = staged._plugins[0]
        plugin.setup(plugin.preferred_format)  # warmup: nunca en el worker
        preview_plugins = list(current_plugins)
        preview_plugins.insert(index, plugin)
        latency = thread.pipeline.preview_total_latency_ms(preview_plugins)
        thread.request_plugin_insert(index, plugin)
        with self._lock:
            plugins_cfg = config.get("plugin_configs")
            if plugins_cfg is not None:
                plugins_cfg.insert(index, plugin_config)
        return latency

    def remove_plugin(self, target: str, index: int) -> float | None:
        """Quita un plugin del pipeline vivo sin reiniciar el stream — el
        worker aplica el remove en la lista entre chunks. Escribe en
        _configs igual que insert_plugin. None si el target no está activo;
        IndexError si el índice no entra en la cadena actual."""
        with self._lock:
            thread = self._threads.get(target)
            config = self._configs.get(target)
        if thread is None or config is None:
            return None
        current_plugins = thread.pipeline._plugins
        if not 0 <= index < len(current_plugins):
            raise IndexError(f"remove index {index} fuera de rango")
        preview_plugins = list(current_plugins)
        del preview_plugins[index]
        latency = thread.pipeline.preview_total_latency_ms(preview_plugins)
        thread.request_plugin_remove(index)
        with self._lock:
            plugins_cfg = config.get("plugin_configs")
            if plugins_cfg is not None and 0 <= index < len(plugins_cfg):
                del plugins_cfg[index]
        return latency


engine = AudioEngine()
