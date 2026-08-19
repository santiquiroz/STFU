from collections import deque

_EMA_ALPHA = 0.1


class StageMetrics:
    """Métricas de una etapa del pipeline.

    Un solo hilo escribe (el worker del pipeline); las lecturas desde el hilo
    de API son snapshots sin lock — GIL + deque(maxlen) lo hacen seguro con
    un único escritor. El p95 se calcula al leer, nunca en el hot path.
    """

    def __init__(self, name: str, budget_ms: float, window: int = 256) -> None:
        self.name = name
        self.budget_ms = budget_ms
        self._samples: deque[float] = deque(maxlen=window)
        self._ema_ms: float = 0.0
        self._overbudget: int = 0

    def record(self, elapsed_ms: float) -> None:
        self._samples.append(elapsed_ms)
        self._ema_ms = (
            elapsed_ms if self._ema_ms == 0.0
            else _EMA_ALPHA * elapsed_ms + (1.0 - _EMA_ALPHA) * self._ema_ms
        )
        if elapsed_ms > self.budget_ms:
            self._overbudget += 1

    def snapshot(self) -> dict:
        ordered = sorted(self._samples)
        p95 = ordered[int(len(ordered) * 0.95)] if ordered else 0.0
        return {
            "stage": self.name,
            "ema_ms": round(self._ema_ms, 3),
            "p95_ms": round(p95, 3),
            "budget_ms": self.budget_ms,
            "overbudget": self._overbudget,
        }
