import numpy as np
import pytest
from stfu.core.audio_format import AudioFormat
from stfu.plugins.builtin.eq_parametric import EQParametricPlugin

_FMT = AudioFormat(48000, 1, 960)


def _sine(freq: float, samples: int, fs: int = 48000) -> np.ndarray:
    t = np.arange(samples) / fs
    return np.sin(2 * np.pi * freq * t).astype(np.float32).reshape(-1, 1)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2)))


def _process_chunked(plugin: EQParametricPlugin, signal: np.ndarray, chunk: int = 960) -> np.ndarray:
    outs = [plugin.process(signal[i:i + chunk]) for i in range(0, len(signal), chunk)]
    return np.concatenate(outs, axis=0)


def _eq_with_band3(gain_db: float) -> EQParametricPlugin:
    p = EQParametricPlugin()
    p.setup(_FMT)
    p.set_parameter("band_3_gain_db", gain_db)  # banda 3 = 1000 Hz, Q=1
    return p


def test_boost_amplifies_band_frequency():
    p = _eq_with_band3(+12.0)
    signal = _sine(1000.0, 960 * 50)
    out = _process_chunked(p, signal)
    # estado estacionario: ignora el transitorio inicial del filtro
    ratio = _rms(out[960 * 10:]) / _rms(signal[960 * 10:])
    assert ratio == pytest.approx(10 ** (12.0 / 20.0), rel=0.1)


def test_cut_attenuates_band_frequency():
    p = _eq_with_band3(-12.0)
    signal = _sine(1000.0, 960 * 50)
    out = _process_chunked(p, signal)
    ratio = _rms(out[960 * 10:]) / _rms(signal[960 * 10:])
    assert ratio == pytest.approx(10 ** (-12.0 / 20.0), rel=0.1)


def test_boost_leaves_far_frequency_untouched():
    p = _eq_with_band3(+12.0)
    signal = _sine(8000.0, 960 * 50)
    out = _process_chunked(p, signal)
    ratio = _rms(out[960 * 10:]) / _rms(signal[960 * 10:])
    assert 0.9 < ratio < 1.15  # ±~1dB lejos de la banda


def test_chunked_processing_equals_whole_signal():
    signal = _sine(1000.0, 960 * 10) + 0.3 * _sine(3000.0, 960 * 10)
    p_chunked = _eq_with_band3(+6.0)
    p_whole = _eq_with_band3(+6.0)
    out_chunked = _process_chunked(p_chunked, signal)
    out_whole = p_whole.process(signal)
    # filtro lineal con estado persistente: por chunks == señal completa
    np.testing.assert_allclose(out_chunked, out_whole, atol=1e-5)


def test_two_active_bands_do_not_silence_signal():
    p = EQParametricPlugin()
    p.setup(_FMT)
    p.set_parameter("band_2_gain_db", +6.0)   # 250 Hz
    p.set_parameter("band_4_gain_db", +6.0)   # 4000 Hz
    signal = _sine(1000.0, 960 * 30)
    out = _process_chunked(p, signal)
    ratio = _rms(out[960 * 10:]) / _rms(signal[960 * 10:])
    assert ratio > 0.7  # el bug de iirpeak dejaba esto en ~0
