"""Ciclo de vida de los pipe servers que alimentan al STFU APO (audiodg)."""
import threading

from stfu.apo.constants import PIPE_BY_FLOW
from stfu.apo.pipe_server import ApoPipeServer


class ApoEngine:
    def __init__(self) -> None:
        self._servers: dict[str, ApoPipeServer] = {}
        self._lock = threading.Lock()

    def start(self, flow: str, plugin_configs: list[dict]) -> None:
        from stfu.audio.engine import _build_pipeline
        from stfu.core.audio_format import AudioFormat
        pipe_name = PIPE_BY_FLOW[flow]
        pipeline = _build_pipeline(plugin_configs)
        # warmup: carga modelos AQUÍ (segundos) y no en el primer frame del
        # APO; el server recompila si el formato real difiere (rápido, el
        # modelo ya está cacheado en el plugin)
        pipeline.compile(AudioFormat(48000, 2, 480))
        with self._lock:
            old = self._servers.pop(flow, None)
            if old:
                old.stop()
            server = ApoPipeServer(pipe_name, pipeline)
            server.start()
            self._servers[flow] = server

    def stop(self, flow: str) -> None:
        with self._lock:
            server = self._servers.pop(flow, None)
        if server:
            server.stop()

    def stop_all(self) -> None:
        with self._lock:
            servers = list(self._servers.values())
            self._servers.clear()
        for s in servers:
            s.stop()

    def status(self) -> dict[str, bool]:
        with self._lock:
            return {flow: True for flow in self._servers}


apo_engine = ApoEngine()
