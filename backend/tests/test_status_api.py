from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)


def test_status_shape():
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"status", "latency_ms", "active", "streams", "apo"}


def test_metering_ws_sends_same_shape_as_status():
    with client.websocket_connect("/ws/metering") as ws:
        msg = ws.receive_json()
    assert set(msg) >= {"status", "latency_ms", "active", "streams", "apo"}
