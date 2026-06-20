from typing import Optional
import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.adapter import FormatAdapter
from stfu.plugins.base import AudioPlugin


class Pipeline:
    def __init__(self) -> None:
        self._plugins: list[AudioPlugin] = []
        self._adapters: list[Optional[FormatAdapter]] = []

    def add_plugin(self, plugin: AudioPlugin) -> None:
        self._plugins.append(plugin)

    def clear(self) -> None:
        for p in self._plugins:
            p.teardown()
        self._plugins.clear()
        self._adapters.clear()

    def compile(self, input_format: AudioFormat) -> None:
        self._adapters.clear()
        current = input_format
        for plugin in self._plugins:
            pref = plugin.preferred_format
            if current != pref:
                self._adapters.append(FormatAdapter(current, pref))
                current = pref
            else:
                self._adapters.append(None)
            current = plugin.setup(current)

    def process(self, audio: np.ndarray) -> np.ndarray:
        if not self._plugins:
            return audio
        chunk = audio
        for plugin, adapter in zip(self._plugins, self._adapters):
            if adapter is not None:
                chunks = list(adapter.convert(chunk))
                if not chunks:
                    return np.zeros_like(chunk)
                chunk = chunks[0]
            chunk = plugin.process(chunk)
        return chunk

    def total_latency_ms(self) -> float:
        plugin_lat = sum(p.algorithmic_latency_ms for p in self._plugins)
        adapter_lat = sum(a.buffering_latency_ms for a in self._adapters if a)
        return plugin_lat + adapter_lat
