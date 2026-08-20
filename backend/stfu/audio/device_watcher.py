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
        ni sleep: el test llama tick() directamente tras flipear el provider.

        Un combo headset cambia input Y output default en el MISMO tick: se
        calcula el par (nuevo input, nuevo output) por target una sola vez y
        se emite UN solo restart_with_devices por target afectado, nunca dos
        (dos restarts secuenciales = dos ciclos de cierre/apertura de
        dispositivo = dos glitches de audio por el mismo evento)."""
        new_defaults = self._safe_defaults()
        old_defaults = self._last_defaults
        self._last_defaults = new_defaults
        if old_defaults is None or new_defaults == old_defaults:
            return
        old_in, old_out = old_defaults
        new_in, new_out = new_defaults
        input_changed = new_in != old_in and old_in is not None and new_in is not None
        output_changed = new_out != old_out and old_out is not None and new_out is not None
        if not input_changed and not output_changed:
            return
        for target in self._engine.active_targets():
            self._restart_target_if_affected(
                target, old_in, new_in, old_out, new_out, input_changed, output_changed,
            )

    def _restart_target_if_affected(
        self,
        target: str,
        old_in: int | None,
        new_in: int | None,
        old_out: int | None,
        new_out: int | None,
        input_changed: bool,
        output_changed: bool,
    ) -> None:
        # Solo sigue streams que estaban EXACTAMENTE en el default viejo: un
        # device explícito elegido por el usuario no se toca aunque coincida
        # con el default de otra dirección, ni se hijackea si nunca fue el
        # default (nunca lo comparamos contra nada más que old_defaults).
        devices = self._engine.current_devices(target)
        if devices is None:
            return
        current_in, current_out = devices
        kwargs = {}
        if input_changed and current_in == old_in:
            kwargs["input_device_id"] = new_in
        if output_changed and current_out == old_out:
            kwargs["output_device_id"] = new_out
        if not kwargs:
            return
        self._restart_target(target, kwargs)

    def _restart_target(self, target: str, kwargs: dict) -> None:
        try:
            self._engine.restart_with_devices(target, **kwargs)
            _log.info("target '%s' reiniciado: default cambió (%s)", target, kwargs)
        except Exception:
            _log.exception("fallo al reiniciar target '%s' tras cambio de default", target)

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
