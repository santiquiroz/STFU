import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)


def _use_tmp_user_store(tmp_path, monkeypatch):
    import stfu.api.routes.presets as pr
    from stfu.presets.store import PresetStore
    monkeypatch.setattr(pr, "_user_store", PresetStore(tmp_path / "presets"))
    return pr


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


def test_get_traversal_name_returns_404_not_500(tmp_path, monkeypatch):
    # FIX 1: un name con forma de traversal llega al handler y hace que
    # _user_store.get levante ValueError → debe mapearse a 404, no a 500.
    pr = _use_tmp_user_store(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as exc:
        pr.get_preset("..")
    assert exc.value.status_code == 404


def test_get_traversal_name_over_http_never_500(tmp_path, monkeypatch):
    # Mismo caso vía HTTP: sea que lo intercepte el routing o el handler,
    # nunca debe ser 500.
    _use_tmp_user_store(tmp_path, monkeypatch)
    r = client.get("/presets/%2e%2e")
    assert r.status_code != 500


def test_save_too_long_name_returns_400_not_500(tmp_path, monkeypatch):
    # FIX 2: PresetSpec se construye a mano; su ValidationError debe dar 400.
    _use_tmp_user_store(tmp_path, monkeypatch)
    long_name = "x" * 65
    r = client.post(f"/presets/{long_name}", json={"plugins": []})
    assert r.status_code == 400


def test_save_curated_name_rejected_409(tmp_path, monkeypatch):
    # FIX 3: guardar sobre un nombre curado se rechaza con 409 y no crea
    # un shadow de usuario (el listado sigue con un único "Gaming" builtin).
    _use_tmp_user_store(tmp_path, monkeypatch)
    r = client.post("/presets/Gaming", json={"plugins": [{"plugin_id": "gain", "parameters": {}}]})
    assert r.status_code == 409

    listing = client.get("/presets").json()
    gaming = [p for p in listing if p["name"] == "Gaming"]
    assert len(gaming) == 1
    assert gaming[0]["builtin"] is True
