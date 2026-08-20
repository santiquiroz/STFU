"""Tests de DefaultDeviceWatcher con engine y default-device provider fake:
nunca toca hardware ni el sd real. tick() se llama directo, sin threads ni
sleeps -- ver DegradeMonitor/test_degrade_monitor.py para el mismo patrón."""
from stfu.audio.device_watcher import DefaultDeviceWatcher


class _FakeEngine:
    def __init__(self, targets: dict[str, tuple[int, int]]):
        self._targets = dict(targets)
        self.restarts: list[tuple[str, dict]] = []

    def active_targets(self) -> list[str]:
        return list(self._targets.keys())

    def current_devices(self, target: str):
        return self._targets.get(target)

    def restart_with_devices(self, target: str, **kwargs) -> float:
        current_in, current_out = self._targets[target]
        new_in = kwargs.get("input_device_id", current_in)
        new_out = kwargs.get("output_device_id", current_out)
        self._targets[target] = (new_in, new_out)
        self.restarts.append((target, kwargs))
        return 0.0


class _FakeDefaultProvider:
    """Callable mutable: el test lo flipea entre ticks para simular que
    Windows cambió el default input/output."""

    def __init__(self, initial: tuple[int | None, int | None]):
        self.value = initial

    def __call__(self):
        return self.value


def test_first_tick_establishes_baseline_without_restart():
    engine = _FakeEngine({"mic": (1, 2)})
    provider = _FakeDefaultProvider((1, 2))
    watcher = DefaultDeviceWatcher(engine=engine, default_provider=provider)
    watcher.tick()
    assert engine.restarts == []


def test_tick_restarts_target_on_default_input_change():
    engine = _FakeEngine({"mic": (1, 2)})
    provider = _FakeDefaultProvider((1, 2))
    watcher = DefaultDeviceWatcher(engine=engine, default_provider=provider)
    watcher.tick()  # baseline
    provider.value = (5, 2)  # usuario cambia de auriculares -> nuevo default input
    watcher.tick()
    assert engine.restarts == [("mic", {"input_device_id": 5})]
    assert engine.current_devices("mic") == (5, 2)


def test_tick_restarts_target_on_default_output_change():
    engine = _FakeEngine({"speaker": (1, 2)})
    provider = _FakeDefaultProvider((1, 2))
    watcher = DefaultDeviceWatcher(engine=engine, default_provider=provider)
    watcher.tick()  # baseline
    provider.value = (1, 9)  # usuario cambia de parlantes -> nuevo default output
    watcher.tick()
    assert engine.restarts == [("speaker", {"output_device_id": 9})]
    assert engine.current_devices("speaker") == (1, 9)


def test_tick_does_not_restart_when_default_unchanged():
    engine = _FakeEngine({"mic": (1, 2)})
    provider = _FakeDefaultProvider((1, 2))
    watcher = DefaultDeviceWatcher(engine=engine, default_provider=provider)
    watcher.tick()
    watcher.tick()
    watcher.tick()
    assert engine.restarts == []


def test_tick_does_not_hijack_target_on_explicit_non_default_device():
    # "mic" corre en el device 99, que nunca fue el default: un cambio de
    # default no debe tocarlo (el usuario lo eligió a mano).
    engine = _FakeEngine({"mic": (99, 2)})
    provider = _FakeDefaultProvider((1, 2))
    watcher = DefaultDeviceWatcher(engine=engine, default_provider=provider)
    watcher.tick()
    provider.value = (5, 2)
    watcher.tick()
    assert engine.restarts == []


def test_tick_only_restarts_targets_that_were_on_the_old_default():
    engine = _FakeEngine({"mic": (1, 2), "speaker": (99, 2)})
    provider = _FakeDefaultProvider((1, 2))
    watcher = DefaultDeviceWatcher(engine=engine, default_provider=provider)
    watcher.tick()
    provider.value = (5, 2)
    watcher.tick()
    assert engine.restarts == [("mic", {"input_device_id": 5})]


def test_tick_handles_provider_error_without_raising():
    engine = _FakeEngine({"mic": (1, 2)})

    def bad_provider():
        raise RuntimeError("no devices")

    watcher = DefaultDeviceWatcher(engine=engine, default_provider=bad_provider)
    watcher.tick()  # no debe lanzar
    watcher.tick()
    assert engine.restarts == []


def test_watcher_starts_and_stops_thread_cleanly():
    engine = _FakeEngine({})
    provider = _FakeDefaultProvider((1, 2))
    watcher = DefaultDeviceWatcher(engine=engine, default_provider=provider, poll_interval_s=0.05)
    watcher.start()
    assert watcher._thread is not None
    watcher.stop()
    assert watcher._thread is None


def test_watcher_start_is_idempotent():
    engine = _FakeEngine({})
    provider = _FakeDefaultProvider((1, 2))
    watcher = DefaultDeviceWatcher(engine=engine, default_provider=provider, poll_interval_s=0.05)
    watcher.start()
    first_thread = watcher._thread
    watcher.start()  # no debe reemplazar el thread vivo
    assert watcher._thread is first_thread
    watcher.stop()
