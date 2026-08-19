from stfu.core.telemetry import StageMetrics


def test_snapshot_empty():
    m = StageMetrics("nc", budget_ms=20.0)
    snap = m.snapshot()
    assert snap == {"stage": "nc", "ema_ms": 0.0, "p95_ms": 0.0, "budget_ms": 20.0, "overbudget": 0}


def test_ema_converges_toward_recent_values():
    m = StageMetrics("nc", budget_ms=20.0)
    for _ in range(200):
        m.record(10.0)
    assert abs(m.snapshot()["ema_ms"] - 10.0) < 0.1


def test_p95_over_window():
    m = StageMetrics("nc", budget_ms=20.0, window=100)
    for v in range(100):  # 0..99 ms
        m.record(float(v))
    assert m.snapshot()["p95_ms"] == 95.0


def test_overbudget_counts_samples_above_budget():
    m = StageMetrics("nc", budget_ms=20.0)
    m.record(19.0)
    m.record(21.0)
    m.record(25.0)
    assert m.snapshot()["overbudget"] == 2


def test_window_is_rolling():
    m = StageMetrics("nc", budget_ms=1000.0, window=10)
    for _ in range(10):
        m.record(100.0)
    for _ in range(10):
        m.record(1.0)  # desplaza todas las muestras viejas
    assert m.snapshot()["p95_ms"] == 1.0
