"""AudioEngine.insert_plugin/remove_plugin: warmup en el hilo del caller
(nunca en el worker), staging vía CaptureThread.request_plugin_insert/remove
y write-through a _configs (mismo criterio que test_set_parameter_writes_
through_to_stored_config en test_engine.py)."""
import pytest
from unittest.mock import MagicMock, patch
from stfu.audio.engine import AudioEngine
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline
from stfu.plugins.base import AudioPlugin

_FMT = AudioFormat(48000, 1, 960)  # preferred_format real de GainPlugin/EQParametricPlugin


class _FmtPlugin(AudioPlugin):
    version = "1.0"

    def __init__(self, tag: str):
        self._tag = tag

    @property
    def name(self):
        return self._tag

    @property
    def preferred_format(self):
        return _FMT

    def setup(self, fmt):
        return fmt

    def process(self, audio):
        return audio

    def teardown(self):
        pass

    @property
    def algorithmic_latency_ms(self):
        return 0.0

    @property
    def parameters(self):
        return []


def _compiled_pipeline(*names):
    p = Pipeline()
    for name in names:
        p.add_plugin(_FmtPlugin(name))
    p.compile(_FMT)
    return p


def _engine_with_active_feeder(plugin_names, plugin_configs):
    engine = AudioEngine()
    thread = MagicMock(name="CaptureThread")
    thread.pipeline = _compiled_pipeline(*plugin_names)
    with patch("stfu.audio.engine.CaptureThread", return_value=thread), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2):
        engine.start("feeder", input_device_id=1, output_device_id=2, plugin_configs=plugin_configs)
    return engine, thread


def test_insert_plugin_stages_via_worker_and_returns_latency():
    engine, thread = _engine_with_active_feeder(
        ["gain"], [{"plugin_id": "gain", "parameters": {}}],
    )

    latency = engine.insert_plugin("feeder", 1, {"plugin_id": "eq_parametric", "parameters": {}})

    assert latency == 0.0  # builtins sin latencia algorítmica, mismo formato: sin adapters
    thread.request_plugin_insert.assert_called_once()
    index_arg, plugin_arg = thread.request_plugin_insert.call_args.args
    assert index_arg == 1
    assert plugin_arg.name == "EQ Paramétrico"


def test_insert_plugin_writes_through_to_stored_config():
    engine, thread = _engine_with_active_feeder(
        ["gain"], [{"plugin_id": "gain", "parameters": {}}],
    )

    engine.insert_plugin("feeder", 1, {"plugin_id": "eq_parametric", "parameters": {}})

    assert engine.current_devices("feeder") == (1, 2)
    assert engine._configs["feeder"]["plugin_configs"] == [
        {"plugin_id": "gain", "parameters": {}},
        {"plugin_id": "eq_parametric", "parameters": {}},
    ]


def test_insert_plugin_at_start_shifts_stored_config():
    engine, thread = _engine_with_active_feeder(
        ["gain"], [{"plugin_id": "gain", "parameters": {}}],
    )

    engine.insert_plugin("feeder", 0, {"plugin_id": "eq_parametric", "parameters": {}})

    assert engine._configs["feeder"]["plugin_configs"] == [
        {"plugin_id": "eq_parametric", "parameters": {}},
        {"plugin_id": "gain", "parameters": {}},
    ]


def test_insert_plugin_bad_index_raises():
    engine, thread = _engine_with_active_feeder(["gain"], [{"plugin_id": "gain", "parameters": {}}])
    with pytest.raises(IndexError):
        engine.insert_plugin("feeder", 9, {"plugin_id": "eq_parametric", "parameters": {}})
    thread.request_plugin_insert.assert_not_called()


def test_insert_plugin_returns_none_for_inactive_target():
    engine = AudioEngine()
    assert engine.insert_plugin("feeder", 0, {"plugin_id": "gain", "parameters": {}}) is None


def test_insert_plugin_unknown_plugin_id_raises_value_error():
    engine, thread = _engine_with_active_feeder(["gain"], [{"plugin_id": "gain", "parameters": {}}])
    with pytest.raises(ValueError):
        engine.insert_plugin("feeder", 0, {"plugin_id": "no-existe", "parameters": {}})
    thread.request_plugin_insert.assert_not_called()


def test_remove_plugin_stages_via_worker_and_returns_latency():
    engine, thread = _engine_with_active_feeder(
        ["gain", "eq"],
        [{"plugin_id": "gain", "parameters": {}}, {"plugin_id": "eq_parametric", "parameters": {}}],
    )

    latency = engine.remove_plugin("feeder", 1)

    assert latency == 0.0
    thread.request_plugin_remove.assert_called_once_with(1)


def test_remove_plugin_writes_through_to_stored_config():
    engine, thread = _engine_with_active_feeder(
        ["gain", "eq"],
        [{"plugin_id": "gain", "parameters": {}}, {"plugin_id": "eq_parametric", "parameters": {}}],
    )

    engine.remove_plugin("feeder", 0)

    assert engine._configs["feeder"]["plugin_configs"] == [{"plugin_id": "eq_parametric", "parameters": {}}]


def test_remove_plugin_bad_index_raises():
    engine, thread = _engine_with_active_feeder(["gain"], [{"plugin_id": "gain", "parameters": {}}])
    with pytest.raises(IndexError):
        engine.remove_plugin("feeder", 9)
    thread.request_plugin_remove.assert_not_called()


def test_remove_plugin_returns_none_for_inactive_target():
    engine = AudioEngine()
    assert engine.remove_plugin("feeder", 0) is None


def test_remove_plugin_leaving_empty_chain_returns_zero_latency():
    engine, thread = _engine_with_active_feeder(["gain"], [{"plugin_id": "gain", "parameters": {}}])

    latency = engine.remove_plugin("feeder", 0)

    assert latency == 0.0
    assert engine._configs["feeder"]["plugin_configs"] == []
