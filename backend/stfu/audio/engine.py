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
        warmupea (sesión ONNX creada) en este hilo — SIEMPRE fuera del lock,
        igual que insert_plugin/remove_plugin, para no bloquear otros
        targets durante la apertura de sesión. El staging hacia el worker
        (request_plugin_swap) y la escritura a _configs corren en un ÚNICO
        bloque bajo lock: si no, restart_with_devices reconstruye el
        pipeline desde el modelo con el que `target` arrancó y revierte en
        silencio un swap en vivo (o un downgrade del DegradeMonitor bajo
        presión de CPU) en el próximo restart por cambio de default device.
        El índice se busca en _configs[target].plugin_configs — no en
        thread.pipeline._plugins, que el worker actualiza de forma asíncrona
        y puede ir un chunk atrás (mismo criterio que insert_plugin) — y
        preserva "parameters" (p.ej. strength) del plugin reemplazado. Antes
        de construir nada se descarta rápido el caso target-inactivo (bajo
        lock, sin tocar build_pipeline): evita levantar el modelo — I/O real
        de sesión ONNX, o un ValueError si model_id no existe — para un
        target que ni siquiera está corriendo. El bloque final vuelve a leer
        thread/config frescos (nunca los del check inicial): si el target se
        paró mientras el modelo se construía/warmupeaba, este swap se
        descarta sin registrarse, mismo criterio anti-TOCTOU que start()."""
        from stfu.core.pipeline_factory import build_pipeline
        with self._lock:
            if target not in self._threads:
                return False
        plugin_id = f"model:{model_id}"
        staged = build_pipeline([{"plugin_id": plugin_id}], device=device)
        plugin = staged._plugins[0]
        plugin.setup(plugin.preferred_format)  # warmup: nunca en el worker, nunca bajo lock
        with self._lock:
            thread = self._threads.get(target)
            if thread is None:
                return False
            config = self._configs.get(target)
            index = self._model_plugin_index(config)
            thread.request_plugin_swap(index, plugin)
            self._write_swapped_model_config(config, index, plugin_id)
        return True

    def _model_plugin_index(self, config: dict | None) -> int:
        """Índice del plugin de modelo/NC en la cadena lógica de `config`
        (plugin_id con prefijo "model:"). Por convención el modelo vive en
        index 0 (ver runtime_state, que lee plugin_configs[0] como el slot
        de strength) — ese mismo 0 es el fallback si no hay config
        registrada todavía o ningún plugin de modelo activo en la cadena."""
        if config is None:
            return 0
        plugins_cfg = config.get("plugin_configs") or []
        return next(
            (i for i, cfg in enumerate(plugins_cfg)
             if cfg.get("plugin_id", "").startswith("model:")),
            0,
        )

    def _write_swapped_model_config(self, config: dict | None, index: int, plugin_id: str) -> None:
        """Escribe el nuevo plugin_id en _configs preservando "parameters"
        del slot reemplazado (p.ej. strength seteado por el usuario antes
        del swap). No-op si no hay config registrada o el índice no entra
        en la cadena — degrada sin romper el swap ya encolado en el worker,
        nunca lanza IndexError."""
        if config is None:
            return
        plugins_cfg = config.get("plugin_configs")
        if plugins_cfg is None or not 0 <= index < len(plugins_cfg):
            return
        parameters = plugins_cfg[index].get("parameters", {})
        plugins_cfg[index] = {"plugin_id": plugin_id, "parameters": dict(parameters)}

    def insert_plugin(
        self, target: str, index: int, plugin_config: dict, device: str = "auto",
    ) -> float | None:
        """Inserta un plugin en el pipeline vivo sin reiniciar el stream:
        se construye y warmupea (setup()) en este hilo, igual que
        swap_model — SIEMPRE fuera del lock, para no bloquear otros targets
        durante la apertura de sesión/dispositivo. La validación del índice,
        el staging hacia el worker y la escritura a _configs corren en un
        ÚNICO bloque bajo lock: dos insert/remove concurrentes sobre el
        MISMO target (dos requests HTTP solapadas — las rutas son `def`
        sync, corren en threads del threadpool) quedan totalmente
        serializados. La validación usa len(_configs[target].plugin_configs)
        — no thread.pipeline._plugins — porque _configs se actualiza en el
        mismo paso atómico que el staging, mientras que el pipeline vivo lo
        actualiza el worker de forma asíncrona (puede ir un chunk atrás);
        usar _configs como fuente de verdad es lo único que garantiza que
        un segundo insert/remove ve el efecto del primero aunque el worker
        todavía no lo haya aplicado, evitando el desync permanente + índice
        mal ubicado que reportó el review de esta task. None si el target
        no está activo; IndexError si el índice no entra en la cadena
        lógica actual (incluyendo cambios ya encolados)."""
        from stfu.core.pipeline_factory import build_pipeline
        staged = build_pipeline([plugin_config], device=device)
        plugin = staged._plugins[0]
        plugin.setup(plugin.preferred_format)  # warmup: nunca en el worker, nunca bajo lock
        with self._lock:
            thread = self._threads.get(target)
            config = self._configs.get(target)
            if thread is None or config is None:
                return None
            plugins_cfg = config["plugin_configs"]
            if not 0 <= index <= len(plugins_cfg):
                raise IndexError(f"insert index {index} fuera de rango")
            preview_plugins = list(thread.pipeline._plugins)
            preview_plugins.insert(index, plugin)
            latency = thread.pipeline.preview_total_latency_ms(preview_plugins)
            thread.request_plugin_insert(index, plugin)
            plugins_cfg.insert(index, plugin_config)
        return latency

    def remove_plugin(self, target: str, index: int) -> float | None:
        """Quita un plugin del pipeline vivo sin reiniciar el stream —
        mismo criterio de serialización que insert_plugin (validación +
        staging + escritura a _configs en un único bloque bajo lock, contra
        len(_configs[target].plugin_configs) como fuente de verdad). None
        si el target no está activo; IndexError si el índice no entra en
        la cadena lógica actual."""
        with self._lock:
            thread = self._threads.get(target)
            config = self._configs.get(target)
            if thread is None or config is None:
                return None
            plugins_cfg = config["plugin_configs"]
            if not 0 <= index < len(plugins_cfg):
                raise IndexError(f"remove index {index} fuera de rango")
            preview_plugins = list(thread.pipeline._plugins)
            if index < len(preview_plugins):
                del preview_plugins[index]
            latency = thread.pipeline.preview_total_latency_ms(preview_plugins)
            thread.request_plugin_remove(index)
            del plugins_cfg[index]
        return latency


engine = AudioEngine()
