from pathlib import Path
import numpy as np
import pytest
from stfu.hub.registry import ModelManifest
from tests.helpers_onnx import make_streaming_model

_CHUNK = 256


@pytest.fixture()
def manifest(tmp_path) -> tuple[ModelManifest, Path]:
    model_path = tmp_path / "model.onnx"
    make_streaming_model(model_path, chunk=_CHUNK, state_dim=4)
    m = ModelManifest(
        id="test-stream", name="Test Stream", version="1.0",
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
    return m, model_path


def _plugin(manifest_and_path, device="cpu"):
    from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
    m, p = manifest_and_path
    plugin = OnnxStreamingPlugin(m, p, device=device)
    plugin.setup(plugin.preferred_format)
    return plugin


def test_process_runs_model(manifest):
    plugin = _plugin(manifest)
    chunk = np.ones((_CHUNK, 1), dtype=np.float32)
    out = plugin.process(chunk)
    assert out.shape == (_CHUNK, 1)
    # estado inicial = ceros → enhanced = audio*0.5 + 0
    np.testing.assert_allclose(out[:, 0], 0.5, rtol=1e-5)


def test_state_feeds_back_between_chunks(manifest):
    plugin = _plugin(manifest)
    chunk = np.ones((_CHUNK, 1), dtype=np.float32)
    plugin.process(chunk)                      # state pasa de 0 a 1
    out2 = plugin.process(chunk)               # enhanced = 0.5 + 1.0
    np.testing.assert_allclose(out2[:, 0], 1.5, rtol=1e-5)


def test_strength_mixes_dry_wet(manifest):
    plugin = _plugin(manifest)
    plugin.set_parameter("strength", 0.0)      # 100% dry
    chunk = np.ones((_CHUNK, 1), dtype=np.float32)
    out = plugin.process(chunk)
    np.testing.assert_allclose(out[:, 0], 1.0, rtol=1e-5)


def test_teardown_and_setup_resets_state(manifest):
    plugin = _plugin(manifest)
    chunk = np.ones((_CHUNK, 1), dtype=np.float32)
    plugin.process(chunk)
    plugin.teardown()
    plugin.setup(plugin.preferred_format)
    out = plugin.process(chunk)
    np.testing.assert_allclose(out[:, 0], 0.5, rtol=1e-5)  # estado volvió a cero


def test_preferred_format_from_manifest(manifest):
    plugin = _plugin(manifest)
    fmt = plugin.preferred_format
    assert (fmt.sample_rate, fmt.channels, fmt.chunk_samples) == (16000, 1, _CHUNK)


def test_active_device_reported(manifest):
    plugin = _plugin(manifest, device="cpu")
    assert plugin.active_device == "cpu"


def test_probe_nan_rejection(manifest, monkeypatch):
    """Probe rejects NaN output; session cleanup and DeviceUnavailable raised."""
    from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
    from stfu.inference import ep_router

    m, p = manifest
    plugin = OnnxStreamingPlugin(m, p, device="cpu")

    # Monkeypatch session.run to return NaN arrays
    import onnxruntime as ort
    original_init = ort.InferenceSession.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        original_run = self.run

        def patched_run(output_names, input_feed):
            # Return NaN-filled arrays for all outputs
            return [np.full((_CHUNK, 1), np.nan, dtype=np.float32) for _ in output_names]

        self.run = patched_run

    monkeypatch.setattr(ort.InferenceSession, "__init__", patched_init)

    # Setup with cpu (only device in ladder) should raise DeviceUnavailable
    with pytest.raises(ep_router.DeviceUnavailable):
        plugin.setup(plugin.preferred_format)

    # Session should be None after failed probe
    assert plugin._session is None


def test_probe_exception_raises_device_unavailable(manifest, monkeypatch):
    """Probe exception on InferenceSession creation raises DeviceUnavailable."""
    from stfu.plugins.onnx_streaming import OnnxStreamingPlugin
    from stfu.inference import ep_router
    import onnxruntime as ort

    m, p = manifest
    plugin = OnnxStreamingPlugin(m, p, device="cpu")

    # Monkeypatch InferenceSession.__init__ to raise RuntimeError
    def patched_init(self, *args, **kwargs):
        raise RuntimeError("Session initialization failed")

    monkeypatch.setattr(ort.InferenceSession, "__init__", patched_init)

    # Setup should raise DeviceUnavailable (cpu is only device in ladder)
    with pytest.raises(ep_router.DeviceUnavailable):
        plugin.setup(plugin.preferred_format)

    # Session should remain None after exception
    assert plugin._session is None
