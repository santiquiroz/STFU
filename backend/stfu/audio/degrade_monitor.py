"""Degradación automática bajo presión (spec §3.5): si el stage del modelo NC
sostiene p95 > budget, se baja al siguiente tier instalado más liviano.
La cancelación NUNCA se apaga por carga — a diferencia de Krisp."""
import logging
import threading

_log = logging.getLogger(__name__)

_TIER_ORDER = ["quality", "default", "floor"]  # de más pesado a más liviano


def _next_lighter_model(model_id: str, catalog: list[dict]) -> str | None:
    by_id = {m["id"]: m for m in catalog}
    current = by_id.get(model_id)
    if current is None or current["tier"] not in _TIER_ORDER:
        return None
    for tier in _TIER_ORDER[_TIER_ORDER.index(current["tier"]) + 1:]:
        candidate = next(
            (m for m in catalog if m["tier"] == tier and m["installed"] and m["id"] != model_id),
            None,
        )
        if candidate:
            return candidate["id"]
    return None


class DegradeMonitor:
    def __init__(self, engine, catalog_fn, interval_s: float = 5.0,
                 strikes_to_degrade: int = 3, cooldown_ticks: int = 24) -> None:
        self._engine = engine
        self._catalog_fn = catalog_fn
        self._interval = interval_s
        self._strikes_needed = strikes_to_degrade
        self._cooldown_ticks = cooldown_ticks
        self._strikes: dict[str, int] = {}
        self._cooldown: dict[str, int] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

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
            try:
                self._tick()
            except Exception:
                _log.exception("degrade monitor tick falló")

    def _tick(self) -> None:
        catalog = self._catalog_fn()
        model_names = {m["name"]: m["id"] for m in catalog}
        for target, stats in self._engine.get_stats().items():
            self._check_target(target, stats, model_names, catalog)

    def _check_target(self, target: str, stats: dict,
                      model_names: dict[str, str], catalog: list[dict]) -> None:
        if self._cooldown.get(target, 0) > 0:
            self._cooldown[target] -= 1
            return
        model_stages = [s for s in stats.get("stages", []) if s["stage"] in model_names]
        over = any(s["p95_ms"] > s["budget_ms"] for s in model_stages)
        if not over:
            self._strikes[target] = 0
            return
        self._strikes[target] = self._strikes.get(target, 0) + 1
        if self._strikes[target] < self._strikes_needed:
            return
        self._degrade(target, model_stages, model_names, catalog)

    def _degrade(self, target: str, model_stages: list[dict],
                 model_names: dict[str, str], catalog: list[dict]) -> None:
        current_id = model_names[model_stages[0]["stage"]]
        lighter = _next_lighter_model(current_id, catalog)
        self._strikes[target] = 0
        if lighter is None:
            _log.warning("%s: %s sobre budget pero ya es el tier más liviano", target, current_id)
            self._cooldown[target] = self._cooldown_ticks
            return
        _log.warning("%s: degradando %s → %s por presión sostenida", target, current_id, lighter)
        if self._engine.swap_model(target, lighter):
            self._cooldown[target] = self._cooldown_ticks
