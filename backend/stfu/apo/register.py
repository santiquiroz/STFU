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


_CREATE_NO_WINDOW = 0x0800_0000


def _run_quiet(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """subprocess robusto en proceso sin consola: redirige los 3 handles a
    DEVNULL (heredar los handles inválidos del padre da WinError 50) y evita
    abrir una ventana."""
    return subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_CREATE_NO_WINDOW,
        **kw,
    )


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


def _read_effect_list(path: str, prop: str) -> list[str]:
    """Lee la lista de CLSID de APOs (REG_MULTI_SZ) del endpoint."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, path, 0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_WOW64_64KEY,
        ) as k:
            val, typ = winreg.QueryValueEx(k, prop)
            if typ == winreg.REG_MULTI_SZ:
                return [c for c in val if c]
            if isinstance(val, str) and val:
                return [val]
    except (FileNotFoundError, OSError):
        pass
    return []


def register_apo(endpoint_guid: str, flow: str, apo_clsid: str) -> None:
    """Añade stfu_apo.dll a la cadena de efectos del endpoint. Requiere admin.

    Windows 10/11 lee PKEY_CompositeFX como REG_MULTI_SZ (lista de CLSIDs). Se
    ANTEPONE el nuestro preservando los del fabricante, con backup para restaurar.
    """
    dll = _stage_apo_dll()
    _run_quiet(["regsvr32", "/s", str(dll)], check=True, timeout=30)

    path = _fx_props_path(endpoint_guid, flow)
    prop = _clsid_prop(flow)
    existing = _read_effect_list(path, prop)

    backups = _load_backups()
    key = _backup_key(endpoint_guid, flow)
    if key not in backups:
        backups[key] = existing
        _save_backups(backups)

    others = [c for c in existing if c.lower() != apo_clsid.lower()]
    new_list = [apo_clsid, *others]
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE, path, 0,
        winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
    ) as k:
        winreg.SetValueEx(k, prop, 0, winreg.REG_MULTI_SZ, new_list)
    _restart_audio_service()


def unregister_apo(endpoint_guid: str, flow: str) -> None:
    """Restaura la cadena de efectos previa del endpoint. Requiere admin."""
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
                winreg.SetValueEx(k, prop, 0, winreg.REG_MULTI_SZ, previous)
            else:
                winreg.DeleteValue(k, prop)
            changed = True
    except FileNotFoundError:
        pass
    _save_backups(backups)
    if changed:
        _restart_audio_service()


def get_apo_status(endpoint_guid: str, flow: str, apo_clsid: str | None = None) -> dict:
    path = _fx_props_path(endpoint_guid, flow)
    effects = _read_effect_list(path, _clsid_prop(flow))
    if not effects:
        return {"registered": False, "clsid": None}
    mine = effects[0]
    if apo_clsid is not None:
        registered = any(c.lower() == apo_clsid.lower() for c in effects)
        return {"registered": registered, "clsid": mine}
    return {"registered": True, "clsid": mine}


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
    """Reinicia audiosrv para que audiodg recargue el APO.

    `net stop audiosrv` PIDE confirmación de servicios dependientes por stdin
    y cuelga para siempre sin consola interactiva. Restart-Service -Force los
    maneja sin prompt; stdin cerrado + timeout garantizan que nunca se cuelgue.
    """
    try:
        _run_quiet(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Restart-Service -Name Audiosrv -Force -ErrorAction Stop"],
            check=False, timeout=90,
        )
    except subprocess.TimeoutExpired:
        _log.warning("Restart-Service audiosrv excedió el timeout; el APO se "
                     "aplicará en la próxima sesión de audio")
