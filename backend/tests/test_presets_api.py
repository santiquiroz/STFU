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


def test_delete_accented_curated_rejected():
    # regresión: el lookup curado por stem de archivo ("musica.json") no
    # matcheaba el name mostrado ("Música") salvo por accidente de
    # case-insensitivity de NTFS en nombres ASCII — esto lo fija en firme.
    got = client.get("/presets/Música")
    assert got.status_code == 200
    assert got.json()["name"] == "Música"

    r = client.delete("/presets/Música")
    assert r.status_code == 409

    r2 = client.delete("/presets/Reunión")
    assert r2.status_code == 409
