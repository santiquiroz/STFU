"""Único módulo que conoce runtimes de inferencia.

Escalera de devices con probe: `auto` prueba NPU→GPU→CPU y se queda con el
primero que funciona; un device elegido a mano NO hace fallback silencioso —
el usuario lo eligió, un fallo debe ser visible. NPU se habilita en F2.5 vía
runtime packs (spec §3.3); mientras tanto existe en el enum pero sin EP.
"""
import logging
from typing import Callable

_log = logging.getLogger(__name__)

DEVICE_LADDER: dict[str, list[str]] = {
    "auto": ["npu", "gpu", "cpu"],
    "npu": ["npu"],
    "gpu": ["gpu"],
    "cpu": ["cpu"],
}

EP_BY_DEVICE: dict[str, str | None] = {
    "npu": None,  # F2.5: runtime packs (QNN / OpenVINO)
    "gpu": "DmlExecutionProvider",
    "cpu": "CPUExecutionProvider",
}


class DeviceUnavailable(RuntimeError):
    pass


def available_devices() -> list[str]:
    import onnxruntime as ort
    available = set(ort.get_available_providers())
    return [
        device for device, ep in EP_BY_DEVICE.items()
        if ep is not None and ep in available
    ]


def providers_for(device: str) -> list[str]:
    ep = EP_BY_DEVICE.get(device, "missing")
    if ep == "missing":
        raise ValueError(f"device desconocido: {device!r}")
    if ep is None:
        raise DeviceUnavailable(f"device {device!r} sin runtime instalado (llega en F2.5)")
    if ep == "CPUExecutionProvider":
        return [ep]
    return [ep, "CPUExecutionProvider"]


def select_device(device: str, probe: Callable[[list[str]], bool]) -> str:
    if device not in DEVICE_LADDER:
        raise ValueError(f"device desconocido: {device!r}")
    for candidate in DEVICE_LADDER[device]:
        try:
            providers = providers_for(candidate)
        except DeviceUnavailable:
            continue
        if probe(providers):
            _log.info("device seleccionado: %s (%s)", candidate, providers[0])
            return candidate
        _log.warning("probe falló para device %s", candidate)
    raise DeviceUnavailable(f"ningún device de la escalera {device!r} pasó el probe")
