import time
import numpy as np
import sounddevice as sd
from stfu.core.audio_format import AudioFormat
from stfu.core.pipeline import Pipeline


class CaptureThread:
    def __init__(
        self,
        input_device_id: int,
        output_device_id: int,
        fmt: AudioFormat,
        pipeline: Pipeline,
    ) -> None:
        self._in = input_device_id
        self._out = output_device_id
        self._fmt = fmt
        self._pipeline = pipeline
        self._stream: sd.Stream | None = None
        self._latency_ms: float = 0.0

    def start(self) -> None:
        self._pipeline.compile(self._fmt)
        self._stream = sd.Stream(
            device=(self._in, self._out),
            samplerate=self._fmt.sample_rate,
            channels=(self._fmt.channels, self._fmt.channels),
            dtype=self._fmt.dtype,
            blocksize=self._fmt.chunk_samples,
            callback=self._callback,
            latency="low",
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _callback(self, indata, outdata, frames, time_info, status) -> None:
        t0 = time.perf_counter()
        outdata[:] = self._pipeline.process(indata.copy())
        self._latency_ms = (time.perf_counter() - t0) * 1000.0

    @property
    def measured_latency_ms(self) -> float:
        return self._latency_ms
