from unittest.mock import patch
from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)

_ENDPOINTS = [{"endpoint_guid": "g", "flow": "Capture", "state": "deactivated"}]


def test_apo_health_route():
    with patch("stfu.api.routes.apo.check_registrations", return_value=_ENDPOINTS), \
         patch("stfu.api.routes.apo.health_needs_repair", return_value=True):
        r = client.get("/apo/health")
    assert r.status_code == 200
    body = r.json()
    assert body["needs_repair"] is True
    assert body["endpoints"] == _ENDPOINTS


def test_status_includes_apo_health():
    r = client.get("/status")
    assert r.status_code == 200
    assert "apo_health" in r.json()
