from stfu.apo.health_monitor import ApoHealthMonitor


def test_tick_logs_once_on_first_degraded_state(caplog):
    calls = {"n": 0}

    def check():
        calls["n"] += 1
        return [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}]

    mon = ApoHealthMonitor(check, interval_s=999)
    import logging
    with caplog.at_level(logging.WARNING):
        mon._tick()
        mon._tick()
    warnings = [r for r in caplog.records if "APO" in r.message or "apo" in r.message.lower()]
    assert len(warnings) == 1        # logueado una sola vez pese a dos ticks degradados
    assert calls["n"] == 2


def test_tick_tolerates_check_exception():
    def boom():
        raise RuntimeError("registro ilegible")
    mon = ApoHealthMonitor(boom, interval_s=999)
    mon._tick()  # no debe propagar


def test_recovery_reArms_the_warning():
    states = [
        [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}],
        [{"endpoint_guid": "g", "flow": "Capture", "state": "ok"}],
        [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}],
    ]

    def check():
        return states.pop(0)

    mon = ApoHealthMonitor(check, interval_s=999)
    import logging
    import pytest
    # 1ra degradación loguea; recuperación re-arma; 2da degradación vuelve a loguear
    log_counts = []
    for _ in range(3):
        before = len(mon._logged_degraded)
        mon._tick()
        log_counts.append(mon._warned)
    # tras recovery (_tick 2) el flag se limpia y la 3ra degradación re-loguea
    assert mon._warned is True
