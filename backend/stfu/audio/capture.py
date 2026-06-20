import queue
import time
import numpy as np
import sounddevice as sd
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline

_OUTPUT_QUEUE_SIZE = 8


class CaptureThread:
    """Captures audio from input device, runs pipeline, plays back on output device.

    Uses separate InputStream + OutputStream so input and output can run at
    different native sample rates (e.g. Blue Snowball at 48kHz, FiiO Q at 384kHz).
    Windows WASAPI shared mode handles the device-side SRC transparently.
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

    def start(self) -> None:
        self._pipeline.compile(self._fmt)

        # Start output stream first so it's ready when input arrives.
        # Open at fmt.sample_rate — Windows WASAPI handles SRC to device rate.
        try:
            self._output_stream = sd.OutputStream(
                device=self._out,
                samplerate=self._fmt.sample_rate,
                channels=self._out_channels,
                dtype=self._fmt.dtype,
                blocksize=self._fmt.chunk_samples,
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
            try:
                self._queue.put_nowait(processed)
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
    if proc_ch == out_ch:
        outdata[:] = processed
    elif proc_ch == 1 and out_ch > 1:
        outdata[:] = np.repeat(processed, out_ch, axis=1)
    else:
        outdata[:] = processed[:, :out_ch]
