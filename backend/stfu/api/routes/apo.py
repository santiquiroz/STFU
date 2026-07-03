from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from stfu.apo.apo_engine import apo_engine
from stfu.apo.constants import CLSID_BY_FLOW
from stfu.apo.endpoint_finder import find_endpoint_guid
from stfu.apo.register import (
    enable_unsigned_apos,
    get_apo_status,
    get_unsigned_apo_enabled,
    register_apo,
    unregister_apo,
)

router = APIRouter(prefix="/apo", tags=["apo"])


class ApoRegisterRequest(BaseModel):
    flow: Literal["Capture", "Render"]
    device_name: str      # substring match
    apo_clsid: str = ""   # vacío = CLSID oficial de STFU para ese flow


class ApoBridgeRequest(BaseModel):
    plugins: list[dict] = []


def _resolve_guid(device_name: str, flow: str) -> str:
    guid = find_endpoint_guid(device_name, flow)
    if guid is None:
        raise HTTPException(400, f"Dispositivo no encontrado: {device_name}")
    return guid


@router.get("/status/{flow}")
def apo_status(flow: Literal["Capture", "Render"], device_name: str):
    guid = _resolve_guid(device_name, flow)
    return get_apo_status(guid, flow)


@router.post("/register")
def apo_register(req: ApoRegisterRequest):
    guid = _resolve_guid(req.device_name, req.flow)
    clsid = req.apo_clsid or CLSID_BY_FLOW[req.flow]
    try:
        register_apo(guid, req.flow, clsid)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "endpoint_guid": guid, "clsid": clsid}


@router.get("/unsigned")
def unsigned_status():
    return {"enabled": get_unsigned_apo_enabled()}


@router.post("/unsigned")
def unsigned_enable():
    try:
        enable_unsigned_apos()
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "enabled": True}


@router.get("/bridge")
def bridge_status():
    return {"active": apo_engine.status()}


@router.post("/bridge/{flow}")
def bridge_start(flow: Literal["Capture", "Render"], req: ApoBridgeRequest):
    try:
        apo_engine.start(flow, req.plugins)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "flow": flow}


@router.delete("/bridge/{flow}")
def bridge_stop(flow: Literal["Capture", "Render"]):
    apo_engine.stop(flow)
    return {"ok": True, "flow": flow}


@router.delete("/register/{flow}")
def apo_unregister(flow: Literal["Capture", "Render"], device_name: str):
    guid = _resolve_guid(device_name, flow)
    try:
        unregister_apo(guid, flow)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True}
