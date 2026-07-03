"""Find Windows audio endpoint GUIDs by device name.

sounddevice muestra el endpoint como "Altavoces (2- FiiO Q series)", pero el
registro NO guarda ese string combinado: lo parte en DeviceDesc ("Altavoces")
y el nombre de interfaz del hardware ("FiiO Q series"). El matcher combina
ambas propiedades para reconocer el endpoint desde el nombre de sounddevice.
"""
import winreg

_MMDEVICES_BASE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
# Windows 10/11 lee los CLSID de APO bajo PKEY_CompositeFX (REG_MULTI_SZ),
# NO bajo las claves legacy PKEY_FX (REG_SZ, Win8.1). Verificado contra el
# endpoint Realtek: sus APOs viven en {d3993a3f...},5/6/7 como arrays.
_COMPOSITE_FX = "{d3993a3f-99c2-4402-b5ec-a92a0367664b}"
_SFX_CLSID_PROP = f"{_COMPOSITE_FX},5"   # PKEY_CompositeFX_StreamEffectClsid
_MFX_CLSID_PROP = f"{_COMPOSITE_FX},6"   # PKEY_CompositeFX_ModeEffectClsid
_EFX_CLSID_PROP = f"{_COMPOSITE_FX},7"   # PKEY_CompositeFX_EndpointEffectClsid

# Propiedades del endpoint en <guid>\Properties
_PROP_FRIENDLY = "{a45c254e-df1c-4efd-8020-67d146a850e0},14"  # nombre completo (a veces ausente)
_PROP_DESC = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"       # "Altavoces" / "Micrófono"
_PROP_IFACE = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"      # "FiiO Q series"

_STATE_ACTIVE = 1


def _flow_key(flow: str) -> str:
    """flow: 'Capture' or 'Render'"""
    return f"{_MMDEVICES_BASE}\\{flow}"


def _read_prop(props_path: str, prop: str) -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, props_path) as k:
            val, _ = winreg.QueryValueEx(k, prop)
            return str(val)
    except OSError:
        return ""


def _device_state(base: str, guid: str) -> int:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{guid}") as k:
            val, _ = winreg.QueryValueEx(k, "DeviceState")
            return int(val)
    except OSError:
        return -1


def _matches(device_name: str, props_path: str) -> bool:
    dn = device_name.lower()
    friendly = _read_prop(props_path, _PROP_FRIENDLY).lower()
    if friendly and (friendly in dn or dn in friendly):
        return True
    # el nombre de interfaz del hardware es el discriminante ("FiiO Q series")
    iface = _read_prop(props_path, _PROP_IFACE).lower()
    if iface and iface in dn:
        return True
    return False


def find_endpoint_guid(device_name: str, flow: str) -> str | None:
    """GUID del endpoint cuyo nombre coincide con el de sounddevice.
    Prefiere endpoints activos; cae a inactivos si no hay activo que calce."""
    base = _flow_key(flow)
    fallback: str | None = None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as base_key:
            i = 0
            while True:
                try:
                    guid = winreg.EnumKey(base_key, i)
                except OSError:
                    break
                i += 1
                if not _matches(device_name, f"{base}\\{guid}\\Properties"):
                    continue
                if _device_state(base, guid) == _STATE_ACTIVE:
                    return guid
                fallback = fallback or guid
    except OSError:
        return None
    return fallback


def _read_friendly_name(base: str, guid: str) -> str:
    """Nombre visible del endpoint, combinando DeviceDesc e interfaz."""
    props = f"{base}\\{guid}\\Properties"
    full = _read_prop(props, _PROP_FRIENDLY)
    if full:
        return full
    desc = _read_prop(props, _PROP_DESC)
    iface = _read_prop(props, _PROP_IFACE)
    if desc and iface:
        return f"{desc} ({iface})"
    return desc or iface
