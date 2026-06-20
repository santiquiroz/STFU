import numpy as np
import pytest
from stfu.core.audio_format import AudioFormat
from stfu.core.adapter import FormatAdapter

def _audio(samples: int, channels: int) -> np.ndarray:
    return np.random.randn(samples, channels).astype(np.float32)

def test_passthrough_same_format():
    fmt = AudioFormat(48000, 1, 960)
    adapter = FormatAdapter(fmt, fmt)
    audio = _audio(960, 1)
    chunks = list(adapter.convert(audio))
    assert len(chunks) == 1
    np.testing.assert_array_equal(chunks[0], audio)

def test_mono_to_stereo():
    src = AudioFormat(48000, 1, 960)
    dst = AudioFormat(48000, 2, 960)
    chunks = list(FormatAdapter(src, dst).convert(_audio(960, 1)))
    assert chunks[0].shape == (960, 2)
    np.testing.assert_array_equal(chunks[0][:, 0], chunks[0][:, 1])

def test_stereo_to_mono():
    src = AudioFormat(48000, 2, 960)
    dst = AudioFormat(48000, 1, 960)
    chunks = list(FormatAdapter(src, dst).convert(_audio(960, 2)))
    assert chunks[0].shape == (960, 1)

def test_resample_48k_to_16k():
    src = AudioFormat(48000, 1, 960)   # 20ms @ 48k
    dst = AudioFormat(16000, 1, 320)   # 20ms @ 16k
    chunks = list(FormatAdapter(src, dst).convert(_audio(960, 1)))
    assert chunks[0].shape == (320, 1)

def test_rechunk_accumulates_until_target():
    src = AudioFormat(48000, 1, 960)
    dst = AudioFormat(48000, 1, 4800)  # 100ms chunks
    adapter = FormatAdapter(src, dst)
    results = []
    for _ in range(4):
        results.extend(adapter.convert(_audio(960, 1)))
    assert len(results) == 0
    results.extend(adapter.convert(_audio(960, 1)))
    assert len(results) == 1
    assert results[0].shape == (4800, 1)

def test_buffering_latency_rechunk():
    src = AudioFormat(48000, 1, 960)
    dst = AudioFormat(48000, 1, 4800)
    assert FormatAdapter(src, dst).buffering_latency_ms == pytest.approx(80.0)

def test_no_buffering_latency_same_chunk():
    fmt = AudioFormat(48000, 1, 960)
    assert FormatAdapter(fmt, fmt).buffering_latency_ms == pytest.approx(0.0)
