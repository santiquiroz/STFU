from fastapi.testclient import TestClient
from unittest.mock import patch
from stfu.main import app

client = TestClient(app)


def test_apo_status_not_registered():
    with patch("stfu.api.routes.apo.get_apo_status", return_value={"registered": False, "clsid": None}):
        with patch("stfu.api.routes.apo.find_endpoint_guid", return_value="fake-guid"):
            resp = client.get("/apo/status/Capture?device_name=TestMic")
    assert resp.status_code == 200
    assert resp.json()["registered"] is False


def test_apo_register_returns_400_when_device_not_found():
    with patch("stfu.api.routes.apo.find_endpoint_guid", return_value=None):
        resp = client.post("/apo/register", json={
            "flow": "Capture",
            "device_name": "NonExistentDevice",
            "apo_clsid": "{00000000-0000-0000-0000-000000000001}",
        })
    assert resp.status_code == 400
