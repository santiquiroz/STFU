"""Procesamiento por chunk: pipeline con degradación a passthrough, swap
atómico de plugins y adaptación de canales.

Responsabilidad única: dado un chunk de audio, decidir si pasa crudo o
procesado, y aplicar swaps de plugin encolados por el hilo de UI. No conoce
streams, ring buffer ni threads de captura/reproducción.
"""
import logging
import queue
import time
import numpy as np
from stfu.core.pipeline import Pipeline

_log = logging.getLogger(__name__)

_OP_REPLACE = "replace"
_OP_INSERT = "insert"
_OP_REMOVE = "remove"


def _adjust_channels(audio: np.ndarray, out_ch: int) -> np.ndarray:
    proc_ch = audio.shape[1]
    if proc_ch == out_ch:
        return audio
    if proc_ch == 1 and out_ch > 1:
        return np.repeat(audio, out_ch, axis=1)
    return audio[:, :out_ch]


class PipelineWorker:
    """Ejecuta `pipeline.process()` por chunk con passthrough ante fallo de
    plugin, y aplica swaps de plugin encolados desde otro hilo.

    Invariante de threading: `request_swap`/`set_bypass` se llaman desde el
    hilo de UI; `drain_swaps`/`process` se llaman desde el worker de audio.
    El GIL hace atómica la escritura de `pipeline_failed`/`bypass` (bools) sin
    necesitar lock — no agregar escritores sin repensar esto.
    """

    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        self._swap_queue: queue.Queue = queue.Queue()
        self.pipeline_failed: bool = False
        self.bypass: bool = False
        self.latency_ms: float = 0.0

    def request_swap(self, index: int, plugin) -> None:
        self._swap_queue.put((_OP_REPLACE, index, plugin))

    def request_insert(self, index: int, plugin) -> None:
        self._swap_queue.put((_OP_INSERT, index, plugin))

    def request_remove(self, index: int) -> None:
        self._swap_queue.put((_OP_REMOVE, index, None))

    def set_bypass(self, on: bool) -> None:
        self.bypass = on

    def drain_swaps(self) -> None:
        while True:
            try:
                op, index, plugin = self._swap_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._apply_staged_change(op, index, plugin)
                self.pipeline_failed = False  # un cambio de cadena exitoso resetea el estado failed
            except Exception:
                _log.exception("%s de plugin %d falló", op, index)

    def _apply_staged_change(self, op: str, index: int, plugin) -> None:
        if op == _OP_REPLACE:
            self._pipeline.replace_plugin(index, plugin)
        elif op == _OP_INSERT:
            self._pipeline.insert_plugin(index, plugin)
        elif op == _OP_REMOVE:
            self._pipeline.remove_plugin(index)

    def process(self, chunk: np.ndarray) -> np.ndarray:
        """Una excepción de plugin no mata al llamador: marca el estado y el
        audio sigue fluyendo sin procesar hasta que el usuario reinicie."""
        if self.bypass:
            return chunk
        if self.pipeline_failed:
            return chunk
        t0 = time.perf_counter()
        try:
            processed = self._pipeline.process(chunk)
        except Exception:
            _log.exception("pipeline crashed; el target continúa en passthrough")
            self.pipeline_failed = True
            return chunk
        self.latency_ms = (time.perf_counter() - t0) * 1000.0
        return processed
