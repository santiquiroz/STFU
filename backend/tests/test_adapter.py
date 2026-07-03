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

def test_resample_48k_to_16k_streaming():
    # Resampler con estado: el primer chunk retiene el delay del filtro,
    # pero todo chunk emitido tiene el tamaño destino y no se pierde audio.
    src = AudioFormat(48000, 1, 960)   # 20ms @ 48k
    dst = AudioFormat(16000, 1, 320)   # 20ms @ 16k
    adapter = FormatAdapter(src, dst)
    chunks = []
    for _ in range(5):
        chunks.extend(adapter.convert(_audio(960, 1)))
    assert all(c.shape == (320, 1) for c in chunks)
    total = sum(len(c) for c in chunks)
    assert 4 * 320 <= total <= 5 * 320


def test_resample_no_boundary_clicks():
    # Seno continuo procesado por chunks: sin estado entre chunks aparecen
    # discontinuidades en cada borde; con estado la señal queda suave.
    src = AudioFormat(48000, 1, 960)
    dst = AudioFormat(44100, 1, 882)
    adapter = FormatAdapter(src, dst)
    fs, freq = 48000, 1000.0
    out = []
    for i in range(20):
        t = (np.arange(960) + i * 960) / fs
        chunk = np.sin(2 * np.pi * freq * t).astype(np.float32).reshape(-1, 1)
        out.extend(c[:, 0] for c in adapter.convert(chunk))
    signal = np.concatenate(out)
    max_theoretical_step = 2 * np.pi * freq / 44100  # derivada máx del seno
    assert np.max(np.abs(np.diff(signal))) < max_theoretical_step * 1.5


def test_extreme_ratio_192k_to_16k_model():
    # Caso real: mic de 192kHz alimentando un modelo que exige 16kHz mono.
    src = AudioFormat(192000, 2, 3840)   # 20ms @ 192k estéreo
    dst = AudioFormat(16000, 1, 320)     # 20ms @ 16k mono
    adapter = FormatAdapter(src, dst)
    fs, freq = 192000, 1000.0
    chunks = []
    for i in range(10):
        t = (np.arange(3840) + i * 3840) / fs
        sig = np.sin(2 * np.pi * freq * t).astype(np.float32)
        chunks.extend(adapter.convert(np.stack([sig, sig], axis=1)))
    assert all(c.shape == (320, 1) for c in chunks)
    total = sum(len(c) for c in chunks)
    # ratio 12:1 → el FIR de soxr retiene ~2-3 chunks de delay; el resto fluye
    assert total >= 6 * 320
    tail = np.concatenate([c[:, 0] for c in chunks[5:]])
    assert float(np.sqrt(np.mean(tail ** 2))) > 0.5  # señal íntegra, no ceros


def test_no_buffering_latency_when_durations_match_across_rates():
    src = AudioFormat(16000, 1, 320)   # 20ms
    dst = AudioFormat(48000, 1, 960)   # 20ms
    assert FormatAdapter(src, dst).buffering_latency_ms == pytest.approx(0.0)

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
