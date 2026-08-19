from dataclasses import dataclass
import logging
import sounddevice as sd

_log = logging.getLogger(__name__)

# Nombre del endpoint render del driver virtual (v2) donde el feeder escribe el
# audio limpio. El driver lo enruta a "STFU Microphone" que las apps eligen.
BRIDGE_RENDER_NAME = "STFU Audio Bridge"


@dataclass
class DeviceInfo:
    id: int
    name: str
    channels_in: int
    channels_out: int
    default_sample_rate: int
    is_default_input: bool = False
    is_default_output: bool = False


def _wasapi_index() -> int | None:
    try:
        return next(
            (i for i, a in enumerate(sd.query_hostapis()) if "WASAPI" in a["name"]),
            None,
        )
    except Exception:
        return None


def _default_device_ids(wasapi_idx: int | None) -> tuple[int | None, int | None]:
    """Índices globales del default input/output del host API WASAPI.

    sd.default.device apunta al host API por defecto (MME en Windows, nombres
    truncados a ~31 chars); el host API WASAPI publica sus propios defaults
    con índice global — sin comparar strings."""
    if wasapi_idx is not None:
        try:
            api = sd.query_hostapis(wasapi_idx)
            din = api["default_input_device"]
            dout = api["default_output_device"]
            return (din if din >= 0 else None, dout if dout >= 0 else None)
        except Exception:
            _log.warning("query_hostapis(%s) falló", wasapi_idx, exc_info=True)
    try:
        raw = sd.default.device
        return int(raw[0]), int(raw[1])
    except Exception:
        _log.warning("sd.default.device no disponible", exc_info=True)
        return None, None


def list_devices() -> list[DeviceInfo]:
    wasapi_idx = _wasapi_index()
    default_in, default_out = _default_device_ids(wasapi_idx)
    result = []
    for i, d in enumerate(sd.query_devices()):
        if wasapi_idx is not None and d["hostapi"] != wasapi_idx:
            continue
        result.append(DeviceInfo(
            id=i,
            name=d["name"],
            channels_in=d["max_input_channels"],
            channels_out=d["max_output_channels"],
            default_sample_rate=int(d["default_samplerate"]),
            is_default_input=(i == default_in),
            is_default_output=(i == default_out),
        ))
    return result


def _first_or_raise(devices: list[DeviceInfo], has_channels, kind: str) -> DeviceInfo:
    device = next((d for d in devices if has_channels(d)), None)
    if device is None:
        raise RuntimeError(f"No hay dispositivo de audio de {kind} disponible")
    return device


def get_default_input() -> DeviceInfo:
    devices = list_devices()
    return (
        next((d for d in devices if d.is_default_input), None)
        or _first_or_raise(devices, lambda d: d.channels_in > 0, "entrada")
    )


def get_default_output() -> DeviceInfo:
    devices = list_devices()
    return (
        next((d for d in devices if d.is_default_output), None)
        or _first_or_raise(devices, lambda d: d.channels_out > 0, "salida")
    )


def find_output_by_name(substring: str) -> DeviceInfo | None:
    # Match por substring: el nombre WASAPI del endpoint puede llevar sufijos de
    # formato/instancia, así que el nombre exacto no es fiable.
    sub = substring.lower()
    return next(
        (d for d in list_devices() if d.channels_out > 0 and sub in d.name.lower()),
        None,
    )


def find_bridge_output() -> DeviceInfo | None:
    return find_output_by_name(BRIDGE_RENDER_NAME)
