from fastapi.testclient import TestClient
from stfu.main import app

client = TestClient(app)


def test_catalog_lists_builtins():
    r = client.get("/plugins")
    assert r.status_code == 200
    by_id = {p["plugin_id"]: p for p in r.json()}
    for pid in ("gain", "eq_parametric", "noise_gate", "compressor", "de_esser", "limiter"):
        assert pid in by_id
        assert "parameters" in by_id[pid]


def test_catalog_param_shape():
    r = client.get("/plugins")
    comp = next(p for p in r.json() if p["plugin_id"] == "compressor")
    ids = {pp["id"] for pp in comp["parameters"]}
    assert {"threshold_db", "ratio", "attack_ms", "release_ms", "makeup_db"} <= ids
    thr = next(pp for pp in comp["parameters"] if pp["id"] == "threshold_db")
    assert thr["type"] == "float" and "min" in thr and "max" in thr
