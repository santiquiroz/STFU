from unittest.mock import patch, call
from stfu.apo import register


def test_repair_reregisters_deactivated_only():
    checks = [
        {"endpoint_guid": "{G1}", "flow": "Capture", "state": "deactivated"},
        {"endpoint_guid": "{G2}", "flow": "Render", "state": "ok"},
        {"endpoint_guid": "{G3}", "flow": "Capture", "state": "endpoint-missing"},
    ]
    with patch("stfu.apo.register.check_registrations", return_value=checks), \
         patch("stfu.apo.register.register_apo") as reg:
        report = register.repair_registrations()
    # solo el deactivated se re-registra
    reg.assert_called_once()
    args = reg.call_args[0]
    assert args[0] == "{G1}" and args[1] == "Capture"
    by_guid = {r["endpoint_guid"]: r["result"] for r in report}
    assert by_guid["{G1}"] == "repaired"
    assert by_guid["{G2}"] == "ok"
    assert by_guid["{G3}"] == "endpoint-missing"


def test_repair_reports_failure_without_raising():
    checks = [{"endpoint_guid": "{G1}", "flow": "Capture", "state": "deactivated"}]
    with patch("stfu.apo.register.check_registrations", return_value=checks), \
         patch("stfu.apo.register.register_apo", side_effect=OSError("regsvr32 falló")):
        report = register.repair_registrations()
    assert report[0]["result"] == "error"
    assert "regsvr32" in report[0]["detail"]
