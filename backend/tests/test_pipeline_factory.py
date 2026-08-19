import pytest
from pathlib import Path
from stfu.core.pipeline_factory import build_pipeline
from stfu.hub.registry import ModelRegistry, ModelManifest
from tests.helpers_onnx import make_streaming_model


def _registry_with_model(tmp_path) -> ModelRegistry:
    registry = ModelRegistry(tmp_path / "models")
    model_file = tmp_path / "m.onnx"
    make_streaming_model(model_file)
    manifest = ModelManifest(
        id="test-stream", name="Test", version="1.0",
        plugin_class="stfu.plugins.onnx_streaming.OnnxStreamingPlugin",
        source="local", file="model.onnx",
        preferred_format={"sample_rate": 16000, "channels": 1, "chunk_samples": 256},
        size_mb=0.01, algorithmic_latency_ms=16.0,
        io_spec={
            "audio_input": {"name": "audio", "shape": [1, "chunk"]},
            "audio_output": "enhanced",
            "states": [{"input": "state_in", "output": "state_out", "shape": [1, 4]}],
        },
    )
    registry.register(manifest, model_file)
    return registry


def test_builds_builtin_plugins():
    p = build_pipeline([{"plugin_id": "gain", "parameters": {"gain_db": -3.0}}])
    assert len(p._plugins) == 1


def test_builds_model_plugin_from_registry(tmp_path):
    registry = _registry_with_model(tmp_path)
    p = build_pipeline([{"plugin_id": "model:test-stream"}], registry=registry, device="cpu")
    from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
    assert isinstance(p._plugins[0], OnnxStreamingPlugin)


def test_unknown_model_id_raises(tmp_path):
    registry = ModelRegistry(tmp_path / "models")
    with pytest.raises(ValueError, match="model:nope"):
        build_pipeline([{"plugin_id": "model:nope"}], registry=registry)


def test_unknown_plugin_raises():
    with pytest.raises(ValueError, match="desconocido"):
        build_pipeline([{"plugin_id": "wat"}])


def test_dfn3_without_torch_gives_clear_error(monkeypatch):
    import importlib.util
    real = importlib.util.find_spec

    def fake_find_spec(name, *a, **kw):
        if name == "df":
            return None
        return real(name, *a, **kw)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    with pytest.raises(ValueError, match="requirements-torch"):
        build_pipeline([{"plugin_id": "deepfilternet3"}])
