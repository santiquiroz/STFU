from pathlib import Path
import pytest
from pydantic import ValidationError
from stfu.hub.registry import ModelManifest, ModelRegistry


def _manifest() -> ModelManifest:
    return ModelManifest(
        id="test-model", name="Test", version="1.0.0",
        plugin_class="stfu.plugins.builtin.gain.GainPlugin",
        source="local", file="model.onnx",
        preferred_format={"sample_rate": 48000, "channels": 1, "chunk_samples": 960},
        supported_backends=["cpu"], size_mb=1.0,
        algorithmic_latency_ms=0.0, tags=["test"],
    )


@pytest.fixture
def registry(tmp_path):
    return ModelRegistry(tmp_path)


def test_empty_on_init(registry):
    assert registry.list() == []


def test_register_and_list(registry, tmp_path):
    f = tmp_path / "model.onnx"
    f.write_bytes(b"fake")
    registry.register(_manifest(), f)
    assert len(registry.list()) == 1
    assert registry.list()[0].id == "test-model"


def test_get_existing(registry, tmp_path):
    f = tmp_path / "model.onnx"
    f.write_bytes(b"fake")
    registry.register(_manifest(), f)
    assert registry.get("test-model").name == "Test"


def test_get_missing_returns_none(registry):
    assert registry.get("nope") is None


def test_persists_across_instances(registry, tmp_path):
    f = tmp_path / "model.onnx"
    f.write_bytes(b"fake")
    registry.register(_manifest(), f)
    registry2 = ModelRegistry(registry.base_dir)
    assert len(registry2.list()) == 1


def test_delete_removes_installed(registry, tmp_path):
    f = tmp_path / "model.onnx"
    f.write_bytes(b"fake")
    registry.register(_manifest(), f)
    registry.delete("test-model")
    assert registry.list() == []


def test_delete_missing_is_noop(registry):
    registry.delete("nope")


def test_delete_rejects_path_traversal(registry):
    with pytest.raises(ValueError):
        registry.delete("../escape")


def test_delete_rejects_identity_dot(registry):
    sentinel = registry.base_dir / "sentinel.txt"
    sentinel.write_text("intact")
    with pytest.raises(ValueError):
        registry.delete(".")
    assert registry.base_dir.exists()
    assert sentinel.read_text() == "intact"


def test_delete_rejects_parent_dotdot(registry):
    sentinel = registry.base_dir / "sentinel.txt"
    sentinel.write_text("intact")
    with pytest.raises(ValueError):
        registry.delete("..")
    assert registry.base_dir.exists()
    assert sentinel.read_text() == "intact"


def _manifest_kwargs(id: str) -> dict:
    return dict(
        id=id, name="Test", version="1.0.0",
        plugin_class="stfu.plugins.builtin.gain.GainPlugin",
        source="local", file="model.onnx",
        preferred_format={"sample_rate": 48000, "channels": 1, "chunk_samples": 960},
        supported_backends=["cpu"], size_mb=1.0,
        algorithmic_latency_ms=0.0, tags=["test"],
    )


def test_manifest_rejects_dot_id():
    with pytest.raises(ValidationError):
        ModelManifest(**_manifest_kwargs("."))


def test_manifest_rejects_dotdot_id():
    with pytest.raises(ValidationError):
        ModelManifest(**_manifest_kwargs(".."))
