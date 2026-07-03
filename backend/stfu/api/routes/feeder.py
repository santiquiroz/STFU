"""Feeder del mic virtual: mic físico → DFN3 → 'STFU Audio Bridge' (driver v2).

Mientras el driver no existe, se puede apuntar a un dispositivo de salida de
prueba (parlantes) para oír el resultado y validar la cadena completa.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from stfu.audio.devices import BRIDGE_RENDER_NAME, find_bridge_output
from stfu.audio.engine import engine

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/feeder", tags=["feeder"])

_TARGET = "feeder"


class FeederConfig(BaseModel):
    input_device_id: int
    plugins: list[dict] = [{"plugin_id": "deepfilternet3", "parameters": {"strength": 0.85}}]
    # Si el bridge no está instalado, se usa este device para oír la prueba.
    test_output_device_id: int | None = None


@router.get("/status")
def feeder_status():
    bridge = find_bridge_output()
    return {
        "bridge_present": bridge is not None,
        "bridge_name": BRIDGE_RENDER_NAME,
        "bridge_device_id": bridge.id if bridge else None,
        "active": _TARGET in engine.active_targets(),
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
            plugin_configs=config.plugins,
        )
    except Exception as exc:
        _log.exception("fallo al iniciar feeder")
        raise HTTPException(500, str(exc))
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
def feeder_parameter(plugin_index: int, parameter_id: str, value: float):
    if not engine.set_parameter(_TARGET, plugin_index, parameter_id, value):
        raise HTTPException(404, "feeder no está activo")
    return {"ok": True}
