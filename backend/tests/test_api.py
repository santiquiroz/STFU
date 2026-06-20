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
