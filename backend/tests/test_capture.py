"""Tests del ciclo de vida de CaptureThread con sounddevice mockeado.

Ejercitan start/stop, degradación de playback, limpieza ante fallos y la muerte
controlada del worker — sin hardware de audio real (portables a CI headless).
"""
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import sounddevice as sd

from stfu.audio.capture import CaptureThread
from stfu.core.audio_format import AudioFormat


def _thread(pipeline=None) -> CaptureThread:
    return CaptureThread(
        input_device_id=0,
        output_device_id=0,
        fmt=AudioFormat(48000, 2, 960),
        pipeline=pipeline if pipeline is not None else MagicMock(),
        out_channels=2,
    )


def _patch_streams(output_factory=None, input_factory=None):
    out = output_factory or MagicMock(return_value=MagicMock(name="OutputStream"))
    inp = input_factory or MagicMock(return_value=MagicMock(name="InputStream"))
    return (
        patch("stfu.audio.capture.sd.OutputStream", out),
        patch("stfu.audio.capture.sd.InputStream", inp),
        patch("stfu.audio.capture._wasapi_auto_convert", return_value=None),
    )


def test_start_opens_streams_and_worker():
    p_out, p_in, p_conv = _patch_streams()
    with p_out as out, p_in as inp, p_conv:
        t = _thread()
        try:
            t.start()
            assert out.called and inp.called
            assert t.playback_active is True
            assert t._worker.is_alive()
        finally:
            t.stop()
    assert not t._worker or not t._worker.is_alive()


def test_output_portaudio_error_disables_playback_but_input_ok():
    failing_out = MagicMock(side_effect=sd.PortAudioError("no device"))
    p_out, p_in, p_conv = _patch_streams(output_factory=failing_out)
    with p_out, p_in as inp, p_conv:
        t = _thread()
        try:
            t.start()  # no debe propagar
            assert t.playback_active is False
            assert inp.called
        finally:
            t.stop()


def test_input_failure_calls_stop_and_reraises():
    out_stream = MagicMock(name="OutputStream")
    failing_in = MagicMock(side_effect=RuntimeError("input boom"))
    p_out, p_in, p_conv = _patch_streams(
        output_factory=MagicMock(return_value=out_stream), input_factory=failing_in
    )
    with p_out, p_in, p_conv:
        t = _thread()
        with pytest.raises(RuntimeError, match="input boom"):
            t.start()
        # el output abierto se cerró y el worker se detuvo (sin huérfano)
        out_stream.close.assert_called()
        assert t._worker is None


def test_stop_closes_both_streams_and_joins_worker():
    out_stream = MagicMock(name="OutputStream")
    in_stream = MagicMock(name="InputStream")
    p_out, p_in, p_conv = _patch_streams(
        output_factory=MagicMock(return_value=out_stream),
        input_factory=MagicMock(return_value=in_stream),
    )
    with p_out, p_in, p_conv:
        t = _thread()
        t.start()
        t.stop()
        out_stream.stop.assert_called()
        out_stream.close.assert_called()
        in_stream.stop.assert_called()
        in_stream.close.assert_called()
        assert t._worker is None


def test_output_start_portaudio_error_closes_stream():
    # constructor OK pero .start() falla -> debe cerrarse el stream (no fuga)
    out_stream = MagicMock(name="OutputStream")
    out_stream.start.side_effect = sd.PortAudioError("start failed")
    p_out, p_in, p_conv = _patch_streams(
        output_factory=MagicMock(return_value=out_stream)
    )
    with p_out, p_in, p_conv:
        t = _thread()
        try:
            t.start()
            assert t.playback_active is False
            out_stream.close.assert_called()
        finally:
            t.stop()


def test_output_non_portaudio_error_cleans_up_and_reraises():
    out_stream = MagicMock(name="OutputStream")
    out_stream.start.side_effect = ValueError("dtype invalido")
    p_out, p_in, p_conv = _patch_streams(
        output_factory=MagicMock(return_value=out_stream)
    )
    with p_out, p_in, p_conv:
        t = _thread()
        with pytest.raises(ValueError, match="dtype invalido"):
            t.start()
        out_stream.close.assert_called()  # el stream a medio abrir se cerró
        assert t._worker is None


def test_worker_failure_sets_flag_and_exits():
    pipeline = MagicMock()
    pipeline.process.side_effect = RuntimeError("plugin exploto")
    p_out, p_in, p_conv = _patch_streams()
    with p_out, p_in, p_conv:
        t = _thread(pipeline=pipeline)
        try:
            t.start()
            t._in_queue.put(np.zeros((960, 2), dtype=np.float32))
            deadline = time.time() + 3.0
            while not t.worker_failed and time.time() < deadline:
                time.sleep(0.02)
            assert t.worker_failed is True
            assert t.stats["worker_failed"] is True
        finally:
            t.stop()
