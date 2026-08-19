from stfu.audio.degrade_monitor import DegradeMonitor, _next_lighter_model


_CATALOG = [
    {"id": "dpdfnet2-48k-hr", "name": "DPDFNet 48kHz HR", "tier": "quality", "installed": True},
    {"id": "dpdfnet2-16k", "name": "DPDFNet2", "tier": "default", "installed": True},
    {"id": "fastenhancer-tiny", "name": "FastEnhancer Tiny", "tier": "floor", "installed": True},
    {"id": "gtcrn", "name": "GTCRN", "tier": "floor", "installed": False},
]


def test_next_lighter_model_picks_installed_lower_tier():
    assert _next_lighter_model("dpdfnet2-48k-hr", _CATALOG) == "dpdfnet2-16k"
    assert _next_lighter_model("dpdfnet2-16k", _CATALOG) == "fastenhancer-tiny"


def test_next_lighter_model_none_at_floor():
    assert _next_lighter_model("fastenhancer-tiny", _CATALOG) is None


class _FakeEngine:
    def __init__(self, over_budget: bool):
        p95 = 30.0 if over_budget else 5.0
        self._stats = {"mic": {"stages": [
            {"stage": "DPDFNet 48kHz HR", "p95_ms": p95, "budget_ms": 20.0, "ema_ms": p95, "overbudget": 0},
        ]}}
        self.swaps: list[tuple[str, str]] = []

    def get_stats(self):
        return self._stats

    def active_model_ids(self, target):
        return {"dpdfnet2-48k-hr"}

    def swap_model(self, target, model_id, device="auto"):
        self.swaps.append((target, model_id))
        return True


def test_degrades_after_consecutive_strikes():
    eng = _FakeEngine(over_budget=True)
    mon = DegradeMonitor(eng, lambda: _CATALOG, strikes_to_degrade=3)
    for _ in range(3):
        mon._tick()
    assert eng.swaps == [("mic", "dpdfnet2-16k")]


def test_healthy_stage_resets_strikes():
    eng = _FakeEngine(over_budget=True)
    mon = DegradeMonitor(eng, lambda: _CATALOG, strikes_to_degrade=3)
    mon._tick()
    mon._tick()
    eng._stats["mic"]["stages"][0]["p95_ms"] = 5.0  # se recuperó
    mon._tick()
    eng._stats["mic"]["stages"][0]["p95_ms"] = 30.0
    mon._tick()
    assert eng.swaps == []  # nunca juntó 3 seguidos


def test_cooldown_blocks_double_degrade():
    eng = _FakeEngine(over_budget=True)
    mon = DegradeMonitor(eng, lambda: _CATALOG, strikes_to_degrade=1, cooldown_ticks=10)
    mon._tick()
    mon._tick()
    assert len(eng.swaps) == 1
