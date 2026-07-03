import logging
import queue
import time
import numpy as np
import sounddevice as sd
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline

_log = logging.getLogger(__name__)

_OUTPUT_QUEUE_SIZE = 8
_PREFILL_CHUNKS = 2


def _wasapi_auto_convert() -> "sd.WasapiSettings | None":
    """AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM: Windows resamplea cualquier
    dispositivo al formato canónico del engine (requiere sounddevice >= 0.4.7)."""
    if not hasattr(sd, "WasapiSettings"):
        return None
    try:
        return sd.WasapiSettings(auto_convert=True)
    except Exception:
        return None


class CaptureThread:
    """Captures audio from input device, runs pipeline, plays back on output device.

    Both streams open at the engine's canonical format; WASAPI auto-convert
    performs SRC for devices with different native rates (192kHz mic, 44.1kHz
    output, etc). If the output stream fails to open, processing continues
    without playback and playback_active reports False.
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
        self._input_overflows: int = 0
        self._output_underflows: int = 0
        self._queue_drops: int = 0

    def start(self) -> None:
        self._pipeline.compile(self._fmt)
        self._prefill_queue()

        try:
            self._output_stream = sd.OutputStream(
                device=self._out,
                samplerate=self._fmt.sample_rate,
                channels=self._out_channels,
                dtype=self._fmt.dtype,
                blocksize=self._fmt.chunk_samples,
                latency="low",
                extra_settings=_wasapi_auto_convert(),
                callback=self._output_callback,
            )
            self._output_stream.start()
        except sd.PortAudioError:
            _log.warning("output stream failed to open (device %s); playback disabled", self._out, exc_info=True)
            self._output_stream = None

        try:
            self._input_stream = sd.InputStream(
                device=self._in,
                samplerate=self._fmt.sample_rate,
                channels=self._fmt.channels,
                dtype=self._fmt.dtype,
                blocksize=self._fmt.chunk_samples,
                latency="low",
                extra_settings=_wasapi_auto_convert(),
                callback=self._input_callback,
            )
            self._input_stream.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self._input_stream:
            self._input_stream.stop()
            self._input_stream.close()
            self._input_stream = None
        if self._output_stream:
            self._output_stream.stop()
            self._output_stream.close()
            self._output_stream = None

    def _prefill_queue(self) -> None:
        silence = np.zeros((self._fmt.chunk_samples, self._out_channels), dtype=np.float32)
        for _ in range(_PREFILL_CHUNKS):
            self._queue.put_nowait(silence.copy())

    def _input_callback(
        self, indata: np.ndarray, frames: int, time_info, status
    ) -> None:
        if status and status.input_overflow:
            self._input_overflows += 1
        t0 = time.perf_counter()
        processed = self._pipeline.process(indata.copy())
        if self._output_stream is not None:
            try:
                self._queue.put_nowait(processed)
            except queue.Full:
                self._queue_drops += 1
        self._latency_ms = (time.perf_counter() - t0) * 1000.0

    def _output_callback(
        self, outdata: np.ndarray, frames: int, time_info, status
    ) -> None:
        if status and status.output_underflow:
            self._output_underflows += 1
        try:
            audio = self._queue.get_nowait()
            _write_to_output(audio, outdata)
        except queue.Empty:
            self._output_underflows += 1
            outdata[:] = 0

    @property
    def measured_latency_ms(self) -> float:
        return self._latency_ms

    @property
    def playback_active(self) -> bool:
        return self._output_stream is not None

    @property
    def stats(self) -> dict:
        return {
            "playback_active": self.playback_active,
            "input_overflows": self._input_overflows,
            "output_underflows": self._output_underflows,
            "queue_drops": self._queue_drops,
            "queue_fill": self._queue.qsize(),
        }


def _write_to_output(processed: np.ndarray, outdata: np.ndarray) -> None:
    out_ch = outdata.shape[1]
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
