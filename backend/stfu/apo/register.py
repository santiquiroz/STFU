"""Register and unregister STFU APO COM DLL on Windows audio endpoints."""
import subprocess
import winreg
from pathlib import Path

from stfu.apo.endpoint_finder import _flow_key, _MFX_CLSID_PROP, _SFX_CLSID_PROP

_APO_DLL = Path(__file__).parent.parent.parent.parent / "apo" / "build" / "stfu_apo.dll"


def _fx_props_path(endpoint_guid: str, flow: str) -> str:
    return f"{_flow_key(flow)}\\{{{endpoint_guid}}}\\FxProperties"


def _clsid_prop(flow: str) -> str:
    return _MFX_CLSID_PROP if flow == "Capture" else _SFX_CLSID_PROP


def register_apo(endpoint_guid: str, flow: str, apo_clsid: str) -> None:
    """Register stfu_apo.dll on the endpoint. Requires admin rights."""
    subprocess.run(["regsvr32", "/s", str(_APO_DLL)], check=True)
    path = _fx_props_path(endpoint_guid, flow)
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE, path, 0,
        winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
    ) as k:
        winreg.SetValueEx(k, _clsid_prop(flow), 0, winreg.REG_SZ, apo_clsid)
    _restart_audio_service()


def unregister_apo(endpoint_guid: str, flow: str) -> None:
    """Remove STFU APO from endpoint. Requires admin rights."""
    path = _fx_props_path(endpoint_guid, flow)
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, path, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
        ) as k:
            winreg.DeleteValue(k, _clsid_prop(flow))
    except FileNotFoundError:
        pass
    _restart_audio_service()


def get_apo_status(endpoint_guid: str, flow: str) -> dict:
    path = _fx_props_path(endpoint_guid, flow)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            clsid, _ = winreg.QueryValueEx(k, _clsid_prop(flow))
            return {"registered": True, "clsid": clsid}
    except (FileNotFoundError, OSError):
        return {"registered": False, "clsid": None}


def _restart_audio_service() -> None:
    subprocess.run(["net", "stop", "audiosrv"], check=False, capture_output=True)
    subprocess.run(["net", "start", "audiosrv"], check=True, capture_output=True)
