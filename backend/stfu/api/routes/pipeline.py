from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from stfu.audio.engine import engine

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
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/pipeline/{target}")
def stop_pipeline(target: str):
    if target not in ("mic", "speaker"):
        raise HTTPException(status_code=400, detail="target must be 'mic' or 'speaker'")
    engine.stop(target)
    return {"ok": True, "target": target, "active": False}


@router.get("/pipeline/active")
def active_pipelines():
    return {"active": engine.active_targets()}
