import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.builtin.compressor import CompressorPlugin

_FMT = AudioFormat(48000, 1, 960)


def _comp(**p):
    c = CompressorPlugin()
    c.setup(_FMT)
    for k, v in p.items():
        c.set_parameter(k, v)
    return c


def _tone(amp, n=48000, f=220):
    t = np.arange(n) / 48000.0
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32).reshape(-1, 1)


def _run(c, sig):
    out = []
    for i in range(0, len(sig) - 960, 960):
        out.append(c.process(sig[i:i + 960]))
    return np.concatenate(out)


def _rms_db(x):
    r = np.sqrt(np.mean(x**2))
    return 20 * np.log10(r + 1e-12)


def test_reduces_dynamic_range():
    c = _comp(threshold_db=-24.0, ratio=4.0, makeup_db=0.0)
    loud = _run(c, _tone(0.5))   # fuerte
    c2 = _comp(threshold_db=-24.0, ratio=4.0, makeup_db=0.0)
    quiet = _run(c2, _tone(0.05))  # flojo (por debajo del umbral, casi sin tocar)
    # el rango entre fuerte y flojo se comprime: la diferencia de salida < la de entrada
    in_range = _rms_db(_tone(0.5)) - _rms_db(_tone(0.05))
    out_range = _rms_db(loud[24000:]) - _rms_db(quiet[24000:])
    assert out_range < in_range - 3.0   # al menos 3 dB de compresión de rango


def test_below_threshold_barely_touched():
    c = _comp(threshold_db=-12.0, ratio=4.0, makeup_db=0.0)
    quiet = _tone(0.05)  # ~ -26 dBFS, debajo de -12
    out = _run(c, quiet)
    assert abs(_rms_db(out[24000:]) - _rms_db(quiet[24000:])) < 2.0


def test_agc_converges_toward_target():
    c = _comp(agc=True, agc_target_db=-18.0)
    quiet = _tone(0.02)  # muy por debajo del target
    out = _run(c, quiet)
    assert _rms_db(out[36000:]) > _rms_db(quiet[36000:]) + 3.0  # AGC subió el nivel hacia el target


def test_output_shape_dtype():
    c = _comp()
    out = c.process(_tone(0.3, n=960))
    assert out.shape == (960, 1) and out.dtype == np.float32
