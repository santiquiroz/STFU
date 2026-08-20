"""AudioEngine.swap_model: write-through a _configs (mismo criterio que
set_parameter/insert_plugin/remove_plugin — ver test_set_parameter_writes_
through_to_stored_config en test_engine.py y test_engine_plugin_insert_
remove.py) preservando "parameters", y supervivencia del swap ante un
restart_with_devices posterior (regresión: swap_model NO escribía en
_configs, así que restart_with_devices reconstruía la cadena desde el
modelo de arranque y revertía en silencio un swap en vivo, o un downgrade
de DegradeMonitor bajo presión de CPU, en el próximo cambio de default
device)."""
from unittest.mock import MagicMock, patch
from stfu.audio.engine import AudioEngine
from stfu.core.audio_format import AudioFormat

_FMT = AudioFormat(48000, 1, 960)


class _FakeModelPlugin:
    """Doble mínimo del plugin devuelto por build_pipeline: swap_model solo
    lee preferred_format y llama setup() para el warmup."""

    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id
        self.preferred_format = _FMT
        self.setup_called_with = None

    def setup(self, fmt):
        self.setup_called_with = fmt
        return fmt


class _FakeStagedPipeline:
    """Doble reusado tanto para el pipeline que arma engine.start() (necesita
    total_latency_ms()) como para el staged de swap_model (necesita
    _plugins[0])."""

    def __init__(self, plugin_id: str):
        self._plugins = [_FakeModelPlugin(plugin_id)]

    def total_latency_ms(self) -> float:
        return 0.0


def _fake_build_pipeline(plugin_configs, registry=None, device="auto"):
    """Sustituye a build_pipeline (tanto el top-level de engine.py como el
    real de pipeline_factory usado dentro de swap_model) — evita tocar el
    ModelRegistry real (modelo no instalado en el entorno de test)."""
    return _FakeStagedPipeline(plugin_configs[0]["plugin_id"])


def _mock_capture_thread():
    """Factory que devuelve un CaptureThread mock nuevo por instancia
    (necesario para restart_with_devices, que crea un segundo thread)."""
    created = []

    def factory(**kwargs):
        m = MagicMock(name=f"CaptureThread{len(created)}")
        m.pipeline = MagicMock()
        created.append(m)
        return m

    return MagicMock(side_effect=factory), created


def test_swap_model_false_for_inactive_target():
    engine = AudioEngine()
    assert engine.swap_model("feeder", "model-b") is False


def test_swap_model_stages_via_worker_at_model_index():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2), \
         patch("stfu.audio.engine.build_pipeline", return_value=MagicMock(total_latency_ms=lambda: 0.0)), \
         patch("stfu.core.pipeline_factory.build_pipeline", side_effect=_fake_build_pipeline):
        engine = AudioEngine()
        engine.start(
            "feeder", input_device_id=1, output_device_id=2,
            plugin_configs=[{"plugin_id": "model:A", "parameters": {"strength": 0.5}}],
        )

        ok = engine.swap_model("feeder", "B")

        assert ok is True
        created[0].request_plugin_swap.assert_called_once()
        index_arg, plugin_arg = created[0].request_plugin_swap.call_args.args
        assert index_arg == 0
        assert plugin_arg.plugin_id == "model:B"
        assert plugin_arg.setup_called_with == _FMT  # warmup corrió antes del lock


def test_swap_model_writes_through_to_stored_config_preserving_parameters():
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2), \
         patch("stfu.audio.engine.build_pipeline", return_value=MagicMock(total_latency_ms=lambda: 0.0)), \
         patch("stfu.core.pipeline_factory.build_pipeline", side_effect=_fake_build_pipeline):
        engine = AudioEngine()
        engine.start(
            "feeder", input_device_id=1, output_device_id=2,
            plugin_configs=[{"plugin_id": "model:A", "parameters": {"strength": 0.5}}],
        )

        engine.swap_model("feeder", "B")

        assert engine._configs["feeder"]["plugin_configs"] == [
            {"plugin_id": "model:B", "parameters": {"strength": 0.5}},
        ]
        # runtime_state lee plugin_configs[0]["parameters"]["strength"]: debe
        # seguir viendo el strength preservado, no perderlo por el swap.
        assert engine.runtime_state("feeder") == {"input_device_id": 1, "strength": 0.5}


def test_swap_model_falls_back_to_index_zero_when_no_model_plugin_active():
    """Cadena sin modelo activo (solo builtins): swap_model asume, por
    convención, que el modelo vive en el slot 0 (mismo criterio que
    runtime_state) y reemplaza ahí."""
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2), \
         patch("stfu.audio.engine.build_pipeline", return_value=MagicMock(total_latency_ms=lambda: 0.0)), \
         patch("stfu.core.pipeline_factory.build_pipeline", side_effect=_fake_build_pipeline):
        engine = AudioEngine()
        engine.start(
            "feeder", input_device_id=1, output_device_id=2,
            plugin_configs=[{"plugin_id": "gain", "parameters": {}}],
        )

        engine.swap_model("feeder", "B")

        index_arg, plugin_arg = created[0].request_plugin_swap.call_args.args
        assert index_arg == 0
        assert engine._configs["feeder"]["plugin_configs"] == [
            {"plugin_id": "model:B", "parameters": {}},
        ]


def test_swap_model_survives_restart_with_devices():
    """Regresión central del fix: un restart_with_devices (device-watcher
    tras desenchufar el headset) después de un swap_model en vivo debe
    reconstruir la cadena con el modelo YA SWAPEADO, no con el modelo de
    arranque."""
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2), \
         patch("stfu.audio.engine.build_pipeline", side_effect=_fake_build_pipeline), \
         patch("stfu.core.pipeline_factory.build_pipeline", side_effect=_fake_build_pipeline):
        engine = AudioEngine()
        engine.start(
            "feeder", input_device_id=1, output_device_id=2,
            plugin_configs=[{"plugin_id": "model:A", "parameters": {"strength": 0.5}}],
        )

        engine.swap_model("feeder", "B")
        assert len(created) == 1  # swap en vivo: sin nuevo CaptureThread

        engine.restart_with_devices("feeder", input_device_id=5)

        assert len(created) == 2  # restart sí abre un CaptureThread nuevo
        assert engine.current_devices("feeder") == (5, 2)
        assert engine._configs["feeder"]["plugin_configs"] == [
            {"plugin_id": "model:B", "parameters": {"strength": 0.5}},
        ]
        assert engine.runtime_state("feeder") == {"input_device_id": 5, "strength": 0.5}


def test_swap_model_second_call_uses_config_updated_by_first_swap():
    """El índice se busca contra _configs (fuente de verdad), no contra
    thread.pipeline._plugins (mock que nunca avanza, igual que en
    producción donde el worker recién lo aplica async) — dos swaps
    consecutivos deben encontrar el mismo slot 0 cada vez."""
    factory, created = _mock_capture_thread()
    with patch("stfu.audio.engine.CaptureThread", factory), \
         patch("stfu.audio.engine._out_channels_for_device", return_value=2), \
         patch("stfu.audio.engine.build_pipeline", return_value=MagicMock(total_latency_ms=lambda: 0.0)), \
         patch("stfu.core.pipeline_factory.build_pipeline", side_effect=_fake_build_pipeline):
        engine = AudioEngine()
        engine.start(
            "feeder", input_device_id=1, output_device_id=2,
            plugin_configs=[{"plugin_id": "model:A", "parameters": {"strength": 0.5}}],
        )

        engine.swap_model("feeder", "B")
        engine.swap_model("feeder", "C")

        assert created[0].request_plugin_swap.call_count == 2
        for call in created[0].request_plugin_swap.call_args_list:
            assert call.args[0] == 0
        assert engine._configs["feeder"]["plugin_configs"] == [
            {"plugin_id": "model:C", "parameters": {"strength": 0.5}},
        ]
