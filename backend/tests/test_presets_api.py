from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)


def test_list_includes_curated():
    r = client.get("/presets")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    for expected in ("Gaming", "Reunión", "Streaming", "Podcast", "Música", "Accesibilidad"):
        assert expected in names


def test_curated_marked_builtin():
    r = client.get("/presets")
    gaming = next(p for p in r.json() if p["name"] == "Gaming")
    assert gaming["builtin"] is True
    assert isinstance(gaming["plugins"], list) and len(gaming["plugins"]) >= 1


def test_save_and_get_user_preset(tmp_path, monkeypatch):
    # el store de usuario debe apuntar a un dir temporal para no ensuciar ~/.stfu
    import stfu.api.routes.presets as pr
    from stfu.presets.store import PresetStore
    monkeypatch.setattr(pr, "_user_store", PresetStore(tmp_path / "presets"))
    r = client.post("/presets/mi-preset", json={"plugins": [{"plugin_id": "gain", "parameters": {}}]})
    assert r.status_code == 200
    got = client.get("/presets/mi-preset")
    assert got.status_code == 200
    assert got.json()["plugins"][0]["plugin_id"] == "gain"


def test_delete_curated_rejected():
    r = client.delete("/presets/Gaming")
    assert r.status_code in (400, 409)
