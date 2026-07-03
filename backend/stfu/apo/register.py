"""Register and unregister STFU APO COM DLL on Windows audio endpoints."""
import json
import logging
import os
import shutil
import subprocess
import sys
import winreg
from pathlib import Path

from stfu.apo.endpoint_finder import _flow_key, _MFX_CLSID_PROP, _SFX_CLSID_PROP

_log = logging.getLogger(__name__)

# audiodg.exe (LocalService) carga la DLL: debe vivir en una ruta legible por
# todos. %LOCALAPPDATA% del usuario NO lo es → se copia a ProgramData.
_APO_MACHINE_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "STFU"
_APO_MACHINE_DLL = _APO_MACHINE_DIR / "stfu_apo.dll"


def _bundled_apo_dll() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller 6 onedir: binarios en _internal/ (sys._MEIPASS); onefile
        # y layouts viejos: junto al exe. Se prueban todas.
        candidates = [
            Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "stfu_apo.dll",
            Path(sys.executable).parent / "stfu_apo.dll",
            Path(sys.executable).parent / "_internal" / "stfu_apo.dll",
        ]
        return next((p for p in candidates if p.exists()), candidates[0])
    return Path(__file__).parent.parent.parent.parent / "apo" / "build" / "stfu_apo.dll"


def _stage_apo_dll() -> Path:
    """Copia la DLL a ProgramData (contexto elevado) y devuelve esa ruta."""
    src = _bundled_apo_dll()
    if not src.exists():
        raise FileNotFoundError(
            f"stfu_apo.dll no encontrado en {src} — compilar con apo/build.ps1"
        )
    _APO_MACHINE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, _APO_MACHINE_DLL)
    except (PermissionError, OSError):
        # ya cargada por audiodg de un registro previo: reusar la existente
        if not _APO_MACHINE_DLL.exists():
            raise
    return _APO_MACHINE_DLL
_BACKUP_FILE = Path.home() / ".stfu" / "apo_fx_backup.json"
_AUDIO_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Audio"


def _fx_props_path(endpoint_guid: str, flow: str) -> str:
    return f"{_flow_key(flow)}\\{endpoint_guid}\\FxProperties"


def _clsid_prop(flow: str) -> str:
    return _MFX_CLSID_PROP if flow == "Capture" else _SFX_CLSID_PROP


def _load_backups() -> dict:
    try:
        return json.loads(_BACKUP_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_backups(backups: dict) -> None:
    _BACKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    _BACKUP_FILE.write_text(json.dumps(backups, indent=2))


def _backup_key(endpoint_guid: str, flow: str) -> str:
    return f"{endpoint_guid}|{flow}"


def register_apo(endpoint_guid: str, flow: str, apo_clsid: str) -> None:
    """Register stfu_apo.dll on the endpoint. Requires admin rights.

    Guarda el CLSID previo del endpoint (si existía) para poder restaurarlo:
    sobrescribir FxProperties sin backup puede dejar sin efectos el APO del
    fabricante del dispositivo.
    """
    dll = _stage_apo_dll()
    subprocess.run(["regsvr32", "/s", str(dll)], check=True)

    path = _fx_props_path(endpoint_guid, flow)
    prop = _clsid_prop(flow)
    previous = get_apo_status(endpoint_guid, flow).get("clsid")
    backups = _load_backups()
    key = _backup_key(endpoint_guid, flow)
    if key not in backups:
        backups[key] = previous
        _save_backups(backups)

    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE, path, 0,
        winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
    ) as k:
        winreg.SetValueEx(k, prop, 0, winreg.REG_SZ, apo_clsid)
    _restart_audio_service()


def unregister_apo(endpoint_guid: str, flow: str) -> None:
    """Restore the endpoint's previous APO (or remove ours). Requires admin."""
    path = _fx_props_path(endpoint_guid, flow)
    prop = _clsid_prop(flow)
    backups = _load_backups()
    key = _backup_key(endpoint_guid, flow)
    previous = backups.pop(key, None)

    changed = False
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, path, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
        ) as k:
            if previous:
                winreg.SetValueEx(k, prop, 0, winreg.REG_SZ, previous)
            else:
                winreg.DeleteValue(k, prop)
            changed = True
    except FileNotFoundError:
        pass
    _save_backups(backups)
    if changed:
        _restart_audio_service()


def get_apo_status(endpoint_guid: str, flow: str) -> dict:
    path = _fx_props_path(endpoint_guid, flow)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            clsid, _ = winreg.QueryValueEx(k, _clsid_prop(flow))
            return {"registered": True, "clsid": clsid}
    except (FileNotFoundError, OSError):
        return {"registered": False, "clsid": None}


def get_unsigned_apo_enabled() -> bool:
    """audiodg solo carga APOs firmados salvo DisableProtectedAudioDG=1."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _AUDIO_KEY) as k:
            val, _ = winreg.QueryValueEx(k, "DisableProtectedAudioDG")
            return int(val) == 1
    except (FileNotFoundError, OSError):
        return False


def enable_unsigned_apos() -> None:
    """Permite APOs sin firma (mismo mecanismo que Equalizer APO). Admin.

    Trade-off documentado: apps que exigen ruta de audio protegida pueden
    negarse a reproducir.
    """
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE, _AUDIO_KEY, 0,
        winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
    ) as k:
        winreg.SetValueEx(k, "DisableProtectedAudioDG", 0, winreg.REG_DWORD, 1)
    _log.warning("DisableProtectedAudioDG=1 — APOs sin firma habilitados")


def _restart_audio_service() -> None:
    subprocess.run(["net", "stop", "audiosrv"], check=False, capture_output=True)
    subprocess.run(["net", "start", "audiosrv"], check=True, capture_output=True)
