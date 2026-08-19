import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from stfu.audio.engine import engine

_log = logging.getLogger(__name__)
router = APIRouter()


class PluginConfig(BaseModel):
    plugin_id: str
    parameters: dict = {}


class PipelineConfig(BaseModel):
    plugins: list[PluginConfig]
    input_device_id: int
    output_device_id: int


@router.post("/pipeline/{target}")
def configure_pipeline(target: str, config: PipelineConfig):
    if target not in ("mic", "speaker"):
        raise HTTPException(status_code=400, detail="target must be 'mic' or 'speaker'")
    if not config.plugins:
        engine.stop(target)
        return {"ok": True, "target": target, "active": False}
    try:
        latency_ms = engine.start(
            target=target,
            input_device_id=config.input_device_id,
            output_device_id=config.output_device_id,
            plugin_configs=[p.model_dump() for p in config.plugins],
        )
        return {"ok": True, "target": target, "active": True, "latency_ms": latency_ms}
    except Exception as exc:
        _log.exception("fallo al iniciar pipeline %s", target)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/pipeline/{target}")
def stop_pipeline(target: str):
    if target not in ("mic", "speaker"):
        raise HTTPException(status_code=400, detail="target must be 'mic' or 'speaker'")
    engine.stop(target)
    return {"ok": True, "target": target, "active": False}


class ParameterUpdate(BaseModel):
    plugin_index: int
    parameter_id: str
    value: float


@router.post("/pipeline/{target}/parameter")
def set_parameter(target: str, update: ParameterUpdate):
    if target not in ("mic", "speaker"):
        raise HTTPException(status_code=400, detail="target must be 'mic' or 'speaker'")
    try:
        ok = engine.set_parameter(target, update.plugin_index, update.parameter_id, update.value)
    except (IndexError, ValueError, ZeroDivisionError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=404, detail=f"pipeline '{target}' no está activo")
    return {"ok": True, "target": target, "parameter_id": update.parameter_id, "value": update.value}


@router.get("/pipeline/active")
def active_pipelines():
    return {"active": engine.active_targets()}


class BypassUpdate(BaseModel):
    on: bool


@router.post("/pipeline/{target}/bypass")
def set_bypass(target: str, update: BypassUpdate):
    if target not in ("mic", "speaker"):
        raise HTTPException(status_code=400, detail="target must be 'mic' or 'speaker'")
    ok = engine.set_bypass(target, update.on)
    if not ok:
        raise HTTPException(status_code=404, detail=f"pipeline '{target}' no está activo")
    return {"ok": True, "target": target, "bypass": update.on}
