import time
import pytest
from stfu.audio.devices import DeviceInfo, list_devices, get_default_input, get_default_output
from stfu.audio.capture import CaptureThread
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline

def test_list_devices_nonempty():
    assert len(list_devices()) > 0

def test_device_fields():
    for d in list_devices():
        assert isinstance(d.id, int)
        assert isinstance(d.name, str)
        assert d.default_sample_rate > 0

def test_default_input_is_capture_device():
    d = get_default_input()
    assert d.channels_in > 0
    assert d.is_default_input is True

def test_default_output_is_render_device():
    d = get_default_output()
    assert d.channels_out > 0
    assert d.is_default_output is True

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
