from unittest.mock import patch
from fastapi.testclient import TestClient
from stfu.audio.devices import DeviceInfo
from stfu.main import app

client = TestClient(app)


def _dev(id, name, out):
    return DeviceInfo(id=id, name=name, channels_in=0, channels_out=out,
                      default_sample_rate=48000)


def test_status_reports_bridge_absent_by_default():
    with patch("stfu.api.routes.feeder.find_bridge_output", return_value=None):
        r = client.get("/feeder/status")
    assert r.status_code == 200
    assert r.json()["bridge_present"] is False
    assert r.json()["bridge_name"] == "STFU Audio Bridge"


def test_status_reports_bridge_present_when_installed():
    bridge = _dev(9, "STFU Audio Bridge", 2)
    with patch("stfu.api.routes.feeder.find_bridge_output", return_value=bridge):
        r = client.get("/feeder/status")
    assert r.json()["bridge_present"] is True
    assert r.json()["bridge_device_id"] == 9


def test_start_without_bridge_or_test_output_is_400():
    with patch("stfu.api.routes.feeder.find_bridge_output", return_value=None):
        r = client.post("/feeder/start", json={"input_device_id": 1})
    assert r.status_code == 400


def test_start_uses_bridge_when_present():
    bridge = _dev(9, "STFU Audio Bridge", 2)
    with patch("stfu.api.routes.feeder.find_bridge_output", return_value=bridge), \
         patch("stfu.api.routes.feeder.engine.start", return_value=40.0) as start:
        r = client.post("/feeder/start", json={"input_device_id": 1})
    assert r.status_code == 200
    assert r.json()["using_bridge"] is True
    assert r.json()["output_device_id"] == 9
    assert start.call_args.kwargs["output_device_id"] == 9


def test_start_falls_back_to_test_output_without_bridge():
    with patch("stfu.api.routes.feeder.find_bridge_output", return_value=None), \
         patch("stfu.api.routes.feeder.engine.start", return_value=40.0) as start:
        r = client.post("/feeder/start", json={"input_device_id": 1, "test_output_device_id": 5})
    assert r.status_code == 200
    assert r.json()["using_bridge"] is False
    assert start.call_args.kwargs["output_device_id"] == 5


def test_find_bridge_output_matches_by_name():
    from stfu.audio import devices
    fake = [_dev(1, "Altavoces (FiiO)", 2), _dev(9, "STFU Audio Bridge", 2)]
    with patch.object(devices, "list_devices", return_value=fake):
        b = devices.find_bridge_output()
    assert b is not None and b.id == 9
