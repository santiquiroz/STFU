import time
import pytest
from stfu.audio.devices import DeviceInfo, list_devices, get_default_input, get_default_output
from stfu.audio.capture import CaptureThread
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline


def _availability() -> tuple[bool, bool, bool]:
    try:
        devs = list_devices()
    except Exception:
        return False, False, False
    return (
        len(devs) > 0,
        any(d.channels_in > 0 for d in devs),
        any(d.channels_out > 0 for d in devs),
    )


_HAS_DEVICES, _HAS_INPUT, _HAS_OUTPUT = _availability()

# Estos tests ejercitan hardware de audio real. En CI headless / máquinas sin
# micrófono o sin salida, saltan de forma determinista en vez de fallar.
requires_devices = pytest.mark.skipif(not _HAS_DEVICES, reason="sin dispositivos de audio")
requires_input = pytest.mark.skipif(not _HAS_INPUT, reason="sin dispositivo de entrada")
requires_output = pytest.mark.skipif(not _HAS_OUTPUT, reason="sin dispositivo de salida")


@requires_devices
def test_list_devices_nonempty():
    assert len(list_devices()) > 0


def test_device_fields():
    for d in list_devices():
        assert isinstance(d.id, int)
        assert isinstance(d.name, str)
        assert d.default_sample_rate > 0


@requires_input
def test_default_input_is_capture_device():
    d = get_default_input()
    assert d.channels_in > 0


@requires_output
def test_default_output_is_render_device():
    d = get_default_output()
    assert d.channels_out > 0


@requires_input
@requires_output
def test_capture_thread_start_stop():
    fmt = AudioFormat(48000, 1, 960)
    thread = CaptureThread(
        input_device_id=get_default_input().id,
        output_device_id=get_default_output().id,
        fmt=fmt,
        pipeline=Pipeline(),
    )
    thread.start()
    time.sleep(0.3)
    thread.stop()


@requires_input
@requires_output
def test_capture_thread_measures_latency():
    fmt = AudioFormat(48000, 1, 960)
    thread = CaptureThread(
        input_device_id=get_default_input().id,
        output_device_id=get_default_output().id,
        fmt=fmt,
        pipeline=Pipeline(),
    )
    thread.start()
    time.sleep(0.3)
    latency = thread.measured_latency_ms
    thread.stop()
    assert latency >= 0.0


def test_get_default_input_raises_when_no_input():
    from stfu.audio import devices
    from unittest.mock import patch
    only_output = [DeviceInfo(id=0, name="spk", channels_in=0, channels_out=2, default_sample_rate=48000)]
    with patch.object(devices, "list_devices", return_value=only_output):
        with pytest.raises(RuntimeError, match="entrada"):
            devices.get_default_input()


def test_get_default_output_raises_when_no_output():
    from stfu.audio import devices
    from unittest.mock import patch
    only_input = [DeviceInfo(id=0, name="mic", channels_in=2, channels_out=0, default_sample_rate=48000)]
    with patch.object(devices, "list_devices", return_value=only_input):
        with pytest.raises(RuntimeError, match="salida"):
            devices.get_default_output()


def test_default_flags_use_wasapi_index_not_name():
    from stfu.audio import devices
    from unittest.mock import patch
    fake_devices = [
        {"name": "Mic largo con nombre que MME truncaria a 31 chars", "hostapi": 2,
         "max_input_channels": 2, "max_output_channels": 0, "default_samplerate": 48000.0},
        {"name": "Speaker largo con nombre que MME truncaria", "hostapi": 2,
         "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000.0},
    ]
    fake_hostapis = [{"name": "MME"}, {"name": "DirectSound"}, {"name": "Windows WASAPI"}]

    def fake_query_hostapis(idx=None):
        if idx is None:
            return fake_hostapis
        return {"default_input_device": 0, "default_output_device": 1}

    with patch.object(devices.sd, "query_devices", return_value=fake_devices), \
         patch.object(devices.sd, "query_hostapis", side_effect=fake_query_hostapis):
        result = devices.list_devices()

    assert result[0].is_default_input is True
    assert result[0].is_default_output is False
    assert result[1].is_default_output is True
    assert result[1].is_default_input is False
