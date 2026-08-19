from unittest.mock import patch
from stfu.apo import health


_BACKUPS = {
    "{AAAA1111-2222-3333-4444-555566667777}|Capture": ["{OLD-MIC-CLSID}"],
    "{BBBB1111-2222-3333-4444-555566667777}|Render": [],
}


def _patch(status_map, missing=()):
    def fake_status(guid, flow, clsid=None):
        key = f"{guid}|{flow}"
        if key in missing:
            return {"registered": False, "clsid": None}
        return status_map.get(key, {"registered": False, "clsid": None})
    return fake_status


def test_all_ok():
    status = {
        "{AAAA1111-2222-3333-4444-555566667777}|Capture": {"registered": True, "clsid": "x"},
        "{BBBB1111-2222-3333-4444-555566667777}|Render": {"registered": True, "clsid": "y"},
    }
    with patch.object(health, "_load_backups", return_value=_BACKUPS), \
         patch.object(health, "get_apo_status", side_effect=_patch(status)), \
         patch.object(health, "_endpoint_exists", return_value=True):
        result = health.check_registrations()
    assert all(r["state"] == "ok" for r in result)
    assert health_states(result) == {"ok"}


def test_deactivated_after_update():
    status = {
        "{AAAA1111-2222-3333-4444-555566667777}|Capture": {"registered": False, "clsid": None},
        "{BBBB1111-2222-3333-4444-555566667777}|Render": {"registered": True, "clsid": "y"},
    }
    with patch.object(health, "_load_backups", return_value=_BACKUPS), \
         patch.object(health, "get_apo_status", side_effect=_patch(status)), \
         patch.object(health, "_endpoint_exists", return_value=True):
        result = health.check_registrations()
        by_flow = {r["flow"]: r["state"] for r in result}
    assert by_flow["Capture"] == "deactivated"
    assert by_flow["Render"] == "ok"


def test_endpoint_missing_after_driver_reinstall():
    status = {
        "{AAAA1111-2222-3333-4444-555566667777}|Capture": {"registered": False, "clsid": None},
    }
    with patch.object(health, "_load_backups", return_value=_BACKUPS), \
         patch.object(health, "get_apo_status", side_effect=_patch(status)), \
         patch.object(health, "_endpoint_exists", side_effect=lambda g, f: not g.startswith("{AAAA")):
        result = health.check_registrations()
        by_flow = {r["flow"]: r["state"] for r in result}
    assert by_flow["Capture"] == "endpoint-missing"


def test_needs_repair_true_when_any_deactivated():
    with patch.object(health, "check_registrations", return_value=[
        {"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"},
        {"endpoint_guid": "h", "flow": "Render", "state": "ok"},
    ]):
        assert health.needs_repair() is True


def test_needs_repair_false_when_all_ok():
    with patch.object(health, "check_registrations", return_value=[
        {"endpoint_guid": "g", "flow": "Capture", "state": "ok"},
    ]):
        assert health.needs_repair() is False


def health_states(result):
    return {r["state"] for r in result}
