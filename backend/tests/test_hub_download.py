import hashlib
import json
import pytest
from pathlib import Path
from stfu.hub.manager import HubManager, Sha256Mismatch
from stfu.hub.registry import ModelRegistry


def _curated_dir(tmp_path, model_bytes: bytes) -> Path:
    curated = tmp_path / "curated"
    curated.mkdir()
    manifest = {
        "id": "fastenhancer-tiny", "name": "FastEnhancer Tiny", "version": "1.0",
        "plugin_class": "stfu.plugins.onnx_streaming.OnnxStreamingPlugin",
        "source": "url", "file": "model.onnx",
        "url": "https://example.com/model.onnx",
        "sha256": hashlib.sha256(model_bytes).hexdigest(),
        "preferred_format": {"sample_rate": 16000, "channels": 1, "chunk_samples": 256},
        "size_mb": 0.01, "algorithmic_latency_ms": 16.0,
        "tier": "floor", "license": "MIT",
        "io_spec": {
            "audio_input": {"name": "audio", "shape": [1, "chunk"]},
            "audio_output": "enhanced", "states": [],
        },
    }
    (curated / "fastenhancer-tiny.json").write_text(json.dumps(manifest))
    return curated


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    model_bytes = b"fake onnx bytes"
    registry = ModelRegistry(tmp_path / "models")
    manager = HubManager(registry, _curated_dir(tmp_path, model_bytes))
    monkeypatch.setattr(
        manager, "_fetch", lambda manifest, dest, on_progress=None: dest.write_bytes(model_bytes)
    )
    return manager


def test_catalog_lists_curated_not_installed(hub):
    cat = hub.catalog()
    assert len(cat) == 1
    assert cat[0]["id"] == "fastenhancer-tiny"
    assert cat[0]["installed"] is False


def test_download_verifies_and_registers(hub):
    path = hub.download("fastenhancer-tiny")
    assert path.exists()
    assert hub.catalog()[0]["installed"] is True


def test_download_rejects_sha_mismatch(hub, monkeypatch):
    monkeypatch.setattr(
        hub, "_fetch", lambda manifest, dest, on_progress=None: dest.write_bytes(b"tampered")
    )
    with pytest.raises(Sha256Mismatch):
        hub.download("fastenhancer-tiny")
    assert hub.catalog()[0]["installed"] is False


def test_delete_rejects_active_model(hub):
    hub.download("fastenhancer-tiny")
    with pytest.raises(ValueError, match="activo"):
        hub.delete("fastenhancer-tiny", active_ids={"fastenhancer-tiny"})


def test_delete_removes_installed(hub):
    hub.download("fastenhancer-tiny")
    hub.delete("fastenhancer-tiny", active_ids=set())
    assert hub.catalog()[0]["installed"] is False


def test_delete_rejects_dotdot_traversal(hub, tmp_path):
    sentinel = tmp_path / "x"
    sentinel.mkdir()
    (sentinel / "canary.txt").write_text("intact")
    with pytest.raises(ValueError):
        hub.delete("../x", active_ids=set())
    assert sentinel.exists()
    assert (sentinel / "canary.txt").read_text() == "intact"


def test_delete_rejects_backslash_traversal(hub, tmp_path):
    sentinel = tmp_path / "y"
    sentinel.mkdir()
    (sentinel / "canary.txt").write_text("intact")
    with pytest.raises(ValueError):
        hub.delete("..\\..\\y", active_ids=set())
    assert sentinel.exists()
    assert (sentinel / "canary.txt").read_text() == "intact"


def test_delete_rejects_identity_dot(hub):
    hub.download("fastenhancer-tiny")
    base_dir = hub._registry.base_dir
    sentinel = base_dir / "sentinel.txt"
    sentinel.write_text("intact")
    with pytest.raises(ValueError):
        hub.delete(".", active_ids=set())
    assert base_dir.exists()
    assert sentinel.read_text() == "intact"
    assert hub.catalog()[0]["installed"] is True


def test_delete_rejects_identity_dotdot(hub):
    hub.download("fastenhancer-tiny")
    base_dir = hub._registry.base_dir
    sentinel = base_dir / "sentinel.txt"
    sentinel.write_text("intact")
    with pytest.raises(ValueError):
        hub.delete("..", active_ids=set())
    assert base_dir.exists()
    assert sentinel.read_text() == "intact"
    assert hub.catalog()[0]["installed"] is True


def test_delete_identity_dot_via_api_returns_4xx(monkeypatch, tmp_path):
    import stfu.api.routes.models as models_route
    from fastapi.testclient import TestClient
    from stfu.hub.registry import ModelRegistry
    from stfu.main import app

    registry = ModelRegistry(tmp_path / "api_models")
    sentinel = registry.base_dir / "sentinel.txt"
    sentinel.write_text("intact")
    monkeypatch.setattr(models_route, "default_registry", lambda: registry)

    client = TestClient(app)
    r = client.delete("/models/%2E")

    assert 400 <= r.status_code < 500
    assert registry.base_dir.exists()
    assert sentinel.read_text() == "intact"
