from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from stfu.apo.endpoint_finder import find_endpoint_guid
from stfu.apo.register import get_apo_status, register_apo, unregister_apo

router = APIRouter(prefix="/apo", tags=["apo"])


class ApoRegisterRequest(BaseModel):
    flow: str           # "Capture" or "Render"
    device_name: str    # substring match
    apo_clsid: str      # e.g. "{XXXXXXXX-...}"


def _resolve_guid(device_name: str, flow: str) -> str:
    guid = find_endpoint_guid(device_name, flow)
    if guid is None:
        raise HTTPException(400, f"Dispositivo no encontrado: {device_name}")
    return guid


@router.get("/status/{flow}")
def apo_status(flow: str, device_name: str):
    guid = _resolve_guid(device_name, flow)
    return get_apo_status(guid, flow)


@router.post("/register")
def apo_register(req: ApoRegisterRequest):
    guid = _resolve_guid(req.device_name, req.flow)
    try:
        register_apo(guid, req.flow, req.apo_clsid)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "endpoint_guid": guid}


@router.delete("/register/{flow}")
def apo_unregister(flow: str, device_name: str):
    guid = _resolve_guid(device_name, flow)
    try:
        unregister_apo(guid, flow)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True}
