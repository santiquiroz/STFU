"""Tests del núcleo DSP de la verificación del cable (driver/verify_cable.py).

Prueban la lógica de detección de pico por FFT con señales sintéticas — sin
hardware ni driver. La parte de reproducir/capturar (play_and_capture) sí
requiere el driver y no se testea aquí.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

_VERIFY_CABLE = Path(__file__).resolve().parents[2] / "driver" / "verify_cable.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_cable", _VERIFY_CABLE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verify_cable"] = mod
    spec.loader.exec_module(mod)
    return mod


vc = _load_module()


def _sine(freq, seconds, sr, amp=0.5):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_dominant_frequency_detects_1khz_clean():
    sr = 48000
    sig = _sine(1000, 1.0, sr)
    peak = vc.dominant_frequency(sig, sr)
    assert abs(peak.freq_hz - 1000) <= 5
    assert peak.snr_db > 30


def test_dominant_frequency_detects_other_freqs():
    sr = 48000
    for f in (440, 2000, 5000):
        peak = vc.dominant_frequency(_sine(f, 0.5, sr), sr)
        assert abs(peak.freq_hz - f) <= 10, f"esperado {f}, medido {peak.freq_hz}"


def test_dominant_frequency_survives_moderate_noise():
    sr = 48000
    rng = np.random.default_rng(42)
    sig = _sine(1000, 1.0, sr) + 0.02 * rng.standard_normal(sr).astype(np.float32)
    peak = vc.dominant_frequency(sig, sr)
    assert abs(peak.freq_hz - 1000) <= 10
    assert peak.snr_db > 15


def test_dominant_frequency_empty_signal():
    peak = vc.dominant_frequency(np.zeros(0, dtype=np.float32), 48000)
    assert peak.freq_hz == 0.0 and peak.magnitude == 0.0


def test_dominant_frequency_accepts_stereo():
    sr = 48000
    mono = _sine(1000, 0.5, sr)
    stereo = np.stack([mono, mono], axis=1)
    peak = vc.dominant_frequency(stereo, sr)
    assert abs(peak.freq_hz - 1000) <= 5


def test_peak_matches_target_within_tolerance():
    peak = vc.PeakResult(freq_hz=1005.0, magnitude=1.0, snr_db=25.0)
    assert vc.peak_matches_target(peak, 1000.0, tol_hz=25.0, min_snr_db=15.0)


def test_peak_matches_target_rejects_off_frequency():
    peak = vc.PeakResult(freq_hz=1200.0, magnitude=1.0, snr_db=40.0)
    assert not vc.peak_matches_target(peak, 1000.0, tol_hz=25.0, min_snr_db=15.0)


def test_peak_matches_target_rejects_low_snr():
    peak = vc.PeakResult(freq_hz=1000.0, magnitude=1.0, snr_db=5.0)
    assert not vc.peak_matches_target(peak, 1000.0, tol_hz=25.0, min_snr_db=15.0)


def test_pure_noise_has_low_snr():
    sr = 48000
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(sr).astype(np.float32)
    peak = vc.dominant_frequency(noise, sr)
    # ruido blanco: sin pico tonal dominante, SNR bajo → no debería pasar el gate
    assert not vc.peak_matches_target(peak, 1000.0, tol_hz=25.0, min_snr_db=15.0)
