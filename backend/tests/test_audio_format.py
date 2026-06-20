import pytest
from stfu.core.audio_format import AudioFormat


def test_creation_with_defaults():
    fmt = AudioFormat(sample_rate=48000, channels=1, chunk_samples=960)
    assert fmt.sample_rate == 48000
    assert fmt.channels == 1
    assert fmt.chunk_samples == 960
    assert fmt.dtype == "float32"


def test_duration_ms():
    fmt = AudioFormat(sample_rate=48000, channels=1, chunk_samples=960)
    assert fmt.duration_ms == pytest.approx(20.0)


def test_equality():
    assert AudioFormat(48000, 1, 960) == AudioFormat(48000, 1, 960)


def test_inequality():
    assert AudioFormat(48000, 1, 960) != AudioFormat(44100, 2, 1024)


def test_immutable():
    fmt = AudioFormat(48000, 1, 960)
    with pytest.raises((AttributeError, TypeError)):
        fmt.sample_rate = 16000
