"""Endpoints /feeder/plugin (insert) y /feeder/plugin/{index} (remove): ver
AudioEngine.insert_plugin/remove_plugin. Mismo patrón de mocking que
test_feeder.py."""
from unittest.mock import patch
from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)


def test_insert_plugin_active_returns_ok_and_latency():
    with patch("stfu.api.routes.feeder.engine.insert_plugin", return_value=42.0) as ins:
        r = client.post("/feeder/plugin", json={"index": 1, "plugin_id": "gain", "parameters": {}})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "latency_ms": 42.0}
    assert ins.call_args.args == ("feeder", 1, {"plugin_id": "gain", "parameters": {}})


def test_insert_plugin_inactive_returns_404():
    with patch("stfu.api.routes.feeder.engine.insert_plugin", return_value=None):
        r = client.post("/feeder/plugin", json={"index": 0, "plugin_id": "gain", "parameters": {}})
    assert r.status_code == 404


def test_insert_plugin_bad_index_returns_400():
    with patch(
        "stfu.api.routes.feeder.engine.insert_plugin",
        side_effect=IndexError("insert index 9 fuera de rango"),
    ):
        r = client.post("/feeder/plugin", json={"index": 9, "plugin_id": "gain", "parameters": {}})
    assert r.status_code == 400


def test_insert_plugin_unknown_plugin_returns_400():
    with patch(
        "stfu.api.routes.feeder.engine.insert_plugin",
        side_effect=ValueError("Plugin desconocido: xyz"),
    ):
        r = client.post("/feeder/plugin", json={"index": 0, "plugin_id": "xyz", "parameters": {}})
    assert r.status_code == 400
    assert "Plugin desconocido" in r.json()["detail"]


def test_insert_plugin_malformed_body_returns_422():
    r = client.post("/feeder/plugin", json={"index": 0})  # plugin_id requerido
    assert r.status_code == 422


def test_remove_plugin_active_returns_ok_and_latency():
    with patch("stfu.api.routes.feeder.engine.remove_plugin", return_value=10.0) as rem:
        r = client.delete("/feeder/plugin/1")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "latency_ms": 10.0}
    rem.assert_called_once_with("feeder", 1)


def test_remove_plugin_inactive_returns_404():
    with patch("stfu.api.routes.feeder.engine.remove_plugin", return_value=None):
        r = client.delete("/feeder/plugin/0")
    assert r.status_code == 404


def test_remove_plugin_bad_index_returns_400():
    with patch(
        "stfu.api.routes.feeder.engine.remove_plugin",
        side_effect=IndexError("remove index 9 fuera de rango"),
    ):
        r = client.delete("/feeder/plugin/9")
    assert r.status_code == 400
