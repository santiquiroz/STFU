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


def _resolve_default_ids() -> tuple[int, int]:
    raw = sd.default.device
    return int(raw[0]), int(raw[1])


def list_devices() -> list[DeviceInfo]:
    default_in, default_out = _resolve_default_ids()
    result = []
    for i, d in enumerate(sd.query_devices()):
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


def get_default_input() -> DeviceInfo:
    return next(d for d in list_devices() if d.is_default_input)


def get_default_output() -> DeviceInfo:
    return next(d for d in list_devices() if d.is_default_output)
