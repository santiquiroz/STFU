import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException
from stfu.core.pipeline_factory import default_registry
from stfu.hub.manager import HubManager, Sha256Mismatch

router = APIRouter()


def _curated_dir() -> Path:
    # PyInstaller onedir: los datos van junto al ejecutable
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "stfu" / "hub" / "curated"
    return Path(__file__).resolve().parents[2] / "hub" / "curated"


def _hub() -> HubManager:
    return HubManager(default_registry(), _curated_dir())


def _active_model_ids() -> set[str]:
    from stfu.audio.engine import engine
    ids = set()
    for target in engine.active_targets():
        ids |= engine.active_model_ids(target)
    return ids


@router.get("/models")
def list_models():
    return _hub().catalog()


@router.post("/models/{model_id}/download")
def download_model(model_id: str):
    try:
        path = _hub().download(model_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Sha256Mismatch as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"installed": True, "path": str(path)}


@router.delete("/models/{model_id}")
def delete_model(model_id: str):
    try:
        _hub().delete(model_id, _active_model_ids())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"deleted": True}
