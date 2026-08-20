from typing import Optional
from time import perf_counter
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.adapter import FormatAdapter
from stfu.core.telemetry import StageMetrics
from stfu.plugins.base import AudioPlugin


def _adapter_or_none(src: AudioFormat, dst: AudioFormat) -> Optional[FormatAdapter]:
    return FormatAdapter(src, dst) if src != dst else None


class Pipeline:
    """Cadena de plugins con adaptación automática de formatos.

    Contrato con la capa de captura: process() recibe y retorna chunks en el
    formato del stream. Internamente los adapters pueden emitir 0..N chunks
    por llamada (acumulación, resampleo); un FIFO de salida absorbe esa
    variabilidad — mientras el pipeline ceba, emite silencio.
    """

    def __init__(self) -> None:
        self._plugins: list[AudioPlugin] = []
        self._stages: list[tuple[Optional[FormatAdapter], AudioPlugin]] = []
        self._output_adapter: Optional[FormatAdapter] = None
        self._input_format: Optional[AudioFormat] = None
        self._out_buffer = np.empty((0, 1), dtype=np.float32)
        self._stage_metrics: list[StageMetrics] = []

    def add_plugin(self, plugin: AudioPlugin) -> None:
        self._plugins.append(plugin)

    def set_parameter(self, plugin_index: int, param_id: str, value) -> None:
        if not 0 <= plugin_index < len(self._plugins):
            raise IndexError(f"plugin_index {plugin_index} fuera de rango")
        self._plugins[plugin_index].set_parameter(param_id, value)

    def replace_plugin(self, index: int, plugin: AudioPlugin) -> None:
        """Swap en caliente desde el hilo del worker. Si el plugin nuevo produce
        el mismo formato de setup que el viejo, hace un swap quirúrgico del
        stage sin re-setupear los demás plugins (preserva el buffer soxr de
        los adapters vecinos). Si el formato difiere, recompila todo."""
        if not 0 <= index < len(self._plugins):
            raise IndexError(f"plugin index {index} fuera de rango")
        old = self._plugins[index]
        if self._input_format is None or not self._can_swap_in_place(index, plugin):
            self._plugins[index] = plugin
            old.teardown()
            if self._input_format is not None:
                self.compile(self._input_format)
            return
        self._swap_stage_in_place(index, old, plugin)

    def _can_swap_in_place(self, index: int, plugin: AudioPlugin) -> bool:
        """True si el plugin nuevo puede reemplazar in-place al del stage
        `index`. compile() siempre llama a setup() de un plugin con su propio
        preferred_format (el adapter previo, si existe, convierte hacia ese
        formato antes de entregarle audio) — por eso un plugin con el mismo
        preferred_format que el viejo recibe exactamente la misma entrada, y
        los adapters vecinos (construidos contra ese preferred_format) siguen
        siendo válidos sin tocarlos. Ante cualquier duda, False → recompile."""
        if index >= len(self._stages):
            return False
        old = self._plugins[index]
        return plugin.preferred_format == old.preferred_format

    def _swap_stage_in_place(self, index: int, old: AudioPlugin, plugin: AudioPlugin) -> None:
        """Reemplaza solo el stage `index`: tira abajo el viejo, setupea el
        nuevo con el formato que ya recibía el viejo y reasigna
        _stages/_stage_metrics en bloque (mismo patrón atómico que compile(),
        ver Task 1) para que un lector concurrente nunca vea listas a medio
        construir."""
        adapter, _ = self._stages[index]
        setup_in = adapter.output_format if adapter is not None else plugin.preferred_format
        old.teardown()
        plugin.setup(setup_in)
        self._plugins[index] = plugin
        new_stages = list(self._stages)
        new_stages[index] = (adapter, plugin)
        new_metrics = list(self._stage_metrics)
        new_metrics[index] = StageMetrics(plugin.name, budget_ms=self._budget_ms())
        self._stages = new_stages
        self._stage_metrics = new_metrics

    def insert_plugin(self, index: int, plugin: AudioPlugin) -> None:
        """Inserta `plugin` (ya seteado por el caller — mismo contrato que
        replace_plugin/swap_model: warmup fuera del worker, acá solo se
        reconectan formatos) en `index`. Igual que _swap_stage_in_place, solo
        toca lo estrictamente necesario: el adapter de entrada del plugin
        nuevo y, si tiene vecino a la derecha, el adapter que lo alimenta (o
        el output_adapter si quedó último). Los demás stages conservan su
        adapter (buffer soxr) intacto — depende del invariante de
        AudioPlugin.setup(): siempre devuelve el fmt de entrada sin
        modificar, así que el formato de salida de un stage es siempre su
        propio preferred_format, sin importar quién sea su vecino."""
        if not 0 <= index <= len(self._plugins):
            raise IndexError(f"insert index {index} fuera de rango")
        new_plugins = list(self._plugins)
        new_plugins.insert(index, plugin)
        if self._input_format is None:
            self._plugins = new_plugins
            return
        stages = list(self._stages)
        metrics = list(self._stage_metrics)
        upstream = new_plugins[index - 1].preferred_format if index > 0 else self._input_format
        in_adapter = _adapter_or_none(upstream, plugin.preferred_format)
        stages.insert(index, (in_adapter, plugin))
        metrics.insert(index, StageMetrics(plugin.name, budget_ms=self._budget_ms()))
        output_adapter = self._output_adapter
        if index + 1 < len(new_plugins):
            downstream = new_plugins[index + 1]
            out_adapter = _adapter_or_none(plugin.preferred_format, downstream.preferred_format)
            stages[index + 1] = (out_adapter, downstream)
        else:
            output_adapter = _adapter_or_none(plugin.preferred_format, self._input_format)
        self._plugins = new_plugins
        self._stages = stages
        self._stage_metrics = metrics
        self._output_adapter = output_adapter

    def remove_plugin(self, index: int) -> None:
        """Quita el plugin en `index` y reconecta sus vecinos con un adapter
        nuevo (o ninguno); el resto de la cadena no se toca — mismo criterio
        quirúrgico que insert_plugin. teardown() del plugin quitado corre acá
        (hilo que aplica el cambio, igual que replace_plugin)."""
        if not 0 <= index < len(self._plugins):
            raise IndexError(f"remove index {index} fuera de rango")
        removed = self._plugins[index]
        new_plugins = list(self._plugins)
        del new_plugins[index]
        if self._input_format is None:
            self._plugins = new_plugins
            removed.teardown()
            return
        stages = list(self._stages)
        metrics = list(self._stage_metrics)
        del stages[index]
        del metrics[index]
        upstream = new_plugins[index - 1].preferred_format if index > 0 else self._input_format
        output_adapter = self._output_adapter
        if index < len(new_plugins):
            downstream = new_plugins[index]
            out_adapter = _adapter_or_none(upstream, downstream.preferred_format)
            stages[index] = (out_adapter, downstream)
        else:
            output_adapter = _adapter_or_none(upstream, self._input_format)
        self._plugins = new_plugins
        self._stages = stages
        self._stage_metrics = metrics
        self._output_adapter = output_adapter
        removed.teardown()

    def preview_total_latency_ms(self, plugins: list[AudioPlugin]) -> float:
        """Latencia total que tendría el pipeline si `plugins` fuera la
        cadena activa, sin mutar el pipeline vivo ni llamar a setup() en
        ningún plugin (solo lee preferred_format/algorithmic_latency_ms —
        propiedades puras — y arma adapters descartables). Permite al caller
        (AudioEngine.insert_plugin/remove_plugin) devolver la latencia
        resultante de un cambio staged antes de que el worker lo aplique."""
        plugin_lat = sum(p.algorithmic_latency_ms for p in plugins)
        if self._input_format is None or not plugins:
            return plugin_lat
        adapter_lat = 0.0
        current = self._input_format
        for plugin in plugins:
            pref = plugin.preferred_format
            adapter = _adapter_or_none(current, pref)
            if adapter is not None:
                adapter_lat += adapter.buffering_latency_ms
            current = pref
        output_adapter = _adapter_or_none(current, self._input_format)
        if output_adapter is not None:
            adapter_lat += output_adapter.buffering_latency_ms
        return plugin_lat + adapter_lat

    def _budget_ms(self) -> float:
        return self._input_format.chunk_samples / self._input_format.sample_rate * 1000.0

    def clear(self) -> None:
        for p in self._plugins:
            p.teardown()
        self._plugins.clear()
        self._stages.clear()
        self._stage_metrics.clear()
        self._output_adapter = None
        self._input_format = None

    def compile(self, input_format: AudioFormat) -> None:
        self._input_format = input_format
        self._out_buffer = np.empty((0, input_format.channels), dtype=np.float32)
        budget_ms = self._budget_ms()
        stage_metrics = [
            StageMetrics(p.name, budget_ms=budget_ms) for p in self._plugins
        ]
        stages: list[tuple[Optional[FormatAdapter], AudioPlugin]] = []
        current = input_format
        for plugin in self._plugins:
            pref = plugin.preferred_format
            adapter = _adapter_or_none(current, pref)
            stages.append((adapter, plugin))
            current = plugin.setup(pref if adapter else current)
        # Reasignación en bloque: un lector concurrente (total_latency_ms desde el
        # hilo de API) nunca ve una lista a medio construir.
        self._stages = stages
        self._stage_metrics = stage_metrics
        self._output_adapter = _adapter_or_none(current, input_format)

    def process(self, audio: np.ndarray) -> np.ndarray:
        if not self._plugins:
            return audio
        chunks: list[np.ndarray] = [audio]
        for (adapter, plugin), metrics in zip(self._stages, self._stage_metrics):
            t0 = perf_counter()
            chunks = self._run_stage(adapter, plugin, chunks)
            metrics.record((perf_counter() - t0) * 1000.0)
        self._push_output(chunks)
        return self._pop_output()

    def _run_stage(
        self,
        adapter: Optional[FormatAdapter],
        plugin: AudioPlugin,
        chunks: list[np.ndarray],
    ) -> list[np.ndarray]:
        if adapter is None:
            return [plugin.process(c) for c in chunks]
        out = []
        for c in chunks:
            out.extend(plugin.process(ac) for ac in adapter.convert(c))
        return out

    def _push_output(self, chunks: list[np.ndarray]) -> None:
        for c in chunks:
            if self._output_adapter is not None:
                for oc in self._output_adapter.convert(c):
                    self._out_buffer = np.concatenate([self._out_buffer, oc], axis=0)
            else:
                self._out_buffer = np.concatenate([self._out_buffer, c], axis=0)

    def _pop_output(self) -> np.ndarray:
        fmt = self._input_format
        n = fmt.chunk_samples
        if len(self._out_buffer) >= n:
            out = self._out_buffer[:n]
            self._out_buffer = self._out_buffer[n:]
            return out
        return np.zeros((n, fmt.channels), dtype=np.float32)

    def stage_metrics(self) -> list[dict]:
        return [m.snapshot() for m in self._stage_metrics]

    def total_latency_ms(self) -> float:
        plugin_lat = sum(p.algorithmic_latency_ms for p in self._plugins)
        adapter_lat = sum(a.buffering_latency_ms for a, _ in self._stages if a)
        if self._output_adapter is not None:
            adapter_lat += self._output_adapter.buffering_latency_ms
        return plugin_lat + adapter_lat
