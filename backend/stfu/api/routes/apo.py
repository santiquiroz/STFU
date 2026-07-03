import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
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

_log = logging.getLogger(__name__)
router = APIRouter(prefix="/apo", tags=["apo"])


_GUID_RE = r"^\{[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$"


class ApoRegisterRequest(BaseModel):
    flow: Literal["Capture", "Render"]
    device_name: str      # substring match
    # vacío = CLSID oficial de STFU para ese flow; si viene, forma GUID estricta
    apo_clsid: str = Field(default="", pattern=f"(^$)|({_GUID_RE})")


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


def _needs_elevation(exc: Exception) -> bool:
    import subprocess
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, subprocess.CalledProcessError):
        return True  # regsvr32 sin admin
    winerror = getattr(exc, "winerror", None)
    return winerror == 5


@router.post("/register")
def apo_register(req: ApoRegisterRequest):
    guid = _resolve_guid(req.device_name, req.flow)
    clsid = req.apo_clsid or CLSID_BY_FLOW[req.flow]
    try:
        register_apo(guid, req.flow, clsid)
    except Exception as e:
        if not _needs_elevation(e):
            _log.exception("fallo en operacion APO")
            raise HTTPException(500, str(e))
        try:
            from stfu.apo.elevate import run_elevated
            run_elevated(["register", guid, req.flow, clsid])
        except Exception as e2:
            _log.exception("fallo en registro APO elevado")
            raise HTTPException(500, str(e2))
    return {"ok": True, "endpoint_guid": guid, "clsid": clsid}


@router.get("/unsigned")
def unsigned_status():
    return {"enabled": get_unsigned_apo_enabled()}


@router.post("/unsigned")
def unsigned_enable():
    try:
        enable_unsigned_apos()
    except Exception as e:
        if not _needs_elevation(e):
            _log.exception("fallo en operacion APO")
            raise HTTPException(500, str(e))
        try:
            from stfu.apo.elevate import run_elevated
            run_elevated(["enable-unsigned"])
        except Exception as e2:
            _log.exception("fallo habilitando APOs sin firma (elevado)")
            raise HTTPException(500, str(e2))
    return {"ok": True, "enabled": True}


@router.get("/bridge")
def bridge_status():
    return {"active": apo_engine.status()}


@router.post("/bridge/{flow}")
def bridge_start(flow: Literal["Capture", "Render"], req: ApoBridgeRequest):
    try:
        apo_engine.start(flow, req.plugins)
    except Exception as e:
        _log.exception("fallo en operacion APO")
        raise HTTPException(500, str(e))
    return {"ok": True, "flow": flow}


@router.delete("/bridge/{flow}")
def bridge_stop(flow: Literal["Capture", "Render"]):
    apo_engine.stop(flow)
    return {"ok": True, "flow": flow}


class BridgeParameterUpdate(BaseModel):
    plugin_index: int
    parameter_id: str
    value: float


@router.post("/bridge/{flow}/parameter")
def bridge_set_parameter(flow: Literal["Capture", "Render"], update: BridgeParameterUpdate):
    try:
        ok = apo_engine.set_parameter(flow, update.plugin_index, update.parameter_id, update.value)
    except IndexError as exc:
        raise HTTPException(400, str(exc))
    if not ok:
        raise HTTPException(404, f"bridge '{flow}' no está activo")
    return {"ok": True, "flow": flow, "parameter_id": update.parameter_id}


@router.delete("/register/{flow}")
def apo_unregister(flow: Literal["Capture", "Render"], device_name: str):
    guid = _resolve_guid(device_name, flow)
    try:
        unregister_apo(guid, flow)
    except Exception as e:
        if not _needs_elevation(e):
            _log.exception("fallo en operacion APO")
            raise HTTPException(500, str(e))
        try:
            from stfu.apo.elevate import run_elevated
            run_elevated(["unregister", guid, flow])
        except Exception as e2:
            _log.exception("fallo en unregister APO elevado")
            raise HTTPException(500, str(e2))
    return {"ok": True}
