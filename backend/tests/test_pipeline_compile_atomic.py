import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.plugins.base import AudioPlugin


class _P(AudioPlugin):
    name = "p"
    version = "1.0"

    @property
    def preferred_format(self):
        return AudioFormat(48000, 1, 480)

    def setup(self, fmt):
        return fmt

    def process(self, audio):
        return audio

    def teardown(self):
        pass

    @property
    def algorithmic_latency_ms(self):
        return 5.0

    @property
    def parameters(self):
        return []


def test_recompile_never_exposes_partial_stages():
    p = Pipeline()
    p.add_plugin(_P())
    p.add_plugin(_P())
    fmt = AudioFormat(48000, 1, 480)
    p.compile(fmt)
    # Snapshot de la referencia de _stages antes de recompilar
    before = p._stages
    p.compile(fmt)
    after = p._stages
    # Debe ser un objeto de lista NUEVO (reasignación en bloque), no el mismo
    # mutado in-place — garantiza que un lector con la referencia vieja ve una
    # lista completa y estable, no una truncada a mitad de compile().
    assert after is not before
    assert len(after) == 2
    # la referencia vieja sigue siendo una lista completa de 2 (no fue vaciada)
    assert len(before) == 2


def test_total_latency_stable_after_recompile():
    p = Pipeline()
    p.add_plugin(_P())
    p.add_plugin(_P())
    fmt = AudioFormat(48000, 1, 480)
    p.compile(fmt)
    assert p.total_latency_ms() == 10.0  # 2 plugins × 5ms
    p.compile(fmt)
    assert p.total_latency_ms() == 10.0
