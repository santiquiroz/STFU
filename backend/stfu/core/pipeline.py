from typing import Optional
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.adapter import FormatAdapter
from stfu.plugins.base import AudioPlugin


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

    def add_plugin(self, plugin: AudioPlugin) -> None:
        self._plugins.append(plugin)

    def clear(self) -> None:
        for p in self._plugins:
            p.teardown()
        self._plugins.clear()
        self._stages.clear()
        self._output_adapter = None
        self._input_format = None

    def compile(self, input_format: AudioFormat) -> None:
        self._stages.clear()
        self._input_format = input_format
        self._out_buffer = np.empty((0, input_format.channels), dtype=np.float32)
        current = input_format
        for plugin in self._plugins:
            pref = plugin.preferred_format
            adapter = FormatAdapter(current, pref) if current != pref else None
            self._stages.append((adapter, plugin))
            current = plugin.setup(pref if adapter else current)
        self._output_adapter = (
            FormatAdapter(current, input_format) if current != input_format else None
        )

    def process(self, audio: np.ndarray) -> np.ndarray:
        if not self._plugins:
            return audio
        chunks: list[np.ndarray] = [audio]
        for adapter, plugin in self._stages:
            chunks = self._run_stage(adapter, plugin, chunks)
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

    def total_latency_ms(self) -> float:
        plugin_lat = sum(p.algorithmic_latency_ms for p in self._plugins)
        adapter_lat = sum(a.buffering_latency_ms for a, _ in self._stages if a)
        if self._output_adapter is not None:
            adapter_lat += self._output_adapter.buffering_latency_ms
        return plugin_lat + adapter_lat
