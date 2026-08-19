import queue
import numpy as np
import pytest
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.capture import CaptureThread
from stfu.plugins.base import AudioPlugin


class _ExplodingPlugin(AudioPlugin):
    name = "exploding"
    version = "1.0"

    @property
    def preferred_format(self):
        return AudioFormat(48000, 2, 960)

    def setup(self, fmt):
        return fmt

    def process(self, audio):
        raise RuntimeError("boom")

    def teardown(self):
        pass

    @property
    def algorithmic_latency_ms(self):
        return 0.0

    @property
    def parameters(self):
        return []


def _thread_with(pipeline: Pipeline) -> CaptureThread:
    fmt = AudioFormat(sample_rate=48000, channels=2, chunk_samples=960)
    pipeline.compile(fmt)
    return CaptureThread(
        input_device_id=0, output_device_id=0, fmt=fmt,
        pipeline=pipeline, out_channels=2,
    )


def test_plugin_exception_marks_failed_and_passes_audio_through():
    pipeline = Pipeline()
    pipeline.add_plugin(_ExplodingPlugin())
    t = _thread_with(pipeline)
    chunk = np.ones((960, 2), dtype=np.float32)

    out = t._process_or_passthrough(chunk)

    assert t.stats["pipeline_failed"] is True
    np.testing.assert_array_equal(out, chunk)  # passthrough, no silencio


def test_failed_state_skips_pipeline_on_next_chunks():
    pipeline = Pipeline()
    pipeline.add_plugin(_ExplodingPlugin())
    t = _thread_with(pipeline)
    chunk = np.ones((960, 2), dtype=np.float32)
    t._process_or_passthrough(chunk)  # primera: explota y marca failed
    out = t._process_or_passthrough(chunk)  # segunda: ni intenta
    np.testing.assert_array_equal(out, chunk)


def test_healthy_pipeline_reports_stats_shape():
    pipeline = Pipeline()
    t = _thread_with(pipeline)
    s = t.stats
    assert s["pipeline_failed"] is False
    assert s["stages"] == []
    assert s["total_latency_ms"] == 0.0
    assert s["inference"] is None


class _InferencePlugin(_ExplodingPlugin):
    """Duck-types runtime_status como el plugin ONNX NC (sin correr ONNX)."""

    def __init__(self, degraded: bool) -> None:
        self._degraded = degraded

    def process(self, audio):
        return audio

    @property
    def runtime_status(self) -> dict:
        return {"device": "cpu", "degraded": self._degraded}


def test_stats_surfaces_first_plugin_runtime_status():
    pipeline = Pipeline()
    pipeline.add_plugin(_InferencePlugin(degraded=True))
    t = _thread_with(pipeline)

    assert t.stats["inference"] == {"device": "cpu", "degraded": True}
