from dataclasses import dataclass
import sounddevice as sd


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


def _default_device_names() -> tuple[str, str]:
    try:
        raw = sd.default.device
        in_name = sd.query_devices(int(raw[0]))["name"]
        out_name = sd.query_devices(int(raw[1]))["name"]
        return in_name, out_name
    except Exception:
        return "", ""


def list_devices() -> list[DeviceInfo]:
    wasapi_idx = _wasapi_index()
    default_in_name, default_out_name = _default_device_names()
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
            is_default_input=(d["max_input_channels"] > 0 and d["name"] == default_in_name),
            is_default_output=(d["max_output_channels"] > 0 and d["name"] == default_out_name),
        ))
    return result


def get_default_input() -> DeviceInfo:
    devices = list_devices()
    return (
        next((d for d in devices if d.is_default_input), None)
        or next(d for d in devices if d.channels_in > 0)
    )


def get_default_output() -> DeviceInfo:
    devices = list_devices()
    return (
        next((d for d in devices if d.is_default_output), None)
        or next(d for d in devices if d.channels_out > 0)
    )
