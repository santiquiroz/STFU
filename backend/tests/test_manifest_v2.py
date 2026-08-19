import pytest
from stfu.hub.registry import ModelManifest, IoSpec, TensorSpec, StateSpec


def _base(**over):
    d = dict(
        id="fastenhancer-tiny", name="FastEnhancer Tiny", version="1.0",
        plugin_class="stfu.plugins.onnx_streaming.OnnxStreamingPlugin",
        source="hf", file="model.onnx",
        preferred_format={"sample_rate": 16000, "channels": 1, "chunk_samples": 256},
        size_mb=0.1, algorithmic_latency_ms=16.0,
        tier="floor", license="MIT", hf_repo="aask1357/fastenhancer",
        sha256="a" * 64,
        io_spec={
            "audio_input": {"name": "input", "shape": [1, "chunk"]},
            "audio_output": "output",
            "states": [{"input": "state_in", "output": "state_out", "shape": [1, 64]}],
        },
    )
    d.update(over)
    return d


def test_manifest_v2_parses():
    m = ModelManifest(**_base())
    assert m.tier == "floor"
    assert m.io_spec.states[0].input == "state_in"
    assert m.supported_devices == ["cpu", "gpu"]


def test_io_spec_optional_for_builtin_plugins():
    m = ModelManifest(**_base(io_spec=None, sha256=None, hf_repo=None))
    assert m.io_spec is None


def test_invalid_tier_rejected():
    with pytest.raises(ValueError):
        ModelManifest(**_base(tier="ultra"))


def test_existing_validators_still_apply():
    with pytest.raises(ValueError):
        ModelManifest(**_base(file="..\\evil.onnx"))
