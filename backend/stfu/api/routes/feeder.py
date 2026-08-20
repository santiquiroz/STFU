"""Feeder del mic virtual: mic físico → DFN3 → 'STFU Audio Bridge' (driver v2).

Mientras el driver no existe, se puede apuntar a un dispositivo de salida de
prueba (parlantes) para oír el resultado y validar la cadena completa.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from stfu.api.routes.pipeline import BypassUpdate, ParameterUpdate, PluginConfig
from stfu.audio.devices import BRIDGE_RENDER_NAME, find_bridge_output
from stfu.audio.engine import engine

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/feeder", tags=["feeder"])

_TARGET = "feeder"
_DEFAULT_PLUGINS = [PluginConfig(plugin_id="deepfilternet3", parameters={"strength": 0.85})]


class FeederConfig(BaseModel):
    input_device_id: int
    plugins: list[PluginConfig] = _DEFAULT_PLUGINS
    # Si el bridge no está instalado, se usa este device para oír la prueba.
    test_output_device_id: int | None = None


def _feeder_playback_active() -> bool:
    stats = engine.get_stats().get(_TARGET)
    return bool(stats and stats.get("playback_active"))


@router.get("/status")
def feeder_status():
    bridge = find_bridge_output()
    active = _TARGET in engine.active_targets()
    runtime = engine.runtime_state(_TARGET) if active else None
    return {
        "bridge_present": bridge is not None,
        "bridge_name": BRIDGE_RENDER_NAME,
        "bridge_device_id": bridge.id if bridge else None,
        "active": active,
        # Distingue 'activo' de 'activo y saliendo audio': si el output stream
        # falló al abrir, el thread sigue registrado pero descarta el audio.
        "playback_active": _feeder_playback_active() if active else False,
        # Permite al frontend reconciliar slider/picker tras un reload o un
        # arranque out-of-session (otro cliente, o el DefaultDeviceWatcher).
        "strength": runtime["strength"] if runtime else None,
        "input_device_id": runtime["input_device_id"] if runtime else None,
    }


@router.post("/start")
def feeder_start(config: FeederConfig):
    bridge = find_bridge_output()
    output_id = bridge.id if bridge else config.test_output_device_id
    if output_id is None:
        raise HTTPException(
            400,
            "Driver STFU no instalado y sin dispositivo de prueba. "
            "Pasa test_output_device_id para oír la prueba por parlantes.",
        )
    try:
        latency = engine.start(
            target=_TARGET,
            input_device_id=config.input_device_id,
            output_device_id=output_id,
            plugin_configs=[p.model_dump() for p in config.plugins],
        )
    except ValueError as exc:
        # Config inválida del cliente (p.ej. plugin_id desconocido).
        raise HTTPException(400, str(exc))
    except Exception:
        _log.exception("fallo al iniciar feeder")
        raise HTTPException(500, "No se pudo iniciar el feeder (ver logs del servidor)")
    return {
        "ok": True,
        "using_bridge": bridge is not None,
        "output_device_id": output_id,
        "latency_ms": latency,
    }


@router.delete("/stop")
def feeder_stop():
    engine.stop(_TARGET)
    return {"ok": True}


@router.post("/parameter")
def feeder_parameter(update: ParameterUpdate):
    try:
        ok = engine.set_parameter(_TARGET, update.plugin_index, update.parameter_id, update.value)
    except (IndexError, ValueError, ZeroDivisionError, TypeError) as exc:
        raise HTTPException(400, str(exc))
    if not ok:
        raise HTTPException(404, "feeder no está activo")
    return {"ok": True}


@router.post("/bypass")
def feeder_bypass(update: BypassUpdate):
    ok = engine.set_bypass(_TARGET, update.on)
    if not ok:
        raise HTTPException(404, "feeder no está activo")
    return {"ok": True, "bypass": update.on}


class PluginInsert(BaseModel):
    index: int
    plugin_id: str
    parameters: dict = {}


@router.post("/plugin")
def feeder_insert_plugin(body: PluginInsert):
    """Inserta un plugin en la cadena viva sin reiniciar el feeder (sin
    corte de audio) — ver AudioEngine.insert_plugin."""
    try:
        latency = engine.insert_plugin(
            _TARGET, body.index,
            {"plugin_id": body.plugin_id, "parameters": body.parameters},
        )
    except (IndexError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    if latency is None:
        raise HTTPException(404, "feeder no está activo")
    return {"ok": True, "latency_ms": latency}


@router.delete("/plugin/{index}")
def feeder_remove_plugin(index: int):
    """Quita un plugin de la cadena viva sin reiniciar el feeder (sin corte
    de audio) — ver AudioEngine.remove_plugin."""
    try:
        latency = engine.remove_plugin(_TARGET, index)
    except IndexError as exc:
        raise HTTPException(400, str(exc))
    if latency is None:
        raise HTTPException(404, "feeder no está activo")
    return {"ok": True, "latency_ms": latency}
