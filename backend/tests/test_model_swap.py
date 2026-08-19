import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.capture import CaptureThread
from stfu.plugins.base import AudioPlugin


class _TaggedPlugin(AudioPlugin):
    version = "1.0"

    def __init__(self, tag: str):
        self._tag = tag
        self.torn_down = False

    @property
    def name(self):
        return self._tag

    @property
    def preferred_format(self):
        return AudioFormat(48000, 2, 960)

    def setup(self, fmt):
        return fmt

    def process(self, audio):
        return audio

    def teardown(self):
        self.torn_down = True

    @property
    def algorithmic_latency_ms(self):
        return 0.0

    @property
    def parameters(self):
        return []


def _fmt():
    return AudioFormat(sample_rate=48000, channels=2, chunk_samples=960)


def test_replace_plugin_tears_down_old_and_swaps_in_place():
    old, new = _TaggedPlugin("old"), _TaggedPlugin("new")
    p = Pipeline()
    p.add_plugin(old)
    p.compile(_fmt())
    p.replace_plugin(0, new)
    assert old.torn_down is True
    assert p._plugins[0] is new
    assert p.stage_metrics()[0]["stage"] == "new"  # métricas recreadas


def test_worker_drains_swap_queue_before_processing():
    old, new = _TaggedPlugin("old"), _TaggedPlugin("new")
    pipeline = Pipeline()
    pipeline.add_plugin(old)
    fmt = _fmt()
    pipeline.compile(fmt)
    t = CaptureThread(input_device_id=0, output_device_id=0, fmt=fmt,
                      pipeline=pipeline, out_channels=2)
    t.request_plugin_swap(0, new)
    t._drain_swaps()
    assert pipeline._plugins[0] is new
