"""Tests de orquestación de AudioEngine con CaptureThread mockeado.

Verifican el ciclo de vida (start/stop/stop_all), el ruteo de parámetros y
_out_channels_for_device sin abrir dispositivos reales. La construcción del
pipeline se movió a stfu.core.pipeline_factory (ver test_pipeline_factory.py).
"""
from unittest.mock import MagicMock, patch

from stfu.audio.engine import AudioEngine, _out_channels_for_device


def _mock_capture_thread():
    """Factory que devuelve un CaptureThread mock nuevo por instancia."""
    created = []

    def factory(**kwargs):
        m = MagicMock(name=f"CaptureThread{len(created)}")
        # pipeline como mock: el ruteo de set_parameter no debe tocar el pipeline
        # real (vacío en estos tests, lanzaría IndexError).
        m.pipeline = MagicMock()
        created.append(m)
        return m

    return MagicMock(side_effect=factory), created


def test_out_channels_caps_at_two():
    with patch("stfu.audio.engine.sd.query_devices", return_value={"max_output_channels": 8}):
        assert _out_channels_for_device(0) == 2


def test_out_channels_defaults_to_two_on_error():
    with patch("stfu.audio.engine.sd.query_devices", side_effect=RuntimeError("bad device")):
        assert _out_channels_for_device(99) == 2


def test_start_registers_target_and_starts_thread():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2):
        engine = AudioEngine()
        latency = engine.start("feeder", input_device_id=1, output_device_id=2, plugin_configs=[])
        assert engine.active_targets() == ["feeder"]
        created[0].start.assert_called_once()
        assert latency == 0.0  # pipeline vacío


def test_start_replaces_and_stops_previous_thread():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2):
        engine = AudioEngine()
        engine.start("feeder", input_device_id=1, output_device_id=2, plugin_configs=[])
        engine.start("feeder", input_device_id=3, output_device_id=4, plugin_configs=[])
        created[0].stop.assert_called_once()  # el viejo se detuvo
        assert engine.active_targets() == ["feeder"]
        assert len(created) == 2


def test_stop_removes_target_and_stops_thread():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2):
        engine = AudioEngine()
        engine.start("feeder", input_device_id=1, output_device_id=2, plugin_configs=[])
        engine.stop("feeder")
        created[0].stop.assert_called_once()
        assert engine.active_targets() == []


def test_stop_all_clears_every_target():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2):
        engine = AudioEngine()
        engine.start("mic", input_device_id=1, output_device_id=2, plugin_configs=[])
        engine.start("speaker", input_device_id=3, output_device_id=4, plugin_configs=[])
        engine.stop_all()
        assert engine.active_targets() == []
        for t in created:
            t.stop.assert_called_once()


def test_set_parameter_false_for_missing_target():
    engine = AudioEngine()
    assert engine.set_parameter("feeder", 0, "strength", 0.5) is False


def test_set_parameter_routes_to_pipeline_for_active_target():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2):
        engine = AudioEngine()
        engine.start("feeder", input_device_id=1, output_device_id=2, plugin_configs=[])
        ok = engine.set_parameter("feeder", 0, "strength", 0.7)
        assert ok is True
        created[0].pipeline.set_parameter.assert_called_once_with(0, "strength", 0.7)


def test_current_devices_none_for_inactive_target():
    engine = AudioEngine()
    assert engine.current_devices("feeder") is None


def test_current_devices_returns_active_target_devices():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2):
        engine = AudioEngine()
        engine.start("feeder", input_device_id=1, output_device_id=2, plugin_configs=[])
        assert engine.current_devices("feeder") == (1, 2)


def test_restart_with_devices_noop_for_inactive_target():
    engine = AudioEngine()
    assert engine.restart_with_devices("feeder", input_device_id=5) is None


def test_restart_with_devices_swaps_input_and_stops_old_thread():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2):
        engine = AudioEngine()
        engine.start("feeder", input_device_id=1, output_device_id=2, plugin_configs=[])
        engine.restart_with_devices("feeder", input_device_id=5)
        assert engine.current_devices("feeder") == (5, 2)
        created[0].stop.assert_called_once()  # el viejo se paró
        assert len(created) == 2
        assert engine.active_targets() == ["feeder"]


def test_restart_with_devices_swaps_output_only():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2):
        engine = AudioEngine()
        engine.start("feeder", input_device_id=1, output_device_id=2, plugin_configs=[])
        engine.restart_with_devices("feeder", output_device_id=9)
        assert engine.current_devices("feeder") == (1, 9)


def test_stop_clears_stored_config():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2):
        engine = AudioEngine()
        engine.start("feeder", input_device_id=1, output_device_id=2, plugin_configs=[])
        engine.stop("feeder")
        assert engine.current_devices("feeder") is None
