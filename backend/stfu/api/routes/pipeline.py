from fastapi import APIRouter
from pydantic import BaseModel

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
    return {"ok": True, "target": target}
