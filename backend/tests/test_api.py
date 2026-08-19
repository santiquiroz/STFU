from unittest.mock import patch
from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)


def test_status_ok():
    r = client.get("/status")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "latency_ms" in r.json()


def test_devices_nonempty():
    r = client.get("/devices")
    assert r.status_code == 200
    assert len(r.json()) > 0
    assert "name" in r.json()[0]


def test_models_is_list():
    r = client.get("/models")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_backends_includes_cpu():
    r = client.get("/backends")
    assert r.status_code == 200
    ids = [b["id"] for b in r.json()]
    assert "cpu" in ids


def test_pipeline_mic_accepts_config():
    r = client.post("/pipeline/mic", json={
        "plugins": [],
        "input_device_id": 0,
        "output_device_id": 0,
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_set_parameter_on_inactive_pipeline_returns_404():
    r = client.post(
        "/pipeline/mic/parameter",
        json={"plugin_index": 0, "parameter_id": "strength", "value": 0.5},
    )
    assert r.status_code == 404


def test_set_parameter_invalid_target_returns_400():
    r = client.post(
        "/pipeline/foo/parameter",
        json={"plugin_index": 0, "parameter_id": "strength", "value": 0.5},
    )
    assert r.status_code == 400


def test_set_bypass_on_inactive_pipeline_returns_404():
    r = client.post("/pipeline/mic/bypass", json={"on": True})
    assert r.status_code == 404


def test_set_bypass_invalid_target_returns_400():
    r = client.post("/pipeline/foo/bypass", json={"on": True})
    assert r.status_code == 400


def test_set_parameter_bad_value_returns_400_not_500():
    with patch("stfu.api.routes.pipeline.engine.set_parameter", side_effect=ValueError("valor no numérico")):
        r = client.post(
            "/pipeline/mic/parameter",
            json={"plugin_index": 0, "parameter_id": "strength", "value": 0.5},
        )
    assert r.status_code == 400


def test_set_parameter_zero_division_returns_400_not_500():
    with patch("stfu.api.routes.pipeline.engine.set_parameter", side_effect=ZeroDivisionError("division por cero")):
        r = client.post(
            "/pipeline/mic/parameter",
            json={"plugin_index": 0, "parameter_id": "strength", "value": 0.5},
        )
    assert r.status_code == 400


def test_set_parameter_type_error_returns_400_not_500():
    with patch("stfu.api.routes.pipeline.engine.set_parameter", side_effect=TypeError("tipo invalido")):
        r = client.post(
            "/pipeline/mic/parameter",
            json={"plugin_index": 0, "parameter_id": "strength", "value": 0.5},
        )
    assert r.status_code == 400
