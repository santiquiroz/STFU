import numpy as np
import pytest
from stfu.core.audio_format import AudioFormat
from stfu.plugins.builtin.noise_gate import NoiseGatePlugin
from stfu.plugins.builtin.compressor import CompressorPlugin
from stfu.plugins.builtin.de_esser import DeEsserPlugin
from stfu.plugins.builtin.limiter import LimiterPlugin
from stfu.plugins.builtin.gain import GainPlugin
from stfu.plugins.builtin.eq_parametric import EQParametricPlugin

_FMT = AudioFormat(48000, 1, 960)


def _chunk(amp=0.3, n=960):
    return amp * np.ones((n, 1), dtype=np.float32)


def _assert_finite_process(plugin):
    out = plugin.process(_chunk())
    assert np.all(np.isfinite(out))


def test_noise_gate_attack_ms_zero_clamped_to_min():
    g = NoiseGatePlugin()
    g.setup(_FMT)
    g.set_parameter("attack_ms", 0)
    assert g._attack_ms == pytest.approx(1.0)
    assert np.isfinite(g._attack_coef)
    _assert_finite_process(g)


def test_noise_gate_release_ms_zero_clamped_to_min():
    g = NoiseGatePlugin()
    g.setup(_FMT)
    g.set_parameter("release_ms", 0)
    assert g._release_ms == pytest.approx(10.0)
    assert np.isfinite(g._release_coef)
    _assert_finite_process(g)


def test_noise_gate_threshold_above_max_clamped():
    g = NoiseGatePlugin()
    g.setup(_FMT)
    g.set_parameter("threshold_db", 999.0)
    assert g._threshold_db == pytest.approx(0.0)
    _assert_finite_process(g)


def test_compressor_ratio_zero_clamped_to_min():
    c = CompressorPlugin()
    c.setup(_FMT)
    c.set_parameter("ratio", 0)
    assert c._ratio == pytest.approx(1.0)
    gain_db = c._compression_gain_db(np.array([10.0], dtype=np.float32))
    assert np.all(np.isfinite(gain_db))
    _assert_finite_process(c)


def test_compressor_ratio_near_zero_clamped_to_min():
    c = CompressorPlugin()
    c.setup(_FMT)
    c.set_parameter("ratio", 1e-8)
    assert c._ratio == pytest.approx(1.0)
    gain_db = c._compression_gain_db(np.array([10.0], dtype=np.float32))
    assert np.all(np.isfinite(gain_db))
    _assert_finite_process(c)


def test_compressor_attack_release_ms_zero_clamped():
    c = CompressorPlugin()
    c.setup(_FMT)
    c.set_parameter("attack_ms", 0)
    c.set_parameter("release_ms", 0)
    assert np.isfinite(c._attack_coef)
    assert np.isfinite(c._release_coef)
    _assert_finite_process(c)


def test_de_esser_freq_hz_zero_clamped_to_min():
    d = DeEsserPlugin()
    d.setup(_FMT)
    d.set_parameter("freq_hz", 0)
    assert d._freq_hz == pytest.approx(2000.0)
    _assert_finite_process(d)


def test_limiter_release_ms_zero_and_ceiling_extreme_clamped():
    lim = LimiterPlugin()
    lim.setup(_FMT)
    lim.set_parameter("release_ms", 0)
    lim.set_parameter("ceiling_db", -999.0)
    assert lim._release_ms == pytest.approx(10.0)
    assert lim._ceiling_db == pytest.approx(-24.0)
    assert np.isfinite(lim._release_coef)
    assert np.isfinite(lim._ceiling_lin)
    _assert_finite_process(lim)


def test_limiter_repeated_extreme_updates_stay_finite():
    """El envelope del limiter persiste entre chunks: un valor extremo que
    generara inf contaminaria _envelope_db para siempre (se auto-perpetua
    via new_env_db = ... * coef). Verifica varios chunks seguidos tras
    clampear un release_ms fuera de rango."""
    lim = LimiterPlugin()
    lim.setup(_FMT)
    lim.set_parameter("release_ms", -50.0)
    for _ in range(5):
        out = lim.process(_chunk(amp=0.9))
        assert np.all(np.isfinite(out))
    assert np.isfinite(lim._envelope_db)


def test_gain_db_extreme_clamped():
    g = GainPlugin()
    g.setup(_FMT)
    g.set_parameter("gain_db", 9999.0)
    assert np.isfinite(g._linear)
    _assert_finite_process(g)


def test_eq_band_freq_and_q_zero_clamped():
    eq = EQParametricPlugin()
    eq.setup(_FMT)
    eq.set_parameter("band_1_freq", 0)
    eq.set_parameter("band_1_q", 0)
    eq.set_parameter("band_1_gain_db", 6.0)
    assert eq._bands[0]["freq"] == pytest.approx(20.0)
    assert eq._bands[0]["q"] == pytest.approx(0.1)
    _assert_finite_process(eq)
