"""F3 finding I2: /status y la WS de metering deben leer el snapshot cacheado
del ApoHealthMonitor en vez de disparar lecturas de winreg en cada request."""
from unittest.mock import MagicMock, patch

from stfu.apo.health_monitor import ApoHealthSnapshot, apo_health_monitor
from stfu.main import _status_payload

_DEGRADED_ENDPOINTS = [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}]


def test_status_payload_reads_cached_snapshot_without_calling_check():
    mock_check = MagicMock(side_effect=AssertionError("no debe leer winreg con snapshot cacheado"))
    fake_snapshot = ApoHealthSnapshot(needs_repair=True, endpoints=_DEGRADED_ENDPOINTS)
    with patch.object(apo_health_monitor, "_check", mock_check), \
         patch.object(apo_health_monitor, "_snapshot", fake_snapshot):
        payload = _status_payload()
    mock_check.assert_not_called()
    assert payload["apo_health"] == {"needs_repair": True, "endpoints": _DEGRADED_ENDPOINTS}


def test_status_payload_before_first_tick_computes_once_and_caches():
    calls = {"n": 0}

    def check():
        calls["n"] += 1
        return [{"endpoint_guid": "g", "flow": "Capture", "state": "ok"}]

    with patch.object(apo_health_monitor, "_snapshot", None), \
         patch.object(apo_health_monitor, "_check", check):
        first = _status_payload()
        second = _status_payload()

    assert calls["n"] == 1
    expected = {"needs_repair": False, "endpoints": [{"endpoint_guid": "g", "flow": "Capture", "state": "ok"}]}
    assert first["apo_health"] == expected
    assert second["apo_health"] == expected


def test_status_payload_before_first_tick_falls_back_to_neutral_on_error():
    with patch.object(apo_health_monitor, "_snapshot", None), \
         patch.object(apo_health_monitor, "_check", side_effect=RuntimeError("registro ilegible")):
        payload = _status_payload()
    assert payload["apo_health"] == {"needs_repair": False, "endpoints": []}


def test_monitor_tick_publishes_snapshot_consumed_by_status_payload():
    checks = [{"endpoint_guid": "g", "flow": "Render", "state": "endpoint-missing"}]
    # _tick muta _snapshot/_warned in-place; congelar sus valores actuales como
    # "new" para que patch.object los restaure al salir y no filtren estado
    # al singleton compartido entre tests.
    with patch.object(apo_health_monitor, "_check", return_value=checks), \
         patch.object(apo_health_monitor, "_snapshot", apo_health_monitor._snapshot), \
         patch.object(apo_health_monitor, "_warned", apo_health_monitor._warned):
        apo_health_monitor._tick()
        payload = _status_payload()
    assert payload["apo_health"] == {"needs_repair": True, "endpoints": checks}
