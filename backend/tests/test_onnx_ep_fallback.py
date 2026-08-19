from pathlib import Path
import numpy as np
import pytest
from stfu.hub.registry import ModelManifest
from stfu.inference import ep_router
from tests.helpers_onnx import make_streaming_model

_CHUNK = 256


def test_remaining_ladder_below_current():
    assert ep_router.remaining_ladder("gpu") == ["cpu"]
    assert ep_router.remaining_ladder("cpu") == []
    assert ep_router.remaining_ladder("npu") == ["gpu", "cpu"]


@pytest.fixture()
def plugin(tmp_path):
    from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
    model_path = tmp_path / "m.onnx"
    make_streaming_model(model_path, chunk=_CHUNK, state_dim=4)
    m = ModelManifest(
        id="t", name="T", version="1.0",
        plugin_class="stfu.plugins.onnx_streaming.OnnxStreamingPlugin",
        source="local", file="model.onnx",
        preferred_format={"sample_rate": 16000, "channels": 1, "chunk_samples": _CHUNK},
        size_mb=0.01, algorithmic_latency_ms=16.0, tier="floor", license="MIT",
        io_spec={
            "audio_input": {"name": "audio", "shape": [1, "chunk"]},
            "audio_output": "enhanced",
            "states": [{"input": "state_in", "output": "state_out", "shape": [1, 4]}],
        },
    )
    pl = OnnxStreamingPlugin(m, model_path, device="cpu")
    pl.setup(pl.preferred_format)
    return pl


def test_runtime_ep_error_falls_back_to_passthrough_when_no_ladder(plugin, monkeypatch):
    # device cpu → no queda escalera; un error de run cae a dry passthrough.
    chunk = np.ones((_CHUNK, 1), dtype=np.float32)

    def boom(*a, **k):
        raise RuntimeError("EP session crashed")

    monkeypatch.setattr(plugin._session, "run", boom)
    out = plugin.process(chunk)
    np.testing.assert_array_equal(out, chunk)   # dry passthrough, finito
    assert plugin.active_device == "cpu"
