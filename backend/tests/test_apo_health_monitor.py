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


def test_check_now_populates_snapshot_and_logs_ok(caplog):
    import logging
    checks = [{"endpoint_guid": "g", "flow": "Capture", "state": "ok"}]
    mon = ApoHealthMonitor(lambda: checks, interval_s=999)
    assert mon._snapshot is None
    with caplog.at_level(logging.INFO):
        snapshot = mon.check_now()
    assert snapshot.needs_repair is False
    assert snapshot.endpoints == checks
    assert mon._snapshot is snapshot
    assert any("arranque" in r.message for r in caplog.records)


def test_check_now_warns_when_degraded_at_boot(caplog):
    import logging
    checks = [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}]
    mon = ApoHealthMonitor(lambda: checks, interval_s=999)
    with caplog.at_level(logging.WARNING):
        snapshot = mon.check_now()
    assert snapshot.needs_repair is True
    warnings = [r for r in caplog.records if "APO" in r.message or "apo" in r.message.lower()]
    assert len(warnings) == 1


def test_check_now_tolerates_check_exception():
    def boom():
        raise RuntimeError("registro ilegible")
    mon = ApoHealthMonitor(boom, interval_s=999)
    snapshot = mon.check_now()  # no debe propagar
    assert snapshot.needs_repair is False
    assert snapshot.endpoints == []


def test_recovery_reArms_the_warning(caplog):
    states = [
        [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}],
        [{"endpoint_guid": "g", "flow": "Capture", "state": "ok"}],
        [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}],
    ]

    def check():
        return states.pop(0)

    mon = ApoHealthMonitor(check, interval_s=999)
    import logging
    with caplog.at_level(logging.WARNING):
        mon._tick()  # 1ra degradación: loguea y arma _warned
        mon._tick()  # recovery: limpia _warned
        mon._tick()  # 2da degradación: re-arma → debe volver a loguear
    warnings = [r for r in caplog.records if "APO" in r.message or "apo" in r.message.lower()]
    assert len(warnings) == 2         # logueado en cada degradación, no solo la primera
    assert mon._warned is True
