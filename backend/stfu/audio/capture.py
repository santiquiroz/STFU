import queue
import time
import numpy as np
import sounddevice as sd
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline

_OUTPUT_QUEUE_SIZE = 8


def _query_device_rate(device_id: int, fallback: int) -> int:
    try:
        return int(sd.query_devices(device_id)["default_samplerate"])
    except Exception:
        return fallback


def _upsample_nearest(audio: np.ndarray, factor: int) -> np.ndarray:
    """Nearest-neighbour upsampling — no allocations beyond the output buffer."""
    return np.repeat(audio, factor, axis=0)


def _downsample_decimate(audio: np.ndarray, factor: int) -> np.ndarray:
    """Integer decimation — takes every Nth sample."""
    return audio[::factor].copy()


def _resample(audio: np.ndarray, in_rate: int, out_rate: int) -> np.ndarray:
    if in_rate == out_rate:
        return audio
    if out_rate > in_rate and out_rate % in_rate == 0:
        return _upsample_nearest(audio, out_rate // in_rate)
    if in_rate > out_rate and in_rate % out_rate == 0:
        return _downsample_decimate(audio, in_rate // out_rate)
    # Non-integer ratio: use scipy polyphase resampler.
    from math import gcd
    from scipy.signal import resample_poly
    g = gcd(in_rate, out_rate)
    return resample_poly(audio, out_rate // g, in_rate // g, axis=0).astype(np.float32)


class CaptureThread:
    """Captures audio from input device, runs pipeline, plays back on output device.

    Opens InputStream at the device's native format (stereo WASAPI shared mode).
    Opens OutputStream at the output device's native sample rate so WASAPI accepts it.
    Resamples processed audio (pipeline output rate → output device rate) before queuing.
    If the output stream fails to open, processing continues without playback.
    """

    def __init__(
        self,
        input_device_id: int,
        output_device_id: int,
        fmt: AudioFormat,
        pipeline: Pipeline,
        out_channels: int | None = None,
    ) -> None:
        self._in = input_device_id
        self._out = output_device_id
        self._fmt = fmt
        self._pipeline = pipeline
        self._out_channels = out_channels if out_channels is not None else fmt.channels
        self._input_stream: sd.InputStream | None = None
        self._output_stream: sd.OutputStream | None = None
        self._queue: queue.Queue = queue.Queue(maxsize=_OUTPUT_QUEUE_SIZE)
        self._latency_ms: float = 0.0
        self._out_rate: int = fmt.sample_rate

    def start(self) -> None:
        self._pipeline.compile(self._fmt)

        # Query output device native rate so WASAPI accepts the format.
        self._out_rate = _query_device_rate(self._out, self._fmt.sample_rate)
        # blocksize proportional to input blocksize so latency stays consistent.
        out_blocksize = max(
            1,
            round(self._fmt.chunk_samples * self._out_rate / self._fmt.sample_rate),
        )

        try:
            self._output_stream = sd.OutputStream(
                device=self._out,
                samplerate=self._out_rate,
                channels=self._out_channels,
                dtype=self._fmt.dtype,
                blocksize=out_blocksize,
                callback=self._output_callback,
            )
            self._output_stream.start()
        except sd.PortAudioError:
            self._output_stream = None

        self._input_stream = sd.InputStream(
            device=self._in,
            samplerate=self._fmt.sample_rate,
            channels=self._fmt.channels,
            dtype=self._fmt.dtype,
            blocksize=self._fmt.chunk_samples,
            callback=self._input_callback,
        )
        self._input_stream.start()

    def stop(self) -> None:
        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
        if self._output_stream:
            self._output_stream.stop()
            self._output_stream.close()
            self._output_stream = None

    def _input_callback(
        self, indata: np.ndarray, frames: int, time_info, status
    ) -> None:
        t0 = time.perf_counter()
        processed = self._pipeline.process(indata.copy())
        if self._output_stream is not None:
            resampled = _resample(processed, self._fmt.sample_rate, self._out_rate)
            try:
                self._queue.put_nowait(resampled)
            except queue.Full:
                pass
        self._latency_ms = (time.perf_counter() - t0) * 1000.0

    def _output_callback(
        self, outdata: np.ndarray, frames: int, time_info, status
    ) -> None:
        try:
            audio = self._queue.get_nowait()
            _write_to_output(audio, outdata)
        except queue.Empty:
            outdata[:] = 0

    @property
    def measured_latency_ms(self) -> float:
        return self._latency_ms


def _write_to_output(processed: np.ndarray, outdata: np.ndarray) -> None:
    out_ch = outdata.shape[1]
    proc_ch = processed.shape[1]
    # Trim or pad to expected frame count (may differ by ±1 due to rounding).
    n = min(processed.shape[0], outdata.shape[0])
    outdata[:n] = _adjust_channels(processed[:n], out_ch)
    if n < outdata.shape[0]:
        outdata[n:] = 0


def _adjust_channels(audio: np.ndarray, out_ch: int) -> np.ndarray:
    proc_ch = audio.shape[1]
    if proc_ch == out_ch:
        return audio
    if proc_ch == 1 and out_ch > 1:
        return np.repeat(audio, out_ch, axis=1)
    return audio[:, :out_ch]
