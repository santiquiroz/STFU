import numpy as np
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.plugins.base import AudioPlugin


class _FmtPlugin(AudioPlugin):
    version = "1.0"

    def __init__(self, tag: str, rate: int = 48000):
        self._tag = tag
        self._rate = rate
        self.setup_calls = 0
        self.torn_down = False

    @property
    def name(self):
        return self._tag

    @property
    def preferred_format(self):
        return AudioFormat(self._rate, 1, 480)

    def setup(self, fmt):
        self.setup_calls += 1
        return fmt

    def process(self, audio):
        return audio

    def teardown(self):
        self.torn_down = True

    @property
    def algorithmic_latency_ms(self):
        return 0.0

    @property
    def parameters(self):
        return []


def _compiled(*plugins):
    p = Pipeline()
    for pl in plugins:
        p.add_plugin(pl)
    p.compile(AudioFormat(48000, 1, 480))
    return p


def test_same_format_swap_does_not_resetup_neighbors():
    neighbor = _FmtPlugin("eq", rate=48000)
    old = _FmtPlugin("model-a", rate=48000)
    p = _compiled(old, neighbor)
    neighbor.setup_calls = 0  # resetear el conteo post-compile inicial
    new = _FmtPlugin("model-b", rate=48000)

    p.replace_plugin(0, new)

    assert p._plugins[0] is new
    assert old.torn_down is True
    assert new.setup_calls == 1          # el nuevo se setupea
    assert neighbor.setup_calls == 0     # el vecino NO se re-setupea (buffers intactos)
    assert p.stage_metrics()[0]["stage"] == "model-b"


def test_different_format_swap_falls_back_to_full_recompile():
    neighbor = _FmtPlugin("eq", rate=48000)
    old = _FmtPlugin("model-a", rate=48000)
    p = _compiled(old, neighbor)
    neighbor.setup_calls = 0
    new = _FmtPlugin("model-c", rate=16000)  # rate distinto → adapters cambian

    p.replace_plugin(0, new)

    assert p._plugins[0] is new
    assert new.setup_calls == 1
    assert neighbor.setup_calls == 1     # recompile total re-setupea todo
