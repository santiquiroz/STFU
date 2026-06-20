"""Find Windows audio endpoint GUIDs by device name."""
import winreg


_MMDEVICES_BASE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
_MFX_CLSID_PROP = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},6"
_SFX_CLSID_PROP = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},5"


def _flow_key(flow: str) -> str:
    """flow: 'Capture' or 'Render'"""
    return f"{_MMDEVICES_BASE}\\{flow}"


def find_endpoint_guid(device_name: str, flow: str) -> str | None:
    """Return the GUID string for the endpoint whose FriendlyName contains device_name."""
    base = _flow_key(flow)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as base_key:
            i = 0
            while True:
                try:
                    guid = winreg.EnumKey(base_key, i)
                    friendly = _read_friendly_name(base, guid)
                    if device_name.lower() in friendly.lower():
                        return guid
                    i += 1
                except OSError:
                    break
    except OSError:
        return None
    return None


def _read_friendly_name(base: str, guid: str) -> str:
    try:
        props_path = f"{base}\\{guid}\\Properties"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, props_path) as k:
            # PKEY_Device_FriendlyName = {a45c254e-df1c-4efd-8020-67d146a850e0},14
            val, _ = winreg.QueryValueEx(k, "{a45c254e-df1c-4efd-8020-67d146a850e0},14")
            return str(val)
    except OSError:
        return ""
