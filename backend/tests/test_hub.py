from pathlib import Path
import pytest
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
