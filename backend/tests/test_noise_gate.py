import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.builtin.noise_gate import NoiseGatePlugin

_FMT = AudioFormat(48000, 1, 960)


def _gate(**params):
    g = NoiseGatePlugin()
    g.setup(_FMT)
    for k, v in params.items():
        g.set_parameter(k, v)
    return g


def _tone(amp, n=48000):
    t = np.arange(n) / 48000.0
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32).reshape(-1, 1)


def _process_all(gate, sig):
    out = []
    for i in range(0, len(sig) - 960, 960):
        out.append(gate.process(sig[i:i + 960]))
    return np.concatenate(out)


def test_loud_signal_passes_mostly_unattenuated():
    gate = _gate(threshold_db=-45.0, attack_ms=5.0)
    loud = _tone(0.5)  # ~ -6 dBFS, muy por encima del umbral
    out = _process_all(gate, loud)
    # tras el ataque, la energía de salida ≈ la de entrada (gate abierto)
    tail_in = np.sqrt(np.mean(loud[24000:]**2))
    tail_out = np.sqrt(np.mean(out[24000 - 960:]**2))
    assert tail_out > 0.9 * tail_in


def test_quiet_signal_gets_attenuated():
    gate = _gate(threshold_db=-45.0, release_ms=100.0, hold_ms=0.0)
    quiet = _tone(0.001)  # ~ -60 dBFS, por debajo del umbral
    out = _process_all(gate, quiet)
    tail = np.sqrt(np.mean(out[24000:]**2))
    quiet_rms = np.sqrt(np.mean(quiet[24000:]**2))
    assert tail < 0.1 * quiet_rms  # fuertemente atenuado


def test_gate_state_persists_across_chunks():
    gate = _gate(threshold_db=-45.0)
    loud = _tone(0.5, n=2000)
    gate.process(loud[:960])
    g_after_first = gate._gain
    gate.process(loud[960:1920])
    # el gate ya está abierto: la ganancia se mantiene alta, no reinicia a 0
    assert gate._gain >= g_after_first - 1e-6


def test_output_shape_and_dtype():
    gate = _gate()
    out = gate.process(_tone(0.3, n=960))
    assert out.shape == (960, 1)
    assert out.dtype == np.float32
