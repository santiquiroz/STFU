"""Vigila el registro del APO en segundo plano. Un cumulative update de
Windows 11 24H2 puede desactivar el APO en silencio; este monitor lo detecta y
lo loguea (no repara solo — la reparación eleva y la decide el usuario).

Publica un snapshot cacheado de la salud en cada ciclo (~60s) para que
endpoints de alta frecuencia (GET /status, WS de metering a ~10Hz) no
disparen lecturas de winreg en cada request — ver `get_snapshot()`."""
from dataclasses import dataclass
import logging
import threading

from stfu.apo.health import check_registrations

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApoHealthSnapshot:
    needs_repair: bool
    endpoints: list[dict]


_NEUTRAL_SNAPSHOT = ApoHealthSnapshot(needs_repair=False, endpoints=[])


class ApoHealthMonitor:
    def __init__(self, check_fn, interval_s: float = 60.0) -> None:
        self._check = check_fn
        self._interval = interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._warned = False
        self._snapshot: ApoHealthSnapshot | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def get_snapshot(self) -> ApoHealthSnapshot:
        """Snapshot cacheado del último ciclo. Antes del primer ciclo hace un
        único cómputo perezoso (y lo cachea) en vez de golpear winreg en cada
        request — así /status y la WS de metering nunca leen el registro
        directamente."""
        if self._snapshot is None:
            self._snapshot = self._compute_snapshot() or _NEUTRAL_SNAPSHOT
        return self._snapshot

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            self._tick()

    def _tick(self) -> None:
        snapshot = self._compute_snapshot()
        if snapshot is None:
            return
        self._snapshot = snapshot
        self._handle_degradation(snapshot.endpoints)

    def _compute_snapshot(self) -> ApoHealthSnapshot | None:
        try:
            checks = self._check()
        except Exception:
            _log.exception("health-check del APO falló")
            return None
        return ApoHealthSnapshot(
            needs_repair=any(c["state"] != "ok" for c in checks),
            endpoints=checks,
        )

    def _handle_degradation(self, checks: list[dict]) -> None:
        degraded = [c for c in checks if c["state"] != "ok"]
        if not degraded:
            self._warned = False
            return
        if not self._warned:
            _log.warning("APO degradado en %d endpoint(s): %s — usar /apo/repair",
                         len(degraded), [(c["flow"], c["state"]) for c in degraded])
            self._warned = True


apo_health_monitor = ApoHealthMonitor(check_registrations)
