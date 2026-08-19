"""Vigila el registro del APO en segundo plano. Un cumulative update de
Windows 11 24H2 puede desactivar el APO en silencio; este monitor lo detecta y
lo loguea (no repara solo — la reparación eleva y la decide el usuario)."""
import logging
import threading

_log = logging.getLogger(__name__)


class ApoHealthMonitor:
    def __init__(self, check_fn, interval_s: float = 60.0) -> None:
        self._check = check_fn
        self._interval = interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._warned = False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            self._tick()

    def _tick(self) -> None:
        try:
            checks = self._check()
        except Exception:
            _log.exception("health-check del APO falló")
            return
        degraded = [c for c in checks if c["state"] != "ok"]
        if not degraded:
            self._warned = False
            return
        if not self._warned:
            _log.warning("APO degradado en %d endpoint(s): %s — usar /apo/repair",
                         len(degraded), [(c["flow"], c["state"]) for c in degraded])
            self._warned = True
