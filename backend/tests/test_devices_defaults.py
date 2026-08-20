import sounddevice as sd
from stfu.audio import devices as dev


_HOSTAPIS = [
    {"name": "MME", "default_input_device": 0, "default_output_device": 1},
    {"name": "Windows WASAPI", "default_input_device": 3, "default_output_device": 4},
]

# El nombre MME está truncado (~31 chars) — con matching por nombre el
# default WASAPI jamás matchearía.
_DEVICES = [
    {"name": "Micrófono (USB Audio Device tru", "hostapi": 0, "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 44100.0},
    {"name": "Altavoces (USB Audio Device tru", "hostapi": 0, "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 44100.0},
    {"name": "Otro micrófono WASAPI de nombre largo", "hostapi": 1, "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 48000.0},
    {"name": "Micrófono (USB Audio Device true name)", "hostapi": 1, "max_input_channels": 2,
     "max_output_channels": 0, "default_samplerate": 192000.0},
    {"name": "Altavoces (USB Audio Device true name)", "hostapi": 1, "max_input_channels": 0,
     "max_output_channels": 2, "default_samplerate": 48000.0},
]


def _patch_sd(monkeypatch):
    monkeypatch.setattr(sd, "query_hostapis", lambda idx=None: _HOSTAPIS if idx is None else _HOSTAPIS[idx])
    monkeypatch.setattr(sd, "query_devices", lambda idx=None: _DEVICES if idx is None else _DEVICES[idx])


def test_default_flags_use_wasapi_hostapi_indices(monkeypatch):
    _patch_sd(monkeypatch)
    result = dev.list_devices()
    by_id = {d.id: d for d in result}
    assert by_id[3].is_default_input is True
    assert by_id[4].is_default_output is True
    assert by_id[2].is_default_input is False


def test_get_default_input_returns_wasapi_default(monkeypatch):
    _patch_sd(monkeypatch)
    assert dev.get_default_input().id == 3


def test_get_default_device_ids_returns_wasapi_defaults_directly(monkeypatch):
    _patch_sd(monkeypatch)
    assert dev.get_default_device_ids() == (3, 4)
