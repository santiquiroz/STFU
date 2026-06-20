from pathlib import Path
from fastapi import APIRouter
from stfu.hub.registry import ModelRegistry

router = APIRouter()
_registry = ModelRegistry(Path.home() / ".stfu" / "models")


@router.get("/models")
def list_models():
    return [m.model_dump() for m in _registry.list()]
