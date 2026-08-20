import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException
from stfu.core.pipeline_factory import default_registry
from stfu.hub.download_jobs import start_download_job
from stfu.hub.manager import HubManager

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


@router.post("/models/{model_id}/download", status_code=202)
def download_model(model_id: str):
    hub = _hub()
    if not hub.is_curated(model_id):
        raise HTTPException(status_code=404, detail=f"modelo {model_id!r} no está en el catálogo")
    job_id = start_download_job(hub, model_id)
    return {"job_id": job_id}


@router.delete("/models/{model_id}")
def delete_model(model_id: str):
    try:
        _hub().delete(model_id, _active_model_ids())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"deleted": True}


@router.post("/models/{model_id}/activate")
def activate_model(model_id: str, target: str = "mic", device: str = "auto"):
    from stfu.audio.engine import engine
    if not any(m["id"] == model_id and m["installed"] for m in _hub().catalog()):
        raise HTTPException(status_code=404, detail=f"modelo {model_id!r} no instalado")
    if not engine.swap_model(target, model_id, device):
        raise HTTPException(status_code=409, detail=f"target {target!r} no está activo")
    return {"activated": model_id, "target": target}
