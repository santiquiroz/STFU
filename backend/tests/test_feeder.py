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


def test_stop_calls_engine_stop():
    with patch("stfu.api.routes.feeder.engine.stop") as stop:
        r = client.delete("/feeder/stop")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    stop.assert_called_once_with("feeder")


def test_parameter_active_returns_200():
    with patch("stfu.api.routes.feeder.engine.set_parameter", return_value=True) as sp:
        r = client.post("/feeder/parameter",
                        json={"plugin_index": 0, "parameter_id": "strength", "value": 0.9})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert sp.call_args.args == ("feeder", 0, "strength", 0.9)


def test_parameter_inactive_returns_404():
    with patch("stfu.api.routes.feeder.engine.set_parameter", return_value=False):
        r = client.post("/feeder/parameter",
                        json={"plugin_index": 0, "parameter_id": "strength", "value": 0.9})
    assert r.status_code == 404


def test_bypass_active_returns_200():
    with patch("stfu.api.routes.feeder.engine.set_bypass", return_value=True) as sb:
        r = client.post("/feeder/bypass", json={"on": True})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert sb.call_args.args == ("feeder", True)


def test_bypass_inactive_returns_404():
    with patch("stfu.api.routes.feeder.engine.set_bypass", return_value=False):
        r = client.post("/feeder/bypass", json={"on": True})
    assert r.status_code == 404


def test_parameter_out_of_range_returns_400():
    with patch("stfu.api.routes.feeder.engine.set_parameter", side_effect=IndexError("índice fuera de rango")):
        r = client.post("/feeder/parameter",
                        json={"plugin_index": 5, "parameter_id": "strength", "value": 0.9})
    assert r.status_code == 400


def test_parameter_bad_value_returns_400_not_500():
    with patch("stfu.api.routes.feeder.engine.set_parameter", side_effect=ValueError("valor no numérico")):
        r = client.post("/feeder/parameter",
                        json={"plugin_index": 0, "parameter_id": "strength", "value": 0.9})
    assert r.status_code == 400


def test_parameter_zero_division_returns_400_not_500():
    with patch("stfu.api.routes.feeder.engine.set_parameter", side_effect=ZeroDivisionError("division por cero")):
        r = client.post("/feeder/parameter",
                        json={"plugin_index": 0, "parameter_id": "strength", "value": 0.9})
    assert r.status_code == 400


def test_start_engine_failure_returns_500_without_leaking_detail():
    bridge = _dev(9, "STFU Audio Bridge", 2)
    with patch("stfu.api.routes.feeder.find_bridge_output", return_value=bridge), \
         patch("stfu.api.routes.feeder.engine.start", side_effect=RuntimeError("detalle interno crudo")):
        r = client.post("/feeder/start", json={"input_device_id": 1})
    assert r.status_code == 500
    assert "detalle interno crudo" not in r.json()["detail"]


def test_start_unknown_plugin_returns_400():
    bridge = _dev(9, "STFU Audio Bridge", 2)
    with patch("stfu.api.routes.feeder.find_bridge_output", return_value=bridge), \
         patch("stfu.api.routes.feeder.engine.start", side_effect=ValueError("Plugin desconocido: xyz")):
        r = client.post("/feeder/start", json={"input_device_id": 1})
    assert r.status_code == 400
    assert "Plugin desconocido" in r.json()["detail"]


def test_start_malformed_plugin_returns_422():
    bridge = _dev(9, "STFU Audio Bridge", 2)
    with patch("stfu.api.routes.feeder.find_bridge_output", return_value=bridge):
        r = client.post("/feeder/start",
                        json={"input_device_id": 1, "plugins": [{"parameters": {}}]})
    assert r.status_code == 422  # plugin_id requerido por el modelo


def test_status_includes_playback_active():
    with patch("stfu.api.routes.feeder.find_bridge_output", return_value=None):
        r = client.get("/feeder/status")
    assert r.status_code == 200
    assert "playback_active" in r.json()
