import numpy as np
import sounddevice as sd
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.capture import (
    CaptureThread,
    _adjust_channels,
    _wasapi_auto_convert,
)


def _thread() -> CaptureThread:
    return CaptureThread(
        input_device_id=0,
        output_device_id=0,
        fmt=AudioFormat(48000, 2, 960),
        pipeline=Pipeline(),
        out_channels=2,
    )


def test_wasapi_auto_convert_returns_settings_or_none():
    result = _wasapi_auto_convert()
    assert result is None or isinstance(result, getattr(sd, "WasapiSettings", type(None)))


def test_stats_initial_state():
    stats = _thread().stats
    assert stats == {
        "playback_active": False,
        "input_overflows": 0,
        "output_underflows": 0,
        "queue_drops": 0,
        "ring_fill": 0,
        "drift_ppm": 0.0,
        "pipeline_failed": False,
        "stages": [],
        "total_latency_ms": 0.0,
    }


def test_adjust_channels_mono_to_stereo():
    mono = np.ones((960, 1), dtype=np.float32)
    stereo = _adjust_channels(mono, 2)
    assert stereo.shape == (960, 2)
    np.testing.assert_array_equal(stereo[:, 0], stereo[:, 1])


def test_adjust_channels_trims_extra_channels():
    twoch = np.stack(
        [np.arange(960, dtype=np.float32), np.arange(960, dtype=np.float32) + 1000.0],
        axis=1,
    )
    trimmed = _adjust_channels(twoch, 1)
    assert trimmed.shape == (960, 1)
    np.testing.assert_array_equal(trimmed[:, 0], twoch[:, 0])
