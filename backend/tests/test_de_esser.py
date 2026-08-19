import numpy as np
from scipy.signal import welch
from stfu.core.audio_format import AudioFormat
from stfu.plugins.builtin.de_esser import DeEsserPlugin

_FMT = AudioFormat(48000, 1, 960)


def _de(**p):
    d = DeEsserPlugin()
    d.setup(_FMT)
    for k, v in p.items():
        d.set_parameter(k, v)
    return d


def _tone(amp, f, n=48000):
    t = np.arange(n) / 48000.0
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32).reshape(-1, 1)


def _run(d, sig):
    out = []
    for i in range(0, len(sig) - 960, 960):
        out.append(d.process(sig[i:i + 960]))
    return np.concatenate(out)


def test_sibilant_band_reduced():
    d = _de(freq_hz=6000.0, threshold_db=-40.0, reduction_db=12.0)
    sib = _tone(0.5, 7000)  # fuerte en la banda de sibilancia
    out = _run(d, sib)
    r_in = np.sqrt(np.mean(sib[24000:]**2))
    r_out = np.sqrt(np.mean(out[24000:]**2))
    assert r_out < 0.6 * r_in   # la sibilancia se atenuó notablemente


def test_low_freq_voice_barely_touched():
    d = _de(freq_hz=6000.0, threshold_db=-40.0, reduction_db=12.0)
    voice = _tone(0.5, 300)  # tono grave, sin sibilancia
    out = _run(d, voice)
    r_in = np.sqrt(np.mean(voice[24000:]**2))
    r_out = np.sqrt(np.mean(out[24000:]**2))
    assert r_out > 0.85 * r_in   # casi intacto


def test_output_shape_dtype():
    d = _de()
    out = d.process(_tone(0.3, 500, n=960))
    assert out.shape == (960, 1) and out.dtype == np.float32
