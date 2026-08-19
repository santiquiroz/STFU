import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.plugins.builtin.limiter import LimiterPlugin

_FMT = AudioFormat(48000, 1, 960)


def _lim(**p):
    l = LimiterPlugin()
    l.setup(_FMT)
    for k, v in p.items():
        l.set_parameter(k, v)
    return l


def _run(l, sig):
    out = []
    for i in range(0, len(sig) - 960, 960):
        out.append(l.process(sig[i:i + 960]))
    return np.concatenate(out)


def test_output_never_exceeds_ceiling():
    l = _lim(ceiling_db=-6.0)  # ceiling ≈ 0.501
    ceiling_lin = 10 ** (-6.0 / 20.0)
    t = np.arange(48000) / 48000.0
    loud = (1.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32).reshape(-1, 1)  # clippearía sin limiter
    out = _run(l, loud)
    assert np.max(np.abs(out)) <= ceiling_lin + 1e-3


def test_quiet_signal_unchanged():
    l = _lim(ceiling_db=-1.0)
    t = np.arange(48000) / 48000.0
    quiet = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32).reshape(-1, 1)
    out = _run(l, quiet)
    # _run() no procesa el último chunk (range(0, len(sig)-960, 960)), out
    # queda 960 muestras más corto que quiet: se acota el tramo de
    # comparación a len(out) para no comparar arrays de shape distinto.
    np.testing.assert_allclose(out[9600:], quiet[9600:len(out)], atol=0.02)  # por debajo del techo: intacto


def test_output_shape_dtype():
    l = _lim()
    out = l.process((0.3 * np.ones((960, 1))).astype(np.float32))
    assert out.shape == (960, 1) and out.dtype == np.float32


def test_process_does_not_mutate_input():
    l = _lim(ceiling_db=-6.0)
    audio = (1.5 * np.ones((960, 1))).astype(np.float32)
    audio_snapshot = audio.copy()
    out = l.process(audio)
    assert np.array_equal(audio, audio_snapshot)
    assert out is not audio


def test_release_persists_chunk_continuity():
    # tras un pico fuerte, la ganancia debe seguir reducida (en release)
    # durante el bloque siguiente aunque ese bloque ya esté por debajo del
    # techo — si el estado se resetea entre llamadas a process() (en vez
    # de persistir _envelope_db), el objeto "en caliente" y uno "en frío"
    # producirían la misma salida para el mismo bloque silencioso.
    loud = (1.5 * np.ones((960, 1))).astype(np.float32)
    quiet = (0.05 * np.ones((960, 1))).astype(np.float32)

    warm = _lim(ceiling_db=-6.0, release_ms=200.0)
    warm.process(loud)
    warm_out = warm.process(quiet)

    cold = _lim(ceiling_db=-6.0, release_ms=200.0)
    cold_out = cold.process(quiet)

    assert not np.allclose(warm_out, cold_out, atol=1e-6)
    # el bloque en release sigue atenuado por debajo de lo que entra
    assert np.max(np.abs(warm_out)) < np.max(np.abs(quiet))


def test_hard_transient_never_exceeds_ceiling():
    # un transitorio de una sola muestra en medio de silencio: el
    # bloque completo debe quedar acotado al techo, sin importar en
    # qué posición del chunk caiga el pico.
    l = _lim(ceiling_db=-6.0)
    ceiling_lin = 10 ** (-6.0 / 20.0)
    audio = np.zeros((960, 1), dtype=np.float32)
    audio[0, 0] = 3.0  # transitorio al inicio del bloque
    audio[959, 0] = -3.0  # y otro al final del mismo bloque
    out = l.process(audio)
    assert np.max(np.abs(out)) <= ceiling_lin + 1e-3
