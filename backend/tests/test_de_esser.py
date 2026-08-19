import numpy as np
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


def test_broadband_no_sibilance_passes_flat():
    # ruido blanco bien por debajo del umbral: el crossover LR4 debe
    # reconstruir magnitud plana (low_band + high_band == input) sin
    # colorear el paso cuando el gate nunca se activa
    rng = np.random.default_rng(42)
    d = _de(freq_hz=6000.0, threshold_db=-30.0, reduction_db=12.0)
    noise = (0.02 * rng.standard_normal(48000)).astype(np.float32).reshape(-1, 1)
    out = _run(d, noise)
    r_in = np.sqrt(np.mean(noise[24000:] ** 2))
    r_out = np.sqrt(np.mean(out[24000:] ** 2))
    ratio_db = 20 * np.log10(r_out / r_in)
    assert abs(ratio_db) < 0.5


def test_zi_persists_chunk_continuity():
    # el filtrado de un chunk debe depender del zi que dejó el chunk
    # anterior: si el zi se resetea entre llamadas a process() en vez de
    # persistir (regresión en el swap atómico de EQParametric), filtrar
    # el mismo chunk2 "en caliente" (tras chunk1) y "en frío" (objeto
    # nuevo) daría resultados indistinguibles cerca del borde.
    rng = np.random.default_rng(7)
    chunk1 = (0.3 * rng.standard_normal(960)).astype(np.float32).reshape(-1, 1)
    chunk2 = (0.3 * rng.standard_normal(960)).astype(np.float32).reshape(-1, 1)

    d = _de(freq_hz=6000.0, threshold_db=-40.0, reduction_db=12.0)
    d._filter_band("_hp_filter", chunk1)
    warm_out = d._filter_band("_hp_filter", chunk2)

    d_cold = _de(freq_hz=6000.0, threshold_db=-40.0, reduction_db=12.0)
    cold_out = d_cold._filter_band("_hp_filter", chunk2)

    assert not np.allclose(warm_out[:10], cold_out[:10], atol=1e-6)


def test_process_does_not_mutate_input():
    d = _de()
    audio = _tone(0.4, 6500, n=960)
    audio_snapshot = audio.copy()
    out = d.process(audio)
    assert np.array_equal(audio, audio_snapshot)
    assert out is not audio
