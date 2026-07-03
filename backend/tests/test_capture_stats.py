import numpy as np
import sounddevice as sd
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.audio.capture import (
    CaptureThread,
    _write_to_output,
    _adjust_channels,
    _wasapi_auto_convert,
)


def test_wasapi_auto_convert_returns_settings_or_none():
    # Act
    result = _wasapi_auto_convert()

    # Assert: None or a WasapiSettings instance
    assert result is None or isinstance(result, getattr(sd, "WasapiSettings", type(None)))


def test_stats_initial_state():
    # Arrange
    thread = CaptureThread(input_device_id=0, output_device_id=0, fmt=AudioFormat(48000, 2, 960), pipeline=Pipeline(), out_channels=2)

    # Act: do not start the thread
    stats = thread.stats

    # Assert
    assert stats == {
        "playback_active": False,
        "input_overflows": 0,
        "output_underflows": 0,
        "queue_drops": 0,
        "queue_fill": 0,
    }


def test_prefill_puts_two_silence_chunks():
    # Arrange
    thread = CaptureThread(input_device_id=0, output_device_id=0, fmt=AudioFormat(48000, 2, 960), pipeline=Pipeline(), out_channels=2)

    # Act
    thread._prefill_queue()

    # Assert
    assert thread._queue.qsize() == 2
    for _ in range(2):
        chunk = thread._queue.get_nowait()
        assert chunk.shape == (960, 2)
        assert chunk.dtype == np.float32
        assert np.all(chunk == 0.0)


def test_write_to_output_pads_short_chunk():
    # Arrange
    processed = np.ones((900, 2), dtype=np.float32)
    outdata = np.empty((960, 2), dtype=np.float32)

    # Act
    _write_to_output(processed, outdata)

    # Assert
    np.testing.assert_array_equal(outdata[:900], np.ones((900, 2), dtype=np.float32))
    np.testing.assert_array_equal(outdata[900:], np.zeros((60, 2), dtype=np.float32))


def test_adjust_channels_mono_to_stereo_and_trim():
    # Mono -> stereo (repeat)
    mono = np.ones((960, 1), dtype=np.float32)
    stereo = _adjust_channels(mono, 2)
    assert stereo.shape == (960, 2)
    assert np.all(stereo[:, 0] == 1.0)
    assert np.all(stereo[:, 1] == 1.0)

    # Stereo -> mono (trim)
    twoch = np.stack([np.arange(960, dtype=np.float32), np.arange(960, dtype=np.float32) + 1000.0], axis=1)
    trimmed = _adjust_channels(twoch, 1)
    assert trimmed.shape == (960, 1)
    np.testing.assert_array_equal(trimmed[:, 0], twoch[:, 0])
