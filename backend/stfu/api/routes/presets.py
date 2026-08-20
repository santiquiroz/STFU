import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError
from stfu.presets.store import PresetSpec, PresetStore

router = APIRouter()


def _curated_dir() -> Path:
    # PyInstaller onedir: los datos van junto al ejecutable
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "stfu" / "presets" / "curated"
    return Path(__file__).resolve().parents[2] / "presets" / "curated"


_curated_store = PresetStore(_curated_dir())
_user_store = PresetStore(Path.home() / ".stfu" / "presets")


class PresetUpdate(BaseModel):
    plugins: list[dict] = []


def _to_payload(preset: PresetSpec, builtin: bool) -> dict:
    return {"name": preset.name, "plugins": preset.plugins, "builtin": builtin}


def _find_curated(name: str) -> PresetSpec | None:
    # Los archivos curados usan slugs ASCII (gaming.json, musica.json...)
    # pero el "name" mostrado/buscado es el nombre en español (p.ej.
    # "Música"): no se puede resolver por stem de archivo, hay que
    # buscar por el campo name entre los presets curados cargados.
    return next((p for p in _curated_store.list() if p.name == name), None)


@router.get("/presets")
def list_presets():
    curated = [_to_payload(p, True) for p in _curated_store.list()]
    user = [_to_payload(p, False) for p in _user_store.list()]
    return curated + user


@router.get("/presets/{name}")
def get_preset(name: str):
    # Un name con forma de traversal (".."/"%2e%2e") hace que _user_store.get
    # levante ValueError en _assert_contained: un nombre inválido simplemente
    # no existe → 404 (espeja el manejo de delete_preset).
    try:
        preset = _user_store.get(name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"preset {name!r} no encontrado")
    if preset is not None:
        return _to_payload(preset, False)
    preset = _find_curated(name)
    if preset is not None:
        return _to_payload(preset, True)
    raise HTTPException(status_code=404, detail=f"preset {name!r} no encontrado")


@router.post("/presets/{name}")
def save_preset(name: str, body: PresetUpdate):
    # Los nombres curados quedan reservados: guardar un shadow de usuario
    # crearía un huérfano imborrable (delete chequea curados primero → 409).
    if _find_curated(name) is not None:
        raise HTTPException(status_code=409, detail="Ya existe un preset predefinido con ese nombre")
    # PresetSpec se construye a mano (no viene del body-parsing de FastAPI),
    # así que su ValidationError no se auto-traduce: hay que mapearlo a 400.
    try:
        preset = PresetSpec(name=name, plugins=body.plugins)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _user_store.save(preset)
    return _to_payload(preset, False)


@router.delete("/presets/{name}")
def delete_preset(name: str):
    if _find_curated(name) is not None:
        raise HTTPException(status_code=409, detail=f"preset curado {name!r} no se puede borrar")
    try:
        _user_store.delete(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"deleted": name}
