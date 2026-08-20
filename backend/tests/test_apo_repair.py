from unittest.mock import patch
from stfu.apo import register


def test_repair_reregisters_deactivated_only():
    checks = [
        {"endpoint_guid": "{G1}", "flow": "Capture", "state": "deactivated"},
        {"endpoint_guid": "{G2}", "flow": "Render", "state": "ok"},
        {"endpoint_guid": "{G3}", "flow": "Capture", "state": "endpoint-missing"},
    ]
    with patch("stfu.apo.register._check_registrations_for_repair", return_value=checks), \
         patch("stfu.apo.register.register_apo") as reg, \
         patch("stfu.apo.register._restart_audio_service"):
        report = register.repair_registrations()
    # solo el deactivated se re-registra
    reg.assert_called_once()
    args, kwargs = reg.call_args
    assert args[0] == "{G1}" and args[1] == "Capture"
    assert kwargs["restart_service"] is False
    by_guid = {r["endpoint_guid"]: r["result"] for r in report}
    assert by_guid["{G1}"] == "repaired"
    assert by_guid["{G2}"] == "ok"
    assert by_guid["{G3}"] == "endpoint-missing"


def test_repair_reports_failure_without_raising():
    checks = [{"endpoint_guid": "{G1}", "flow": "Capture", "state": "deactivated"}]
    with patch("stfu.apo.register._check_registrations_for_repair", return_value=checks), \
         patch("stfu.apo.register.register_apo", side_effect=OSError("regsvr32 falló")), \
         patch("stfu.apo.register._restart_audio_service") as restart:
        report = register.repair_registrations()
    assert report[0]["result"] == "error"
    assert "regsvr32" in report[0]["detail"]
    # ningún repair exitoso → no hace falta reiniciar el servicio
    restart.assert_not_called()


def test_repair_restarts_audio_service_once_for_whole_batch():
    checks = [
        {"endpoint_guid": "{G1}", "flow": "Capture", "state": "deactivated"},
        {"endpoint_guid": "{G2}", "flow": "Render", "state": "deactivated"},
    ]
    with patch("stfu.apo.register._check_registrations_for_repair", return_value=checks), \
         patch("stfu.apo.register.register_apo") as reg, \
         patch("stfu.apo.register._restart_audio_service") as restart:
        register.repair_registrations()
    assert reg.call_count == 2
    for _, kwargs in reg.call_args_list:
        assert kwargs["restart_service"] is False
    restart.assert_called_once()


def test_repair_skips_restart_when_nothing_repaired():
    checks = [{"endpoint_guid": "{G1}", "flow": "Render", "state": "ok"}]
    with patch("stfu.apo.register._check_registrations_for_repair", return_value=checks), \
         patch("stfu.apo.register.register_apo") as reg, \
         patch("stfu.apo.register._restart_audio_service") as restart:
        register.repair_registrations()
    reg.assert_not_called()
    restart.assert_not_called()
