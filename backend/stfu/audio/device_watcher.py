"""Sigue el default input/output de Windows y reinicia los targets que
corrían sobre el default viejo cuando éste cambia (headset desconectado,
salida cambiada desde el sistema). Distinto del hotplug genérico: eso
reacciona a la lista completa de dispositivos, esto sigue puntualmente el id
del default actual y solo actúa sobre streams que estaban en ESE default.

Poll en vez de IMMNotificationClient (COM): un callback COM no dispara sin
hardware real ni un dispositivo virtual, así que no es testeable sin mockear
STA/pywin32 de punta a punta. Un poll de 1-2s es imperceptible para el
usuario (cambiar de auriculares no es latencia-crítico) y se testea
inyectando un `default_provider` fake, sin threads ni sleeps reales."""
import logging
import threading
from typing import Callable

from stfu.audio.devices import get_default_device_ids
from stfu.audio.engine import engine as _default_engine

_log = logging.getLogger(__name__)

_POLL_INTERVAL_S = 1.5

DefaultDeviceProvider = Callable[[], tuple[int | None, int | None]]


class DefaultDeviceWatcher:
    def __init__(
        self,
        engine=_default_engine,
        default_provider: DefaultDeviceProvider = get_default_device_ids,
        poll_interval_s: float = _POLL_INTERVAL_S,
    ) -> None:
        self._engine = engine
        self._default_provider = default_provider
        self._poll_interval_s = poll_interval_s
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # None hasta el primer tick/start: sin baseline no hay "cambio" que
        # detectar, evita un reinicio espurio contra el default inicial.
        self._last_defaults: tuple[int | None, int | None] | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._last_defaults = self._safe_defaults()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def tick(self) -> None:
        """Un ciclo de detección + reinicio. Público para testear sin thread
        ni sleep: el test llama tick() directamente tras flipear el provider."""
        new_defaults = self._safe_defaults()
        old_defaults = self._last_defaults
        self._last_defaults = new_defaults
        if old_defaults is None or new_defaults == old_defaults:
            return
        old_in, old_out = old_defaults
        new_in, new_out = new_defaults
        if new_in != old_in:
            self._restart_targets_on_old_default("input", old_in, new_in)
        if new_out != old_out:
            self._restart_targets_on_old_default("output", old_out, new_out)

    def _restart_targets_on_old_default(
        self, direction: str, old_id: int | None, new_id: int | None
    ) -> None:
        if old_id is None or new_id is None:
            return
        for target in self._engine.active_targets():
            if self._target_was_on_device(target, direction, old_id):
                self._restart_target(target, direction, new_id)

    def _target_was_on_device(self, target: str, direction: str, device_id: int) -> bool:
        # Solo sigue streams que estaban EXACTAMENTE en el default viejo: un
        # device explícito elegido por el usuario no se toca aunque coincida
        # con el default de otra dirección, ni se hijackea si nunca fue el
        # default (nunca lo comparamos contra nada más que old_defaults).
        devices = self._engine.current_devices(target)
        if devices is None:
            return False
        input_id, output_id = devices
        current_id = input_id if direction == "input" else output_id
        return current_id == device_id

    def _restart_target(self, target: str, direction: str, new_id: int) -> None:
        kwargs = {"input_device_id": new_id} if direction == "input" else {"output_device_id": new_id}
        try:
            self._engine.restart_with_devices(target, **kwargs)
            _log.info(
                "target '%s' reiniciado: default de %s cambió a device %s",
                target, direction, new_id,
            )
        except Exception:
            _log.exception(
                "fallo al reiniciar target '%s' tras cambio de default (%s)", target, direction
            )

    def _loop(self) -> None:
        while not self._stop_event.wait(self._poll_interval_s):
            try:
                self.tick()
            except Exception:
                _log.exception("device watcher tick falló")

    def _safe_defaults(self) -> tuple[int | None, int | None]:
        try:
            return self._default_provider()
        except Exception:
            _log.warning("no se pudo leer el default device actual", exc_info=True)
            return (None, None)


watcher = DefaultDeviceWatcher()
